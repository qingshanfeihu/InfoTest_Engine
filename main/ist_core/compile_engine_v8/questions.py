"""问题组织(两条问询通道的题面组装,纯函数、零 I/O 决策):

① 欠定通道(needs_decision.json 台账 → ask_decision 面板):台账是锚——问题文本由
   代码从台账拼装,autoid 全名、选项、ordering_sensitive 的「顺序语义保留/放弃」
   显式句都由代码保证(题面结构不变量的机械断言=validate_questions,测试消费)。
   每次 ask ≤4 题(ask_user 工具硬限),超出分批。

② 矛盾/止损通道(ask_contradiction interrupt → 面板):panel/cap/env/bed/contra/
   suspended 六类题面(`build_ask_question`)+ Other 自由输入意图归类(`answer_token`)。
   本文件是 ask 面板语义单一事实源;止损落账形态在 nodes.ask_contradiction
   (user_stop 事件分离,test_claim_stickiness 锁语义)。

题面纪律(用户验收四标准):自然语言可懂(零内部术语);不自相矛盾(claim 历史全呈现,
归因 churn 后不只显最后一轮);选项真实有效(文案从案情事实拼装,label→token 与引擎
动作一致);不提供虚假问题(超长素材走句读摘要带「…」留痕,不无痕硬截)。
"""

from __future__ import annotations

import json
import re
from pathlib import Path

# 决策选项(与 compile_user_decision 的 decision 枚举一致)
DECISIONS = ("改过程", "改预期", "改描述")

def _first_clause(s: str, cap: int = 150) -> str:
    """按中文标点截首句(§18.14 D2:替代裸 `[:N]` 词中断路——668059 曾被截在
    '已检索:knowledge/data/markdo';机读检索证明尾部本就不该进用户题面)。"""
    s = str(s or "").strip()
    for i, ch in enumerate(s):
        if ch in "。;；" and i >= 10:
            return s[:i]      # 不含末标点——外层 join 用「；」连,避免双标点
    return s if len(s) <= cap else s[:cap].rstrip() + "…"


def clip_text(s: str, cap: int = 160) -> str:
    """超长题面素材的句读摘要(P0-新② 题面硬化;zhaiyq 实弹:题面曾被裸 [:N] 词中
    断成「调整断言为not_found方)」且无省略标记,读者不知道被截)。整句累加到 cap,
    放不下的丢弃并以「…」留痕;首句即超长时退回定长截断但仍带「…」——截断永远可见。"""
    s = " ".join(str(s or "").split())
    if len(s) <= cap:
        return s
    out: list[str] = []
    used = 0
    for seg in re.split(r"(?<=[。;；!?！?])", s):
        if not seg:
            continue
        if used + len(seg) > cap:
            break
        out.append(seg)
        used += len(seg)
    kept = "".join(out).rstrip("。;；,,")
    if not kept:
        kept = s[:cap].rstrip()
    return kept + "…"


# claim_kind → 建议断言形态(机械映射;最终形态以用户答案落盘为准)。
# cross_client_landing(E10a,2026-07-16):键名与 verifiability 侧(丙队)冻结——
# 跨客户端落点类主张的可验等价首选同客户端关系断言(relation),次选分组分布区间。
FORM_BY_KIND = {
    "distribution": "dist", "weight_ratio": "dist",
    "new_member_last": "member", "absolute_position": "member", "rotation_order": "member",
    "new_member_participates": "member",
    "relation_same": "captured_relation", "relation_diff": "captured_relation",
    "cross_client_landing": "captured_relation",
}

# 「加请求/观测次数」这类采样建议只对计数/位次类主张成立(run22 病理:generic 采样
# 模板套在非采样类欠定上=误导选项);关系类/落点类不靠加样本解决,不入此集。
_SAMPLING_KINDS = frozenset({
    "distribution", "weight_ratio", "new_member_last", "absolute_position",
    "rotation_order", "new_member_participates"})


def load_ledgers(outputs_root: Path, autoids: list[str]) -> dict[str, dict]:
    """读各 case 的 needs_decision.json 台账原件(缺失的跳过,不猜)。"""
    out: dict[str, dict] = {}
    for aid in autoids:
        p = outputs_root / aid / "needs_decision.json"
        if p.is_file():
            try:
                out[aid] = json.loads(p.read_text(encoding="utf-8"))
            except Exception:  # noqa: BLE001
                continue
    return out


