"""v4 置信函数 f():判 xlsx check_point 行"配不配得上它所测的配置行为"。

不替代上机 verdict,是第二判据(快筛+abstain)。终判仍上机。

**设计红线(goal:不许硬代码)**:本模块**不写任何"某模式该用某断言形态"的规则、不派魔数分、
不做关键词意图匹配**。那些是 _CAPS 式硬编码。判分交给 LLM 看真实证据(招牌菜先例+手册+原始需求)
现场判——few-shot 锚点,不训练、不写规则。

本模块只做**纯客观事实**的两件事(它们是框架契约/数据,不是判断):
1. link_assertion_to_config:按框架派发契约,把每个 check_point 串到它所测的配置步骤。
2. build_judge_evidence:组装"待判断言 + 所测配置 + 同类招牌菜先例 + 原始需求"成证据包,交给 LLM 判分。

判分(score_case)= 调 LLM,喂证据包,让它输出每行 0-1 置信 + 理由。无 LLM 时返回 abstain
(不退化成硬规则猜分——那违背"只看事实")。
"""
from __future__ import annotations
import json
import re
from dataclasses import dataclass, field

# 观测算子判据收敛到单一事实源（与 grade_extract 共用，免两套实现漂移给 grade 矛盾信号）。
from main.case_compiler.observe_ops import observe_kind, config_existence_check, is_observe_command


# ── 唯一的"事实"部分:串联(框架派发契约,客观,非判断)──────────────────
def link_assertion_to_config(rows: list[dict]) -> list[dict]:
    """把每个 check_point 行,关联到它前面最近的"产出输出的非 check_point 步骤"。

    框架契约(事实):check_point 校验上一个非 check_point 步骤的输出(dig/show)。
    config_context = 截至该产出步骤为止所有 APV 配置命令。这是框架行为,不是我的判断。

    rows: [{"E","F","G"}...] 数据区顺序行。
    返回 [{"cp", "tested_step", "config_context":[...]}]
    """
    links = []
    last_output_step = None
    config_so_far: list[str] = []
    captured: dict[str, str] = {}   # 寄存器变量名(H/save_as)→ 捕获它的那条命令,供关系断言溯源
    for row in rows:
        e = (row.get("E") or "").strip()
        g = (row.get("G") or "").strip()
        h = (row.get("H") or "").strip()
        if e == "check_point":
            # cp_h = check_point 引用的寄存器变量名(H 非空 = 捕获+比较关系断言,expect 从寄存器取);
            # capture_src = 该变量捕获自哪条命令(让 grade 能判"捕获源与本次观测是否同源可比")。
            links.append({"cp": row, "tested_step": last_output_step,
                          "config_context": list(config_so_far),
                          "cp_h": h, "capture_src": captured.get(h, "")})
        else:
            if h:   # 非 check_point 步的 H = 把本步输出捕获进变量,登记供后续关系断言溯源
                captured[h] = g
            if e.startswith("APV") and g:
                for line in g.split("\n"):
                    if line.strip():
                        config_so_far.append(line.strip())
            # 带 H 的观测步仅把回显存进寄存器、**不刷新框架 result**（对齐框架 test_xlsx.py:308
            # `if row[7] is None: result=func() else: locals()[var]=func()` 与 structural_gate:201
            # 的 H 把门）。漏掉 `not h` → 带 H 的 dig 被误当后续 check_point 的观测源 → 把"读 show
            # 回显的 IP 断言(断错缓冲)"误判成行为观测/真 V，给 grade 干净体检单放过（GA 假 PASS 根因，
            # 681783 实测 genuine_v_count 4→0）。
            if g and is_observe_command(g) and not h:
                last_output_step = row
    return links


@dataclass
class RowScore:
    cp_g: str
    score: float           # 0-1,LLM 给的
    notes: list[str] = field(default_factory=list)


