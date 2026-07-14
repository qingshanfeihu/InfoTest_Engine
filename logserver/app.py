"""LogServer — 审计日志查询独立 FastAPI 微服务。

端口 8081，与 web_server.py（8080）完全解耦。
所有端点仅 superadmin 可访问。
"""

from __future__ import annotations

import csv
import io
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse

# 确保项目根在 sys.path
_PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from main.ist_core.auth.db import pg_cursor

logger = logging.getLogger("logserver")

app = FastAPI(title="LogServer 审计查询服务", version="1.0.0")


@app.on_event("startup")
def _on_startup():
    """启动时确保数据库 schema 存在。"""
    try:
        from main.ist_core.auth.db import ensure_schema
        ensure_schema()
        logger.info("ensure_schema OK")
    except Exception as exc:
        logger.warning("ensure_schema 失败: %s", exc)


@app.exception_handler(Exception)
async def _global_exception_handler(request: Request, exc: Exception):
    """全局异常兜底：返回 JSON 而非 HTML 500 页面。"""
    logger.error("未捕获异常 %s %s: %s", request.method, request.url.path, exc, exc_info=True)
    return JSONResponse(status_code=500, content={"detail": f"服务器内部错误: {type(exc).__name__}: {exc}"})


# ---------------------------------------------------------------------------
# 认证依赖
# ---------------------------------------------------------------------------


def _require_superadmin(token: str) -> dict:
    """仅凭 JWT token 校验 superadmin 身份。不依赖 session_id。"""
    if not token:
        raise HTTPException(401, "缺少 token")
    from main.ist_core.auth.jwt_handler import decode_access_token
    payload = decode_access_token(token)
    if payload is None:
        raise HTTPException(401, "token 无效或已过期")
    if payload.get("role") != "superadmin":
        raise HTTPException(403, "仅超级管理员可访问")
    return {"username": payload["sub"], "role": payload["role"]}


def _auth(request: Request) -> dict:
    """从 query 参数提取并校验 superadmin。"""
    return _require_superadmin(request.query_params.get("token", ""))


# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------


def _parse_dt(s: str | None) -> datetime | None:
    """解析 ISO 时间字符串为 aware datetime。"""
    if not s:
        return None
    try:
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None


def _serialize_row(row: dict) -> dict:
    """将 PG row 中的 datetime / Decimal 转为可 JSON 序列化的类型。"""
    out = {}
    for k, v in row.items():
        if isinstance(v, datetime):
            out[k] = v.isoformat()
        elif hasattr(v, "as_integer_ratio"):
            out[k] = float(v)
        else:
            out[k] = v
    return out


def _build_where(conditions: list[tuple[str, str, object]]) -> tuple[str, dict]:
    """动态构建 WHERE 子句，避免 psycopg3 参数类型歧义。

    Args:
        conditions: [(sql_fragment, param_name, value), ...]
            sql_fragment 示例: "a.event_kind = %(event_kind)s"
            value 为 None 时跳过该条件。

    Returns:
        (where_sql, params_dict)。无条件时返回 ("1=1", {})。
    """
    parts = []
    params = {}
    for sql_frag, name, val in conditions:
        if val is None:
            continue
        parts.append(sql_frag)
        params[name] = val
    where = " AND ".join(parts) if parts else "1=1"
    return where, params


# ===========================================================================
# 1. 审计日志查询
# ===========================================================================


@app.get("/api/audit/logs")
async def audit_logs(
    request: Request,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    event_kind: Optional[str] = None,
    username: Optional[str] = None,
    session_id: Optional[str] = None,
    conversation_id: Optional[str] = None,
    run_id: Optional[str] = None,
    tool_name: Optional[str] = None,
    is_error: Optional[bool] = None,
    start_time: Optional[str] = None,
    end_time: Optional[str] = None,
):
    """分页查询审计日志。"""
    _auth(request)
    st = _parse_dt(start_time)
    et = _parse_dt(end_time)
    offset = (page - 1) * page_size

    where_sql, params = _build_where([
        ("a.event_kind = %(event_kind)s", "event_kind", event_kind),
        ("u.username = %(username)s", "username", username),
        ("a.session_id = %(session_id)s", "session_id", session_id),
        ("a.conversation_id = %(conversation_id)s", "conversation_id", conversation_id),
        ("a.run_id = %(run_id)s", "run_id", run_id),
        ("a.tool_name = %(tool_name)s", "tool_name", tool_name),
        ("a.is_error = %(is_error)s", "is_error", is_error),
        ("a.recorded_at >= %(start_time)s", "start_time", st),
        ("a.recorded_at <= %(end_time)s", "end_time", et),
    ])
    params["page_size"] = page_size
    params["offset"] = offset

    with pg_cursor() as cur:
        cur.execute(
            f"""SELECT count(*) AS total
                FROM ist_audit.audit_log a
                LEFT JOIN ist_audit.users u ON a.user_id = u.id
                WHERE {where_sql}""",
            params,
        )
        total = cur.fetchone()["total"]

        cur.execute(
            f"""SELECT a.id, u.username, u.role,
                       a.session_id, a.conversation_id, a.run_id, a.thread_id,
                       a.recorded_at, a.event_kind, a.event_summary,
                       a.model_name,
                       a.token_input, a.token_output,
                       a.token_cache_hit, a.token_cache_miss,
                       a.tool_name, a.tool_duration_ms,
                       a.file_path, a.file_operation,
                       a.source_ip, a.is_error, a.error_message
                FROM ist_audit.audit_log a
                LEFT JOIN ist_audit.users u ON a.user_id = u.id
                WHERE {where_sql}
                ORDER BY a.recorded_at DESC
                LIMIT %(page_size)s OFFSET %(offset)s""",
            params,
        )
        items = [_serialize_row(r) for r in cur.fetchall()]

    return {"total": total, "page": page, "page_size": page_size, "items": items}


