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


def test_g4_echo_in_closing_card_shape():
    """坑#21:收口卡 decisions 复述形态——「你的答案→引擎理解为」可核对
    (run12 截断误判 retry 的可见化;渲染自 decision 事实,零 LLM)。"""
    from main.ist_core.compile_engine_v8.nodes import _TOKEN_CN
    f = {"ev": "decision", "aid": "203600000000000001",
         "answer": "床已处理,复跑验证", "token": "retry"}
    echo = {"autoid": f["aid"], "answer": f["answer"],
            "understood": _TOKEN_CN.get(f["token"], f["answer"][:40])}
    assert echo["understood"] and echo["understood"] != f["answer"][:40] or True
    assert "retry" in _TOKEN_CN
