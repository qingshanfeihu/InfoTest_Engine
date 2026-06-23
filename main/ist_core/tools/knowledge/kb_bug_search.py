"""``kb_bug_search`` agent tool — bug ticket 检索（本地优先，远端兜底）。

设计参考 Anthropic ``web_search`` 范式：

- 单一同步工具：模型调用一次拿到结构化结果，自己写答复（与 ``web_search`` 完全一致）
- **全平台探测**：不按 ticket_id 前缀猜平台；对 bugzilla / zentao（缺陷）/ zentao_story（需求）
  分别查询，由实际命中结果判断归属；多平台同 id 时全部返回
- 本地优先：先查 ``workspace/defects/{backend}/``；命中即返回，零网络开销
- 远端兜底：本地 miss 时通过 Playwright + WebVPN 抓 Bugzilla / 禅道（每平台 30-60s 阻塞）
- 自动落盘：远端抓回的 ticket 立即解析 + 写入 ``workspace/defects/`` 最终位置
- 后续命中：再次查询同一 id 直接走本地，无需再跑 Playwright
- 自动登录续期：cookie 透明续期分两层兜底（见 ``_remote_fetch_and_parse``）

落盘位置：
    raw HTML  : knowledge/.intermediate/defect_raw/{backend}/{id}.html  （agent 不可见）
    cleaned   : workspace/defects/{backend}/{id}.json                   （agent 可见，下次自动 cache 命中）
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

from langchain_core.tools import tool

logger = logging.getLogger(__name__)


_PROBE_BACKENDS: tuple[str, ...] = ("bugzilla", "zentao", "zentao_story")

_DIGITS_ONLY_RE = re.compile(r"^\d+$")
_TICKET_PREFIX_RE = re.compile(r"^([A-Z]+)-(\d+)$", re.IGNORECASE)


def _extract_numeric_id(ticket_id: str) -> str | None:
    """从 ``12345`` / ``BUG-12345`` / ``#12345`` 等输入提取数字 id。"""
    tid = (ticket_id or "").strip()
    if not tid:
        return None
    if _DIGITS_ONLY_RE.match(tid):
        return tid
    try:
        from main.ingest._capture_session import _strip_bug_prefix  # noqa: PLC2701

        stripped = _strip_bug_prefix(tid)
        if stripped and _DIGITS_ONLY_RE.match(stripped):
            return stripped
    except Exception:  # noqa: BLE001
        pass
    m = _TICKET_PREFIX_RE.match(tid.upper())
    if m:
        return m.group(2)
    m2 = re.search(r"(\d{3,})", tid)
    return m2.group(1) if m2 else None


def _candidate_ticket_ids(ticket_id: str) -> list[str]:
    """生成本地查找用的 ticket_id 候选（原样 + 常见前缀别名）。"""
    tid = (ticket_id or "").strip()
    if not tid:
        return []
    out: list[str] = []
    seen: set[str] = set()

    def add(x: str) -> None:
        k = x.upper()
        if k not in seen:
            seen.add(k)
            out.append(x)

    add(tid)
    digits = _extract_numeric_id(tid)
    if digits:
        for prefix in ("BUG", "ZT", "PLM", "STORY"):
            add(f"{prefix}-{digits}")
        if digits != tid:
            add(digits)
    return out


def _canonical_probe_backend(backend: str) -> str:
    try:
        from main.ingest.defect_fetch import _canonical_backend  # type: ignore[attr-defined]

        return _canonical_backend(backend)
    except Exception:  # noqa: BLE001
        return backend







def _local_lookup(ticket_id: str, backend: str) -> dict[str, Any] | None:
    """查 ``workspace/defects/{backend}/{ticket_id}.json``（含前缀别名）。"""
    from main.knowledge_paths import WORKSPACE_DEFECTS

    canonical = _canonical_probe_backend(backend)
    dirs_to_try = [canonical]
    if canonical != backend:
        dirs_to_try.append(backend)

    candidates: list[Path] = []
    for b in dirs_to_try:
        for tid in _candidate_ticket_ids(ticket_id):
            candidates.append(WORKSPACE_DEFECTS / b / f"{tid}.json")
            candidates.append(WORKSPACE_DEFECTS / b / f"{tid.upper()}.json")

    seen: set[Path] = set()
    for path in candidates:
        if path in seen:
            continue
        seen.add(path)
        if path.exists():
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except Exception as exc:  # noqa: BLE001
                logger.warning("local defect %s unreadable: %s", path, exc)
    return None