# ── 证据组装(客观:把三份真实料拼成给 LLM 的证据,不含任何判断逻辑)──────
def build_judge_evidence(rows: list[dict], need_intent: str,
                         anchor_examples: str = "", manual_facts: str = "") -> str:
    """组装判分证据包(纯拼装,无判断)。anchor_examples=招牌菜先例文本(compile_precedent 给),
    manual_facts=手册相关行为(agent grep 给)。这些是真实料,不是我编的规则。"""
    links = link_assertion_to_config(rows)
    parts = [f"原始需求(作者意图): {need_intent or '(未提供)'}", "", "待判的 check_point(每个含它所测的配置):"]
    for i, lk in enumerate(links):
        cp_g = (lk["cp"].get("G") or "").strip()
        cp_f = (lk["cp"].get("F") or "").strip()
        cp_h = (lk.get("cp_h") or "").strip()
        tested = (lk["tested_step"].get("G") if lk["tested_step"] else "") or "(无前序输出步骤)"
        cfg = "; ".join(lk["config_context"][-8:]) or "(无)"
        if cp_h:   # 捕获+比较关系断言(框架原生:expect 从寄存器 cp_h 取),G 空属正常、非悬空
            cap = (lk.get("capture_src") or "").strip() or "(未找到捕获步)"
            parts.append(f"  [{i}] 断言(跨观测关系/捕获比较): {cp_f}(寄存器 {cp_h})")
            parts.append(f"      寄存器 {cp_h} = 前序捕获自: {cap}")
            parts.append(f"      语义: found=本次结果与首次捕获【相同】(同池/亲和保持);not_found=【不同】(换池/超时)")
        else:      # 字面量/常量断言,原逻辑逐字不变(防回归)
            parts.append(f"  [{i}] 断言: {cp_f}({cp_g})")
        parts.append(f"      它校验的输出来自: {tested}")
        parts.append(f"      截至此处的配置: {cfg}")
        # 缺陷①恒真探针(论文三层):看观测算子性质 + 断言是否只是配置存在性检查(非业务行为验证)。
        # 行为观测(dig/统计/session)=V 性质(验业务行为,贡献覆盖);配置查询 show + expect 匹配前序配置命令
        # =G 性质配置存在性检查(不算覆盖)。draft 把后者标 layer=V 即伪覆盖/秩亏(linalg §10)。
        _obs = tested if lk["tested_step"] else ""
        _kind = observe_kind(_obs)        # observe_ops 单一事实源（与 grade_extract 同实现）
        is_cfg_exist, matched_cfg = config_existence_check(_obs, cp_g, lk.get("config_context") or [], cp_f)
        # show 上的 not_found/abs_found(配过的配置) = 状态变更验证（验配置被移除/覆盖后消失，非恒真）
        # = V 性质真覆盖；不因观测是 show 就当 G 段（治应急池覆盖、删除配置类「只能 show 观测」被误判）。
        _is_state_change = (_kind == "config_query") and (cp_f in ("not_found", "abs_found")) and bool(matched_cfg)
        if _kind == "behavior":
            obs_kind = "行为观测(V 性质:dig/统计/session——验业务行为)"
        elif _is_state_change:
            obs_kind = "状态变更验证(V 性质:show + not_found(配过的配置)——验配置被移除/覆盖后消失,非恒真)"
        elif _kind == "config_query":
            obs_kind = "配置查询(G 性质:看配置在不在)"
        else:
            obs_kind = "(无观测步)"
        parts.append(f"      观测算子: {obs_kind}")
        if is_cfg_exist:
            parts.append("      ⚠ 配置存在性检查(查的是前面配过的配置在不在,G 性质)——"
                         "不贡献 V 段覆盖;若 draft 标 layer=V 即伪覆盖/恒真,见判据(a)(b)")
    if anchor_examples:
        parts += ["", "同类招牌菜先例(已验证跑通的认证断言形态,供参考):", anchor_examples]
    if manual_facts:
        parts += ["", "手册相关行为(配置该产生什么可观测特征):", manual_facts]
    return "\n".join(parts)


