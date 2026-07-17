# pytest 产物隔离 patch（审计 4-3-①；待批间隙验证后合入，当前未生效）

> 状态：**已写好、未合入**（leader 裁决：产物 fixture 动 conftest 面大，批间隙验证后再合）。
> 日志隔离（4-3-②）已另行落地生效（loader.py `PYTEST_CURRENT_TEST` 检测，见 #18 diff 摘要）——本 patch 只覆盖**产物**侧。

## 前置事实（写 patch 时勘探到的结构约束，修正报告原方案 A）

报告 4-3-① 原推荐「conftest autouse fixture 统一 monkeypatch outputs_root 到 tmp_path」。实勘发现**工具层没有可 patch 的单点**：

- 可 patch 点（模块级函数，monkeypatch 可达）：`compile_engine_v8/_shared.py: project_root()/outputs_root()`、`tools/device/batch_tools.py: _project_root()`；
- **不可 patch 点**：`emit_xlsx_tool.py`（8+ 处）、`verifiability_tool.py`（3 处）、`compile_prep.py`（2 处）、`precedent_tools.py`（2 处）的 root 全是**函数体内 inline** `Path(__file__).resolve().parents[4]`——monkeypatch 无落点。

故方案修订为**混合三件**：①可 patch 点 fixture 化；②不可 patch 点走「前缀白名单 + session 时间窗」终扫搬运（零生产改动、双判据无误删面）；③长期解（工具层 root 收敛为共同函数、单点可 patch）列 #15 备选，属生产结构清理非本轮。

## Patch 内容（对 `tests/conftest.py` 的增量，直接追加到文件尾）

```python
# ── pytest 产物隔离(审计 4-3-①,两段式) ─────────────────────────────────────
# ①V8 引擎链路测试:outputs 根改指 tmp(模块级函数可 monkeypatch 的点全部收口;
#   多数 v8 测试的 rig 已各自 patch,本夹具兜住漏网的直调)。
# ②工具层直调测试(emit/prep/verifiability 的 root 是函数内 inline 表达式,无
#   patch 点):session 结束按「已知测试前缀 ∧ mtime 在本 session 窗口内」双判据
#   把产物从 workspace/outputs/ 搬到系统 tmp——前缀与真编译产物(批名/18 位
#   autoid 目录)零交集,时间窗防误搬历史同名残留;搬运非删除,可回查。
import shutil
import tempfile
import time
from pathlib import Path

_TEST_PRODUCT_PREFIXES = (
    "_pytest_",     # _pytest_merged/_pytest_prep_*/_pytest_runbatch/_pytest_lint_merged…
    "t_",           # t_dist/t_fill_*/t_good/t_prov*…(runtime_fill/emit 族测试产物)
    "R_sig",        # test_fail_signatures 产物
)
_SESSION_T0 = time.time()


@pytest.fixture(autouse=True)
def _isolate_v8_outputs(request, monkeypatch, tmp_path_factory):
    """V8 引擎链路的产物根指向 tmp(仅对未自带 rig-patch 的测试兜底;rig 内
    setattr 后到,天然覆盖本兜底,互不干扰)。"""
    try:
        from main.ist_core.compile_engine_v8 import _shared as sh
        base = tmp_path_factory.mktemp("v8_outputs")
        monkeypatch.setattr(sh, "outputs_root", lambda: base, raising=True)
    except Exception:
        pass
    yield


def pytest_sessionfinish(session, exitstatus):
    """工具层直调测试的产物终扫:前缀白名单 ∧ session 时间窗 → 搬去 tmp。
    双判据缺一不搬(真编译产物是批名/autoid 目录,不匹配前缀;历史同名残留
    mtime 早于本 session,不在窗口)。搬运目的地保留供回查,不静默删除。"""
    out = Path(__file__).resolve().parents[1] / "workspace" / "outputs"
    if not out.is_dir():
        return
    dest = Path(tempfile.gettempdir()) / f"ist_pytest_products_{int(_SESSION_T0)}"
    for item in out.iterdir():
        try:
            if not item.name.startswith(_TEST_PRODUCT_PREFIXES):
                continue
            if item.stat().st_mtime < _SESSION_T0 - 5:
                continue                      # 本 session 之前的同名残留不动(留人工判)
            dest.mkdir(parents=True, exist_ok=True)
            shutil.move(str(item), str(dest / item.name))
        except Exception:
            pass                              # 清扫失败不影响测试结论
```

## 已知边界（如实声明）

1. `_isolate_v8_outputs` 与既有 rig 夹具的 setattr 顺序：autouse 先执行、rig 后执行——rig 的 `monkeypatch.setattr(sh, "outputs_root", …)` 覆盖本兜底，**互不冲突**（都在各自 teardown 还原）。
2. 部分工具层测试**断言产物路径**（如 test_xlsx_lint_gates 从 `workspace/outputs/_pytest_lint_merged/` 回读）——终扫在 sessionfinish（所有断言之后），不影响断言；但若未来有跨 session 依赖产物的测试（不该有），会被搬走暴露。
3. `t_` 前缀较短，理论上可能撞未来的真实批名——真编译批名来自脑图 stem（中文/长名），实际零交集；若担心可把白名单收紧为精确清单。
4. **验证步骤**（批间隙执行）：合入 → 跑全量 pytest → 断言 ①`workspace/outputs/` 无新增 `_pytest_*/t_*/R_sig`（被搬走）②真编译产物目录 untouched ③全量仍 2141+ passed。

## 长期解（#15 备选登记）

工具层 15+ 处 inline `Path(__file__).resolve().parents[4]` 收敛为共同 `project_root()`（挂 `main/common/env.py` 或复用 `knowledge_paths`），产物根单点可 patch——彼时本 patch ②段可退役，①段扩为全域单点。属生产结构清理（触 emit/verifiability 等运行链路文件），需独立回归轮，不塞本批。

*Py-Eng · 2026-07-17 · 任务 #18 交付件（待验证合入）*
