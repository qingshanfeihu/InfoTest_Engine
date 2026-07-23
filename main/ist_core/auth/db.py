"""PostgreSQL 连接管理与 ist_audit schema 初始化。

psycopg3 连接模式：autocommit=True, dict_row。
prepare_threshold 使用默认值（5），避免首次执行参数化查询时类型推断失败。
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

CREATE TABLE IF NOT EXISTS ist_audit.conversations (
    conversation_id  VARCHAR(80) PRIMARY KEY,
    user_id          UUID NOT NULL REFERENCES ist_audit.users(id) ON DELETE CASCADE,
    session_id       VARCHAR(80) REFERENCES ist_audit.sessions(session_id) ON DELETE SET NULL,
    title            VARCHAR(200) NOT NULL DEFAULT '新对话',
    model_name       VARCHAR(64),
    message_count    INTEGER NOT NULL DEFAULT 0,
    last_message_at  TIMESTAMPTZ,
    is_active        BOOLEAN NOT NULL DEFAULT TRUE,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_conversations_user_time
    ON ist_audit.conversations(user_id, last_message_at DESC NULLS LAST);
CREATE INDEX IF NOT EXISTS idx_conversations_active
    ON ist_audit.conversations(user_id, is_active) WHERE is_active = TRUE;
CREATE INDEX IF NOT EXISTS idx_conversations_session
    ON ist_audit.conversations(session_id);

-- audit_log / token_daily_summary / trace 已禁用（2026-07-23，项目已接入 langfuse，
-- 不再需要单独维护 log 系统的这三张表。保留 DDL 注释供参考。）

-- CREATE TABLE IF NOT EXISTS ist_audit.token_daily_summary (
--     id            BIGSERIAL PRIMARY KEY,
--     user_id       UUID NOT NULL ,
--     date          DATE NOT NULL,
--     model_name    VARCHAR(64) NOT NULL,
--     call_count    INTEGER NOT NULL DEFAULT 0,
--     input_tokens  BIGINT NOT NULL DEFAULT 0,
--     output_tokens BIGINT NOT NULL DEFAULT 0,
--     cache_hit     BIGINT NOT NULL DEFAULT 0,
--     cache_miss    BIGINT NOT NULL DEFAULT 0,
--     cost_rmb      NUMERIC(12, 6),
--     UNIQUE (user_id, date, model_name)
-- );
-- CREATE INDEX IF NOT EXISTS idx_token_daily_user
--     ON ist_audit.token_daily_summary(user_id, date DESC);

-- CREATE TABLE IF NOT EXISTS ist_audit.trace (
--     id                    BIGSERIAL PRIMARY KEY,
--     trace_id              UUID NOT NULL UNIQUE,
--     user_id               UUID,
--     session_id            VARCHAR(120),
--     conversation_id       VARCHAR(120),
--     thread_id             VARCHAR(256),
--     user_input            TEXT,
--     started_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
--     ended_at              TIMESTAMPTZ,
--     duration_ms           INTEGER,
--     demand_classification JSONB,
--     node_path             TEXT[],
--     llm_calls             JSONB,
--     thinking_full         TEXT,
--     thinking_segments     JSONB,
--     subagent_runs         JSONB,
--     kb_retrievals         JSONB,
--     tool_calls            JSONB,
--     error_info            JSONB,
--     status                VARCHAR(16) NOT NULL DEFAULT 'running'
--         CHECK (status IN ('running', 'done', 'error', 'cancelled'))
-- );
-- CREATE INDEX IF NOT EXISTS idx_trace_user_time
--     ON ist_audit.trace(user_id, started_at DESC);
-- CREATE INDEX IF NOT EXISTS idx_trace_session
--     ON ist_audit.trace(session_id);
-- CREATE INDEX IF NOT EXISTS idx_trace_status
--     ON ist_audit.trace(status);
-- CREATE INDEX IF NOT EXISTS idx_trace_started
--     ON ist_audit.trace(started_at DESC);

-- ── 对话业务持久存储（sys_dialog_chat）──
-- 职责：前端对话历史展示、分页查询、审计导出、合规归档
-- 不作为推理数据源（推理上下文仅从 Checkpointer 加载）
-- 无物理外键，仅逻辑关联字段
-- 每轮对话一行：用户输入 + 模型最终回答
CREATE TABLE IF NOT EXISTS ist_audit.sys_dialog_chat (
    id                BIGSERIAL PRIMARY KEY,

    -- 归属标识（逻辑关联，无物理外键）
    username          VARCHAR(64)  NOT NULL,
    session_id        VARCHAR(120) NOT NULL,
    conversation_id   VARCHAR(120) NOT NULL,
    thread_id         VARCHAR(256) NOT NULL,
    run_id            VARCHAR(64)  NOT NULL,

    -- 用户输入
    user_input        TEXT,

    -- 模型
    model_name        VARCHAR(64),

    -- 模型最终回答
    llm_output        TEXT,

    -- 评分冗余字段（前端对话列表展示，无需联表 sys_chat_rating）
    rating            SMALLINT CHECK (rating BETWEEN 0 AND 5),

    -- 保留字段（JSONB，供后续扩展）
    reserved          JSONB,

    -- 元数据
    recorded_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 前端对话历史列表（核心查询路径）
CREATE INDEX IF NOT EXISTS idx_sdc_user_conv_time
    ON ist_audit.sys_dialog_chat (username, conversation_id, recorded_at DESC);

-- 按 run_id 查询单轮对话
CREATE INDEX IF NOT EXISTS idx_sdc_run
    ON ist_audit.sys_dialog_chat (run_id);

-- 审计导出：按时间范围 + 用户筛选
CREATE INDEX IF NOT EXISTS idx_sdc_recorded_at
    ON ist_audit.sys_dialog_chat (recorded_at DESC);

-- ── 对话评分表（sys_chat_rating）──
-- 职责：存储用户对单轮对话的评分和评价
-- 无物理外键，仅逻辑关联字段
-- 每轮对话可提交一次评分，重复提交覆盖原有分数
CREATE TABLE IF NOT EXISTS ist_audit.sys_chat_rating (
    id                BIGSERIAL PRIMARY KEY,

    -- 归属标识（逻辑关联，无物理外键）
    username          VARCHAR(64)  NOT NULL,
    session_id        VARCHAR(120) NOT NULL,
    conversation_id   VARCHAR(120) NOT NULL,
    run_id            VARCHAR(64)  NOT NULL,
    thread_id         VARCHAR(256),

    -- 评分（0~5 分）
    score             SMALLINT NOT NULL CHECK (score BETWEEN 0 AND 5),

    -- 文字评价（选填）
    comment           TEXT,

    -- 元数据
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),

    -- 唯一约束：每轮对话仅允许一条评分记录
    UNIQUE (username, conversation_id, run_id)
);

-- 索引：按用户、对话、单次执行快速查询评分
CREATE INDEX IF NOT EXISTS idx_rating_user_conv
    ON ist_audit.sys_chat_rating (username, conversation_id);
CREATE INDEX IF NOT EXISTS idx_rating_run
    ON ist_audit.sys_chat_rating (run_id);
CREATE INDEX IF NOT EXISTS idx_rating_time
    ON ist_audit.sys_chat_rating (created_at DESC);

"""

