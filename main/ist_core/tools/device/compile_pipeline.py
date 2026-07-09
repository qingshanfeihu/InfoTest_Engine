"""compile_pipeline 遗留模块 —— 仅保留 V6 引擎复用的两个自包含 helper。

原 V3/v5「确定性编译流水线」`compile_pipeline` @tool 及其内部实现（prep→draft→grade→merge
的整条 main-orchestrated 流水线）已随 v5 编译路径删除（2026-07-07，只保留 V6 引擎）。
保留本文件仅因 V6 引擎节点仍从这里 import 两个自包含 helper：

- ``_emit_progress`` —— `compile_engine/nodes/_shared.py` 用它把进度推到 EventBus。
- ``_grade_extract_facts`` —— `compile_engine/nodes/compile_phase.py` 用它跑机械信号预探针
  （加载 `tools/device/grade_extract_script.py` 的 extract）。

新代码可直接引用这两个函数；不要再往本文件加编排逻辑（编排收在 V6 StateGraph 里）。
"""

from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def _emit_progress(text: str) -> None:
    """把进度推到默认 EventBus → TUI 实时渲染（evidence_added → '· …' 行）。失败一律静默。"""
    try:
        from main.ist_core.events import get_default_bus
        get_default_bus().emit("evidence_added", payload={"text": text})
    except Exception:  # noqa: BLE001
        logger.debug("进度 emit 失败", exc_info=True)


def _project_root() -> Path:
    return Path(__file__).resolve().parents[4]


def _grade_extract_facts(xp: Path, prov: Path, intent_text: str = "") -> dict:
    """确定性预跑 tools/device/grade_extract_script.py 的 extract(xp, prov)，产出机械信号。

    脚本是独立的按文件路径加载脚本（非包内可直接 import 的模块），用 importlib 加载。
    缺失 / import 失败 / extract 抛错时一律吞掉返回 {}，不阻断调用方（可观测性不拖垮主流程）。
    返回结构作为 brief 的 extract_facts= 段并入。
    """
    try:
        import importlib.util as _ilu
        script = (_project_root() / "main" / "ist_core" / "tools"
                  / "device" / "grade_extract_script.py")
        if not script.is_file():
            return {}
        spec = _ilu.spec_from_file_location("grade_extract_script", script)
        if spec is None or spec.loader is None:
            return {}
        mod = _ilu.module_from_spec(spec)
        spec.loader.exec_module(mod)
        facts = mod.extract(str(xp), str(prov), intent_text=intent_text)
        return facts if isinstance(facts, dict) else {}
    except Exception:  # noqa: BLE001
        logger.debug("grade_extract 加载/执行失败: xp=%s", xp, exc_info=True)
        return {}