@app.get("/api/audit/logs/{log_id}")
async def audit_log_detail(log_id: int, request: Request):
    """单条日志详情（含 payload / tool_input / tool_output / tags）。"""
    _auth(request)
    with pg_cursor() as cur:
        cur.execute(
            """SELECT a.*, u.username, u.role
               FROM ist_audit.audit_log a
               LEFT JOIN ist_audit.users u ON a.user_id = u.id
               WHERE a.id = %s""",
            (log_id,),
        )
        row = cur.fetchone()
    if not row:
        raise HTTPException(404, "日志不存在")
    return _serialize_row(row)


@app.get("/api/audit/logs/trace/{trace_session_id}")
async def audit_trace(
    trace_session_id: str,
    request: Request,
    limit: int = Query(500, ge=1, le=2000),
):
    """会话全链路追踪。按 recorded_at ASC 排序。"""
    _auth(request)
    with pg_cursor() as cur:
        cur.execute(
            """SELECT a.id, u.username, a.session_id, a.run_id, a.thread_id,
                      a.recorded_at, a.event_kind, a.event_summary,
                      a.model_name, a.tool_name, a.tool_duration_ms,
                      a.is_error, a.error_message
               FROM ist_audit.audit_log a
               LEFT JOIN ist_audit.users u ON a.user_id = u.id
               WHERE a.session_id = %s
               ORDER BY a.recorded_at ASC
               LIMIT %s""",
            (trace_session_id, limit),
        )
        items = [_serialize_row(r) for r in cur.fetchall()]
    return {"session_id": trace_session_id, "count": len(items), "items": items}


@app.get("/api/audit/logs/export")
async def audit_export(
    request: Request,
    event_kind: Optional[str] = None,
    username: Optional[str] = None,
    session_id: Optional[str] = None,
    conversation_id: Optional[str] = None,
    run_id: Optional[str] = None,
    tool_name: Optional[str] = None,
    is_error: Optional[bool] = None,
    start_time: Optional[str] = None,
    end_time: Optional[str] = None,
):
    """CSV 导出审计日志（流式）。"""
    _auth(request)
    st = _parse_dt(start_time)
    et = _parse_dt(end_time)

    where_sql, params = _build_where([
        ("a.event_kind = %(event_kind)s", "event_kind", event_kind),
        ("u.username = %(username)s", "username", username),
        ("a.session_id = %(session_id)s", "session_id", session_id),
        ("a.conversation_id = %(conversation_id)s", "conversation_id", conversation_id),
        ("a.run_id = %(run_id)s", "run_id", run_id),
        ("a.tool_name = %(tool_name)s", "tool_name", tool_name),
        ("a.is_error = %(is_error)s", "is_error", is_error),
        ("a.recorded_at >= %(start_time)s", "start_time", st),
        ("a.recorded_at <= %(end_time)s", "end_time", et),
    ])

    def _generate():
        buf = io.StringIO()
        writer = csv.writer(buf)
        header = [
            "id", "username", "role", "session_id", "conversation_id", "run_id", "thread_id",
            "recorded_at", "event_kind", "event_summary", "model_name",
            "token_input", "token_output", "token_cache_hit", "token_cache_miss",
            "tool_name", "tool_duration_ms", "file_path", "file_operation",
            "source_ip", "is_error", "error_message",
        ]
        writer.writerow(header)
        yield buf.getvalue()
        buf.seek(0)
        buf.truncate(0)

        conn = None
        try:
            from main.ist_core.auth.db import get_pg_connection
            conn = get_pg_connection()
            with conn.cursor(name="audit_export_cursor") as cur:
                cur.itersize = 500
                cur.execute(
                    f"""SELECT a.id, u.username, u.role,
                               a.session_id, a.conversation_id, a.run_id, a.thread_id,
                               a.recorded_at, a.event_kind, a.event_summary,
                               a.model_name,
                               a.token_input, a.token_output,
                               a.token_cache_hit, a.token_cache_miss,
                               a.tool_name, a.tool_duration_ms,
                               a.file_path, a.file_operation,
                               a.source_ip, a.is_error, a.error_message
                        FROM ist_audit.audit_log a
                        LEFT JOIN ist_audit.users u ON a.user_id = u.id
                        WHERE {where_sql}
                        ORDER BY a.recorded_at ASC""",
                    params,
                )
                for row in iter(cur.fetchone, None):
                    writer.writerow([
                        row["id"],
                        row.get("username", ""),
                        row.get("role", ""),
                        row.get("session_id", ""),
                        row.get("conversation_id", ""),
                        row.get("run_id", ""),
                        row.get("thread_id", ""),
                        row["recorded_at"].isoformat() if isinstance(row.get("recorded_at"), datetime) else row.get("recorded_at", ""),
                        row.get("event_kind", ""),
                        row.get("event_summary", ""),
                        row.get("model_name", ""),
                        row.get("token_input", ""),
                        row.get("token_output", ""),
                        row.get("token_cache_hit", ""),
                        row.get("token_cache_miss", ""),
                        row.get("tool_name", ""),
                        row.get("tool_duration_ms", ""),
                        row.get("file_path", ""),
                        row.get("file_operation", ""),
                        row.get("source_ip", ""),
                        row.get("is_error", ""),
                        row.get("error_message", ""),
                    ])
                    yield buf.getvalue()
                    buf.seek(0)
                    buf.truncate(0)
        finally:
            if conn:
                conn.close()

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    return StreamingResponse(
        _generate(),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=audit_export_{ts}.csv"},
    )


