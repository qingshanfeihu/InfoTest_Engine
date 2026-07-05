"""分布区间断言辅助（算法类 rr/wrr 的确定性区间断言落地）。

为什么要它：负载均衡分布类算法（轮询 rr / 加权 wrr）的**单次**命中哪个后端是运行时落点
（算不准），但**N 次访问的命中分布是可离线确定的统计区间**——rr 每桶≈N/k、wrr 每桶≈N×w_i/Σw，
守恒律 Σ各桶命中 == 总请求数 N。所以正确断言形态既不是写死单次命中 IP（偶对偶错）、也不是
写恒真 `Hit:\\s+\\d+`（字段在就过、不验分布）、更不是 `<RUNTIME>` 弃权，而是断言「各后端累计
命中数落在 [期望-容差, 期望+容差] 区间」。

框架 check_point 只有 found(正则)/not_found/abs_found，没有数值区间算子，区间只能落成
`found(区间正则)`；手写区间正则脆弱（[8,12] 要写成 `(?:[8-9]|1[0-2])`），故由本模块**确定性
生成**区间正则 + 守恒/反恒真门把关，agent 只声明 {字段, 总次数, 各桶期望/容差}。

红线：本模块只做「数字区间→正则」「守恒/反恒真校验」这类与意图无关的确定性变换；
**不产任何设备命令、不决定用哪条 show、不写死期望分布**——anchor/field/期望/容差全部由
查过 footprint/先例/dev_probe 的 agent 提供（命中分布回显格式因设备而异）。
"""

from __future__ import annotations


# ── 数字闭区间 → 正则（经典 range-to-regex；把 [lo,hi] 拆成若干同位数子区间）────────────

def _fill_by_nines(num: int, nines: int) -> int:
    """把 num 的低 nines 位填成 9。fill_by_nines(8,1)=9；fill_by_nines(123,2)=199。"""
    return num - num % (10 ** nines) + (10 ** nines - 1)


def _fill_by_zeros(num: int, zeros: int) -> int:
    """把 num 的低 zeros 位填成 0 再减 1。fill_by_zeros(12,1)=9；fill_by_zeros(105,1)=99。"""
    return num - num % (10 ** zeros) - 1


def _split_to_ranges(lo: int, hi: int) -> list[tuple[int, int]]:
    """把 [lo,hi] 拆成若干子区间，每个子区间内的数同位数、且逐位可用 [a-b] 表达。

    切点取在「低位全 9」（lo 侧上推）与「低位全 0 减 1」（hi 侧下推）边界——这些正是数字位数/
    十进制进位的天然分界，保证每个子区间 start/stop 位数一致（_range_to_pattern 的前提）。
    """
    stops = {hi}
    nines = 1
    stop = _fill_by_nines(lo, nines)
    while lo <= stop < hi:
        stops.add(stop)
        nines += 1
        stop = _fill_by_nines(lo, nines)
    zeros = 1
    stop = _fill_by_zeros(hi, zeros)
    while lo < stop <= hi:
        stops.add(stop)
        zeros += 1
        stop = _fill_by_zeros(hi, zeros)
    ranges: list[tuple[int, int]] = []
    start = lo
    for stop in sorted(stops):
        ranges.append((start, stop))
        start = stop + 1
    return ranges


def _range_to_pattern(start: int, stop: int) -> str:
    """同位数 [start,stop] → 逐位正则。(8,9)→`[8-9]`；(10,12)→`1[0-2]`；(100,105)→`10[0-5]`。"""
    pattern = ""
    for ds, de in zip(str(start), str(stop)):
        pattern += ds if ds == de else f"[{ds}-{de}]"
    return pattern


def int_range_to_regex(lo: int, hi: int) -> str:
    """整数闭区间 [lo,hi] → 匹配区间内任一整数的正则**主体**（不含外层分组/边界，调用方包）。

    例：[8,12]→`[8-9]|1[0-2]`；[18,22]→`1[8-9]|2[0-2]`；[95,105]→`9[5-9]|10[0-5]`；[8,8]→`8`。
    调用方应包成 `(?<!\\d)(?:{rng})(?!\\d)` 以加数字边界（防 `1[0-2]` 误配 `120` 的 `12`）。
    """
    if lo > hi:
        raise ValueError(f"区间非法 lo={lo} > hi={hi}")
    if lo < 0:
        raise ValueError(f"区间下界须 >=0，实际 lo={lo}")
    seen: set[str] = set()
    uniq: list[str] = []
    for a, b in _split_to_ranges(lo, hi):
        p = _range_to_pattern(a, b)
        if p not in seen:
            seen.add(p)
            uniq.append(p)
    return "|".join(uniq)


