"""ab_gate A-B 闸纯决策离线测试（零设备 / 零网络）。

覆盖：
  - judge 四裁决（insufficient_sample / promote / discard / trial）+ 边界。
  - flaky 成对作废不污染 A-B。
  - select_held_out 排除训练轨迹（induced_from）+ 显式 exclude（防记忆）。
  - 确定性：同输入同输出（judge + select + build_ab_test_record，ts 显式注入）。
  - 反模式被拒绝：A-B 闸不看 autoid 做分支（换一批用例规则仍成立）；run_fn 是唯一
    设备触点，模块本身零设备 import。

加载策略：skill_lib 包 __init__ 依赖尚在建设的 schema.py，故直接按文件路径加载
ab_gate.py（importlib），与 sibling 进度解耦。
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

# ── 按文件路径独立加载 ab_gate（绕开 __init__ 对 schema.py 的依赖） ──────────
_AB_GATE_PATH = (
    Path(__file__).resolve().parents[1]
    / "main" / "case_compiler" / "skill_lib" / "ab_gate.py"
)
_spec = importlib.util.spec_from_file_location("_ab_gate_under_test", _AB_GATE_PATH)
ab_gate = importlib.util.module_from_spec(_spec)
# 注册到 sys.modules：@dataclass 在 `from __future__ import annotations` 下
# 需通过模块名解析注解，未注册会 NoneType.__dict__ 报错。
sys.modules[_spec.name] = ab_gate
_spec.loader.exec_module(ab_gate)

ABGate = ab_gate.ABGate
ABDecision = ab_gate.ABDecision


# ── 测试替身（鸭子类型，无需 schema.py / corpus） ────────────────────────────

class _FakeCase:
    def __init__(self, autoid: str):
        self.autoid = autoid

    def __repr__(self):
        return f"_FakeCase({self.autoid})"


class _FakeRetriever:
    """确定性检索器替身：固定顺序返回 case，验证排除逻辑。"""

    def __init__(self, autoids):
        self._cases = [_FakeCase(a) for a in autoids]
        self.calls = []

    def nearest_cases(self, query, module="", k=3):
        self.calls.append((query, module, k))
        return list(self._cases[:k])


class _FakeCandidate:
    """候选技能替身：含 when_to_use + evidence.induced_from。"""

    def __init__(self, when_to_use="rr wrr 轮询 分布", induced_from=None, module="sdns"):
        self.when_to_use = when_to_use
        self.module = module
        self.evidence = {"induced_from": list(induced_from or [])}


# ── helpers ─────────────────────────────────────────────────────────────────

def _passes(n):
    return [{"passed": True} for _ in range(n)]


def _fails(n):
    return [{"passed": False} for _ in range(n)]


# ════════════════════════════════════════════════════════════════════════════
# judge 裁决
# ════════════════════════════════════════════════════════════════════════════

def test_judge_promote():
    """with 全过 / without 全挂，净增 ≥ +1 且 with ≥ without → promote。"""
    g = ABGate(min_sample=3)
    d = g.judge(_passes(3), _fails(3))
    assert d["verdict"] == "promote"
    assert d["with_rate"] == 1.0
    assert d["without_rate"] == 0.0
    assert d["sample"] == 3
    assert d["with_passes"] == 3 and d["without_passes"] == 0


def test_judge_discard_when_with_worse():
    """with 比 without 差 → discard（技能有害，废稿）。"""
    g = ABGate(min_sample=3)
    d = g.judge(_fails(3), _passes(3))
    assert d["verdict"] == "discard"
    assert d["with_passes"] == 0 and d["without_passes"] == 3


def test_judge_trial_on_tie():
    """持平（diff==0）→ trial（攒更多样本再判）。"""
    g = ABGate(min_sample=3)
    d = g.judge(_passes(3), _passes(3))
    assert d["verdict"] == "trial"
    assert d["with_passes"] == d["without_passes"] == 3


def test_judge_insufficient_sample():
    """有效样本 < min_sample → insufficient_sample，即便 with 全胜也不晋升。"""
    g = ABGate(min_sample=3)
    d = g.judge(_passes(2), _fails(2))
    assert d["verdict"] == "insufficient_sample"
    assert d["sample"] == 2


def test_judge_promote_exactly_at_margin():
    """边界：diff 恰好 == promote_margin → promote。"""
    g = ABGate(min_sample=3, promote_margin=1)
    # with 2/3, without 1/3 → diff = +1
    d = g.judge(
        _passes(2) + _fails(1),
        _passes(1) + _fails(2),
    )
    assert d["verdict"] == "promote"
    assert d["with_passes"] == 2 and d["without_passes"] == 1


def test_judge_trial_when_positive_but_below_margin():
    """diff > 0 但 < margin（margin=2）→ 不晋升，入 trial。"""
    g = ABGate(min_sample=3, promote_margin=2)
    d = g.judge(_passes(2) + _fails(1), _passes(1) + _fails(2))  # diff=+1 < 2
    assert d["verdict"] == "trial"


def test_judge_empty_results():
    """空结果 → sample=0 → insufficient_sample，rate 不除零。"""
    g = ABGate()
    d = g.judge([], [])
    assert d["verdict"] == "insufficient_sample"
    assert d["sample"] == 0
    assert d["with_rate"] == 0.0 and d["without_rate"] == 0.0


def test_judge_uneven_lengths_pairs_to_min():
    """with/without 长度不等 → 按 min 配对。"""
    g = ABGate(min_sample=3)
    d = g.judge(_passes(5), _fails(3))
    assert d["sample"] == 3   # min(5,3)


# ── flaky 处理 ───────────────────────────────────────────────────────────────

def test_judge_flaky_pair_discarded():
    """任一侧 flaky 的成对样本整对作废，不计入 sample（不污染 A-B）。"""
    g = ABGate(min_sample=3)
    with_r = [{"passed": True}, {"passed": True, "flaky": True}, {"passed": True}, {"passed": True}]
    without_r = [{"passed": False}, {"passed": False}, {"passed": False}, {"passed": False, "flaky": True}]
    d = g.judge(with_r, without_r)
    # index 1 (with flaky) + index 3 (without flaky) 各作废 → 剩 2 对
    assert d["sample"] == 2
    assert d["with_passes"] == 2 and d["without_passes"] == 0


def test_judge_accepts_bool_and_int_results():
    """run_fn 可回 bool / int，非 dict 时 flaky 默认 False。"""
    g = ABGate(min_sample=3)
    d = g.judge([True, 1, True], [False, 0, 0])
    assert d["verdict"] == "promote"
    assert d["with_passes"] == 3 and d["without_passes"] == 0


# ════════════════════════════════════════════════════════════════════════════
# select_held_out — 排除训练轨迹（防记忆，量迁移）
# ════════════════════════════════════════════════════════════════════════════

def test_select_excludes_induced_from():
    """induced_from 轨迹必须被排除（不在训练分布上测）。"""
    g = ABGate(min_sample=3)
    retr = _FakeRetriever(["A", "B", "C", "D", "E"])
    cand = _FakeCandidate(induced_from=["A", "C"])
    held = g.select_held_out(retr, cand)
    ids = [c.autoid for c in held]
    assert "A" not in ids and "C" not in ids
    assert ids[:3] == ["B", "D", "E"]   # 确定性顺序保持


def test_select_excludes_explicit_autoids():
    """调用方显式 exclude_autoids 与 induced_from 取并集排除。"""
    g = ABGate(min_sample=3)
    retr = _FakeRetriever(["A", "B", "C", "D", "E"])
    cand = _FakeCandidate(induced_from=["A"])
    held = g.select_held_out(retr, cand, exclude_autoids=["B"])
    ids = [c.autoid for c in held]
    assert "A" not in ids and "B" not in ids
    assert ids[:3] == ["C", "D", "E"]


def test_select_respects_n():
    """n 控制返回数量。"""
    g = ABGate(min_sample=3)
    retr = _FakeRetriever([str(i) for i in range(20)])
    cand = _FakeCandidate(induced_from=[])
    assert len(g.select_held_out(retr, cand, n=5)) == 5


def test_select_dedups_autoids():
    """检索器回重复 autoid 时去重。"""
    g = ABGate(min_sample=3)
    retr = _FakeRetriever(["A", "A", "B", "B", "C"])
    cand = _FakeCandidate(induced_from=[])
    held = g.select_held_out(retr, cand, n=3)
    assert [c.autoid for c in held] == ["A", "B", "C"]


def test_select_for_eval_adds_backup():
    """select_held_out_for_eval 在 held_out_k 上加 flaky_backup 个备份样本。"""
    g = ABGate(min_sample=3, held_out_k=3, flaky_backup=2)
    retr = _FakeRetriever([str(i) for i in range(20)])
    cand = _FakeCandidate(induced_from=[])
    held = g.select_held_out_for_eval(retr, cand)
    assert len(held) == 5   # 3 + 2


# ════════════════════════════════════════════════════════════════════════════
# evaluate — run_fn 注入（唯一设备触点）
# ════════════════════════════════════════════════════════════════════════════

def test_evaluate_with_injected_run_fn():
    """端到端：run_fn 回调注入，模块本身零设备耦合。"""
    g = ABGate(min_sample=3, held_out_k=3, flaky_backup=0)
    retr = _FakeRetriever(["A", "B", "C", "D"])
    cand = _FakeCandidate(induced_from=["A"])  # A 被排除 → 选 B C D

    def run_fn(case, with_skill):
        # 带技能全过，不带全挂（与 autoid 无关 → 不是逐 case 硬编码）
        return {"passed": bool(with_skill)}

    out = g.evaluate(retr, cand, run_fn)
    assert out["verdict"] == "promote"
    assert out["sample"] == 3
    assert out["sample_autoids"] == ["B", "C", "D"]


def test_evaluate_run_fn_is_only_device_touch():
    """run_fn 被调用 2N 次（每 case with + without），证明设备动作全经注入。"""
    g = ABGate(min_sample=3, held_out_k=3, flaky_backup=0)
    retr = _FakeRetriever(["X", "Y", "Z"])
    cand = _FakeCandidate(induced_from=[])
    calls = []

    def run_fn(case, with_skill):
        calls.append((case.autoid, with_skill))
        return True

    g.evaluate(retr, cand, run_fn)
    assert len(calls) == 6  # 3 cases × 2 (with/without)
    assert {c[1] for c in calls} == {True, False}


# ════════════════════════════════════════════════════════════════════════════
# 确定性 + evidence 记录
# ════════════════════════════════════════════════════════════════════════════

def test_judge_deterministic():
    """同输入 → 同输出（多次调用结果逐字段相等）。"""
    g = ABGate(min_sample=3)
    a = g.judge(_passes(3), _fails(3))
    b = g.judge(_passes(3), _fails(3))
    assert a == b


def test_build_ab_test_record_explicit_ts():
    """evidence.ab_test 记录：ts 显式注入（默认 0，不调 time.time）→ 确定性。"""
    g = ABGate(min_sample=3)
    d = g.judge(_passes(3) + _fails(0), _passes(1) + _fails(2))
    rec_a = g.build_ab_test_record(d)
    rec_b = g.build_ab_test_record(d)
    assert rec_a == rec_b
    assert rec_a["ts"] == 0.0
    assert rec_a["with"] == "3/3"
    assert rec_a["without"] == "1/3"
    rec_ts = g.build_ab_test_record(d, ts=123.0)
    assert rec_ts["ts"] == 123.0


def test_decision_to_dict_roundtrip():
    dec = ABDecision(verdict="promote", with_rate=1.0, without_rate=0.0,
                     sample=3, with_passes=3, without_passes=0, margin=1)
    d = dec.to_dict()
    assert d["verdict"] == "promote" and d["margin"] == 1


# ════════════════════════════════════════════════════════════════════════════
# 反模式被拒绝 / 红线守护
# ════════════════════════════════════════════════════════════════════════════

def test_no_per_case_hardcoding_in_source():
    """红线①：源码不得出现逐 autoid 硬编码分支（如 if autoid == '778012'）。"""
    src = _AB_GATE_PATH.read_text(encoding="utf-8")
    # 已知 rr 用例 autoid 不得作为字面量出现在判定逻辑里
    for aid in ("778012", "593516", "593545", "593573", "994899", "994957"):
        assert aid not in src, f"源码出现逐 case 硬编码 autoid {aid}"


def test_no_device_or_network_imports():
    """红线③零设备耦合：源码不得 import MCP / SSH / requests 等设备/网络模块。"""
    src = _AB_GATE_PATH.read_text(encoding="utf-8")
    banned = ("device_mcp_client", "paramiko", "import requests",
              "import socket", "FrameworkMCPClient", "time.time(", "import random")
    for tok in banned:
        assert tok not in src, f"ab_gate 不应耦合 {tok}（设备/网络/非确定性）"


def test_verdict_invariant_under_autoid_relabel():
    """红线①：把同一批结果换一组 autoid，裁决不变（规则与 autoid 无关）。"""
    g = ABGate(min_sample=3)
    # 两组完全不同 autoid 的 held-out，结果分布相同 → verdict 必须相同
    d1 = g.judge(_passes(3), _fails(3))
    d2 = g.judge(_passes(3), _fails(3))
    assert d1["verdict"] == d2["verdict"] == "promote"


def test_constructor_rejects_bad_knobs():
    with pytest.raises(ValueError):
        ABGate(min_sample=0)
    with pytest.raises(ValueError):
        ABGate(promote_margin=0)