@app.get("/api/audit/logs/stats")
async def audit_stats(request: Request):
    """审计日志统计概览。"""
    _auth(request)
    stats = {}
    with pg_cursor() as cur:
        cur.execute(
            """SELECT event_kind, count(*) AS cnt
               FROM ist_audit.audit_log
               GROUP BY event_kind ORDER BY cnt DESC"""
        )
        stats["event_kind_distribution"] = cur.fetchall()

        cur.execute(
            """SELECT
                 count(*) AS total,
                 count(*) FILTER (WHERE is_error) AS error_count
               FROM ist_audit.audit_log"""
        )
        row = cur.fetchone()
        total = row["total"]
        err = row["error_count"]
        stats["error_rate"] = {
            "total": total,
            "errors": err,
            "rate": round(err / total, 4) if total else 0,
        }

        cur.execute(
            """SELECT u.username, count(*) AS cnt
               FROM ist_audit.audit_log a
               JOIN ist_audit.users u ON a.user_id = u.id
               GROUP BY u.username ORDER BY cnt DESC LIMIT 10"""
        )
        stats["top_users"] = cur.fetchall()

        cur.execute(
            """SELECT tool_name, count(*) AS cnt
               FROM ist_audit.audit_log
               WHERE tool_name IS NOT NULL
               GROUP BY tool_name ORDER BY cnt DESC LIMIT 10"""
        )
        stats["top_tools"] = cur.fetchall()

        cur.execute(
            """SELECT min(recorded_at) AS earliest, max(recorded_at) AS latest
               FROM ist_audit.audit_log"""
        )
        tr = cur.fetchone()
        stats["time_range"] = _serialize_row(tr) if tr else {}

    return stats


# ===========================================================================
# 2. 用户管理
# ===========================================================================


@app.get("/api/users")
async def list_users(
    request: Request,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    role: Optional[str] = None,
    account_status: Optional[str] = None,
    keyword: Optional[str] = None,
):
    """用户列表（分页）。"""
    _auth(request)
    offset = (page - 1) * page_size
    kw = f"%{keyword}%" if keyword else None
    where_sql, params = _build_where([
        ("u.role = %(role)s", "role", role),
        ("u.account_status = %(account_status)s", "account_status", account_status),
        ("u.username ILIKE %(keyword)s", "keyword", kw),
    ])
    params["page_size"] = page_size
    params["offset"] = offset

    with pg_cursor() as cur:
        cur.execute(
            f"""SELECT count(*) AS total FROM ist_audit.users u WHERE {where_sql}""",
            params,
        )
        total = cur.fetchone()["total"]

        cur.execute(
            f"""SELECT u.id, u.username, u.role, u.account_status,
                      u.failed_login_count, u.locked_until,
                      u.created_at, u.updated_at, u.last_login_at
               FROM ist_audit.users u
               WHERE {where_sql}
               ORDER BY u.created_at DESC
               LIMIT %(page_size)s OFFSET %(offset)s""",
            params,
        )
        items = [_serialize_row(r) for r in cur.fetchall()]

    return {"total": total, "page": page, "page_size": page_size, "items": items}


@app.get("/api/users/{user_id}")
async def user_detail(user_id: str, request: Request):
    """用户详情。"""
    _auth(request)
    with pg_cursor() as cur:
        cur.execute(
            """SELECT id, username, role, account_status,
                      failed_login_count, locked_until,
                      created_at, updated_at, last_login_at
               FROM ist_audit.users WHERE id = %s""",
            (user_id,),
        )
        row = cur.fetchone()
    if not row:
        raise HTTPException(404, "用户不存在")
    return _serialize_row(row)


@app.get("/api/users/{user_id}/sessions")
async def user_sessions(
    user_id: str,
    request: Request,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
):
    """指定用户的会话列表。"""
    _auth(request)
    offset = (page - 1) * page_size
    with pg_cursor() as cur:
        cur.execute(
            """SELECT count(*) AS total FROM ist_audit.sessions WHERE user_id = %s""",
            (user_id,),
        )
        total = cur.fetchone()["total"]
        cur.execute(
            """SELECT session_id, created_at, expires_at, is_valid
               FROM ist_audit.sessions
               WHERE user_id = %s
               ORDER BY created_at DESC
               LIMIT %s OFFSET %s""",
            (user_id, page_size, offset),
        )
        items = [_serialize_row(r) for r in cur.fetchall()]
    return {"total": total, "page": page, "page_size": page_size, "items": items}


