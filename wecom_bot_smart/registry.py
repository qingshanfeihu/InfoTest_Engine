r"""基于 SQLite 的文档注册表。

替代旧 JSON 文件方案（DocRegistry in tools.py），
支持 topic 去重、版本历史、全文搜索、内容变更检测。

迁移说明：
    - 旧 ``workspace/outputs/doc_registry.json`` 保留不删
    - 新注册表用 ``workspace/outputs/doc_registry.db``
    - ``lookup()`` / ``register()`` / ``list_recent()`` 接口兼容旧 DocRegistry
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Generator

logger = logging.getLogger("wecom_bot_smart.registry")

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
_DEFAULT_DB = str(_PROJECT_ROOT / "workspace" / "outputs" / "doc_registry.db")

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS documents (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    topic        TEXT NOT NULL,
    docid        TEXT NOT NULL DEFAULT '',
    url          TEXT NOT NULL DEFAULT '',
    title        TEXT NOT NULL DEFAULT '',
    doc_type     TEXT NOT NULL DEFAULT 'report',
    status       TEXT NOT NULL DEFAULT 'active',
    content_hash TEXT NOT NULL DEFAULT '',
    owner_userid TEXT NOT NULL DEFAULT '',
    scope        TEXT NOT NULL DEFAULT 'private',
    chat_id      TEXT NOT NULL DEFAULT '',
    creator_type TEXT NOT NULL DEFAULT 'user',
    metadata     TEXT NOT NULL DEFAULT '{}',
    created_at   TEXT NOT NULL,
    updated_at   TEXT NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_documents_owner_topic_active
    ON documents(owner_userid, topic) WHERE status = 'active';

CREATE TABLE IF NOT EXISTS document_history (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    document_id  INTEGER NOT NULL REFERENCES documents(id),
    action       TEXT NOT NULL,
    content_hash TEXT NOT NULL DEFAULT '',
    metadata     TEXT NOT NULL DEFAULT '{}',
    created_at   TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_history_doc
    ON document_history(document_id);

CREATE INDEX IF NOT EXISTS idx_documents_created
    ON documents(created_at DESC);

CREATE INDEX IF NOT EXISTS idx_documents_owner
    ON documents(owner_userid) WHERE status = 'active';

CREATE INDEX IF NOT EXISTS idx_documents_chat
    ON documents(chat_id) WHERE status = 'active' AND chat_id != '';

CREATE VIRTUAL TABLE IF NOT EXISTS documents_fts USING fts5(
    title, topic, metadata, content='documents', content_rowid='id'
);

CREATE TRIGGER IF NOT EXISTS documents_ai AFTER INSERT ON documents BEGIN
    INSERT INTO documents_fts(rowid, title, topic, metadata)
    VALUES (new.id, new.title, new.topic, new.metadata);
END;

CREATE TRIGGER IF NOT EXISTS documents_ad AFTER DELETE ON documents BEGIN
    INSERT INTO documents_fts(documents_fts, rowid, title, topic, metadata)
    VALUES ('delete', old.id, old.title, old.topic, old.metadata);
END;

CREATE TRIGGER IF NOT EXISTS documents_au AFTER UPDATE ON documents BEGIN
    INSERT INTO documents_fts(documents_fts, rowid, title, topic, metadata)
    VALUES ('delete', old.id, old.title, old.topic, old.metadata);
    INSERT INTO documents_fts(rowid, title, topic, metadata)
    VALUES (new.id, new.title, new.topic, new.metadata);
END;
"""

# 旧 schema → 新 schema 的 migration SQL（按列增量添加）
_MIGRATION_COLUMNS = [
    ("owner_userid", "TEXT NOT NULL DEFAULT ''"),
    ("scope", "TEXT NOT NULL DEFAULT 'private'"),
    ("chat_id", "TEXT NOT NULL DEFAULT ''"),
    ("creator_type", "TEXT NOT NULL DEFAULT 'user'"),
]

# 用户隔离严格模式：IST_STRICT_USER_ISOLATION=true 时，所有查询必须提供 owner_userid
_STRICT_ISOLATION = os.environ.get("IST_STRICT_USER_ISOLATION", "").strip().lower() in (
    "1", "true", "yes",
)


class PermissionError(Exception):
    """用户隔离权限错误。"""
    pass


