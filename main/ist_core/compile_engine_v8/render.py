"""用户面渲染层(DESIGN §11.2-11.9:一切叙事 = 事实流的确定性投影;渲染时刻零 LLM)。

三条纪律:
1. 与 engine_report 同一 fold(数字可被视图重算复核,INV-1 扩展到人话报告);
2. LLM 产的人话只取判断时刻落账的中文字段(panel 的 hypothesis/ask、决策 answer),
   渲染不生成;
3. 零术语泄漏:状态/语境/层/处置走人话词表,英文枚举与指纹哈希不出用户面
   (leak_scan 机械门,测试与 closing 断言共用)。

修法段是判定式(§11.7):有裁决说裁决、有采信说采信、在问询流程说等待——陈述句,
不设选项;queue 参数是 D 片修法队列的接缝(本片恒空)。
"""

from __future__ import annotations

import re
import time

# ── 人话词表(用户面模板内容,语言分层的既定例外;机器枚举 → 中文) ────────────────

STATUS_CN = {
    "deliverable": "验证通过",
    "subset_verified": "单独验证通过(待整卷复验)",
    "authored": "已编写(未上机)",
    "failed": "上机未通过",
    "contradicted": "单独能过、整卷复验会挂(用例间相互干扰)",
    "failed_terminal": "按裁决收尾(未通过卷)",
    "escalated": "引擎无法继续(需人工)",
    "awaiting_user": "等待你的决定",
    "suspended": "挂起(下批继续)",
    "pending": "未开始",
    "delivery_blocked": "验证通过但卷面缺案尾清理——暂不交付(重编补自清后可交付)",
    "broken": "未跑成(执行中断/日志陈腐/级联受害)——结论无效,已安排复跑",
    # pyATS 七码子分类(§④):broken 按协议级硬码细分处置(用户面人话)
    "broken_errored": "未跑成·断言/命令写坏了(断言被设备实际回显反证,或命令执行失败)"
                      "——原样复跑必再错,已安排重写",
    "broken_blocked": "未跑成·设备不可达(ping 不通)——复跑救不了死设备,需恢复环境后继续",
}
CTX_CN = {"delivery": "整卷连跑复验", "subset": "单独验证"}
LAYER_CN = {"G": "设备拒绝了命令(语法/能力)", "E": "环境/测试床问题",
            "V": "设备真实行为与断言不符", "transient": "偶发波动(重跑消失)",
            "product_defect": "疑似产品缺陷", "user": "用户裁决"}
DISP_CN = {"reflow": "带反馈重新编写", "frozen": "原方法已证无效,换法重编",
           "env_blocked": "按环境阻塞收尾", "defect_candidate": "缺陷候选(需换形态坐实)",
           "fixed": "已修复待复跑", "rerun_isolated": "卷面无嫌疑,隔离复跑对照",
           "user_stop": "按你的裁决停止(未通过如实报告)",
           "engineering_fault": "工程故障(引擎缺口,已呈报,非产品缺陷)"}
# escalated 子类人话(B-1 de-escalate 通道,§2.2 报告去向行)
_ESC_SUBCLASS_CN = {"no_output": "本轮编写未产出(可能撞到并发或墙钟限制)",
                    "not_executed": "连续多轮未能在设备上跑成",
                    "no_ledger_channel": "判定为欠定,但没有可落账的问询通道"}
_ESC_ROUTE_CN = {"no_output": "重编", "not_executed": "换床复跑"}
SHAPE_CN = {"manual_vs_device": "手册与实机不符",
            "expected_vs_observed": "预期结果与上机行为不符",
            "method_vs_implementation": "验证方法与功能实现不符",
            "ordering_vs_persistence": "执行顺序与持久化状态互扰",
            "other": "意图记载有差异"}
ACTION_CN = {
    "self_cleanup": "让这个用例结束时清理自己留下的持久产物",
    "recompile_directed": "按已找到的方向重新编写",
    "rerun_isolated": "不改卷面,单独复跑对照确认",
    "vary_form": "换一种配置形态实现同一意图(坐实/排除产品缺陷)",
}

_TS_PREFIX = re.compile(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2} +[\d.]+ +- +")


def clean_device_echo(text: str, limit: int = 0) -> str:
    """设备回显给人看的清理(仅展示层;喂 LLM 的原文一字不动——V6 契约原样继承)。"""
    lines, blank = [], False
    for ln in str(text or "").splitlines():
        ln = _TS_PREFIX.sub("", ln).rstrip()
        if not ln:
            if blank:
                continue
            blank = True
        else:
            blank = False
        lines.append(ln)
    out = "\n".join(lines).strip()
    return out[:limit] if limit > 0 else out


def _ellip(s: str, n: int) -> str:
    """D+1 族性清扫:用户可见辅助文本定长截断**带明示省略「…」**(截断永远留痕,不无痕硬截;
    决策依据类不走此函数=不截,走此的是方向/证据摘要等辅助引用)。"""
    s = str(s or "")
    return s if len(s) <= n else s[:n].rstrip() + "…"


_REVISION_HDR = re.compile(r"^#+\s*Revision\b.*$", re.MULTILINE)
_RULING_HDR = re.compile(r"^#+\s*裁决\s*$", re.MULTILINE)


def _ruling_summary(ruling: str, limit: int = 120) -> str:
    """裁决要点摘要(D14):判例 ruling 是「`# 裁决` 头 + 若干 `## Revision @时间戳` 累积段」的
    markdown 文本(存储侧 [:500] 截断)。取**最新一段**操作性内容做要点,去 md 头/Revision 时间戳/
    换行折叠/半句尾——旧 `str(ruling)[:160]` 直出把整块含 `## Revision @2026-...` 时间戳的原文
    喂用户看(668000 去向行实证:一行糊满 md 头+时间戳+半截句子)。取最新段=沿用的是当前操作裁决。"""
    s = str(ruling or "").strip()
    if not s:
        return ""
    body = ""
    for seg in reversed(_REVISION_HDR.split(s)):   # 末段=最近 Revision 的操作性内容
        seg = _RULING_HDR.sub("", seg)
        # MULTILINE:剥**每一行**行首 md 头,含段内 `## 双方记载` 类头(redline 边角:无 MULTILINE
        # 只剥段首一个头、段内头会以带 ## 的纯文字入摘要)
        seg = re.sub(r"^#+\s*", "", seg.strip(), flags=re.MULTILINE).strip()
        if seg:
            body = seg
            break
    body = re.sub(r"\s+", " ", body or _RULING_HDR.sub("", s)).strip()   # 折叠换行/多空格
    return (body[:limit].rstrip() + "…") if len(body) > limit else body


# ── 时间线:事实 → 人话(机械翻译,零判断) ─────────────────────────────────────


def case_timeline(mine: list[dict]) -> list[str]:
    out: list[str] = []
    for f in mine:
        ev = f.get("ev")
        if ev == "authored":
            r = int(f.get("round") or 0)
            out.append(f"第 {r} 次编写完成" + ("(重新编写)" if r > 1 else ""))
        elif ev == "verdict":
            ctx = CTX_CN.get(str(f.get("ctx")), str(f.get("ctx")))
            res = str(f.get("result"))
            word = {"pass": "通过", "fail": "未通过"}.get(res, "未跑成(结论无效)")
            out.append(f"{ctx}:{word}")
        elif ev == "rollback":
            out.append("此前的通过结论被复验推翻,已从先例知识库撤销")
        elif ev == "ask_panel":
            out.append("发现意图记载差异,向你呈报")
        elif ev == "adopted":
            out.append("同一问题你此前已有裁决,直接沿用(免问)")
        elif ev == "decision" and f.get("answer"):
            # D15(provenance 分流):adopt 免问派生的 decision 事实(provenance=adopted:*)不是本批
            # 亲答——同案已有 adopted 事实走上面「直接沿用(免问)」行,此处跳过防「你的裁决:X」
            # 误示为本批亲裁(668000 时间线实证:免问案连出两行、后一行读着像用户答过)。
            if str(f.get("provenance") or "").startswith("adopted:"):
                continue
            out.append(f"你的裁决:{f.get('answer')}")
        elif ev == "suspended":
            # F-Py-5①:decision 类未作答挂起显「未作答」;bed 床治理/resume 恢复/欠定/改描述→「挂起」
            out.append("未作答,留待下批再问"
                       if _is_no_answer_reason(str(f.get("reason") or ""))
                       else "挂起,留待下批继续")
        elif ev == "resumed":
            out.append("恢复处理")
        elif ev == "delivery_blocked":
            out.append("验证通过,但卷面缺案尾清理(会污染后续用例),暂不交付")
    return out


def _latest_attribution(mine: list[dict]) -> dict:
    atts = [f for f in mine if f.get("ev") == "attribution"]
    return atts[-1] if atts else {}


def _latest_semantic_attribution(mine: list[dict]) -> dict:
    """最后一条**语义**归因(N1a 本体分离):跳过 user_stop 生命周期记账行
    (契约形态 disposition=="user_stop";过渡形态 user_stop 布尔字段双兼容)——
    517027 型案的「怎么判断的」显示站立的缺陷主张,而非记账行的假语义。
    旧事实(env_blocked 无标记)行为不变(向后兼容,在途批照旧渲染)。"""
    atts = [f for f in mine if f.get("ev") == "attribution"
            and str(f.get("disposition")) != "user_stop" and not f.get("user_stop")]
    return atts[-1] if atts else {}


def _latest_panel_dict(mine: list[dict], read_json) -> dict:
    """最新 ask_panel 事实 → 盘上面板全文(closing 清理会挪目录,读不到给空)。"""
    pf = [f for f in mine if f.get("ev") == "ask_panel"]
    if not pf:
        return {}
    return read_json(str(pf[-1].get("ref") or "")) or {}


def diagnosis_text(mine: list[dict], panel: dict | None = None) -> str:
    """怎么判断的:批级诊断(s₀ 配对,片3)优先——它有单案归因没有的批级视野;
    次之 panel 的 hypothesis(归因孔判断时刻写下的中文);再次归因词表+关键证据
    引文;皆无=如实说明未完成分析。取**语义**归因(跳过 user_stop 记账行)。"""
    att = _latest_semantic_attribution(mine)
    parts = []
    diags = [f for f in mine if f.get("ev") == "diagnosis"]
    diag = diags[-1] if diags else {}
    if str(diag.get("h_position", "")).startswith("h_s0"):
        pol = [str(p.get("aid", ""))[-6:] for p in (diag.get("polluters") or [])][:3]
        parts.append("判断:测试床状态残留污染(批级诊断)——"
                     + (f"卷内前驱案(尾号 {'、'.join(pol)})的持久/底层配置写跨案存活,"
                        if pol else "本案自身的持久化产物跨轮存活,")
                     + "该类污染复跑洗不掉(复跑只能救采集噪声),须床态治理/排卷尾。")
    hyp = str((panel or {}).get("hypothesis") or "").strip()
    shape = str((panel or {}).get("conflict_shape") or "")
    if hyp and not parts:
        parts.append((f"{SHAPE_CN.get(shape, SHAPE_CN['other'])}:" if shape else "") + hyp)
    elif att and not parts:
        cn = LAYER_CN.get(str(att.get("layer") or ""), "")
        if cn:
            parts.append(f"判断:{cn}。")
    if not att and not hyp and not parts:
        return "本轮收口前未能完成原因分析(证据在案,可续跑补齐)。"
    if att.get("evidence") and str(att.get("evidence")) != "user":
        parts.append(f"关键证据:「{clean_device_echo(str(att.get('evidence')), 200)}」。")
    return " ".join(parts) or "(证据在案,见事实台账)"


def _escalated_remedy_text(mine: list[dict]) -> str:
    """escalated 案去向(§2.2:对称 suspended 的现有格式,无通道案不许承诺可续跑)。

    只在案**仍处于**升级中时被调用(remedy_text 已用 _is_escalated 判过)——engineering_fault
    /封顶后的 defect_candidate 都带 de_escalated 解除,不会走到这里,由 remedy_text 上层
    按 disposition 分支处理,措辞与本函数分开维护(那两支是终局陈述,这支是待答/保持陈述)。
    """
    from main.ist_core.compile_engine_v8 import facts as _F
    aid = str(mine[0].get("aid")) if mine else ""
    sub = _F.escalated_subclass(mine, aid)
    cause = _ESC_SUBCLASS_CN.get(sub, "引擎侧遇到无法自行推进的情况")
    deesc_decs = [f for f in mine if f.get("ev") == "decision"
                 and str(f.get("question_id", "")).startswith(f"deesc:{aid}:")
                 # H-19:未答自动挂起落 decision{answer:"",token:suspend}——不得渲染成
                 # 「已按你的裁决「」处理」(非交互批全部 escalated 必走此谎报路径)。
                 and str(f.get("answer") or "").strip()
                 and str(f.get("token") or "") != "suspend"]
    if not deesc_decs:
        opts = ("重编/工程故障呈报/保持" if sub == "no_ledger_channel"
               else f"{_ESC_ROUTE_CN.get(sub, '重编')}/缺陷候选/保持")
        return (f"**去向**:{cause};引擎已呈报恢复问询(可选「{opts}」),"
                f"答复后重跑同参数会按你的选择继续;未答复则重跑同参数会再次呈报。")
    last = deesc_decs[-1]
    if str(last.get("token")) == "deesc_keep":
        n = _F.recovery_attempts(mine, aid)
        tried = f"(此前已尝试恢复 {n} 次)" if n else ""
        return (f"**去向**:{cause}{tried};你选择保持,本用例暂不再自动重试。"
                f"重跑同参数会沿用这次的保持,除非换了测试床或产品版本——那种情况下"
                f"会再次问你是否恢复。")
    return f"**去向**:{cause};已按你的裁决「{str(last.get('answer', ''))[:24]}」处理,详见时间线。"


def remedy_text(queue: list[dict], mine: list[dict], panel: dict | None = None) -> str:
    """去向段(判定式):有裁决说裁决、有采信说采信、在问询/挂起流程说等待——
    陈述句不设选项。queue 是 D 片修法队列的接缝(有则队列头=唯一导出修法)。"""
    if queue:
        head = queue[0]
        act = ACTION_CN.get(str(head.get("action")), str(head.get("action")))
        line = f"**修复方案**:{act}"
        if head.get("direction"):
            line += f"。方向:{_ellip(head['direction'], 160)}"   # 辅助:超长明示省略
        rest = [ACTION_CN.get(str(q.get("action")), "") for q in queue[1:]]
        if any(rest):
            line += f"。若仍未通过,后续依次:{'、'.join(r for r in rest if r)}"
        return line + "。"
    # escalated(§2.2 报告去向行,B-1 de-escalate 通道)优先于下面按 disposition 判的
    # 分支——escalated 案未必带 attribution(no_output 案从没跑到归因步),必须先按
    # 事实存在性(_is_escalated)判,不能等 disp 落空才兜底,否则会误落到函数末尾的
    # 通用「仍在引擎流程中」而不说明真实卡点/通道(无通道案不许承诺可续跑,§2.2)。
    from main.ist_core.compile_engine_v8.views import _is_escalated
    if _is_escalated(mine):
        return _escalated_remedy_text(mine)
    # 事实流机械判定(优先级:终局裁决 > 采信 > 待答呈报 > 挂起 > 授权等待 > 兜底)
    att = _latest_attribution(mine)
    disp = str(att.get("disposition") or "")
    decs = [f for f in mine if f.get("ev") == "decision" and f.get("answer")]
    if disp == "defect_candidate" and str(att.get("evidence", "")).startswith("engine_auto_cap"):
        # round-cap 封顶的真终态(§2.2 精确措辞:"已尽轮次,记缺陷候选"——与用户主动
        # 确认/疑似产品缺陷两种"缺陷候选"来路不同,不能共用下面两支笼统文案)
        return ("**结论**:引擎已尽轮次(多次重试仍未能推进、未产生新证据),记为缺陷候选"
                "(`defect_candidates.md`);如需继续,可在批注中说明后人工重新提交。")
    if disp == "engineering_fault":
        return ("**结论**:引擎侧遇到结构性缺口(非产品缺陷),已呈报记录、不计入缺陷候选单;"
                "该缺口需要工程侧后续处理,当前用例结果按未通过卷收尾。")
    if disp == "defect_candidate" and str(att.get("evidence")) == "user":
        return ("**结论**:你已确认为产品缺陷,已记入缺陷候选单"
                "(`defect_candidates.md`),该用例以缺陷结案。")
    if disp == "defect_candidate":
        return ("**结论**:疑似产品缺陷,已列入缺陷候选单(`defect_candidates.md`);"
                "坐实需换一种配置形态复现。")
    if (disp in ("env_blocked", "user_stop")) and int(att.get("round") or 0) == 99:
        # D15(provenance 分流):最后一条 decision 若为 adopt 免问派生(provenance=adopted:*),
        # 措辞不能说「你的裁决」(用户本批没被问)——改「此前批判例」如实归因。
        _ld = decs[-1] if decs else None
        if _ld and str(_ld.get("provenance") or "").startswith("adopted:"):
            who = f"(依据此前批的同键判例「{_ld.get('answer')}」)"
        else:
            who = f"(依据你的裁决「{_ld.get('answer')}」)" if _ld else ""
        # N1a:user_stop=用户止损记账(非 env 题面的停止/降级),不是环境结论——
        # 措辞不说"环境";历史达过缺陷候选的,指到缺陷候选单(N1 floor 报告面)。
        # env_blocked@99=env 题面停止(用户确认环境)或在途批旧事实,旧文案保持。
        if disp == "user_stop" or att.get("user_stop"):
            had_dc = any(f.get("ev") == "attribution"
                         and str(f.get("disposition")) == "defect_candidate"
                         for f in mine)
            tail = ("此前轮次曾达缺陷候选,其主张与证据已汇总在缺陷候选单"
                    "(`defect_candidates.md`)。" if had_dc else "")
            return (f"**结论**:按你的止损裁决收尾{who},该用例记入未通过卷,"
                    f"下批可继续。{tail}")
        return f"**结论**:按环境/取舍收尾{who},该用例记入未通过卷,下批可继续。"
    adopted = [f for f in mine if f.get("ev") == "adopted"]
    if adopted:
        _rs = _ruling_summary(adopted[-1].get("ruling") or "")   # D14:去 md 头/时间戳/半句
        return ("**去向**:同一差异你此前已有裁决,本批直接沿用并按其重编"
                + (f"(裁决要点:{_rs})。" if _rs else "。"))
    pf = [f for f in mine if f.get("ev") == "ask_panel"]
    if pf:
        prnd = int(pf[-1].get("round") or 0)
        aid = str(pf[-1].get("aid") or "")
        answered = any(d.get("ev") == "decision"
                       and str(d.get("question_id")) == f"panel:{aid}:{prnd}"
                       for d in mine)
        ask = str((panel or {}).get("ask") or "").strip()
        if not answered:
            return ("**去向**:已向你呈报差异待确认" + (f"(问题:{ask})" if ask else "")
                    + ",答复后按你的裁决继续。")
    blocked = [f for f in mine if f.get("ev") == "delivery_blocked"]
    if blocked and not any(f.get("ev") == "authored" for f in mine[mine.index(blocked[-1]):]):
        return ("**去向**:功能验证已通过,只差案尾清理步(自己留下的网络层配置要在"
                "案内恢复);下批续跑会带此反馈重新编写,补上后即可交付。")
    from main.ist_core.compile_engine_v8.views import _is_suspended
    if _is_suspended(mine):
        # F-Py-5①:未作答挂起 vs 床治理/欠定挂起分流(会签初衷=让用户知道要答)
        if _no_answer_suspended(mine):
            return "**去向**:你未作答,本轮先挂起;重跑同参数会再次呈报请你裁决。"
        return "**去向**:已挂起;重跑同参数时会再次询问是否恢复。"
    caps = [f for f in mine if f.get("ev") == "cap_reached"]
    if caps and not decs:
        return "**去向**:重编轮次已用尽,等待你授权继续/挂起/停止。"
    return "**状态**:仍在引擎流程中(证据与过程全部在事实台账,可续跑)。"


