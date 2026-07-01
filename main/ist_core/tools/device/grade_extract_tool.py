"""compile_grade_extract: grade 子流程的确定性探针工具（包装 grade_extract.extract）。

为什么是工具不是 run_python：grade fork 此前靠 `run_python` 跑
`skills/ist_compile_grade/scripts/grade_extract.py`，但 fork 的 run_python cwd/sys.path 不含
项目根、相对路径又依赖 CWD——实测 grade 找不到脚本（"script doesn't exist"）直接 fallback
肉眼判，确定性信号（distribution_coverage_gap_suspect / layer_mismatch / weak_v_coverage_suspect
等）全没生效、放水（778012 写死命中 IP + Hit:固定数 带病 PASS 即此根因）。包成工具后在主进程
内按**绝对路径** importlib 加载 extract()，免 CWD/路径之祸，grade 第一步必能拿到信号。

脚本仍留在 skill 目录（anthropics skill 自洽、可单独命令行跑），本工具只按文件路径加载其 extract()。
红线：只透传 grade_extract 的确定性信号，不下 PASS/CUT 终判（终判仍由 grade LLM 据真证据现场判）。
"""

from __future__ import annotations

import json
from pathlib import Path

from langchain_core.tools import tool


def _load_extract():
    """importlib 按文件路径加载 skill 目录下 grade_extract.py 的 extract()（非 main 包内模块）。"""
    import importlib.util as ilu

    root = Path(__file__).resolve().parents[4]
    script = (root / "main" / "ist_core" / "skills"
              / "ist_compile_grade" / "scripts" / "grade_extract.py")
    if not script.is_file():
        raise FileNotFoundError(f"grade_extract.py 不存在: {script}")
    spec = ilu.spec_from_file_location("ist_compile_grade_extract", script)
    if spec is None or spec.loader is None:
        raise ImportError("无法加载 grade_extract spec")
    mod = ilu.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.extract


@tool(parse_docstring=True)
def compile_grade_extract(xlsx_path: str, prov_path: str = "-") -> str:
    """对一份 case.xlsx 跑确定性探针，返回 V 段覆盖/恒真/分布等结构化信号（grade 判定前第一步必做）。

    grade 第一步调它（别再用 run_python 跑脚本——fork 里 cwd/路径不稳、会找不到脚本而放水）。
    它只产**确定性信号**、不下终判；终判由你据真实证据 + source_ref 现场判。

    Args:
        xlsx_path: 待审 case.xlsx 路径。
        prov_path: 对应 case.provenance.json 路径；无 provenance / 不确定时传 "-"。

    Returns:
        JSON。case 级关键信号：has_distribution_method（配了 rr/wrr）、has_distribution_assertion、
        distribution_coverage_gap_suspect（配了分布算法却无分布区间也无关系断言＝漏测分布）、
        weak_v_coverage_suspect、count_tautology_count（无界 Hit:\\d+ 恒真）、
        count_hardcoded_count（写死单计数 Hit:固定数）、hardcoded_hit_ip_count（分布算法下写死单次
        命中落点 IP）、genuine_v_count、suspect_count；每个 check_point 带 mode/expect/layer/
        observe_kind/is_genuine_v_assertion/layer_mismatch/source_kind/各 suspect 标志/suspect_reason。
    """
    xp = (xlsx_path or "").strip()
    if not xp:
        return "error: 必须指定 xlsx_path"
    if not Path(xp).is_file():
        return f"error: case.xlsx 不存在: {xp}"
    try:
        extract = _load_extract()
    except Exception as e:  # noqa: BLE001
        return f"error: 加载 grade_extract 失败: {e}"
    try:
        facts = extract(xp, (prov_path or "-").strip() or "-")
    except Exception as e:  # noqa: BLE001
        return f"error: grade_extract 执行失败: {e}"
    return json.dumps(facts, ensure_ascii=False, indent=1)