def build_questions(ledgers: dict[str, dict]) -> list[dict]:
    """台账 → ask_user questions(机械模板)。每 case 一题(≤4 题一批由调用方切)。"""
    questions = []
    for aid, nd in sorted(ledgers.items()):
        claims = [c for c in (nd.get("claims") or []) if isinstance(c, dict)]
        if not claims:
            continue
        ordering = any(c.get("ordering_sensitive") for c in claims)
        reasons = "；".join(_first_clause(c.get("reason", "")) for c in claims[:3])
        mins = [int(c.get("min_requests") or 0) for c in claims]
        min_req = max(mins) if any(m > 0 for m in mins) else 0
        kinds = [str(c.get("claim_kind", "")) for c in claims]
        form = next((FORM_BY_KIND[k] for k in kinds if k in FORM_BY_KIND), "dist")

        if all(k == "missing_teardown" for k in kinds):
            # G1 配对恢复呈报(V8.5 片5):写是被测行为本身 vs 该补恢复步
            c0 = claims[0]
            tau = "；".join(str(t) for t in (c0.get("suggested_tau") or [])[:3])
            q_text = (f"用例 {aid}(尾号 {aid[-6:]})的配置写会在测试床留下框架清理"
                      f"够不着的网络层残留(同类残留曾一批内六次弄坏共享床):{reasons}。")
            opt_process = {"label": "改过程",
                           "description": f"案尾追加恢复步(建议:{tau or '逆序 no 回放'}),断言之后执行——推荐。"}
            opt_expect = {"label": "改预期",
                          "description": "该写是被测行为本身、必须保留残留——按此意图重编(残留将由批末床态收敛处理,交付报告声明)。"}
            opt_desc = {"label": "改描述",
                        "description": "用例意图待人工厘清,本轮不产出(挂起)。"}
            questions.append({"question": q_text, "header": f"清理·{aid[-6:]}",
                              "options": [opt_process, opt_expect, opt_desc],
                              "multiSelect": False, "_autoid": aid,
                              "_ordering": False, "_form": form})
            continue

        if all(c.get("test_point") for c in claims):
            # §18.13 三元组投影(逐字渲染,零模板文案):面板=worker 报告本身。
            # 真实路径 claim_kind=verification_path_absent 但带三元组字段→走这里
            # (旧版掉进 generic「加请求/观测次数」模板=run22 病理)。
            c0 = claims[0]
            tp = str(c0.get("test_point") or "")
            obs = str(c0.get("obstacle") or "")
            equiv = c0.get("equivalent") or None
            proc = str((equiv or {}).get("procedure") or "") if equiv else ""
            preserves = str((equiv or {}).get("preserves") or "") if equiv else ""
            no_eq = str(c0.get("no_equivalent_reason") or "")
            q_text = (f"用例 {aid[-6:]} 要验证:{tp}。\n问题:{obs}。"
                      + (f"\n等价方法:{proc}" + (f"({preserves})" if preserves else "") + "。"
                         if proc else ""))
            opts, tok = [], {}
            if proc:
                lbl = f"采纳「{proc[:60]}」"
                opts.append({"label": lbl,
                             "description": "采纳此等价验证重编(引擎按它编写;差异声明随交付报告)。"})
                tok[lbl] = "改过程"
            lbl_other = "我给别的等价方案"
            opts.append({"label": lbl_other,
                         "description": "在自定义输入里给出你的等价方案,原文随裁决下发 worker。"})
            tok[lbl_other] = "改预期"
            lbl_susp = "挂起,如实报告"
            opts.append({"label": lbl_susp,
                         "description": f"{no_eq or obs}。本轮不产出,待可执行环境。"})
            tok[lbl_susp] = "改描述"
            questions.append({"question": q_text, "header": f"欠定·{aid[-6:]}",
                              "options": opts, "multiSelect": False, "_autoid": aid,
                              "_ordering": ordering, "_form": form,
                              "_token_by_label": tok})   # P3:label→token 显式映射
            continue

        if all(k == "forbidden_mechanism" for k in kinds):
            # F6 禁令机制呈报(§18.11 五稿):山穷水尽=有能力完成设计验证就实现——
            # 题面主推 worker 按配置面模型推导的等价实现(模型条件,差异已声明),
            # 投降选项必须携穷举论证语义;误报(字面命中非机制)一答放行。
            c0 = claims[0]
            prop = str(c0.get("proposed_equivalent") or c0.get("suggested_fix") or "")[:200]
            q_text = (f"用例 {aid}(尾号 {aid[-6:]})的意图要求测试床禁止的机制:{reasons}。"
                      + (f"worker 按配置面模型推导的等价实现:{prop}。" if prop else "")
                      + "等价性为模型条件(启动通道等差异已在报告声明),如何处置?")
            opt_process = {"label": "改过程",
                           "description": ("采纳等价实现重编(推荐;差异声明随交付报告)。"
                                           "若命中词并非本案执行机制(如计数/字段名),同选此项"
                                           "并注明,照常编写。")}
            opt_expect = {"label": "改预期",
                          "description": "等价实现方向不对——在自定义输入里给出你的等价方案,原文将随裁决下发 worker。"}
            opt_desc = {"label": "改描述",
                        "description": "确认无有效替代/必须真机制——本轮不产出,挂起待可执行环境(如实报告)。"}
            questions.append({"question": q_text, "header": f"禁令·{aid[-6:]}",
                              "options": [opt_process, opt_expect, opt_desc],
                              "multiSelect": False, "_autoid": aid,
                              "_ordering": False, "_form": form})
            continue

        if all(k == "command_existence" for k in kinds):
            # S6 存在性呈报(§18.14 S3:题面人话对象——用干净 cmds,机读检索证明
            # (签名数/覆盖率/检索路径)留台账 _evidence 不进用户面)。
            cmds = "、".join(f"『{c.get('command', '')}』" for c in claims[:3])
            q_text = (f"用例 {aid[-6:]} 用到的命令 {cmds} 在被测版本的 CLI 手册里"
                      f"查不到(可能这版没有此功能,或命令改了名)。")
            opt_process = {"label": "改过程",
                           "description": f"换用版本内存在的等价命令/形态重写 {cmds}(引擎继续编写)。"}
            opt_expect = {"label": "改预期",
                          "description": "保留过程,改用版本内可观测的替代验证形态。"}
            opt_desc = {"label": "改描述",
                        "description": ("确认该功能不属本版本/记载互斥(fulldns 先例)——"
                                        "本轮不产出,挂起待适用版本;文档不一致如实写报告。")}
            questions.append({"question": q_text, "header": f"存在性·{aid[-6:]}",
                              "options": [opt_process, opt_expect, opt_desc],
                              "multiSelect": False, "_autoid": aid,
                              "_ordering": False, "_form": form})
            continue

        if all(k == "cross_client_landing" for k in kinds):
            # E10a(2026-07-16 团队裁决):跨客户端落点类主张(「特定客户端固定命中
            # 特定成员/池」)——落点由设备调度实现决定,轮转/加权的数学推不出该映射;
            # 手册/判例证实前欠定。专用题面防掉通用采样模板(design-challenger §二 E1:
            # 掉 generic=对非采样类主张给「加请求/观测次数」误导选项,run22 同型)。
            q_text = (f"用例 {aid}(尾号 {aid[-6:]})主张特定客户端固定命中特定成员/池:"
                      f"{reasons}。该落点由设备调度实现决定,轮转/加权算法推不出"
                      "「某客户端必中某成员」;在手册/判例证实前按原样验证不了。你希望怎么改?")
            opt_process = {"label": "改过程",
                           "description": ("改为可验形态:同一客户端内多次请求做关系断言"
                                           "(两次应答相同/不同),或按客户端分组做分布区间;"
                                           f"请求次数同步加到可验水平。断言形态按 {form}。")}
            opt_expect = {"label": "改预期",
                          "description": ("你确认存在确定性映射(如按地址族过滤/固定绑定)"
                                          "——在自定义输入里给出手册/判例依据,保留原预期"
                                          "按该映射重编。")}
            opt_desc = {"label": "改描述",
                        "description": "用例意图待人工厘清,本轮不产出(挂起)。"}
            questions.append({"question": q_text, "header": f"落点·{aid[-6:]}",
                              "options": [opt_process, opt_expect, opt_desc],
                              "multiSelect": False, "_autoid": aid,
                              "_ordering": ordering, "_form": form})
            continue

        # —— 通用兜底(2026-07-16 重组,防混合/非采样类掉采样模板——design-challenger
        # §二 E1:旧版对任何非特判台账一律给「加请求/观测次数」,对 missing_teardown+
        # distribution 混合案或非采样类欠定=误导选项):改过程的文案从各 claim 自带
        # 事实拼装;「加请求/观测次数」只在确有采样类主张时出现。纯采样类文案与旧版等同。
        sampling = [c for c in claims
                    if int(c.get("min_requests") or 0) > 0
                    or str(c.get("claim_kind")) in _SAMPLING_KINDS]
        q_text = (f"用例 {aid}(尾号 {aid[-6:]})按原始写法验证不出目标行为:{reasons}。"
                  + (f"最小可验请求数 {min_req} 次。" if min_req else "")
                  + "你希望怎么改?")
        proc_parts: list[str] = []
        if sampling:
            proc_parts.append("加请求/观测次数到可验水平"
                              + (f"(≥{min_req} 次)" if min_req else ""))
        for c in claims:
            k = str(c.get("claim_kind") or "")
            if k in _SAMPLING_KINDS:
                continue
            if c.get("suggested_tau"):
                proc_parts.append("案尾补恢复步(建议:"
                                  + "；".join(str(t) for t in c["suggested_tau"][:3]) + ")")
            elif c.get("proposed_equivalent"):
                proc_parts.append(f"采纳等价实现:{_first_clause(str(c['proposed_equivalent']), 80)}")
            elif c.get("command"):
                proc_parts.append(f"换用版本内存在的等价命令重写『{c['command']}』")
        if not proc_parts:
            proc_parts.append("按上述障碍逐条修改测试过程,使每条主张可验")
        opt_process = {
            "label": "改过程",
            "description": ("；".join(dict.fromkeys(proc_parts))
                            + (";顺序语义**保留**(产物须能证明顺序)" if ordering else "")
                            + f"。断言形态按 {form}。")}
        opt_expect = {
            "label": "改预期",
            "description": ("把不可证伪的绝对预期改成可验形态(关系/归属)"
                            + (";⚠ 顺序语义将**放弃**——选这项即显式批准放弃「按序命中」的覆盖"
                               if ordering else "") + "。")}
        opt_desc = {"label": "改描述", "description": "用例描述本身有歧义/与设备行为矛盾,待人工厘清(本轮不产出)。"}
        questions.append({
            "question": q_text,
            "header": f"欠定·{aid[-6:]}",
            "options": [opt_process, opt_expect, opt_desc],
            "multiSelect": False,
            "_autoid": aid,           # 内部路由用(发给 ask_user 前剥离)
            "_ordering": ordering,
            "_form": form,
        })
    return questions


