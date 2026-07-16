# team3 · P0/P1 实现交付 — 甲队(引擎核心面)

> 五项任务(裁决后终版,brief 为准)+ 追加批(接线包 2a-g/K1/K2/normalize 消费点/在途批兼容)全部落地。
> 文件域:`compile_engine_v8/{nodes,uncertain,facts,briefs,render,_shared,views,report_gate}.py` + `fail_attribution.py`(K1 锁,报备)+ 对应测试。
> 回归:`tests/ist_core -q` **1243 passed 零失败**;全量 `--collect-only` **2142 collected 无 ImportError**(含乙/丙队并行改动的工作树;期间两次全量窗口吃到丙实时写 batch_tools 的中间态各挂 1-2 例,单跑全过、复跑全绿,非回归)。
> 全程未 commit;zhaiyq 真机零触碰(未 SSH、未 dev_*、workspace 只读未动)。
> 生成:2026-07-16(追加批同日增补)。

---

## 任务1 · P0-新① 缺陷候选单持久化(C20 湮灭链修复)

**改动**:
- `nodes.py:1539-1543` attribute 收账透传:`_attribution.defect_candidate` 表单(repro/expected_with_source/actual/version/ticket_id)整体抄进 attribution 事实——此前只抄 5 字段,表单唯一落点 last_run.json 被 closing 删除,全 repo 零消费者。
- `nodes.py:2452` `_collect_defect_candidates(fs, vw, manifest)`:目标集=任意轮达 defect_candidate 的案(**N1 floor**:含后轮被弱处置覆盖的,517027 型 r2 主张不再消失),排除最终 deliverable(换形态 PASS 证伪缺陷假设);每案带 claim 全史(`F.strong_claims` 过滤 dc)+ 表单 + 处置轨迹(round×disposition×by_user)。
- `nodes.py:2655`(收集,report 带 `defect_candidates` 键)+ `nodes.py:2742`(双文件产出:`defect_candidates.json` 机读原样 + `defect_candidates.md` 人话渲染,进 deliver_files 走交付对账断言;写在 §11.9 清理与删 last_run 之前;产出失败显式告警不静默)。
- `render.py:298` `render_defect_candidates_md`:判定式渲染零 LLM,表单字段中文标签、轨迹用 DISP_CN 词表、设备证据入 code fence(leak_scan 全过)。
- `render.py`(remedy_text dc 分支 + render_delivery_report 交付物行):文案与产物对齐——"已记入缺陷候选单(`defect_candidates.md`)"不再说谎。

**新事实 kind**:无(attribution 事实增可选字段 `defect_candidate`;report 增 `defect_candidates` 键)。
**测试**(`test_render_closing.py` +3):`test_closing_emits_defect_candidates_files`(两文件在/字段全/deliver_files/报告提及)、`test_defect_candidates_floor_lists_overridden_dc`(dc 被 reflow 覆盖仍列入+轨迹)、`test_no_defect_candidates_no_files`。e2e 端到端见任务5 ⑤。

## 任务2 · A2 换轴入库(观察级判据,theory-challenger 修法)

**改动**:
- `uncertain.py:72-73` 门键换轴:入库器消费 `led.observation_cases()`(aid+语境标签)——不再按 `{failed_terminal, escalated}` 终态枚举(不是加 SUSPENDED 一个枚举值;按终态扩枚举是 §2.7.6 所禁增长方式);旧 led 自动回退(hasattr 兼容)。
- `nodes.py:2425` `_UncertainLed(vw, fs)`:deliverable 排除(走 verified 晋升)、**broken 三态排除**(源窗口失真,(43)——run13 撤销观察前科),其余全入源;案态只翻译成 observed_under 语境(挂起轮/止损收尾轮/升级轮/矛盾轮/fail 轮观察)。`nodes.py:2527` closing 接线。
- `uncertain.py:23` `_normalize_observation`:fact_key 用**归一化内容 hash**(剥时间戳形态 token+折叠空白;不剥语义数字——Hit:0 的 0 是观察身份)——逐字 hash 被跨轮时间戳绕过幂等、纯计数观察组被伪造多语境的洞封死。`_promote_behavior_candidates` 的 fact_key 同步换同源(两路不同源则 uncertain→verified 升级遇不上)。
- `nodes.py:2375` `_attribution_observations`(**绑 C5 生产侧兜底**):无 behavior_candidates 案(777976/593516 型)从 attribution 事实机械转候选——verbatim 判据=evidence 非空≠"user"(submit_attribution 子串门背书);源窗口判据=对应 verdict∈{pass,fail}(broken 轮排除);锚命令=失败断言来源观测步(crash-gate 保证存在;无锚如实 no-op 不猜);dc 表单(actual)全收、普通归因只收最新一轮(信噪)。

