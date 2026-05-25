"""function_llm.resolve_chat_completions_url 单测."""

from __future__ import annotations

from main.function_llm import DASHSCOPE_CHAT_URL, resolve_chat_completions_url


def test_resolve_default():
    assert resolve_chat_completions_url(None) == DASHSCOPE_CHAT_URL


def test_resolve_api_root():
    assert (
        resolve_chat_completions_url("https://api.deepseek.com")
        == "https://api.deepseek.com/chat/completions"
    )


def test_resolve_idempotent_when_already_endpoint():
    full = "https://api.deepseek.com/chat/completions"
    assert resolve_chat_completions_url(full) == full


def test_resolve_strips_trailing_slash():
    assert (
        resolve_chat_completions_url("https://api.deepseek.com/")
        == "https://api.deepseek.com/chat/completions"
    )