def validate_questions(questions: list[dict], ledgers: dict[str, dict]) -> bool:
    """题面结构不变量的机械断言(测试消费;生产路径纯模板拼装,不在运行时过此门):
    每题含对应 autoid;ordering_sensitive 的题面必须显式出现「顺序语义」;选项 label
    可映射到决策 token——固定枚举题 label ⊆ DECISIONS;三元组等自由 label 题
    (§18.13 逐字投影,label 内嵌 procedure 原文)以 `_token_by_label` 映射表为准
    (label 全在表内 ∧ token 值 ⊆ DECISIONS),不按字面枚举误杀。"""
    if len(questions) != len(ledgers):
        return False
    for q in questions:
        aid = q.get("_autoid", "")
        if aid not in ledgers:
            return False
        text = str(q.get("question", ""))
        if aid not in text and aid[-6:] not in text:
            return False
        if q.get("_ordering") and "顺序语义" not in text + json.dumps(
                q.get("options", []), ensure_ascii=False):
            return False
        labels = [o.get("label") for o in q.get("options", [])]
        tok_map = q.get("_token_by_label") or {}
        if tok_map:
            if not (set(labels) <= set(tok_map)
                    and set(tok_map.values()) <= set(DECISIONS)):
                return False
        elif not set(labels) <= set(DECISIONS):
            return False
    return True