**顺手修复(既有 bug,同施工面)**:`_shared.py:310` 补 `env_flag`——V6 迁 V8 漏带,`_promote_behavior_candidates` 首行 `sh.env_flag` AttributeError 被 `_writeback_one` 的 debug-except 静默吞,**PASS 行为知识晋升自 V8 迁移起从未生效**;现恢复。

**测试**(`test_self_healing_loop.py` +5,_StubLedger 换轴改造,既有 6 例保绿):`test_suspended_case_observations_ingested`(挂起案入库+语境)、`test_attribution_observation_fallback_no_candidates`(无候选案经兜底通道入)、`test_timestamp_variant_dedup`(时戳变体同键)、`test_uncertain_led_axis_and_attribution_observations`(排除集+锚+broken/user 排除)、`test_promote_env_flag_regression`(bug 回归锚)。

## 任务5 · N1 替代(claim 级证据粘性 + user_stop 本体分离)

**改动**:
- `facts.py:213-216` `STRONG_DISPOSITIONS` + `strong_claims(facts, aid)`:强处置 claim 历史([主张,证据] 对,claim 级粒度;evidence=="user" 记账行不算 claim;同 claim 跨轮幂等)。消费端读法——事实流 append-only 本就保留,brief/题面/缺陷单由此取全史。
- `nodes.py:1481` attribute fork env 注入 `strong_claims`(必须消费事实:逐条 adopt/refute/声明不适用;"修复另一条 claim 不构成对本条的反驳")。
- `nodes.py:1552` 收账时历史强 claim 在场∧本轮弱处置∧非用户源 → 落 `strong_claim_unaddressed` 审计事实(不硬拒——换形态检验轮属 dc 处置组成部分,硬单调会封锁推翻误判所需的实验,044572 实证;守 dongkl 定稿 §0 摆事实不替判)。
- `nodes.py:2237` stop/downgrade:独立 **`user_stop` 事实**(键名冻结,乙队 questions 侧消费)+ attribution 记账行加 `user_stop:true` 标记。**路由零变化**(views._user_sourced/S_TERMINAL/report_gate 照读 env_blocked@99)——生命周期记账与语义归因字段分开,下批检索/统计可分辨。
- `render.py:114` `_latest_semantic_attribution`(diagnosis_text 换用):跳过 user_stop 记账行——517027 型"怎么判断的"显示站立缺陷主张,不再显示"环境/测试床问题"假语义;`render.py:192` remedy_text:user_stop 在场说"按你的止损裁决收尾"(不说环境),历史达 dc 的指到缺陷候选单。旧事实(无标记)走旧文案,向后兼容。

**新事实 kind**:`user_stop`(冻结)、`strong_claim_unaddressed`;attribution 事实增可选布尔 `user_stop`。
**测试**(新 `test_claim_stickiness.py`,7 例):strong_claims 三单元(517027 形态全史/user 源排除/幂等)、render 三单元(diagnosis 跳记账行/remedy 止损措辞+dc 指引/旧事实兼容)、**e2e `test_e2e_claim_stickiness_and_user_stop`**(cap→"停止该案"全链:①收账透传表单 ②第二轮 env 携 strong_claims ③unaddressed 落账 ④user_stop 分离+failed_terminal 路由不变 ⑤floor 单含被覆盖 dc+轨迹 ⑥sibling_contrast 注入+落账)。

