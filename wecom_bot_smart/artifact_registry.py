r"""测试资产注册表。

在 DocumentRegistry 之上扩展，管理所有类型的测试产出物：
文档、报告、日志、截图、pcap、配置文件等。

核心能力：
- 按 task_id 关联一次测试任务的所有产出物
- 按 artifact_type 分类管理
- 文档版本追踪（同任务多次生成不覆盖历史）
- 生命周期管理（active → archived）
- 全文搜索（FTS5）

与 DocumentRegistry 的关系：
- DocumentRegistry 管企微云文档 CRUD + 去重
- ArtifactRegistry 管资产全生命周期 + 任务关联
- 两者通过 document_versions 表桥接

用法::

    from wecom_bot_smart.artifact_registry import ArtifactRegistry
    from wecom_bot_smart.artifact_schema import ArtifactType

    ar = ArtifactRegistry()

    # 创建任务
    ar.create_task("TEST-20260713-001", "IPv6 功能测试")

    # 注册资产（关联任务）
    ar.register_artifact(
        artifact_type=ArtifactType.DOCUMENT,
        name="IPv6 测试报告 v1",
        url="https://...",
        related_task_id="TEST-20260713-001",
    )

    # 查询任务的所有资产
    artifacts = ar.get_task_artifacts("TEST-20260713-001")

    # 获取文档最新版本号
    ver = ar.get_next_version("TEST-20260713-001", ArtifactType.DOCUMENT)
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Generator

from .artifact_schema import (
    ArtifactRecord,
    ArtifactType,
    DocumentVersionRecord,
    TaskRecord,
    TaskStatus,
)

logger = logging.getLogger("wecom_bot_smart.artifact_registry")

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
_DEFAULT_DB = str(_PROJECT_ROOT / "workspace" / "outputs" / "artifact_registry.db")

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS tasks (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id    TEXT NOT NULL UNIQUE,
    name       TEXT NOT NULL DEFAULT '',
    status     TEXT NOT NULL DEFAULT 'pending',
    metadata   TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS artifacts (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    artifact_type    TEXT NOT NULL,
    name             TEXT NOT NULL DEFAULT '',
    url              TEXT NOT NULL DEFAULT '',
    docid            TEXT NOT NULL DEFAULT '',
    related_task_id  TEXT NOT NULL DEFAULT '',
    related_case_id  TEXT NOT NULL DEFAULT '',
    version          INTEGER NOT NULL DEFAULT 1,
    status           TEXT NOT NULL DEFAULT 'active',
    metadata         TEXT NOT NULL DEFAULT '{}',
    created_at       TEXT NOT NULL,
    updated_at       TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_artifacts_task
    ON artifacts(related_task_id) WHERE status = 'active';

CREATE INDEX IF NOT EXISTS idx_artifacts_type
    ON artifacts(artifact_type) WHERE status = 'active';

CREATE INDEX IF NOT EXISTS idx_artifacts_case
    ON artifacts(related_case_id) WHERE status = 'active';

CREATE INDEX IF NOT EXISTS idx_artifacts_created
    ON artifacts(created_at DESC);

CREATE TABLE IF NOT EXISTS document_versions (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    artifact_id  INTEGER NOT NULL REFERENCES artifacts(id),
    topic        TEXT NOT NULL DEFAULT '',
    content_hash TEXT NOT NULL DEFAULT '',
    version      INTEGER NOT NULL DEFAULT 1,
    created_at   TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_docver_topic
    ON document_versions(topic);

CREATE VIRTUAL TABLE IF NOT EXISTS artifacts_fts USING fts5(
    name, artifact_type, related_task_id, related_case_id, metadata,
    content='artifacts', content_rowid='id'
);

CREATE TRIGGER IF NOT EXISTS artifacts_ai AFTER INSERT ON artifacts BEGIN
    INSERT INTO artifacts_fts(rowid, name, artifact_type, related_task_id, related_case_id, metadata)
    VALUES (new.id, new.name, new.artifact_type, new.related_task_id, new.related_case_id, new.metadata);
END;

CREATE TRIGGER IF NOT EXISTS artifacts_ad AFTER DELETE ON artifacts BEGIN
    INSERT INTO artifacts_fts(artifacts_fts, rowid, name, artifact_type, related_task_id, related_case_id, metadata)
    VALUES ('delete', old.id, old.name, old.artifact_type, old.related_task_id, old.related_case_id, old.metadata);
END;

CREATE TRIGGER IF NOT EXISTS artifacts_au AFTER UPDATE ON artifacts BEGIN
    INSERT INTO artifacts_fts(artifacts_fts, rowid, name, artifact_type, related_task_id, related_case_id, metadata)
    VALUES ('delete', old.id, old.name, old.artifact_type, old.related_task_id, old.related_case_id, old.metadata);
    INSERT INTO artifacts_fts(rowid, name, artifact_type, related_task_id, related_case_id, metadata)
    VALUES (new.id, new.name, new.artifact_type, new.related_task_id, new.related_case_id, new.metadata);
END;
"""


