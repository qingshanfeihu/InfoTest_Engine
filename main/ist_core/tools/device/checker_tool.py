"""compile_expected_hits:rr/wrr 命中计数的可验区间(worker 禁手算计数期望)。"""

from __future__ import annotations

from langchain_core.tools import tool


@tool(parse_docstring=True)
def compile_expected_hits(algorithm: str, n_requests: int, n_pools: int,
                          uninterrupted: bool = True, weight: int = 0,
                          pool_participates: bool = True) -> str:
    """算一个池在 N 次同类型查询后累计 Hit 的**可验区间**——计数类期望值必须来自本工具,不要手算。

    模型经设备回放验证(实证细节见 docs/PLAN_v4_engine.md 步骤5):单段连续查询给精确
    区间;查询序列被 show/配置插入分段后设备轮转态漂移——分段场景自动降级,别写精确
    区间。wrr 设备配比与配置权重不符(疑似产品缺陷在案),只给参与性。

    Args:
        algorithm: rr 或 wrr(其他算法如 ga 是确定性映射,用捕获比较不用计数区间)。
        n_requests: 该池参与的同类型查询总次数(A 与 AAAA 分开算)。
        uninterrupted: 这批查询之间是否无 show/配置步插入(连续 dig)。分段查询传 False。
        n_pools: 参与该类型查询轮转的池数(只数含目标记录类型地址的池)。
        weight: wrr 时该池配置权重;rr 忽略。
        pool_participates: 该池是否含目标记录类型的地址(v6-only 池对 A 查询传 False)。

    Returns:
        区间 + 置信度 + 断言建议;confidence=low 时**不要**写精确区间断言。
    """
    algo = (algorithm or "").strip().lower()
    from main.case_compiler.checkers.rr_hit import rr_hit_range_segmented, wrr_hit_range
    if algo == "rr":
        r = rr_hit_range_segmented(n_requests, n_pools, uninterrupted, pool_participates)
    elif algo == "wrr":
        r = wrr_hit_range(n_requests, n_pools, weight, pool_participates)
    else:
        return (f"error: algorithm 支持 rr/wrr,收到 {algorithm!r}。ga/哈希/会话保持是"
                "确定性映射——用捕获比较(CAPTURE_COMPARE)验关系,不用计数区间。")
    # 只给数字段(区间的数学结果),**不组装设备回显前缀**——回显格式(计数字段叫什么)
    # 是领域内容,红线禁写死,由 worker 从先例卷面/手册核实后自己拼。(红线评审 2026-07-04:
    # 早前把 Hit 前缀整条返回=从后门重注入被本轮 prompt 清理的设备格式,自相矛盾。)
    nums = (str(r.lo) if r.lo == r.hi
            else "(?:" + "|".join(str(v) for v in range(r.lo, r.hi + 1)) + ")")
    return (f"=== compile_expected_hits ===\n"
            f"{r.as_pattern_hint()}  置信={r.confidence}\n"
            f"依据: {r.note}\n"
            f"数字段(区间数学结果): {nums}\n"
            f"用法: 接在该计数字段的**真实回显前缀**后组成断言——前缀从先例卷面/手册核实,"
            "不同版本/命令可能不同,别默认某写法。\n"
            + ("⚠ 置信 low——不要写精确区间断言,按依据里的改法调整观测结构或降级参与性。"
               if r.confidence == "low" else ""))
