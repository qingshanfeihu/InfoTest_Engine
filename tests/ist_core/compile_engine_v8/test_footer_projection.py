"""Footer 九态投影完整性(item1 回归:emit_tick 的 13→9 投影不得丢态)。

活证 29906 round1:broken 三态漏投 → footer 桶和 51 < total 53、broken 案凭空消失。
本测试动态枚举 views 全部 case 状态,断言九桶之和==状态数(残差 0)——若日后新增一个
case 状态却没更新 `_footer_bucket_counts`,本测试即红(正是当年 broken 三态漏投的坑型)。
"""
from main.ist_core.compile_engine_v8 import _shared as sh
from main.ist_core.compile_engine_v8 import views as V


def _all_status_values() -> list[str]:
    """views 里全部 S_* 派生状态标签的字符串值(= view()['counts'] 的合法键域)。"""
    return [getattr(V, n) for n in dir(V)
            if n.startswith("S_") and isinstance(getattr(V, n), str)]


def test_footer_projection_complete_no_state_dropped():
    statuses = _all_status_values()
    counts = {s: 1 for s in statuses}          # 每态各 1 个 case
    buckets = sh._footer_bucket_counts(counts)
    assert sum(buckets.values()) == len(statuses), (
        f"footer 投影丢态:Σ九桶={sum(buckets.values())} ≠ 状态数={len(statuses)};"
        f"未投影的状态会在 footer 凭空消失(29906 broken 三态坑型)。buckets={buckets}")


def test_footer_projection_broken_three_states_bucketed():
    # broken 三态必须落桶(item1 修复点):否则 footer < total
    counts = {"broken": 2, "broken_errored": 1, "broken_blocked": 3}
    buckets = sh._footer_bucket_counts(counts)
    assert sum(buckets.values()) == 6
    assert buckets["failed_active"] == 6   # 非通过/非终态/仍在环内 → failed_active


def test_footer_projection_all_pass_unchanged():
    # 全通过批:仅 deliverable → passed 桶,残差 0(happy-path 零行为变化保真)
    buckets = sh._footer_bucket_counts({"deliverable": 5})
    assert buckets["passed"] == 5
    assert sum(buckets.values()) == 5