@dataclass
class DocumentRecord:
    """文档注册记录。"""

    id: int = 0
    topic: str = ""
    docid: str = ""
    url: str = ""
    title: str = ""
    doc_type: str = "report"
    status: str = "active"
    content_hash: str = ""
    owner_userid: str = ""
    scope: str = "private"
    chat_id: str = ""
    creator_type: str = "user"
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str = ""
    updated_at: str = ""


class DocumentRegistry:
    """基于 SQLite 的文档注册表。

    支持：
    - topic 去重（唯一索引 + 软删除）
    - 版本历史（document_history 表）
    - 全文搜索（FTS5 虚拟表 + 自动触发器同步）
    - 内容变更检测（content_hash 字段）
    - 线程安全（每线程独立连接，WAL 模式）

    兼容旧 DocRegistry JSON 接口（lookup / register / list_recent）。

    用法::

        registry = DocumentRegistry()
        # 注册
        registry.register(topic="report-2026-07-13", docid="abc", url="https://...")
        # 查找
        record = registry.lookup("report-2026-07-13")
        # 搜索
        results = registry.search("IPv6")
        # 历史
        history = registry.get_history("report-2026-07-13")
    """

    def __init__(self, db_path: str | None = None) -> None:
        self._db_path = db_path or _DEFAULT_DB
        self._local = threading.local()
        os.makedirs(os.path.dirname(self._db_path), exist_ok=True)
        self._init_schema()

    # ------------------------------------------------------------------
    # 连接管理
    # ------------------------------------------------------------------

    def _get_conn(self) -> sqlite3.Connection:
        """每线程一个连接（threading.local）。"""
        conn = getattr(self._local, "conn", None)
        if conn is None:
            conn = sqlite3.connect(self._db_path, timeout=10)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA busy_timeout=5000")
            self._local.conn = conn
        return conn

    @contextmanager
    def _transaction(self) -> Generator[sqlite3.Connection, None, None]:
        conn = self._get_conn()
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise

    def _init_schema(self) -> None:
        with self._transaction() as conn:
            # 先检查是否已有旧表
            has_old_table = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='documents'"
            ).fetchone() is not None
            # 如果有旧表，先迁移列
            if has_old_table:
                self._migrate(conn)
            # 再建表/索引/触发器（IF NOT EXISTS 保证幂等）
            conn.executescript(_SCHEMA_SQL)

    @staticmethod
    def _migrate(conn: sqlite3.Connection) -> None:
        """增量迁移：检查旧表结构，添加缺失列。"""
        existing_cols = {row[1] for row in conn.execute("PRAGMA table_info(documents)")}
        for col_name, col_def in _MIGRATION_COLUMNS:
            if col_name not in existing_cols:
                conn.execute(f"ALTER TABLE documents ADD COLUMN {col_name} {col_def}")
                logger.info("DocumentRegistry migration: 添加列 %s", col_name)

        # 迁移旧索引：如果旧的 topic 唯一索引存在，替换为 (owner_userid, topic)
        indexes = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND name='idx_documents_topic_active'"
        ).fetchall()
        if indexes:
            conn.execute("DROP INDEX IF EXISTS idx_documents_topic_active")
            conn.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_documents_owner_topic_active "
                "ON documents(owner_userid, topic) WHERE status = 'active'"
            )
            logger.info("DocumentRegistry migration: 索引 topic → (owner_userid, topic)")

    @staticmethod
    def _require_owner(owner_userid: str, operation: str = "查询") -> None:
        """严格隔离模式下强制要求 owner_userid。"""
        if _STRICT_ISOLATION and not owner_userid:
            raise PermissionError(
                f"STRICT_USER_ISOLATION 模式下{operation}文档必须提供 owner_userid"
            )

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    def register(
        self,
        topic: str,
        docid: str = "",
        url: str = "",
        title: str = "",
        doc_type: str = "report",
        content_hash: str = "",
        owner_userid: str = "",
        scope: str = "private",
        chat_id: str = "",
        creator_type: str = "user",
        metadata: dict[str, Any] | None = None,
    ) -> int:
        """注册新文档。同 owner_userid + topic 的旧记录自动软删除。返回新记录 id。"""
        now = time.strftime("%Y-%m-%d %H:%M:%S")
        meta_json = json.dumps(metadata or {}, ensure_ascii=False)

        with self._transaction() as conn:
            # 软删除同 owner + topic 旧记录
            old = conn.execute(
                "SELECT id FROM documents "
                "WHERE owner_userid = ? AND topic = ? AND status = 'active'",
                (owner_userid, topic),
            ).fetchone()
            if old:
                conn.execute(
                    "UPDATE documents SET status = 'superseded', updated_at = ? "
                    "WHERE id = ?",
                    (now, old["id"]),
                )
                conn.execute(
                    "INSERT INTO document_history "
                    "(document_id, action, content_hash, metadata, created_at) "
                    "VALUES (?, 'superseded', '', '{}', ?)",
                    (old["id"], now),
                )

            cursor = conn.execute(
                "INSERT INTO documents "
                "(topic, docid, url, title, doc_type, status, content_hash, "
                "owner_userid, scope, chat_id, creator_type, metadata, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, 'active', ?, ?, ?, ?, ?, ?, ?, ?)",
                (topic, docid, url, title, doc_type, content_hash,
                 owner_userid, scope, chat_id, creator_type, meta_json, now, now),
            )
            doc_id = cursor.lastrowid or 0

            conn.execute(
                "INSERT INTO document_history "
                "(document_id, action, content_hash, metadata, created_at) "
                "VALUES (?, 'created', ?, ?, ?)",
                (doc_id, content_hash, meta_json, now),
            )

        logger.info(
            "DocumentRegistry: 注册 topic=%s owner=%s docid=%s id=%d",
            topic, owner_userid, docid, doc_id,
        )
        return doc_id

    def lookup(
        self,
        topic: str,
        owner_userid: str = "",
        chat_id: str = "",
    ) -> dict[str, str] | None:
        """按 topic + 用户上下文查找活跃文档。

        隔离规则：
        - owner_userid 非空时，只返回该用户的 private 文档或匹配的 group 文档
        - owner_userid 为空时，返回任意匹配文档（向后兼容）
        - STRICT_USER_ISOLATION 模式下必须提供 owner_userid

        Returns:
            ``{"docid", "url", "title", "created_at", "content_hash", "owner_userid"}`` 或 ``None``
        """
        self._require_owner(owner_userid, "查找")
        conn = self._get_conn()
        if owner_userid:
            row = conn.execute(
                "SELECT * FROM documents "
                "WHERE topic = ? AND status = 'active' "
                "AND ("
                "  (scope = 'private' AND owner_userid = ?) "
                "  OR (scope = 'group' AND chat_id = ? AND chat_id != '') "
                "  OR scope = 'enterprise'"
                ") ORDER BY "
                "  CASE WHEN owner_userid = ? THEN 0 ELSE 1 END, "
                "  created_at DESC LIMIT 1",
                (topic, owner_userid, chat_id, owner_userid),
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT * FROM documents WHERE topic = ? AND status = 'active'",
                (topic,),
            ).fetchone()
        if row is None:
            return None
        return {
            "docid": row["docid"],
            "url": row["url"],
            "title": row["title"],
            "created_at": row["created_at"],
            "content_hash": row["content_hash"],
            "owner_userid": row["owner_userid"],
        }

    def lookup_by_id(self, doc_id: int) -> DocumentRecord | None:
        """按自增 id 查找文档。"""
        conn = self._get_conn()
        row = conn.execute(
            "SELECT * FROM documents WHERE id = ?", (doc_id,),
        ).fetchone()
        if row is None:
            return None
        return self._row_to_record(row)

    def update(
        self,
        topic: str,
        content_hash: str,
        metadata: dict[str, Any] | None = None,
    ) -> bool:
        """更新已有文档的 content_hash 和 metadata。返回是否成功。"""
        now = time.strftime("%Y-%m-%d %H:%M:%S")
        meta_json = json.dumps(metadata or {}, ensure_ascii=False)

        with self._transaction() as conn:
            row = conn.execute(
                "SELECT id FROM documents WHERE topic = ? AND status = 'active'",
                (topic,),
            ).fetchone()
            if row is None:
                return False

            conn.execute(
                "UPDATE documents SET content_hash = ?, metadata = ?, updated_at = ? "
                "WHERE id = ?",
                (content_hash, meta_json, now, row["id"]),
            )
            conn.execute(
                "INSERT INTO document_history "
                "(document_id, action, content_hash, metadata, created_at) "
                "VALUES (?, 'updated', ?, ?, ?)",
                (row["id"], content_hash, meta_json, now),
            )
        logger.info("DocumentRegistry: 更新 topic=%s", topic)
        return True

    def list_recent(
        self,
        limit: int = 10,
        owner_userid: str = "",
        chat_id: str = "",
    ) -> list[dict[str, str]]:
        """列出最近文档。默认只返回当前用户的 private 文档。"""
        self._require_owner(owner_userid, "列出")
        conn = self._get_conn()
        if owner_userid:
            rows = conn.execute(
                "SELECT * FROM documents "
                "WHERE status = 'active' "
                "AND ("
                "  (scope = 'private' AND owner_userid = ?) "
                "  OR (scope = 'group' AND chat_id = ? AND chat_id != '') "
                "  OR scope = 'enterprise'"
                ") ORDER BY created_at DESC LIMIT ?",
                (owner_userid, chat_id, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM documents WHERE status = 'active' "
                "ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [
            {
                "title": r["title"],
                "url": r["url"],
                "created_at": r["created_at"],
                "topic": r["topic"],
                "owner_userid": r["owner_userid"],
            }
            for r in rows
        ]

    # ------------------------------------------------------------------
    # 搜索与历史
    # ------------------------------------------------------------------

    def search(
        self,
        query: str,
        limit: int = 10,
        owner_userid: str = "",
        chat_id: str = "",
    ) -> list[DocumentRecord]:
        """全文搜索文档。默认只搜索当前用户可见的文档。"""
        self._require_owner(owner_userid, "搜索")
        conn = self._get_conn()
        scope_filter = ""
        params: list[Any] = []
        if owner_userid:
            scope_filter = (
                " AND ("
                "  (d.scope = 'private' AND d.owner_userid = ?) "
                "  OR (d.scope = 'group' AND d.chat_id = ? AND d.chat_id != '') "
                "  OR d.scope = 'enterprise'"
                ")"
            )
            params = [owner_userid, chat_id]

        try:
            sql = (
                "SELECT d.* FROM documents_fts f "
                "JOIN documents d ON d.id = f.rowid "
                "WHERE documents_fts MATCH ? AND d.status = 'active' "
                f"{scope_filter} "
                "ORDER BY rank LIMIT ?"
            )
            rows = conn.execute(sql, [query, *params, limit]).fetchall()
            return [self._row_to_record(r) for r in rows]
        except sqlite3.OperationalError:
            logger.debug("FTS 查询失败，降级到 LIKE: %s", query)
            like = f"%{query}%"
            sql = (
                "SELECT * FROM documents d "
                "WHERE d.status = 'active' "
                "AND (d.title LIKE ? OR d.topic LIKE ? OR d.metadata LIKE ?) "
                f"{scope_filter} "
                "ORDER BY d.created_at DESC LIMIT ?"
            )
            rows = conn.execute(sql, [like, like, like, *params, limit]).fetchall()
            return [self._row_to_record(r) for r in rows]

    def get_history(self, topic: str) -> list[dict[str, str]]:
        """获取文档版本历史（created / updated / superseded）。"""
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT h.* FROM document_history h "
            "WHERE h.document_id IN ("
            "  SELECT id FROM documents WHERE topic = ?"
            ") ORDER BY h.created_at DESC",
            (topic,),
        ).fetchall()
        return [
            {
                "action": r["action"],
                "content_hash": r["content_hash"],
                "created_at": r["created_at"],
            }
            for r in rows
        ]

    # ------------------------------------------------------------------
    # 统计
    # ------------------------------------------------------------------

    def count(self, status: str = "active") -> int:
        """按状态统计文档数。"""
        conn = self._get_conn()
        row = conn.execute(
            "SELECT COUNT(*) as cnt FROM documents WHERE status = ?",
            (status,),
        ).fetchone()
        return row["cnt"] if row else 0

    # ------------------------------------------------------------------
    # 内部
    # ------------------------------------------------------------------

    @staticmethod
    def _row_to_record(row: sqlite3.Row) -> DocumentRecord:
        meta_raw = row["metadata"]
        try:
            meta = json.loads(meta_raw) if meta_raw else {}
        except (ValueError, TypeError):
            meta = {}
        return DocumentRecord(
            id=row["id"],
            topic=row["topic"],
            docid=row["docid"],
            url=row["url"],
            title=row["title"],
            doc_type=row["doc_type"],
            status=row["status"],
            content_hash=row["content_hash"],
            owner_userid=row["owner_userid"],
            scope=row["scope"],
            chat_id=row["chat_id"],
            creator_type=row["creator_type"],
            metadata=meta,
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )
