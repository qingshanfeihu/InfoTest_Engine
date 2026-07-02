"""pricing.compute_cost_rmb：精确命中 / provider 前缀归一 / 未知模型."""

from main.ist_core.pricing import PRICING_RMB, compute_cost_rmb


def test_exact_model_name_hits():
    cost = compute_cost_rmb("deepseek-v4-pro", input_miss=1_000_000, input_hit=0, output=0)
    assert cost == PRICING_RMB["deepseek-v4-pro"]["input_miss"]


def test_provider_prefixed_model_normalizes_to_bare_name():
    # 三方聚合网关形态（如 tokensec）：deepseek/deepseek-v4-pro → deepseek-v4-pro
    bare = compute_cost_rmb("deepseek-v4-pro", input_miss=500_000, input_hit=200_000, output=100_000)
    prefixed = compute_cost_rmb("deepseek/deepseek-v4-pro", input_miss=500_000, input_hit=200_000, output=100_000)
    assert prefixed == bare
    assert prefixed is not None and prefixed > 0


def test_unknown_model_returns_none():
    assert compute_cost_rmb("no-such/model-x", input_miss=1000, input_hit=0, output=0) is None


def test_exact_hit_takes_precedence_over_basename():
    # 若将来收录带前缀的专价键，精确命中应优先于末段归一
    PRICING_RMB["vendor/special-model"] = {"input_miss": 9.0, "input_hit": 9.0, "output": 9.0}
    PRICING_RMB["special-model"] = {"input_miss": 1.0, "input_hit": 1.0, "output": 1.0}
    try:
        cost = compute_cost_rmb("vendor/special-model", input_miss=1_000_000, input_hit=0, output=0)
        assert cost == 9.0
    finally:
        PRICING_RMB.pop("vendor/special-model", None)
        PRICING_RMB.pop("special-model", None)


def test_thinking_param_follows_model_family():
    """thinking 参数 schema 随模型族而非网关(实证同一网关 deepseek=enabled、minimax=adaptive)。"""
    from main.common.llm_helpers import thinking_param_for_model as f
    assert f("mimo-v2.5-pro", True) == {"type": "enabled"}
    assert f("deepseek/deepseek-v4-pro", False) == {"type": "disabled"}
    assert f("minimax/minimax-m3", True) == {"type": "adaptive"}   # enabled 会 400
    assert f("minimax/minimax-m3", False) == {"type": "disabled"}
    assert f("qwen/qwen3.6-plus", True) is None                    # 未知族不注入
    assert f("", True) is None