# ── 报告生成 ─────────────────────────────────────────────────────────────────


def _is_no_answer_reason(reason: str) -> bool:
    """suspended reason 是否「decision 类未答挂起」——reason=`auto:{qid}`、qid 前缀=题面 kind
    (nodes ask_contradiction qids:panel/cap/env/bed/resume/contra)。★仅 decision 类
    (panel/cap/env/contra)未答=待用户答→「未作答」;**bed 未答=床治理待外部处理(§11.7 bed 语义
    独立、Design 硬约束)、resume=不恢复→保持挂起**,虽也走 :2336 auto: 但显「挂起」不是「未作答」。
    白名单(非 startswith("auto:") 笼统黑名单)贯彻 bed 独立到渲染、防新 kind 误判。"""
    if not str(reason).startswith("auto:"):
        return False
    kind = str(reason)[len("auto:"):].split(":")[0]   # auto:{kind}:{aid}:{n} → kind 前缀
    return kind in ("panel", "cap", "env", "contra")


def _no_answer_suspended(mine: list[dict]) -> bool:
    """当前挂起是否 decision 类「未作答挂起」(最新 suspended 事实判据)——用户面分流用
    (F-Py-5①·会签初衷走渲染层、不改状态机):未作答→显「未作答」、床治理/欠定/恢复→「挂起」。"""
    sus = [f for f in mine if f.get("ev") == "suspended"]
    return bool(sus) and _is_no_answer_reason(str(sus[-1].get("reason") or ""))


def _status_cn(status: str, mine: list[dict]) -> str:
    """状态人话(F-Py-5①):suspended 按 reason 分流——no-answer 挂起→「未作答」、其余→STATUS_CN
    (床治理/欠定/改描述挂起仍显「挂起」)。收口卡/详报同源,避免「收口卡说挂起、详报说未作答」自矛盾。"""
    if status == "suspended" and _no_answer_suspended(mine):
        return "未作答(下批会再次问你)"
    return STATUS_CN.get(status, status)


def _case_section(aid: str, c: dict, mine: list[dict], mcase: dict,
                  queue: list[dict], panel: dict | None) -> list[str]:
    title = str(mcase.get("title") or "")
    # F-Py-7(短号·A 配套):18 位 autoid 后缀标尾号——用户记忆里是短号(如 655233),18 位长号
    # 认不出是自己哪条用例(User 21:21 实证);18 位保留(框架 dev_run_batch canonical 匹配用),
    # 尾号仅供用户辨识。题面侧本已用尾号(questions.py),此处补齐交付物侧(Design F-Py-7 A 配套)。
    out = [f"## {title or ('用例 …' + aid[-6:])}",
           f"- 编号 `{aid}`(尾号 {aid[-6:]}) · 状态:{_status_cn(str(c.get('status')), mine)}"
           f" · 编写 {c.get('rounds')} 次"]
    tl = case_timeline(mine)
    if tl:
        out.append("\n**发生了什么**:" + "→ ".join(tl) + "。")
    out.append("\n**怎么判断的**:" + diagnosis_text(mine, panel))
    out.append("\n" + remedy_text(queue, mine, panel))
    return out


def _batch_name(manifest: dict, report: dict | None = None) -> str:
    """交付物标题批名(F-Py-10:标题不露绝对本地路径/home/用户名/冗长目录)——取 source 文件名主干
    (=批名),回落 report.batch。/Users/jiangyongze/.../inputs/automatic_case/yzg.txt → yzg。
    纯字符串操作(去目录+去扩展名),不依赖 Path;空则回落 report.batch。"""
    src = str(manifest.get("source") or "").replace("\\", "/")
    base = src.rsplit("/", 1)[-1]                              # 去目录(剥 home/用户名/路径)
    stem = base.rsplit(".", 1)[0] if "." in base else base     # 去扩展名
    return stem or str((report or {}).get("batch") or "")