def range_regex_for_count(lo: int, hi: int) -> str:
    """[lo,hi] → 带数字边界、可直接拼进 G 列的区间正则片段。"""
    return f"(?<!\\d)(?:{int_range_to_regex(lo, hi)})(?!\\d)"


# ── 守恒 / 反恒真校验 ─────────────────────────────────────────────────────────────

def _bucket_bounds(expected: int, tol: int) -> tuple[int, int]:
    """单桶区间 [lo,hi]，lo 在 0 处截断（命中数非负）。"""
    return max(0, expected - tol), expected + tol


def validate_distribution(total, buckets) -> str | None:
    """校验一个分布区间断言声明。返回 None=通过，否则返回**可读打回原因**（emit 据此拒绝）。

    三类与意图无关、确定性可判的约束：
    - 结构：total 为正整数；至少 2 个桶（单后端无「分布」可言）；每桶 expected/tol 为非负整数。
    - 守恒（论文/oracle_distribution 守恒律）：各桶区间必须能容纳总请求数——`Σlo <= total <= Σhi`；
      且分布中心对齐 `|Σexpected - total| <= 桶数`（容忍 rr 不整除时各桶取整的累积余数）。
    - 反恒真：每桶 `hi < total`——否则单个桶的区间宽到「把全部流量都打到它」也算通过，
      该断言对「算法失效＝流量全压一个后端」无法证伪 ＝ 恒真伪覆盖。
    """
    if not isinstance(total, int) or isinstance(total, bool) or total <= 0:
        return f"分布断言 total（总请求数）须为正整数，实际 {total!r}"
    if not isinstance(buckets, list) or len(buckets) < 2:
        return f"分布断言至少需 2 个桶（每后端一个）才有分布可验，实际 {len(buckets) if isinstance(buckets, list) else buckets!r} 个"

    sum_lo = sum_hi = sum_exp = 0
    for i, b in enumerate(buckets):
        if not isinstance(b, dict):
            return f"bucket[{i}] 不是 dict"
        if not str(b.get("anchor", "")).strip():
            return f"bucket[{i}] 缺 anchor（后端标识，如成员 IP/名字，用于把命中数锚定到该后端）"
        expected = b.get("expected")
        tol = b.get("tol", 0)
        if not isinstance(expected, int) or isinstance(expected, bool) or expected < 0:
            return f"bucket[{i}]({b.get('anchor')}) expected（期望命中数）须为非负整数，实际 {expected!r}"
        if not isinstance(tol, int) or isinstance(tol, bool) or tol < 0:
            return f"bucket[{i}]({b.get('anchor')}) tol（容差）须为非负整数，实际 {tol!r}"
        lo, hi = _bucket_bounds(expected, tol)
        if hi >= total:
            return (f"bucket[{i}]({b.get('anchor')}) 区间 [{lo},{hi}] 上界 ≥ 总请求数 {total}"
                    f"——单桶宽到可容纳全部流量，对「算法失效=流量全压一个后端」不可证伪=恒真。"
                    f"收紧容差让 hi < {total}。")
        sum_lo += lo
        sum_hi += hi
        sum_exp += expected

    if not (sum_lo <= total <= sum_hi):
        return (f"守恒矛盾：各桶区间和 [Σlo={sum_lo}, Σhi={sum_hi}] 容纳不下总请求数 {total}"
                f"（实际总命中必 == 总请求数）。检查期望/容差，确保 Σlo ≤ {total} ≤ Σhi。")
    if abs(sum_exp - total) > len(buckets):
        return (f"分布中心偏移：Σ期望命中 {sum_exp} 与总请求数 {total} 相差 > 桶数 {len(buckets)}"
                f"——rr 应每桶≈N/k、wrr 应每桶≈N×w_i/Σw，Σ期望应≈总请求数。")
    return None


# ── 把 dist 声明展开成 N 条普通 found check_point ───────────────────────────────────

