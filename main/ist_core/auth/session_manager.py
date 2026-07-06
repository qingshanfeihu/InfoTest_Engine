"""会话管理器：二级回退（JWT → Redis → PG）。

写入顺序：PG 先写 → Redis 后写。PG 失败则全回滚；Redis 失败仅 warning。
"""

from __future__ import annotations

import json
import logging
import os
import secrets
import time
from typing import Optional

from main.ist_core.auth.db import get_pg_connection, pg_cursor
from main.ist_core.auth.jwt_handler import create_access_token, decode_access_token

logger = logging.getLogger(__name__)


class SessionManager:
    """PG-backed + Redis-cached 会话管理。"""

    def __init__(
        self,
        redis_url: str | None = None,
        session_ttl: int | None = None,
    ):
        self._ttl = session_ttl or int(os.environ.get("IST_SESSION_TTL_SEC", "28800"))
        self._redis = None
        url = redis_url or os.environ.get("IST_REDIS_URL", "")
        if url:
            try:
                import redis
                self._redis = redis.from_url(url, decode_responses=True)
                self._redis.ping()
                logger.info("Redis connected: %s", url.split("@")[-1])
            except Exception as exc:
                logger.warning("Redis unavailable, falling back to PG-only: %s", exc)
                self._redis = None

    # ------------------------------------------------------------------
    # 公共接口
    # ------------------------------------------------------------------

    def create_session(
        self,
        username: str,
        role: str,
        channel: str = "web",
    ) -> tuple[str, str]:
        """创建会话。PG 先写 → Redis 后写。

        Returns:
            (session_id, jwt_token)
        """
        jwt_token, _jti, expires_at = create_access_token(username, role, self._ttl)
        session_id = self._gen_session_id(channel)
        user = self._pg_get_user_by_username(username)
        if not user:
            raise ValueError(f"user not found: {username}")
        user_id = str(user["id"])

        # PG 先写
        self._pg_create(session_id, user_id, jwt_token, expires_at)
        # Redis 后写（失败仅 warning）
        self._redis_set(session_id, {
            "username": username,
            "role": role,
            "user_id": user_id,
            "expires_at": expires_at,
        })
        return session_id, jwt_token

    def validate_session(
        self,
        session_id: str,
        jwt_token: str,
    ) -> Optional[dict]:
        """二级回退校验会话。

        Returns:
            {"username", "role", "session_id"} 或 None
        """
        # 1. JWT 签名校验（本地计算，无 IO）
        payload = decode_access_token(jwt_token)
        if payload is None:
            return None
        base_info = {
            "username": payload["sub"],
            "role": payload["role"],
            "session_id": session_id,
        }

        # 2. Redis 缓存
        cached = self._redis_get(session_id)
        if cached:
            return base_info

        # 3. PG sessions 表
        pg_row = self._pg_validate(session_id)
        if pg_row:
            # 回填 Redis
            self._redis_set(session_id, {
                "username": base_info["username"],
                "role": base_info["role"],
                "user_id": pg_row.get("user_id", ""),
                "expires_at": pg_row["expires_at"].timestamp()
                    if hasattr(pg_row["expires_at"], "timestamp")
                    else float(pg_row["expires_at"]),
            })
            return base_info

        # session 不在 Redis 也不在 PG → 无效
        return None

    def invalidate_session(self, session_id: str) -> None:
        """注销会话：PG 设 is_valid=FALSE → Redis DEL。"""
        self._pg_invalidate(session_id)
        self._redis_delete(session_id)

    # ------------------------------------------------------------------
    # 内部：SessionID 生成
    # ------------------------------------------------------------------

    @staticmethod
    def _gen_session_id(channel: str) -> str:
        """{channel}_{ms_timestamp}_{random8hex}"""
        ms = int(time.time() * 1000)
        rand = secrets.token_hex(4)
        return f"{channel}_{ms}_{rand}"

    # ------------------------------------------------------------------
    # 内部：PG 操作
    # ------------------------------------------------------------------

    @staticmethod
    def _pg_create(session_id: str, user_id: str, jwt_token: str, expires_at: float) -> None:
        from datetime import datetime, timezone
        exp_dt = datetime.fromtimestamp(expires_at, tz=timezone.utc)
        with pg_cursor() as cur:
            cur.execute(
                """INSERT INTO ist_audit.sessions (session_id, user_id, jwt_token, expires_at)
                   VALUES (%s, %s, %s, %s)""",
                (session_id, user_id, jwt_token, exp_dt),
            )

    @staticmethod
    def _pg_validate(session_id: str) -> Optional[dict]:
        with pg_cursor() as cur:
            cur.execute(
                """SELECT session_id, user_id, jwt_token, created_at, expires_at, is_valid
                   FROM ist_audit.sessions
                   WHERE session_id = %s AND is_valid = TRUE""",
                (session_id,),
            )
            row = cur.fetchone()
        if not row:
            return None
        # 检查过期：过期则回写 is_valid=FALSE
        from datetime import datetime, timezone
        if row["expires_at"] < datetime.now(timezone.utc):
            try:
                with pg_cursor() as cur:
                    cur.execute(
                        "UPDATE ist_audit.sessions SET is_valid = FALSE WHERE session_id = %s",
                        (session_id,),
                    )
            except Exception as exc:
                logger.debug("标记过期会话失败 session_id=%s: %s", session_id, exc)
            return None
        return row

    @staticmethod
    def _pg_invalidate(session_id: str) -> None:
        with pg_cursor() as cur:
            cur.execute(
                "UPDATE ist_audit.sessions SET is_valid = FALSE WHERE session_id = %s",
                (session_id,),
            )

    @staticmethod
    def cleanup_expired_sessions() -> int:
        """批量将所有过期会话标记为 is_valid=FALSE。

        Returns:
            受影响的行数。建议定时调用（如每小时一次）。
        """
        from datetime import datetime, timezone
        try:
            with pg_cursor() as cur:
                cur.execute(
                    """UPDATE ist_audit.sessions
                       SET is_valid = FALSE
                       WHERE is_valid = TRUE AND expires_at < %s""",
                    (datetime.now(timezone.utc),),
                )
                count = cur.rowcount
                if count:
                    logger.info("cleanup_expired_sessions: 标记 %d 个过期会话", count)
                return count
        except Exception as exc:
            logger.warning("cleanup_expired_sessions 失败: %s", exc)
            return 0

    @staticmethod
    def _pg_get_user_by_username(username: str) -> Optional[dict]:
        with pg_cursor() as cur:
            cur.execute(
                "SELECT id, username, password_hash, role, account_status FROM ist_audit.users WHERE username = %s",
                (username,),
            )
            return cur.fetchone()

    # ------------------------------------------------------------------
    # 内部：Redis 操作
    # ------------------------------------------------------------------

    def _redis_set(self, session_id: str, data: dict) -> None:
        if not self._redis:
            return
        try:
            self._redis.setex(
                f"ist:sess:{session_id}",
                self._ttl + 300,  # 比 JWT 多 5min 容错
                json.dumps(data, default=str),
            )
        except Exception as exc:
            logger.warning("Redis SET failed for %s: %s", session_id, exc)

    def _redis_get(self, session_id: str) -> Optional[dict]:
        if not self._redis:
            return None
        try:
            raw = self._redis.get(f"ist:sess:{session_id}")
            if raw:
                return json.loads(raw)
        except Exception as exc:
            logger.warning("Redis GET failed for %s: %s", session_id, exc)
        return None

    def _redis_delete(self, session_id: str) -> None:
        if not self._redis:
            return
        try:
            self._redis.delete(f"ist:sess:{session_id}")
        except Exception as exc:
            logger.warning("Redis DEL failed for %s: %s", session_id, exc)

    # ------------------------------------------------------------------
    # 对话（Conversation）管理
    # ------------------------------------------------------------------

    def create_conversation(
        self,
        username: str,
        title: str = "新对话",
        model_name: str | None = None,
        session_id: str | None = None,
    ) -> dict:
        """新建对话。PG 先写 → Redis 后写。"""
        user = self._pg_get_user_by_username(username)
        if not user:
            raise ValueError(f"user not found: {username}")
        user_id = str(user["id"])
        conversation_id = self._gen_session_id("conv")
        now = time.time()

        with pg_cursor() as cur:
            # 先将同用户旧 is_active 设 FALSE
            cur.execute(
                "UPDATE ist_audit.conversations SET is_active = FALSE WHERE user_id = %s AND is_active = TRUE",
                (user_id,),
            )
            cur.execute(
                """INSERT INTO ist_audit.conversations (conversation_id, user_id, session_id, title, model_name)
                   VALUES (%s, %s, %s, %s, %s)""",
                (conversation_id, user_id, session_id, title, model_name),
            )

        conv_data = {
            "conversation_id": conversation_id,
            "session_id": session_id,
            "title": title,
            "model_name": model_name,
            "is_active": True,
            "message_count": 0,
            "created_at": now,
        }
        # Redis 单条缓存
        self._redis_set_conv(conversation_id, conv_data)
        # 【屏蔽切换对话功能】列表缓存失效已注释
        # self._redis_invalidate_conv_list(username)
        return {
            "conversation_id": conversation_id,
            "session_id": session_id,
            "title": title,
            "model_name": model_name,
            "is_active": True,
        }

    # 【屏蔽切换对话功能】列表查询注释
    # def list_conversations(
    #     self,
    #     username: str,
    #     limit: int = 20,
    #     offset: int = 0,
    # ) -> list[dict]:
    #     """列出用户的对话。优先读 Redis 缓存，miss 则查 PG 并回填。"""
    #     cached = self._redis_get_conv_list(username)
    #     if cached is not None:
    #         return cached[offset : offset + limit]
    #
    #     user = self._pg_get_user_by_username(username)
    #     if not user:
    #         return []
    #     user_id = str(user["id"])
    #
    #     with pg_cursor() as cur:
    #         cur.execute(
    #             """SELECT conversation_id, title, model_name, message_count,
    #                       last_message_at, is_active, created_at
    #                FROM ist_audit.conversations
    #                WHERE user_id = %s
    #                ORDER BY last_message_at DESC NULLS LAST, created_at DESC
    #                LIMIT %s""",
    #             (user_id, max(limit + offset, 100)),
    #         )
    #         rows = cur.fetchall()
    #
    #     result = []
    #     for r in rows:
    #         result.append({
    #             "conversation_id": r["conversation_id"],
    #             "title": r["title"],
    #             "model_name": r["model_name"],
    #             "message_count": r["message_count"],
    #             "last_message_at": r["last_message_at"].isoformat() if r["last_message_at"] else None,
    #             "is_active": r["is_active"],
    #             "created_at": r["created_at"].isoformat() if r["created_at"] else None,
    #         })
    #
    #     self._redis_set_conv_list(username, result)
    #     return result[offset : offset + limit]

    # 【屏蔽切换对话功能】单条查询注释
    # def get_conversation(self, username: str, conversation_id: str) -> dict | None:
    #     """获取单个对话详情（Redis → PG 二级回退，校验归属）。"""
    #     # 1. Redis 缓存
    #     cached = self._redis_get_conv(conversation_id)
    #     if cached:
    #         return cached
    #
    #     user = self._pg_get_user_by_username(username)
    #     if not user:
    #         return None
    #     user_id = str(user["id"])
    #
    #     with pg_cursor() as cur:
    #         cur.execute(
    #             """SELECT conversation_id, user_id, title, model_name, message_count,
    #                       last_message_at, is_active, created_at, updated_at
    #                FROM ist_audit.conversations
    #                WHERE conversation_id = %s AND user_id = %s""",
    #             (conversation_id, user_id),
    #         )
    #         row = cur.fetchone()
    #     if not row:
    #         return None
    #
    #     result = {
    #         "conversation_id": row["conversation_id"],
    #         "title": row["title"],
    #         "model_name": row["model_name"],
    #         "message_count": row["message_count"],
    #         "last_message_at": row["last_message_at"].isoformat() if row["last_message_at"] else None,
    #         "is_active": row["is_active"],
    #         "created_at": row["created_at"].isoformat() if row["created_at"] else None,
    #         "updated_at": row["updated_at"].isoformat() if row["updated_at"] else None,
    #     }
    #     # 回填 Redis
    #     self._redis_set_conv(conversation_id, result)
    #     return result

    # 【屏蔽切换对话功能】激活/切换对话注释
    # def activate_conversation(self, username: str, conversation_id: str) -> dict | None:
    #     """切换对话：同用户旧 is_active 设 FALSE，目标设 TRUE。"""
    #     user = self._pg_get_user_by_username(username)
    #     if not user:
    #         return None
    #     user_id = str(user["id"])
    #
    #     old_active_id = self.get_active_conversation_id(username)
    #
    #     with pg_cursor() as cur:
    #         cur.execute(
    #             "UPDATE ist_audit.conversations SET is_active = FALSE WHERE user_id = %s AND is_active = TRUE",
    #             (user_id,),
    #         )
    #         cur.execute(
    #             """UPDATE ist_audit.conversations SET is_active = TRUE, updated_at = now()
    #                WHERE conversation_id = %s AND user_id = %s
    #                RETURNING session_id""",
    #             (conversation_id, user_id),
    #         )
    #         row = cur.fetchone()
    #         if row is None:
    #             return None
    #         session_id = row.get("session_id") or ""
    #
    #     if old_active_id:
    #         self._redis_delete_conv(old_active_id)
    #     self._redis_delete_conv(conversation_id)
    #     self._redis_invalidate_conv_list(username)
    #     thread_id = f"{username}_{session_id}_{conversation_id}" if session_id else f"{username}_{conversation_id}"
    #     return {"conversation_id": conversation_id, "thread_id": thread_id}


