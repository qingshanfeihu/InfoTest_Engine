"""questions.py 第二问询族语义面回归锚(2026-07-16 P0-新②/N2 替代/E10a/题面硬化)。

覆盖团队裁决的五组必增测试:①停止≠env_blocked 记账;②cap Other 缺陷意图不归并
continue;③cap/env 面板有缺陷选项;④新 claim_kind 不掉 generic 模板;⑤超长题面
摘要留痕。另锁:answer_token 与 nodes._answer_token 既有语义等价(接线后旧测试
路径经委托复用本实现,这里先行钉死)、新渲染路径零内部术语泄漏、claim 历史呈现
(517027 实弹:r2 缺陷假设在 r3 题面消失)、N2 分歧语境注入(既有 contra 兜底不动)。
"""

from main.ist_core.compile_engine_v8.questions import (
    DECISIONS, answer_token, build_ask_question, build_questions, clip_text,
    validate_questions)

A = "203601753067517027"


# ── ① 停止/降级记账如实(与甲队 user_stop 事件分离成对的题面侧承诺) ─────────────

def test_stop_option_declares_bookkeeping_semantics():
    """517027 实弹:cap「停止该案」曾被记成 env_blocked 假语义。事实层修复=甲队
    user_stop 事件分离(nodes 落 `ev:user_stop`+attribution 带 user_stop:true 标记,
    test_claim_stickiness.py 锁);题面侧成对承诺=停止选项文案如实声明记账语义,
    且 stop 归类不误吞(cap 停修词→stop 而非 continue)。"""
    q = build_ask_question({"autoid": A, "kind": "cap", "rounds": 3, "evidence": "x"})
    stop_opt = next(o for o in q["options"] if o["label"] == "停止该案")
    assert "不覆盖在案技术判断" in stop_opt["description"]   # 记账行≠语义归因,题面即声明
    assert "如实报告" in stop_opt["description"]
    assert answer_token("cap", "停止该案") == "stop"
    assert answer_token("cap", "别修了,放弃") == "stop"      # 停修意图不再恒 continue


# ── ② cap Other 自由输入:意图归类,不再恒归并 continue ──────────────────────

def test_cap_other_defect_intent_not_merged_to_continue():
    """最恶性误译修复:用户写「是缺陷」曾被理解成「再修 2 轮」并真授权。"""
    assert answer_token("cap", "这是产品缺陷,别修了") == "defect"
    assert answer_token("cap", "实机行为是产品问题,提单吧") == "defect"
    assert answer_token("env", "不是环境,是产品缺陷") == "defect"
    assert answer_token("panel", "这是bug,记缺陷候选") == "defect"
    assert answer_token("contra", "这是产品缺陷") == "defect"


def test_cap_other_negated_defect_not_defect():
    """否定门:「不是缺陷,继续修」不得因含「缺陷」二字被归缺陷。"""
    assert answer_token("cap", "不是缺陷,继续修") == "continue"
    assert answer_token("cap", "算不上产品问题,换个思路继续") == "continue"


def test_cap_other_intent_buckets():
    assert answer_token("cap", "别修了,放弃") == "stop"          # 停修意图
    assert answer_token("cap", "预期应为不轮询,按手册改") == "correct"   # 纠正意图
    assert answer_token("cap", "换个断言支点看看") == "correct"
    # 其他:原文落账走通用纠正处理——绝不虚假授权追加轮次
    assert answer_token("cap", "随便吧") == "correct"
    assert answer_token("cap", "随便吧") != "continue"


def test_answer_token_privilege_and_kind_defaults_unchanged():
    """接线等价锚:既有语义(nodes._answer_token 测试面)在新实现下逐条保持。"""
    assert answer_token("panel", "挂起") == "suspend"
    assert answer_token("panel", "挂起该案") == "suspend"
    assert answer_token("panel", "停止该案") == "stop"
    assert answer_token("panel", "不要挂起,预期结果按手册第三章的写法来") == "correct"
    assert answer_token("cap", "不要停止该案,换个思路继续修") == "continue"
    assert answer_token("env", "确认环境问题,停止该案") == "stop"
    assert answer_token("env", "提缺陷单") == "defect"           # 旧版恒 retry 的误译修复
    assert answer_token("bed", "重编补自清") == "reflow_tau"
    assert answer_token("bed", "床已处理,复跑验证") == "retry"
    assert answer_token("bed", "先不动") == "suspend"
    assert answer_token("suspended", "恢复处理") == "resume"
    assert answer_token("suspended", "保持挂起") == "keep"
    assert answer_token("contra", "如实降级") == "downgrade"
    assert answer_token("contra", "再排一次") == "reorder"


