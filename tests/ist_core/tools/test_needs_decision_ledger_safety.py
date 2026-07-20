"""P0 批前:needs_decision 台账加固(读损不清账 / 原子写 / 不作假承诺)。

三件安全性缺陷同型出现在 emit 两出口(command_existence / missing_teardown):
① parse 失败静默 `pass` → data 停在空 claims → 整份覆写把**其他门**的 claims 一起抹掉
   (用户题面凭空消失,无痕迹);
② 裸 `write_text` 被 Ctrl-C/崩溃打断留截断台账(96 份交付中 1 份实证);
③ 落盘只 debug 吞掉,返回文本却承诺 "ledger entry is already written"——台账没写成
   而 LLM 被告知已写,用户面少一道题且无人知道。

本组只测这三件安全性;两出口是否统一走 `_land_needs_decision` 的合并语义属行为面
变更,归 #62。
"""
from __future__ import annotations

import json



from main.ist_core.tools.device.emit_xlsx_tool import _read_claims_ledger


# ------------------------------------------------------- ① 读损不清账(核心回归)
def test_corrupt_ledger_returns_none_so_caller_skips_write(tmp_path):
    ndp = tmp_path / "needs_decision.json"
    ndp.write_text('{"autoid": "1", "claims": [{"claim_kind": "oth', encoding="utf-8")  # 截断
    assert _read_claims_ledger(ndp, "1") is None, "读损必须返回 None(调用方据此跳过覆写)"


def test_structurally_wrong_ledger_also_returns_none(tmp_path):
    ndp = tmp_path / "needs_decision.json"
    ndp.write_text('{"autoid": "1", "claims": "not-a-list"}', encoding="utf-8")
    assert _read_claims_ledger(ndp, "1") is None


def test_missing_file_returns_fresh_ledger(tmp_path):
    got = _read_claims_ledger(tmp_path / "nope.json", "205400000000000003")
    assert got == {"autoid": "205400000000000003", "claims": []}


def test_healthy_ledger_is_returned_verbatim(tmp_path):
    ndp = tmp_path / "needs_decision.json"
    payload = {"autoid": "1", "claims": [{"claim_kind": "other_gate", "reason": "keep me"}]}
    ndp.write_text(json.dumps(payload), encoding="utf-8")
    assert _read_claims_ledger(ndp, "1") == payload


def test_corrupt_ledger_is_left_untouched_and_reported_not_landed(tmp_path, monkeypatch):
    """核心回归:台账读损时不得覆写(其他门 claims 不能被抹),且返回 False=不许承诺已落账。"""
    import main.ist_core.tools.device.emit_xlsx_tool as et

    outd = tmp_path / "205400000000000003"
    outd.mkdir()
    ndp = outd / "needs_decision.json"
    corrupt = '{"autoid": "205400000000000003", "claims": [{"claim_kind": "other_ga'
    ndp.write_text(corrupt, encoding="utf-8")
    monkeypatch.setattr(et._sh, "outputs_root", lambda: tmp_path)

    landed = et._land_claims("205400000000000003",
                             lambda claims: claims + [{"claim_kind": "command_existence"}],
                             gate="command_existence")
    assert landed is False
    assert ndp.read_text(encoding="utf-8") == corrupt, "读损台账被覆写=其他门 claims 遭清除"


def test_other_gates_claims_survive_a_second_gate_landing(tmp_path, monkeypatch):
    """健康台账上落新 claim,**其他门的既有 claim 必须还在**(旧 bug 的正向面)。"""
    import main.ist_core.tools.device.emit_xlsx_tool as et

    outd = tmp_path / "1"
    outd.mkdir()
    ndp = outd / "needs_decision.json"
    ndp.write_text(json.dumps({"autoid": "1", "claims": [
        {"claim_kind": "verification_path_absent", "reason": "keep me"}]}), encoding="utf-8")
    monkeypatch.setattr(et._sh, "outputs_root", lambda: tmp_path)

    assert et._land_claims("1", lambda c: c + [{"claim_kind": "missing_teardown"}],
                           gate="missing_teardown") is True
    kinds = [c["claim_kind"] for c in json.loads(ndp.read_text(encoding="utf-8"))["claims"]]
    assert kinds == ["verification_path_absent", "missing_teardown"], kinds