# ══════════════════════ 第二问询族(ask_contradiction 面板)═══════════════════
# 本文件是 ask 面板语义的单一事实源:engine_tool._contradiction_question 委托
# build_ask_question;nodes._answer_token 别名 answer_token。止损落账形态在
# nodes.ask_contradiction(user_stop 事件分离,test_claim_stickiness 锁语义)。

# 题面与 briefs 重编注入必须同一事实面:引文窗口同宽(超窗只加「…」留痕,不改窗口)
_QUOTE_CLIP = 300

# 展示路径控制字符(TAB/回车/其余 C0 与 DEL;\n 由各拼装点自管)——sides quote 携
# 真实 TAB 直通题干曾撕裂 TUI 面板行(渲染侧 dom.py 已同修,此为双侧防御)
_CTRL_RE = re.compile(r"[\t\x00-\x08\x0b-\x1f\x7f]")


def _display_clean(s: str) -> str:
    """题面**展示路径**的控制字符规格化(\\t→空格、\\r 及其余控制符剥除)。
    只用于用户题面拼装——落盘 jsonl 与 LLM 载荷保持 verbatim 契约,一字不动。"""
    return _CTRL_RE.sub(" ", str(s or "").replace("\r", ""))

_SHAPE_CN = {"manual_vs_device": "手册与实机不符",
             "expected_vs_observed": "预期结果与上机行为不符",
             "method_vs_implementation": "验证方法与功能实现不符",
             "ordering_vs_persistence": "执行顺序与持久化状态互扰",
             "other": "意图记载有差异"}
_RECEIPT_CN = {"miss": "知识库未命中", "hit_conflicting": "命中但记载互斥",
               "hit_adopted_blocked": "命中但与实机矛盾未采用"}

# 归因处置 → 用户面人话(claim 历史渲染用;值全中文,内部键名不进题面)
_DISP_CN = {"defect_candidate": "疑似产品缺陷", "expectation_suspect": "预期存疑",
            "reflow": "判用例侧可修", "rerun_isolated": "判隔离复跑",
            "transient": "疑似瞬态", "env_blocked": "判环境阻塞",
            "frozen": "同法两轮未过", "user_stop": "你已裁决停止"}

# 止损落账形态在 nodes.ask_contradiction(独立 user_stop 事实+r99 记账行,键名冻结,
# test_claim_stickiness 锁语义);本文件只管题面——「停止该案」选项文案「记为你的
# 停止裁决,不覆盖在案技术判断」与 render 跳记账行的行为成对。

