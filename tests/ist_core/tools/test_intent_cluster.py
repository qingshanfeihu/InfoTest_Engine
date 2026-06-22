"""V3 步骤3：意图族聚类（H_G 摊销）。"""

from __future__ import annotations

from main.ist_core.tools.device.intent_cluster import (
    cluster_by_intent, summarize_families, _pair_similarity,
)


def test_pair_similarity_basic():
    assert _pair_similarity("sdns 监听器健康检查", "sdns 监听器健康检查") == 1.0
    assert _pair_similarity("", "x") == 0.0
    assert 0.0 < _pair_similarity("sdns 监听器配置", "sdns 监听器删除") < 1.0


def test_cluster_same_intent_one_family():
    cases = [
        {"key": "a", "intent": "sdns 监听器健康检查配置"},
        {"key": "b", "intent": "sdns 监听器健康检查配置"},
        {"key": "c", "intent": "sdns 监听器健康检查配置"},
    ]
    fams = cluster_by_intent(cases, threshold=0.5)
    assert len(fams) == 1
    assert fams[0].size() == 3
    assert fams[0].head_key == "a"


def test_cluster_distinct_intents_separate_families():
    cases = [
        {"key": "a", "intent": "sdns 监听器健康检查"},
        {"key": "b", "intent": "slb 会话保持轮询权重"},
        {"key": "c", "intent": "ssl 证书加密套件协商"},
    ]
    fams = cluster_by_intent(cases, threshold=0.5)
    assert len(fams) == 3
    assert all(f.size() == 1 for f in fams)


def test_cluster_mixed():
    cases = [
        {"key": "a", "intent": "sdns 监听器健康检查超时"},
        {"key": "b", "intent": "sdns 监听器健康检查间隔"},
        {"key": "c", "intent": "ssl 证书协商失败告警"},
    ]
    fams = cluster_by_intent(cases, threshold=0.3)
    # a,b 同族(共享 sdns/监听/听器/健康/康检/检查)，c 独立
    sizes = sorted(f.size() for f in fams)
    assert sizes == [1, 2]


def test_cluster_deterministic():
    cases = [{"key": str(i), "intent": f"sdns 监听器配置 {i}"} for i in range(5)]
    f1 = cluster_by_intent(cases, 0.4)
    f2 = cluster_by_intent(cases, 0.4)
    assert [f.member_keys for f in f1] == [f.member_keys for f in f2]


def test_cluster_empty():
    assert cluster_by_intent([], 0.5) == []


def test_summarize_families():
    cases = [
        {"key": "a", "intent": "sdns 监听器健康检查"},
        {"key": "b", "intent": "sdns 监听器健康检查"},
        {"key": "c", "intent": "ssl 证书协商"},
    ]
    fams = cluster_by_intent(cases, 0.5)
    s = summarize_families(fams)
    assert "2 族" in s and "3 case" in s
    assert "3→2" in s  # H_G 摊销：3 次骨架推导降到 2 次
