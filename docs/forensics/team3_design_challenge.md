# team3 · 设计对抗质疑 — DESIGN_dongkl_finalization + V8 实现 + CLAUDE.md 编译章节

> 角色:设计对抗质疑者。全程只读(唯一写=本文档)。
> 对象:`docs/DESIGN_dongkl_finalization.md` 全文、`main/ist_core/compile_engine_v8/`(graph/nodes/views/facts/_shared/briefs/questions/remedies/render/report_gate/uncertain/engine_tool)、两孔契约(`compile-worker.md`/`compile-attributor.md`)、门族(`emit_xlsx_tool`/`structural_gate`/`batch_tools`/`fail_attribution`/`ask_panel`)、CLAUDE.md 编译章节。
> 证据源:代码逐行 + dongkl 盘上交付物(engine_report/facts/物理卷 openpyxl 实读)+ zhaiyq 活批 facts.jsonl 只读快照(517027/533020 全事实链)+ 前五份 forensics。
> 生成:2026-07-16。裁决词表:**兑现** / **兑现但有旁路** / **未兑现(证据)** / **声称过时**。

---

## 零、五个最重发现(先读)

1. **【未兑现·最重】"缺陷候选单"不存在于任何交付物,结构化缺陷表单全链湮灭**(§一 C20)。render 对 defect_candidate 案说"已记入缺陷候选单",但交付物全集(case.xlsx/双报告/engine_report/facts/unsuccessful×2)无此文件;`submit_attribution` 强制校验的结构化表单(repro/expected_with_source/actual)唯一落点是 `last_run.json._attribution.defect_candidate`,而 `attribute` 收账只抄 5 个字段不含它(nodes.py:1438-1444),`closing` 又把 last_run.json 删了(nodes.py:2536-2540)——全 repo 零消费者(grep 实证)。**用户要求"除设备缺陷外全部输出"——设备缺陷恰是唯一该单独输出却被引擎丢弃的东西**。zhaiyq 532862(引擎自判 product_defect 层)的结构化单将同样湮灭。
2. **【实证复盘】517027 三重叠加的 ask 缺陷**(§二 A):cap 面板 evidence 只显最后一轮归因(churn 后=reflow 的"已修复"叙事),r2 的 defect_candidate 假设(超时条目不清)不呈现;cap 选项(继续/挂起/停止)无缺陷出口;用户选"停止"被硬编码成 `attribution layer=E disposition=env_blocked`——**非环境问题以"环境阻塞"入账终态,事实层语义为假**。
3. **【兑现但有旁路】"swallowed verdicts are structurally impossible"**(§一 C1):裁决入账层面成立;但 dongkl 物理主卷**至今**24 案(22 交付+778041 泄漏+哨兵)而 engine_report 仍写 `delivered_with_labels` 零失配——组成对账门是事后加的、只检测不纠正、不回溯历史批。
4. **【修复冲突·最险】A1 签名结构化缺迁移条款**(§四):`_fail_signatures` 是五处交集比较的输入(.frozen.json/digest 跨轮/facts frozen 谓词/跨床反驳/词干聚类),修复上线跨界轮"旧脏签名∩新净签名=∅"→冻结与跨床反驳静默失效一轮。
5. **【修复冲突】N2 与既有 contra≥2 通道重叠**(§四):533020 全事实链实证已收敛——2 次 delivery 翻转→contra ask→用户 downgrade 结案。"无限振荡"不成立;真缺口是 contra 题面不呈污染分歧证据。

---

## 一、设计声称 × 兑现裁决表

