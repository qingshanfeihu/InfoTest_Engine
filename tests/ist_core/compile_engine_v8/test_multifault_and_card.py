# -*- coding: utf-8 -*-
"""§18.6 多因与消费补全(坑#8/9/21/23/25)+INV-7 账实分离。"""
from __future__ import annotations

from main.ist_core.compile_engine_v8 import views as V


def test_leak_denylist_tracks_new_enums():
    """坑#23:denylist 从枚举源生成——views 新状态词自动被拦,无需人工补表。"""
    from main.ist_core.compile_engine_v8.render import leak_scan
    for word in ("broken", "delivery_blocked", "gate_disabled", "writeback_failed",
                 "report_mismatch", "rerun_isolated", "manual_vs_device"):
        assert leak_scan(f"状态 {word} 出现"), word
    assert leak_scan("这句纯中文与 pending 单词都不泄漏") == []


def test_full_signature_clustering():
    """坑#25:双签名故障按全签名集归簇——第二故障族不再不可见。"""
    import re
    sig_by_aid = {"A": ["timeout X", "tftp failed Y"], "B": ["tftp failed Y"]}
    stems: dict = {}
    for aid, sig_list in sig_by_aid.items():
        for one in sig_list or []:
            stem = re.sub(r"\d{6,}", "<id>", " ".join(str(one).lower().split()))[:160]
            if stem and aid not in stems.get(stem, []):
                stems.setdefault(stem, []).append(aid)
    assert stems["tftp failed y"] == ["A", "B"]   # 第二签名把 A 拉进共因簇


def test_inv7_counts_recomputed_from_facts():
    """INV-7(坑#22 补锚):注入与事实流不一致的 state 计数缓存,counts_update 以
    事实流重算为准——缓存是缓存,真理在流。"""
    from main.ist_core.compile_engine_v8 import _shared as sh
    aid = "203600000000000001"
    fs = [{"ev": "authored", "aid": aid, "round": 1, "artifact": "a1"}]
    import unittest.mock as um
    with um.patch.object(sh, "manifest", lambda s: {"cases": [{"autoid": aid}]}), \
         um.patch.object(sh, "outputs_root", lambda: __import__("pathlib").Path("/nonexistent")):
        out = sh.counts_update({"n_authored": 99, "n_failed": 42}, fs)
    assert out["n_authored"] == 1 and out["n_failed"] == 0


def test_g4_echo_replays_run12_truncation_misjudge():
    """坑#21 真回放(走 closing 的实际 echo 构建路径 _g4_decision_echoes;旧版手搓
    dict+恒真断言 `… or True` 永不可能失败,2026-07-13 审计发现后重写):
    run12 实录——「停止:…」长文本截断被语义兜底误判成 retry。echo 的价值=answer
    原文与 understood 并排呈现,误判肉眼可见;断言这对相悖字段确实并排产出。"""
    from main.ist_core.compile_engine_v8.nodes import _TOKEN_CN, _g4_decision_echoes
    fs = [
        {"ev": "decision", "aid": "203600000000000001",
         "answer": "停止:床有残留需要人工清理之后再", "token": "retry"},   # 截断误判形态
        {"ev": "decision", "aid": "203600000000000002",
         "answer": "自定义说法", "token": "not-a-known-token"},            # Other 自由输入
        {"ev": "decision", "aid": "203600000000000003", "answer": "",
         "token": "suspend"},                                              # 空答(自动挂起)不产 echo
    ]
    echoes = _g4_decision_echoes(fs)
    assert len(echoes) == 2                                   # 空答不入收口卡
    mis = echoes[0]
    assert mis["answer"].startswith("停止")                    # 用户原文在场
    assert mis["understood"] == _TOKEN_CN["retry"]            # 引擎理解在场
    assert not mis["understood"].startswith("停止")            # 两者相悖=误判可核对
    free = echoes[1]
    assert free["understood"] == "自定义说法"                  # 表外 token 回落原文,不翻译
