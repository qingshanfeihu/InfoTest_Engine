"""``web_bug_search`` agent tool — bug ticket 检索（本地优先，远端兜底）。

设计参考 Anthropic ``web_search`` 范式：

- 单一同步工具：模型调用一次拿到结构化结果，自己写答复（与 ``web_search`` 完全一致）
- 本地优先：先 grep ``workspace/defects/{backend}/``；命中即返回，零网络开销
- 远端兜底：本地 miss 时通过 Playwright + WebVPN 抓 Bugzilla / 禅道（30-60s 阻塞）
- 自动落盘：远端抓回的 ticket 立即解析 + 写入 ``workspace/defects/`` 最终位置
- 后续命中：再次查询同一 id 直接走本地，无需再跑 Playwright
- 自动登录续期：cookie 透明续期分两层兜底——
    L1（内置）：``defect_fetch.fetch_one_sync`` 在每次抓取时先用当前 cookie 试，
              失败就调 ``ensure_portal_logged_in`` 用账号密码 + 验证码 OCR 自动续期；
    L2（外置）：L1 失败时（如账号密码错 / WebVPN 异常）才返 ``login_required``，
              本工具再调一次 ``refresh_login_sync`` 续期 + 重试 1 次
- 失败结构化：抓取失败/未找到时返回 ``{status, error_code, ticket_id}``，对齐 ``web_search`` 的 error_code

backend 自动识别（按 ticket_id 前缀）：
    BUG-*    → bugzilla
    ZT-*     → zentao
    STORY-*  → zentao_story
    PLM-*    → plm

落盘位置：
    raw HTML  : knowledge/.intermediate/defect_raw/{backend}/{id}.html  （agent 不可见）
    cleaned   : workspace/defects/{backend}/{id}.json                   （agent 可见，下次自动 cache 命中）

不做的事（与 web_search 哲学一致）：
- 不做 ``check_status`` 轮询（同步阻塞）
- 不做 ``fetch_async`` / job_id（``TaskOutput`` 已弃用）
- 不做 Qdrant 索引（grep 在几百到几千 ticket 量级足够）
- 不主动开放 ``--refresh-login`` 子命令给用户（cookie 失效已被自动续期；账号密码异常时返回 login_required 让 agent 提示用户检查 environment）
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

from langchain_core.tools import tool

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# backend detection
# ---------------------------------------------------------------------------


_BACKEND_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"^BUG-\d+$",   re.IGNORECASE), "bugzilla"),
    (re.compile(r"^ZT-\d+$",    re.IGNORECASE), "zentao"),
    (re.compile(r"^STORY-\d+$", re.IGNORECASE), "zentao_story"),
    (re.compile(r"^PLM-\d+$",   re.IGNORECASE), "plm"),
]


def _detect_backend(ticket_id: str) -> str | None:
    """根据 ticket_id 前缀识别 backend，并归一化到 fetch_one_sync 用的 canonical 名。

    PLM-* 在 legacy ingest 里走 zentao backend（PLM 是禅道的统一入口），
    所以这里直接归一化，避免 lookup / parse 阶段路径错位。
    """
    tid = (ticket_id or "").strip()
    raw = None
    for pat, backend in _BACKEND_PATTERNS:
        if pat.match(tid):
            raw = backend
            break
    if raw is None:
        return None
    try:
        from main.ingest.defect_fetch import _canonical_backend  # type: ignore[attr-defined]
        return _canonical_backend(raw)
    except Exception:  # noqa: BLE001
        return raw


# ---------------------------------------------------------------------------
# local kb lookup
# ---------------------------------------------------------------------------


def _local_lookup(ticket_id: str, backend: str) -> dict[str, Any] | None:
    """查 ``workspace/defects/{backend}/{ticket_id}.json``。

    PLM-* / ZT-* / BUG-* 共享禅道 backend——禅道详情页存的是数字 id，parser 落盘
    时按 ``BUG-{n}`` 命名。所以查 PLM-115998 时也要尝试 BUG-115998.json / ZT-115998.json。
    """
    from main.knowledge_paths import WORKSPACE_DEFECTS

    tid = (ticket_id or "").strip()
    candidates: list[Path] = [
        WORKSPACE_DEFECTS / backend / f"{tid}.json",
        WORKSPACE_DEFECTS / backend / f"{tid.upper()}.json",
    ]
    # 把数字部分剥出来，尝试同 backend 下的 BUG-/ZT-/STORY-/PLM- 别名
    m = re.match(r"^([A-Z]+)-(\d+)$", tid.upper())
    if m:
        digits = m.group(2)
        for prefix in ("BUG", "ZT", "STORY", "PLM"):
            alias = f"{prefix}-{digits}.json"
            candidates.append(WORKSPACE_DEFECTS / backend / alias)

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


def _summarize_ticket(ticket: dict[str, Any], *, source: str) -> dict[str, Any]:
    """把 cleaned ticket JSON 收敛成 agent 友好的 dict。

    完整 ticket 可能含 14 条 comments；agent 主对话只需要核心字段，
    需要详情时再 read_file 完整 JSON。
    """
    md = ticket.get("metadata", {}) or {}
    return {
        "source":           source,
        "ticket_id":        ticket.get("ticket_id"),
        "title":            ticket.get("title"),
        "fix_summary":      ticket.get("fix_summary"),
        "description":      (ticket.get("description") or "")[:1500],
        "steps_to_reproduce": (ticket.get("steps_to_reproduce") or "")[:800],
        "metadata": {
            "module":             md.get("module"),
            "product":            md.get("product"),
            "severity":           md.get("severity"),
            "status":             md.get("status"),
            "resolution":         md.get("resolution"),
            "affected_versions":  md.get("affected_versions"),
            "fixed_versions":     md.get("fixed_versions"),
            "fixed_commit":       md.get("fixed_commit"),
            "related_feature_ids": md.get("related_feature_ids"),
            "comments_count":     md.get("comments_count"),
            "backend":            md.get("backend"),
        },
    }


# ---------------------------------------------------------------------------
# remote fetch + parse
# ---------------------------------------------------------------------------


def _remote_fetch_and_parse(ticket_id: str, backend: str, *, _retry_after_login: bool = False) -> dict[str, Any]:
    """跑 Playwright 抓 + 解析。

    Cookie 失效（``login_required``）时**自动跑一次 ``refresh_login_sync``** 续期，
    成功后递归重试一次抓取（``_retry_after_login=True`` 防止死循环）。

    返回 ticket JSON 或 ``{"_error": ..., "_error_code": ...}``。
    """
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
        # 区分常见错误类型：login_required / not_found / unavailable
        # error 字段来自 fetch_one_sync，可能是：
        #   login_expired / fetch_timeout / no_fetch / system_exit_* / subprocess_failed
        code = "fetch_failed"
        low = err.lower()
        if "login" in low or "captcha" in low or "expired" in low:
            code = "login_required"
        elif "not found" in low or "404" in low or "not_found" in low:
            code = "not_found"
        elif "timeout" in low:
            code = "timeout"

        # 自动 refresh_login + 重试一次（仅 login_required 触发，且只重试一次）
        if code == "login_required" and not _retry_after_login:
            logger.info(
                "web_bug_search: cookie expired for %s, auto-refreshing login ...",
                backend,
            )
            ok = refresh_login_sync(backend)
            if ok:
                logger.info("web_bug_search: login refreshed, retrying fetch ...")
                return _remote_fetch_and_parse(ticket_id, backend, _retry_after_login=True)
            logger.warning(
                "web_bug_search: refresh_login_sync(%s) failed; returning login_required",
                backend,
            )

        return {
            "_error": err,
            "_error_code": code,
            "_raw_path": fetch_result.get("raw_path"),
        }

    # 抓回了 HTML，跑解析
    try:
        parse_backend(backend)
    except Exception as exc:  # noqa: BLE001
        return {
            "_error": f"parse failed: {exc}",
            "_error_code": "parse_failed",
        }

    # 解析后再读 cleaned JSON
    ticket = _local_lookup(ticket_id, backend)
    if ticket is None:
        # 远端返回了页面但解析后没产出指定 id 的 JSON——典型场景是 bugzilla 对
        # 不存在的 id 返回 "no such bug" 占位页，被 parser 落成 UNKNOWN.json。
        # 当成 not_found 处理；同时清掉 UNKNOWN.json 避免污染本地 KB。
        from main.knowledge_paths import WORKSPACE_DEFECTS
        unknown = WORKSPACE_DEFECTS / backend / "UNKNOWN.json"
        if unknown.exists():
            try:
                unknown.unlink()
            except Exception:  # noqa: BLE001
                pass
        return {
            "_error": f"remote returned page but no ticket {ticket_id} parsed (likely not_found)",
            "_error_code": "not_found",
        }
    return ticket


# ---------------------------------------------------------------------------
# the tool
# ---------------------------------------------------------------------------


@tool("web_bug_search")
def web_bug_search(ticket_id: str) -> dict[str, Any]:
    """按 ticket id 检索 bug / story 详情（本地优先，远端兜底）。

    支持 backend 自动识别（按前缀）：
      BUG-*    → bugzilla
      ZT-*     → zentao
      STORY-*  → zentao_story
      PLM-*    → plm

    返回结构化 dict，含 title / description / fix_summary / metadata（含 status /
    affected_versions / fixed_versions / fixed_commit / related_feature_ids 等）。
    本地命中秒级；远端抓取需要 30-60 秒（Playwright + WebVPN 登录）。

    失败时返回 ``{status: "error", error_code, ticket_id}``：
      - login_required: 自动 refresh_login + 重试 1 次后仍失败（如账号密码错 / WebVPN 异常）
      - not_found     : 远端确实没这个 id（bugzilla 返回 no-such-bug 占位页）
      - parse_failed  : HTML 抓回但解析失败
      - ingest_unavailable: defect_fetch 模块未安装
      - unknown_backend: ticket_id 前缀无法识别 backend
    """
    tid = (ticket_id or "").strip()
    if not tid:
        return {"status": "error", "error_code": "invalid_input",
                "reason": "empty ticket_id"}

    backend = _detect_backend(tid)
    if backend is None:
        return {
            "status": "error",
            "error_code": "unknown_backend",
            "ticket_id": tid,
            "reason": "ticket_id prefix must be BUG-* / ZT-* / STORY-* / PLM-*",
        }

    # 1) 本地优先
    local = _local_lookup(tid, backend)
    if local is not None:
        return {"status": "ok", **_summarize_ticket(local, source="local_kb")}

    # 2) 远端兜底（同步阻塞 30-60s）
    logger.info("web_bug_search: %s not in local kb, fetching from %s ...", tid, backend)
    remote = _remote_fetch_and_parse(tid, backend)
    if "_error" in remote:
        return {
            "status": "error",
            "error_code": remote.get("_error_code", "fetch_failed"),
            "ticket_id": tid,
            "backend": backend,
            "reason": remote["_error"],
        }
    return {"status": "ok", **_summarize_ticket(remote, source="remote_fetch")}
