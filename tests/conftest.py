"""测试基座公共夹具。"""
import os
import re
from pathlib import Path

import pytest

# F-Py-9(C):conftest 污染门的**过渡债豁免面**——F-Py-9b 系统性隔离(~10 硬编码写点走
# sh.outputs_root + 全局隔离 + 41 读点同改)本修复轮内落地前,这批测试伪键仍再生。
# **精确列名**(非通配模式=fail-closed):门放行这些已知名、硬拒任何**新**伪键(R_sig 已
# F-Py-9 修、故意不列入=其再生即回归被抓)。**★过渡债、非永久放行**(Design 条件2):F-Py-9b
# 落地后按下方来源逐组清除、本集清零、门恢复零豁免(防"过渡态摆烂成永久")。
# 来源映射(F-Py-9b 按此溯源清零):
#   _pytest_merged/_pytest_runbatch/_pytest_gate_merged → test_batch_compile_tools(out_name)
#   _pytest_lint_merged → test_xlsx_lint_gates;   _pytest_prep_* → test_compile_prep
#   t_dist* → test_distribution_emit;   t_prov*/t_good/t_noprov → test_provenance_ir + test_emit_prov_autoassemble
#   t_fill_* → test_runtime_fill;   t_rt_* → test_runtime_fill_replay;   _fanout/wave1/b → test_fanout_concurrency
# 名单=广扫 970 测试实测再生集 + 少数自清理但可能漏网的已知名。
_F_PY_9B_KNOWN_POLLUTION = frozenset({
    "_pytest_merged", "_pytest_runbatch", "_pytest_gate_merged", "_pytest_lint_merged",
    "_pytest_prep_dongkl", "_pytest_prep_dup", "_pytest_prep_redline",
    "_pytest_prep_yzg", "_pytest_prep_zhaiyq", "_fanout", "wave1", "b",
    "t_dist", "t_dist_prov", "t_fill_apply", "t_fill_blank", "t_fill_list",
    "t_fill_lock", "t_fill_prov", "t_good", "t_noprov", "t_prov",
    "t_prov_backfill", "t_prov_mismatch", "t_rt_bad", "t_rt_ok",
})


@pytest.fixture(scope="session", autouse=True)
def _no_new_test_pollution_in_prod_outputs():
    """F-Py-9(C 门·硬拒):session 收尾扫生产 workspace/outputs/ 无**本 session 新增**的**未知**
    测试伪键(非 18 位 autoid、非点开头、不在 F-Py-9b 过渡豁免集)。抓 R_sig 类回归 + 任何新
    硬编码写生产路径。只断言新增、不碰既有真产物(yzg/dongkl 在 before 集)。豁免集随 F-Py-9b 清零。"""
    root = Path(__file__).resolve().parents[1] / "workspace" / "outputs"
    before = {p.name for p in root.iterdir()} if root.is_dir() else set()
    yield
    if not root.is_dir():
        return
    new = {p.name for p in root.iterdir()} - before
    bad = sorted(n for n in new if not re.fullmatch(r"\d{18}", n)
                 and not n.startswith(".") and n not in _F_PY_9B_KNOWN_POLLUTION)
    assert not bad, (
        f"测试污染生产 workspace/outputs/ 新增**未知**伪键: {bad} —— 某测试未隔离写生产路径"
        "(R_sig 类回归或新硬编码);补该测试 tmp 隔离,或若属 F-Py-9b 已知族加进豁免集。")


@pytest.fixture(autouse=True)
def _provenance_optional_for_legacy_tests(monkeypatch):
    """存量测试聚焦各自的门/结构语义,不逐个补 provenance——统一走可选模式。

    provenance 必传门(V4 步骤0)的专项覆盖在 tests/ist_core/tools/
    test_provenance_mandatory.py:那里显式 delenv 后验证拒绝/放行两侧,
    本夹具不会稀释它。
    """
    if "IST_PROVENANCE_OPTIONAL" not in os.environ:
        monkeypatch.setenv("IST_PROVENANCE_OPTIONAL", "1")
