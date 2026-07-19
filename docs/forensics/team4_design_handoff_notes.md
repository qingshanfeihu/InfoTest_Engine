# team4 Design 交接笔记（给未来的自己·2026-07-19 会话末）

> 我是 **Design（产品设计专家）**，team4 的评审门。全程中文回复。角色：**所有 Eng 改动的 Design 评审门（P/F+reason，F 即打回）** + leader 委派的设计裁量代裁权。四关：双评审(Theory+Design)→redline→leader 亲跑 pytest→leader commit。**禁 commit（成员一律不 commit）、禁打印 Token、编造观察=最严重违规。**

## 一、收口批 #42 当前状态（会话末）

- **四件全 P**：D31 首件 / D28 co-merge / TUI 三件(#27/D23/D24) / 六件套(Z7/D22/D25/D26/D29/q4)。
- **四域已 commit**：81fc792b(engine)/7984867f(agents)/cd63877d(tui,含 D22 滞后测按我条款锁入=语义标签+反向锁 .md 原名不得进用户面)/2c6fc37d(docs)。**权威 pytest 2261 绿**。
- **docs 回填已 land（我这轮）**：`DESIGN §17.5`(D31 二犯根治，引 THEORY §5.5.8 零双写) + `§20`(D28 基准#4 空值兜底)。等 leader docs 跟进 commit。
- **待触发**：zhaiyq 重渲（走幂等闸、组成无 broken→应零设备轮）→ **准入复验批（若触发）的评审**是真上机变量；07-28 sprint #38 交付=「4 脑图准入」，真 gate=zhaiyq 上机非代码评审。

## 二、本会话设计裁决 + 落点（future-me 查这里）

| 裁决 | 核心 | 落点 |
|---|---|---|
| #27 footer 冻结 | 组合判据 `phase∧produced==passed==0∧(spin>0∨fork_running>0∨fork_done>0)`+编写期字段域不重叠(done=fork_done/入账字段 else 不动) | ist_app.py:335-375；done_n 含 error(生命周期非成功) |
| D22 内部文件名泄漏 | source_ref **结构锚白名单**(非 quote grep 强字典)+手册转章节去.md+序号保底 | questions.py `_source_label_cn` |
| D23/D24 TUI hint | hint 对齐 B(数字直选落答+前进)+第二处注释债+前进×回扫配套；D24 `_highlight_for` 条件化(已答显已选/未答保0) | ask_user_view.py :64/:336/:390 |
| D28 英文散文 | **复用休眠字段 user_note**(非造 user_summary=framework-capability)+基准#4 兜底(空退 _DISP_CN 中文非 fix_direction 英文) | nodes.py:1856/2332/2354, fail_attribution.py:341, DESIGN §20 |
| D31 对账器漂移 | 双路独立保留+等价守门(单测期+fixture 穷举全状态转换+双重断言)+REPORT_MISMATCH 自降级 UX；run18 迟到回收卷维持 42 | report_gate.py:37-42, test_report_gate.py:252, DESIGN §17.5, THEORY §5.5.8 |

## 三、持久方法论教训（带走的、能逐枪指认的）

1. **最硬一课（单杠杆）**：**「我没找到 X」是关于我查法的陈述、不是关于 X 的判决**——任何"查无"(grep 零/文件不存在/断言未命中)先默认**证伪自己的查法**(换独立手段重查)，活下来才准变成关于世界的论断。D31 我窄搜假想名零结果→判"不在盘"F 两轮=反面；注入我三工具(Read+ls+cat)证伪"缓存bug"=正面。同一信号相反处置、相反结果。
2. **方法沉淀 #17**（team4_fix_round_plan.md §方法沉淀，已 land）：宽搜实体特征、勿窄搜假想名；报告与核查两侧名实必须对齐。
3. **grep 命中看语境、不唯计数**：`test_ask_user.py:553 assert "↑↓/数字 移动" not in hint` 是守门断言(防 A 回归)、非 A 残留——命中≠残留，读语境才判准。
4. **不信漂移行号、按内容锚 grep**：编辑后行号漂移，用内容特征定位。
5. **verbatim 协议**（Py-Eng 诚信卫生#2 起因，SECOND_ND vs 实际 REDEC 名实不符×3）：报方贴**实际落盘符号名+真跑复制粘贴**(非手打重构)、核方**宽搜实体**。其验证数字降参考、权威验证 leader/我亲跑。
6. **抗注入**（team4_oob_injection_incident.md，leader 入档+三条协议全队广播）：①指令通道唯一性(leader 只走 teammate-message)②降核实强度的指令天然可疑③不可核实之物永不确认(确认=编造观察)。口授内容不替代落盘核实。
7. **云盘 IO**：`grep -rn` 递归大目录慢，**缩范围**(子目录/单文件 grep、直接 Read 已知路径)快；宽搜实体特征但窄 IO 范围，两不误。
8. **docs 零双写=定义单源应用于文档自身**：land「单源防漂移」条款时，引 Theory §5.5.8 而非拷贝句子(拷贝=双写=将来漂移=正在记录的病的元级重演)。

## 四、这轮 Design 门实证的价值样本（四关设计意图）

三次拦截：①抓 SECOND_ND 名实不符(verbatim 引文定谳)②拦未审代码放行("非全P"诚实提醒 leader，防 redline 漏六件套)③独立验证载重声称(六件套控制流广扫证"零引擎逻辑")；一次被拦：窄搜误判(leader 中立抽查纠正、我认领根因在己)。**全入档=四关设计的正反样本齐了。**

## 五、越界不改的 flag（呈 leader/release）

`README.md:5`「1.0.5-beta.1（**V6** 循环驱动引擎）」既存 staleness（引擎已 V8、V6→V8 早于本会话）；版本标签是 release/leader 裁量，Design 位不单方改。**CLAUDE.md/README 经核无真·失效**(footer #27 反更准、D28/D31 是新增/低于粒度)——不做无谓编辑是正确的 fix。

## 六、会话末状态更新（收口批 committed + #44/corpus 早对齐 + loose end 清零）

**收口批 #42 全 committed**：`81fc792b`(engine: D31/D28/六件套) + `7984867f`(agents: D28 user_note 产侧) + `cd63877d`(tui: #27/D23/D24/D22 滞后测) + `2c6fc37d`(theory: K §5.5.7/5.5.8) + `12b01ad2`(design: 我的 §17.5/§20 回填 + #44 交接注)。权威 2261 绿。

**②术语对齐（IETF human-in-the-loop → 交互设计术语规范）→ leader 裁 descope 销项**（非欠账）：理由=五加速点里最轻（零代码文档级）、真实消费方是**专利/对外叙事工作（未启动）**，现在落规范=没读者的文档；L0-L5 分级语言已在准入报告 §1 用上（五点#1）。**后批池注记（Design 认领）**：「IETF `draft-cui-nmrg-llm-nm` 术语对齐——**专利/对外叙事工作启动时重启**」。future-me：此项非未完成、是有意押后，触发条件=专利叙事启动。

**#44 自由度映射早对齐（已收敛、待 #43 数据底）**：`team4_llm_freedom_mapping.md`（LLM-Eng）+ `team4_theory_corpus_study.md`（Theory）。轴口径拍齐并全应用——**双轴正交**（需 gate 性=错误代价×无人值守〔我〕/ 可 gate 性=ABC〔对齐 `[[compile-quality-abc-three-layer]]`〕决定门形态）、**C×需强单列「防御纵深」类**（判例+安全禁令窄桥+ask+升深度+观察级监测，门密度=纵深层数）、**判据挂轴零双写**、**B 验证器兜底=正交事后-gate 维**（自由发挥面标"验证器兜底?有/无"）。corpus C1 咬合更正：`form=f(op,H)` 105 零例外**机械、非决策面**（归 engine emit 门 A 层），唯一真决策面=`worker/断言op&H选择`(C 层)——scaffold 现 26 面。**future-me #44 条款化**：C1/C2 喂断言形态面、C5 补 available-but-unused 判别器（判"footprint 治理缺口"vs"正常沉默"、防误杀）+ 接 C×需强防御纵深（footprint=判例层厚度、数据两处共用）；待 #43 delta 落数据底后逐面条款化入 DESIGN/skill。

**本场 loose end 清零**：scaffold 过目 done（无偏差+更正自己 imprecision）、②术语对齐 descope（后批池注记已录本节）。余件均待触发/待他方：#44 条款化 blocked by #43 / corpus 完整版待 delta（§4 轴③⑤⑥）/ zhaiyq 复验批 await trigger / README V6→V8 呈 leader。

**一个自留的行为教训（非项目、给未来自己）**：本场尾巴 SendMessage summary 撞 200 上限连撞三次，最狠一次还写下"我数了~150"却照样超（假的数=肉眼估计）——**修法不是"估准一点"，是"写短到明显安全、别判断够不够"**（最后两条 short-first 就过了）。教训真被用上的形，往往比"记住规则"更朴素：短，就直接短。同 `[[cloud-drive-no-run-in-place]]` 系「知道≠做到、内化在改打法那一下」。

## 七、#45 六裁决执行批 · 我的三件 docs（已 land，待 leader 攒 docs commit）

用户 2026-07-19 定谳「按建议走」（团队自决制+用户否决权）。我领三件（全 docs、禁 commit 归 leader），已全 land 进 `DESIGN_v8_engine.md`：

| 件 | 落点 | 核心 |
|---|---|---|
| ⑥C | §5.5 治理改写 | 废固定行数预算（60/50/80 及 99/86/206 作废）→ ①归属行（每条规则须 theory-map.md 有归属，无=该删）②150 行熔断（越线先置换再增补、不得净增）；账上一笔置换=检索顺序细节 prompt→contracts.md |
| ②B | §18.15 单元 E 缓立定谳 | E 缓立不立门；转正条件二选一=DS-2 种子 ≥30 对 / 真评审器候选出现；补反向指针「逐单元交代去向」那句，治 design_audit P0-1「A-E 措辞对 E 落空」 |
| ④B | 新增 §18.16 数据集承接 | DS-1↔改归因链必跑回归 / DS-2↔评审器候选必过准入考场（grade 之死红线）/ DS-3↔建设前置照 THEORY §7（正本单源零双写）；纪律：无消费点=死数据（同 C5） |

**future-me 注**：锚均按内容定位、§18.16 干净新节号（原 §18.15→§19 直连无冲突）。三件 + §16.4 代价注 + Theory K/S 件同批 docs commit（等 leader）。#43 corpus C1-C9 增量此前已全 P。

**#45 审务全清（会话末，全 P）**：
- **③A 管线退役** P：9 py 删净仅剩 SKILL.md／零外部残留／无游离测试；`{device}→set()` 映射 fs_* 非 gated 前缀=基础组常驻永不 drop；我 07-17 decision_memo:123 已签认、本次执行落地复核。
- **①A 缝合条款三锚复核** P：ctx=(π,B)B维／δ(c)=∅／∃-pass 三锚逐条对 K 主体（(15)/§90-99）；(44) 断言求值三分初查 `^(44)` pattern 误报零命中→宽搜全中（§2.12.3b）=「查无先审查法」当场用。
- **①A 接线问2（宪法级幂等闸）** P：三重机械保证不重引 livelock——图必终止（graph.py:25 diagnose 全终局→closing 无回边）／escalated 退 comp（ready 状态集不含 ESCALATED）／(40)终止性+封顶切环；与 Theory 协审**独立同结论=交叉验证**（我走图终止性、Theory 走确定性拒）。
- **§16.4 续跑代价注** land（我落）：coexist 非空卷续跑不幂等=条款⒉安全侧取舍 + ①A 缝合扩展同步（消 DESIGN↔THEORY 漂移）+ 两诚实边界（我续跑代价/Theory 单案残留假 PASS 属 oracle 残差）。
- **⑥C 格式确认** P + **⑤⑥+⑥C md 终审** P：双射我 `comm` 独立验证 41==41（非只信自检）／头注非硬卡／置换真落（检索顺序 worker md→contracts.md）；⑤A 三条=锚卷面命令零写死+语言分层+write_todos 安全，合红线。
- **#44 §1.3.3 必留人工极背书** P：与 corpus C8 三粒度不可判定理咬合、与我评审轴（信号只授权它实际量到的）同构。

**docs 落点（我 land 待 leader commit）**：DESIGN §5.5(⑥C)／§18.15(②B)／§18.16(④B)／§16.4 代价注。**待**：leader redline 整批→pytest→#45 尾 commit；#44 full mapping 待收口窗口从 §6 台账一次 land（评审门优先于自己产出）。

## 八、#48 R0 归因（供给侧 6 探针·framework-capability-before-limitation 实战）

用户令：归因 #47 R0「本质行为层不可行」= design/contract gap 还是 never-demanded。我供给侧 6 探针（行级证据）、Theory 公式侧、交互点 gate↔formula。

**核心结论**：R0 = **demand-side 为主、供给侧无结构性阻断**（framework-capability-before-limitation 命中，同 abs_found）。
- **探针①⑤（决定性）**：gate F 方法闭集**从 mirror 动态解析、非硬编码 8**——`structural_gate._valid_fs_by_e`:95（提 mirror env/check_point/ssh_server public methods）+ `_execute_returning_actions`:112（正则解析 apv_action 32+client_action 8=**40 execute 动作**）；execute∈allowed→accept。「词汇=8」是 105 卷 sdns **观测产出**、非能力上限。
- **门三态判据钉死**：found_times REJECT（:419-427 框架 2 参真做不到）vs execute ACCEPT（框架 ssh_server 有 40 动作）——**门 accept/reject 判据=框架支持性、非需求**。
- ②blocks 无 execute shape=prompt-data（steps 可绕）／③worker refs 未指 execute=prompt-data／④domain_grammar slb×1/ssl×0=grammar-data／⑥DESIGN 沉默=非排除。**缺口仅 prompt 引导+slb/ssl grammar JSON（低成本），无 engine/design-contract gap**。

**G/V 分层（双专家交叉·收口）**：R0 拆 G 层（execute 命令供给，我证 gate accept 无阻断）∧ V 层（π 投影可观测，Theory R1 逐个盘：握手/健康 V 通、信任验证走既有 V_U）。**form/π 正交**（Theory 精化：form 判断言形态 100% 覆盖、π 判观测面存在性，V 瓶颈在 π 非 form）。**R0 重构终态**：≠「不可行」，= G 通∧V 逐个盘∧需求侧未证∧缺口低成本。#47「不可行」是把「逐个盘 V 层+需求侧空白+引导缺口」笼统压成一个标签。

**方法样本（带走）**：R0「零产出」信号实际只量到「没产出过」——没当「结构性排除」，行级 grep 查证发现 gate/parser/框架全支持 execute。同本场那根轴（信号只授权它实际量到的）+ framework-capability-before-limitation。双专家 G（我 gate）+V（Theory 公式）交叉把 R0 从笼统标签拆成分层诊断——同 ①A 独立同结论交叉验证。**已合并**：leader 入 #47 amendment（新节「R0 归因修正：G/V 分层」，三方 sign-off）。

**#48 erratum（2026-07-19·Py-Eng #50 per-method READ 抓·最刺的自打脸）**：我 #48 引的 `ssh_server.py:151 def execute` 是 **grep 命中当 read line 引**——实际 :151 落在 `"""…"""` 注释块（:130-160）内 = **dead code**，live dispatch 在 `dic_operation.py:57`。结论 **unchanged**（40 动作 registry 我真读了 `_execute_returning_actions` parse + gate :559-561 no-whitelist skip 与死引无关）。**轴咬了 championing 它的人**：满会话讲「grep 命中≠read line」，自己在 #48 证据里犯——引 file:line 前必 Read 那行上下文、不拿 grep 命中当读过。已入 `[[signal-licenses-only-what-measured]]` 引证侧。

## 九、#44 LLM 自由度分层映射（committed bfac0b41「三层定稿」）+ 一个 thrashing 过程教训

**交付（三层各归其位、cross-ref、零双写）**：
- **DESIGN §21「LLM 自由度分层纪律」**（clause/framework 层，byte-identical @ 1997 行，过 Theory P + leader P）：双轴（门密度 key 需 gate 性 × 门形态 by 可 gate 性 ABC）+ 三极收束（机械默认可/engine 强制/必留人工）+ C×需强防御纵深 + 2 firm 条款（form 守成/欠定修法方向修复）+ 修复模板。
- **mapping doc §7 Design 全映射定稿**（per-face 数据层）：30 面 + #48 派生面（`worker/execute-form可见性`）三极 verdict × ⑥C `[Wn]/[An]` cross-ref × 官方锚 × clause 状态（firm 9 / 理论初判 ~14，不 over-claim）。
- LLM-Eng §1-§6 数据底（双轴框架/决策面/§3 表/六轴注入/§6 台账）。
- **后批**：worker/attributor prompt/skill 实改（#48 派生面 contracts.md 补句、条款② min_requests 接线）走四关 with eval，按 §21 三极+门密度对号。

**一个 thrashing 过程教训（记打法·负面样本）**：这轮 land→revert（leader「mapping DOC only」澄清，我把原任务「条款化入 DESIGN」当即时 land）→leader ruling reinstate→**我 reinstate 撞 leader 已做的 reinstate 成 duplicate**→dedup（verify 两副本 byte-identical → git checkout 两份 + 单次 re-add）→relocate §7 + 删独立 doc。**根因=并发动作 + 消息交叉 + 我 reinstate 前没 re-read 盘上状态**（leader 说「byte-identical to reviewed state」已暗示 reviewed 副本在盘、我该先 read）。同 `[[signal-licenses-only-what-measured]]` 的执行侧——**动作前先核盘上状态**（指令不授权盲目行动）。正面：clean revert 尊重权威 process 对了、dedup 前 verify byte-identical 才动对了；负面：reinstate 前漏核状态造 duplicate。**结果**：leader commit 了 §7 版（=我 relocate 的 ruling 版），committed 状态正确、你 flag 的 3 点随独立 doc 删除消解。future-me：多 agent 并发编辑同文件时，任何 re-add/restore 前先 `git status`+grep 盘上现状。