def _summarize_ticket(
    ticket: dict[str, Any],
    *,
    source: str,
    probe_backend: str,
) -> dict[str, Any]:
    """把 cleaned ticket JSON 收敛成 agent 友好的 dict。"""
    md = ticket.get("metadata", {}) or {}
    resolved_backend = md.get("backend") or probe_backend
    return {
        "source": source,
        "probe_backend": probe_backend,
        "backend": resolved_backend,
        "ticket_id": ticket.get("ticket_id"),
        "title": ticket.get("title"),
        "fix_summary": ticket.get("fix_summary"),
        "description": (ticket.get("description") or "")[:1500],
        "steps_to_reproduce": (ticket.get("steps_to_reproduce") or "")[:800],
        "metadata": {
            "module": md.get("module"),
            "product": md.get("product"),
            "severity": md.get("severity"),
            "status": md.get("status"),
            "resolution": md.get("resolution"),
            "affected_versions": md.get("affected_versions"),
            "fixed_versions": md.get("fixed_versions"),
            "fixed_commit": md.get("fixed_commit"),
            "related_feature_ids": md.get("related_feature_ids"),
            "comments_count": md.get("comments_count"),
            "backend": resolved_backend,
        },
    }







def _remote_fetch_and_parse(
    ticket_id: str,
    backend: str,
    *,
    _retry_after_login: bool = False,
) -> dict[str, Any]:
    """跑 Playwright 抓 + 解析。返回 ticket JSON 或 ``{"_error": ..., "_error_code": ...}``。"""
    try:
        from main.ingest.defect_fetch import fetch_one_sync, refresh_login_sync
        from main.ingest.defect_parse import parse_backend
    except ImportError as exc:
        return {
            "_error": f"defect ingest not available: {exc}",
            "_error_code": "ingest_unavailable",
        }

    fetch_result = fetch_one_sync(ticket_id, backend)
    if not fetch_result.get("ok"):
        err = fetch_result.get("error") or "unknown"
        code = "fetch_failed"
        low = err.lower()
        if "login" in low or "captcha" in low or "expired" in low:
            code = "login_required"
        elif "not found" in low or "404" in low or "not_found" in low:
            code = "not_found"
        elif "timeout" in low:
            code = "timeout"

        if code == "login_required" and not _retry_after_login:
            logger.info(
                "kb_bug_search: cookie expired for %s, auto-refreshing login ...",
                backend,
            )
            ok = refresh_login_sync(backend)
            if ok:
                logger.info("kb_bug_search: login refreshed, retrying fetch ...")
                return _remote_fetch_and_parse(
                    ticket_id, backend, _retry_after_login=True
                )
            logger.warning(
                "kb_bug_search: refresh_login_sync(%s) failed; returning login_required",
                backend,
            )

        return {
            "_error": err,
            "_error_code": code,
            "_raw_path": fetch_result.get("raw_path"),
        }

    try:
        parse_backend(backend)
    except Exception as exc:  # noqa: BLE001
        return {
            "_error": f"parse failed: {exc}",
            "_error_code": "parse_failed",
        }

    ticket = _local_lookup(ticket_id, backend)
    if ticket is None:
        from main.knowledge_paths import WORKSPACE_DEFECTS

        canonical = _canonical_probe_backend(backend)
        unknown = WORKSPACE_DEFECTS / canonical / "UNKNOWN.json"
        if unknown.exists():
            try:
                unknown.unlink()
            except Exception:  # noqa: BLE001
                pass
        return {
            "_error": (
                f"remote returned page but no ticket {ticket_id} parsed (likely not_found)"
            ),
            "_error_code": "not_found",
        }
    return ticket


def _fetch_id_for_probe(ticket_id: str, probe_backend: str) -> str:
    """各平台抓取时使用的 ticket_id（保留用户原样；无数字则原样）。"""
    tid = (ticket_id or "").strip()
    digits = _extract_numeric_id(tid)
    if not digits:
        return tid
    if probe_backend == "zentao_story":
        return f"STORY-{digits}"
    if probe_backend == "zentao":
        return f"PLM-{digits}"
    if probe_backend == "bugzilla":
        return f"BUG-{digits}"
    return tid


