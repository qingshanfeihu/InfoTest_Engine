"""submit_behavior_fact:设备行为知识**候选**登记(V6 支柱2b,归因孔③的子义务)。

候选≠直接入库:落 outputs/<autoid>/behavior_candidates.json,由引擎 writeback 节点
按结局分流(自愈环,2026-07-08)——该 case **上机真 PASS** → 机械晋升为 verified
(RawFact(behavior)+device_evidence,经 merger 的 device_verified 门);**fail/escalated**
→ 以 validity=uncertain + 观测语境入库(带标渲染、不冒充已验证,同 fact_key 将来 PASS
实证时自动升级)。fail 轮的观察恰恰最有信息量,照常登记,别因未通过而少登记。

机械校验:observe_cmd 必须真实出现在该 case 卷面的 APV 命令里(读 case.xlsx),
防"给不存在的观测编行为"。
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from langchain_core.tools import tool

logger = logging.getLogger(__name__)


@tool(parse_docstring=True)
def submit_behavior_fact(autoid: str, observe_cmd: str, content: str, note: str = "") -> str:
    """Register a device-behavior knowledge candidate (echo format / counter semantics /
    assertion-technique observations).

    Candidates are not stored directly: on a true on-device PASS the engine promotes them to
    verified (device-evidence gate); fail/escalated observations enter at uncertain level with
    their context and auto-upgrade once a later PASS confirms them. Fail-round observations
    carry the most information — register them as usual. The observation command must actually
    appear on this case's sheet.

    Args:
        autoid: This case's autoid (18 digits).
        observe_cmd: The observation command this behavior anchors to (verbatim from the sheet,
            e.g. a show/statistics command) — the knowledge attaches to this command's
            footprint node.
        content: Statement of the observed behavior (what it is and which echo supports it;
            state facts, not instructions).
        note: Optional supplement.

    Returns:
        Registration confirmation, or the validation failure reason.
    """
    aid = (autoid or "").strip()
    cmd = (observe_cmd or "").strip()
    body = (content or "").strip()
    if not aid or len(aid) != 18 or not aid.isdigit():
        return f"error: autoid must be an 18-digit number, got {autoid!r}"
    if not cmd or not body:
        return "error: observe_cmd and content are required"

    # F-Py-9b-1b(写侧补口):读 case.xlsx 走 _sh.outputs_root() 单一根隔离(生产==parents[4]、字节等价)。
    from main.ist_core.compile_engine_v8 import _shared as _sh
    xlsx = _sh.outputs_root() / aid / "case.xlsx"
    if not xlsx.is_file():
        return f"error: this case has no sheet ({xlsx.name} missing), nothing to anchor the behavior to"
    try:
        from main.ist_core.tools.device.batch_tools import _xlsx_apv_lines
        cmds = _xlsx_apv_lines(xlsx).get(aid, [])
    except Exception as e:  # noqa: BLE001
        return f"error: failed to read the case sheet: {e}"
    if cmd not in cmds:
        return (f"error: observe_cmd is not among this case's APV commands on the sheet — "
                f"behavior knowledge must anchor to an observation command that actually ran "
                f"(the sheet has {len(cmds)} commands; copy one verbatim).")

    cand_path = xlsx.parent / "behavior_candidates.json"
    cands: list = []
    if cand_path.is_file():
        try:
            cands = json.loads(cand_path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            cands = []
    cands = [c for c in cands if not (c.get("observe_cmd") == cmd
                                      and c.get("content") == body)]
    cands.append({"observe_cmd": cmd, "content": body, "note": (note or "").strip()})
    cand_path.write_text(json.dumps(cands, ensure_ascii=False, indent=2), encoding="utf-8")
    return (f"Behavior candidate registered ({len(cands)} on file) — it is promoted into the "
            "knowledge base automatically once this case truly PASSes on device; on fail it "
            "is not stored.")
