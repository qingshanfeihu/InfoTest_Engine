"""认证与会话管理包。

公共接口：
- db: get_pg_connection, ensure_schema, pg_cursor
- models: User, Session
- password: hash_password, verify_password, verify_password_legacy
- jwt_handler: create_access_token, decode_access_token
- session_manager: SessionManager
- token_aggregator: aggregate_daily_tokens
"""

from main.ist_core.auth.db import ensure_schema, get_pg_connection, pg_cursor
from main.ist_core.auth.jwt_handler import create_access_token, decode_access_token
from main.ist_core.auth.models import Session, User
from main.ist_core.auth.password import hash_password, verify_password, verify_password_legacy
from main.ist_core.auth.session_manager import SessionManager
from main.ist_core.auth.token_aggregator import aggregate_daily_tokens

__all__ = [
    "get_pg_connection",
    "pg_cursor",
    "ensure_schema",
    "User",
    "Session",
    "hash_password",
    "verify_password",
    "verify_password_legacy",
    "create_access_token",
    "decode_access_token",
    "SessionManager",
    "aggregate_daily_tokens",
]