| # | 声称(出处) | 代码落点 | 强制机制 | 违背实例/旁路 | 裁决 → 动作 |
|---|---|---|---|---|---|
| C1 | "swallowed verdicts are structurally impossible"(engine_tool.py:333 docstring;SKILL.md description 逐字同款) | INV-2 残差门 nodes.py:962-968(comp 全员必在 last_run,缺=error 硬停);reconcile 全射 facts.py:213-236(每裁决显式结局);INV-11 fail-loud 族(writeback_failed/rollback_failed/emit_invalid/gate_disabled) | 有(裁决入账层) | ①dongkl 778041:裁决没被吞,**物理交付卷吞了案**——盘上实读主卷 24 案 vs report deliverable 22,outcome=`delivered_with_labels`、`volume_composition_mismatch:null`(门 2026-07-16 后加,不回溯);②composition 门 fail-open(卷读不出→`([],[])`);③reconcile 对卷外 autoid 记录静默 drop(语境锚,注释合理) | **兑现但有旁路**。字面范围(verdict reconciliation)成立,但两处声称点(工具 docstring+SKILL description)的自然读法是"交付不会吞结论",被 778041 破。→ ①改文档:两处措辞限定为"每条上机裁决必有显式入账结局";②方案 a(按 deliverable 重合并)专项轮落地,并对 dongkl 历史卷做一次性回溯(现状=把泄漏卷继续交付在盘上) |
| C2 | "先问后落代码强制"(CLAUDE.md;DESIGN §⑤ needs_decision 链) | worker 声明欠定但无台账→escalated(nodes.py:408-420);S_AWAITING_USER 挡 merge ready 集(views:92-94+merge live 排除);`compile_user_decision` form 门;emit F6 门(user_decision.json 放行凭据,读引擎盖章 intent.json) | 有(声明过的欠定) | 旁路链:worker 白名单**含 run_python**(compile-worker.md frontmatter)→可直写 case.xlsx+`os.stat` 取精确 mtime 伪造 `.grade_credential.json`→precheck(mtime+lint)通过→**emit 专属门(F6 禁令机制/user_decision form/provenance 必传)全部旁路**——merge 重扫只有形态 lint,不含这三门。对"未声明的欠定"本就无法强制(语义上不可判) | **兑现(已声明欠定)/防漂移-worker 绕行不成立(禁令机制族)**。→ 改代码(择一):合并预检增查"intent.json 带 forbidden_mechanism ∧ 无 user_decision.json"组合(引擎侧数据都在,一行谓词);或凭证加工具进程盐。风险评级低(非对抗环境)但 F6 是安全 backstop,backstop 可绕应记档 |
| C3 | "ledger 迁移合法性表:`passed→重编` 在数据层非法"(CLAUDE.md) | V8 **无 ledger**——状态=事实流派生标签(views.py 全文),author 靠状态选案(nodes.py:348-350 不选 deliverable) | 无"数据层非法"概念 | V8 里对 pass 案追加 authored 事实完全合法:指纹失配→自动降回 subset_verified 重验(这是特性,INV-8) | **声称过时**。→ 改 CLAUDE.md:V8 语义="pass 卷面锁=裁决-卷面指纹绑定(deliverable 三重匹配),重编自动触发重验",非迁移非法表 |
| C4 | "断点续跑…已跑设备轮不重烧(run_marker 幂等)"(CLAUDE.md;engine_tool docstring "without re-burning device rounds") | V8 无 run_marker(全仓 grep 0);替代=终验幂等闸(merge nodes.py:833-836 同 volume 有 delivery 裁决且无待升格→不重跑)+verdict 幂等键+checkpoint | 有(对**已完成并入账**的轮) | crash 落在 run 节点中途(digest 已烧设备、reconcile 未跑)→resume 重执行 run→**该轮重烧**。V6 run_marker 挡的正是这段,V8 没接 | **部分兑现,措辞陈旧**。→ 改 CLAUDE.md;可选改代码:run 节点 digest 前查"同 volume 的 last_run 已存在且未消费"则跳直 reconcile |
| C5 | "凭证 LLM 冒充不了/精确 xlsx_mtime 值只能从工具落盘获得"(emit_xlsx_tool.py:1722 注释;CLAUDE.md) | compile_emit 过全门落凭证(1591-1608);precheck/合并双卡点验 mtime 签名+重扫 lint | 有(防事故/防直改) | `os.path.getmtime` 就能获得精确值;worker 有 run_python(见 C2)。合并 lint 重扫兜住形态类,伪造只绕"经 emit"证据(F6/provenance/form 门) | **字面不成立,工程上双卡点兜底**。→ 改文档措辞("冒充需主动伪造且仍过成品卷 lint;emit 专属门不受 lint 保护"——与 C2 同施工面) |
| C6 | INV-flush "批末必有聚合点=强制不变量"(DESIGN §⑥-B) | graph.py 全部 pre-ask closing 边过 `_gather_or_close`(:50-61)✓;closing 落 `awaiting_user_unasked` 兜底(nodes.py:2265-2280)✓;两处豁免=设计明文 post-ask ✓ | 有(needs_decision 族) | **词汇缺口**:门只查 `n_awaiting_user`;panel/env/cap/bed/contra/suspended 等待集(`n_ask_contradiction`)在硬错误收口边(run device_busy/reconcile error/merge error)**不 flush**,closing 兜底事实也只覆盖 S_AWAITING_USER。这族问询静默不问——report 的 remedy_text 会说"等待你授权"(诚实),但无 ask、无显式 unasked 事实(正是 yzg 7 欠定案同型,只是换了问询族) | **兑现一半**。→ 改代码(小):`_gather_or_close` 与 closing 兜底扩到第二问询族;或改设计文档明示"INV-flush 范围=欠定族" |
| C7 | 卷指纹隔离:subset 复跑不 churn current_volume(§⑥-C②) | views.py:134-152(排除 ctx=subset);report_gate.py:27 同口径 | 有 | zhaiyq 活批未再现饿死 | **兑现** |
| C8 | broken 三态+errored 机械短路不调 LLM(§④) | views 子态(23-27);reconcile 机械归因 nodes.py:1034-1074(`mechanical:True`,不派孔);graph 路由 110-112/125-128;footer 投影 `_footer_bucket_counts` Σ=total(team2 修) | 有 | 无 | **兑现** |
| C9 | broken per-case streak≥2 降秩终止(§⑥-A) | nodes.py:1005-1025(跨 artifact 按 aid 累计,pass/fail 重置) | 有 | zhaiyq 561213/589503 均 2 连 broken→escalated ✓ | **兑现** |
| C10 | F1 平摆无默认(§B) | ask_panel.py schema(hypothesis/ask 中性描述门:71-82)+verbatim 双侧门+retrieval_receipt 必填+形态-侧别一致门(241-246);engine_tool panel 双选项对称(226-229) | 有 | 选项集偏窄(见 §二 C):"实机为准/产品缺陷"两读之外(如"预期对,采样噪声,复跑再看")无位,Other→correct | **兑现**(平摆本体);选项完备性归 §二 |
| C11 | 写回像记忆:precedent 三标/footprint 只标机生;真 PASS 双写回+矛盾回滚(§A) | reconcile 写回/回滚(nodes.py:1077-1124,provisional=非 delivery);`_writeback_one/_rollback_one` 失败显式入账(INV-11) | 有 | zhaiyq 533020 链实证 writeback→delivery fail→rollback 循环工作 ✓ | **兑现** |
| C12 | expectation_suspect 必带 panel(机械门,防活锁) | fail_attribution.py:241-253(无 ask_panel.json 拒绝落) | 有 | 门只查**文件存在**,不查 ts/_round 新鲜度——陈旧已答面板可满足门;引擎收割侧 ts 门(nodes.py:1456)会拒收陈旧面板,该案落 S_FAILED+空队列,由终验幂等闸兜住不活锁,但以"failed 无新呈报"收尾 | **兑现但有旁路**(低危)。→ 改代码一行:门补 `panel._round == rec._round` |
| C13 | 止损归用户/round==99 来源信号伪造不了(views.py:36-42) | submit_attribution round 取台账 `_round`(fail_attribution:317);engine attribute 收账覆盖为 rounds_used(nodes.py:1439);99 仅 ask_contradiction 节点写(nodes.py:2120/2125) | 有 | `_round` 理论到 99 需 ~48 次 continue 授权,不可达 | **兑现** |
| C14 | 自愈环:fail/escalated 观察 uncertain 入库(CLAUDE.md;uncertain.py docstring) | `_ingest_uncertain_observations`(uncertain.py:47:仅 `failed_terminal+escalated`) | 有(窄) | ①已知:漏 S_SUSPENDED(fix plan A2);②**新**:连 docstring 声称的 "fail" 也没收——S_FAILED/S_CONTRADICTED 终批案同样不入库(实现比文档更窄);③**新·杠杆掐点**:数据源=`behavior_candidates.json`(attributor **自愿**调 submit_behavior_fact 才有)——dongkl 12 未决案仅 6 有候选,**最富信息的 777976(跨客户端)/593516(成员IP配错命令)恰好无候选**→A2 单独落地对这两案零效果,验收标准"8 挂起案观察可见于 footprint"**不可达** | **未兑现**(范围+数据源双断)。→ 改修复方案:A2 扩 in_state(suspended+failed+contradicted)且必须与 C5(attr_evidence 一次性回填)绑定为同一验收;结构性补生产侧兜底(closing 把 fail 轮 attribution 的 evidence/fix_direction 机械转观察候选,或 attributor prompt 升强度) |
| C15 | 终验整卷路由(V6 修复) | V8 等价物=merge 语境判定(779-784)+组成锚 INV-8+待升格强制终验(831-836) | 有 | CLAUDE.md 引用的回归锚 `test_final_full_verify_routing.py` 全 tests/ 不存在(code_align D4 已记) | **兑现(机制),文档锚失效** |
| C16 | 上机互斥+残留探测 | `_RUN_MUTEX` 非阻塞进程锁(batch_tools:557-565);deliver 前 SSH 探残留 pytest | 有 | 跨进程窗口(探测与启动之间)仍在——已知限制,文档如实 | **兑现** |
| C17 | 归因修法生效性闭环(_prev_attribution) | batch_tools:1259-1266(fail 记录保留上轮 _attribution) | 有 | zhaiyq N1 churn 说明"保留了但没约束力"(归 §四 N1) | **兑现(机制);约束力缺=N1 议题** |
| C18 | frozen≠终态/override 换法通道 | digest 落 .frozen.json 保留 overrides 历史(batch_tools:1206-1236);emit `override_frozen_reason` 门 | 有 | **V8 派生谓词 `F.frozen` 零消费者**(views.py:157 产出,全 repo 无读者)——两套冻结(digest 文件链 vs 事实派生)并存,活的是 V6 文件链;死谓词是漂移隐患(改了签名格式后两套各断各的) | **兑现(V6 链);V8 谓词=死代码**。→ 改代码(删或接线到 remedies/briefs)或设计文档记录双轨现状 |
| C19 | G5 报告保真(Report=render(fold(facts))) | report_gate.py 独立重算(故意不复用 views)+headline 核对+closing 翻转 outcome | 有 | G5 核"报告 vs facts",**不核"物理卷 vs facts"**——778041 型泄漏 G5 结构上抓不到(composition 门补位后闭合);另 recount 的 needs_decision 判据比 views 粗(any-decision vs 按题配对),多题部分作答场景会自误报(fail-loud 方向,可接受) | **兑现**(范围内) |
| C20 | "缺陷候选单"(render remedy_text:"已记入缺陷候选单";fail_attribution docstring:"defect candidates that never land cannot be rolled up into a defect list") | 结构化表单强制校验(fail_attribution:321-336 repro/expected_with_source/actual 必填)→落 last_run.json | **无**(交付侧) | attribute 收账只抄 layer/disposition/h_position/fix_direction/evidence(nodes.py:1438-1444),**不抄 defect_candidate 字段**;closing 删 last_run.json(2536-2540);全 repo 该字段零读者(grep 实证)→**表单湮灭,交付集无缺陷单文件,render 文案说谎** | **未兑现(最重)**。→ 改代码三件套:①attribute 收账透传 defect_candidate 入 attribution 事实;②closing 产 `defect_candidates.md`(+json)入 deliver_files 与对账;③render 文案与产物对齐。P0 级:顶撞用户"除设备缺陷外全部输出"的验收本意 |