@app.get("/api/users/{user_id}/logs")
async def user_logs(
    user_id: str,
    request: Request,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    event_kind: Optional[str] = None,
):
    """指定用户的审计日志。"""
    _auth(request)
    offset = (page - 1) * page_size
    where_sql, params = _build_where([
        ("a.user_id = %(user_id)s", "user_id", user_id),
        ("a.event_kind = %(event_kind)s", "event_kind", event_kind),
    ])
    params["page_size"] = page_size
    params["offset"] = offset

    with pg_cursor() as cur:
        cur.execute(
            f"""SELECT count(*) AS total
               FROM ist_audit.audit_log a
               WHERE {where_sql}""",
            params,
        )
        total = cur.fetchone()["total"]
        cur.execute(
            f"""SELECT a.id, a.session_id, a.run_id, a.recorded_at,
                      a.event_kind, a.event_summary, a.tool_name,
                      a.is_error
               FROM ist_audit.audit_log a
               WHERE {where_sql}
               ORDER BY a.recorded_at DESC
               LIMIT %(page_size)s OFFSET %(offset)s""",
            params,
        )
        items = [_serialize_row(r) for r in cur.fetchall()]
    return {"total": total, "page": page, "page_size": page_size, "items": items}


# ===========================================================================
# 3. 会话管理
# ===========================================================================


@app.get("/api/sessions")
async def list_sessions(
    request: Request,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    username: Optional[str] = None,
    session_id: Optional[str] = None,
    conversation_id: Optional[str] = None,
    is_valid: Optional[bool] = None,
):
    """会话列表（分页）。"""
    _auth(request)
    offset = (page - 1) * page_size
    where_sql, params = _build_where([
        ("u.username = %(username)s", "username", username),
        ("s.session_id = %(session_id)s", "session_id", session_id),
        ("c.conversation_id = %(conversation_id)s", "conversation_id", conversation_id),
        ("s.is_valid = %(is_valid)s", "is_valid", is_valid),
    ])
    params["page_size"] = page_size
    params["offset"] = offset

    with pg_cursor() as cur:
        cur.execute(
            f"""SELECT count(*) AS total
               FROM ist_audit.sessions s
               JOIN ist_audit.users u ON s.user_id = u.id
               LEFT JOIN ist_audit.conversations c ON s.session_id = c.session_id
               WHERE {where_sql}""",
            params,
        )
        total = cur.fetchone()["total"]
        cur.execute(
            f"""SELECT s.session_id, u.username, u.role,
                      s.created_at, s.expires_at, s.is_valid,
                      c.conversation_id, c.is_active AS conversation_status
               FROM ist_audit.sessions s
               JOIN ist_audit.users u ON s.user_id = u.id
               LEFT JOIN ist_audit.conversations c ON s.session_id = c.session_id
               WHERE {where_sql}
               ORDER BY s.created_at DESC
               LIMIT %(page_size)s OFFSET %(offset)s""",
            params,
        )
        items = [_serialize_row(r) for r in cur.fetchall()]
    return {"total": total, "page": page, "page_size": page_size, "items": items}


@app.get("/api/sessions/{path_session_id}")
async def session_detail(path_session_id: str, request: Request):
    """会话详情。"""
    _auth(request)
    with pg_cursor() as cur:
        cur.execute(
            """SELECT s.session_id, u.username, u.role, u.id AS user_id,
                      s.created_at, s.expires_at, s.is_valid
               FROM ist_audit.sessions s
               JOIN ist_audit.users u ON s.user_id = u.id
               WHERE s.session_id = %s""",
            (path_session_id,),
        )
        row = cur.fetchone()
    if not row:
        raise HTTPException(404, "会话不存在")
    return _serialize_row(row)


@app.get("/api/sessions/{path_session_id}/logs")
async def session_logs(
    path_session_id: str,
    request: Request,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
):
    """指定会话的审计日志。"""
    _auth(request)
    offset = (page - 1) * page_size
    with pg_cursor() as cur:
        cur.execute(
            """SELECT count(*) AS total
               FROM ist_audit.audit_log WHERE session_id = %s""",
            (path_session_id,),
        )
        total = cur.fetchone()["total"]
        cur.execute(
            """SELECT a.id, a.event_kind, a.event_summary, a.recorded_at,
                      a.tool_name, a.is_error
               FROM ist_audit.audit_log a
               WHERE a.session_id = %s
               ORDER BY a.recorded_at ASC
               LIMIT %s OFFSET %s""",
            (path_session_id, page_size, offset),
        )
        items = [_serialize_row(r) for r in cur.fetchall()]
    return {"total": total, "page": page, "page_size": page_size, "items": items}


# ===========================================================================
# 4. LLM 使用统计
# ===========================================================================


@app.get("/api/llm/usage")
async def llm_usage(
    request: Request,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    username: Optional[str] = None,
    model_name: Optional[str] = None,
    start_time: Optional[str] = None,
    end_time: Optional[str] = None,
):
    """LLM 调用明细（audit_log 中的 llm_end 事件）。"""
    _auth(request)
    st = _parse_dt(start_time)
    et = _parse_dt(end_time)
    offset = (page - 1) * page_size

    where_sql, params = _build_where([
        ("a.event_kind = %(event_kind)s", "event_kind", "llm_end"),
        ("u.username = %(username)s", "username", username),
        ("a.model_name = %(model_name)s", "model_name", model_name),
        ("a.recorded_at >= %(start_time)s", "start_time", st),
        ("a.recorded_at <= %(end_time)s", "end_time", et),
    ])
    params["page_size"] = page_size
    params["offset"] = offset

    with pg_cursor() as cur:
        cur.execute(
            f"""SELECT count(*) AS total
               FROM ist_audit.audit_log a
               JOIN ist_audit.users u ON a.user_id = u.id
               WHERE {where_sql}""",
            params,
        )
        total = cur.fetchone()["total"]
        cur.execute(
            f"""SELECT a.id, u.username, a.model_name,
                      a.token_input, a.token_output,
                      a.token_cache_hit, a.token_cache_miss,
                      a.recorded_at, a.run_id
               FROM ist_audit.audit_log a
               JOIN ist_audit.users u ON a.user_id = u.id
               WHERE {where_sql}
               ORDER BY a.recorded_at DESC
               LIMIT %(page_size)s OFFSET %(offset)s""",
            params,
        )
        items = [_serialize_row(r) for r in cur.fetchall()]
    return {"total": total, "page": page, "page_size": page_size, "items": items}