_NEG_DEFECT_RE = re.compile(
    r"(不是|不算|并非|算不上|没有|不认为是?|别提|不要提|先不提|非)\s*(产品)?\s*(缺陷|产品问题|bug)",
    re.IGNORECASE)


# 条件/时序标记(中文语法结构词,非领域词):出现在缺陷词**之前的同一子句内**=
# 该缺陷词挂在前置条件下,不是当场确认
_COND_MARKERS = ("若", "如果", "假如", "要是", "一旦", "除非", "才", "先", "等", "再", "则")


def _defect_intent(a: str) -> bool:
    """自由输入的**无条件**缺陷意图(两道门)。

    否定门(517027 实弹):「不是缺陷,继续修」不算——用户在 cap 面板写「是缺陷」
    曾被恒归并成 continue(最恶性误译)。
    条件句门(2026-07-17 实弹):「直查仍不返回**才**按缺陷候选结案」是带前置条件的
    处置指令,非当场确认缺陷——短路成 defect 会把用户的条件裁决简化执行(先做 X、
    若仍失败才 Y 变成了直接 Y)。判据是**句法位置关系**(含缺陷词的子句内、缺陷词
    之前出现条件/时序标记)而非意图词表——条件句掉 correct 兜底,原文完整落账下发,
    条件语义由消费侧(worker/引擎按用户原文)保持。"""
    s = _NEG_DEFECT_RE.sub("", str(a or ""))
    low = s.lower()
    hit = next((w for w in ("缺陷", "产品问题", "提单", "bug") if w in low), None)
    if not hit:
        return False
    # 取缺陷词所在子句(句读切分),看词前是否有条件/时序标记
    for clause in re.split(r"[。;；,，\n]", low):
        i = clause.find(hit)
        if i < 0:
            continue
        head = clause[:i]
        return not any(m in head for m in _COND_MARKERS)
    return True


def answer_token(kind: str, a: str) -> str:
    """用户答案 → 小写决策 token(机械映射;挂起/停止是跨题面常驻特权)。

    自由输入(Other)按意图归类,不再按题面剧本硬归并(2026-07-16 P0-新②c;旧版
    cap→恒 continue、env→非确认词即 retry,把剧本外意图强塞最近 token):
    - 缺陷意图(带否定门)在 panel/cap/env/bed/contra 一律 → defect;
    - cap:纠正词(预期/断言/手册…)→ correct(原文落账,裁决语义交下游消费);
      继续词 → continue;停修词 → stop;其余 → correct(原文即信息,不虚假授权轮次)。
    特权词只在短指令里生效(≤8 字):长句里的「挂起/停止」多为叙述
    (「不要挂起,按手册来」),按题面语义走、原文全程保留在 decision 里。"""
    short = len(a) <= 8
    if kind == "suspended":
        # 先于特权判定:「保持挂起」是本题面的常规选项,不是特权触发
        if "恢复" in a:
            return "resume"
        return "stop" if ("停止" in a and short) else "keep"
    if "挂起" in a and (short or a.startswith("挂起")):
        return "suspend"
    if "停止" in a and (short or a.startswith("停止")):
        return "stop"
    if kind in ("panel", "cap", "env", "bed", "contra") and _defect_intent(a):
        return "defect"
    if kind == "panel":
        if "确认" in a or "按此" in a:
            return "confirm"
        return "correct"
    if kind == "cap":
        if any(w in a for w in ("预期", "断言", "改成", "应为", "手册", "改用", "期望")):
            return "correct"
        if any(w in a for w in ("继续", "再修", "再试", "接着")):
            return "continue"
        if any(w in a for w in ("别修", "不修", "不要修", "放弃", "算了")):
            return "stop"
        return "correct"
    if kind == "env":
        return "stop" if "确认环境" in a else "retry"
    if kind == "bed":
        if "降级" in a:
            return "downgrade"
        if "重编" in a or "补自清" in a or "补清理" in a:
            return "reflow_tau"
        if "已处理" in a or "复跑" in a or "已清" in a:
            return "retry"
        return "suspend"   # 不明确=默认挂起到下批(床治理是外部动作,宁等勿猜)
    if kind == "contra":
        if "降级" in a or "接受单跑" in a:
            return "downgrade"
        return "reorder"
    return "correct"


def _side_cn(s: dict) -> str:
    src = str(s.get("source_ref") or "")
    label = "实机回显" if (src in ("device", "device_context", "causality", "detail_tail",
                                   "framework_traceback") or "last_run" in src) \
        else src.rsplit("/", 1)[-1]
    # 引文是 verbatim 契约:窗口宽度与 briefs 注入同宽不改,超窗加「…」留痕;
    # 控制符只在本展示投影剥(落盘 ask_panel.json 与 LLM 载荷仍逐字)
    q = _display_clean(str(s.get("quote") or ""))
    return f"{label}:『{q[:_QUOTE_CLIP]}{'…' if len(q) > _QUOTE_CLIP else ''}』"


