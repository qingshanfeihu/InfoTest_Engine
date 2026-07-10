"""导出修法队列(THEORY 互扰消解推论+三权分立的机械执行体,DESIGN §11.7)。

队列 = f(事实流, 卷面通道命中, 文法数据) 的纯函数——引擎的"下一步"永远可导出;
**案进 ask 的机械前提 = 队列为空**(队列非空即问 = 引擎把自己的判定推给用户)。

修法动作闭集(理论序:自清理 > 定向重编 > 隔离复跑 > 换形态):
- self_cleanup   互扰消解首选(通道 case_mitigation 数据驱动;复合排尾由 merge 自动施加)
- recompile_directed  归因给出 fix_direction 且其后未重编过
- rerun_isolated 矛盾案卷面无嫌疑时先隔离复跑对照(不盲改卷)
- vary_form      缺陷候选必须换形态复现坐实(行为层可导性推论)

"已试"判据全部机械:authored 事实的 remedy 戳(author 派发时盖)+ attribution 的
disposition 史。新通道/新义务 = 改 domain_grammar JSON,本模块零改(自愈合纪律)。
"""

from __future__ import annotations

from main.ist_core.compile_engine_v8 import facts as F
from main.ist_core.compile_engine_v8 import persistence as P


def _tried_remedies(mine: list[dict]) -> set[str]:
    """已试修法集:authored.remedy 戳 ∪ disposition 史(机械,不读散文)。"""
    tried: set[str] = set()
    for f in mine:
        if f.get("ev") == "authored" and f.get("remedy"):
            tried.add(str(f.get("remedy")))
        if f.get("ev") == "attribution":
            disp = str(f.get("disposition") or "")
            if disp == "rerun_isolated":
                tried.add("rerun_isolated")
    return tried


def _channel_specs(case_rows: list[dict]) -> list[tuple[str, dict]]:
    hits = P.case_channels(case_rows or [])
    out = []
    for name in sorted(hits):
        spec = P._channels().get(name) or {}
        if spec.get("case_mitigation"):
            out.append((name, spec))
    return out


def derive_queue(mine: list[dict], aid: str, case_rows: list[dict]) -> list[dict]:
    """该案当前的未试修法队列(理论序)。mine=该案事实子流。

    仅对「最新裁决为 fail」的案有意义(pass/未上机返回空——无需修)。
    每项: {action, channel?, obligation?, refs?, direction?}。
    """
    last = F.latest_verdict(mine, aid)
    if not last or last.get("result") != "fail":
        return []
    tried = _tried_remedies(mine)
    contra = F.contradictions(mine, aid)
    atts = [f for f in mine if f.get("ev") == "attribution"]
    last_att = atts[-1] if atts else {}
    queue: list[dict] = []

    # ① 案内自清理(互扰消解首选;命中持久通道的 fail/矛盾案——自我包含是编写义务,
    #   与失败原因无关地优先补齐,矛盾案尤然)
    for name, spec in _channel_specs(case_rows):
        key = f"self_cleanup:{name}"
        if key not in tried:
            cm = spec["case_mitigation"]
            queue.append({"action": "self_cleanup", "channel": name, "remedy_key": key,
                          "obligation": str(cm.get("obligation") or ""),
                          "refs": list(cm.get("refs") or [])})

    # ② 定向重编:最新归因给了方向、其后未重编(authored round ≤ 归因 round;
    #   remedy_key 按归因轮键控——新一轮归因给出新方向即再次可试)
    if last_att and str(last_att.get("disposition")) in ("reflow", "frozen"):
        att_round = int(last_att.get("round") or 0)
        key = f"recompile_directed:r{att_round}"
        if F.rounds_used(mine, aid) <= att_round and key not in tried:
            queue.append({"action": "recompile_directed", "remedy_key": key,
                          "direction": str(last_att.get("fix_direction") or "")[:400]})

    # ③ 隔离复跑:矛盾案(单跑过整卷挂/交付态被反证)未做过对照
    if contra > 0 and "rerun_isolated" not in tried:
        queue.append({"action": "rerun_isolated", "remedy_key": "rerun_isolated"})

    # ④ 换形态:缺陷候选必须换形态坐实
    if str(last_att.get("disposition")) == "defect_candidate" and "vary_form" not in tried:
        queue.append({"action": "vary_form", "remedy_key": "vary_form"})

    return queue


def queue_empty(mine: list[dict], aid: str, case_rows: list[dict]) -> bool:
    """ask 边的机械前置门(§11.7):导出修法队列为空才允许问用户。"""
    return not derive_queue(mine, aid, case_rows)
