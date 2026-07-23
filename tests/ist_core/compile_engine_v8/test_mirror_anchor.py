"""mirror 同步锚 M-14/M-15。"""
from __future__ import annotations

from pathlib import Path

from main.ist_core.compile_engine_v8 import mirror_anchor as MA


def test_missing_local_prevents_match_M14(tmp_path):
    """M-14:本地缺锚文件不得报 match;missing_local 必须计算。"""
    root = tmp_path / "mirror"
    # 只放部分锚文件
    kept = MA.ANCHOR_FILES[0]
    (root / kept).parent.mkdir(parents=True)
    (root / kept).write_text("local-only\n", encoding="utf-8")
    rem = {kept: MA.local_hashes(root)[kept]}  # 远端与本地同 hash

    def remote_exec(_cmd):
        # 伪造 sha256sum 输出
        return "\n".join(f"{h}  /x/{rel}" for rel, h in rem.items())

    rep = MA.check_sync(remote_exec, root=root)
    assert rep["missing_local"] == [r for r in MA.ANCHOR_FILES if r != kept]
    assert rep["status"] == "mismatch"
    assert kept in (rep.get("checked") or [])


def test_full_match_when_all_present_M14(tmp_path):
    root = tmp_path / "mirror"
    for rel in MA.ANCHOR_FILES:
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(f"body-{rel}\n", encoding="utf-8")
    loc = MA.local_hashes(root)

    def remote_exec(_cmd):
        return "\n".join(f"{h}  /r/{rel}" for rel, h in loc.items())

    rep = MA.check_sync(remote_exec, root=root)
    assert rep["status"] == "match"
    assert rep["missing_local"] == []
    assert rep["diffs"] == []


def test_unknown_enters_findings_and_facts_M15(tmp_path, monkeypatch):
    """M-15:unknown 入 findings(不拦批)+ mirror_unverified 事实。"""
    from main.ist_core.compile_engine_v8 import nodes as N
    from main.ist_core.compile_engine_v8 import _shared as sh
    import main.ist_core.compile_engine_v8.facts as F
    import main.ist_core.compile_engine_v8.bed as B

    facts_file = tmp_path / "facts.jsonl"
    facts_file.write_text("", encoding="utf-8")
    monkeypatch.setattr(N.B, "bed_check", lambda *a, **k: {
        "host": "h", "probes": {}, "findings": [], "needs_ask": False,
        "anchor": {"status": "match", "device": "x"}, "ours_unrestored": []})
    monkeypatch.setattr(N.B, "bed_snapshot", lambda fn: {})
    monkeypatch.setattr(N.B, "bed_unrestored", lambda *a, **k: [])
    monkeypatch.setattr(
        "main.ist_core.compile_engine_v8.mirror_anchor.check_sync",
        lambda *_a, **_k: {"status": "unknown", "reason": "remote unreachable: timeout"})
    monkeypatch.setattr(sh, "outputs_root", lambda: tmp_path / "outputs")
    monkeypatch.setattr(sh, "facts_path", lambda s: facts_file)
    monkeypatch.setattr(sh, "manifest", lambda s: {"cases": []})
    monkeypatch.setattr(sh, "project_root", lambda: tmp_path)
    monkeypatch.setattr(sh, "emit", lambda *a, **k: None)
    monkeypatch.setattr(sh, "counts_update", lambda *a, **k: {})
    # 干净床不 interrupt
    out = N.bed_gate({"out_name": "b1"})
    assert out["phase_status"] == "ok"
    fs = F.load_facts(facts_file)
    assert any(f.get("ev") == "mirror_unverified" for f in fs)
    checked = [f for f in fs if f.get("ev") == "bed_checked"]
    assert checked
    findings = checked[-1].get("findings") or []
    assert any(f.get("kind") == "mirror_sync" and f.get("unverified") for f in findings)
