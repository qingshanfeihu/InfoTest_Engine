"""终验路由:子集轮收敛于「部分 pass+部分终态」时必须回 merge 做终验整卷。

zhaiyq 实证(2026-07-06):每轮都有 failed_terminal 垫底 → _after_attribute 直接
writeback → 终验整卷从未发生 → 主交付卷停在 round1 旧版(600046 重编已修对,
交付物却是恒真+恒 fail 的旧断言,且主卷从未整卷上机)。
"""
from main.ist_core.compile_engine.graph import _after_attribute, _after_run


def test_subset_converged_with_terminal_tail_goes_final_merge():
    # 子集轮后全终态(active fail=0)且有 pass → 终验整卷
    s = {"run_scope": "subset", "n_passed": 51, "n_failed_active": 0,
         "n_pending_compile": 0, "round": 3, "max_rounds": 3}
    assert _after_attribute(s) == "merge"


def test_final_full_run_then_writeback_no_loop():
    # 终验 run 后 run_scope=full → 不再命中终验分支(无环)
    s = {"run_scope": "full", "n_passed": 51, "n_failed_active": 0,
         "n_pending_compile": 0, "round": 3, "max_rounds": 3}
    assert _after_attribute(s) == "writeback"
    assert _after_run({"phase_status": "ok", "run_scope": "full",
                       "n_failed_active": 0}) == "writeback"


def test_capped_with_active_fail_still_reports_honestly():
    # 封顶且仍有 active fail:不借终验绕过轮次上限,维持如实报告
    s = {"run_scope": "subset", "n_passed": 10, "n_failed_active": 2,
         "n_pending_compile": 0, "round": 3, "max_rounds": 3}
    assert _after_attribute(s) == "writeback"


def test_zero_passed_all_terminal_skips_final_verify():
    # 全军覆没(passed=0)没有可终验的东西 → writeback 如实报告
    s = {"run_scope": "subset", "n_passed": 0, "n_failed_active": 0,
         "n_pending_compile": 0, "round": 2, "max_rounds": 3}
    assert _after_attribute(s) == "writeback"