# ── ③ cap/env 面板补「确认产品缺陷」选项(语义同 panel 面板既有缺陷臂) ─────────

def test_cap_panel_offers_defect_exit():
    q = build_ask_question({"autoid": A, "kind": "cap", "title": "", "rounds": 3,
                            "evidence": "修法方向x", "prior_choices": []})
    labels = [o["label"] for o in q["options"]]
    assert "确认产品缺陷" in labels and len(q["options"]) == 4   # ≤4:ask_user 硬限内
    assert q["_tokens"]["确认产品缺陷"] == "defect"
    assert q["_tokens"]["停止该案"] == "stop"
    assert "未收敛" in q["question"]


def test_env_panel_offers_defect_exit():
    q = build_ask_question({"autoid": A, "kind": "env", "evidence": "依据y"})
    labels = [o["label"] for o in q["options"]]
    assert "确认产品缺陷" in labels and len(q["options"]) == 3
    assert q["_tokens"]["确认产品缺陷"] == "defect"
    assert q["_tokens"]["确认环境问题,停止该案"] == "stop"


def test_cap_who_carries_tried_proof():
    q = build_ask_question({"autoid": A, "kind": "cap", "rounds": 3,
                            "tried": ["重编 2 次", "隔离复跑 1 次"], "queue_empty": True})
    assert "引擎已试:重编 2 次、隔离复跑 1 次" in q["question"]


# ── claim 历史呈现(P0-新②d,517027 实弹) ───────────────────────────────────

def test_cap_question_shows_full_claim_history_not_only_last():
    """517027:r1/r2 缺陷假设、r3 reflow 叙事——旧题面只显 r3「缺陷已修复」,
    r2「Timeout=0」假设消失,用户被问「多轮未收敛怎么办」时看不到站立假设。"""
    q = build_ask_question({
        "autoid": A, "kind": "cap", "rounds": 3,
        "evidence": "Round 1的缺陷已修复——编译器现在使用IPv6 service IP",
        "claim_history": [
            {"round": 1, "layer": "V", "disposition": "defect_candidate",
             "claim": "SDNS不返回AAAA记录。"},
            {"round": 2, "layer": "V", "disposition": "defect_candidate",
             "claim": "会话保持超时条目不清除(Timeout=0)。"},
            {"round": 3, "layer": "V", "disposition": "reflow",
             "claim": "Round 1的缺陷已修复——编译器现在使用IPv6 service IP。"}]})
    text = q["question"]
    assert "Timeout=0" in text and "第2轮" in text     # 早轮缺陷假设在场
    assert "第3轮" in text                              # 最后一轮也在(不偏科)
    assert "疑似产品缺陷" in text
    # 选项与案情一致:缺陷选项文案援引在案假设轮次
    dopt = next(o for o in q["options"] if o["label"] == "确认产品缺陷")
    assert "第 1、2 轮" in dopt["description"]


def test_env_question_shows_claim_history_when_present():
    q = build_ask_question({
        "autoid": A, "kind": "env", "evidence": "设备不可达",
        "claim_history": [{"round": 2, "layer": "V", "disposition": "defect_candidate",
                           "claim": "超时条目不清除。"}]})
    assert "第2轮" in q["question"] and "疑似产品缺陷" in q["question"]


def test_cap_without_history_keeps_evidence_line():
    """无 claim_history(旧调用方/接线前)→ 保持既有「最近的修法方向」形态。"""
    q = build_ask_question({"autoid": A, "kind": "cap", "rounds": 3, "evidence": "修法方向x"})
    assert "最近的修法方向" in q["question"] and "修法方向x" in q["question"]


# ── ④ E10a:cross_client_landing 专用题面,不掉 generic 采样模板 ────────────────