---

## 二、ask 面板设计专项(用户验收点:自然语言可懂/不自相矛盾/选项真实有效/不提供虚假问题)

### A. 题面与案情失配 — 517027 全链复盘(zhaiyq facts 逐事实实读)

```
r1 attribution V/defect_candidate  "SDNS不返回AAAA记录…"
r2 attribution V/defect_candidate  "session persistence expired entries (Timeout=0) should…"  ← 真缺陷假设
r3 attribution V/reflow            "Round 1的缺陷已修复——编译器现在使用IPv6 service IP…"      ← churn
cap_reached → ask_shown kind=cap   题面 evidence = r3 的 reflow 叙事(截断)
decision tok=stop("停止该案") → attribution E/env_blocked r99 → S_TERMINAL
```

三个独立缺陷叠加:
1. **cap 题面 evidence=最后一轮归因**(nodes.py:2005 `atts[-1].fix_direction[:300]`;engine_tool:233 再截 [:160])——归因 churn 后,站着的 defect_candidate 假设(r2)不进题面。用户读到的是"缺陷已修复"却被问"多轮未收敛怎么办"——**题面自相矛盾的机理**。
2. **cap/env 面板无缺陷出口**(engine_tool:236-252):cap=继续/挂起/停止,env=确认环境/隔离复跑。引擎自己两轮判 defect_candidate,面板却不给"确认缺陷"选项——正是任务书点名的 517027 形态,代码层面结构性成立(defect token 只在 panel kind 存在,而 panel 依赖 attributor 自愿 file)。
3. **stop→env_blocked 硬编码语义假**(nodes.py:2118-2122):cap/env/bed 的 stop/downgrade 一律落 `layer=E, disposition=env_blocked`。517027 按引擎自己的证据链是疑似产品缺陷,终态账面却写"环境阻塞"。render 说"按环境/取舍收尾"(hedge 了一半),facts 层是假的——下批检索/统计按 env_blocked 消费即误导。