## 任务4 · F11 降级版(sibling_contrast advisory 事实注入)

**改动**:
- `nodes.py:1301` `_sibling_contrast`:manifest 同 group_path 兄弟按视图状态分裂 `{passed:[{aid_tail,title}], failed:[…]}`(各[:12] 配额;**键名 `sibling_contrast` 冻结**,乙队题面读同键);note 明示"哪条前提被证伪是你的判断,非机械裁决"——不机械改 disposition((47) 路由红线)。
- `nodes.py:1278` `_pass_is_vacuous`(**(44) 断言级非空真前置**):对照 PASS 案回读其 pass verdict 的 evidence_ref 记录,`anomaly_lines`/`window_distortion` 非空即剔除(778012 三连假过——空真 PASS 当机械证伪证据=拿假证据翻真案);记录读不到保守判 vacuous(无凭据 PASS 不作对照)。digest 层 07-14 起 anomaly-pass 已降 broken,本门对新批幂等冗余、对历史批/旧 client 兜底。
- `nodes.py:1492` env 注入 + 落 `sibling_contrast` 事实(passed/failed/advisory 布尔,run_id 幂等);**advisory**:frozen(2 轮同签名)∧ 非空真对照 PASS 在场 → 禁第三轮同向重编的建议写进 env(prefer expectation_suspect/defect_candidate/换证据面),由 attributor 判。
- 开关 `IST_SIBLING_CONTRAST_INJECT`(默认 1;关=不注入不落事实)。

**新事实 kind**:`sibling_contrast`。
**测试**(新 `test_attribute_contrast.py`,6 例):同组分裂+异组排除、vacuous 剔除、无记录保守判、frozen+对照→advisory、开关关、无组不构造。e2e 见任务5 ⑥。

## 任务3 · D9 brief 注入去事实化

**改动**(`briefs.py:71/80-84/191-197`,开关 `IST_BRIEF_HYPOTHESIS_MARKUP` 默认 1):
- 归因侧:`attribution="{sig}" status="hypothesis"` + `<fix_direction confidence="hypothesis" note="prior-round attribution — a hypothesis to re-verify against this round's echo, not established fact">`(re-verify 非 distrust,正确归因定向价值保留);`[:800]` 截断与响度降级布局不动。
- 意图侧成对措辞(防单标"未证实"滑向 worker 自决改预期):`expected:` 是 author's anticipated outcome not device-verified(须 ground)∧ intent 仍是断言期望值 sole source——与实机矛盾走 verifiability/panel 呈报,never silently replace with observed value。
- `<user_adjudication>` 权威措辞零改动(highest authority 保持)。`attribution="` XML 属性 grep 全 repo 零机读方(规格卡质疑③实证解除)。

**测试**(`test_briefs.py` +4,既有 10 例含布局门保绿):`test_fix_direction_marked_hypothesis`、`test_intent_note_marks_expected_as_author_claim`、`test_user_adjudication_stays_authoritative`(防连带弱化)、`test_hypothesis_markup_switch_off`。

---

## 追加批(team-lead 指令,同日)

### 接线包 2a-g(乙队 §三,与 user_stop facts 同批落地)