def test_cross_client_landing_gets_dedicated_template_not_generic():
    led = {A: {"claims": [{
        "claim_kind": "cross_client_landing",
        "reason": "主张不同触发客户端各自固定命中不同池,轮转算法推不出该映射。",
        "min_requests": 0}]}}
    qs = build_questions(led)
    assert len(qs) == 1
    q = qs[0]
    blob = q["question"] + " ".join(o["description"] for o in q["options"])
    assert "客户端" in q["question"]
    assert "加请求/观测次数到可验水平" not in blob    # 不掉 generic 采样模板
    assert [o["label"] for o in q["options"]] == list(DECISIONS)
    assert q["_form"] == "captured_relation"
    assert validate_questions(qs, led)


def test_mixed_claims_compose_not_sampling_only():
    """design-challenger §二 E1:混合 claim(missing_teardown+distribution)曾掉
    generic 采样模板——teardown 侧建议整个消失。重组后两侧建议并陈。"""
    led = {A: {"claims": [
        {"claim_kind": "missing_teardown", "reason": "缺案尾恢复。",
         "suggested_tau": ["逆序回放接口配置"], "min_requests": 0},
        {"claim_kind": "distribution", "reason": "样本不足以支撑占比断言。",
         "min_requests": 20}]}}
    qs = build_questions(led)
    assert len(qs) == 1
    proc = next(o for o in qs[0]["options"] if o["label"] == "改过程")["description"]
    assert "恢复步" in proc and "逆序回放接口配置" in proc   # teardown 侧在场
    assert "加请求/观测次数" in proc                        # 采样侧也在场(确有采样类)


def test_non_sampling_claim_no_misleading_sampling_advice():
    """纯非采样类欠定不再收到「加请求/观测次数」误导建议(run22 同型防复发)。"""
    led = {A: {"claims": [{"claim_kind": "unverifiable",
                           "reason": "观测通道缺失。", "min_requests": 0}]}}
    qs = build_questions(led)
    proc = next(o for o in qs[0]["options"] if o["label"] == "改过程")["description"]
    assert "加请求/观测次数" not in proc


def test_pure_sampling_claim_keeps_legacy_wording():
    """纯采样类台账文案与旧版等同(重组零回归)。"""
    led = {A: {"claims": [{"claim_kind": "distribution",
                           "reason": "占比断言需大样本。", "min_requests": 24}]}}
    qs = build_questions(led)
    proc = next(o for o in qs[0]["options"] if o["label"] == "改过程")["description"]
    assert proc.startswith("加请求/观测次数到可验水平(≥24 次)")
    assert "断言形态按 dist" in proc


# ── ⑤ 超长题面摘要(句读留痕,不无痕硬截) ─────────────────────────────────────

def test_clip_text_clause_boundary_with_marker():
    s = "第一句结论在此。第二句补充证据继续说明设备行为。第三句很长" + "x" * 200
    out = clip_text(s, 40)
    assert out.endswith("…")                 # 截断留痕
    assert out.startswith("第一句结论在此。")
    assert "第三句" not in out               # 按句丢弃,不词中断
    assert len(out) <= 41


def test_clip_text_marks_hard_cut_when_single_long_clause():
    s = "没有任何句读的超长连续串" * 30
    out = clip_text(s, 50)
    assert out.endswith("…") and len(out) <= 51


def test_clip_text_short_passthrough():
    assert clip_text("短句", 50) == "短句"


def test_cap_evidence_no_silent_midword_cut():
    """zhaiyq 实弹:题面曾中途截断成「调整断言为not_found方)」且无省略标记。"""
    ev = ("将检查点调整为not_found方向并复验通过与否需要再看设备回显。"
          "该修法此前在第二轮已尝试过一次。" + "尾部超长补充说明" * 40)
    q = build_ask_question({"autoid": A, "kind": "cap", "rounds": 3, "evidence": ev})
    assert "…" in q["question"]                    # 截断可见
    assert "not_found方向" in q["question"]        # 句内不再词中断


# ── N2 替代:污染分歧语境注入既有 contra/cap 题面(零新面板类型) ────────────────

def test_contra_question_carries_s0_dispute_context():
    q = build_ask_question({"autoid": A, "kind": "contra", "contradictions": 2,
                            "s0_dispute": {"count": 2, "pre_dirty": [], "post_dirty": []}})
    assert "分歧" in q["question"] and "机械配对" in q["question"]
    assert "隔离复跑通过不代表整卷会过" in q["question"]
    assert "两头干净" in q["question"]             # 快照三分语义:两头净=偶发/取证失真
    # 既有 contra≥2 兜底不动:选项仍是 重排复验/如实降级,零新 token
    assert [o["label"] for o in q["options"]] == ["重排复验", "如实降级"]