def expand_distribution_step(step: dict) -> tuple[list[dict] | None, str | None]:
    """把一个分布声明步 → N 条锚定区间正则的 `found` check_point（每桶一条）。

    声明形态（F="dist"，dist 见下）::

        {"E":"check_point","F":"dist","dist":{
            "total":30, "field":"<count_field_regex>",
            "buckets":[{"anchor":"<backend_anchor_regex>","expected":10,"tol":2}, ...]}}

    展开为每桶一条::

        {"E":"check_point","F":"found",
         "G":"<backend_anchor_regex>[^\\\\n]*<count_field_regex>(?<!\\\\d)(?:[8-9]|1[0-2])(?!\\\\d)"}

    - `field` 锚定命中数字段前缀，依设备回显格式由 agent 给。
    - 默认 `anchor[^\\n]*field<区间>`（命中数与后端标识同行）；若回显格式特殊，桶可给 `pattern`
      模板（含 `{range}` 占位）自定义整条正则，emit 把 `{range}` 替换为带边界的区间正则。
    返回 (steps, None) 或 (None, 打回原因)。
    """
    dist = step.get("dist") or {}
    total = dist.get("total")
    field = str(dist.get("field", ""))
    buckets = dist.get("buckets")
    err = validate_distribution(total, buckets)
    if err:
        return None, err

    out: list[dict] = []
    for b in buckets:
        anchor = str(b["anchor"])
        lo, hi = _bucket_bounds(int(b["expected"]), int(b.get("tol", 0)))
        rng = range_regex_for_count(lo, hi)
        tmpl = b.get("pattern")
        if tmpl:
            if "{range}" not in str(tmpl):
                return None, f"bucket({anchor}) 的 pattern 模板必须含 {{range}} 占位"
            g = str(tmpl).replace("{range}", rng)
        else:
            g = f"{anchor}[^\\n]*{field}{rng}"
        out.append({
            "E": "check_point", "F": "found", "G": g,
            # fallback desc 写人话:交付卷 desc 是执行工程师读的,不出现内部术语
            # (「分布区间断言」)与集合符号(∈)——2026-07-05 v12 交付卷抽查 29/154 条
            # 违规全部来自本模板,worker 给了 desc 则原样用。
            "desc": str(b.get("desc") or f"{anchor} 池累计命中应在 {lo} 到 {hi} 次之间"),
        })
    return out, None


def _is_dist_step(step) -> bool:
    return (isinstance(step, dict) and str(step.get("F", "")).strip() == "dist"
            and bool(step.get("dist")))


def expand_distribution_steps(steps: list) -> tuple[list | None, list | None, str | None]:
    """展开 steps 里所有 dist 声明。返回 (new_steps, plan, error)。

    plan 与**原** steps 同序，每项 ("dist", N) 或 ("normal", 1)，供 provenance 同步展开
    （emit 接线用，保证 provenance.steps 与展开后 steps 仍逐位对齐）。
    """
    new_steps: list = []
    plan: list[tuple[str, int]] = []
    for s in steps:
        if _is_dist_step(s):
            expanded, err = expand_distribution_step(s)
            if err:
                return None, None, err
            new_steps.extend(expanded)
            plan.append(("dist", len(expanded)))
        else:
            new_steps.append(s)
            plan.append(("normal", 1))
    return new_steps, plan, None


def expand_provenance_steps_with_plan(prov_steps_raw, plan):
    """按 plan 把 provenance 的 steps 列表与 steps 同步展开（dist 桶标 layer=V/distribution_derived）。

    prov_steps_raw 长度须 == plan 长度（= 原 steps 数）；不一致则原样返回，交给下游 backfill 自行
    判断（长度对不上 → 旁挂跳过，xlsx 仍正常产出）。
    """
    if not isinstance(prov_steps_raw, list) or len(prov_steps_raw) != len(plan):
        return prov_steps_raw
    out: list = []
    for raw, (kind, n) in zip(prov_steps_raw, plan):
        if kind == "dist":
            ref = ""
            if isinstance(raw, dict):
                ref = (raw.get("source") or {}).get("ref", "") or ""
            for _ in range(n):
                out.append({"E": "check_point", "F": "found", "G": "", "layer": "V",
                            "source": {"kind": "distribution_derived", "ref": ref}})
        else:
            out.append(raw)
    return out