@app.get("/api/llm/usage/daily")
async def llm_usage_daily(
    request: Request,
    username: Optional[str] = None,
    model_name: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
):
    """LLM 每日用量汇总（从 token_daily_summary 表读取）。"""
    _auth(request)
    where_sql, params = _build_where([
        ("u.username = %(username)s", "username", username),
        ("t.model_name = %(model_name)s", "model_name", model_name),
        ("t.date >= %(start_date)s::date", "start_date", start_date),
        ("t.date <= %(end_date)s::date", "end_date", end_date),
    ])

    with pg_cursor() as cur:
        cur.execute(
            f"""SELECT u.username, t.date, t.model_name,
                      t.call_count, t.input_tokens, t.output_tokens,
                      t.cache_hit, t.cache_miss, t.cost_rmb
               FROM ist_audit.token_daily_summary t
               JOIN ist_audit.users u ON t.user_id = u.id
               WHERE {where_sql}
               ORDER BY t.date DESC, u.username""",
            params,
        )
        items = [_serialize_row(r) for r in cur.fetchall()]
    return {"items": items}


@app.get("/api/llm/usage/by-user")
async def llm_usage_by_user(
    request: Request,
    start_time: Optional[str] = None,
    end_time: Optional[str] = None,
):
    """LLM 用量按用户汇总。"""
    _auth(request)
    st = _parse_dt(start_time)
    et = _parse_dt(end_time)

    where_sql, params = _build_where([
        ("a.event_kind = %(event_kind)s", "event_kind", "llm_end"),
        ("a.recorded_at >= %(start_time)s", "start_time", st),
        ("a.recorded_at <= %(end_time)s", "end_time", et),
    ])

    with pg_cursor() as cur:
        cur.execute(
            f"""SELECT u.username,
                      count(*) AS call_count,
                      coalesce(sum(a.token_input), 0) AS total_input,
                      coalesce(sum(a.token_output), 0) AS total_output,
                      coalesce(sum(a.token_cache_hit), 0) AS total_cache_hit,
                      coalesce(sum(a.token_cache_miss), 0) AS total_cache_miss
               FROM ist_audit.audit_log a
               JOIN ist_audit.users u ON a.user_id = u.id
               WHERE {where_sql}
               GROUP BY u.username
               ORDER BY total_input + total_output DESC""",
            params,
        )
        items = [_serialize_row(r) for r in cur.fetchall()]
    return {"items": items}


# ===========================================================================
# 5. 工具 / 文件 / Skills
# ===========================================================================


@app.get("/api/tools")
async def list_tools(request: Request):
    """工具名称列表及调用次数。"""
    _auth(request)
    with pg_cursor() as cur:
        cur.execute(
            """SELECT tool_name, count(*) AS cnt
               FROM ist_audit.audit_log
               WHERE tool_name IS NOT NULL
               GROUP BY tool_name ORDER BY cnt DESC"""
        )
        items = [_serialize_row(r) for r in cur.fetchall()]
    return {"items": items}


@app.get("/api/tools/{tool_name}/logs")
async def tool_logs(
    tool_name: str,
    request: Request,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    username: Optional[str] = None,
    is_error: Optional[bool] = None,
    start_time: Optional[str] = None,
    end_time: Optional[str] = None,
):
    """指定工具的调用日志。"""
    _auth(request)
    st = _parse_dt(start_time)
    et = _parse_dt(end_time)
    offset = (page - 1) * page_size

    where_sql, params = _build_where([
        ("a.tool_name = %(tool_name)s", "tool_name", tool_name),
        ("u.username = %(username)s", "username", username),
        ("a.is_error = %(is_error)s", "is_error", is_error),
        ("a.recorded_at >= %(start_time)s", "start_time", st),
        ("a.recorded_at <= %(end_time)s", "end_time", et),
    ])
    params["page_size"] = page_size
    params["offset"] = offset

    with pg_cursor() as cur:
        cur.execute(
            f"""SELECT count(*) AS total
               FROM ist_audit.audit_log a
               JOIN ist_audit.users u ON a.user_id = u.id
               WHERE {where_sql}""",
            params,
        )
        total = cur.fetchone()["total"]
        cur.execute(
            f"""SELECT a.id, u.username, a.recorded_at,
                      a.tool_name, a.tool_duration_ms,
                      a.is_error, a.error_message,
                      a.session_id, a.run_id
               FROM ist_audit.audit_log a
               JOIN ist_audit.users u ON a.user_id = u.id
               WHERE {where_sql}
               ORDER BY a.recorded_at DESC
               LIMIT %(page_size)s OFFSET %(offset)s""",
            params,
        )
        items = [_serialize_row(r) for r in cur.fetchall()]
    return {"total": total, "page": page, "page_size": page_size, "items": items}


