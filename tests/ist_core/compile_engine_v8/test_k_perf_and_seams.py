"""K1/K2 性能刀 + A1 签名归一消费点 + 在途批兼容 + cap-correct 闭环(2026-07-16 追加)。

K1/K2 纯并行/配置化零语义(设计锚=worker fanout 并行既有设计的对称延伸);
normalize 消费点=A1 迁移条款(存量签名跨格式交集不静默失效);
在途批兼容=zhaiyq 续跑收口硬要求(532862 旧 last_run 表单能进缺陷单)。
"""
from __future__ import annotations

import concurrent.futures as cf
import json

from main.ist_core.compile_engine_v8 import _shared as sh
from main.ist_core.compile_engine_v8 import facts as F
from main.ist_core.compile_engine_v8 import nodes as N


# ── K2:fanout 池尺寸真接 IST_FANOUT_CONCURRENCY ────────────────────────────────


def test_fanout_pool_size_env(monkeypatch):
    """env 设 16 → 池 16(此前硬编码 min(8,n),配置不生效);默认 8 行为不变。"""
    monkeypatch.setenv("IST_FANOUT_CONCURRENCY", "16")
    assert N._fanout_pool_size(36) == 16
    assert N._fanout_pool_size(3) == 3          # 案数封顶仍在
    monkeypatch.delenv("IST_FANOUT_CONCURRENCY")
    assert N._fanout_pool_size(36) == 8         # 默认值=旧行为
    assert N._fanout_pool_size(1) == 2          # 下限
    monkeypatch.setenv("IST_FANOUT_CONCURRENCY", "bogus")
    assert N._fanout_pool_size(36) == 8         # 坏值回退默认


# ── K1:last_run 并发写无丢失(submit_attribution 读改写锁) ─────────────────────


def test_submit_attribution_concurrent_no_loss(tmp_path):
    """8 案并发 submit_attribution 同一 last_run.json → 8 条 _attribution 全在
    (无锁时整读改写相互覆盖丢归因——K1 池化的安全前提)。"""
    from main.ist_core.tools.device.fail_attribution import submit_attribution
    aids = [f"20360000000000010{i}" for i in range(8)]
    lr = tmp_path / "last_run.json"
    lr.write_text(json.dumps([
        {"autoid": a, "device_context": f"echo occupied {a[-3:]}", "_round": 1}
        for a in aids]), encoding="utf-8")

    def _one(a):
        return submit_attribution.func(
            xlsx_path=str(lr), autoid=a, layer="V", disposition="reflow",
            evidence=f"occupied {a[-3:]}")

    with cf.ThreadPoolExecutor(max_workers=8) as ex:
        outs = list(ex.map(_one, aids))
    assert all("attribution landed" in o for o in outs), outs
    data = json.loads(lr.read_text(encoding="utf-8"))
    landed = [r["autoid"] for r in data if isinstance(r.get("_attribution"), dict)]
    assert sorted(landed) == sorted(aids), f"并发写丢失:{set(aids) - set(landed)}"


# ── A1 消费点:存量签名跨格式归一(frozen / 跨床反驳) ───────────────────────────

A = "203600000000000001"


def _v(result, sigs, rid, art="a1", bed=""):
    return {"ev": "verdict", "aid": A, "run_id": rid, "ctx": "delivery",
            "result": result, "artifact": art, "volume": "v",
            "signatures": sigs, "bed": bed}


def test_frozen_intersects_across_signature_formats():
    """旧格式脏签名(`p2 in: xxx.txt` 尾)与新格式(`p2`)归一后交集非空 →
    冻结判定跨界轮不静默失效(A1 迁移条款消费点)。"""
    fs = [_v("fail", ["p2 in: 203600000000000001.txt"], "r1"),
          _v("fail", ["p2"], "r2")]
    assert F.frozen(fs, A, "a1") is True
    # 真不同签名归一后仍不相交(归一不制造假交集)
    fs2 = [_v("fail", ["p2 in: x.txt"], "r1"), _v("fail", ["p9"], "r2")]
    assert F.frozen(fs2, A, "a1") is False


