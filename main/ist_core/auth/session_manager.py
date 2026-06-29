"""会话管理器：三级回退（JWT → Redis → PG → JWT-only）。

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
        """三级回退校验会话。

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

        # 4. JWT-only 兜底（签名已过，session 不在 PG/Redis，但仍返回 JWT 中的信息）
        return base_info

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