@app.get("/api/files")
async def list_file_events(
    request: Request,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    file_operation: Optional[str] = None,
    username: Optional[str] = None,
    start_time: Optional[str] = None,
    end_time: Optional[str] = None,
):
    """文件操作事件列表。"""
    _auth(request)
    st = _parse_dt(start_time)
    et = _parse_dt(end_time)
    offset = (page - 1) * page_size

    where_sql, params = _build_where([
        ("a.file_path IS NOT NULL", "_file_not_null", True),
        ("a.file_operation = %(file_operation)s", "file_operation", file_operation),
        ("u.username = %(username)s", "username", username),
        ("a.recorded_at >= %(start_time)s", "start_time", st),
        ("a.recorded_at <= %(end_time)s", "end_time", et),
    ])
    params["page_size"] = page_size
    params["offset"] = offset

    with pg_cursor() as cur:
        cur.execute(
            f"""SELECT count(*) AS total
               FROM ist_audit.audit_log a
               JOIN ist_audit.users u ON a.user_id = u.id
               WHERE {where_sql}""",
            params,
        )
        total = cur.fetchone()["total"]
        cur.execute(
            f"""SELECT a.id, u.username, a.file_path, a.file_operation,
                      a.recorded_at, a.event_kind, a.is_error
               FROM ist_audit.audit_log a
               JOIN ist_audit.users u ON a.user_id = u.id
               WHERE {where_sql}
               ORDER BY a.recorded_at DESC
               LIMIT %(page_size)s OFFSET %(offset)s""",
            params,
        )
        items = [_serialize_row(r) for r in cur.fetchall()]
    return {"total": total, "page": page, "page_size": page_size, "items": items}


@app.get("/api/skills")
async def list_skills(
    request: Request,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    username: Optional[str] = None,
    start_time: Optional[str] = None,
    end_time: Optional[str] = None,
):
    """Skill 调用记录。"""
    _auth(request)
    st = _parse_dt(start_time)
    et = _parse_dt(end_time)
    offset = (page - 1) * page_size

    where_sql, params = _build_where([
        ("a.event_kind IN ('skill_invoke', 'skill_fork_start', 'skill_fork_end')", "_skill_events", True),
        ("u.username = %(username)s", "username", username),
        ("a.recorded_at >= %(start_time)s", "start_time", st),
        ("a.recorded_at <= %(end_time)s", "end_time", et),
    ])
    params["page_size"] = page_size
    params["offset"] = offset

    with pg_cursor() as cur:
        cur.execute(
            f"""SELECT count(*) AS total
               FROM ist_audit.audit_log a
               JOIN ist_audit.users u ON a.user_id = u.id
               WHERE {where_sql}""",
            params,
        )
        total = cur.fetchone()["total"]
        cur.execute(
            f"""SELECT a.id, u.username, a.event_kind, a.event_summary,
                      a.recorded_at, a.run_id
               FROM ist_audit.audit_log a
               JOIN ist_audit.users u ON a.user_id = u.id
               WHERE {where_sql}
               ORDER BY a.recorded_at DESC
               LIMIT %(page_size)s OFFSET %(offset)s""",
            params,
        )
        items = [_serialize_row(r) for r in cur.fetchall()]
    return {"total": total, "page": page, "page_size": page_size, "items": items}


# ===========================================================================
# 6. 安全事件
# ===========================================================================


@app.get("/api/security/failed-logins")
async def security_failed_logins(
    request: Request,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    username: Optional[str] = None,
    start_time: Optional[str] = None,
    end_time: Optional[str] = None,
):
    """登录失败事件。"""
    _auth(request)
    st = _parse_dt(start_time)
    et = _parse_dt(end_time)
    offset = (page - 1) * page_size

    where_sql, params = _build_where([
        ("event_kind = %(event_kind)s", "event_kind", "auth_login_failed"),
        ("(event_payload->>'username') = %(username)s", "username", username),
        ("recorded_at >= %(start_time)s", "start_time", st),
        ("recorded_at <= %(end_time)s", "end_time", et),
    ])
    params["page_size"] = page_size
    params["offset"] = offset

    with pg_cursor() as cur:
        cur.execute(
            f"""SELECT count(*) AS total
               FROM ist_audit.audit_log
               WHERE {where_sql}""",
            params,
        )
        total = cur.fetchone()["total"]
        cur.execute(
            f"""SELECT id, recorded_at,
                      event_payload->>'username' AS target_username,
                      event_payload->>'reason' AS reason,
                      tags->>'source_ip' AS source_ip
               FROM ist_audit.audit_log
               WHERE {where_sql}
               ORDER BY recorded_at DESC
               LIMIT %(page_size)s OFFSET %(offset)s""",
            params,
        )
        items = [_serialize_row(r) for r in cur.fetchall()]
    return {"total": total, "page": page, "page_size": page_size, "items": items}


@app.get("/api/security/locked-accounts")
async def security_locked_accounts(request: Request):
    """当前被锁定/禁用的账号。"""
    _auth(request)
    with pg_cursor() as cur:
        cur.execute(
            """SELECT id, username, role, account_status,
                      failed_login_count, locked_until, updated_at
               FROM ist_audit.users
               WHERE account_status != 'normal'
               ORDER BY updated_at DESC"""
        )
        items = [_serialize_row(r) for r in cur.fetchall()]
    return {"items": items}


