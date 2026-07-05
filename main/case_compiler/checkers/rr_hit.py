"""rr/wrr 命中计数的线性状态机(V4 步骤5;linalg §8)。

理想 rr:k 个池循环轮转,起点由运行时决定(黑盒不可知)。N 次同类型请求后,
池 i 的累计 Hit 是确定性区间——base = N//k, r = N%k:
- r == 0 → 每池恰好 base(与起点无关,精确值);
- r > 0  → 每池 ∈ {base, base+1},且恰有 r 个池取 base+1(取哪 r 个由起点决定)。

wrr:2026-07-03/04 两轮实测设备各池命中配比与配置权重不符(疑似产品缺陷,
缺陷候选在案)——模型置信度低,输出降级为参与性区间 [1, N](或 [0, N] 当
池可能不参与),不给权重比例区间。

地址族过滤:只有含目标记录类型地址的池参与该类型查询的轮转(实证:A 查询
不落 v6-only 池,其 Hit 恒 0)。
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class HitRange:
    lo: int
    hi: int
    confidence: str   # exact | high | low
    note: str = ""

    def as_pattern_hint(self) -> str:
        if self.lo == self.hi:
            return f"Hit 恰为 {self.lo}"
        return f"Hit ∈ [{self.lo}, {self.hi}]"


def rr_hit_range(n_requests: int, n_pools: int, pool_participates: bool = True) -> HitRange:
    """理想 rr 下单池累计 Hit 的可验区间(起点未知)。"""
    if n_pools <= 0 or n_requests < 0:
        return HitRange(0, max(0, n_requests), "low", "参数不合法,退化为全区间")
    if not pool_participates:
        return HitRange(0, 0, "exact", "该池不含目标记录类型地址,不参与该类型查询轮转")
    base, r = divmod(n_requests, n_pools)
    if r == 0:
        return HitRange(base, base, "exact", f"{n_requests}次/{n_pools}池整除,与起点无关")
    return HitRange(base, base + 1, "high",
                    f"{n_requests}次/{n_pools}池,余{r}——恰有{r}个池取上界,取哪几个由运行时起点决定")


def wrr_hit_range(n_requests: int, n_pools: int, weight: int = 0,
                  pool_participates: bool = True) -> HitRange:
    """wrr 下单池累计 Hit——设备实测配比与配置权重不符(两轮实证,疑似产品缺陷),
    不给比例区间,降级为参与性。

    降级不是永久假设——复核条件:该缺陷候选核实/修复后,拿一针 wrr 探针(权重 3:2:1、
    发若干轮)重跑,若各池命中≈权重比即恢复 weight_ratio 精确区间。当前保守是因为
    2026-07 两轮实测未观察到配比,缺陷单落实后更新此函数与 note。"""
    if not pool_participates:
        return HitRange(0, 0, "exact", "该池不参与该类型查询")
    if n_requests <= 0:
        return HitRange(0, 0, "exact", "零请求")
    lo = 1 if (weight > 0 and n_requests >= n_pools) else 0
    return HitRange(lo, n_requests, "low",
                    "wrr 实测配比与配置权重不符(疑似产品缺陷在案)——仅参与性可验,"
                    "精确配比留缺陷候选核实,不要写权重比例断言")


def rr_hit_range_segmented(n_requests: int, n_pools: int, uninterrupted: bool,
                           pool_participates: bool = True) -> HitRange:
    """带适用域判定的 rr 区间(回放实证,本地 2026-07-04 晚探针;设备侧时钟 +5h40m
    故 junitxml 时间戳显示 07-05,同一批实测):

    - **单段连续查询**(dig 之间无 show/配置插入):区间模型 6/6 池级样本命中
      (整除→精确、余数→[base,base+1] 且恰 r 池取上界)——confidence 沿用 exact/high。
    - **跨段累计**(段间插入过 show statistics 等):实测轮转态漂移(11 次分两段得
      5/3/3,超出理想区间)——精确区间不可用,降级 low、建议每段独立断言或参与性。
    """
    if not uninterrupted:
        base = HitRange(0 if n_requests == 0 else 1, n_requests, "low",
                        "查询序列被 show/配置步分段——设备实测(2026-07-05 探针)分段后轮转态"
                        "漂移,精确区间不成立。改法:每个连续段单独 show 单独断言(段内可用"
                        "精确区间),或对累计只断言参与性。")
        return base
    return rr_hit_range(n_requests, n_pools, pool_participates)