- **2a** `nodes.py`(import 区):`_answer_token` 删本地实现→委托 `questions.answer_token`(import-as 绑定模块属性,`N._answer_token` 直调路径不断)。
- **2b** stop/downgrade 落账(`nodes.py:2246-2261`,契约终版):env 题面 → `{layer:"E", disposition:"env_blocked"}`(选项原文即「确认环境问题」,语义如实);**其余题面** → `{layer:"user", disposition:"user_stop"}`(值冻结)+ 独立 `user_stop` 事实。乙文档草案的 `Q.stop_accounting` 在其终版代码不存在(注释declared 留甲侧)——语义 inline 实现,行为与契约逐字一致。
- **2c** 终态元组:`views.py:85-89` + `report_gate.py:41-44` 加 `"user_stop"`(S_TERMINAL 投影不丢,乙实测警告解除)。
- **2d** `render.py`:`DISP_CN["user_stop"]`=「按你的裁决停止(未通过如实报告)」、`LAYER_CN["user"]`=「用户裁决」(leak_scan denylist 自动收编);remedy_text 契约分支(`disp=="user_stop"`→止损措辞+dc 单指引;`env_blocked@99` 旧文案原样=在途批渲染不变);`_latest_semantic_attribution` 判据= disposition 契约形态+过渡布尔双兼容。
- **2e** `nodes.py`(ask item 组装):cap/env 注入 `claim_history`=[{round,layer,disposition,claim,evidence}](r99 生命周期行不入;键名冻结,乙 `_claim_history_line` 消费)。
- **2f** `nodes.py`:diagnose 不升格分支落 `s0_dispute` 事实({fork_h,mech,run_id} 幂等;判定不变,既有锁测继续绿并增③断言);contra/cap item 注入 `s0_dispute={count}`(pre/post_dirty 有数据源后同键补入)。
- **2g** `_shared.granted_rounds` 认 cap-correct(+2);`briefs.py` 注入 cap-correct 用户纠正原文(`<user_adjudication>` 样板,panel 裁决在场不重复)——cap-correct 从「落账可见永不行动」修成有效路径。
- `test_ask_panel.py` cap 四选项断言乙已同步。

### K1 归因并发化 + K2 编写池接通 env(纯并行/配置,零流程语义)

- **K1**(`nodes.py` attribute):裸 for 串行(36 fork 并发=1,zhaiyq 128min/dongkl 120min)→ prepare 段保持串行(事实 append/attr_evidence 落盘/env 组装零共享写),`ThreadPoolExecutor(_fanout_pool_size)` 只跑 `_call_fork`——与编写 fanout 完全对称(`ex.map` 同款,ForkExecutor.call 本不含限流获取,worker 现状即池尺寸限并发)。**安全前提**:`fail_attribution.py` 加模块级 `_LAST_RUN_LOCK`,`submit_attribution` 读改写整段持锁(锁外读锁内写会把并发同伴刚落的归因覆盖回旧快照);两处测试 rig 假体同持真锁(测试密闭)。
- **K2**(`nodes._fanout_pool_size`):`IST_FANOUT_CONCURRENCY` 真接到池尺寸(此前只喂 limiter,编写池硬编码 min(8,n) 配置不生效);默认 8 行为零变化;编写/归因两池共用。
- 测试:`test_k_perf_and_seams.py` — `test_submit_attribution_concurrent_no_loss`(8 线程同文件 8 条归因全在)、`test_fanout_pool_size_env`(env=16→16/默认 8/坏值回退)。

### A1 接缝:normalize_fail_signature 消费点(存量签名跨格式交集)

- `facts.py` `_norm_sigs`(惰性 import+恒等回退)——`frozen` 交集两侧归一(facts.py:169 原锚);`nodes._cross_bed_refuted` 同(1722-28 原锚)。旧格式 `` p2 in: xxx.txt`` 与新格式 ``p2`` 归一后可交集,冻结/跨床反驳跨界轮不静默失效。
- 测试:`test_frozen_intersects_across_signature_formats`(含反例:真不同签名不产假交集)、`test_cross_bed_refuted_normalizes_stored_signatures`。

## 在途批兼容性自证(zhaiyq 续跑收口硬要求)