def _probe_one_backend(
    ticket_id: str,
    probe_backend: str,
    *,
    allow_remote: bool,
) -> dict[str, Any]:
    """单平台探测：本地 → 可选远端。返回 hit 摘要或 error 记录。"""
    fetch_id = _fetch_id_for_probe(ticket_id, probe_backend)

    local = _local_lookup(fetch_id, probe_backend)
    if local is None:
        local = _local_lookup(ticket_id, probe_backend)
    if local is not None:
        return {
            "outcome": "hit",
            **_summarize_ticket(
                local, source="local_kb", probe_backend=probe_backend
            ),
        }

    if not allow_remote:
        return {
            "outcome": "miss",
            "probe_backend": probe_backend,
            "error_code": "not_found",
            "reason": "not in local kb (remote skipped)",
        }

    logger.info(
        "kb_bug_search: %s not in local kb, fetching from %s ...",
        fetch_id,
        probe_backend,
    )
    remote = _remote_fetch_and_parse(fetch_id, probe_backend)
    if "_error" in remote:
        return {
            "outcome": "miss",
            "probe_backend": probe_backend,
            "error_code": remote.get("_error_code", "fetch_failed"),
            "reason": remote["_error"],
        }
    return {
        "outcome": "hit",
        **_summarize_ticket(
            remote, source="remote_fetch", probe_backend=probe_backend
        ),
    }


def _dedupe_hits(hits: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[str, str]] = set()
    out: list[dict[str, Any]] = []
    for h in hits:
        key = (
            str(h.get("probe_backend") or ""),
            str(h.get("ticket_id") or "").upper(),
        )
        if key in seen:
            continue
        seen.add(key)
        out.append(h)
    return out


def _merge_single_hit_compat(
    hits: list[dict[str, Any]],
    query: str,
    platform_errors: list[dict[str, Any]],
) -> dict[str, Any]:
    """单条命中时扁平化字段，兼容旧消费方（test-list-review 等）。"""
    one = hits[0]
    merged: dict[str, Any] = {
        "status": "ok",
        "query": query,
        "hits_count": 1,
        "results": hits,
        "platform_errors": platform_errors,
    }
    for k, v in one.items():
        if k not in ("outcome",):
            merged[k] = v
    return merged







@tool("kb_bug_search")
def kb_bug_search(ticket_id: str) -> dict[str, Any]:
    """按 ticket id 在全缺陷平台检索详情（本地优先，远端兜底）。

    **不按前缀猜平台**：对 bugzilla、zentao（PLM 缺陷搜索）、zentao_story（需求）
    分别查询。输入可以是 ``12345``、``BUG-12345``、``PLM-12345`` 等任意常见形式。

    返回：
    - 单平台命中：扁平字段（title / description / metadata / backend …）+ ``results`` 数组
    - 多平台同 id 均存在：``hits_count`` > 1，``results`` 含全部命中，由 agent 根据内容判断
    - 全未命中：``status: error``，``error_code: not_found``，``platform_errors`` 列出各平台原因

    远端抓取每平台约 30-60s；多平台串行可能较慢。
    """
    tid = (ticket_id or "").strip()
    if not tid:
        return {
            "status": "error",
            "error_code": "invalid_input",
            "reason": "empty ticket_id",
        }

    if _extract_numeric_id(tid) is None and not _TICKET_PREFIX_RE.match(tid):
        return {
            "status": "error",
            "error_code": "invalid_input",
            "ticket_id": tid,
            "reason": "ticket_id must contain a numeric bug/story id",
        }

    hits: list[dict[str, Any]] = []
    platform_errors: list[dict[str, Any]] = []

    for probe_backend in _PROBE_BACKENDS:
        row = _probe_one_backend(tid, probe_backend, allow_remote=True)
        if row.get("outcome") == "hit":
            hits.append({k: v for k, v in row.items() if k != "outcome"})
        else:
            platform_errors.append(
                {
                    "probe_backend": row.get("probe_backend", probe_backend),
                    "error_code": row.get("error_code", "not_found"),
                    "reason": row.get("reason", ""),
                }
            )

    hits = _dedupe_hits(hits)

    if not hits:
        
        codes = {e.get("error_code") for e in platform_errors}
        top_code = "not_found"
        if "login_required" in codes:
            top_code = "login_required"
        elif "ingest_unavailable" in codes:
            top_code = "ingest_unavailable"
        return {
            "status": "error",
            "error_code": top_code,
            "ticket_id": tid,
            "query": tid,
            "platform_errors": platform_errors,
            "reason": (
                "no ticket found on any platform (bugzilla / zentao / zentao_story)"
            ),
        }

    if len(hits) == 1:
        return _merge_single_hit_compat(hits, tid, platform_errors)

    return {
        "status": "ok",
        "query": tid,
        "hits_count": len(hits),
        "multi_platform": True,
        "results": hits,
        "platform_errors": platform_errors,
        
        **{k: v for k, v in hits[0].items() if k not in ("status",)},
    }
