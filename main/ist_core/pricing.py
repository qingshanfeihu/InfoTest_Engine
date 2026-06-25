"""LLM 模型定价表 + 成本计算（人民币，元/百万 token）."""

from __future__ import annotations


PRICING_RMB: dict[str, dict[str, float]] = {
    # MiMo-V2.5 系列
    "mimo-v2.5": {"input_miss": 1.0, "input_hit": 0.02, "output": 2.0},
    "mimo-v2.5-pro": {"input_miss": 3.0, "input_hit": 0.025, "output": 6.0},
    # DeepSeek
    "deepseek-v4-flash": {"input_miss": 1.0, "input_hit": 0.02, "output": 2.0},
    "deepseek-v4-pro": {"input_miss": 3.0, "input_hit": 0.025, "output": 6.0},
    "deepseek-chat": {"input_miss": 1.0, "input_hit": 0.02, "output": 2.0},
    "deepseek-reasoner": {"input_miss": 1.0, "input_hit": 0.02, "output": 2.0},
}


def compute_cost_rmb(
    model: str,
    *,
    input_miss: int,
    input_hit: int,
    output: int,
) -> float | None:
    """按模型单价计算成本（元）。未知模型返回 None。"""
    price = PRICING_RMB.get(model)
    if not price:
        return None
    return (
        input_miss * price["input_miss"] / 1_000_000
        + input_hit * price["input_hit"] / 1_000_000
        + output * price["output"] / 1_000_000
    )
