"""Extractor 共享工具：selectors.yaml 加载、HTML 净化、CSS 选择器兜底抽取。"""

from __future__ import annotations

import logging
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

_SELECTORS_YAML = Path(__file__).parent / "selectors.yaml"


@lru_cache(maxsize=1)
def load_selectors() -> dict[str, Any]:
    if not _SELECTORS_YAML.exists():
        return {}
    return yaml.safe_load(_SELECTORS_YAML.read_text(encoding="utf-8")) or {}


def make_soup(html: str) -> BeautifulSoup:
    """优先 lxml，失败回退 html.parser。去除 script/style/nav/header/footer。"""
    try:
        soup = BeautifulSoup(html, "lxml")
    except Exception:  # noqa: BLE001
        soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "nav", "header", "footer", "noscript"]):
        tag.decompose()
    return soup


def select_text(soup: BeautifulSoup, selectors: list[str]) -> str:
    """按 selectors 列表依次尝试，取第一个非空文本。"""
    for sel in selectors or []:
        try:
            el = soup.select_one(sel)
        except Exception:  # noqa: BLE001
            continue
        if el is None:
            continue
        text = el.get_text(" ", strip=True)
        if text:
            return text
    return ""


def select_texts(soup: BeautifulSoup, selectors: list[str]) -> list[str]:
    """每个 selector 取所有匹配的文本，合并去重。"""
    out: list[str] = []
    seen: set[str] = set()
    for sel in selectors or []:
        try:
            for el in soup.select(sel):
                t = el.get_text(" ", strip=True)
                if t and t not in seen:
                    out.append(t)
                    seen.add(t)
        except Exception:  # noqa: BLE001
            continue
    return out


def select_attrs(soup: BeautifulSoup, selectors: list[str], attr: str) -> list[str]:
    """取每个匹配元素的指定属性（常用于 attachment 的 href）。"""
    out: list[str] = []
    for sel in selectors or []:
        try:
            for el in soup.select(sel):
                v = el.get(attr)
                if v:
                    out.append(str(v))
        except Exception:  # noqa: BLE001
            continue
    return out


_TICKET_ID_RE = re.compile(
    r"(BUG|BZ|PLM|TICKET|REQ|STORY|ZT|ZENTAO)[-_ #]*(\d+)",
    re.IGNORECASE,
)


def extract_ticket_id(text: str) -> str:
    """从任意文本中兜底提取 ``BUG-123`` / ``STORY-500`` / ``ZT-9987`` 形式的 id。

    支持 ``Bug #10001`` / ``STORY 500`` / ``ZT_10002`` 多种分隔方式。
    """
    if not text:
        return ""
    m = _TICKET_ID_RE.search(text)
    if not m:
        return text.strip().split()[0] if text.strip() else ""
    prefix = m.group(1).upper()
    
    if prefix == "BZ":
        prefix = "BUG"
    if prefix == "ZENTAO":
        prefix = "ZT"
    return f"{prefix}-{m.group(2)}"


def normalize_severity(raw: str) -> str:
    """将各种别名（P0 / Blocker / Major / High）归一为 ``low|mid|high|critical``。"""
    s = (raw or "").strip().lower()
    if not s:
        return "low"
    if s in {"critical", "blocker", "p0", "urgent", "s1", "crash"}:
        return "critical"
    if s in {"high", "major", "p1", "s2"}:
        return "high"
    if s in {"medium", "mid", "normal", "p2", "s3"}:
        return "mid"
    return "low"


def normalize_status(raw: str) -> str:
    s = (raw or "").strip().lower()
    if not s:
        return "open"
    if any(k in s for k in ("已关闭", "关闭", "closed")):
        return "fixed"
    if any(k in s for k in ("已解决", "已修复", "fixed", "resolved", "done")):
        return "fixed"
    if any(k in s for k in ("激活", "新建", "new", "active", "triage", "unconfirmed", "open", "待办", "待修复", "待处理")):
        return "triage" if "激活" in s or "triage" in s or "unconfirmed" in s else "open"
    return "open"


def normalize_resolution(raw: str) -> str:
    """归一 Bugzilla / 禅道的 resolution 字段到统一枚举。

    输出：``fixed | duplicate | not_repro | by_design | wont_fix | external | postponed | transferred | ""``
    """
    if raw is None:
        return ""
    s = str(raw).strip().lower()
    if not s or s in {"---", "none"}:
        return ""
    mapping = [
        (("fixed", "已解决", "修复", "resolved"), "fixed"),
        (("duplicate", "重复", "重复 bug", "重复问题"), "duplicate"),
        (("not_repro", "无法重现", "无法复现", "worksforme", "works for me", "不能重现"), "not_repro"),
        (("by design", "by_design", "设计如此", "按设计", "设计"), "by_design"),
        (("wontfix", "wont_fix", "won't fix", "不予解决", "不解决"), "wont_fix"),
        (("external", "外部原因", "第三方"), "external"),
        (("postponed", "延期", "推迟"), "postponed"),
        (("转为需求", "transferred", "转需求"), "transferred"),
    ]
    for keys, label in mapping:
        if any(k in s for k in keys):
            return label
    return s


def parse_int(raw: str | int | None, default: int = 0) -> int:
    if raw is None:
        return default
    try:
        return int(str(raw).strip())
    except (TypeError, ValueError):
        return default