| 要求 | 自证 |
|---|---|
| ①新事实 kind 只增不改既有行语义 | 新 kind=`user_stop`/`strong_claim_unaddressed`/`sibling_contrast`/`s0_dispute`(全部新增);attribution 事实新增**可选**字段(defect_candidate);唯一新 disposition 值 `user_stop` 只由新代码写出,旧行(env_blocked@99)语义/路由/渲染逐字保持(`test_remedy_legacy_env_blocked_wording_unchanged`) |
| ②facts 读取器容忍旧行 | 全部消费点 `.get()` 容忍缺字段;`idem_key` 对新 kind 走内容键(前向兼容既有分支);`_latest_semantic_attribution` 对无标记旧行为恒等;`_norm_sigs` 对新格式幂等、import 失败恒等回退 |
| ③缺陷单对老 run 工作 | `_collect_defect_candidates(last_run=…)`:老代码收账的 dc 行无表单字段 → closing 从盘上 last_run.json(删除前)回读 `_attribution.defect_candidate` 补齐——**532862 续跑收口即此路径**;测试 `test_defect_candidates_backfills_form_from_legacy_last_run`(无 last_run 时案仍列、form 如实 None 不丢案) |
| ④checkpoint 恢复不断 | `state.py` 零改动;state 既有键零增删改(K1/K2/接线全部经函数与事实流);graph 拓扑零变化;续跑同参重入 checkpoint 的节点序不变 |

## 通用性自证(机制零领域知识;领域词全量清单)

配对/判据全部**结构级**:F11 `sibling_contrast` 配对键=manifest `group_path`(脑图结构)+视图状态+(44) 协议信号(anomaly_lines/window_distortion),**零关键字匹配**;A2 观察级判据=源窗口(verdict result 闭集)∧ verbatim(工具门背书),零领域词;`_attribution_observations` 锚提取读 E/F 列**框架结构词**(check_point/config——xlsx 列方法闭集,非设备领域词)。改动中出现的全部领域词归类:

| 领域词 | 出现处 | 类别 |
|---|---|---|
| sdns/show sdns host status/Timeout=0/IPv6/会话保持/AAAA/dig | 测试文件(claim_stickiness/attribute_contrast/self_healing/k_perf/render_closing 夹具) | **测试夹具数据**(断言的是机制行为,夹具可换任意域) |
| 「配置形态见该批取证」等 observed_under 兜底句 | uncertain.py/_UncertainLed._CTX | **用户面中文文案**(语言分层既定例外,无判定作用) |
| repro/expected_with_source/actual/version/ticket_id | _collect/render | **工具契约字段名**(submit_attribution 既有 schema 引用,非领域判定) |
| 缺陷单 md 中文标签(复现步骤/预期…) | render_defect_candidates_md | 用户面模板内容(既定例外) |

机制代码(nodes/facts/uncertain/briefs 判定路径)grep 无一条设备命令、无一个协议/功能关键字参与判定。

## 理论/设计符合性(逐项锚点;fix_plan §编号待 H14 固化)