### B. 自由输入(Other)的 token 强制归并 — 选项虚假有效性的机理

`_answer_token`(nodes.py:1518-1556):特权词(挂起/停止)仅短句生效,其余**按题面 kind 硬归并**:
- **cap → 恒 `continue`**:用户在 cap 面板写"这是产品缺陷,别修了"→引擎理解为"追加 2 轮"并真授权(granted_rounds+2)。G4 echo 会显示"(语义兜底…请核对)"但动作已发生。
- **env → 非"确认环境"即 `retry`**:写"提缺陷单"→隔离复跑。
- **panel → 非缺陷/确认词即 `correct`**:程序性答案("复跑一次试试")会被当**意图纠正原文**下发 worker("ruling 覆盖 Z、意图最高权威",briefs.py:156-157)——把 retry 类答案编译进卷面。
- bed_gate 自由输入含"继续"子串即 proceed(engine_tool:150)——"先清理再继续"会被读成放行。

**裁决**:选项在其预设剧本内真实有效;剧本外的用户意图被强制塞进最近的 token。→ 改代码:Other 归并加否定门(含"缺陷/不是环境/别修"类硬词时不归并,改为重问或落 correct+panel);cap/env 面板补第三/四选项(见 §四 N1 联动)。

### C. 截断 — zhaiyq 实弹"调整断言为not_found方)"的定位

