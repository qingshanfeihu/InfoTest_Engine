"""A-B 闸（SkillsBench 解药）：候选技能晋升前的**行为**证据门。

设计契约（见 plan「A-B 闸机制」§163-170）：自生成技能零样本平均 **-1.3pp**，
Voyager 式成功的充分前提是**确定性执行验证**。本模块把这条警告落成机制——
held-out 同类 case 带 / 不带候选技能各跑一次首跑，对比首跑通过率裁决晋升。

**三条硬纪律（与四条红线对齐）**：
  1. 零设备耦合：设备动作全由调用方注入的 ``run_fn`` 回调承担，本模块只做纯决策
     （选样 + 裁决），不 import 任何 MCP / SSH / 设备模块。可离线 pytest 全覆盖。
  2. 确定性：选样走 retriever 的确定性排序，裁决是纯整数比较，时间戳显式注入
     （默认 0），无 ``time.time`` / 无 RNG → 同输入同输出。
  3. 不测训练分布（防记忆，借 Voyager 检索策略）：held-out 必须**排除**候选技能的
     ``evidence.induced_from`` 轨迹 autoid + 调用方显式 exclude，否则量到的是记忆不是迁移。

**裁决阈值（plan §168，task 契约逐字）**：
  - ``sample < min_sample``（默认 3，统计地板）         → ``insufficient_sample``（入试用，不晋升）
  - ``with_passes − without_passes ≥ margin`` 且 ``with ≥ without`` → ``promote``
  - ``with_passes < without_passes``                    → ``discard``
  - 持平（diff == 0）                                    → ``trial``（攒更多样本再判）

**flaky 处理（plan §167）**：单个 held-out 若被判 flaky（``run_fn`` 回结果带
``flaky=True``），该样本作废**不污染** A-B（flaky 不是技能的功劳/过错）；裁决前丢弃成对样本。

本模块**只依赖标准库**，对 candidate / retriever 全程鸭子类型，故可脱离 skill_lib
包 ``__init__``（及尚在建设的 schema.py）被独立加载。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Iterable, Optional, Protocol


# ── 鸭子类型协议（仅文档化期望接口，运行时不强制、不 import 具体类） ──────────

class _RetrieverLike(Protocol):
    """检索器期望接口：与 SemanticRetriever.nearest_cases 同形。"""

    def nearest_cases(self, query: str, module: str = ..., k: int = ...) -> list: ...


# run_fn 回调契约：``run_fn(case, with_skill: bool) -> 结果``。
#   - case          : select_held_out 返回的 held-out case 对象（至少有 .autoid）。
#   - with_skill    : True=带候选技能首跑；False=不带（基线）首跑。
#   - 返回           : 下列任一形态（_result_passed / _result_flaky 解析）：
#       * bool / int          —— 首跑是否通过（1/0、True/False）。
#       * dict                —— {"passed": bool, "flaky": bool}（flaky 默认 False）。
#   设备 / 框架 MySQL pass-fail 全在 run_fn 内部完成 → 本模块零设备耦合。
RunFn = Callable[[Any, bool], Any]


# ── 候选 / 结果解析（鸭子类型，防 schema.py 依赖） ───────────────────────────

def _candidate_query(candidate: Any) -> str:
    """候选技能 → 检索 query：优先 when_to_use（含 TRIGGER 语义），回退 description/name。"""
    for attr in ("when_to_use", "description", "name"):
        val = getattr(candidate, attr, None)
        if isinstance(val, str) and val.strip():
            return val
        if isinstance(candidate, dict):
            v = candidate.get(attr)
            if isinstance(v, str) and v.strip():
                return v
    if isinstance(candidate, str):
        return candidate
    return ""


def _candidate_module(candidate: Any) -> str:
    """候选技能 → 模块提示（用于检索器结构化字段加权）；缺失则空串。"""
    val = getattr(candidate, "module", None)
    if val is None and isinstance(candidate, dict):
        val = candidate.get("module")
    return str(val) if isinstance(val, str) else ""


def _induced_from(candidate: Any) -> list[str]:
    """候选技能 evidence.induced_from（训练轨迹 autoid）。dict / dataclass 均兼容。"""
    ev = getattr(candidate, "evidence", None)
    if ev is None and isinstance(candidate, dict):
        ev = candidate.get("evidence")
    if ev is None:
        return []
    if isinstance(ev, dict):
        src = ev.get("induced_from", [])
    else:
        src = getattr(ev, "induced_from", []) or []
    return _norm_autoids(src)


def _norm_autoids(items: Optional[Iterable[Any]]) -> list[str]:
    """把任意 autoid 集合归一成去重保序的 str 列表。"""
    out: list[str] = []
    seen: set[str] = set()
    for it in (items or []):
        s = str(it).strip()
        if s and s not in seen:
            seen.add(s)
            out.append(s)
    return out


def _result_passed(r: Any) -> bool:
    if isinstance(r, dict):
        return bool(r.get("passed", r.get("pass", False)))
    return bool(r)


def _result_flaky(r: Any) -> bool:
    if isinstance(r, dict):
        return bool(r.get("flaky", False))
    return False


# ── 裁决结果 ────────────────────────────────────────────────────────────────

@dataclass
class ABDecision:
    """一次 A-B 裁决（纯数据，可直接 to_dict 落 evidence.ab_test）。"""

    verdict: str           # insufficient_sample | promote | discard | trial
    with_rate: float       # 带技能首跑通过率
    without_rate: float    # 不带技能首跑通过率
    sample: int            # 有效成对样本数（已剔除 flaky）
    with_passes: int = 0
    without_passes: int = 0
    margin: int = 1        # 晋升所需 case 净增

    def to_dict(self) -> dict:
        return {
            "verdict": self.verdict,
            "with_rate": self.with_rate,
            "without_rate": self.without_rate,
            "sample": self.sample,
            "with_passes": self.with_passes,
            "without_passes": self.without_passes,
            "margin": self.margin,
        }


# ── A-B 闸 ──────────────────────────────────────────────────────────────────

class ABGate:
    """A-B 闸纯决策器：选 held-out 被试 + 裁决晋升。设备动作经 run_fn 注入。

    构造参数皆为机制旋钮（非逐 case 特化）：
      min_sample   统计地板 N（默认 3，plan §166）。
      promote_margin  晋升所需 with−without case 净增（默认 +1，plan §168）。
      held_out_k   每次选取的 held-out 数（默认 min_sample，确保达地板）。
      flaky_backup 额外多选的备份样本数，供 flaky 丢弃后仍可能达地板（默认 2）。
    """

    def __init__(
        self,
        *,
        min_sample: int = 3,
        promote_margin: int = 1,
        held_out_k: Optional[int] = None,
        flaky_backup: int = 2,
    ):
        if min_sample < 1:
            raise ValueError("min_sample 必须 ≥ 1")
        if promote_margin < 1:
            raise ValueError("promote_margin 必须 ≥ 1（晋升至少要净增 1 个 case）")
        self.min_sample = min_sample
        self.promote_margin = promote_margin
        self.held_out_k = held_out_k if held_out_k is not None else min_sample
        self.flaky_backup = max(0, flaky_backup)

    # ── 被试选取 ───────────────────────────────────────────────────────────

    def select_held_out(
        self,
        retriever: _RetrieverLike,
        candidate: Any,
        exclude_autoids: Optional[Iterable[Any]] = None,
        n: Optional[int] = None,
    ) -> list:
        """检索同类 held-out case，**排除训练轨迹**（防记忆，量迁移不量记忆）。

        排除集 = candidate.evidence.induced_from ∪ exclude_autoids（调用方显式）。
        返回 retriever 确定性排序下、剔除排除集后的前 n 个 case（同输入同输出）。
        """
        target = n if n is not None else self.held_out_k
        query = _candidate_query(candidate)
        module = _candidate_module(candidate)
        excludes = set(_induced_from(candidate)) | set(_norm_autoids(exclude_autoids))

        # 多取缓冲：被排除的样本会被滤掉，向检索器多要一些以保证滤后仍够数。
        fetch = target + len(excludes) + self.flaky_backup + 4
        try:
            cases = retriever.nearest_cases(query, module, k=fetch)
        except TypeError:
            # 兼容只接受 (query, k) 的检索器变体
            cases = retriever.nearest_cases(query, k=fetch)

        held: list = []
        seen: set[str] = set()
        for c in cases or []:
            aid = str(getattr(c, "autoid", "") or "").strip()
            if not aid or aid in excludes or aid in seen:
                continue
            seen.add(aid)
            held.append(c)
            if len(held) >= target:
                break
        return held

    def select_held_out_for_eval(
        self,
        retriever: _RetrieverLike,
        candidate: Any,
        exclude_autoids: Optional[Iterable[Any]] = None,
    ) -> list:
        """evaluate 专用：在 held_out_k 之上额外多选 flaky_backup 个备份样本。"""
        return self.select_held_out(
            retriever, candidate, exclude_autoids,
            n=self.held_out_k + self.flaky_backup,
        )

    # ── 裁决 ───────────────────────────────────────────────────────────────

    def judge(self, with_results: list, without_results: list) -> dict:
        """对 with/without 首跑结果裁决。返回 dict（含 verdict/with_rate/without_rate/sample）。

        - 成对比较：按位置配对 with[i] vs without[i]，取两侧长度 min 为对数。
        - flaky 剔除：任一侧 flaky 的成对样本整对丢弃（不污染 A-B，plan §167）。
        - 阈值：见模块 docstring。
        """
        paired = min(len(with_results), len(without_results))
        w_passes = 0
        wo_passes = 0
        sample = 0
        for i in range(paired):
            rw, rwo = with_results[i], without_results[i]
            if _result_flaky(rw) or _result_flaky(rwo):
                continue   # flaky 整对作废
            sample += 1
            if _result_passed(rw):
                w_passes += 1
            if _result_passed(rwo):
                wo_passes += 1

        with_rate = round(w_passes / sample, 6) if sample else 0.0
        without_rate = round(wo_passes / sample, 6) if sample else 0.0
        diff = w_passes - wo_passes

        if sample < self.min_sample:
            verdict = "insufficient_sample"
        elif diff >= self.promote_margin and w_passes >= wo_passes:
            verdict = "promote"
        elif w_passes < wo_passes:
            verdict = "discard"
        else:
            verdict = "trial"

        return ABDecision(
            verdict=verdict,
            with_rate=with_rate,
            without_rate=without_rate,
            sample=sample,
            with_passes=w_passes,
            without_passes=wo_passes,
            margin=self.promote_margin,
        ).to_dict()

    # ── 端到端编排（设备动作经 run_fn 注入，本身仍零设备耦合） ───────────────

    def evaluate(
        self,
        retriever: _RetrieverLike,
        candidate: Any,
        run_fn: RunFn,
        exclude_autoids: Optional[Iterable[Any]] = None,
    ) -> dict:
        """选 held-out → 经 run_fn 逐 case 跑 with/without → judge。

        run_fn 是唯一设备触点（注入），本方法不接触任何设备/网络。返回 judge dict
        外加 ``sample_autoids``（实际参与裁决的 held-out autoid，可溯源）。
        """
        held = self.select_held_out_for_eval(retriever, candidate, exclude_autoids)
        with_results: list = []
        without_results: list = []
        sample_autoids: list[str] = []
        for case in held:
            with_results.append(run_fn(case, True))
            without_results.append(run_fn(case, False))
            sample_autoids.append(str(getattr(case, "autoid", "") or ""))
        decision = self.judge(with_results, without_results)
        decision["sample_autoids"] = sample_autoids
        return decision

    # ── evidence.ab_test 记录构造（确定性，ts 显式注入） ─────────────────────

    @staticmethod
    def build_ab_test_record(decision: dict, *, ts: float = 0.0) -> dict:
        """把 judge/evaluate 结果包成 evidence.ab_test 落盘形态（plan §169）。

        ts 显式注入（默认 0），不调 time.time → 内容寻址 hash 确定性。
        """
        sample = int(decision.get("sample", 0))
        wp = int(decision.get("with_passes", 0))
        wop = int(decision.get("without_passes", 0))
        return {
            "verdict": decision.get("verdict"),
            "with": f"{wp}/{sample}",
            "without": f"{wop}/{sample}",
            "with_rate": decision.get("with_rate", 0.0),
            "without_rate": decision.get("without_rate", 0.0),
            "sample": sample,
            "ts": ts,
        }