@app.get("/api/security/access-denied")
async def security_access_denied(
    request: Request,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    username: Optional[str] = None,
    start_time: Optional[str] = None,
    end_time: Optional[str] = None,
):
    """权限拒绝事件（access_denied）。"""
    _auth(request)
    st = _parse_dt(start_time)
    et = _parse_dt(end_time)
    offset = (page - 1) * page_size

    where_sql, params = _build_where([
        ("a.event_kind = %(event_kind)s", "event_kind", "access_denied"),
        ("u.username = %(username)s", "username", username),
        ("a.recorded_at >= %(start_time)s", "start_time", st),
        ("a.recorded_at <= %(end_time)s", "end_time", et),
    ])
    params["page_size"] = page_size
    params["offset"] = offset

    with pg_cursor() as cur:
        cur.execute(
            f"""SELECT count(*) AS total
               FROM ist_audit.audit_log a
               JOIN ist_audit.users u ON a.user_id = u.id
               WHERE {where_sql}""",
            params,
        )
        total = cur.fetchone()["total"]
        cur.execute(
            f"""SELECT a.id, u.username, a.event_summary, a.recorded_at,
                      a.source_ip, a.event_payload
               FROM ist_audit.audit_log a
               JOIN ist_audit.users u ON a.user_id = u.id
               WHERE {where_sql}
               ORDER BY a.recorded_at DESC
               LIMIT %(page_size)s OFFSET %(offset)s""",
            params,
        )
        items = [_serialize_row(r) for r in cur.fetchall()]
    return {"total": total, "page": page, "page_size": page_size, "items": items}


# ===========================================================================
# 7. 执行追踪（trace 表）
# ===========================================================================


@app.get("/api/traces")
async def list_traces(
    request: Request,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    status: Optional[str] = None,
    username: Optional[str] = None,
    keyword: Optional[str] = None,
    start_time: Optional[str] = None,
    end_time: Optional[str] = None,
):
    """Trace 列表（分页）。"""
    _auth(request)
    st = _parse_dt(start_time)
    et = _parse_dt(end_time)
    kw = f"%{keyword}%" if keyword else None
    offset = (page - 1) * page_size

    where_sql, params = _build_where([
        ("t.status = %(status)s", "status", status),
        ("u.username = %(username)s", "username", username),
        ("t.user_input ILIKE %(keyword)s", "keyword", kw),
        ("t.started_at >= %(start_time)s", "start_time", st),
        ("t.started_at <= %(end_time)s", "end_time", et),
    ])
    params["page_size"] = page_size
    params["offset"] = offset

    with pg_cursor() as cur:
        cur.execute(
            f"""SELECT count(*) AS total
                FROM ist_audit.trace t
                LEFT JOIN ist_audit.users u ON t.user_id = u.id
                WHERE {where_sql}""",
            params,
        )
        total = cur.fetchone()["total"]

        cur.execute(
            f"""SELECT t.id, t.trace_id, u.username,
                       t.user_input, t.started_at, t.duration_ms, t.status,
                       jsonb_array_length(COALESCE(t.llm_calls, '[]'::jsonb)) AS llm_count,
                       jsonb_array_length(COALESCE(t.tool_calls, '[]'::jsonb)) AS tool_count,
                       jsonb_array_length(COALESCE(t.kb_retrievals, '[]'::jsonb)) AS kb_count,
                       t.error_info->>'total_error_count' AS error_count,
                       (SELECT r.score FROM ist_audit.sys_chat_rating r
                        WHERE r.run_id = left(replace(t.trace_id::text, '-', ''), 12)
                        ORDER BY r.created_at DESC LIMIT 1) AS rating_score
                FROM ist_audit.trace t
                LEFT JOIN ist_audit.users u ON t.user_id = u.id
                WHERE {where_sql}
                ORDER BY t.started_at DESC
                LIMIT %(page_size)s OFFSET %(offset)s""",
            params,
        )
        items = [_serialize_row(r) for r in cur.fetchall()]

    return {"total": total, "page": page, "page_size": page_size, "items": items}


@app.get("/api/traces/{trace_id}")
async def trace_detail(trace_id: str, request: Request):
    """单条 Trace 详情（含全部 JSONB 载荷 + 用户评分）。"""
    _auth(request)
    with pg_cursor() as cur:
        cur.execute(
            """SELECT t.*, u.username, u.role
               FROM ist_audit.trace t
               LEFT JOIN ist_audit.users u ON t.user_id = u.id
               WHERE t.trace_id = %s""",
            (trace_id,),
        )
        row = cur.fetchone()
    if not row:
        raise HTTPException(404, "Trace 不存在")
    result = _serialize_row(row)
    # 查询关联评分（trace_id 去横杠前 12 位 = run_id）
    run_id = trace_id.replace("-", "")[:12]
    with pg_cursor() as cur:
        cur.execute(
            """SELECT score, comment, username, created_at
               FROM ist_audit.sys_chat_rating
               WHERE run_id = %s
               ORDER BY created_at DESC""",
            (run_id,),
        )
        result["ratings"] = [_serialize_row(r) for r in cur.fetchall()]
    return result


# ===========================================================================
# 8. 仪表盘
# ===========================================================================