def render_delivery_report(report: dict, fs: list[dict], manifest: dict,
                           queues: dict[str, list[dict]],
                           panels: dict[str, dict] | None = None) -> str:
    """delivery_report.md 全文(判定式三段;数字与 engine_report 同源)。"""
    t = report.get("totals", {})
    ok = int(t.get("deliverable") or 0)
    total = int(t.get("cases") or 0)
    mcases = {str(c.get("autoid")): c for c in (manifest.get("cases") or [])}
    lines = [f"# 交付报告 — {_batch_name(manifest, report)}",
             f"> 生成 {time.strftime('%Y-%m-%d %H:%M', time.localtime())}",
             "",
             f"本批 {total} 个用例:**{ok} 个通过整卷复验,已入交付卷**"
             + (f";其余 {total - ok} 个的情况逐一说明如下。" if total > ok else "。"), ""]
    # 未跑成分母:broken 三子态(复跑/重写/env)同属「无结论」,统一不计通过率分母(§④)
    n_broken = (int(t.get("broken") or 0) + int(t.get("broken_errored") or 0)
                + int(t.get("broken_blocked") or 0))
    if n_broken:
        lines.append(f"- ⚠ 有 {n_broken} 个用例本轮**未跑成**(执行中断/日志陈腐/级联"
                     f"受害/断言被实机回显反证/设备不可达)——它们的结果是「无结论」而非"
                     f"「未通过」,不计入通过率分母叙事")
    # K 健康度行(§18.2 第6行式③):门数据面缺席=判定降级,用户必须看得见——诊断/τ/
    # bed 恢复的可信度取决于三数据面(grammar 门/inventory 签名/case 画像)是否齐备
    _gd = {}
    for f in fs:
        if f.get("ev") == "gate_disabled":
            _gd[str(f.get("gate"))] = str(f.get("reason") or "")
    if _gd:
        _cn = {"diagnose_s0": "批级污染诊断", "inverse_forms": "τ 覆盖门/机械恢复",
               "touch_profile": "触碰画像(s₀ 配对输入)"}
        items = "；".join(f"{_cn.get(g, g)}" for g in sorted(_gd))
        lines.append(f"- ⚠ **K 健康度**:{len(_gd)} 个判定门本轮因数据面缺席而降级({items})"
                     f"——相关诊断/覆盖判定的可信度下降,详见机读报告 gate_disabled 事实")
    moved = report.get("moved_tail") or []
    if moved:
        names = [str((mcases.get(a) or {}).get("title") or ("…" + a[-6:])) for a in moved]
        lines.append(f"- 有 {len(moved)} 个用例会在设备上留下跨用例存活的配置(保存/同步类),"
                     f"已按规则排到卷尾执行:{'、'.join(names)}")
    if report.get("coexist_violations"):
        lines.append("- ⚠ 本卷存在官方标注互斥的操作组合,已在组卷时检查并声明(详见机读报告)")
    # F-Py-8:极性照抄先例的审计标注(非拒卷、非 ⚠ 警告——交付=已上机验方向;仅供复核抽查来源)
    _prec = report.get("precedent_polarity_flags") or []
    if _prec:
        _pn = sum(int(p.get("count") or 0) for p in _prec)
        _pnames = [str((mcases.get(p.get("autoid")) or {}).get("title")
                       or ("…" + str(p.get("autoid"))[-6:])) for p in _prec]
        lines.append(f"- {len(_prec)} 个交付用例的 {_pn} 条断言极性照抄先例语法"
                     f"(已上机验方向,仅作来源标注供复核抽查):{'、'.join(_pnames)}")
    bad = {a: c for a, c in (report.get("cases") or {}).items()
           if c.get("status") != "deliverable"}
    if bad:
        lines.append("")
        for aid, c in sorted(bad.items()):
            mine = [f for f in fs if str(f.get("aid")) == aid]
            lines += _case_section(aid, c, mine, mcases.get(aid) or {},
                                   queues.get(aid) or [], (panels or {}).get(aid))
            lines.append("")
    _dc = report.get("defect_candidates") or {}
    lines.append("---")
    lines.append("交付物:`case.xlsx`(通过卷)"
                 + ("、`unsuccessful_cases.xlsx`+`unsuccessful_cases.md`(未通过卷与详报)" if bad else "")
                 + (f"、`defect_candidates.md`(缺陷候选单,{int(_dc.get('count') or 0)} 案,"
                    f"含结构化表单与处置轨迹)" if _dc else "")
                 + "、`engine_report.json`(机读)。全部过程事实在 `facts.jsonl`,可审计可续跑。")
    return "\n".join(lines) + "\n"