# 【屏蔽切换对话功能】删除对话注释
    # def delete_conversation(self, username: str, conversation_id: str) -> bool:
    #     """删除对话（CASCADE 删关联 sessions）。"""
    #     user = self._pg_get_user_by_username(username)
    #     if not user:
    #         return False
    #     user_id = str(user["id"])
    #
    #     with pg_cursor() as cur:
    #         cur.execute(
    #             "DELETE FROM ist_audit.conversations WHERE conversation_id = %s AND user_id = %s",
    #             (conversation_id, user_id),
    #         )
    #         deleted = cur.rowcount > 0
    #
    #     if deleted:
    #         self._redis_delete_conv(conversation_id)
    #         self._redis_invalidate_conv_list(username)
    #     return deleted


# 【屏蔽切换对话功能】重命名对话注释
    # def rename_conversation(self, username: str, conversation_id: str, title: str) -> bool:
    #     """重命名对话。"""
    #     user = self._pg_get_user_by_username(username)
    #     if not user:
    #         return False
    #     user_id = str(user["id"])
    #
    #     with pg_cursor() as cur:
    #         cur.execute(
    #             """UPDATE ist_audit.conversations SET title = %s, updated_at = now()
    #                WHERE conversation_id = %s AND user_id = %s""",
    #             (title, conversation_id, user_id),
    #         )
    #         updated = cur.rowcount > 0
    #
    #     if updated:
    #         self._redis_delete_conv(conversation_id)
    #         self._redis_invalidate_conv_list(username)
    #     return updated

    def increment_message_count(self, conversation_id: str) -> None:
        """递增对话消息计数并更新 last_message_at。同时失效 Redis 单条缓存。"""
        try:
            with pg_cursor() as cur:
                cur.execute(
                    """UPDATE ist_audit.conversations
                       SET message_count = message_count + 1,
                           last_message_at = now(),
                           updated_at = now()
                       WHERE conversation_id = %s""",
                    (conversation_id,),
                )
        except Exception as exc:
            logger.debug("increment_message_count 失败: %s", exc)
        # 使 Redis 单条缓存失效（下次 get_conversation 回填）
        self._redis_delete_conv(conversation_id)

    def get_active_conversation_id(self, username: str) -> str | None:
        """获取用户当前活跃对话 ID。"""
        user = self._pg_get_user_by_username(username)
        if not user:
            return None
        user_id = str(user["id"])

        with pg_cursor() as cur:
            cur.execute(
                """SELECT conversation_id FROM ist_audit.conversations
                   WHERE user_id = %s AND is_active = TRUE
                   ORDER BY updated_at DESC LIMIT 1""",
                (user_id,),
            )
            row = cur.fetchone()
        return row["conversation_id"] if row else None

    # ------------------------------------------------------------------
    # 内部：Redis 对话列表缓存
    # ------------------------------------------------------------------

    # 【屏蔽切换对话功能】Redis 对话列表缓存注释
    # def _redis_get_conv_list(self, username: str) -> list[dict] | None:
    #     if not self._redis:
    #         return None
    #     try:
    #         raw = self._redis.get(f"ist:conv:list:{username}")
    #         if raw:
    #             return json.loads(raw)
    #     except Exception as exc:
    #         logger.warning("Redis GET conv_list failed for %s: %s", username, exc)
    #     return None

    # def _redis_set_conv_list(self, username: str, data: list[dict]) -> None:
    #     if not self._redis:
    #         return
    #     try:
    #         self._redis.setex(
    #             f"ist:conv:list:{username}",
    #             300,  # 5 分钟 TTL
    #             json.dumps(data, default=str),
    #         )
    #     except Exception as exc:
    #         logger.warning("Redis SET conv_list failed for %s: %s", username, exc)

    # def _redis_invalidate_conv_list(self, username: str) -> None:
    #     if not self._redis:
    #         return
    #     try:
    #         self._redis.delete(f"ist:conv:list:{username}")
    #     except Exception as exc:
    #         logger.warning("Redis DEL conv_list failed for %s: %s", username, exc)

    # ------------------------------------------------------------------
    # 内部：Redis 单条 Conversation 缓存
    # ------------------------------------------------------------------

    def _redis_set_conv(self, conversation_id: str, data: dict) -> None:
        """缓存单条 conversation 到 Redis。key: ist:conv:{conversation_id}"""
        if not self._redis:
            return
        try:
            self._redis.setex(
                f"ist:conv:{conversation_id}",
                self._ttl + 300,  # 与 session 一致的 TTL
                json.dumps(data, default=str),
            )
        except Exception as exc:
            logger.warning("Redis SET conv failed for %s: %s", conversation_id, exc)

    def _redis_get_conv(self, conversation_id: str) -> dict | None:
        """从 Redis 读取单条 conversation 缓存。"""
        if not self._redis:
            return None
        try:
            raw = self._redis.get(f"ist:conv:{conversation_id}")
            if raw:
                return json.loads(raw)
        except Exception as exc:
            logger.warning("Redis GET conv failed for %s: %s", conversation_id, exc)
        return None

    def _redis_delete_conv(self, conversation_id: str) -> None:
        """删除单条 conversation 的 Redis 缓存。"""
        if not self._redis:
            return
        try:
            self._redis.delete(f"ist:conv:{conversation_id}")
        except Exception as exc:
            logger.warning("Redis DEL conv failed for %s: %s", conversation_id, exc)

    # ------------------------------------------------------------------
    # is_active 对话控制
    # ------------------------------------------------------------------

    def is_conversation_active(self, username: str, conversation_id: str) -> bool:
        """检查对话是否 is_active=TRUE，同时校验归属。

        is_active=false 的对话禁止触发新 Agent 推理，仅读取 sys_dialog_chat 做页面展示。
        """
        user = self._pg_get_user_by_username(username)
        if not user:
            return False
        user_id = str(user["id"])

        with pg_cursor() as cur:
            cur.execute(
                """SELECT is_active FROM ist_audit.conversations
                   WHERE conversation_id = %s AND user_id = %s""",
                (conversation_id, user_id),
            )
            row = cur.fetchone()
        return bool(row and row.get("is_active"))

    # 【屏蔽切换对话功能】重建 thread_id 注释
    # def build_thread_id(self, username: str, conversation_id: str) -> str | None:
    #     """构建标准 thread_id = {username}_{session_id}_{conversation_id}。
    #
    #     从 conversations 表查出 session_id。若 conversation 不存在或不属于该用户返回 None。
    #     """
    #     user = self._pg_get_user_by_username(username)
    #     if not user:
    #         return None
    #     user_id = str(user["id"])
    #
    #     with pg_cursor() as cur:
    #         cur.execute(
    #             """SELECT session_id FROM ist_audit.conversations
    #                WHERE conversation_id = %s AND user_id = %s""",
    #             (conversation_id, user_id),
    #         )
    #         row = cur.fetchone()
    #     if not row:
    #         return None
    #     session_id = row.get("session_id") or ""
    #     if session_id:
    #         return f"{username}_{session_id}_{conversation_id}"
    #     return f"{username}_{conversation_id}"


# ------------------------------------------------------------------
# 模块级安全获取 SessionManager 单例（供 dialog_sink 等模块使用）
# ------------------------------------------------------------------

_SESSION_MGR: SessionManager | None = None


def _get_session_mgr_safe() -> SessionManager | None:
    """安全获取 SessionManager 单例，避免循环导入。"""
    global _SESSION_MGR
    if _SESSION_MGR is None:
        try:
            _SESSION_MGR = SessionManager()
        except Exception:
            return None
    return _SESSION_MGR
