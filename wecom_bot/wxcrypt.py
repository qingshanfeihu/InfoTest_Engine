"""企业微信 WXBizMsgCrypt — 基于 wechatpy 库的薄封装。"""

from __future__ import annotations

import logging

from wechatpy.crypto import WeChatCrypto
from wechatpy.exceptions import (
    WeChatException,
    InvalidSignatureException,
    InvalidAppIdException,
)

logger = logging.getLogger("wecom_bot.crypt")


class WXBizMsgCryptError(Exception):
    pass


class WXBizMsgCrypt:
    """企业微信消息加解密器（委托 wechatpy.WeChatCrypto）。"""

    def __init__(self, token: str, encoding_aes_key: str, corp_id: str) -> None:
        if len(encoding_aes_key) != 43:
            raise WXBizMsgCryptError(
                f"encoding_aes_key 长度必须为 43 字符，实际: {len(encoding_aes_key)}"
            )
        self._corp_id = corp_id
        self._crypto = WeChatCrypto(
            token=token, encoding_aes_key=encoding_aes_key, app_id=corp_id,
        )

    def verify_url(
        self, msg_signature: str, timestamp: str, nonce: str, echostr: str
    ) -> tuple[int, str | None]:
        verify_xml = (
            "<xml>"
            f"<Encrypt><![CDATA[{echostr}]]></Encrypt>"
            "</xml>"
        )
        try:
            plain = self._crypto.decrypt_message(
                verify_xml, msg_signature, timestamp, nonce
            )
            return (0, plain)
        except WeChatException as e:
            logger.error("verify_url 失败: %s", e)
            return (_map_error(e), None)

    def decrypt_msg(
        self, msg_signature: str, timestamp: str, nonce: str, post_data: str
    ) -> tuple[int, str | None]:
        try:
            plain_xml = self._crypto.decrypt_message(
                post_data, msg_signature, timestamp, nonce
            )
            return (0, plain_xml)
        except WeChatException as e:
            logger.error("decrypt_msg 失败: %s", e)
            return (_map_error(e), None)

    def encrypt_msg(
        self, reply_xml: str, nonce: str, timestamp: str | None = None
    ) -> str:
        return self._crypto.encrypt_message(reply_xml, nonce, timestamp)


def _map_error(exc: WeChatException) -> int:
    if isinstance(exc, InvalidSignatureException):
        return -40001
    if isinstance(exc, InvalidAppIdException):
        return -40005
    msg = str(exc).lower()
    if "signature" in msg or "签名" in msg:
        return -40001
    if "xml" in msg or "parse" in msg:
        return -40002
    if "decrypt" in msg or "aes" in msg or "解密" in msg:
        return -40007
    if "corpid" in msg or "appid" in msg:
        return -40005
    return -40007
