"""密码哈希与验证。

哈希格式：``pbkdf2_sha256$<iterations>$<salt_hex>$<hash_hex>``
与 web_server.py 原有实现兼容，迭代次数 200000。
"""

from __future__ import annotations

import hashlib
import hmac
import secrets

_PBKDF2_ITERATIONS = 200_000


def hash_password(password: str) -> str:
    """生成 ``pbkdf2_sha256$200000$<salt_hex>$<hash_hex>`` 格式的密码哈希。"""
    salt = secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, _PBKDF2_ITERATIONS)
    return f"pbkdf2_sha256${_PBKDF2_ITERATIONS}${salt.hex()}${dk.hex()}"


def verify_password(stored_hash: str, password: str) -> bool:
    """恒定时间校验密码。格式不符或校验失败返回 False。"""
    try:
        algo, iters, salt_hex, want_hex = stored_hash.split("$", 3)
        if algo != "pbkdf2_sha256":
            return False
        dk = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"),
            bytes.fromhex(salt_hex), int(iters),
        )
        return hmac.compare_digest(dk.hex(), want_hex)
    except Exception:
        return False


def verify_password_legacy(user_row: dict, password: str) -> bool:
    """兼容 ssh_users.json 的 password_hash / plaintext 字段。

    用于迁移期间的旧用户验证。迁移完成后可移除。
    """
    stored_hash = user_row.get("password_hash")
    if stored_hash:
        return verify_password(stored_hash, password)
    # 明文兜底（恒定时间比较）
    plain = user_row.get("password")
    if plain is None:
        return False
    return hmac.compare_digest(str(plain), password)
