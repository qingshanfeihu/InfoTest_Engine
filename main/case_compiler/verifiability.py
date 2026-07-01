"""用例可验性证伪（math model：算法类用例「如写无法验证目标行为」的确定性判定）。

为什么要它：负载均衡算法用例的脑图常把「运行时行为」写成「确定性预期 + 极少请求」，导致**按用例
过程根本验不出声称的效果**——不是断言写法问题，是用例本身欠定（underdetermined）。死抠断言形态
去硬写只会产出偶对偶错或恒真的假断言。正确做法：先用数学模型证伪，欠定就 ask_user（改描述/改
过程/改预期），别乱写。

三类典型（皆来自真实脑图 dongkl）：
- 「客户端1发1次请求→命中第一个pool」：rr 起点由运行时计数器定，绝对「第1次必中p1」在任何请求数
  下都不可证伪（只有「连续两次不同」这种关系可验）→ 改预期。
- 「wrr 3:2:1，发3次→命中3权重pool」：3 次体现不出 3:2:1 比例（需 ≥Σ权重=6 次）→ 改过程/改预期。
- 「新增一个pool，发1次→按原有顺序最后才命中新增pool」：这是**有序轨迹**声明，不是“新增 pool
  有命中”的分布声明；1 次物理上测不出（需 ≥原pool数+1 次），请求数够后也要断言新增 pool
  出现在原 pool 之后，不能降级成统计里 Hit>0。

设计：claim_kind（自然语言预期→声称的行为类型，由 LLM 抽取）+ 数值参数（请求数/pool数/权重）→
确定性判 verifiable / underdetermined(原因 + 最小请求数 + 建议修法)。分布/比例类**复用**
`distribution_assertion.validate_distribution`（守恒 + 反恒真），不另写一套（单一事实源）。

红线：本模块只做「给定结构化参数的数学判定」；自然语言预期→claim_kind/请求数/权重的语义抽取是
LLM 的活（见 compile-worker prompt），不在这里硬编码关键词匹配。
"""

from __future__ import annotations

from dataclasses import dataclass, field

# 复用既有分布数学（守恒门 + 反恒真门）——分布/比例类可验性直接走它，不重写。
from main.case_compiler.distribution_assertion import validate_distribution

# 分布类算法（命中按比例/均摊摊开，可用分布区间验）；ga/topology/一致性哈希不在此列（确定性映射）。
DISTRIBUTION_ALGOS = ("rr", "wrr", "grr", "gwrr")

# claim_kind：脑图预期声称的「被测行为类型」（LLM 从 expected 自然语言抽取后传入）。
CLAIM_KINDS = (
    "absolute_position",  # 「第N次/某客户端命中第N个pool」绝对位置（rr/wrr 起点非确定→不可证伪）
    "rotation_order",     # 「依次轮转/按顺序命中」需看完整一轮
    "new_member_last",    # 「新增pool最后才命中」需原pool轮完+1，且要保留有序轨迹语义
    "new_member_participates", # 「新增pool参与轮转/有命中」：较弱声明，不等价于最后命中
    "weight_ratio",       # wrr「按权重比例命中」需 ≥Σ权重 次
    "distribution",       # 一般「命中分布」
    "relation_same",      # 「两次相同」（会话保持/亲和）
    "relation_diff",      # 「两次不同/切换」
)

# 建议修法（与 ask_user 三选项对齐）
FIX_DESC = "改描述"      # 用例描述本身有歧义/自相矛盾
FIX_PROCESS = "改过程"   # 步骤（请求次数）不足以暴露行为——加请求
FIX_EXPECT = "改预期"    # 预期写成了不可证伪的绝对值——改成关系/分布


@dataclass
class Verdict:
    verifiable: bool
    claim_kind: str
    reason: str = ""
    min_requests: int | None = None      # 验出该行为所需的最小请求数（欠定时给目标）
    suggested_fix: str = ""              # 改描述/改过程/改预期（ask_user 的倾向项，非终判）
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "verifiable": self.verifiable,
            "claim_kind": self.claim_kind,
            "reason": self.reason,
            "min_requests": self.min_requests,
            "suggested_fix": self.suggested_fix,
            "notes": list(self.notes),
        }


