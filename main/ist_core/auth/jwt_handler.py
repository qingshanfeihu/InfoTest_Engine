"""纯 Python HS256 JWT 实现，无第三方依赖。

JWT payload 结构：
    {"sub": "<username>", "role": "<role>", "jti": "<uuid_hex>", "iat": <ts>, "exp": <ts>}
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
import uuid


def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(s: str) -> bytes:
    padding = 4 - len(s) % 4
    if padding != 4:
        s += "=" * padding
    return base64.urlsafe_b64decode(s)


def _hmac_sha256(key: bytes, msg: bytes) -> bytes:
    return hmac.new(key, msg, hashlib.sha256).digest()


def _get_secret() -> bytes:
    secret = os.environ.get("IST_JWT_SECRET", "")
    if not secret:
        raise RuntimeError("IST_JWT_SECRET 环境变量未设置，无法签发/校验 JWT")
    return secret.encode("utf-8")


def create_access_token(
    username: str,
    role: str,
    ttl_sec: int | None = None,
) -> tuple[str, str, float]:
    """签发 JWT。

    Returns:
        (jwt_token, jti, expires_at)
    """
    ttl = ttl_sec or int(os.environ.get("IST_SESSION_TTL_SEC", "28800"))
    now = time.time()
    jti = uuid.uuid4().hex
    payload = {
        "sub": username,
        "role": role,
        "jti": jti,
        "iat": now,
        "exp": now + ttl,
    }
    header = _b64url_encode(json.dumps({"alg": "HS256", "typ": "JWT"}).encode())
    body = _b64url_encode(json.dumps(payload).encode())
    signing_input = f"{header}.{body}".encode()
    sig = _b64url_encode(_hmac_sha256(_get_secret(), signing_input))
    return f"{header}.{body}.{sig}", jti, payload["exp"]


def decode_access_token(token: str) -> dict | None:
    """校验 JWT 签名和过期时间。

    Returns:
        payload dict 或 None（签名无效 / 过期 / 格式错误）
    """
    try:
        parts = token.split(".")
        if len(parts) != 3:
            return None
        header_b64, body_b64, sig_b64 = parts
        # 校验签名
        signing_input = f"{header_b64}.{body_b64}".encode()
        expected = _b64url_encode(_hmac_sha256(_get_secret(), signing_input))
        if not hmac.compare_digest(sig_b64, expected):
            return None
        # 解码 payload
        payload = json.loads(_b64url_decode(body_b64))
        # 校验过期（30s 容差）
        if time.time() > payload.get("exp", 0) + 30:
            return None
        return payload
    except Exception:
        return None