def render_defect_candidates_md(entries: list[dict], manifest: dict) -> str:
    """缺陷候选单人话渲染(P0 C20;判定式,同 fold 投影,渲染零 LLM)。

    每案:结构化表单(repro/expected_with_source/actual/version/ticket_id)+
    claim 全史(517027 型多主张并列,不只最新)+ 处置轨迹(如实展示后轮改判)。
    候选≠终判(§11.7 缺陷确认权在人)——轨迹与确认状态如实标注。
    设备证据放 code fence(leak_scan 豁免面;正文守零术语泄漏)。"""
    lines = [f"# 缺陷候选单 — {_batch_name(manifest)}",
             f"> 生成 {time.strftime('%Y-%m-%d %H:%M', time.localtime())} · "
             f"共 {len(entries)} 案 · 候选非终判,确认权在人",
             ""]
    for e in entries:
        _dc_aid = str(e.get("autoid") or "")
        lines.append(f"## {e.get('title') or ('用例 …' + _dc_aid[-6:])}")
        lines.append(f"- 编号 `{_dc_aid}`(尾号 {_dc_aid[-6:]}) · 当前状态:"   # 全号+尾号(与主报告一致)
                     f"{STATUS_CN.get(str(e.get('status')), e.get('status'))}"
                     + (" · **你已确认为产品缺陷**" if e.get("user_confirmed")
                        else " · 待人工确认"))
        claims = e.get("claims") or []
        if claims:
            lines.append("\n**缺陷主张**(全史,后轮改判不隐去先前主张):")
            for cl in claims:
                lines.append(f"- 第 {cl.get('round')} 轮:{cl.get('claim') or '(见证据)'}")
                if cl.get("evidence"):
                    lines.append("  ```\n  " + clean_device_echo(str(cl["evidence"]), 300)
                                 + "\n  ```")
        elif e.get("latest_claim"):
            lines.append(f"\n**缺陷主张**:{e['latest_claim']}")
        form = e.get("form") or {}
        if form:
            lines.append("\n**结构化表单**:")
            for key, label in (("repro", "复现步骤"), ("expected_with_source", "预期(含出处)"),
                               ("actual", "实际"), ("version", "版本"), ("ticket_id", "单号")):
                v = str(form.get(key) or "").strip()
                if v:
                    lines.append(f"- {label}:{v}")
        trail = e.get("disposition_trail") or []
        if trail:
            words = []
            for t in trail:
                w = DISP_CN.get(str(t.get("disposition")), str(t.get("disposition")))
                r = "用户裁决" if int(t.get("round") or 0) == 99 else f"第{t.get('round')}轮"
                words.append(f"{r} {w}" + ("(你的裁决)" if t.get("by_user") else ""))
            lines.append("\n**处置轨迹**:" + " → ".join(words))
        lines.append("")
    return "\n".join(lines) + "\n"


def render_unsuccessful_md(report: dict, fs: list[dict], manifest: dict,
                           queues: dict[str, list[dict]],
                           evidence: dict[str, str],
                           panels: dict[str, dict] | None = None) -> str:
    """未通过卷详报:每案三段式 + 脑图原文 + 关键设备回显(清理后)。"""
    mcases = {str(c.get("autoid")): c for c in (manifest.get("cases") or [])}
    bad = {a: c for a, c in (report.get("cases") or {}).items()
           if c.get("status") != "deliverable"}
    lines = [f"# 未通过用例详报 — {_batch_name(manifest)}",
             f"> 生成 {time.strftime('%Y-%m-%d %H:%M', time.localtime())} · 共 {len(bad)} 个",
             ""]
    for aid, c in sorted(bad.items()):
        mine = [f for f in fs if str(f.get("aid")) == aid]
        mc = mcases.get(aid) or {}
        lines += _case_section(aid, c, mine, mc, queues.get(aid) or [],
                               (panels or {}).get(aid))
        sis = mc.get("step_intents") or []
        if sis:
            lines.append("\n**脑图原始用例**:")
            for si in sis:
                d, e = str(si.get("desc") or ""), str(si.get("expected") or "")
                lines.append(f"- {d}" + (f" → 预期:{e}" if e else ""))
        ev = evidence.get(aid) or ""
        if ev:
            lines.append("\n**最后一次设备关键回显**(已剥时间戳,原文在事实台账):")
            lines.append("```\n" + clean_device_echo(ev, 1500) + "\n```")
        lines.append("")
    return "\n".join(lines) + "\n"


# ── 报告机械门:零术语泄漏(测试与 closing 断言共用) ───────────────────────────

