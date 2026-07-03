"""企业微信机器人中间件 — FastAPI 主入口。"""

from __future__ import annotations

import logging
import threading
from typing import Callable

from fastapi import BackgroundTasks, FastAPI, Query, Request, Response
from fastapi.responses import PlainTextResponse

from .config import server_config, wecom_config
from .task_handler import handle_message, parse_message_xml
from .wxcrypt import WXBizMsgCrypt

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("wecom_bot.main")

app = FastAPI(title="InfoTest Engine — 企业微信中间件", version="1.0.0",
              docs_url=None, redoc_url=None)

try:
    wecom_config.validate()
    _crypt = WXBizMsgCrypt(
        token=wecom_config.token,
        encoding_aes_key=wecom_config.encoding_aes_key,
        corp_id=wecom_config.corp_id,
    )
    logger.info("WXBizMsgCrypt 初始化成功")
except Exception as e:
    logger.error("配置校验失败: %s", e)
    _crypt = None

_active_threads: set[threading.Thread] = set()


def _spawn_bg_task(callable_: Callable[[], None]) -> None:
    def _wrapper() -> None:
        try:
            callable_()
        finally:
            _active_threads.discard(threading.current_thread())

    t = threading.Thread(target=_wrapper, daemon=True, name="wecom-bg-task")
    _active_threads.add(t)
    t.start()


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "service": "wecom-bot",
        "wecom_configured": wecom_config.is_valid,
        "active_bg_threads": len(_active_threads),
    }


@app.get("/wecom/callback")
async def wecom_verify(
    msg_signature: str = Query(..., alias="msg_signature"),
    timestamp: str = Query(...),
    nonce: str = Query(...),
    echostr: str = Query(...),
):
    if _crypt is None:
        return PlainTextResponse("crypt not initialized", status_code=500)

    ret, plain = _crypt.verify_url(msg_signature, timestamp, nonce, echostr)
    if ret != 0:
        logger.error("URL 验证失败: errcode=%s", ret)
        return PlainTextResponse(f"verify failed: {ret}", status_code=403)

    logger.info("URL 验证成功")
    return PlainTextResponse(plain or "")


@app.post("/wecom/callback")
async def wecom_callback(
    request: Request,
    background_tasks: BackgroundTasks,
    msg_signature: str = Query(..., alias="msg_signature"),
    timestamp: str = Query(...),
    nonce: str = Query(...),
):
    if _crypt is None:
        return PlainTextResponse("crypt not initialized", status_code=500)

    post_data = await request.body()
    post_text = post_data.decode("utf-8")

    ret, plain_xml = _crypt.decrypt_msg(msg_signature, timestamp, nonce, post_text)
    if ret != 0:
        logger.error("消息解密失败: errcode=%s", ret)
        return PlainTextResponse(f"decrypt failed: {ret}", status_code=403)

    if plain_xml is None:
        return PlainTextResponse("decrypt failed", status_code=500)

    try:
        msg = parse_message_xml(plain_xml)
    except Exception:
        logger.exception("XML 解析失败")
        return PlainTextResponse("success", status_code=200)

    try:
        reply_xml, bg_callable = handle_message(msg)
    except Exception:
        logger.exception("handle_message 异常")
        reply_xml = ""
        bg_callable = None

    if bg_callable is not None:
        background_tasks.add_task(_spawn_bg_task, bg_callable)

    if reply_xml:
        try:
            encrypted_reply = _crypt.encrypt_msg(reply_xml, nonce, timestamp)
            return Response(content=encrypted_reply, media_type="application/xml; charset=utf-8")
        except Exception:
            logger.exception("回复加密失败")
            return PlainTextResponse("encrypt failed", status_code=500)

    return PlainTextResponse("success", status_code=200)


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.exception("未捕获异常: %s %s", request.method, request.url)
    return PlainTextResponse("success", status_code=200)


def main():
    import uvicorn
    logger.info("启动 企微中间件: %s:%s", server_config.host, server_config.port)
    uvicorn.run("wecom_bot.main:app", host=server_config.host,
                port=server_config.port, log_level="info")


if __name__ == "__main__":
    main()