_JUDGE_SYS = """你是测试评审专家(厨师长)。判断每个 check_point 断言"配不配得上它所测的配置行为"——
即这个断言有没有真的测到原始需求要测的行为,还是只是写了个能 pass 但没咬住行为的弱断言。

判据(只据给你的真实证据,不靠通用常识硬套):
- 看"原始需求要测什么" vs "这个断言实际在校验什么"——对得上才算测到。
- 对照"同类招牌菜先例"的断言形态:先例怎么验这类行为的,待判断言是不是也咬住了同样的可观测特征。
- 对照"手册行为":配置该产生的可观测特征,断言有没有针对它。
- **关系断言(捕获+比较)识别**:若断言形如 found(寄存器 v1)/not_found(寄存器 v1)(期望值是【寄存器引用】、
  引自前序捕获步,证据里标了"跨观测关系/捕获比较"),它测的是"两次观测的**关系**"(本次结果与首次捕获相同/不同)——
  这是会话保持/亲和性/同-异成员/轮转类需求的**正确**编码形态,期望值本就该是运行时捕获的首值、不是编译期常量,
  **不可因"没有字面期望值/G 空"判弱**。判强/弱看:(a)捕获源与本次观测是否同源可比(都对同一对象 dig/show);
  (b)found/not_found 方向是否对上需求要测的关系(该保持的用 found、该变化的用 not_found)。方向对、同源可比 → 高分。
- **边界(防放水)**:以上宽容**仅限寄存器引用型断言**。若断言是 found(某字面量)(期望值是写死的域名/IP/字符串,
  非寄存器引用),仍按下条严判,不得因本 case 别处有关系断言就放松对字面量弱断言的判定:
- 若断言只是 found 一个跟需求行为无关的字面量(域名/IP),而需求要测的是动态行为(分布/计数/时序/关系),
  且先例用的是统计/计数/关系类断言——则该断言弱,低分。
- **(a) 覆盖只由 V 段断言判定(论文§四 三层分解 G⊔E⊔V)**:断言按观测算子性质分层——配置查询 show + **found**
  (看配置在不在)=G 段配置存在性检查;dig/统计/session(看业务行为/解析/计数)=V 段行为验证;**show + not_found/
  abs_found(配过的配置)=状态变更验证(验配置被移除/覆盖后消失,非恒真——配置还在就 fail)=V 段**(证据里标
  "状态变更验证(V 性质)";应急池覆盖、删除配置类产品上只能用 show 观测,这 not_found 就是它们的真 V 覆盖)。
  **只有 V 段断言贡献覆盖度**;G 段配置存在性检查是健全性前置、不算覆盖。证据里标"⚠ 配置存在性检查"的断言,
  即使 found 成立也**不计入覆盖**。
- **(b) observe-then-assert 恒真识别(缺陷①核心=论文 linalg §10 秩亏方向)**:若证据标某断言是"配置存在性检查"
  (观测是配置查询 show、expect 只是 found 一条前序配置命令的回显),而 draft 却标 layer=V——这是**伪覆盖**:
  它"配 X→show X→found X",不验任何业务行为,无论被测命令成败都恒成立。判 **0 分**。
  典型:`clear sdns session persistence X ALL`(要测 ALL 参数/session 清除效果)却只断言 `found "sdns host persistence 3600 X"`
  (验自己前面配的 host persistence 在不在)——没验 ALL 任何行为效果,恒 found。重做意见应指明:断言应改为对**被测行为**的
  V 段断言(如断言被拒回显 "Query type not support"、或 session 表清除前后差异/重新请求命中变化)。
- **(c) 强制核 source_ref 真支撑期望值 + 预期冲突识别**:期望值(字面量)必须有手册/先例/config 客观来源支撑。
  source_ref 缺失、或读出来与期望值对不上 → 低分(期望值没溯源,等于瞎写)。**特别地:若期望值是设备错误回显
  (Invalid input/not support…)而来源 kind=intent(仅凭脑图意图、无手册溯源),且 ref 复述脑图预期却与手册/实机矛盾
  (如"设备应拒绝合法的ALL参数"自相矛盾)——这是脑图预期与手册冲突,draft 改不动,判 0 分**(对应 grade 根因「用例预期冲突」)。
注意:以上 (a)/(b)/(c) **不适用**于上面已豁免的两类——`<RUNTIME>` 占位(诚实弃权)与寄存器引用型关系断言
(found/not_found 寄存器),它们按各自判据走,不受恒真/相关性/source_ref 严判约束。

对每个 check_point 输出 0.0-1.0 置信(1=完全咬住需求行为,0=完全没测到)+ 一句理由。
只看证据下结论,证据不足就给中间分并说明。严格输出 JSON:
{"rows":[{"idx":0,"score":0.0,"reason":"..."}]}"""