needs_decision 通道已修(questions.py `_first_clause` 按中文标点截,§18.14 D2,668059 实证驱动);**ask_contradiction 通道全是裸 `[:N]`**:nodes.py:1505(`_case_diag`[:160])、2005/2009/2016(evidence[:300]);engine_tool:233([:160])、291([:200])、217(hypothesis[:300])。双层截断、无省略号、词中断。zhaiyq 实弹即此。→ 改代码:`_first_clause` 推广到第二问询族(同一函数,搬用即可)。

### D. 同题重问/沿用裁决语义 — 兑现良好

- question_id 按(类型:aid:轮/计数)键控,答过不重问 ✓;挂起案"同批不再问、新批问一次恢复"✓(_shared.py:140-157)。
- adopted 免问三条件门(同键∧token 唯一∧实机行为引文仍匹配,nodes.py:1249-1275)+时间线人话"你此前已有裁决,直接沿用(免问)"✓;prior_adjudication 注入下一轮归因 brief 防重复呈报 ✓。
- 折叠组答案广播逐案落盘、非代表标 folded_into,账目可回放 ✓。
- 部分作答不吞已答案子(§16.6 run17 修)✓;零答→自动挂起+可恢复,永不空转 ✓。

### E. 虚假问题防护 — 两处残留

1. **needs_decision 混合 claim_kind 掉 generic 模板**:questions.py 分支全是 `all(k == X)` 精确匹配——一案同时有 missing_teardown+distribution 两类 claim 即掉底部 generic"加请求/观测次数到可验水平"模板,对非采样类欠定给误导选项(run22 病理只修了 test_point 单类)。E10a 新增 claim_kind 会再踩(见 §四)。
2. **queue_empty 声称**:题面带"已试修法+队列空证明"(remedies)✓;队列非空仍进 ask 时仅 log warning 照问(nodes.py:1984-1986,fail-open"人比闸权威")——设计自洽,但报表层 R5 度量不区分此形态,建议 decision_outcome 补 queue_nonempty 标记(一行)。

### F. TUI 最后一公里(记忆佐证,非本轮代码)

多题面板"数字只高亮、每题必须 enter、Tab 不落答案"(run15+17 两次 3 题丢 2)——丢答案在引擎侧表现为零答→自动挂起(安全但静默降级)。engine_tool._panel 的答案正则(`(?=\. "|\.?\s*$)`)对含 `. "` 序列的自由输入会早停截断。ask 链的可靠性瓶颈在这一层,与本轮修复方案正交,记档。

---

## 三、交付诚实性专项(用户要求:除设备缺陷外全部输出)

### 兑现面(先说好的)