# ---------------------------------------------------------------- ② 原子写
def test_landing_goes_through_atomic_writer(tmp_path, monkeypatch):
    """落盘走 _write_json_atomic(tmp+os.replace),不留半写窗口、不留 tmp 残骸。"""
    import main.ist_core.tools.device.emit_xlsx_tool as et
    import main.ist_core.tools.device.verifiability_tool as vt

    outd = tmp_path / "1"
    outd.mkdir()
    monkeypatch.setattr(et._sh, "outputs_root", lambda: tmp_path)
    seen = {}
    real = vt._write_json_atomic

    def _spy(path, obj):
        seen["path"] = path
        return real(path, obj)

    monkeypatch.setattr(vt, "_write_json_atomic", _spy)
    assert et._land_claims("1", lambda c: c + [{"claim_kind": "command_existence"}],
                           gate="command_existence") is True
    assert seen.get("path") == outd / "needs_decision.json", "未走原子写入口"
    assert not list(outd.glob("*.tmp")), "原子写残留 tmp 文件"


# ------------------------------------------------------------ ③ 不作假承诺
def test_write_failure_reports_not_landed(tmp_path, monkeypatch):
    import main.ist_core.tools.device.emit_xlsx_tool as et
    import main.ist_core.tools.device.verifiability_tool as vt

    (tmp_path / "1").mkdir()
    monkeypatch.setattr(et._sh, "outputs_root", lambda: tmp_path)

    def _boom(path, obj):
        raise OSError("disk full")

    monkeypatch.setattr(vt, "_write_json_atomic", _boom)
    assert et._land_claims("1", lambda c: c, gate="command_existence") is False


def test_gate_text_promise_is_conditioned_on_landing():
    """两出口的返回文本必须由 ledger_landed 派生,不再无条件承诺 already written。"""
    import inspect
    import main.ist_core.tools.device.emit_xlsx_tool as et

    src = inspect.getsource(et)
    assert src.count("ledger write FAILED") >= 2, "两出口都要有落账失败的如实分支"
    for seg in src.split("ledger_landed = _land_claims")[1:]:
        head = seg[:2000]
        assert "if ledger_landed" in head, "承诺句未与真实落账结果绑定"


def test_verifiability_reports_failed_ledger_write(monkeypatch):
    """verifiability_tool:_land_needs_decision 返回 False 时随文如实报(补 :267 缺口)。"""
    import main.ist_core.tools.device.verifiability_tool as vt
    monkeypatch.setattr(vt, "_land_needs_decision", lambda *a, **k: False)
    # 数学恒假的序列(period=2 等权轮转下 found[0,1] 跨了两个剩余类)→ 走落账分支
    out = vt.compile_check_verifiability.func(
        autoid="205400000000000003", algo="rr", n_requests=4, n_pools=2,
        claim_kind="rotation_order",
        sequence_json='["found","found","not_found","not_found"]',
        cycle_kind="uniform_rotation",
    )
    assert "NEEDS_USER_DECISION" in out, f"未走 sequence_periodicity 落账分支:{out}"
    assert "FAILED" in out, f"落账失败却未随文报告:{out}"


def test_verifiability_stays_silent_when_ledger_lands(monkeypatch):
    """落账成功时不得平白喊 FAILED(否则告警噪声反噬可信度)。"""
    import main.ist_core.tools.device.verifiability_tool as vt
    monkeypatch.setattr(vt, "_land_needs_decision", lambda *a, **k: True)
    out = vt.compile_check_verifiability.func(
        autoid="205400000000000003", algo="rr", n_requests=4, n_pools=2,
        claim_kind="rotation_order",
        sequence_json='["found","found","not_found","not_found"]',
        cycle_kind="uniform_rotation",
    )
    assert "NEEDS_USER_DECISION" in out and "FAILED" not in out
