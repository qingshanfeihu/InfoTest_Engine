"""questions.py 第二问询族语义面回归锚(2026-07-16 P0-新②/N2 替代/E10a/题面硬化)。

覆盖团队裁决的五组必增测试:①停止≠env_blocked 记账;②cap Other 缺陷意图不归并
continue;③cap/env 面板有缺陷选项;④新 claim_kind 不掉 generic 模板;⑤超长题面
摘要留痕。另锁:answer_token 与 nodes._answer_token 既有语义等价(接线后旧测试
路径经委托复用本实现,这里先行钉死)、新渲染路径零内部术语泄漏、claim 历史呈现
(517027 实弹:r2 缺陷假设在 r3 题面消失)、N2 分歧语境注入(既有 contra 兜底不动)。
"""

from main.ist_core.compile_engine_v8.questions import (
    DECISIONS, answer_token, build_ask_question, build_questions, chinese_ratio,
    clip_text, english_leak_fields, validate_questions)

A = "203601753067517027"


# ── F-Py-2:叙述字段英文泄漏 detector(中文占比判据,Design 路A) ──────────────────────────────
def test_english_leak_catches_english_narrative():
    """正例:纯英文归因句(reason/fix_direction/no_equivalent_reason 灌英文)被抓(D1:英文直灌题面)。"""
    for claims in ([{"reason": "The device rejected the command due to syntax error"}],
                   [{"fix_direction": "rollback the config in reverse order and retry it"}],
                   [{"no_equivalent_reason": "no equivalent command exists in this version"}]):
        assert english_leak_fields(claims), f"英文归因句应被抓: {claims}"


def test_english_leak_exempts_chinese_quote_and_bracketed_command():
    """反例(不误抓):中文叙述 / 中文+『』命令(剔『』后占比高) / 原文引用字段(device_quote/quote)豁免。"""
    for claims in ([{"reason": "配置保存后残留了会话保持命令未清理,批末统一清"}],
                   [{"reason": "残留『no sdns session persistence www.zyq.com ALL』命令未清"}],
                   [{"device_quote": "sdns pool cname www.a.com syntax error at line 3 col 8"}],
                   [{"quote": "command not found in the CLI manual of this version"}]):
        assert english_leak_fields(claims) == [], f"合法内容误报(假阳): {claims} → {english_leak_fields(claims)}"


def test_english_leak_bare_command_reason_is_flagged():
    """★eval 坐实器(Design 裁②·判据保持):裸命令占满的 reason=worker 双违反(reason 该是中文 WHY
    叙述、命令该走『』结构化通道)——**被 flag=正确行为**(逼源头写正经 WHY 叙述+命令『』),非误杀。
    坐实器价值:逼出边界 case 让设计裁清楚(此裁=该抓、判据对);合法叙述 reason 占比高不误抓(见上)。"""
    bare = [{"reason": "残留 no sdns session persistence www.zyq.com ALL 命令"}]
    assert chinese_ratio(bare[0]["reason"]) < 0.30           # 命令裸奔占满 → 低中文占比
    assert english_leak_fields(bare)                          # → 被 flag(正确:逼 worker 结构化,非误杀)


def test_english_leak_exempts_fact_level_machine_reason():
    """作用域:fact 顶层 reason 是机读码(contradicted_at_delivery)、不灌题面——detector 只该验
    claims 叙述字段。此处直验:机读码若误当叙述验会假阳,故 detector 只在 claims 语境用。"""
    assert chinese_ratio("contradicted_at_delivery") < 0.30  # 机读码占比≈0(证明勿全 facts 扫)


def test_validate_questions_rejects_english_leak_claim():
    """门:注入题面的 claims 叙述字段英文泄漏 → validate_questions False(「自然语言可懂」不变量破)。"""
    q = {"_autoid": A, "question": f"用例 {A} 欠定", "options": [{"label": "改过程"}]}
    assert validate_questions([q], {A: {"claims": [{"reason": "配置保存后残留未清理"}]}})       # 中文→过
    assert not validate_questions([q], {A: {"claims": [{"reason": "config not cleaned up, residual left after save"}]}})  # 英文→拒


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


def test_answer_token_whitespace_suspends_not_correct():
    """F-Py-5①(裁点2·Design 裁 minimal):whitespace-only 答案→suspend(与 empty 的上游
    auto-suspend 一致),修唯一真可达 bug——whitespace " " 因 `not " "`==False 绕上游
    `if not a:` 到 answer_token、旧落末尾 correct 兜底=静默降级(把没答当纠正决策)。"""
    for kind in ("panel", "cap", "env", "bed", "contra"):
        assert answer_token(kind, "   ") == "suspend"       # 纯空白→suspend(非 correct)
        assert answer_token(kind, "\t\n ") == "suspend"     # 制表/换行空白→suspend
    # suspended 类:空白→keep(保持挂起,已正确待答语义)——例外,不归 suspend
    assert answer_token("suspended", "   ") == "keep"
    # 非空实质答案照常映射(guard 只拦纯空白,不误伤纠正/确认/意图词)
    assert answer_token("panel", "确认") == "confirm"
    assert answer_token("cap", "改预期为 X") == "correct"
    assert answer_token("bed", "已处理") == "retry"
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


