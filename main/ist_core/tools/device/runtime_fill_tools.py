"""上机回填 tools：列 <RUNTIME> 槽位 + 把设备真实值锁死回填进 case.xlsx。

配合 ist-fill fork：fork 先 dev_run_batch/dev_run_case 拿设备真实输出，再 compile_runtime_slots
看有哪些待填槽位（及各自的前序观测命令），把每个槽位的真实值从设备输出里抽出来，
调 compile_runtime_fill 锁死写入。抽不出就给空值＝如实留空，绝不猜。

红线：本模块不编值、不解析领域语义。值由 fork（看设备真实输出）给定；锁由 runtime_fill
结构性保证（只动含 <RUNTIME> 的格子，填完即锁）。
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from langchain_core.tools import tool

logger = logging.getLogger(__name__)


def _resolve(xlsx_path: str):
    """走 agent 沙箱多根解析定位 xlsx（与 dev_run_case 一致）。"""
    p = None
    try:
        from main.ist_core.tools.deepagent.file_tools import _resolve_inside_root
        p = _resolve_inside_root(xlsx_path, must_exist=True)
    except Exception:
        p = None
    if p is None or not Path(p).is_file():
        cands = [Path(xlsx_path)]
        if not Path(xlsx_path).is_absolute():
            root = Path(__file__).resolve().parents[4]
            cands += [root / xlsx_path, root / "knowledge" / "data" / xlsx_path]
        p = next((c for c in cands if c.is_file()), None)
    return Path(p) if (p and Path(p).is_file()) else None


@tool(parse_docstring=True)
def compile_runtime_slots(xlsx_path: str) -> str:
    """列出 case.xlsx 里所有**待上机回填的 <RUNTIME> 槽位**（draft 诚实留空的不可知期望值）。

    每个槽位给出：slot_id、autoid、当前 G 全文（含 <RUNTIME>）、断言方法、**紧邻前序观测步的命令**
    （设备据它产出输出——你要回填的真实值就从这条命令的设备真实输出里抽）。

    用法：上机跑完（dev_run_batch / dev_run_case）拿到设备逐步骤真实输出后，调本工具看有哪些槽位，
    把每个槽位对应的真实值从设备输出里抽出来，再调 compile_runtime_fill 写入。

    **已回填的槽位不会出现在列表里**（填完即不含 <RUNTIME>，天然锁死）——所以本工具列出的永远
    只是"还没填的"，重复调用幂等。

    Args:
        xlsx_path: case.xlsx 路径（通常 workspace/outputs/<脑图名>/case.xlsx）。

    Returns:
        JSON：{"count": N, "slots": [{slot_id, autoid, row, current_g, method, observe_obj, observe_cmd}]}。
        count=0 表示没有待填槽位（全是可溯源的确定值或已回填完）。
    """
    p = _resolve(xlsx_path)
    if p is None:
        return json.dumps({"error": f"xlsx 不存在: {xlsx_path}"}, ensure_ascii=False)
    try:
        from main.case_compiler.runtime_fill import list_runtime_slots
        slots = list_runtime_slots(p)
    except Exception as e:  # noqa: BLE001
        return json.dumps({"error": f"扫描槽位失败: {e}"}, ensure_ascii=False)
    return json.dumps({"count": len(slots), "slots": [s.to_dict() for s in slots]},
                      ensure_ascii=False, indent=2)


@tool(parse_docstring=True)
def compile_runtime_fill(xlsx_path: str, fills_json: list | str = "", run_meta: str = "") -> str:
    """把设备真实值**锁死回填**进 case.xlsx 的 <RUNTIME> 槽位（不反复改的硬保证在此）。

    只动仍含 <RUNTIME> 的格子；填上后该格子不再含占位符 → 后续任何回填都定位不到它，
    **永不覆盖已填值**（锁是结构性的，不靠你自律）。所以同一槽位你只能填一次，填错也不会被你
    下一轮悄悄改掉——要改得人工介入。

    你给的值必须来自**设备真实输出**（dev_run_batch / dev_run_case / dev_probe 拿到的）。
    抽不出某槽位的真实值就给空值（或干脆不传该槽位）＝如实留空，**绝不猜一个**。

    fills_json 是 JSON 数组，每项三个键：slot_id（来自 compile_runtime_slots）、
    runtime_value（替换 <RUNTIME> 那一段的设备真实值，空＝抽不出留空）、evidence（可选，取值依据的输出片段）。
    例：``[{"slot_id":"123#0","runtime_value":"active","evidence":"status: active"}]``

    Args:
        xlsx_path: case.xlsx 路径。
        fills_json: **首选原生数组**(JSON 数组字符串兼容)。每项含 slot_id、真实值与
            必填的 evidence——取值依据的设备输出片段;值只能来自设备真实输出,缺依据即拒。
        run_meta: 可选运行标识（如 build / task 串），写入 provenance 溯源。

    Returns:
        回填汇总：filled / left_blank（如实留空）/ not_found（已锁死或 id 错）各 slot_id + 明细。
    """
    p = _resolve(xlsx_path)
    if p is None:
        return f"error: xlsx 不存在: {xlsx_path}"
    try:
        fills = json.loads(fills_json) if isinstance(fills_json, str) else fills_json
        if not isinstance(fills, list):
            return "error: fills_json 必须是数组(首选原生数组)"
    except Exception as e:  # noqa: BLE001
        return f"error: fills_json 解析失败: {e}(建议直接传原生数组)"
    # evidence 必填(A 层):值必须来自设备真实输出——无依据的回填与"绝不猜一个"红线冲突。
    _no_ev = [str(f.get("slot_id", "?")) for f in fills
              if isinstance(f, dict) and str(f.get("runtime_value", "") or "").strip()
              and not str(f.get("evidence", "") or "").strip()]
    if _no_ev:
        return ("error: 以下槽位填了值但没给 evidence(取值依据的设备输出片段): "
                + ", ".join(_no_ev) + "。值必须溯源设备真实输出;抽不出就留空,绝不猜。")

    try:
        from main.case_compiler.runtime_fill import apply_fills, list_runtime_slots
        root = Path(__file__).resolve().parents[4]
        _slots_before = {s.slot_id: s for s in list_runtime_slots(p)}
        res = apply_fills(p, fills, project_root=root, run_meta=run_meta)
    except Exception as e:  # noqa: BLE001
        return f"error: 回填失败: {e}"

    # sidecar 记账(2026-07-05 生命周期洞修复):回填只写给定卷(通常是合并卷),
    # per-case 卷仍是 <RUNTIME>——之后任何重合并会从 per-case 卷重建,**静默丢掉
    # 全部已填值**(v12 实跑整卷重合并过两次,恰逢 RUNTIME=0 才没炸)。把成功回填
    # 记到卷同目录 runtime_fills.json(键=autoid+原 G 全文:内容级、跨卷稳定——
    # 行号跨卷必漂不可用),compile_emit_merged 合并后按内容匹配自动重放:卷面
    # 未变必中,变了必不中(安全跳过,不猜)。
    try:
        if res.filled:
            _fill_by_id = {str(f.get("slot_id")): f for f in fills if isinstance(f, dict)}
            side = Path(p).parent / "runtime_fills.json"
            records: list[dict] = []
            if side.is_file():
                try:
                    records = [r for r in json.loads(side.read_text(encoding="utf-8"))
                               if isinstance(r, dict)]
                except Exception:  # noqa: BLE001
                    records = []
            # 内容键含前序观测命令(observe_cmd):整值槽的 G 全是 <RUNTIME> 不独特,
            # 真正锚定"该填什么值"的是产出该值的那条观测命令。case 重编改了观测→键变→
            # 不重放(值失效);观测没变→键稳→旧值仍有效可重放。
            byk = {(r.get("autoid"), r.get("observe_cmd"), r.get("g_original")): r for r in records}
            for sid in res.filled:
                s = _slots_before.get(sid)
                f = _fill_by_id.get(sid)
                if not s or not f:
                    continue
                byk[(s.autoid, s.observe_cmd, s.current_g)] = {
                    "autoid": s.autoid, "observe_cmd": s.observe_cmd, "g_original": s.current_g,
                    "runtime_value": str(f.get("runtime_value") or ""),
                    "evidence": str(f.get("evidence") or "")[:500],
                }
            import os as _os
            _tmp = side.with_suffix(".json.tmp")
            _tmp.write_text(json.dumps(list(byk.values()), ensure_ascii=False, indent=1),
                            encoding="utf-8")
            _os.replace(_tmp, side)
    except Exception:  # noqa: BLE001
        logger.debug("runtime_fills sidecar 记账失败(回填本身已完成)", exc_info=True)

    lines = [f"=== compile_runtime_fill ===", res.summary(),
             f"filled: {res.filled}", f"left_blank(如实留空,不猜): {res.left_blank}",
             f"not_found(已锁死/ id 错): {res.not_found}", "--- 明细 ---"]
    lines += res.details
    remaining = 0
    try:
        from main.case_compiler.runtime_fill import list_runtime_slots
        remaining = len(list_runtime_slots(p))
    except Exception:  # noqa: BLE001
        pass
    lines.append(f"--- 本 xlsx 仍待回填槽位数: {remaining}（含本次留空的）---")
    return "\n".join(lines)