| 改动 | 理论/设计锚 |
|---|---|
| 任务1 缺陷单持久化 | 设计挑战 **C20** 裁决三件套(attribute 透传+closing 产物+render 对齐);DESIGN **§11.7 telos**(唯一合法非 excel 结局=缺陷候选,必须单独输出);THEORY **§2.12.4** 回流弧的交付侧前置(候选单是 confirmed/wontfix 回流的输入);fix_plan P0-新① |
| 任务2 A2′ 换轴 | THEORY 回炉 **§五-2 A2′** 逐字(观察级判据/broken 排除((43))/归一化幂等/成立域限定);**§2.7.6**(按终态枚举=被禁增长方式);**(47)** L_model 前提(判例层唯一可达通道);C5 绑定=fix_plan §五.3 验收 |
| 任务5 N1a/N1b | THEORY 回炉 **§五-2 N1a/N1b** 逐字(字段分离/claim 级粘性/静默消失落账不硬拒);**(36)** 写权律(用户止损=生命周期记账,归对通路);**(40)** 增补(跨轮处置一致性=写而无读者的 `_prev_attribution` 半程补全);dongkl 定稿 **§0**(摆事实+自查,不加机械门替判) |
| 任务4 F11′ | THEORY 回炉 **§五-2 F11′** 逐字(事实注入非结论,(37)①;窗口审计前置,(44) 边界;排在域分诊后);**(47)** 执行位阶(同型判定内容依赖→L_model,机械只到证据装配);GA-CUT 教训(A/B 分界) |
| 任务3 D9 | 规格卡 D9+设计挑战 **§四 D9** 成对措辞裁决(单标"未证实"→worker 自决改预期=红线9 observe-then-assert 反向重演);**(45b)** 机生不盖人源(user_adjudication 权威不动) |
| user_stop 契约(2b/2c/2d) | THEORY 回炉 **§2.2 进攻二**(r99 env_blocked 三例=两类本体混用一字段,一手数据钉死);N1a;team-lead 契约冻结 |
| claim_history/s0_dispute 注入(2e/2f) | 乙队 §一-1d/2(517027 题面 churn 失忆;N2′ 分歧语境=(46) 三元组的证据分量);规格卡 N2①② |
| cap-correct 闭环(2g) | 乙队 §三-2g(「落账可见但不行动」→有效路径;(41)③ 消化保真的行动侧补全) |
| K1/K2 | worker fanout 并行既有设计的**对称延伸**(两孔同为 fork 派发,无理由一个并行一个串行;team3_perf_audit 实证+team-lead 指令);零流程语义(prepare/收账时序不变) |
| normalize 消费点 | 规格卡 **§四 A1 冲突裁决**(五处交集比较的迁移条款——存量字段侧归一,防跨界轮冻结静默失效) |
| env_flag bug 修 | 自愈环既有设计恢复(uncertain→verified 晋升是 CLAUDE.md 记载的两段闸第二段,非新机制) |

## 跑数汇总

| 套件 | 结果 |
|---|---|
| `tests/ist_core -q`(全量,终数,三队全部完工后) | **1243 passed, 0 failed**(80s) |
| `pytest tests/ --collect-only -q` | **2144 collected, 0 ImportError** |
| 本队新增/改造测试 | +33(claim_stickiness 7、attribute_contrast 6、k_perf_and_seams 7、self_healing +5、render_closing +3、briefs +4、diagnose +1 断言) |
| 直接邻域保绿 | v8 全目录 347 / self_healing 11 / fail_attribution 7(锁重构后) |

## 接缝确认(冻结键名,乙队消费)

- `sibling_contrast`:attribute fork env 键 + 同名事实 kind,结构 `{passed:[{aid_tail,title}], failed:[…], note, advisory?}`。
- `user_stop`:独立事实 kind(`{ev, aid, question_id, answer, token}`)+ attribution 事实可选布尔字段 `user_stop`;facts 结构已承载,questions 侧记账语义乙队接。
- 与任务1同源字段:attribution 事实的 `defect_candidate`(dict:repro/expected_with_source/actual/version/ticket_id)、`evidence`/`fix_direction`——A2 兜底通道与缺陷单同源消费。

## 环境开关(全部默认开/新增)

`IST_SIBLING_CONTRAST_INJECT=1`、`IST_BRIEF_HYPOTHESIS_MARKUP=1`;总闸 `FOOTPRINT_UNCERTAIN_WRITEBACK` 语义不变(经新 `sh.env_flag` 读取)。

## 额外发现(既有 bug,已修)

`sh.env_flag` V6→V8 迁移漏带:`_promote_behavior_candidates`(PASS 行为知识晋升,writeback 三连第三件)首行 AttributeError 被 debug-except 静默吞——**自 V8 切换起从未生效**,footprint 行为知识只出不进(uncertain 入库在、verified 晋升断)。已在 `_shared.py:310` 补齐并加回归锚 `test_promote_env_flag_regression`。

*team3 甲队 · 2026-07-16 · 未 commit(工作树交 team-lead 统一收口)*
