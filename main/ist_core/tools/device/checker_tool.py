"""compile_expected_hits:rr/wrr 命中计数的可验区间(worker 禁手算计数期望)。"""

from __future__ import annotations

from langchain_core.tools import tool


@tool(parse_docstring=True)
def compile_expected_hits(algorithm: str, n_requests: int, n_pools: int,
                          uninterrupted: bool = True, weight: int = 0,
                          pool_participates: bool = True) -> str:
    """Compute the **verifiable interval** of a pool's cumulative Hit count after N same-type queries — count expectations must come from this tool, never hand-calculated.

    The model is device-replay validated: a single uninterrupted query segment gets an exact
    interval; once the query sequence is segmented by interleaved show/config steps the
    device rotation state drifts — segmented scenarios auto-degrade, do not write exact
    intervals. wrr device ratios have been observed to deviate from configured weights
    (suspected product defect on record) — participation-only there.

    Args:
        algorithm: rr or wrr (other algorithms like ga are deterministic mappings — verify
            with capture-compare, not count intervals).
        n_requests: total same-type queries this pool participates in (count A and AAAA separately).
        uninterrupted: whether the queries run back-to-back with no show/config step in
            between (consecutive dig); pass False for segmented queries.
        n_pools: number of pools participating in rotation for that query type (count only
            pools holding addresses of the target record type).
        weight: this pool's configured weight for wrr; ignored for rr.
        pool_participates: whether this pool holds addresses of the target record type
            (pass False for a v6-only pool against A queries).

    Returns:
        Interval + confidence + assertion advice; when confidence=low do **not** write an
        exact-interval assertion.
    """
    algo = (algorithm or "").strip().lower()
    from main.case_compiler.checkers.rr_hit import rr_hit_range_segmented, wrr_hit_range
    if algo == "rr":
        r = rr_hit_range_segmented(n_requests, n_pools, uninterrupted, pool_participates)
    elif algo == "wrr":
        r = wrr_hit_range(n_requests, n_pools, weight, pool_participates)
    else:
        return (f"error: algorithm supports rr/wrr, got {algorithm!r}. ga/hash/persistence are "
                "deterministic mappings — verify the relation with capture-compare "
                "(CAPTURE_COMPARE), not count intervals.")
    # 只给数字段(区间的数学结果),**不组装设备回显前缀**——回显格式(计数字段叫什么)
    # 是领域内容,红线禁写死,由 worker 从先例卷面/手册核实后自己拼。(红线评审 2026-07-04:
    # 早前把 Hit 前缀整条返回=从后门重注入被本轮 prompt 清理的设备格式,自相矛盾。)
    nums = (str(r.lo) if r.lo == r.hi
            else "(?:" + "|".join(str(v) for v in range(r.lo, r.hi + 1)) + ")")
    return (f"=== compile_expected_hits ===\n"
            f"{r.as_pattern_hint()}  confidence={r.confidence}\n"
            f"basis: {r.note}\n"
            f"number field (interval math result): {nums}\n"
            f"usage: append it to the count field's **real echo prefix** to form the assertion — "
            "verify the prefix from precedent volumes/the manual; it may differ across "
            "versions/commands, never assume one spelling.\n"
            + ("⚠ confidence low — do not write an exact-interval assertion; adjust the "
               "observation structure per the basis above or degrade to participation."
               if r.confidence == "low" else ""))