- **全状态进报告**:render `bad` 集=一切非 deliverable(含 pending/escalated/suspended/awaiting/broken 三态),每案三段式(发生了什么/怎么判断的/去向)。dongkl 实证 12/12 分节齐全:593545 pending"未开始·编写 0 次"在报,778041"按裁决收尾(未通过卷)"在报 ✓。
- **G5 报告重算门**独立路径核数字+headline ✓;**leak_scan** 术语泄漏门 ✓;**G4 decision echo** 进收口卡 ✓;**交付对账断言**(报告说有=盘上真有,缺=outcome 降级)✓;**awaiting_user_unasked** 区分"没问过/问了没答"✓。
- 挂起案 delivered/unfinished 存档+prep 还原,续跑链完整 ✓。

### 静默/失真路径清单(系统扫描结果,按重排序)

| # | 路径 | 机理(file:line) | 裁决 → 动作 |
|---|---|---|---|
| S1 | **结构化缺陷单湮灭** | =C20 | 改代码(P0) |
| S2 | **历史批不回溯**:dongkl 主卷至今 24 案、report `delivered_with_labels` 零失配 | composition 门只管未来 closing;方案 a(重合并纠正)未落 | 改修复方案:方案 a 专项轮 + 对已交付批一次性对账/重滤脚本 |
| S3 | **unsuccessful_cases.xlsx 合并失败静默**:`_archive_unsuccessful` 失败仅 `logger.debug`,不入 deliver_files→missing 对账不报;而 delivery_report 正文(先渲染)无条件声称"交付物:…unsuccessful_cases.xlsx" | nodes.py:2219-2223 vs render.py:269-271 | 改代码(小):失败→outcome 降级或正文条件化+落事实 |
| S4 | **G3 封堵 × composition 门必然降级**:G3 案物理上仍在最后 delivery 卷→组成对账必报 leaked→outcome 必 delivery_incomplete——"带标注交付"对 G3 批结构性不可达(诚实方向,但两门组合放大) | nodes.py:2391-2418 + 2547-2566 | 改修复方案:方案 a 需覆盖"G3 封堵后重合并剔除"场景 |
| S5 | **engine_tool 陈旧报告风险**:`_MAX_INTERRUPT_ROUNDS=12` 耗尽后直接读盘上 engine_report.json 当本次结果——若是同名批上次 closing 的旧报告,无 staleness 校验,静默把旧结论当新结论返回主 agent | engine_tool.py:365-377 | 改代码(小):report 带 run_start 序核对,或耗尽时明示"未收口,续跑" |
| S6 | 无卷案不在 unsuccessful_cases.xlsx(无 rows 跳过,合理)但报告不声明该卷仅含有卷案 | nodes.py:2212-2216 | 改文档/render 一句 |
| S7 | composition 门 fail-open(卷读不出→零报)+哨兵过滤正确(`999999999999999` 排除,batch_tools:234) | nodes.py:2243-2252 | 可接受(已注释宁漏勿杀);记档 |
| S8 | fail_attribution 写 last_run **非原子**(batch_tools 同文件已原子化,纪律不一致);崩溃后果=reconcile INV-11 硬停(fail-loud 可见) | fail_attribution.py:339 | 改代码(一行,对齐 `_write_json_atomic`) |
| S9 | INV-flush 第二问询族旁路(=C6):硬错误收口时 panel/cap/env 族问询静默不问,报告 remedy_text 说"等待授权"但无 ask、无显式 unasked 事实 | graph.py:61 + nodes.py:2265-2280 | 改代码(小) |

**结论**:报告层诚实度高(12/12 呈现+多重对账);失真集中在**物理卷层**(S1/S2/S4)与**收尾边界**(S3/S5/S9)。"无遗漏路径"的系统证明不成立,但遗漏路径已可枚举闭合如上。

---

## 四、P0/P1 修复方案 × 设计不变量冲突检查(逐项)