class ArtifactRegistry:
    """测试资产注册表。

    管理所有测试产出物的生命周期、版本、任务关联。
    基于 SQLite，与 DocumentRegistry 独立（可同库或异库）。

    线程安全：每线程独立连接 + WAL 模式。
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
            conn.executescript(_SCHEMA_SQL)

    # ==================================================================
    # Task CRUD
    # ==================================================================

    def create_task(
        self,
        task_id: str,
        name: str = "",
        status: str = "pending",
        metadata: dict[str, Any] | None = None,
    ) -> int:
        """创建测试任务。task_id 唯一，重复创建返回已有记录 id。"""
        now = time.strftime("%Y-%m-%d %H:%M:%S")
        meta_json = json.dumps(metadata or {}, ensure_ascii=False)

        with self._transaction() as conn:
            existing = conn.execute(
                "SELECT id FROM tasks WHERE task_id = ?", (task_id,),
            ).fetchone()
            if existing:
                return existing["id"]

            cursor = conn.execute(
                "INSERT INTO tasks (task_id, name, status, metadata, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (task_id, name, status, meta_json, now, now),
            )
            return cursor.lastrowid or 0

    def update_task_status(self, task_id: str, status: str) -> bool:
        """更新任务状态。"""
        now = time.strftime("%Y-%m-%d %H:%M:%S")
        with self._transaction() as conn:
            cursor = conn.execute(
                "UPDATE tasks SET status = ?, updated_at = ? WHERE task_id = ?",
                (status, now, task_id),
            )
            return cursor.rowcount > 0

    def get_task(self, task_id: str) -> TaskRecord | None:
        """获取任务详情。"""
        conn = self._get_conn()
        row = conn.execute(
            "SELECT * FROM tasks WHERE task_id = ?", (task_id,),
        ).fetchone()
        return self._row_to_task(row) if row else None

    def list_tasks(self, status: str = "", limit: int = 20) -> list[TaskRecord]:
        """列出任务。"""
        conn = self._get_conn()
        if status:
            rows = conn.execute(
                "SELECT * FROM tasks WHERE status = ? ORDER BY created_at DESC LIMIT ?",
                (status, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM tasks ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [self._row_to_task(r) for r in rows]

    # ==================================================================
    # Artifact CRUD
    # ==================================================================

    def register_artifact(
        self,
        artifact_type: ArtifactType | str,
        name: str,
        url: str = "",
        docid: str = "",
        related_task_id: str = "",
        related_case_id: str = "",
        version: int | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> int:
        """注册测试资产。

        version 为 None 时自动递增（同 task + type 的最大版本 + 1）。
        """
        at = artifact_type if isinstance(artifact_type, str) else artifact_type.value
        now = time.strftime("%Y-%m-%d %H:%M:%S")
        meta_json = json.dumps(metadata or {}, ensure_ascii=False)

        with self._transaction() as conn:
            if version is None and related_task_id:
                row = conn.execute(
                    "SELECT MAX(version) as max_ver FROM artifacts "
                    "WHERE related_task_id = ? AND artifact_type = ?",
                    (related_task_id, at),
                ).fetchone()
                version = (row["max_ver"] or 0) + 1 if row else 1
            elif version is None:
                version = 1

            cursor = conn.execute(
                "INSERT INTO artifacts "
                "(artifact_type, name, url, docid, related_task_id, related_case_id, "
                "version, status, metadata, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, 'active', ?, ?, ?)",
                (at, name, url, docid, related_task_id, related_case_id,
                 version, meta_json, now, now),
            )
            return cursor.lastrowid or 0

    def register_document_version(
        self,
        artifact_id: int,
        topic: str,
        content_hash: str = "",
        version: int = 1,
    ) -> int:
        """记录文档版本（桥接 Artifact ↔ DocumentRegistry）。"""
        now = time.strftime("%Y-%m-%d %H:%M:%S")
        with self._transaction() as conn:
            cursor = conn.execute(
                "INSERT INTO document_versions "
                "(artifact_id, topic, content_hash, version, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (artifact_id, topic, content_hash, version, now),
            )
            return cursor.lastrowid or 0

    def get_artifact(self, artifact_id: int) -> ArtifactRecord | None:
        """按 id 获取资产。"""
        conn = self._get_conn()
        row = conn.execute(
            "SELECT * FROM artifacts WHERE id = ?", (artifact_id,),
        ).fetchone()
        return self._row_to_artifact(row) if row else None

    def get_task_artifacts(
        self,
        task_id: str,
        artifact_type: ArtifactType | str | None = None,
        status: str = "active",
    ) -> list[ArtifactRecord]:
        """获取任务关联的所有资产。可按类型过滤。"""
        conn = self._get_conn()
        if artifact_type:
            at = artifact_type if isinstance(artifact_type, str) else artifact_type.value
            rows = conn.execute(
                "SELECT * FROM artifacts "
                "WHERE related_task_id = ? AND artifact_type = ? AND status = ? "
                "ORDER BY version DESC",
                (task_id, at, status),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM artifacts "
                "WHERE related_task_id = ? AND status = ? "
                "ORDER BY artifact_type, version DESC",
                (task_id, status),
            ).fetchall()
        return [self._row_to_artifact(r) for r in rows]

    def get_next_version(
        self,
        task_id: str,
        artifact_type: ArtifactType | str,
    ) -> int:
        """获取下一个版本号。"""
        at = artifact_type if isinstance(artifact_type, str) else artifact_type.value
        conn = self._get_conn()
        row = conn.execute(
            "SELECT MAX(version) as max_ver FROM artifacts "
            "WHERE related_task_id = ? AND artifact_type = ?",
            (task_id, at),
        ).fetchone()
        return (row["max_ver"] or 0) + 1 if row else 1

    def archive_artifact(self, artifact_id: int) -> bool:
        """归档资产（active → archived）。"""
        now = time.strftime("%Y-%m-%d %H:%M:%S")
        with self._transaction() as conn:
            cursor = conn.execute(
                "UPDATE artifacts SET status = 'archived', updated_at = ? "
                "WHERE id = ? AND status = 'active'",
                (now, artifact_id),
            )
            return cursor.rowcount > 0

    # ==================================================================
    # 搜索
    # ==================================================================

    def search_artifacts(self, query: str, limit: int = 10) -> list[ArtifactRecord]:
        """全文搜索资产。"""
        conn = self._get_conn()
        try:
            rows = conn.execute(
                "SELECT a.* FROM artifacts_fts f "
                "JOIN artifacts a ON a.id = f.rowid "
                "WHERE artifacts_fts MATCH ? AND a.status = 'active' "
                "ORDER BY rank LIMIT ?",
                (query, limit),
            ).fetchall()
            return [self._row_to_artifact(r) for r in rows]
        except sqlite3.OperationalError:
            logger.debug("FTS 查询失败，降级到 LIKE: %s", query)
            rows = conn.execute(
                "SELECT * FROM artifacts "
                "WHERE status = 'active' "
                "AND (name LIKE ? OR related_task_id LIKE ? OR metadata LIKE ?) "
                "ORDER BY created_at DESC LIMIT ?",
                (f"%{query}%", f"%{query}%", f"%{query}%", limit),
            ).fetchall()
            return [self._row_to_artifact(r) for r in rows]

    def get_document_versions(self, topic: str) -> list[DocumentVersionRecord]:
        """获取某文档主题的所有版本记录。"""
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT * FROM document_versions WHERE topic = ? ORDER BY version DESC",
            (topic,),
        ).fetchall()
        return [
            DocumentVersionRecord(
                id=r["id"],
                artifact_id=r["artifact_id"],
                topic=r["topic"],
                content_hash=r["content_hash"],
                version=r["version"],
                created_at=r["created_at"],
            )
            for r in rows
        ]

    # ==================================================================
    # 统计
    # ==================================================================

    def count_artifacts(
        self,
        task_id: str = "",
        artifact_type: ArtifactType | str | None = None,
        status: str = "active",
    ) -> int:
        """统计资产数量。"""
        conn = self._get_conn()
        conditions = ["status = ?"]
        params: list[Any] = [status]
        if task_id:
            conditions.append("related_task_id = ?")
            params.append(task_id)
        if artifact_type:
            at = artifact_type if isinstance(artifact_type, str) else artifact_type.value
            conditions.append("artifact_type = ?")
            params.append(at)
        where = " AND ".join(conditions)
        row = conn.execute(
            f"SELECT COUNT(*) as cnt FROM artifacts WHERE {where}", params,
        ).fetchone()
        return row["cnt"] if row else 0

    # ==================================================================
    # 内部
    # ==================================================================

    @staticmethod
    def _row_to_task(row: sqlite3.Row) -> TaskRecord:
        try:
            meta = json.loads(row["metadata"]) if row["metadata"] else {}
        except (ValueError, TypeError):
            meta = {}
        return TaskRecord(
            id=row["id"],
            task_id=row["task_id"],
            name=row["name"],
            status=row["status"],
            metadata=meta,
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    @staticmethod
    def _row_to_artifact(row: sqlite3.Row) -> ArtifactRecord:
        try:
            meta = json.loads(row["metadata"]) if row["metadata"] else {}
        except (ValueError, TypeError):
            meta = {}
        return ArtifactRecord(
            id=row["id"],
            artifact_type=row["artifact_type"],
            name=row["name"],
            url=row["url"],
            docid=row["docid"],
            related_task_id=row["related_task_id"],
            related_case_id=row["related_case_id"],
            version=row["version"],
            status=row["status"],
            metadata=meta,
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )
