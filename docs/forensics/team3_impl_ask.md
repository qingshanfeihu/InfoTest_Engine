# team3 · 实现交付 — 乙队:ask 面板语义面(questions.py)

> 角色:P0/P1 实现队·乙。独占文件:`main/ist_core/compile_engine_v8/questions.py` + 其测试。
> 本轮写入面:questions.py(重写收编)、新增 `tests/ist_core/compile_engine_v8/test_questions_ask_semantics.py`、
> **授权接线**(团队长裁决 2026-07-16):engine_tool.py 一行委托 + test_ask_panel.py 断言更新。
> 未越界:nodes/uncertain/facts/briefs/render(甲)、batch_tools/verifiability/domain_grammar/worker.md(丙)零字节改动。
> 回归:`tests/ist_core -q` 全绿(接线前基线 1205 passed;接线后 ask 通道相邻+甲队粘性测试 53 passed,收尾另附全量数)。
> 生成:2026-07-16(裁决后终版)。

---

## 零、一句话

第二问询族(panel/cap/env/bed/contra/suspended)的**题面组装与 Other 意图归类**收编进 questions.py 成为 ask 面板语义单一事实源;517027 三重缺陷(cap/env 无缺陷出口、Other 恒 continue、题面 churn 失忆)+ 无痕硬截全部修复并已接线生效;止损记账如实化由甲队以 user_stop 事件分离形态落地(本队退役重复方案,单一事实源);在途批(zhaiyq)续跑兼容以真实三案数据渲染样张自证。

## 一、完成项 × 任务映射

| 任务 | 落点 | 测试锚 |
|---|---|---|
| **1a cap/env 补「确认产品缺陷」选项** | `build_ask_question`:cap 4 选项(继续/缺陷/挂起/停止,恰在 ask_user 2-4 硬限内)、env 3 选项;token=`defect` 复用 panel 面板既有缺陷臂——nodes defect 落账分支(product_defect/defect_candidate/r99/evidence=user)已存在,**自动对齐甲队缺陷候选单**(同 disposition 键);零新 token,`_TOKEN_CN` 零改动。**已接线生效** | `test_cap_panel_offers_defect_exit` / `test_env_panel_offers_defect_exit`;test_ask_panel 旧断言更新为 4 选项 |
| **1b stop 记账如实** | **甲队落地(冻结契约终态,nodes 内联)**:非 env 题面 stop/downgrade → r99 attribution `{layer:"user", disposition:"user_stop"}` + 独立 `ev:"user_stop"` 事实(question_id/answer/token);env 题面 → env_blocked 如实保留(选项原文即「确认环境问题」);views:86/report_gate:41 终态元组已扩 `user_stop`,render 语义归因跳记账行。演化注:甲曾短暂以 marker 形态(attribution 留 env_blocked+`user_stop:true`)过渡,终版收敛回冻结契约;乙曾输出 `stop_accounting()` 同契约函数,甲选择内联后乙已移除(单一事实源在 nodes)。题面侧成对承诺=「停止该案」选项文案:「记为你的停止裁决,不覆盖在案技术判断」 | 甲:`test_claim_stickiness.py`(含 e2e ④ N1a 契约断言+旧事实向后兼容);乙:`test_stop_option_declares_bookkeeping_semantics` |
| **1c cap Other 意图归类** | `answer_token`:缺陷意图带否定门(`_NEG_DEFECT_RE`,「不是缺陷,继续修」不误归)在 panel/cap/env/bed/contra 一律→defect;cap 桶=纠正词→correct/继续词→continue/停修词→stop/其余→correct(**绝不虚假授权轮次**);env「提缺陷单」不再恒 retry。既有语义(特权词短指令、bed/suspended/contra 缺省)逐条保持。**接线待甲**(nodes `_answer_token` 别名一行,diff 见 §三-2a) | `test_cap_other_defect_intent_not_merged_to_continue` / `_negated_defect` / `_intent_buckets` / `test_answer_token_privilege_and_kind_defaults_unchanged` |
| **1d 题面呈现 claim 历史** | `_claim_history_line`:cap/env 题面逐轮渲染「第N轮:处置人话——『主张』」(≤4 轮+更早略计数),churn 不吞早轮假设;缺陷选项文案援引在案假设轮次;`_DISP_CN` 全中文,未知键兜底「其他判断」。**渲染已接线生效;数据组装待甲 2e** | `test_cap_question_shows_full_claim_history_not_only_last` / `test_env_question_shows_claim_history_when_present` / `test_claim_history_unknown_disposition_stays_chinese`;真实样张 §六 |
| **2 N2 替代(撤新 ask 臂)** | `_s0_dispute_note`:分歧语境注入**既有** contra/cap 题面——「编写侧 N 次判起点被残留污染 vs 机械配对未找到污染者(两者口径不同)+隔离复跑通过不代表整卷会过」;床态快照按分辨实验三分渲染(跑前脏=受害者/跑后脏=自污染/两头净=偶发或取证失真)。零新面板类型、零新 token、无 IST_S0_DISPUTE_ASK,contra≥2 兜底与选项原样不动。**渲染已接线;数据投影待甲 2f** | `test_contra_question_carries_s0_dispute_context` / `_snapshot_victim_form` / `_snapshot_self_pollution_form` / `test_contra_without_dispute_no_injected_line` / `test_cap_question_carries_s0_dispute_context_too` |
| **3 E10a 题面模板** | `build_questions` 新分支 `all(k=="cross_client_landing")`:专用题面+三选项(改过程=同客户端关系断言/分组分布区间;改预期=用户给手册/判例依据按确定性映射;改描述=挂起);`FORM_BY_KIND` 映射 `captured_relation`。键名与丙队落地代码实读对齐(verifiability.py:44)。同族病根顺修:**通用兜底重组**——「加请求/观测次数」只在确有采样类主张时出现,混合 claim 两侧建议并陈,纯采样类文案与旧版逐字等同 | `test_cross_client_landing_gets_dedicated_template_not_generic` / `test_mixed_claims_compose_not_sampling_only` / `test_non_sampling_claim_no_misleading_sampling_advice` / `test_pure_sampling_claim_keeps_legacy_wording` |
| **4 题面质量硬化** | `clip_text` 句读摘要:整句累加到 cap、放不下丢弃并「…」留痕,首句即超长退回定长截断仍带「…」——**截断永远可见**;第二问询族全部裸 `[:N]` 换 clip_text;panel sides 引文保持 [:300] 窗口与 briefs 同宽(verbatim 契约),超窗加「…」标记;选项文案从案情事实拼装 | `test_clip_text_*`×3 / `test_cap_evidence_no_silent_midword_cut` / `test_new_render_paths_no_internal_terms_leak` |

欠定通道既有五分支(清理/三元组/禁令/存在性/纯采样通用)措辞逐字保留;`validate_questions`/`load_ledgers`/`_first_clause`/`DECISIONS` 契约不变。

## 二、接缝键名清单(冻结终态)

| 键 | 形态 | 产方→耗方 | 状态 |
|---|---|---|---|
| `user_stop` | **冻结契约终态(甲 nodes 内联)**:非 env 止损 → r99 attribution `{layer:"user",disposition:"user_stop"}` + 独立 `ev:"user_stop"` 事实;env 止损 → env_blocked 如实;views:86/report_gate:41 元组含 user_stop;乙 `_DISP_CN` 备词条 | 甲 nodes → 甲 views/render/报告 + 下批检索;乙题面词条 | **已按冻结契约落地收敛**(中途 marker 过渡形态已被甲替换) |
| `claim_history` | case dict 键=`[{round,layer,disposition,claim,evidence}]`(r99 记账行不入);渲染容忍缺键/缺字段(claim 缺回落 fix_direction) | 甲 nodes 2e → 乙 `_claim_history_line` | 键名冻结;甲组装待落(§三-2e),旧 facts 行字段实证齐全(§六) |
| `s0_dispute` | case dict 键=`{count:int, pre_dirty?:[str], post_dirty?:[str]}`(diff 键可缺省=不渲染快照行) | 甲 nodes 2f → 乙 `_s0_dispute_note` | 键名冻结;甲投影待落(依赖其 N2① s0_dispute 事实) |
| `cross_client_landing` | needs_decision claim_kind 值;`_form="captured_relation"` | 丙 verifiability → 乙 build_questions | **已对齐**(双方落地代码实读一致) |
| `defect` token(cap/env 新臂) | 复用既有 token;落账=nodes 既有 defect 分支+甲队缺陷候选单 | 乙题面 → 甲落账 | **已接线生效**(题面已上线,落账分支既有) |

## 三、接线包(状态更新)

| # | 内容 | 归属 | 状态 |
|---|---|---|---|
| 1 | engine_tool.py `_SHAPE_CN/_RECEIPT_CN/_QUOTE_CLIP/_side_cn/_contradiction_question`(150 行)→ 一行委托 `from …questions import build_ask_question as _contradiction_question` | 乙(团队长授权) | **✅ 已应用**(-150/+5;5 个测试文件的 `ET._contradiction_question` 直调路径经 import-as 不断) |
| 2a | nodes.py `_answer_token`(:1629-1667)删除,顶部 import 区加一行:<br>`from main.ist_core.compile_engine_v8.questions import answer_token as _answer_token`<br>(test_ask_panel:339-344 / test_tau_coverage_gate:150 直调 `N._answer_token` 经模块属性不断;行为差异=Other 意图归类修复,等价锚已由乙 `test_answer_token_privilege_and_kind_defaults_unchanged` 先行钉死) | 甲(团队长转交) | **✅ 甲已落**(nodes:27 别名,旧函数已删——1c 端到端生效) |
| ~~2b/2c/2d~~ | ~~stop 落账分支/views:85/report_gate:41 终态元组/render 人话表~~ | — | **撤销**:甲队 user_stop 标记方案免去全部三项(元组零改动) |
| 2e | cap/env item 组装注入 `claim_history`(r99 行过滤;字段=round/layer/disposition/claim←user_note∨fix_direction[:400]/evidence[:200]) | 甲 | ⏳ 待甲(1d 活体生效前置;降级渲染已兜底) |
| 2f | contra/cap item 注入 `s0_dispute={count}`(自其 N2① 事实;快照 pre_dirty/post_dirty 有数据源后同键补入) | 甲 | ⏳ 待甲 |
| 2g | cap-correct 配套:`_shared.granted_rounds` 认 cap-correct(+2)+ briefs 注入 cap 纠正原文(样板=panel `<user_adjudication>` 块)。未接期间 correct 决策如实落账+G4 echo 可见但不重编(诚实降级,无假授权) | 甲 | ⏳ 待甲(团队长广播已列) |
| 3 | test_ask_panel.py:217 cap 选项断言 3→4 + docstring 更新 | 乙(授权) | **✅ 已应用** |

## 四、理论/设计符合性(逐项引锚)

| 改动 | 理论/设计锚点 | 符合性说明 |
|---|---|---|
| cap/env 缺陷臂(1a) | THEORY §2「目标函数与终态」(唯一非通过正当终态=缺陷候选)+ (40) 处置分类学(七类出口满射,用户终判缺陷不可缺位)+ §11.7(缺陷确认权在人);design_challenge §二 A-2(代码坐实缺陷出口只存在于 panel 类)与 §四 N1 行「cap/env 补缺陷出口」 | 面板给出口、终判仍在人(选项而非默认);token 复用既有 defect 落账=零新机制,(36) 用户源写带锚带账既有路径 |
| user_stop 记账(1b) | theory_challenge §2.2 进攻二(r99 env_blocked 全是用户停批记账——两类本体混用一字段,一手数据钉死)+ §五-2 **N1a 台账本体论**(生命周期终局落独立事件类型/字段,不得覆写语义归因);C13(round=99 止损信号伪造不了) | 甲队落地即 N1a 教科书形态:独立事件类型 + 标记字段,语义归因(render `_latest_attribution` 跳记账行)不再被假环境语义覆盖;路由零变化守住 §11.7 三权分立 |
| Other 意图归类(1c) | design_challenge §二 B(token 强制归并机理 + 裁决「Other 归并加否定门」)+ (41) 问询链保真④提交保真(G4 echo 已在,归并是链上最后失真点)+ (26)(用户意图被强塞≈答案失真) | 否定门+意图桶取代题面剧本硬归并;fallback=correct(原文落账)而非 continue(授权行为),失真方向从「替用户行动」变为「保留原文待消费」 |
| claim 历史呈现(1d) | theory_challenge §五-2 **N1b claim 级证据粘性**(强处置 claim 机械保留并注入为必须消费事实——本项即其**用户侧消费面**)+ (46) 问询三元组(没推导没资格问;cap 题面只显 churn 后单轮=第三分量失真)+ design_challenge §二 A-1(`atts[-1].fix_direction` 机理定位) | 题面=render(全轮归因事实),与 briefs 注入(甲 N1b worker 侧)成对——同一份粘性数据两个消费面;渲染零自由度(逐轮逐字+句读摘要),同 (42) 报告保真形态 |
| N2 替代(2) | theory_challenge §2.3(污染归属是实然,(19)/(26) 判分歧时 ask 非法→**裁决删 ask 臂**)+ §五-2 N2′(呈报须携已二分证据;快照三分=§3.2 分辨实验的用户可见半)+ design_challenge §四 N2(真缺口=contra 题面不呈污染分歧证据,533020 用户被盲问) | 不新增裁决律、不新增面板/token/开关;仅把分歧证据注入既有 contra≥2 兜底题面——「让用户看全再选」,发问资格按 (46) 补齐第三分量 |
| E10a 题面(3) | p0p1_specs 卡 E10a(「必须连改 questions.py 新 kind 分支+题面模板,并给混合 claims 非 generic 兜底」为采纳条件)+ design_challenge §二 E-1(`all(k==X)` 精确匹配掉 generic 的机理,run22 同型)+ (47)/§0.1(L_oracle-B advisory:题面呈欠定事实+可验等价,不硬判) | 专用分支+混合重组双管齐下;可验等价(关系断言/分组区间)进选项而非硬改写,终判在用户;「按客户端分组」与丙队 verifiability notes 同口径 |
| clip_text 硬化(4) | design_challenge §二 C(第二问询族全是裸 `[:N]` 双层截断、无省略号词中断——zhaiyq 实弹定位;修法=「_first_clause 推广到第二问询族」)+ §18.14 D2 既有先例 + (41) 题面失真=问询链失真 | 句读摘要+必带留痕;panel sides 保持 [:300] 窗口与 briefs 同宽(「题面与 briefs 同一事实面」注释契约),只加显示标记不改窗口 |
| 收编单一事实源 | CLAUDE.md 三层栈判定表(确定性流程→py 纯函数)+ (42) 报告保真同型(题面=render(案情事实),零自由度)+ (46) 消费点(questions.py 本就是三元组题面渲染地) | 题面组装从工具壳(engine_tool)归位到题面模块;engine_tool 余留纯桥接(interrupt→面板→答案对位) |

## 五、验收四标准自查(全 13 模板:欠定 6 + 矛盾 7)

1. **自然语言可懂**:零内部术语——既有 leak 测试(五 kind)+ 新路径 leak 测试(cap×历史×分歧,词表增补 user_stop/defect_candidate/h_s0/s0_dispute/claim_history);处置人话表未知键兜底中文;引文(『』/「」内)保留原始记录本貌,题面框架全中文。
2. **不前后矛盾**:claim 历史逐轮全呈现,「缺陷已修复」叙事与站立假设并陈(§六样张一即 517027 实弹反例的正面);s0 分歧双方口径差异写明;既往选择/已试修法照旧在题面。
3. **选项真实有效**:label→token 引擎同源 `_tokens` 映射,全部 ∈ `_TOKEN_CN` 既有语义集;缺陷臂直通既有落账+缺陷候选单;缺陷选项援引在案假设轮次(无假设时用通用如实文案);停止选项声明记账语义(与甲队 render 跳记账行为成对)。
4. **不提供虚假问题**:题面素材全部来自案情事实键;无凭空选项;Other 归类修复后剧本外意图不再被强塞;缺陷意图带否定门。

## 六、在途批兼容性(硬要求自证;样张=zhaiyq 真实 facts 只读渲染)

**背景**:zhaiyq 进程被外因杀死未收口,将以新代码从 checkpoint 续跑。续跑重弹面板的两条路径都已覆盖:

- **路径 A(checkpoint 挂旧 interrupt payload)**:旧 case dict **无新键**(claim_history/s0_dispute)→ 本文件全部新键 fail-open,渲染降级到现行为(样张「降级版」),不崩不空。测试锚:`test_cap_without_history_keeps_evidence_line`、`test_contra_without_dispute_no_injected_line`。
- **路径 B(节点重跑重建 payload)**:甲 2e/2f 落地后,组装直接吃**旧格式 attribution 行**——zhaiyq 三案实测字段(round/layer/disposition/fix_direction/evidence)齐全,r99 记账行被组装过滤(样张「接线后」即以旧行直出)。
- **旧 r99 行兼容**:zhaiyq 存量 env_blocked r99 行无 `user_stop` 标记 → 甲队 render 走旧文案(其 `test_claim_stickiness.py::…backward` 锁);claim_history 组装本就排除 r99,乙侧零影响。
- **已答不重问**:517027/600046 已停案的 cap decision(question_id 键控)在续跑中不重弹(既有收敛律),不受本轮影响。
- **活体验收点**:532862 挂起案新批恢复问询(样张三);其恢复后再触发 cap 面板时,缺陷臂/claim 历史/停止语义即本轮修复的正面——Other 新归类生效依赖 §三-2a(甲)。

### 样张(2026-07-16 以 `workspace/outputs/zhaiyq/facts.jsonl` 三案原始行渲染,只读)