def score_case(rows: list[dict], need_intent: str = "",
               anchor_examples: str = "", manual_facts: str = "",
               model=None, judge_timeout_s: int = 120) -> dict:
    """LLM 判分(无硬规则)。喂证据包让 LLM 给每行置信。最弱行拖垮全局。

    model: LangChain chat model;None 时尝试默认构建。构建失败 → abstain(不猜分)。
    返回 {overall, abstain, rows:[RowScore], evidence}。
    """
    links = link_assertion_to_config(rows)
    if not links:
        return {"overall": 0.0, "abstain": True, "rows": [], "reason": "无check_point"}

    evidence = build_judge_evidence(rows, need_intent, anchor_examples, manual_facts)

    if model is None:
        try:
            from main.ist_core.agents._llm import build_agent_chat_model
            model = build_agent_chat_model()
        except Exception as exc:  # noqa: BLE001
            return {"overall": 0.0, "abstain": True, "rows": [],
                    "reason": f"无LLM判分器(不退化成硬规则猜分): {exc}", "evidence": evidence}

    try:
        from langchain_core.messages import SystemMessage, HumanMessage
        import concurrent.futures as _cf
        # LLM 判分加超时保护:hang 住不能卡死整轮(实测过 model.invoke 无超时会 hang 死拖垮 batch)。
        # 超时则返回 abstain(不退化成硬规则猜分),由上机 verdict 兜底。
        msgs = [SystemMessage(content=_JUDGE_SYS), HumanMessage(content=evidence)]
        with _cf.ThreadPoolExecutor(max_workers=1) as _ex:
            resp = _ex.submit(model.invoke, msgs).result(timeout=judge_timeout_s)
        txt = str(resp.content)
        m = re.search(r"\{.*\}", txt, re.S)
        data = json.loads(m.group(0)) if m else {"rows": []}
    except _cf.TimeoutError:
        return {"overall": 0.0, "abstain": True, "rows": [],
                "reason": f"判分 LLM 调用超时(>{judge_timeout_s}s),abstain 不卡死流程;由上机 verdict 兜底",
                "evidence": evidence}
    except Exception as exc:  # noqa: BLE001
        return {"overall": 0.0, "abstain": True, "rows": [],
                "reason": f"判分调用/解析失败: {exc}", "evidence": evidence}

    by_idx = {r.get("idx"): r for r in data.get("rows", [])}
    scores = []
    cov_scores = []      # 贡献覆盖的行(= 非配置存在性检查 = V 性质行)的分
    for i, lk in enumerate(links):
        cp_g = (lk["cp"].get("G") or "").strip()
        r = by_idx.get(i, {})
        sc = float(r.get("score", 0.0)) if isinstance(r.get("score"), (int, float)) else 0.0
        scores.append(RowScore(cp_g=cp_g, score=sc, notes=[r.get("reason", "")]))
        _obs = (lk["tested_step"].get("G") if lk["tested_step"] else "") or ""
        # 传 F 列算子：not_found(配置)=状态变更验证、非恒真存在性 → _is_ce=False → 计入覆盖池
        # （cov_scores），不再被当恒真伪覆盖剔除（治 105969 应急池覆盖断言被排除在覆盖外）。
        _is_ce, _ = config_existence_check(_obs, cp_g, lk.get("config_context") or [], (lk["cp"].get("F") or "").strip())
        if not _is_ce:
            cov_scores.append(sc)

    # 最弱「贡献覆盖的 V 段」行拖垮全局(结构规则,非领域硬编码)。与模型「只有 V 段算覆盖」对齐:
    # 配置存在性检查(G 段:show X→found X 配置回显)按定义不贡献覆盖,故不让它把行为类 case 拖垮——
    # min() 只对非配置存在性检查行取。但若全是配置存在性检查(配置验证类 case,无行为观测),它们
    # 就是该 case 的覆盖,退回对全部行取 min(不误杀配置验证类 case)。
    pool = cov_scores if cov_scores else [s.score for s in scores]
    overall = min(pool) if pool else 0.0
    return {"overall": overall, "abstain": overall < 0.5, "rows": scores, "evidence": evidence}
