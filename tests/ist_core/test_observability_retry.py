"""Langfuse handler 初始化韧性:瞬态失败冷却重试,不再进程终身盲跑。

2026-07-13 实证:02:16 启动的 TUI 进程首次 LLM 调用时 auth_check 撞 jp.cloud 读超时
(该端点 07-10/11/12 在 tui.log 反复超时前科)→ 旧版"失败即永久 None"让整个进程全天
零 trace(02:19 与 10:41 两轮 run 盲跑),且异常分支只记 debug 级、tui.log 不可见。
"""
from __future__ import annotations

import sys
import types


def _reset(monkeypatch):
    import main.ist_core.observability as O
    monkeypatch.setattr(O, "_HANDLER", None)
    monkeypatch.setattr(O, "_INIT_DONE", False)
    monkeypatch.setattr(O, "_NEXT_RETRY_TS", 0.0)
    O._STATUS.update(state="uninit", detail="")
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-test")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-test")
    monkeypatch.delenv("LANGFUSE_TRACING_ENABLED", raising=False)
    return O


class _ClientAuthTimeout:
    def auth_check(self):
        raise TimeoutError("HTTPSConnectionPool: Read timed out")


class _ClientOK:
    def auth_check(self):
        return True


def _fake_langfuse(monkeypatch, client_holder):
    fake = types.ModuleType("langfuse")
    fake.get_client = lambda: client_holder["client"]
    fake_lc = types.ModuleType("langfuse.langchain")

    class _Handler:  # 替身 CallbackHandler
        pass

    fake_lc.CallbackHandler = _Handler
    fake.langchain = fake_lc
    monkeypatch.setitem(sys.modules, "langfuse", fake)
    monkeypatch.setitem(sys.modules, "langfuse.langchain", fake_lc)
    return _Handler


def test_transient_auth_failure_recovers_after_cooldown(monkeypatch):
    O = _reset(monkeypatch)
    holder = {"client": _ClientAuthTimeout()}
    handler_cls = _fake_langfuse(monkeypatch, holder)

    assert O.get_langfuse_handler() is None          # 首次:瞬态超时 → 降级
    assert O.langfuse_status()["state"] == "init_failed"
    assert O._INIT_DONE is False and O._NEXT_RETRY_TS > 0   # 非永久放弃

    assert O.get_langfuse_handler() is None          # 冷却期内:不重试不拖慢

    holder["client"] = _ClientOK()                   # 网络恢复
    monkeypatch.setattr(O, "_NEXT_RETRY_TS", 0.0)    # 冷却期已过
    h = O.get_langfuse_handler()
    assert isinstance(h, handler_cls)
    assert O.langfuse_status()["state"] == "ok"
    assert O._INIT_DONE is True                      # 成功后缓存,不再重复 auth


def test_unconfigured_is_permanent_off(monkeypatch):
    O = _reset(monkeypatch)
    monkeypatch.delenv("LANGFUSE_PUBLIC_KEY", raising=False)
    monkeypatch.delenv("LANGFUSE_SECRET_KEY", raising=False)
    assert O.get_langfuse_handler() is None
    assert O.langfuse_status()["state"] == "off"
    assert O._INIT_DONE is True                      # 未配置=确定态,无需反复检查