def _leak_pattern() -> "re.Pattern":
    """denylist 从枚举源机械生成(§18.6 坑#23:硬编码 20 词表随枚举新增静默漂移——
    新状态/处置/形态词自动入表,零人工记账)。豁免 pending/failed(常见英文单词,
    误伤面大于泄漏面;它们的中文词条由 STATUS_CN 结构门保证)。"""
    from main.ist_core.compile_engine_v8 import views as _V
    words = {getattr(_V, n) for n in dir(_V) if n.startswith("S_")}
    words |= set(STATUS_CN) | set(DISP_CN) | set(SHAPE_CN) | set(ACTION_CN) | set(CTX_CN)
    words |= {"ask_panel", "adopted", "not_run", "gate_disabled",
              "writeback_failed", "rollback_failed", "emit_invalid",
              "report_mismatch", "delivery_incomplete"}
    words -= {"pending", "failed", "other"}
    pat = "|".join(sorted((re.escape(w) for w in words if w), key=len, reverse=True))
    # F-Py-3(token 类级兜底,Design P·双层 net):denylist(已知枚举,上)之外再兜 **token-shape** 内部
    # 标识——兜任何残留内部 marker/token,不只已登记枚举(LLM-Eng 源头清具体中文黑话词/我兜 ASCII
    # token 类,正交)。三类 shape,均带下划线结构锚(非无特征强字典,故低假阳):
    #   ① UPPER_SNAKE 带下划线(NEEDS_USER_DECISION/S_FAILED)——要求下划线→排除缩略语(DNS/HTTP/IP 无下划线不匹配);
    #   ② leading-underscore(_attribution/_round/_fail_signatures)——首字符下划线的内部字段名;
    #   ③ internal-underscore snake(needs_decision/ask_panel/last_run)——**文件名引用豁免**:后接
    #      已知交付物扩展名集(.md/.json/...)时不算泄漏(delivery_report.md 是合法引用、bare
    #      delivery_report 仍抓;扩展名集限定=不放行 needs_decision.internalfoo 类钻空子,Design 精化)。
    # 中文人话(状态/语境词、6 黑话词、3 label token 改过程/改预期/改描述)是非-ASCII、天然不匹配 shape。
    # 文件名.ext / 路径段引用豁免:snake 后接已知交付物扩展名(delivery_report.md)或 `/`(路径段
    # automatic_case/)、或前接 `/`——都是文件/路径**引用**非 bare token 泄漏。扩展名限定已知集
    # (Design 精化:不放行任意 .xxx,needs_decision.internalfoo 仍抓)。
    _EXT = r"(?!\.(?:md|json|jsonl|xlsx|xls|txt|log|csv|py|xml|yaml|yml)\b|/)"
    _tok = (r"[A-Z][A-Z0-9]*_[A-Z0-9_]+"                 # ① UPPER_SNAKE 带下划线
            r"|_[a-z][a-z0-9_]*"                          # ② leading-underscore
            r"|(?<!/)[a-z][a-z0-9]*_[a-z0-9_]+" + _EXT)   # ③ internal-underscore(文件名/路径段豁免)
    return re.compile(r"\b(" + pat + r")\b|\b[0-9a-f]{16}\b|\b(?:" + _tok + r")\b")


_LEAK = _leak_pattern()


def leak_scan(text: str) -> list[str]:
    """返回用户面文本中泄漏的内部术语/指纹(应为空;code fence 内的设备回显豁免)。"""
    out, in_fence = [], False
    for ln in str(text or "").splitlines():
        if ln.strip().startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence or ln.strip().startswith("`") and ln.strip().endswith("`"):
            continue
        for m in _LEAK.finditer(re.sub(r"`[^`]*`", "", ln)):
            out.append(m.group(0))
    return out


# ── F-Py-8:断言极性照抄先例 flag(Design 定案·三层审计抽查:机械做来源/语义留上机 oracle) ─────────
# 机械只做**可靠的来源 flag**(provenance source.kind=precedent=照抄先例语法),**不判极性语义对错**
# (极性对不对本案意图=语义,机械判不了、硬门会误杀合法极性,该上机验的别离线硬推)。closing 据此
# 报告标注「N 案断言极性照抄先例、已上机验方向」(暴露非掩盖、非硬门不拒卷),上机 oracle 兜底极性
# 对错(也兜 worker 自标 intent 骗过 flag 的盲区——极性方向错→上机 fail)。
def precedent_sourced_assertions(provenance: dict) -> list:
    """扫 case.provenance.json 断言步,返回 source.kind=precedent(照抄先例语法)的断言——极性照抄
    风险**候选**(缩抽查面从全断言到 precedent-sourced 少量)。**只标来源、不判极性对错**(语义留上机)。
    返回 [{"step":i, "F":算子, "ref":先例 ref}, ...]。closing 报告标注用、非硬门。"""
    out = []
    for i, step in enumerate((provenance or {}).get("steps") or []):
        if not isinstance(step, dict):
            continue
        src = step.get("source") or {}
        f = str(step.get("F") or "")
        if str(src.get("kind")) == "precedent" and f in ("found", "not_found", "abs_found"):
            out.append({"step": i, "F": f, "ref": str(src.get("ref") or "")})
    return out
