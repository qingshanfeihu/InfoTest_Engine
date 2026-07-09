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
    """登记一条设备行为知识候选(回显格式/计数器语义/断言技法类现象)。

    候选不直接入库——上机真 PASS 由引擎晋升为 verified(设备实证门);fail/escalated
    以 uncertain 级带语境入库,PASS 实证后自动升级。fail 轮观察最有信息量,照常登记。
    观测命令必须真实出现在该 case 卷面上。

    Args:
        autoid: 该 case 的 autoid(18 位)。
        observe_cmd: 该行为锚定的观测命令(卷面原文,如某条 show/统计命令)——知识挂
            在这条命令的 footprint 节点下。
        content: 行为现象的陈述(是什么、依据什么回显;写事实不写指令)。
        note: 可选补充。

    Returns:
        登记确认或校验失败原因。
    """
    aid = (autoid or "").strip()
    cmd = (observe_cmd or "").strip()
    body = (content or "").strip()
    if not aid or len(aid) != 18 or not aid.isdigit():
        return f"error: autoid 必须是 18 位数字,收到 {autoid!r}"
    if not cmd or not body:
        return "error: observe_cmd 与 content 必填"

    root = Path(__file__).resolve().parents[4]
    xlsx = root / "workspace" / "outputs" / aid / "case.xlsx"
    if not xlsx.is_file():
        return f"error: 该 case 无卷面({xlsx.name} 不存在),行为无从锚定"
    try:
        from main.ist_core.tools.device.batch_tools import _xlsx_apv_lines
        cmds = _xlsx_apv_lines(xlsx).get(aid, [])
    except Exception as e:  # noqa: BLE001
        return f"error: 卷面读取失败: {e}"
    if cmd not in cmds:
        return (f"error: observe_cmd 不在该 case 卷面的 APV 命令里——行为知识必须锚定"
                f"真实执行过的观测命令(卷面有 {len(cmds)} 条,原样复制其一)。")

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
    return (f"行为候选已登记({len(cands)} 条)——该 case 上机真 PASS 后自动晋升入库,"
            "fail 则不入库。")
