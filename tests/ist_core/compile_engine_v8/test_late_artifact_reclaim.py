"""迟到产出回收(run18 实弹):fork 墙钟超时 ≠ worker 无产出。

run18@79 实录:655233 派发后 600s 单次墙钟超时,引擎判 escalated("no output");
worker 线程在 Python 里杀不掉,继续跑到 935s 时 compile_emit 成功——合格卷
(11KB)+ lint 凭证静静躺在盘上,案却已被标成 escalated 永不再看,烧掉 15 分钟与
整案 token。修:escalated 语义改「可被后续 authored 解除」(与 suspended/resumed
同型),merge 开工先扫 escalated 案的盘上产出,凭证有效即回收。
"""
from __future__ import annotations

import json

from main.ist_core.compile_engine_v8 import views as V
from main.ist_core.compile_engine_v8 import _shared as sh
from main.ist_core.compile_engine_v8 import nodes as N

A = "203601753067655233"


def _land_artifact(outputs, aid: str, mtime_sig: str = "sig-1") -> None:
    """盘上落一份合格卷+lint 凭证(emit 全门已过的物理证据)。"""
    d = outputs / aid
    d.mkdir(parents=True, exist_ok=True)
    (d / "case.xlsx").write_text("volume", encoding="utf-8")
    (d / ".grade_credential.json").write_text(
        json.dumps({"source": "lint", "xlsx_mtime": mtime_sig}), encoding="utf-8")


# ── views:escalated 可被 authored 解除 ──────────────────────────────────────

def test_escalated_cleared_by_later_authored():
    fs = [{"ev": "escalated", "aid": A, "reason": "no output from fork"},
          {"ev": "authored", "aid": A, "round": 1, "artifact": "sig-1"}]
    vw = V.batch_view(fs, {"cases": [{"autoid": A}]})
    assert vw["cases"][A]["status"] == V.S_AUTHORED     # 迟到产出解除 escalated


def test_escalated_without_artifact_stays_escalated():
    """真·无产出:escalated 保持(升级人工的语义不被削弱)。"""
    fs = [{"ev": "authored", "aid": A, "round": 1, "artifact": "sig-0"},
          {"ev": "escalated", "aid": A, "reason": "no output from fork"}]
    vw = V.batch_view(fs, {"cases": [{"autoid": A}]})
    assert vw["cases"][A]["status"] == V.S_ESCALATED    # authored 在 escalated 之前=旧账,不解除


# ── merge 开工回收 ───────────────────────────────────────────────────────────

def test_merge_reclaims_late_artifact(tmp_path, monkeypatch):
    """run18 形态回放:escalated 案盘上有合格卷+有效凭证 → 回收落 authored。"""
    outputs = tmp_path / "outputs"
    outputs.mkdir()
    _land_artifact(outputs, A)
    monkeypatch.setattr(sh, "outputs_root", lambda: outputs)
    monkeypatch.setattr(sh, "project_root", lambda: tmp_path)
    monkeypatch.setattr(sh, "manifest", lambda s: {"cases": [{"autoid": A}]})
    monkeypatch.setattr(sh, "emit", lambda t: None)
    fs = [{"ev": "escalated", "aid": A, "reason": "no output from fork (tail=none)"}]
    facts = N._reclaim_late_artifacts({}, fs)
    assert len(facts) == 1
    assert facts[0]["ev"] == "authored" and facts[0]["aid"] == A
    assert facts[0]["artifact"] == f"{A}:sig-1"         # 指纹=<aid>:<xlsx_mtime>
    # 回收后视图解除 escalated
    vw = V.batch_view(fs + facts, {"cases": [{"autoid": A}]})
    assert vw["cases"][A]["status"] == V.S_AUTHORED


def test_merge_does_not_reclaim_without_credential(tmp_path, monkeypatch):
    """无 lint 凭证(未过 emit 门)的裸 xlsx 不回收——门不可绕。"""
    outputs = tmp_path / "outputs"
    (outputs / A).mkdir(parents=True)
    (outputs / A / "case.xlsx").write_text("volume", encoding="utf-8")   # 凭证缺失
    monkeypatch.setattr(sh, "outputs_root", lambda: outputs)
    monkeypatch.setattr(sh, "project_root", lambda: tmp_path)
    monkeypatch.setattr(sh, "manifest", lambda s: {"cases": [{"autoid": A}]})
    monkeypatch.setattr(sh, "emit", lambda t: None)
    fs = [{"ev": "escalated", "aid": A, "reason": "no output"}]
    assert N._reclaim_late_artifacts({}, fs) == []


def test_merge_reclaim_is_idempotent(tmp_path, monkeypatch):
    """同一卷面已入账 → 不重复落 authored(幂等,防续跑刷账)。"""
    outputs = tmp_path / "outputs"
    outputs.mkdir()
    _land_artifact(outputs, A)
    monkeypatch.setattr(sh, "outputs_root", lambda: outputs)
    monkeypatch.setattr(sh, "project_root", lambda: tmp_path)
    monkeypatch.setattr(sh, "manifest", lambda s: {"cases": [{"autoid": A}]})
    monkeypatch.setattr(sh, "emit", lambda t: None)
    fs = [{"ev": "escalated", "aid": A, "reason": "no output"},
          {"ev": "authored", "aid": A, "round": 1, "artifact": f"{A}:sig-1"}]
    assert N._reclaim_late_artifacts({}, fs) == []      # 已解除且已入账:零动作