def test_cross_bed_refuted_normalizes_stored_signatures():
    """跨床反驳的存量签名交集同过归一(旧∩新非空才能识别同签名跨床复现)。"""
    mine = [_v("fail", ["p2 in: old.txt"], "r1", bed="10.4.127.93"),
            _v("fail", ["p2"], "r2", bed="10.4.127.105")]
    assert N._cross_bed_refuted(mine, mine[-1]) is True
    mine2 = [_v("fail", ["p2 in: old.txt"], "r1", bed="10.4.127.93"),
             _v("fail", ["p9"], "r2", bed="10.4.127.105")]
    assert N._cross_bed_refuted(mine2, mine2[-1]) is False


# ── 在途批兼容:老 run 收账的 dc 行无表单 → closing 从盘上 last_run 回读 ──────────


def test_defect_candidates_backfills_form_from_legacy_last_run():
    """zhaiyq 532862 活体验收点镜像:旧代码收账的 attribution 行无 defect_candidate
    字段,表单躺在 last_run.json——_collect 回读补齐,续跑收口缺陷单字段全。"""
    from main.ist_core.compile_engine_v8 import views as V
    fs = [{"ev": "attribution", "aid": A, "round": 2, "run_id": "r2",
           "layer": "product_defect", "disposition": "defect_candidate",
           "fix_direction": "IPv6 会话保持超时条目不清除",
           "evidence": "Timeout=0 entry"}]          # 老形态:无 form 字段
    vw = {"cases": {A: {"status": V.S_SUSPENDED}}}
    manifest = {"cases": [{"autoid": A, "title": "IPv6 会话保持"}]}
    legacy_lr = {A: {"autoid": A, "_attribution": {
        "layer": "product_defect", "disposition": "defect_candidate",
        "defect_candidate": {"repro": "复现步骤", "expected_with_source": "手册:应清除",
                             "actual": "Timeout=0 条目存活", "version": "10.5.0.585"}}}}
    out = N._collect_defect_candidates(fs, vw, manifest, last_run=legacy_lr)
    assert len(out) == 1
    assert out[0]["form"]["repro"] == "复现步骤"     # 回读补齐
    # 无 last_run 时同一 facts 仍列案(form 缺如实为 None,不丢案)
    out2 = N._collect_defect_candidates(fs, vw, manifest, last_run=None)
    assert len(out2) == 1 and out2[0]["form"] is None


# ── 接线包 2g:cap-correct 闭环(授权轮次 + brief 注入) ─────────────────────────


def test_granted_rounds_counts_cap_correct():
    """cap 题面 Other 纠正(token=correct)=带纠正继续修 → 授权 +2(不计则用户
    纠正意见落账可见但永不行动)。"""
    fs = [{"ev": "decision", "aid": A, "question_id": f"cap:{A}:3",
           "answer": "断言支点错了,改用状态查询", "token": "correct"}]
    assert sh.granted_rounds(fs, A) == 2
    fs.append({"ev": "decision", "aid": A, "question_id": f"cap:{A}:5",
               "answer": "继续", "token": "continue"})
    assert sh.granted_rounds(fs, A) == 4


def test_brief_injects_cap_correction(monkeypatch):
    """cap-correct 的用户纠正原文注入重编 brief(最高权威;此前零消费者)。"""
    from main.ist_core.compile_engine_v8 import briefs as BR
    monkeypatch.setattr(sh, "manifest", lambda st: {"cases": [
        {"autoid": A, "title": "t", "step_intents": []}]})
    fs = [{"ev": "authored", "aid": A, "round": 1, "artifact": "a1"},
          {"ev": "decision", "aid": A, "question_id": f"cap:{A}:3",
           "answer": "断言支点错了,改用状态查询验证", "token": "correct"}]
    b = BR.build_brief(A, {"manifest_ref": "", "max_rounds": 3}, fs)
    assert "<user_adjudication>" in b
    assert "断言支点错了" in b and "highest authority" in b
