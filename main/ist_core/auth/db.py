"""PostgreSQL 连接管理与 ist_audit schema 初始化。

复用 graph.py 的 psycopg3 连接模式：autocommit=True, prepare_threshold=0, dict_row。
"""

from __future__ import annotations

import logging
import os
from contextlib import contextmanager
from typing import Optional

import psycopg
from psycopg.rows import dict_row

logger = logging.getLogger(__name__)

_DDL = """\
CREATE SCHEMA IF NOT EXISTS ist_audit;

CREATE TABLE IF NOT EXISTS ist_audit.users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    username VARCHAR(64) NOT NULL UNIQUE,
    password_hash VARCHAR(256) NOT NULL,
    role VARCHAR(32) NOT NULL DEFAULT 'reviewer',
    account_status VARCHAR(16) NOT NULL DEFAULT 'normal'
        CHECK (account_status IN ('normal', 'lock', 'disable')),
    failed_login_count INTEGER NOT NULL DEFAULT 0,
    locked_until TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_login_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS ist_audit.sessions (
    session_id VARCHAR(80) PRIMARY KEY,
    user_id UUID NOT NULL REFERENCES ist_audit.users(id) ON DELETE CASCADE,
    jwt_token TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at TIMESTAMPTZ NOT NULL,
    is_valid BOOLEAN NOT NULL DEFAULT TRUE
);

CREATE INDEX IF NOT EXISTS idx_sessions_user_id
    ON ist_audit.sessions(user_id);
CREATE INDEX IF NOT EXISTS idx_sessions_expires
    ON ist_audit.sessions(expires_at) WHERE is_valid = TRUE;

CREATE TABLE IF NOT EXISTS ist_audit.audit_log (
    id            BIGSERIAL PRIMARY KEY,
    user_id       UUID REFERENCES ist_audit.users(id),
    session_id    VARCHAR(80) REFERENCES ist_audit.sessions(session_id),
    run_id        VARCHAR(32) NOT NULL,
    thread_id     VARCHAR(64),
    recorded_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    event_kind    VARCHAR(32) NOT NULL,
    event_summary TEXT,
    event_payload JSONB,
    model_name    VARCHAR(64),
    token_input   INTEGER,
    token_output  INTEGER,
    token_cache_hit  INTEGER,
    token_cache_miss INTEGER,
    tool_name     VARCHAR(64),
    tool_input    TEXT,
    tool_output   TEXT,
    tool_duration_ms INTEGER,
    file_path     VARCHAR(512),
    file_operation VARCHAR(16),
    source_ip     INET,
    is_error      BOOLEAN NOT NULL DEFAULT false,
    error_message TEXT,
    tags          JSONB
);

CREATE INDEX IF NOT EXISTS idx_audit_user_time
    ON ist_audit.audit_log(user_id, recorded_at DESC);
CREATE INDEX IF NOT EXISTS idx_audit_session
    ON ist_audit.audit_log(session_id);
CREATE INDEX IF NOT EXISTS idx_audit_run
    ON ist_audit.audit_log(run_id);
CREATE INDEX IF NOT EXISTS idx_audit_event_kind
    ON ist_audit.audit_log(event_kind, recorded_at DESC);
CREATE INDEX IF NOT EXISTS idx_audit_tool
    ON ist_audit.audit_log(tool_name, recorded_at DESC);
CREATE INDEX IF NOT EXISTS idx_audit_error
    ON ist_audit.audit_log(recorded_at DESC) WHERE is_error = true;
CREATE INDEX IF NOT EXISTS idx_audit_payload
    ON ist_audit.audit_log USING GIN(event_payload);

CREATE TABLE IF NOT EXISTS ist_audit.token_daily_summary (
    id            BIGSERIAL PRIMARY KEY,
    user_id       UUID NOT NULL REFERENCES ist_audit.users(id),
    date          DATE NOT NULL,
    model_name    VARCHAR(64) NOT NULL,
    call_count    INTEGER NOT NULL DEFAULT 0,
    input_tokens  BIGINT NOT NULL DEFAULT 0,
    output_tokens BIGINT NOT NULL DEFAULT 0,
    cache_hit     BIGINT NOT NULL DEFAULT 0,
    cache_miss    BIGINT NOT NULL DEFAULT 0,
    cost_rmb      NUMERIC(12, 6),
    UNIQUE (user_id, date, model_name)
);
CREATE INDEX IF NOT EXISTS idx_token_daily_user
    ON ist_audit.token_daily_summary(user_id, date DESC);
"""


def _build_dsn() -> str:
    """从环境变量构建 DSN，兼容 IST_POSTGRES_DSN 或分项参数。"""
    dsn = os.environ.get("IST_POSTGRES_DSN", "")
    if dsn:
        # graph.py 兼容：postgresql+psycopg:// → postgresql://
        if dsn.startswith("postgresql+psycopg://"):
            dsn = "postgresql://" + dsn.split("://", 1)[1]
        return dsn
    host = os.environ.get("IST_POSTGRES_HOST", "localhost")
    port = os.environ.get("IST_POSTGRES_PORT", "6543")
    db = os.environ.get("IST_POSTGRES_DB", "ultra_agent")
    user = os.environ.get("IST_POSTGRES_USER", "ultra_agent")
    password = os.environ.get("IST_POSTGRES_PASSWORD", "ultra_agent")
    return f"postgresql://{user}:{password}@{host}:{port}/{db}"


def get_pg_connection() -> psycopg.Connection:
    """获取 PG 连接（autocommit, dict_row）。"""
    dsn = _build_dsn()
    return psycopg.connect(dsn, autocommit=True, prepare_threshold=0, row_factory=dict_row)


@contextmanager
def pg_cursor():
    """上下文管理器：自动获取连接 + 游标，退出时关闭。"""
    conn = get_pg_connection()
    try:
        with conn.cursor() as cur:
            yield cur
    finally:
        conn.close()


def ensure_schema(conn: Optional[psycopg.Connection] = None) -> None:
    """确保 ist_audit schema 和表存在。传入 conn 则复用，否则新建。"""
    def _execute_ddl(cursor):
        for stmt in _DDL.split(';'):
            stmt = stmt.strip()
            if stmt:
                cursor.execute(stmt)
    if conn is not None:
        _execute_ddl(conn.cursor())
        return
    with pg_cursor() as cur:
        _execute_ddl(cur)
    logger.info("ist_audit schema ensured")
