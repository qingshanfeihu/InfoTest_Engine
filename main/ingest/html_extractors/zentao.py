"""禅道（ZenTao）Bug / Story 页面 HTML 抽取器（v1.5.1 扩展字段）。"""

from __future__ import annotations

import hashlib
import re
from typing import Any

from bs4 import BeautifulSoup

from main.ingest.html_extractors._common import (
    extract_ticket_id,
    load_selectors,
    make_soup,
    normalize_resolution,
    normalize_severity,
    normalize_status,
    parse_int,
    select_attrs,
    select_text,
    select_texts,
)
from main.ingest.html_extractors.schema import Attachment, DefectTicket


def _resolve_zentao_cfg() -> dict[str, Any]:
    cfg = load_selectors() or {}
    zt = cfg.get("zentao") or {}
    if not zt and cfg.get("plm", {}).get("alias_of") == "zentao":
        zt = cfg.get("zentao") or {}
    return zt or {}


def select_by_th_label(soup: BeautifulSoup, labels: list[str]) -> str:
    """遍历 th/label/td.w-80px/strong，文本等于 labels 任一 → 取后续 td 的文本。"""
    if not labels:
        return ""
    label_set = {label.strip() for label in labels if label}
    for sel in ("th", "td.w-80px", "label", "strong"):
        for el in soup.select(sel):
            text = el.get_text(" ", strip=True).rstrip("：:")
            if text and text in label_set:
                sib = el.find_next_sibling("td")
                if sib is not None:
                    val = sib.get_text(" ", strip=True)
                    if val:
                        return val
                nxt = el.find_next("td")
                if nxt is not None and nxt is not el:
                    val = nxt.get_text(" ", strip=True)
                    if val:
                        return val
    return ""


def select_all_by_th_label(soup: BeautifulSoup, labels: list[str]) -> list[str]:
    """同上但返回所有匹配项（多值字段）。"""
    out: list[str] = []
    seen: set[str] = set()
    if not labels:
        return out
    label_set = {label.strip() for label in labels if label}
    for el in soup.select("th, td.w-80px, label, strong"):
        text = el.get_text(" ", strip=True).rstrip("：:")
        if text and text in label_set:
            sib = el.find_next_sibling("td")
            if sib is None:
                continue
            items = [li.get_text(" ", strip=True) for li in sib.find_all("li")]
            if not items:
                raw = sib.get_text(" ", strip=True)
                items = [s.strip() for s in re.split(r"[\s,，、;；/]+", raw) if s.strip()]
            for it in items:
                if it and it not in seen:
                    seen.add(it)
                    out.append(it)
    return out


def _zentao_severity_map(raw: str) -> str:
    if not raw:
        return "low"
    s = str(raw).strip()
    m = re.match(r"^(\d)", s)
    if m:
        n = int(m.group(1))
        return {1: "low", 2: "mid", 3: "high", 4: "critical"}.get(n, "low")
    return normalize_severity(s)


def _zentao_status_map(raw: str) -> str:
    s = (raw or "").strip().lower()
    if not s:
        return "open"
    if any(k in s for k in ("已解决", "已关闭", "已修复", "closed", "resolved", "fixed")):
        return "fixed"
    if any(k in s for k in ("激活", "新建", "new", "active", "triage")):
        return "triage"
    return normalize_status(s)


_NUM_RE = re.compile(r"#?(\d{2,6})")

# 禅道失败页面信号
_INVALID_ZENTAO_SIGNALS = [
    "没有匹配的结果",
    "无搜索结果",
    "未找到匹配",
    "no results",
    "您没有访问权限",
    "无访问权限",
    "您无权",
    "page not found",
    "404 - 找不到页面",
    "bug 不存在",
    "需求不存在",
    "story not exist",
]


def _detect_zentao_invalid(soup) -> str:
    body_text = soup.get_text(" ", strip=True).lower()
    for sig in _INVALID_ZENTAO_SIGNALS:
        if sig in body_text:
            return f"zentao_signal:{sig}"
    title_el = soup.find("title")
    if title_el is not None:
        title = title_el.get_text(strip=True).lower()
        if any(t in title for t in ("404", "not found", "无权", "无搜索结果")):
            return f"zentao_title:{title[:60]}"
    # 搜索结果落在 #mainContent 但只有 "我的工作台" / 空表格 → 视为无效
    # (搜索失败时禅道会留在原页面，url 仍是 m=my&f=index)
    return ""


def _extract_id_list(text: str, prefix: str) -> list[str]:
    """从 "相关需求 #500, #501" 或 "相关用例: 1001 1002" 这种文本里提 id 列表。"""
    if not text:
        return []
    out: list[str] = []
    seen: set[str] = set()
    for m in _NUM_RE.finditer(text):
        key = f"{prefix}-{m.group(1)}"
        if key not in seen:
            seen.add(key)
            out.append(key)
    return out