# ── F-Py-5②(scheme 通道拒空):等价方案类 option 结构标记 _needs_scheme_labels ──────────

def test_scheme_requiring_options_carry_needs_scheme_labels():
    """F-Py-5②:「需用户自定义 scheme」的 option 带结构标记 _needs_scheme_labels(非 grep 字面)——
    consumer 据此判「答案 strip==标签(无 scheme 补充)」拒落 re-ask(532618 空答陷阱)。
    ★窄化(实现视角精化设计判据):只等价方案类(自定义输入型)需 scheme,missing_teardown 的
    改预期(保留残留)自足不列——避免误折自足决策。"""
    # test_point 三元组面板:「我给别的等价方案」需 scheme(选它=承诺给方案)
    tp = {"claim_kind": "verification_path_absent", "test_point": "验证 X",
          "sources": [{"kind": "step", "quote": "步骤"}], "obstacle": "床跑不了",
          "no_equivalent_reason": "无等价手段"}
    q_tp = build_questions({A: {"claims": [tp]}})[0]
    assert q_tp.get("_needs_scheme_labels") == ["我给别的等价方案"]
    # forbidden 面板:opt_expect「改预期」(描述=在下面自定义输入里写你的等价方案)需 scheme
    fm = {"claim_kind": "forbidden_mechanism", "reason": "禁止机制 wrr", "proposed_equivalent": "用 rr"}
    q_fm = build_questions({A: {"claims": [fm]}})[0]
    assert q_fm.get("_needs_scheme_labels") == ["改预期"]
    # ★missing_teardown 面板:改预期=保留残留(自足决策)不需 scheme→不列(窄化命门)
    mt = {"claim_kind": "missing_teardown", "reason": "缺恢复步", "suggested_tau": ["逆序回放"]}
    q_mt = build_questions({A: {"claims": [mt]}})[0]
    assert not q_mt.get("_needs_scheme_labels")             # 空/无——不误把自足改预期当需 scheme
    # ★consumer 判据 scheme_answer_empty:与 W3 :728 子串判据一致(容 TUI 序号/换行加工),
    # 剥标签+序号/标点/空白后无实质=空 scheme→拒(Design 审的同面板判据一致性 gap 修)
    from main.ist_core.compile_engine_v8.questions import scheme_answer_empty
    _tp_lbls = set(q_tp["_needs_scheme_labels"])
    assert scheme_answer_empty("我给别的等价方案", _tp_lbls)            # 纯标签=空 scheme→拒
    assert scheme_answer_empty("我给别的等价方案  ", _tp_lbls)          # 尾空格(F-Py-5① 血泪边界)→拒
    assert scheme_answer_empty("1. 我给别的等价方案", _tp_lbls)         # ★TUI 序号加工→仍拒(gap 修)
    assert scheme_answer_empty("我给别的等价方案：", _tp_lbls)          # 标签+空冒号→拒
    assert not scheme_answer_empty("我给别的等价方案:用 dig 验命中", _tp_lbls)   # 带真 scheme→land
    _fm_lbls = set(q_fm["_needs_scheme_labels"])
    assert scheme_answer_empty("改预期", _fm_lbls)                     # 纯标签→拒
    assert scheme_answer_empty("1. 改预期", _fm_lbls)                  # 序号+纯标签(无 scheme)→拒
    assert not scheme_answer_empty("1. 改预期为实机实际值", _fm_lbls)   # 序号+真 scheme→land(不误拒)
    # ★纯数字 scheme 不误拒(Design re-审 F:断言预期值多是数字——端口/TTL/权重/命中数;
    # 旧剥全部 \d 会把 scheme 实质数字当噪音剥致误拒,^ 锚只剥前导序号后修复)
    assert not scheme_answer_empty("改预期 100", _fm_lbls)             # 数字值 scheme→land
    assert not scheme_answer_empty("改预期：3600", _fm_lbls)           # TTL 数字→land
    assert not scheme_answer_empty("1. 改预期 53", _fm_lbls)           # 序号+数字 scheme→land


# ── F-Py-4(清单感知折叠·数据按引用):机械清单折叠、散文不折 ──────────────────────────