def _claim_history_line(c: dict, cap_each: int = 90, last_n: int = 4) -> str:
    """claim 历史摘要(P0-新②d;接缝键 `claim_history`=[{round,layer,disposition,
    claim,evidence}],甲队 N1 粘性数据组装):逐轮呈现「轮次×判断×主张」,归因 churn
    不吞早轮假设——517027 实弹:r2「Timeout=0」缺陷假设在 r3 reflow 叙事的题面里
    消失,用户读到「缺陷已修复」却被问「多轮未收敛怎么办」,题面自相矛盾。"""
    hist = [h for h in (c.get("claim_history") or []) if isinstance(h, dict)]
    if not hist:
        return ""
    lines = []
    for h in hist[-last_n:]:
        disp = _DISP_CN.get(str(h.get("disposition") or ""), "其他判断")
        claim = clip_text(str(h.get("claim") or h.get("fix_direction") or ""), cap_each)
        lines.append(f"第{int(h.get('round') or 0)}轮:{disp}——「{claim}」")
    more = len(hist) - last_n
    return "；".join(lines) + (f"(更早 {more} 轮略)" if more > 0 else "")


def _standing_defect_rounds(c: dict) -> list[int]:
    """claim 历史里判过「疑似产品缺陷」的轮次(缺陷选项文案援引用,选项与案情一致)。"""
    return [int(h.get("round") or 0) for h in (c.get("claim_history") or [])
            if isinstance(h, dict) and str(h.get("disposition")) == "defect_candidate"]


def _s0_dispute_note(c: dict) -> str:
    """污染分歧语境(N2 替代,2026-07-16 裁决:撤新 ask 臂,不新增面板类型/不引入
    IST_S0_DISPUTE_ASK;把「编写孔假设 vs 机械配对结论(+床态快照 diff 如有)」注入
    既有 contra/cap 题面,让用户看全分歧再选)。接缝键 `s0_dispute`={count,pre_dirty[],
    post_dirty[]},甲队 diagnose 侧组装;快照语义按分辨实验三分:跑前脏=受害者/
    跑后脏=自污染/两头净=偶发或取证失真。"""
    d = c.get("s0_dispute") or {}
    n = int(d.get("count") or 0)
    if not n:
        return ""
    pre = [str(x) for x in (d.get("pre_dirty") or [])][:3]
    post = [str(x) for x in (d.get("post_dirty") or [])][:3]
    seg = (f"批内诊断分歧:编写侧 {n} 次判「起点被残留污染」,而机械配对在同卷共居案中"
           "未找到污染者——两者口径不同(后者不查本案自身上轮残留),隔离复跑通过不代表整卷会过")
    if pre:
        seg += f"。复跑前床态快照已见残留(受害者形态):{'、'.join(pre)}"
    elif post:
        seg += f"。复跑后床态快照新增残留(自污染形态):{'、'.join(post)}"
    elif d.get("pre_dirty") is not None and d.get("post_dirty") is not None:
        seg += "。床态快照两头干净——偶发失败或取证窗口失真形态,谨慎判环境"
    return seg


