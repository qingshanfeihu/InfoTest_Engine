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

-- audit_log 已迁移为按周分区表，由 _migrate_audit_log_partitioned() 管理
-- （原 CREATE TABLE / ALTER TABLE / INDEXES 已移至 _PARTITIONED_AUDIT_LOG_DDL）

CREATE TABLE IF NOT EXISTS ist_audit.token_daily_summary (
    id            BIGSERIAL PRIMARY KEY,
    user_id       UUID NOT NULL ,
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

-- ── 对话轮次 trace 聚合表 ──
-- 一次 run = 一行，结构化剖面：执行链路 / 思考文本 / 技能执行 / 知识库检索 / 工具明细 / 报错信息
CREATE TABLE IF NOT EXISTS ist_audit.trace (
    id                    BIGSERIAL PRIMARY KEY,
    trace_id              UUID NOT NULL UNIQUE,
    user_id               UUID,
    session_id            VARCHAR(120),
    conversation_id       VARCHAR(120),
    thread_id             VARCHAR(256),
    user_input            TEXT,
    started_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
    ended_at              TIMESTAMPTZ,
    duration_ms           INTEGER,
    -- 结构化 JSONB 载荷
    demand_classification JSONB,
    node_path             TEXT[],
    llm_calls             JSONB,
    thinking_full         TEXT,
    thinking_segments     JSONB,
    subagent_runs         JSONB,
    kb_retrievals         JSONB,
    tool_calls            JSONB,
    error_info            JSONB,
    status                VARCHAR(16) NOT NULL DEFAULT 'running'
        CHECK (status IN ('running', 'done', 'error', 'cancelled'))
);

CREATE INDEX IF NOT EXISTS idx_trace_user_time
    ON ist_audit.trace(user_id, started_at DESC);
CREATE INDEX IF NOT EXISTS idx_trace_session
    ON ist_audit.trace(session_id);
CREATE INDEX IF NOT EXISTS idx_trace_status
    ON ist_audit.trace(status);
CREATE INDEX IF NOT EXISTS idx_trace_started
    ON ist_audit.trace(started_at DESC);

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

# ── audit_log 按周分区表（由 Python 迁移逻辑管理）──
_PARTITIONED_AUDIT_LOG_DDL = """\
CREATE TABLE IF NOT EXISTS ist_audit.audit_log (
    id            BIGSERIAL,
    user_id       UUID,
    session_id    VARCHAR(80),
    conversation_id VARCHAR(80),
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
    tags          JSONB,
    trace_id      UUID,
    category      VARCHAR(32)
) PARTITION BY RANGE (recorded_at);

CREATE INDEX IF NOT EXISTS idx_audit_user_time
    ON ist_audit.audit_log(user_id, recorded_at DESC);
CREATE INDEX IF NOT EXISTS idx_audit_session
    ON ist_audit.audit_log(session_id);
CREATE INDEX IF NOT EXISTS idx_audit_conversation
    ON ist_audit.audit_log(conversation_id);
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
"""

# ── 分区维护 SQL ──

_PARTITION_CREATE_FN = """\
DROP FUNCTION IF EXISTS ist_audit.create_audit_partitions(integer);
CREATE OR REPLACE FUNCTION ist_audit.create_audit_partitions(back INT DEFAULT 2, ahead INT DEFAULT 4)
RETURNS void LANGUAGE plpgsql AS $fn$
DECLARE
    range_start DATE;
    range_end DATE;
    part_name TEXT;
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = 'ist_audit' AND c.relname = 'audit_log' AND c.relkind = 'p'
    ) THEN RETURN; END IF;
    FOR i IN -back..ahead LOOP
        range_start := date_trunc('week', CURRENT_DATE)::DATE + (i * 7);
        range_end   := range_start + 7;
        part_name   := 'audit_log_' || to_char(range_start, 'YYYYMMDD');
        IF NOT EXISTS (
            SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE n.nspname = 'ist_audit' AND c.relname = part_name
        ) THEN
            EXECUTE format(
                'CREATE TABLE IF NOT EXISTS ist_audit.%I PARTITION OF ist_audit.audit_log
                 FOR VALUES FROM (%L) TO (%L)', part_name, range_start, range_end
            );
            RAISE NOTICE '创建分区: ist_audit.%', part_name;
        END IF;
    END LOOP;
END;
$fn$;
"""

_PARTITION_DROP_FN = """\
CREATE OR REPLACE FUNCTION ist_audit.drop_old_audit_partitions(keep_weeks INT DEFAULT 8)
RETURNS void LANGUAGE plpgsql AS $fn$
DECLARE
    cutoff DATE := date_trunc('week', CURRENT_DATE)::DATE - (keep_weeks * 7);
    r RECORD;
BEGIN
    FOR r IN SELECT inhrelid::regclass::text AS child_name
             FROM pg_inherits i JOIN pg_class p ON i.inhparent = p.oid
             JOIN pg_namespace n ON n.oid = p.relnamespace
             WHERE n.nspname = 'ist_audit' AND p.relname = 'audit_log'
             AND (SELECT relname FROM pg_class WHERE oid = i.inhrelid) < 'audit_log_' || to_char(cutoff, 'YYYYMMDD')
    LOOP
        EXECUTE format('DROP TABLE IF EXISTS ist_audit.%I', r.child_name);
        RAISE NOTICE '已清理旧分区: %', r.child_name;
    END LOOP;
END;
$fn$;
"""


def _migrate_audit_log_partitioned() -> None:
    """将旧非分区 audit_log 迁移为按周分区表，并建分区覆盖旧数据。"""
    def _exec_ddl(cur, ddl_text: str) -> None:
        for stmt in ddl_text.split(';'):
            stmt = stmt.strip()
            if stmt:
                cur.execute(stmt)

    # 1. 检查 audit_log 当前状态
    with pg_cursor() as cur:
        cur.execute("""
            SELECT relkind FROM pg_class c
            JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE n.nspname = %s AND c.relname = %s
        """, ('ist_audit', 'audit_log'))
        row = cur.fetchone()

        if row is None:
            # 全新安装：建分区表 + 索引
            with pg_cursor() as cur2:
                _exec_ddl(cur2, _PARTITIONED_AUDIT_LOG_DDL)
            logger.info("已创建分区 audit_log 表")
        elif row['relkind'] == 'r':
            # 旧非分区表 → 迁移
            with pg_cursor() as cur2:
                cur2.execute("ALTER TABLE ist_audit.audit_log RENAME TO audit_log_legacy")
            with pg_cursor() as cur2:
                _exec_ddl(cur2, _PARTITIONED_AUDIT_LOG_DDL)

    # 2. 创建维护函数（幂等）
    with pg_cursor() as cur:
        cur.execute(_PARTITION_CREATE_FN)
        cur.execute(_PARTITION_DROP_FN)

    # 3. 建分区：向前 4 周覆盖旧数据，向后 4 周覆盖新数据
    with pg_cursor() as cur:
        cur.execute("SELECT ist_audit.create_audit_partitions(4, 4)")

    # 4. 迁移旧数据（如果有遗留的 legacy 表）
    with pg_cursor() as cur:
        cur.execute("""
            SELECT 1 FROM information_schema.tables
            WHERE table_schema = %s AND table_name = %s
        """, ('ist_audit', 'audit_log_legacy'))
        if cur.fetchone() is None:
            logger.info("无旧表需迁移，跳过")
        else:
            try:
                cur.execute("SELECT count(*) FROM ist_audit.audit_log_legacy")
                cnt = cur.fetchone()['count']
                if cnt > 0:
                    logger.info("迁移 %d 行旧数据...", cnt)
                    cur.execute("""
                        INSERT INTO ist_audit.audit_log (id, user_id, session_id, conversation_id,
                            run_id, thread_id, recorded_at, event_kind, event_summary, event_payload,
                            model_name, token_input, token_output, token_cache_hit, token_cache_miss,
                            tool_name, tool_input, tool_output, tool_duration_ms,
                            file_path, file_operation, source_ip, is_error, error_message,
                            tags, trace_id, category)
                        SELECT id, user_id, session_id, conversation_id,
                            run_id, thread_id, recorded_at, event_kind, event_summary, event_payload,
                            model_name, token_input, token_output, token_cache_hit, token_cache_miss,
                            tool_name, tool_input, tool_output, tool_duration_ms,
                            file_path, file_operation, source_ip, is_error, error_message,
                            tags, trace_id, category
                        FROM ist_audit.audit_log_legacy
                    """)
                    logger.info("迁移完成，共 %d 行", cnt)
            except Exception as exc:
                logger.warning("数据迁移失败（旧表已保留在 audit_log_legacy）: %s", exc)
                return

    # 5. 重置序列，防止新插入 ID 和迁移数据重叠
    with pg_cursor() as cur:
        seq_name_result = cur.execute(
            "SELECT pg_get_serial_sequence('ist_audit.audit_log', 'id') as s"
        )
        seq_name = cur.fetchone()['s']
        if seq_name:
            cur.execute(
                "SELECT setval(%s, (SELECT max(id) FROM ist_audit.audit_log) + 1, false)",
                (seq_name,)
            )
            logger.info("序列 %s 已重置", seq_name)

    # 6. 清理旧表
    with pg_cursor() as cur:
        try:
            cur.execute("DROP TABLE IF EXISTS ist_audit.audit_log_legacy")
        except Exception:
            pass

    # 7. 清理超出 8 周窗口的历史分区（刚迁过来的旧数据可能超出保留期）
    with pg_cursor() as cur:
        cur.execute("SELECT ist_audit.drop_old_audit_partitions(8)")

    logger.info("audit_log 分区迁移完成")

    # 2. 创建维护函数
    with pg_cursor() as cur:
        cur.execute(_PARTITION_CREATE_FN)
        cur.execute(_PARTITION_DROP_FN)

    # 3. 建当前周 + 未来 4 周分区
    with pg_cursor() as cur:
        cur.execute("SELECT ist_audit.create_audit_partitions(4)")

    logger.info("audit_log 分区维护完成")


def _run_partition_maintenance() -> None:
    """维护已有分区：建新分区 + 清理旧分区。"""
    with pg_cursor() as cur:
        cur.execute(_PARTITION_CREATE_FN)
        cur.execute(_PARTITION_DROP_FN)
        # 建未来 4 周分区（back=0 不补历史） + 删 8 周前旧分区
        cur.execute("SELECT ist_audit.create_audit_partitions(0, 4)")
        cur.execute("SELECT ist_audit.drop_old_audit_partitions(8)")


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