**样张一 · 517027(配置AAAA类型的会话保持,使用ipv4访问)— cap·接线后**
> 题面:用例 …517027(配置AAAA类型的会话保持,使用ipv4访问) 已重编 3 轮仍未通过,引擎多轮未收敛。各轮判断:第1轮:疑似产品缺陷——「SDNS不返回AAAA记录: dig @172.16.34.70 www.zyq.com AAAA +short 返回空,show sdns session persistence…」;第2轮:疑似产品缺陷——「SDNS session persistence expired entries (Timeout=0) should be removed from show sdns sess…」;第3轮:判用例侧可修——「Round 1的缺陷(SDNS不返回AAAA记录)在round 2已修复——编译器现在使用IPv6 service IP(fc00::231/fc00::225)替代IPv4(17…」。如何处理?
> 选项:[继续,再修 2 轮]授权追加重编轮次/[确认产品缺陷]实机行为是产品问题(在案第 1、2 轮曾判疑似产品缺陷,见上)——记入缺陷候选单,该用例以缺陷结案/[挂起该案]…/[停止该案]以未通过如实报告,不再消耗轮次(记为你的停止裁决,不覆盖在案技术判断)
>
> **四标准**:r2「Timeout=0」假设在场(实弹病灶正面修复✓);r3「已修复」叙事与 r1/r2 假设并陈不再自相矛盾✓;缺陷选项援引第 1、2 轮(r3 是 reflow 不援引,与案情精确一致)✓;所有素材出自该案 attribution 原文✓。

**样张一b · 517027 — cap·降级版(无新字段=续跑路径 A)**
> 题面:…已重编 3 轮仍未通过,引擎多轮未收敛(最近的修法方向:Round 1的缺陷(SDNS不返回AAAA记录)在round 2已修复——…会话保持条目正常创建…)。如何处理?
> 选项:同上四项(缺陷臂在,援引轮次注省略——无历史数据不虚构)。
> **兼容性**:不崩不空,信息面=旧行为+缺陷出口;「…」留痕替代旧版无痕硬截。

**样张二 · 532862(配置AAAA类型的会话保持,使用ipv6访问)— cap·接线后**
> 各轮判断:第1轮:疑似产品缺陷——「SDNS不返回AAAA记录: dig @3ffb::70…」;第2轮:疑似产品缺陷——「…entries should be removed…」;第3轮:疑似产品缺陷——「设备应清理超时后的IPv6 SDNS会话保持条目(与IPv4行为一致)…」。
> 缺陷选项:「实机行为是产品问题(在案第 1、2、3 轮曾判疑似产品缺陷,见上)…」
> **四标准**:三轮一致的缺陷证据链完整呈现,用户可据 IPv4/IPv6 对照(题面引文自带 517027 对照语句)直接选缺陷臂——上批该案因无缺陷出口被自动挂起,本轮正面修复✓。

**样张三 · 532862 — suspended·新批恢复问询(续跑活体点)**
> 题面:用例 …532862(配置AAAA类型的会话保持,使用ipv6访问) 上批被挂起。本批如何处理?
> 选项:[恢复处理]回到正常流程继续修/[保持挂起]本批继续不动它
> **兼容性**:零新字段依赖,旧 facts 直出✓。

**样张四 · 600046(会话保持后,修改被保持的service ip)— cap·接线后**
> 各轮判断:第1轮:判隔离复跑——「Device session persistence table confirms…」;第1轮:疑似产品缺陷——「After sdns service ip ip1 172.16.35.213 changes…」;第2轮:判用例侧可修——「Command syntax error: `sdns host persistence 10 www.zyq.com 24 64 A` was rejected…」;第3轮:疑似产品缺陷——「验证sdns service ip修改后是否应自动清除旧IP的session persistence条目。CLI手册未明确此行为,设备保留了旧条目(.231)和新条目(.213)…」。
> 缺陷选项援引「第 1、3 轮」。
> **四标准**:同轮双判断(r1 隔离复跑+缺陷候选)如实并陈不合并;G 层语法拒(r2)与 V 层缺陷假设(r3)人话区分;churn 全貌可见——上批用户在只见最后一轮的题面下选了「停止」,新题面下缺陷假设不可能再被 churn 叙事掩盖✓。

## 七、残留与观察项(如实)

- **待甲三项**:§三-2e(claim_history 组装)/2f(s0_dispute 投影)/2g(cap-correct 配套);未落期间渲染层全部优雅降级(样张已证)。2a 与 user_stop 契约甲已落地收敛(§二)。
- **接缝演化教训(入档)**:user_stop 曾在两侧异步演化中短暂双轨(甲 marker 过渡形态 vs 冻结契约;乙一度退役 stop_accounting 时甲侧恰有一版消费它,3 个 e2e 短暂红)——终态以冻结契约收敛,全绿。教训:冻结契约期两侧任何形态调整先过团队长广播,不做单方"消解"。
- panel sides 引文 [:300] 窗口维持与 briefs 同宽,仅加「…」标记;超长引文完整版在盘上 ask_panel.json。
- engine_tool `_panel` 答案正则对含 `. "` 序列自由输入早停(TUI 桥接层,design_challenge §二 F 已记档)——正交,未动。
- suspended 题面未加缺陷意图归类(答案空间=恢复/保持;宁保守,观察一批再定)。
- 样张渲染脚本为一次性只读(未入库);claim 文本混有英文=归因原文引用(『』内如实),题面框架全中文。

*team3 · 2026-07-16 · 乙队(impl-ask)。测试:新增 27(test_questions_ask_semantics);接线后 ask 通道+粘性 53 passed;全量数见收尾汇报。*
