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
# **单一事实源 = domain_grammar.json `algorithm_classes.distribution.methods`**（2026-07-16 合流，
# lexicon 单源纪律：本元组降为 grammar 不可读时的回退快照，快照↔grammar 一致性由
# test_distribution_algos_single_source 锁——判定处一律走 _distribution_algos() 现查）。
DISTRIBUTION_ALGOS = ("rr", "wrr", "grr", "gwrr")


def _distribution_algos() -> tuple[str, ...]:
    """分布类算法集现查（数据驱动：新算法=加 grammar JSON 条目零代码）。grammar
    缺失/坏时退回退快照——本模块是纯数学层，不因数据文件缺失硬炸（与检测器层
    「宁可炸得早」语义不同：这里误退快照最多是词表旧一拍，且一致性有测试锁）。"""
    try:
        from main.case_compiler.domain_grammar import distribution_methods
        return tuple(distribution_methods()) or DISTRIBUTION_ALGOS
    except Exception:  # noqa: BLE001
        return DISTRIBUTION_ALGOS


def _deterministic_algos() -> tuple[str, ...]:
    """确定性映射类算法集现查（grammar `algorithm_classes.deterministic_mapping`——
    distribution.provenance 散文知识的机读提升）。三分判定用：算法 ∈ 分布类→轮转数学；
    ∈ 本类→「预期与算法不符」等确定性语义；**两者都不中=未知→fail-open 中性放行**
    （原 provenance 带「等」字=非穷举，把「不在分布清单」当「非分布」是封闭世界
    假设误杀——2026-07-16 用户通用性裁决）。grammar 不可读退空集（未知→放行方向）。"""
    try:
        from main.case_compiler.domain_grammar import deterministic_mapping_methods
        return tuple(deterministic_mapping_methods())
    except Exception:  # noqa: BLE001
        return ()

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
    "cross_client_landing",  # 「特定客户端命中特定池/跨客户端共享轮转」跨客户端落点主张
                             # （777976 实证：轮转计数器跨客户端共享还是各自独立由设备实现
                             # 决定，rr/wrr 数学推不出「客户端N→池M」）
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
        if algo not in _distribution_algos():
            known_det = algo in _deterministic_algos()
            return Verdict(True, ck,
                           reason=((f"算法 {algo!r} 是确定性映射类（文法数据确认）；"
                                    if known_det else
                                    f"算法 {algo!r} 未在文法数据中分类（fail-open，不套轮转模型）；")
                                   + "绝对位置未被轮转起点模型证伪。"
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

    # ①b 跨客户端落点：只对分布类算法判死（样板同 ①——非分布类不误杀，红线语义保持）。
    # 777976 实证：worker 把「client2 应命中 pool2」按共享全局轮转硬推，三轮错前提打转；
    # 真机制是设备按地址族过滤（确定性映射），与轮转计数无关。
    if ck == "cross_client_landing":
        if algo not in _distribution_algos():
            known_det = algo in _deterministic_algos()
            return Verdict(True, ck,
                           reason=((f"算法 {algo!r} 是确定性映射类（文法数据确认）；"
                                    if known_det else
                                    f"算法 {algo!r} 未在文法数据中分类（fail-open，不套轮转模型）；")
                                   + "跨客户端确定性映射（如按源地址/地址族选池）可能成立，"
                                     "未被轮转起点模型证伪。是否可写固定落点仍需手册/判例支撑。"),
                           notes=["确定性映射的落点期望须溯源手册/先例（地址族过滤即 777976 "
                                  "的深层真机制）；无支撑时回到改描述/改预期，"
                                  "不要把分布类算法的修法套到非分布算法。"])
        return Verdict(
            False, ck,
            reason=(f"{algo} 的轮转计数器跨客户端是共享还是各自独立由设备实现决定，"
                    "rr/wrr 数学推不出「客户端N→池M」；该主张在无手册/判例支撑时不可证伪"
                    "（偶对偶错）。"),
            min_requests=None, suggested_fix=FIX_EXPECT,
            notes=["可验的等价预期：同客户端两次命中的**关系**断言（relation_diff/"
                   "relation_same），或按客户端分组的**分布区间**（distribution）。",
                   "若手册/判例证实该设备轮转计数跨客户端共享（全局单计数器），"
                   "按 rotation_order/absolute_position 重判，不按本 claim。"],
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
    # 算法三分（2026-07-16 通用性裁决）：分布类→守恒数学；**数据确认**的确定性映射→预期与
    # 算法不符（改描述，既有语义）；未知算法→fail-open 放行（把「不在分布清单」当「非分布」
    # 是封闭世界假设误杀——新算法可能就是个未入数据的分布变体）。
    if ck in ("weight_ratio", "distribution"):
        if algo not in _distribution_algos():
            if algo in _deterministic_algos():
                return Verdict(False, ck,
                               reason=(f"claim={ck} 但算法 {algo!r} 是确定性映射类"
                                       "（文法数据确认：命中由优先级/探测/哈希定）——预期与算法不符。"),
                               suggested_fix=FIX_DESC)
            return Verdict(True, ck,
                           reason=(f"算法 {algo!r} 未在文法数据中分类（既非分布类亦非已确认的"
                                   "确定性映射）——本数学工具不判（fail-open 中性放行，非证实）。"),
                           notes=["该算法的分布/比例语义须由手册/判例/上机钉死后写断言；"
                                  "钉死为分布类后加 grammar algorithm_classes 条目即获守恒数学支持。"])
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


def check_sequence_periodicity(
    cycle_kind: str | None,
    period: int | None,
    found_idx: list[int],
    notfound_idx: list[int],
    *,
    algo: str = "",
) -> Verdict:
    """序列↔周期自洽（E10b）：断言的 found/not_found 位置排布与声明的轮转周期能否同时为真。

    数学模型（仅 cycle_kind="uniform_rotation"）：等权严格轮转下，单个成员占**且仅占**一个模
    ``period`` 剩余类（起点/池序未知只平移/置换剩余类，不改「恰一类」性质）。可满足 ⟺
    ``∃r∈[0,period): (∀i∈found_idx: i≡r) ∧ (∀j∈notfound_idx: j≢r)``，O(P) 枚举。
    矛盾 = 内容无关的数学恒假（778012 实证形态：前 3 次 not_found + 后 5 次全 found、
    P=4——found 落两个剩余类，任何设备行为下都不可能全真）。

    定位是 **advisory**（L_oracle-B）：「严格轮转」的模型类本身是对设备行为的假设
    （dongkl 实测有设备根本不轮转），故矛盾走 NEEDS_USER_DECISION 呈报、不做 lint
    硬拒——硬门化 = 把严格轮转假设走私进 A 层。调用方开关 ``IST_SEQ_CONSISTENCY_CHECK``
    与 ``sequence_json`` 传参构成双门（接线在工具壳，本函数保持纯数学）。

    **通用性红线（2026-07-16 用户裁决返工）**：本函数**零算法语义**——参数是**周期语义类**
    ``cycle_kind``，不是算法名；「算法名→cycle_kind」的映射属领域知识，由调用方供给
    （工具壳从 domain_grammar.json `algorithm_classes` 数据现查，或 worker LLM 语义抽取
    传入——新算法=加 JSON 条目/语义判断，零 .py 变化）。``algo`` 仅用于呈报文案。
    取值：``"uniform_rotation"``（等权严格轮转，剩余类模型闭合于数学→判）/
    ``"weighted"``（加权轮转，剩余类占位依赖调度器交织实现→不判）/
    ``"none"``（无轮转周期概念，确定性映射→不适用）/
    ``None`` 或其他（语义未知→**fail-open 中性放行**，未知不误杀——顶注红线纪律）。
    period 未声明/无效同样 fail-open 放行（不误杀，零建议）。

    Args:
        cycle_kind: 周期语义类（见上）。非 "uniform_rotation" 一律中性放行。
        period: 声明的轮转周期（等权轮转下 = 候选池数）。None/无效 → 中性放行。
        found_idx: 该成员被断言 found 的请求序号列表（0 起算；1 起算也不影响判定——
            ∃r 吸收整体平移）。
        notfound_idx: 该成员被断言 not_found 的请求序号列表（同一编号基）。
        algo: 可选算法名，只进呈报文案（帮用户对上下文），不参与任何判定分支。

    输入语义：单一成员视角的 per-member 序列（"found: 池名" 与 "found: 成员IP" 混指
    多成员时判定错位——抽象是调用方的责任）；多成员联合约束逐成员分别调用，不做联合
    SAT。空序列 trivially 可满足。
    """
    ck = (cycle_kind or "").strip().lower()
    algo_note = f"（算法 {algo!r}）" if (algo or "").strip() else ""
    if ck == "none":
        return Verdict(True, "sequence_periodicity",
                       reason=(f"周期语义类为 none{algo_note}：无轮转周期概念（确定性映射类）"
                               "——本检查不适用（中性放行，非证实）。"),
                       notes=["确定性映射的时序预期溯源手册/判例，不走剩余类模型。"])
    if ck == "weighted":
        return Verdict(True, "sequence_periodicity",
                       reason=(f"周期语义类为 weighted{algo_note}：加权轮转的成员-剩余类占位"
                               "取决于调度器交织实现（设备相关）——本检查不判"
                               "（中性放行，非证实）。"),
                       notes=["仅等权严格轮转（uniform_rotation）的序列自洽闭合于数学；"
                              "加权变体的时序预期溯源手册/判例，或待上机钉死调度形态后"
                              "作为数据升级。"])
    if ck != "uniform_rotation":
        return Verdict(True, "sequence_periodicity",
                       reason=(f"周期语义类未知（cycle_kind={cycle_kind!r}{algo_note}）"
                               "——fail-open 中性放行，不误杀（未知语义不套剩余类模型）。"))
    try:
        period = int(period)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        period = 0
    if period < 1:
        return Verdict(True, "sequence_periodicity",
                       reason=(f"period 未声明或无效（{period!r}）{algo_note}——fail-open "
                               "中性放行：周期未知时剩余类模型无从建立，不猜不误杀。"))
    f_idx = [int(i) for i in (found_idx or [])]
    nf_idx = [int(j) for j in (notfound_idx or [])]
    if not f_idx and not nf_idx:
        return Verdict(True, "sequence_periodicity",
                       reason="无该成员的位置断言，序列约束为空（平凡可满足）。")
    satisfiable = any(
        all(i % period == r for i in f_idx) and all(j % period != r for j in nf_idx)
        for r in range(period)
    )
    if satisfiable:
        return Verdict(True, "sequence_periodicity",
                       reason=(f"存在剩余类 r 使 found⊆r、not_found∩r=∅（period={period}）"
                               "——排布与等权严格轮转模型可同时为真（可满足≠已证实，"
                               "落点仍由设备运行时定）。"))
    return Verdict(
        False, "sequence_periodicity",
        reason=(f"数学恒假：period={period} 的等权严格轮转下单成员占且仅占一个模 {period} "
                f"剩余类，而 found 序号 {sorted(set(f_idx))} 与 not_found 序号 "
                f"{sorted(set(nf_idx))} 的排布对每个剩余类都矛盾{algo_note}——任何设备行为、"
                "任何起点下该断言组都不可能全真（内容无关，advisory 呈报）。"),
        suggested_fix=FIX_EXPECT,
        notes=["矛盾出在断言排布本身：要么改预期（修正 found/not_found 的位置分配），"
               "要么改过程（调整请求序列使排布落进同一剩余类）。",
               "若意图本就不是等权严格轮转（如权重/亲和/过滤），周期语义类不是 "
               "uniform_rotation，不适用本检查。"],
    )


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