| 修复 | 对照不变量 | 冲突/缺口 | 裁决 → 动作 |
|---|---|---|---|
| **A1** fail_signatures 结构化解析 | 冻结语义(同签名两轮=换法);跨床反驳;瞬态复现护栏 | 签名是**五处交集比较**的输入:①.frozen.json `signatures`;②digest 跨轮 `sig_now∩sig_prev`(batch_tools:1200-1204);③facts verdict signatures→`F.frozen`(facts.py:169-170);④`_cross_bed_refuted`(nodes.py:1722-1730);⑤diagnose 词干聚类(1929-1938)。**修复上线的跨界轮:旧脏∩新净=∅→冻结/跨床反驳静默失效一轮**(在跑批 resume 场景必踩);反向收益=节头假交集消失 | **改修复方案**:补迁移条款——上线后首轮对 prev 侧签名按新规则**重提取原文**再比(fix plan 验收#2 的"9 案重提取"扩到运行时 prev_map 现场),或双算一轮;.frozen.json 存量文件同规则刷一遍 |
| **A2** 入库补 S_SUSPENDED | §11.11 挂起=本批不打扰;(45) 判例血统 | ①与"不打扰"不冲突(入库非问询)✓;②改描述型挂起(零上机)入库其编译期 probe 观察,语义成立 ✓;③**杠杆被数据源掐住**(C14):777976/593516 无 behavior_candidates,A2 单独落地对它们零效果,验收"8 挂起案观察可见"不可达 | **改修复方案**:A2 与 C5 绑定为同一验收;in_state 扩到 suspended+failed+contradicted(对齐 docstring 的"fail");补生产侧兜底(见 C14) |
| **D9** brief 注入标"作者预期(未证实)"/上轮归因标"假设" | 红线9:断言期望值溯源脑图/手册,禁 observe-then-assert;(45b) 机生不盖人源 | 现状确认:briefs.intent_summary(:22-24)把 `expected:` 原样当事实注入;fix_direction 以 `<fix_direction>` 无假设框注入(:78)。**张力**:标"未证实"若无后半句,worker 会滑向"以设备观察为准改预期"——而"预期以实机为准"是 user 专属裁决(§2.6/(40) 第七类),worker 自决=洗白反向重演 | **改修复方案措辞**:标注必须成对——"作者预期(设备未证实)+ 预期仍是断言期望值的唯一来源;与实机矛盾走 verifiability/panel 呈报,不得以观察值替换"。eval 断言补:产出期望值仍溯源 intent/manual |
| **E10a** verifiability 增客户端维度 | §0.1(B 层 advisory);needs_decision→questions 链 | advisory 定位合规 ✓。**实在冲突**:新 claim_kind 落 needs_decision 后,questions.build_questions 分支全是 `all(kind==X)` 精确匹配→新 kind **掉 generic"加请求/观测次数"模板**=误导面板(run22 同型,§二 E1) | **改修复方案**:E10a 必须连改 questions.py(新 kind 分支或 FORM_BY_KIND+题面模板),并给混合 claims 一个非 generic 的兜底 |
| **E10b** 序列↔周期自洽机械检查 | §0.1 判据(内容无关数学恒假→L_oracle advisory) | 合规 ✓(纯可满足性判定,advisory 呈报不硬拒)。落点建议:emit advisory+verifiability 双通道之一即可,勿做成 lint 硬门(时序断言的合法弱形态存在) | 通过;实现时守 advisory |
| **F11** 对照差分机械触发 premise-falsified | (47) 执行位阶律/§0.1 语义门禁;GA-CUT 教训 | "同型对照案 PASS∧本案同断言 FAIL"的**同型/同断言判定是内容判断**——做成 disposition 硬改写=语义门(禁);fix plan 措辞"引擎 disposition 增机械触发…不再同向重编"偏硬。另:强制 premise-falsified 会把真缺陷暴露案(变体轴恰是缺陷面)错引出重编流,幸而目的地含 ask/缺陷候选(用户终判),风险=框定而非误杀 | **改修复方案**:降为 advisory 三件套——机械配对产 `premise_conflict` 事实+brief 注入+**强制 panel 呈报**(复用 expectation_suspect 的 panel 必带门),不静默改 disposition;配对判据给可证伪机械定义(同 group_path∧同 F 算子∧同 check 文本),不做模糊相似 |
| **N1** 处置单调律 | vary_form 四查协议(remedies:75-82+briefs:166-173);§11.7 引擎无终结权 | dc→reflow(vary_form) 是**证实步骤不是降级**——单调律若禁 dc 后一切 reflow,四查协议死。517027 实证真缺口在"vary 完成后":varied∧再 fail∧prev dc→仍可自由 churn 到 reflow/env | **改修复方案**:单调律定义在 vary 后——`varied ∧ 同签名再 fail ∧ prev dc` → 机械触发 panel(带 defect 选项,用户终判),禁静默转 reflow/env;与 §11.7 相容(终判仍在人)。同施工面顺修 §二 A(cap 题面呈站立 dc 假设+cap/env 补缺陷出口+stop 不再硬编码 env_blocked,可落 `user_stop` 中性 disposition 或按站立假设分层) |
| **N2** 污染分歧裁决律 | §14-R4 山穷水尽才 ask;既有 contra≥2 通道 | **与既有机制重叠**:533020 全链实证 2 次 delivery 翻转→contra ask 已触发→用户 downgrade 结案——"无限隔离复跑/livelock"不成立(contradictions 按卷面累计,复跑不重置)。真缺口:①contra 题面不呈污染分歧证据(fork h_s0 vs 机械无污染者,用户盲判);②代价=2 轮 delivery 重跑 | **改修复方案**:撤"新增裁决律",改为 contra 题面并呈 diagnosis 分歧(读 `diagnosis.basis=fork candidate…` 与 polluters=[] 的矛盾,一行注入)+可选"存在诊断分歧时 contra 阈值降为 1"(参数,不新增机制)。与 §14-R4 无冲突(仍是批末聚合) |
| **B1'** co-required 文法类型 | §0.1 A 层判据;自愈"零代码"承诺;INV-11 式③ | 协议硬事实(任何值都被拒)→A 层合格 ✓;C7 上机钉死前置已在 plan ✓(572708 两轮两种响应勿写死);"零代码"承诺边界已被 team_gaps 纠正 ✓ | 通过;补一条:新类型加载失败须走既有 `gate_disabled` 显式入账(diagnose 同款),不静默 no-op |
| **D8** worker.md 补分布构造事实 | §3.1 成对簿(checker_tool↔worker.md 设备字段 token);零写死命令红线 | checker_tool docstring 明令"count expectations must come from this tool";worker.md:48 记录过"Hit 前缀重注入=从后门重注入被清理的设备格式"半修实弹 | 通过+施工提醒:D8 文案禁再引入 `Hit:` 字面 token,区间表达一律指到 compile_expected_hits/dist 组合子(现有 :79-99 段已是正确形态,增补跨客户端/双证据面事实即可) |

---

## 五、CLAUDE.md 编译章节陈旧声称表(交文档 owner,均已代码证实)

1. 引擎路径 `main/ist_core/compile_engine/`→实为 `compile_engine_v8/`(目录不存在,D4 已记)。
2. `engine_report.json/engine_ledger.json`→V8 产 engine_report.json+**facts.jsonl**,无 engine_ledger.json(grep 0)。
3. "ledger 迁移合法性表:passed→重编数据层非法"→V8 无 ledger(C3)。
4. "断点续跑…run_marker 幂等"→V8 无 run_marker(C4)。
5. "8 节点三类"→V8 为 **11** 节点(NODE_TYPES/SKILL.md phases 一致)。
6. `_cleanup_temp 清 per-autoid/子集卷…`→V8 closing 为 `_stash delivered/unfinished`+删 manifest/last_run(语义不同:per-case 目录保留供续跑)。
7. "fresh-PASS grade 短路…force_regrade"→grade 已删(07-07),该 bullet 为 V6 fanout 语义残留。
8. 回归锚 `test_final_full_verify_routing.py` 不存在(D4)。
9. `docs/DESIGN_v6_engine.md` 自述"编译只有 V6 一条路"已加历史头(team2 F2)✓,CLAUDE.md 正文对应句仍在。

---

## 六、结论与优先级

**理论/设计骨架经受住了对抗**:INV 族(残差门/全射对账/fail-loud/幂等键/指纹绑定)、问询收敛律、写回-回滚环、broken 三态、平摆契约在代码与两批活数据上均兑现;S1/S2 prompt(两界面/分布区间/同案自查/血统纪律)已落两孔契约。**没兑现的集中在三处**:

- **P0(改代码)**:①C20 缺陷候选单湮灭(attribute 透传+closing 产物+render 对齐)——直接顶撞用户"除设备缺陷外全部输出";②§二 A/B ask 出口修正(cap/env 补缺陷出口+cap 题面呈站立 dc 假设+stop 不硬编码 env_blocked+Other 归并否定门)——与 N1 同施工面一次做掉。
- **P1(改修复方案后再施工)**:A1 迁移条款、A2 绑定 C5+扩状态+生产侧兜底、D9 成对措辞、E10a 连改 questions.py、F11 降 advisory+panel、N2 撤律改题面注入。
- **P2(小改+文档)**:INV-flush 第二问询族(C6/S9)、截断修法推广(§二 C)、S3/S5/S8 收尾窄口、C12 面板新鲜度、C18 死谓词、两处"structurally impossible"措辞限定、CLAUDE.md 九条(§五)。

**一句话**:V8 把"裁决不会被吞"做实了,但把"结论会被完整交出去"想当然了——缺陷单湮灭、物理卷滞留、ask 出口缺位,都是同一个病:**账内闭环强,账到人的最后一跳弱**。修复方案八项里五项需按 §四 修正落点后再动工。