def build_ask_question(c: dict) -> dict:
    """问询目标 → 面板一题(§11.11 构件六:题面渲染自案情事实,自然中文,零内部术语)。
    片4:题面携「已试修法」清单(队列空证明的用户可见半——问到你不是因为没试,
    是引擎侧导出修法已试尽/修法在引擎权限外)。

    2026-07-16 P0 收编自 engine_tool._contradiction_question,四处语义修复:
    ① cap/env 面板补「确认产品缺陷」选项(517027:引擎两轮自判疑似缺陷,面板却只有
      继续/挂起/停止——缺陷出口只存在于 panel 类,用户被迫用「停止」表达缺陷);
    ② cap/env 题面呈现 claim 历史(`claim_history` 接缝键):churn 后不只显最后一轮;
    ③ contra/cap 题面注入污染分歧语境(`s0_dispute` 接缝键,N2 替代——既有 contra≥2
      兜底不动,零新面板类型);
    ④ 题面素材经 clip_text 句读摘要,超长带「…」留痕(zhaiyq 实弹:无痕硬截)。"""
    aid = str(c.get("autoid"))
    kind = str(c.get("kind") or "contra")
    title = str(c.get("title") or "")
    who = f"用例 …{aid[-6:]}" + (f"({title[:24]})" if title else "")
    tried = [str(x) for x in (c.get("tried") or []) if x]
    if tried and kind in ("cap", "env", "bed", "contra"):
        who += f"[引擎已试:{ '、'.join(tried[:3]) }]"
    if kind == "panel":
        p = c.get("panel") or {}
        sides = "；".join(_side_cn(s) for s in (p.get("sides") or [])[:3])
        rc = [str(r.get("outcome") or "") for r in (p.get("retrieval_receipt") or [])]
        searched = "、".join(sorted({_RECEIPT_CN.get(x, x) for x in rc if x}))
        shape_cn = _SHAPE_CN.get(str(p.get("conflict_shape") or ""), _SHAPE_CN["other"])
        # 双源平摆、无预设首选项(§18.15-B/(45)/(46);与 ask_panel 中性契约成对):
        # 呈报差异本身+两侧记载,不渲"引擎的理解"、不给"确认按此"默认——两个选项各指
        # 一侧(实机为准 / 手册为准即缺陷),两读对称,余走 Other。
        q = (f"{who}:{shape_cn}。双方记载——{sides}。"
             + (f"已检索:{searched}。" if searched else "")
             + f"情况梳理:{clip_text(str(p.get('hypothesis') or ''), 300)}。"
             + _display_clean(str(p.get("ask") or "该以哪一方为准?"))
             + ("(该用例重编轮次已用尽,你的答案同时决定是否继续)" if c.get("cap_reached") else "")
             + " 若都不对,选 Other 直接写出正确的意图/预期。")
        # token=correct(非 confirm):中性化后 hypothesis 不再提方向,"confirm=按呈报理解 Z 编"
        # 失去所指;用户选的那一侧 label 即裁决方向,走 correct("ruling 覆盖 Z、意图最高权威",
        # briefs.py)——同时与 answer_token 的 panel 兜底(非缺陷/非确认→correct)一致,
        # 裸串/token 两路殊途同归,不生歧义(成对机制补齐,§18.15-B/(46))。
        return {"question": q, "header": f"裁决{aid[-4:]}",
                "options": [
                    {"label": "预期以实机为准", "description": "以实机实际行为为准,修订该用例的预期断言并重编"},
                    {"label": "确认产品缺陷", "description": "实机行为是产品问题——记入缺陷候选单,该用例以缺陷结案"}],
                "_tokens": {"预期以实机为准": "correct", "确认产品缺陷": "defect"},
                "_key": aid}
    if kind == "cap":
        hist = _claim_history_line(c)
        dc_rounds = _standing_defect_rounds(c)
        note = _s0_dispute_note(c)
        q = (f"{who} 已重编 {c.get('rounds')} 轮仍未通过,引擎多轮未收敛"
             + (f"。各轮判断:{hist}" if hist else
                (f"(最近的修法方向:{clip_text(str(c.get('evidence') or ''), 160)})"
                 if c.get("evidence") else ""))
             + (f"。{note}" if note else "")
             + "。如何处理?")
        dc_note = (f"(在案第 {'、'.join(str(r) for r in dc_rounds)} 轮曾判疑似产品缺陷,见上)"
                   if dc_rounds else "")
        return {"question": q, "header": f"轮次{aid[-4:]}",
                "options": [
                    {"label": "继续,再修 2 轮", "description": "授权追加重编轮次"},
                    {"label": "确认产品缺陷", "description":
                        f"实机行为是产品问题{dc_note}——记入缺陷候选单,该用例以缺陷结案"},
                    {"label": "挂起该案", "description": "先放一放,跑完其他用例;重跑同参数时会再次询问"},
                    {"label": "停止该案", "description":
                        "以未通过如实报告,不再消耗轮次(记为你的停止裁决,不覆盖在案技术判断)"}],
                "_tokens": {"继续,再修 2 轮": "continue", "确认产品缺陷": "defect",
                            "挂起该案": "suspend", "停止该案": "stop"},
                "_key": aid}
    if kind == "env":
        hist = _claim_history_line(c)
        q = (f"{who} 的失败被判为环境阻塞"
             + (f"(依据:{clip_text(str(c.get('evidence') or ''), 160)})" if c.get("evidence") else "")
             + (f"。各轮判断:{hist}" if hist else "")
             + "。确认是环境问题吗?")
        return {"question": q, "header": f"环境{aid[-4:]}",
                "options": [
                    {"label": "确认环境问题,停止该案", "description": "以环境阻塞如实报告该用例"},
                    {"label": "不认可,隔离复跑", "description": "单独再跑一次验证这个判断"},
                    {"label": "确认产品缺陷", "description":
                        "不是环境问题,是产品问题——记入缺陷候选单,该用例以缺陷结案"}],
                "_tokens": {"确认环境问题,停止该案": "stop", "不认可,隔离复跑": "retry",
                            "确认产品缺陷": "defect"},
                "_key": aid}
    if kind == "bed":
        if c.get("self_polluter"):
            # G2((40) 分类学):自污染者——卷面自身含无恢复步的网络层写,复跑=
            # 再污染(run12 六次拆床实证),「复跑」出口对此类是毒药,不提供
            tau = "；".join(str(t) for t in (c.get("suggested_tau") or [])[:3])
            q = (f"{who} 的卷面自身含网络层配置写而**无案尾恢复步**"
                 + (f"(缺恢复:{('、'.join(str(x) for x in c.get('missing_tau') or [])[:60])})"
                    if c.get("missing_tau") else "")
                 + "——每次执行都会重新污染共享床(复跑只会再拆一次,不是出路)。如何处置?")
            return {"question": q, "header": f"缺清理{aid[-4:]}",
                    "options": [
                        {"label": "重编补自清", "description":
                            f"重新编写并在断言后追加恢复步(建议:{tau or '逆序 no 回放'})——推荐"},
                        {"label": "挂起到下批", "description": "本批不动它,下批处理"},
                        {"label": "如实降级", "description": "该案不入交付卷,以未通过如实报告"}],
                    "_tokens": {"重编补自清": "reflow_tau", "挂起到下批": "suspend",
                                "如实降级": "downgrade"},
                    "_key": aid}
        # 文案与证据强度匹配(run14 实弹修:交换子配对是必要条件推断,假阳 20-26%
        # 理论自认;设备失联/命令失败呈同样症状——「唯一根治」类断言语气曾在
        # 11 案设备失联批上全部乱断言)
        _grp = [str(a)[-6:] for a in (c.get("group_aids") or []) if str(a) != str(aid)]
        _grp_note = (f"本题代表 {len(_grp) + 1} 个同因用例(另含尾号 {'、'.join(_grp[:6])})"
                     f",你的答案将应用到全部。" if _grp else "")
        # 证据强度分档(echo-grounding,2026-07-13):回显有占用形态佐证=echo_confirmed
        # (必要条件+回显直接佐证,语气可强些);无=necessity_only(仅交换子必要条件推断,
        # 假阳 20-26%,须提醒「也可能是本案自身命令写法问题,完整回显里查」)。负门(自身
        # 执行失败)已在归因侧由 anomaly_lines 拦下不进本问询。
        _es = str(c.get("echo_support") or "necessity_only")
        if _es == "echo_confirmed":
            _strength = ("此判定=交换子配对必要条件 + 受害者回显含占用/已存在形态直接佐证。"
                         "若属实:整卷复跑洗不掉,须清理床上残留(床权在你)。")
        else:
            _strength = ("注意:此判定仅为交换子配对的**必要条件推断(非确证,假阳约 1/4)**——"
                         "受害者回显里**未见**占用/已存在形态佐证。同样的症状也可能来自"
                         "**本案自身的命令写法**(如撞交互确认、加载全配置冲突)或设备/环境异常;"
                         "下结论前建议看该案完整设备回显确认失败机理。")
        q = (f"{who} 被批级配对判为**疑似测试床状态污染**"
             + (f"(依据:{clip_text(str(c.get('evidence') or ''), 200)})" if c.get("evidence") else "")
             + "。" + _strength + _grp_note + "如何处置?")
        return {"question": q, "header": f"床态{aid[-4:]}",
                "options": [
                    {"label": "挂起到下批", "description": "床治理后下批续跑该案(重跑同参数时会询问恢复)"},
                    {"label": "床已处理,复跑验证", "description": "你已清理残留——引擎复跑一次验证"},
                    {"label": "如实降级", "description": "该案不入交付卷,以未通过如实报告"}],
                "_tokens": {"挂起到下批": "suspend", "床已处理,复跑验证": "retry",
                            "如实降级": "downgrade"},
                "_key": aid}
    if kind == "suspended":
        _g2 = [str(a)[-6:] for a in (c.get("group_aids") or []) if str(a) != str(aid)]
        q = (f"{who} 上批被挂起。"
             + (f"本题代表 {len(_g2) + 1} 个同因挂起用例(另含尾号 {'、'.join(_g2[:8])})"
                f",答案应用到全部。" if _g2 else "")
             + "本批如何处理?")
        return {"question": q, "header": f"挂起{aid[-4:]}",
                "options": [
                    {"label": "恢复处理", "description": "回到正常流程继续修"},
                    {"label": "保持挂起", "description": "本批继续不动它"}],
                "_tokens": {"恢复处理": "resume", "保持挂起": "keep"},
                "_key": aid}
    note = _s0_dispute_note(c)
    q = (f"{who} 单独验证通过、整卷复验第 {c.get('contradictions')} 次失败"
         f"(跨案持久态互扰嫌疑"
         + (f";{clip_text(str(c.get('diagnosis') or ''), 120)}" if c.get("diagnosis") else "")
         + (f";既往选择:{c.get('prior_choices')}" if c.get("prior_choices") else "")
         + ")"
         + (f"。{note}" if note else "")
         + ",如何处置?")
    return {"question": q, "header": f"矛盾{aid[-4:]}",
            "options": [
                {"label": "重排复验", "description": "重排卷序后再终验一轮(互扰案排卷尾)"},
                {"label": "如实降级", "description": "该案不入交付卷,以未通过如实报告"}],
            "_tokens": {"重排复验": "reorder", "如实降级": "downgrade"},
            "_key": aid}