class ZentaoExtractor:
    """禅道 Bug / Story 页面统一抽取器。"""

    backend = "zentao"
    version = "v2"

    def __init__(self, *, doc_type: str = "bug") -> None:
        self.doc_type_hint = doc_type

    def extract(self, html: str) -> DefectTicket:
        if not html:
            return DefectTicket(ticket_id="UNKNOWN", backend=self.backend)

        cfg = _resolve_zentao_cfg()
        self.version = cfg.get("version") or self.version
        soup = make_soup(html)

        invalid_reason = _detect_zentao_invalid(soup)

        th_labels = cfg.get("th_labels") or {}

        raw_id = select_text(soup, cfg.get("ticket_id", []))
        ticket_id = extract_ticket_id(raw_id) or raw_id or "UNKNOWN"

        # 主字段
        title = select_by_th_label(soup, th_labels.get("title", []))
        if not title and raw_id:
            title = re.sub(r"^Bug\s*#?\d+[\s:：]*", "", raw_id).strip() or raw_id

        # 兜底：如果信号词没命中，但解析后 ticket_id=UNKNOWN 且 title 也空，
        # 说明这页不是真正的详情页（很可能是 PLM dashboard / 搜索回首页）。
        # 标 invalid_reason 让 chain 知道要 fallthrough。
        if not invalid_reason and ticket_id == "UNKNOWN" and not title:
            invalid_reason = "zentao_no_detail_data"

        product = select_by_th_label(soup, th_labels.get("product", []))
        module = select_by_th_label(soup, th_labels.get("module", []))
        severity_raw = select_by_th_label(soup, th_labels.get("severity", []))
        severity = _zentao_severity_map(severity_raw)
        priority = select_by_th_label(soup, th_labels.get("priority", []))
        status_raw = select_by_th_label(soup, th_labels.get("status", []))
        status = _zentao_status_map(status_raw)
        resolution = normalize_resolution(select_by_th_label(soup, th_labels.get("resolution", [])))

        description = select_by_th_label(soup, th_labels.get("description", []))
        if not description:
            description = select_text(soup, cfg.get("description_blocks", []))
        steps = select_by_th_label(soup, th_labels.get("steps_to_reproduce", []))
        fix_summary = select_by_th_label(soup, th_labels.get("fix_summary", []))

        # 时间/人员
        reported_by = select_by_th_label(soup, th_labels.get("reported_by", []))
        reported_at = select_by_th_label(soup, th_labels.get("reported_at", []))
        resolved_by = select_by_th_label(soup, th_labels.get("resolved_by", []))
        resolved_at = select_by_th_label(soup, th_labels.get("resolved_at", []))

        # 版本
        affected = select_all_by_th_label(soup, th_labels.get("affected_versions", []))
        fixed_versions = select_all_by_th_label(soup, th_labels.get("fixed_versions", []))
        fixed_commit = select_by_th_label(soup, th_labels.get("fixed_commit", []))

        # 关联
        related_story = select_by_th_label(soup, th_labels.get("related_story", []))
        related_case = select_by_th_label(soup, th_labels.get("related_case_ids", []))
        related_task = select_by_th_label(soup, th_labels.get("related_task_ids", []))
        related_bug = select_by_th_label(soup, th_labels.get("related_bug_ids", []))

        related_story_ids = _extract_id_list(related_story, "STORY")
        related_case_ids = _extract_id_list(related_case, "TC")
        related_task_ids = _extract_id_list(related_task, "TASK")
        related_bug_ids = _extract_id_list(related_bug, "ZT")

        # 相关 feature：story 的 id 即是上游 feature 候选
        related_feature_ids: list[str] = []
        for sid in related_story_ids:
            m = _NUM_RE.search(sid)
            if m:
                related_feature_ids.append(m.group(1))

        # 激活次数
        activated_raw = select_by_th_label(soup, th_labels.get("activated_count", []))
        activated_count = parse_int(activated_raw, 0)

        # 附件
        attachment_urls = select_attrs(soup, cfg.get("attachments", []), "href")
        attachment_names = select_texts(soup, cfg.get("attachments", []))
        attachments = [
            Attachment(url=url, filename=attachment_names[i] if i < len(attachment_names) else "")
            for i, url in enumerate(attachment_urls)
        ]

        # doc_type
        doc_type = self.doc_type_hint or "bug"
        if ticket_id.upper().startswith(("STORY", "REQ", "PLM")):
            doc_type = "plm_ticket"

        html_sha = hashlib.sha256(html.encode("utf-8", errors="ignore")).hexdigest()[:16]

        return DefectTicket(
            ticket_id=ticket_id,
            title=title,
            product=product,
            module=module,
            severity=severity,
            priority=priority,
            status=status,
            resolution=resolution,
            description=description,
            steps_to_reproduce=steps,
            fix_summary=fix_summary,
            reported_by=reported_by,
            reported_at=reported_at,
            resolved_by=resolved_by,
            resolved_at=resolved_at,
            affected_versions=affected,
            fixed_versions=fixed_versions,
            fixed_commit=fixed_commit,
            related_feature_ids=related_feature_ids,
            related_case_ids=related_case_ids,
            related_story_ids=related_story_ids,
            related_task_ids=related_task_ids,
            related_bug_ids=related_bug_ids,
            activated_count=activated_count,
            attachments=attachments,
            backend=self.backend,
            doc_type=doc_type,
            html_sha256=html_sha,
            invalid_reason=invalid_reason,
        )


class ZentaoStoryExtractor(ZentaoExtractor):
    """禅道需求页面；默认 doc_type=plm_ticket。"""

    def __init__(self) -> None:
        super().__init__(doc_type="plm_ticket")