def test_contra_dispute_snapshot_victim_form():
    q = build_ask_question({"autoid": A, "kind": "contra", "contradictions": 2,
                            "s0_dispute": {"count": 1,
                                           "pre_dirty": ["接口地址残留 1 项"]}})
    assert "受害者形态" in q["question"] and "接口地址残留 1 项" in q["question"]


def test_contra_dispute_snapshot_self_pollution_form():
    q = build_ask_question({"autoid": A, "kind": "contra", "contradictions": 2,
                            "s0_dispute": {"count": 1, "pre_dirty": [],
                                           "post_dirty": ["新增分区配置 1 项"]}})
    assert "自污染形态" in q["question"] and "新增分区配置 1 项" in q["question"]


def test_contra_without_dispute_no_injected_line():
    q = build_ask_question({"autoid": A, "kind": "contra", "contradictions": 2})
    assert "分歧" not in q["question"]


def test_cap_question_carries_s0_dispute_context_too():
    q = build_ask_question({"autoid": A, "kind": "cap", "rounds": 3,
                            "s0_dispute": {"count": 2}})
    assert "分歧" in q["question"]


# ── 渲染层守恒:既有分支锚保持 + 新路径零内部术语泄漏 ───────────────────────────

def test_bed_suspended_panel_branches_keep_existing_anchors():
    qb = build_ask_question({"autoid": A, "kind": "bed", "evidence": "basis",
                             "echo_support": "necessity_only"})
    assert "必要条件推断" in qb["question"]
    qsp = build_ask_question({"autoid": A, "kind": "bed", "self_polluter": True,
                              "missing_tau": ["x"], "suggested_tau": ["no x"]})
    labels = [o["label"] for o in qsp["options"]]
    assert "重编补自清" in labels and "床已处理,复跑验证" not in labels
    qp = build_ask_question({"autoid": A, "kind": "panel", "cap_reached": True,
                             "panel": {"conflict_shape": "expected_vs_observed",
                                       "sides": [], "retrieval_receipt": [],
                                       "hypothesis": "h", "ask": "?"}})
    assert "轮次已用尽" in qp["question"]
    plabels = [o["label"] for o in qp["options"]]
    assert any("实机" in l for l in plabels) and any("缺陷" in l for l in plabels)
    qs2 = build_ask_question({"autoid": A, "kind": "suspended"})
    assert [o["label"] for o in qs2["options"]] == ["恢复处理", "保持挂起"]


def test_new_render_paths_no_internal_terms_leak():
    """内部术语零泄漏门(与 test_ask_panel 同款词表,外加本轮新增的内部键名)。"""
    q = build_ask_question({
        "autoid": A, "kind": "cap", "title": "标题", "rounds": 3,
        "prior_choices": [],
        "claim_history": [
            {"round": 1, "layer": "V", "disposition": "defect_candidate",
             "claim": "会话条目不清除。"},
            {"round": 2, "layer": "V", "disposition": "rerun_isolated",
             "claim": "疑似床态互扰。"},
            {"round": 3, "layer": "user", "disposition": "user_stop",
             "claim": "用户停止。"}],
        "s0_dispute": {"count": 2, "pre_dirty": [], "post_dirty": []}})
    text = q["question"] + " ".join(o["label"] + o["description"] for o in q["options"])
    for term in ("env_blocked", "reflow", "disposition", "attribution", "panel",
                 "cap_reached", "S_", "frozen", "rerun_isolated", "token",
                 "user_stop", "defect_candidate", "h_s0", "s0_dispute",
                 "claim_history"):
        assert term not in text, term
    assert len(q["header"]) <= 12


def test_claim_history_unknown_disposition_stays_chinese():
    """未知处置键不得把内部英文键名漏进题面(兜底人话)。"""
    q = build_ask_question({
        "autoid": A, "kind": "cap", "rounds": 3,
        "claim_history": [{"round": 1, "layer": "X",
                           "disposition": "some_future_key", "claim": "观察一条。"}]})
    assert "some_future_key" not in q["question"]
    assert "其他判断" in q["question"]