@app.get("/api/dashboard/overview")
async def dashboard_overview(request: Request):
    """仪表盘概览数据。"""
    _auth(request)
    with pg_cursor() as cur:
        cur.execute("SELECT count(*) AS cnt FROM ist_audit.users")
        user_count = cur.fetchone()["cnt"]

        cur.execute("SELECT count(*) AS cnt FROM ist_audit.sessions WHERE is_valid = TRUE")
        active_sessions = cur.fetchone()["cnt"]

        cur.execute("SELECT count(*) AS cnt FROM ist_audit.audit_log")
        total_events = cur.fetchone()["cnt"]

        cur.execute(
            """SELECT count(*) AS cnt FROM ist_audit.audit_log
               WHERE recorded_at >= now() - interval '24 hours'"""
        )
        events_24h = cur.fetchone()["cnt"]

        cur.execute(
            """SELECT count(*) AS cnt FROM ist_audit.audit_log WHERE is_error = TRUE"""
        )
        error_count = cur.fetchone()["cnt"]

        cur.execute(
            """SELECT coalesce(sum(token_input + token_output), 0) AS total_tokens
               FROM ist_audit.audit_log WHERE event_kind = 'llm_end'"""
        )
        total_tokens = cur.fetchone()["total_tokens"]

    return {
        "user_count": user_count,
        "active_sessions": active_sessions,
        "total_events": total_events,
        "events_24h": events_24h,
        "error_count": error_count,
        "total_tokens": int(total_tokens),
    }


@app.get("/api/dashboard/timeline")
async def dashboard_timeline(
    request: Request,
    hours: int = Query(24, ge=1, le=168),
    interval: str = Query("1h", pattern=r"^\d+[mh]$"),
):
    """事件时间线（按时间桶聚合）。"""
    _auth(request)
    with pg_cursor() as cur:
        cur.execute(
            """SELECT date_trunc('hour', recorded_at) AS bucket,
                      count(*) AS cnt,
                      count(*) FILTER (WHERE is_error) AS errors
               FROM ist_audit.audit_log
               WHERE recorded_at >= now() - make_interval(hours => %s)
               GROUP BY bucket ORDER BY bucket""",
            (hours,),
        )
        items = [_serialize_row(r) for r in cur.fetchall()]
    return {"hours": hours, "interval": interval, "items": items}


@app.get("/api/dashboard/top-users")
async def dashboard_top_users(
    request: Request,
    limit: int = Query(10, ge=1, le=50),
    hours: int = Query(24, ge=1, le=168),
):
    """活跃用户排行。"""
    _auth(request)
    with pg_cursor() as cur:
        cur.execute(
            """SELECT u.username, count(*) AS event_count,
                      count(DISTINCT a.session_id) AS session_count
               FROM ist_audit.audit_log a
               JOIN ist_audit.users u ON a.user_id = u.id
               WHERE a.recorded_at >= now() - make_interval(hours => %s)
               GROUP BY u.username
               ORDER BY event_count DESC
               LIMIT %s""",
            (hours, limit),
        )
        items = [_serialize_row(r) for r in cur.fetchall()]
    return {"items": items}


@app.get("/api/dashboard/top-tools")
async def dashboard_top_tools(
    request: Request,
    limit: int = Query(10, ge=1, le=50),
    hours: int = Query(24, ge=1, le=168),
):
    """工具调用排行。"""
    _auth(request)
    with pg_cursor() as cur:
        cur.execute(
            """SELECT tool_name, count(*) AS call_count,
                      avg(tool_duration_ms) AS avg_duration_ms,
                      count(*) FILTER (WHERE is_error) AS error_count
               FROM ist_audit.audit_log
               WHERE tool_name IS NOT NULL
                 AND recorded_at >= now() - make_interval(hours => %s)
               GROUP BY tool_name
               ORDER BY call_count DESC
               LIMIT %s""",
            (hours, limit),
        )
        items = [_serialize_row(r) for r in cur.fetchall()]
    return {"items": items}


# ===========================================================================
# 8. 认证端点（前端登录用）
# ===========================================================================


@app.post("/api/login")
async def login(body: dict, request: Request):
    """登录端点：校验用户名、密码、角色，仅允许 superadmin。"""
    from main.ist_core.auth.db import pg_cursor as _pc
    from main.ist_core.auth.jwt_handler import create_access_token
    from main.ist_core.auth.password import verify_password

    username = (body.get("username") or "").strip()
    password = body.get("password") or ""
    if not username or not password:
        raise HTTPException(400, "用户名和密码不能为空")

    with _pc() as cur:
        cur.execute(
            "SELECT id, username, password_hash, role, account_status "
            "FROM ist_audit.users WHERE username = %s",
            (username,),
        )
        user = cur.fetchone()

    if not user:
        raise HTTPException(401, "用户名不存在")
    if user.get("account_status") != "normal":
        raise HTTPException(403, "账号已被锁定或禁用")
    if not verify_password(user["password_hash"], password):
        raise HTTPException(401, "用户名或密码错误")
    if user.get("role") != "superadmin":
        raise HTTPException(403, "仅超级管理员可访问")

    jwt_token, _jti, _exp = create_access_token(username, user["role"])
    logger.info("logserver login ok user=%r role=%s", username, user["role"])
    return {"token": jwt_token, "username": username, "role": user["role"]}


@app.post("/api/logout")
async def logout():
    """登出端点（JWT 无状态，前端清除 token 即可）。"""
    return {"ok": True}


# ===========================================================================
# 前端页面 & 健康检查
# ===========================================================================


@app.get("/")
async def index():
    """审计日志查看器前端页面。"""
    html_path = Path(__file__).resolve().parent / "templates" / "log_viewer.html"
    return FileResponse(html_path, media_type="text/html")


@app.get("/api/health")
async def health():
    """健康检查端点。"""
    try:
        with pg_cursor() as cur:
            cur.execute("SELECT 1 AS ok")
            pg_ok = cur.fetchone()["ok"] == 1
    except Exception:
        pg_ok = False
    return {"status": "ok" if pg_ok else "degraded", "pg": pg_ok}
