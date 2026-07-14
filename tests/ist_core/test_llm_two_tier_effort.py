"""两档模型收敛 + reasoning_effort 通道(2026-07-06 配置简化)。

IST_MODEL 主档单源(旧 REVIEW/OPUS/SONNET 合并)、IST_FLASH 省钱档(旧 HAIKU 合并,
兼容回落);思考默认开、effort 默认 high(2026-07-06 实跑对照 max 无增益降回),
IST_EFFORT=max 全局升档,fork frontmatter effort: 按点覆盖;仅 deepseek 族注入
(其他族支持面未证实)。
"""
import pytest

from main.ist_core.agents import _llm


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for k in ("IST_MODEL", "IST_REVIEW_MODEL", "IST_OPUS_MODEL", "IST_SONNET_MODEL",
              "IST_HAIKU_MODEL", "IST_FLASH", "IST_EFFORT", "IST_THINKING"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "dummy-key-for-ctor")


def test_tier_flash_and_haiku_resolve_to_ist_flash(monkeypatch):
    monkeypatch.setenv("IST_MODEL", "pro-x")
    monkeypatch.setenv("IST_FLASH", "flash-x")
    assert _llm.ist_core_tier_model("flash") == "flash-x"
    assert _llm.ist_core_tier_model("haiku") == "flash-x"     # 旧词别名
    assert _llm.ist_core_tier_model("opus") == "pro-x"        # 旧词归主档
    assert _llm.ist_core_tier_model("sonnet") == "pro-x"
    assert _llm.ist_core_tier_model("") == "pro-x"


def test_flash_falls_back_to_legacy_haiku_then_default(monkeypatch):
    monkeypatch.setenv("IST_HAIKU_MODEL", "legacy-haiku")
    assert _llm.ist_core_flash_model() == "legacy-haiku"      # 旧 env 兼容
    monkeypatch.delenv("IST_HAIKU_MODEL")
    assert _llm.ist_core_flash_model() == _llm.DEFAULT_FLASH_MODEL


def test_ist_model_takes_priority_over_legacy_review(monkeypatch):
    monkeypatch.setenv("IST_MODEL", "main-model")
    monkeypatch.setenv("IST_REVIEW_MODEL", "legacy-review")
    assert _llm.ist_core_default_model() == "main-model"
    monkeypatch.delenv("IST_MODEL")
    assert _llm.ist_core_default_model() == "legacy-review"   # 旧环境不崩


def _extra_body(model):
    eb = getattr(model, "extra_body", None)
    if eb is None:
        eb = (getattr(model, "model_kwargs", None) or {}).get("extra_body") or {}
    return eb or {}


def test_effort_defaults_to_high_for_deepseek_thinking():
    # 2026-07-06 用户拍板:34-case 实跑对照 max 无更好表现——默认降回 high
    m = _llm._build_chat_model("deepseek-v4-pro")
    eb = _extra_body(m)
    assert eb.get("thinking", {}).get("type") == "enabled"    # 思考默认开
    assert eb.get("reasoning_effort") == "high"               # 深度默认 high


def test_effort_global_env_and_per_call_override(monkeypatch):
    monkeypatch.setenv("IST_EFFORT", "max")
    assert _extra_body(_llm._build_chat_model("deepseek-v4-flash")).get("reasoning_effort") == "max"
    # 调用点显式覆盖优先于全局
    monkeypatch.setenv("IST_EFFORT", "high")
    assert _extra_body(_llm._build_chat_model("deepseek-v4-pro", effort="max")).get("reasoning_effort") == "max"
    # 非法值按 high 处理
    monkeypatch.setenv("IST_EFFORT", "ultra")
    assert _extra_body(_llm._build_chat_model("deepseek-v4-pro")).get("reasoning_effort") == "high"


def test_effort_not_injected_for_non_deepseek_or_thinking_off(monkeypatch):
    assert "reasoning_effort" not in _extra_body(_llm._build_chat_model("mimo-v2.5-pro"))
    monkeypatch.setenv("IST_THINKING", "off")
    assert "reasoning_effort" not in _extra_body(_llm._build_chat_model("deepseek-v4-pro"))


def test_fork_spec_carries_effort_field():
    from main.ist_core.skills.loader import load_subagent
    spec = load_subagent("compile-worker")
    assert spec is not None and "effort" in spec              # 字段存在(默认空=全局)
