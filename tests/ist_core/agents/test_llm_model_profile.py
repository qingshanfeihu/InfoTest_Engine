"""模型窗口 profile → deepagents 摘要 fraction 阈值激活(2026-07-08 修复锚定)。

背景:deepagents compute_summarization_defaults 仅当 model.profile 带 max_input_tokens
才用 fraction(0.85 触发/0.10 保留);自定义 ChatOpenAI 的 profile 恒 None → 此前一直走
"tokens=170000 + keep 6 条消息"兜底——对实测 1,048,565 token 窗口(deepseek-v4-pro/flash
超限报错原文)的 16% 就砍到 6 条。本测锚定:profile 默认挂载、fraction 生效、env 逃生口。
"""
from __future__ import annotations

import pytest

pytest.importorskip("deepagents")


@pytest.fixture()
def _env(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-dummy")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://api.example.com")
    monkeypatch.delenv("IST_MODEL_CTX", raising=False)


def test_profile_default_activates_fraction(_env):
    from main.ist_core.agents._llm import _build_chat_model
    from deepagents.middleware.summarization import compute_summarization_defaults

    m = _build_chat_model("deepseek-v4-pro")
    assert m.profile == {"max_input_tokens": 1048565}
    d = compute_summarization_defaults(m)
    assert d["trigger"] == ("fraction", 0.85)
    assert d["keep"] == ("fraction", 0.1)


def test_profile_env_override_and_escape(monkeypatch, _env):
    from main.ist_core.agents._llm import _build_chat_model
    from deepagents.middleware.summarization import compute_summarization_defaults

    monkeypatch.setenv("IST_MODEL_CTX", "400000")
    assert _build_chat_model("deepseek-v4-pro").profile == {"max_input_tokens": 400000}

    # 0/负值 = 不挂 profile,退回 deepagents 兜底档(tokens=170000)——行为逃生口
    monkeypatch.setenv("IST_MODEL_CTX", "0")
    m = _build_chat_model("deepseek-v4-pro")
    assert m.profile is None
    assert compute_summarization_defaults(m)["trigger"] == ("tokens", 170000)


def test_explicit_profile_kwarg_not_overwritten(_env):
    from main.ist_core.agents._llm import _build_chat_model

    m = _build_chat_model("deepseek-v4-pro", profile={"max_input_tokens": 12345})
    assert m.profile == {"max_input_tokens": 12345}
