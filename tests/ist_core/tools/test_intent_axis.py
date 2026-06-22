"""qa_lookup_pattern 意图轴：向后兼容 + 意图索引 + 双轴融合（PLAN §阶段一·补）。"""

from __future__ import annotations

from main.ist_core.tools.device import precedent_tools as pt


def test_intent_tokens_handles_cjk_bigram_and_ascii():
    toks = pt._intent_tokens("SSL通道建立")
    assert "ssl" in toks
    assert "通道" in toks  # bigram
    assert "道建" in toks


def test_intent_similarity_zero_on_empty():
    assert pt._intent_similarity("", ["任意意图路径"]) == 0.0
    assert pt._intent_similarity("需求", []) == 0.0


def test_intent_similarity_higher_for_overlap():
    paths = ["161148 > 两台设备分别是rhost和vhost > SSL通道能够建立"]
    hi = pt._intent_similarity("SSL通道能够建立 rhost vhost", paths)
    lo = pt._intent_similarity("完全无关的负载均衡轮询", paths)
    assert hi > lo


def test_lookup_pattern_both_empty_errors():
    r = pt.qa_lookup_pattern.invoke({"my_config": "", "intent": ""})
    assert r.startswith("error")


def test_lookup_pattern_intent_only_does_not_error_on_empty_config():
    # 分布外：my_config 空但 intent 非空 → 走纯意图轴，不报 "my_config 为空" 错。
    r = pt.qa_lookup_pattern.invoke({
        "my_config": "", "intent": "SSL通道能够建立", "limit": 2,
    })
    assert not r.startswith("error: my_config")
