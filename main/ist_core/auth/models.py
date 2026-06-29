"""认证领域模型：User / Session dataclass。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional


@dataclass
class User:
    id: str
    username: str
    password_hash: str
    role: str  # admin | reviewer
    account_status: str  # normal | lock | disable
    failed_login_count: int
    locked_until: Optional[datetime]
    created_at: datetime
    updated_at: datetime
    last_login_at: Optional[datetime]

    @classmethod
    def from_row(cls, row: dict) -> User:
        return cls(
            id=str(row["id"]),
            username=row["username"],
            password_hash=row["password_hash"],
            role=row.get("role", "reviewer"),
            account_status=row.get("account_status", "normal"),
            failed_login_count=row.get("failed_login_count", 0),
            locked_until=row.get("locked_until"),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            last_login_at=row.get("last_login_at"),
        )


@dataclass
class Session:
    session_id: str  # {channel}_{ms}_{random8hex}
    user_id: str  # UUID
    jwt_token: str
    created_at: datetime
    expires_at: datetime
    is_valid: bool

    @classmethod
    def from_row(cls, row: dict) -> Session:
        return cls(
            session_id=row["session_id"],
            user_id=str(row["user_id"]),
            jwt_token=row["jwt_token"],
            created_at=row["created_at"],
            expires_at=row["expires_at"],
            is_valid=row.get("is_valid", True),
        )