def test_fold_enumeration_folds_command_lists_not_prose():
    """F-Py-4(leader 判据):≥5 短枚举项(换行/顿号/斜杠/逗号)∧ 项短(≤20)无句读 → 折叠
    「共 N 项(前 3)」;3-4 项、散文(含句读)、长项不折。600113 sdns pool 方法斜杠清单实证。"""
    from main.ist_core.compile_engine_v8.questions import _fold_enumeration, clip_text
    # ≥5 斜杠枚举(600113 形态)→折叠
    f = _fold_enumeration("rr/wrr/sh/lc/dh/sed/random")
    assert f and f.startswith("共 7 项(前 3:rr、wrr、sh")
    assert _fold_enumeration("a、b、c、d、e、f").startswith("共 6 项")   # 顿号枚举
    # 3-4 项→不折(短清单全显价值>折叠)
    assert _fold_enumeration("rr/wrr/sh") is None
    assert _fold_enumeration("a、b、c、d") is None
    # 散文(含句读)→不折(即使 ≥5 逗号分句)
    assert _fold_enumeration("先配置池,再加成员,然后下发,查看状态。最后验证访问,确认命中") is None
    # 长项(≥5 项但单项 >20 字符=散文样长句、非命令样)→不折
    long5 = "/".join(["配置轮询算法为加权模式并在下发保存后立即生效不受任何缓存影响"] * 5)
    assert _fold_enumeration(long5) is None
    # ★边界锚(Design 审·显式化):无句读逗号短句散文会误折(逗号是弱清单指示、散文也用)——承认为
    # 可接受边界:发生率低(clip_text caller 归因类多含句读、evidence 走 clean_device_echo)、题面素材
    # 本有损摘要,罕见逗号散文折叠可接受;顿号/斜杠是强清单指示、逗号弱。eval 锚死边界防将来误判为 bug。
    assert _fold_enumeration("先看配置,再查状态,然后测试,最后验证,完成").startswith("共 5 项")
    # clip_text 吃到折叠(清单先于 cap 判断,与长度无关)
    assert clip_text("rr/wrr/sh/lc/dh/sed/random").startswith("共 7 项")


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


def test_triple_projection_free_labels_pass_validate():
    """三元组题(§18.13 逐字投影)的自由 label(「采纳「…」」等)不被 validate 的
    字面枚举误杀——`_token_by_label` 在场时按映射表校验(label 全在表 ∧ token ⊆
    DECISIONS)。回归锚(审计 1-2):旧版 validate 只认 DECISIONS 字面,三元组题必
    False,接回断言路径会整族误杀。"""
    led = {A: {"claims": [{
        "claim_kind": "verification_path_absent",
        "test_point": "sdns listener 配置 port 53 执行 write file 存盘后重启,配置应丢失",
        "obstacle": "自动化环境无法重启设备(会断连、无法继续测试)",
        "equivalent": {"procedure": "查 show startup 中有没有 sdns listener port 53 的配置",
                       "preserves": "write 家族错写启动面会被它抓住(对被测写步敏感)"},
        "reason": "环境无法重启"}]}}
    qs = build_questions(led)
    assert len(qs) == 1 and qs[0].get("_token_by_label")
    # F-TUI-2:采纳 label 由动态 `采纳「{proc}」` 改固定短语(仍是非 DECISIONS 字面的自由 label,
    # 测点=映射表过门不被字面枚举误杀,不变)
    assert any(o["label"] == "采纳该等价方案(方法见题面)" for o in qs[0]["options"])
    assert validate_questions(qs, led)   # 自由 label 经映射表过门,不误杀


def test_defect_intent_conditional_clause_not_shortcut():
    """条件句门(2026-07-17 实弹):带前置条件的缺陷处置指令不得短路成无条件 defect
    ——「直查仍不返回才按缺陷候选结案」曾被归「确认产品缺陷」,用户的条件裁决被
    简化执行。条件句掉 correct 兜底(原文完整落账下发)。"""
    # 实弹原文与同型条件句 → 非 defect,cap 兜底 correct
    for cond in ("直查仍不返回才按缺陷候选结案",
                 "若复现再提单",
                 "先隔离复跑,如果还挂就报缺陷",
                 "等复现后再提单"):
        assert answer_token("cap", cond) == "correct", cond
    # 无条件缺陷意图照旧短路(517027 修复不回归)
    for uncond in ("是缺陷", "确认产品缺陷,提单吧", "这是产品问题", "不认可,是缺陷"):
        assert answer_token("cap", uncond) == "defect", uncond
    # 否定门照旧(「不是缺陷」不算)
    assert answer_token("cap", "不是缺陷,继续修") == "continue"
    assert answer_token("cap", "先不提缺陷,按手册改预期") == "correct"


def test_side_cn_and_ask_strip_control_chars_display_only():
    """题面展示路径剥控制字符(TAB→空格/\\r 剥;双侧防御,渲染侧 dom.py 已同修)。
    verbatim 契约边界:只动展示投影,落盘 jsonl 与 LLM 载荷不经此函数。"""
    from main.ist_core.compile_engine_v8.questions import _side_cn
    s = _side_cn({"source_ref": "device", "quote": "col1\tcol2\r\nWarning:\toccupied"})
    assert "\t" not in s and "\r" not in s
    assert "col1 col2" in s and "Warning: occupied" in s   # 语义保持,仅规格化
    q = build_ask_question({
        "autoid": A, "kind": "panel",
        "panel": {"conflict_shape": "expected_vs_observed",
                  "sides": [{"source_ref": "device", "quote": "a\tb"}],
                  "retrieval_receipt": [], "hypothesis": "h",
                  "ask": "该以\t哪一方为准?"}})
    assert "\t" not in q["question"]