def _implied_buckets(n_requests: int, weights: list[int]) -> list[dict]:
    """按权重把 n_requests 摊成各桶期望命中（守恒：Σ==n_requests），容差取期望的 ~⌈30%⌉、至少 1。

    用于复用 validate_distribution 判「该请求数下分布是否可表达成守恒、非恒真的区间」。
    余数补到最大权重桶，保证 Σ严格==n_requests。
    """
    total_w = sum(weights)
    base = [n_requests * w // total_w for w in weights]
    remainder = n_requests - sum(base)
    # 余数依次补给权重最大的桶（稳定、可复现）
    order = sorted(range(len(weights)), key=lambda i: (-weights[i], i))
    for j in range(remainder):
        base[order[j % len(order)]] += 1
    buckets = []
    for i, exp in enumerate(base):
        tol = max(1, round(exp * 0.3))
        buckets.append({"anchor": f"pool{i+1}", "expected": exp, "tol": tol})
    return buckets


def check_verifiability(
    algo: str,
    n_requests: int,
    n_pools: int,
    *,
    weights: list[int] | None = None,
    claim_kind: str = "",
    existing_pools: int | None = None,
) -> Verdict:
    """给定结构化参数，判用例「如写」能否验证其声称的行为。

    Args:
        algo: 算法名（rr/wrr/grr/gwrr/ga/...，小写）。
        n_requests: 用例实际发起的请求总数（按 claim 涉及的那组客户端合计）。
        n_pools: 当前关联的 pool 总数。
        weights: wrr 各 pool 权重（按关联顺序）；非 wrr 传 None。
        claim_kind: 预期声称的行为类型（见 CLAIM_KINDS，LLM 抽取）。
        existing_pools: new_member_last 用——新增前已有的 pool 数（缺省 = n_pools-1）。

    Returns:
        Verdict（verifiable=False 时带 reason/min_requests/suggested_fix，供 worker 上报 ask_user）。
    """
    algo = (algo or "").strip().lower()
    ck = (claim_kind or "").strip()
    n_requests = int(n_requests or 0)
    n_pools = int(n_pools or 0)

    if ck and ck not in CLAIM_KINDS:
        return Verdict(False, ck, reason=f"未知 claim_kind={ck!r}（应∈{CLAIM_KINDS}）",
                       suggested_fix=FIX_DESC)

    # ① 绝对位置：只对分布类算法判死。优先级/确定性映射类是否可验取决于手册/先例，
    # 本数学工具不把它们误杀成 rr/wrr 的运行时绝对位置问题。
    if ck == "absolute_position":
        if algo not in DISTRIBUTION_ALGOS:
            return Verdict(True, ck,
                           reason=(f"算法 {algo!r} 非分布类；绝对位置未被 rr/wrr 轮转起点模型证伪。"
                                   "是否可写固定期望仍需手册/先例支撑。"),
                           notes=["若手册/先例不能证明该确定性映射，回到改描述/改预期；"
                                  "不要把分布类算法的修法套到非分布算法。"])
        return Verdict(
            False, ck,
            reason=(f"{algo} 轮转起点由运行时计数器决定，不保证从第一个 pool 起；"
                    "「第N次请求必中第N个pool」是不可证伪的绝对断言（偶对偶错）。"),
            min_requests=None, suggested_fix=FIX_EXPECT,
            notes=["可验的等价预期：连续两次命中**不同** pool（rotation_order，关系断言），"
                   "或多次请求各 pool 命中落在**分布区间**（distribution）。"],
        )

    # ② 轮转顺序：要看出「依次轮转」至少需走完整一轮 = n_pools 次。
    if ck == "rotation_order":
        need = max(2, n_pools)
        if n_requests >= need:
            return Verdict(True, ck, reason=f"{n_requests} 次 ≥ 一轮 {need} 次，可验轮转。",
                           min_requests=need)
        return Verdict(
            False, ck,
            reason=f"验「依次轮转」至少需走完整一轮 {need} 次（n_pools={n_pools}），实际仅 {n_requests} 次。",
            min_requests=need, suggested_fix=FIX_PROCESS)

    # ③ 新增 pool 最后命中：这是有序轨迹声明。请求数不够时物理上看不到；请求数够时也只能
    # 继续按“有序轨迹”表达，不能降级成“新增 pool 有命中/分布统计”。
    if ck == "new_member_last":
        prev = existing_pools if existing_pools is not None else max(1, n_pools - 1)
        need = prev + 1
        if n_requests >= need:
            return Verdict(True, ck,
                           reason=(f"{n_requests} 次 ≥ 原 {prev} pool 轮完+1 = {need} 次，"
                                   "请求数足以覆盖“最后才命中新增 pool”的有序轨迹。"),
                           min_requests=need,
                           notes=["断言仍需证明“新增 pool 在原 pool 之后出现”的顺序语义；"
                                  "统计里新增 pool 有命中只证明参与轮转，不等价于最后命中。",
                                  "只改请求次数/断言形态，原 case 的配置形态、服务类型、关联关系等约束应保留。"])
        return Verdict(
            False, ck,
            reason=(f"设备要原有 {prev} 个 pool 轮完才轮到新增 pool，验「最后才命中新增」至少需 {need} 次；"
                    f"实际仅 {n_requests} 次，物理上看不到新 pool 被命中。"),
            min_requests=need, suggested_fix=FIX_PROCESS,
            notes=["这类无法靠改断言形态补救——请求数不够，任何断言都验不出，需改过程（加请求）。",
                   "改过程只作用于这个欠定行为 claim；配置形态、服务类型、关联关系等原始约束应保留。"])

    # ③b 新增 pool 参与轮转：这是比 new_member_last 更弱的声明；它可用统计/分布表达，但不能拿来
    # 替代“最后才命中”的原预期。
    if ck == "new_member_participates":
        need = max(2, n_pools)
        if n_requests >= need:
            return Verdict(True, ck,
                           reason=f"{n_requests} 次 ≥ 一轮 {need} 次，可验新增 pool 是否参与轮转/产生命中。",
                           min_requests=need,
                           notes=["断言需让新增成员的命中下界可证伪地大于 0，或用等价关系证明它被触达。",
                                  "该 claim 只证明“参与轮转”，不证明“按照原有顺序最后才命中”。"])
        return Verdict(False, ck,
                       reason=f"验新增 pool 参与轮转至少需走一轮 {need} 次（n_pools={n_pools}），实际仅 {n_requests} 次。",
                       min_requests=need, suggested_fix=FIX_PROCESS)

    # ④ 权重比例 / ⑤ 一般分布：复用 distribution_assertion 的守恒 + 反恒真门判「该请求数下分布可否表达」。
    if ck in ("weight_ratio", "distribution"):
        if algo not in DISTRIBUTION_ALGOS:
            return Verdict(False, ck,
                           reason=f"claim={ck} 但算法 {algo!r} 非分布类（rr/wrr/grr/gwrr）——预期与算法不符。",
                           suggested_fix=FIX_DESC)
        w = weights or [1] * max(1, n_pools)
        if ck == "weight_ratio":
            need = sum(w)
            if n_requests < need:
                return Verdict(
                    False, ck,
                    reason=f"wrr 权重 {w} 需至少 Σ={need} 次请求才能体现比例，实际仅 {n_requests} 次。",
                    min_requests=need, suggested_fix=FIX_PROCESS)
        # 请求数够：进一步用既有守恒/反恒真门验「该分布能否表达成有效区间断言」（混合复用）。
        buckets = _implied_buckets(n_requests, w)
        err = validate_distribution(n_requests, buckets)
        if err:
            return Verdict(
                False, ck,
                reason=f"该请求数下分布无法表达成有效（守恒+非恒真）区间断言：{err}",
                min_requests=max(sum(w), len(w) * 2), suggested_fix=FIX_PROCESS)
        return Verdict(True, ck, reason=f"{n_requests} 次可表达成守恒、非恒真的分布区间断言。",
                       min_requests=sum(w) if ck == "weight_ratio" else len(w))

    # ⑥ 关系（两次同/异）：至少 2 次。
    if ck in ("relation_same", "relation_diff"):
        if n_requests >= 2:
            return Verdict(True, ck, reason="≥2 次可验两次观测的关系。", min_requests=2)
        return Verdict(False, ck,
                       reason=f"验「两次观测{'相同' if ck=='relation_same' else '不同'}」至少需 2 次，实际 {n_requests} 次。",
                       min_requests=2, suggested_fix=FIX_PROCESS)

    # claim_kind 未提供：无法判定（让上游补充语义抽取，不擅自放行）。
    return Verdict(False, ck or "(empty)",
                   reason="未提供 claim_kind（声称的行为类型），无法做可验性判定。",
                   suggested_fix=FIX_DESC,
                   notes=["请先从脑图 expected 抽取 claim_kind（见 CLAIM_KINDS）再判。"])


def render_needs_user_decision(autoid: str, verdict: Verdict) -> str:
    """把欠定 Verdict 渲染成 worker 上报给 orchestrator 的结构化标记（orchestrator 解析后 ask_user）。"""
    lines = [
        f"NEEDS_USER_DECISION autoid={autoid}",
        f"原因：{verdict.reason}",
    ]
    if verdict.min_requests:
        lines.append(f"最小可验请求数：{verdict.min_requests}")
    lines.append(f"建议修法：{verdict.suggested_fix or '改描述'}（可选：改描述 / 改过程 / 改预期）")
    for n in verdict.notes:
        lines.append(f"备注：{n}")
    return "\n".join(lines)