# ── audit_log 按周分区表（已禁用 2026-07-23，项目已接入 langfuse）──
# _PARTITIONED_AUDIT_LOG_DDL = """\
# CREATE TABLE IF NOT EXISTS ist_audit.audit_log (
#     id            BIGSERIAL,
#     ...
# ) PARTITION BY RANGE (recorded_at);
# """
_PARTITIONED_AUDIT_LOG_DDL = ""  # 空字符串，ensure_schema 不再执行

# ── 分区维护 SQL（已禁用）──
_PARTITION_CREATE_FN = ""
_PARTITION_DROP_FN = ""


def _migrate_audit_log_partitioned() -> None:
    """audit_log 分区迁移已禁用（2026-07-23，项目已接入 langfuse）。"""
    pass


def _run_partition_maintenance() -> None:
    """audit_log 分区维护已禁用（2026-07-23，项目已接入 langfuse）。"""
    pass


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
    return psycopg.connect(dsn, autocommit=True, row_factory=dict_row)


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
    """确保 ist_audit schema 和表存在（audit_log 为按周分区表）。"""
    def _execute_ddl(cursor):
        for stmt in _DDL.split(';'):
            stmt = stmt.strip()
            if stmt:
                cursor.execute(stmt)
    if conn is not None:
        _execute_ddl(conn.cursor())
    else:
        with pg_cursor() as cur:
            _execute_ddl(cur)

    # audit_log 分区迁移（幂等：已分区则跳过迁移，仅执行维护）
    try:
        _migrate_audit_log_partitioned()
    except Exception as exc:
        logger.warning("audit_log 分区迁移失败: %s", exc)

    # 分区维护：建新分区 + 清理旧分区
    try:
        _run_partition_maintenance()
    except Exception as exc:
        logger.warning("分区维护失败: %s", exc)

    logger.info("ist_audit schema ensured")
