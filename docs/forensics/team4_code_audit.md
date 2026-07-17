# team4 · Python 工程师代码审计（任务 #9/#10/#11/#12）

> 只读调查，零代码改动（除本报告；pytest 实跑一轮，其产物如实记录于第四节）。
> 范围：`main/ist_core/compile_engine_v8/`（16 模块全量通读）+ `main/case_compiler/` + `main/ist_core/tools/device/`（结构与引用扫描）+ `tests/` 全量。
> 对照物：`docs/DESIGN_v8_engine.md`（1813 行全读）+ `docs/forensics/team3_impl_engine.md`（既有取证，本报告只报增量）。
> 分级：P0=行为缺陷/设计违约；P1=结构不一致/死代码/文档-代码漂移；P2=风格/可读性。
> 生成：2026-07-17 · Py-Eng。

**总计数：P0 × 0 · P1 × 11 · P2 × 10**（另：设计一致性「合规待办」4 项、注释清点 20+ 处、测试隔离方案 2 组）。
**pytest 基线（任务 #15 回归红线）：2141 passed / 1 skipped / 0 failed / 0 error（55.64s）；collect-only 2142 collected / 0 错误。**

---

## 第一节（任务 #9）：V8 代码 vs 设计文档一致性 + 冗余注释清点

### 1.1 总体结论

逐模块对照后，**未发现 P0 级设计违约**：DESIGN §16.1 重画拓扑（prep→bed_gate→author→ask_decision→merge→run→reconcile→attribute→diagnose→ask_contradiction→closing）与 `graph.py`/`state.NODE_TYPES` 三方一致；事实流 append-only+幂等键（§2.1）、权威序（§2.3）、INV-2 残差硬停（nodes.py:984-993）、INV-11 三式（reconcile 式①/writeback_failed 式②/gate_disabled 式③，nodes.py:972-983、1119-1124、1962-1984）、G1-G6 门、§11.9 交付契约（closing）、§18.13 三元组投影（questions.py:124-156）、§18.8.1 全部止血件（restorable_diff/迟到回收/probe_resilient/escalated 解除）均能在代码指认落点。设计文档「设计中/立项/队列末位」标注的未实施项（I4 quarantine、I5 契约套件 `tests/framework_contracts/` 不存在、I7 transient_rate 无实现、S1 类型图、§16.2-C diagnose 的 LLM 半）与代码现状**一致**——文档的完成度纪律（§18.7）执行到位。

### 1.2 实现缺口/偏离（增量发现）

| # | 级 | 位置 | 发现 |
|---|---|---|---|
| 1-1 | **P1** | `questions.py:5-6` vs 全 repo | **幽灵开关 `IST_ENGINE_ASKQ_LLM`**：docstring 承诺「=1 时允许 LLM 润色散文,润色后仍过 validate_questions(不过则回落模板)」——全 repo 无任何代码读取该 env，LLM 润色路径从未实现。docstring 描述不存在的行为。 |
| 1-2 | **P1** | `questions.py:274-292` | **`validate_questions` 是无消费者的死门**（生产面零调用，仅 3 个测试文件当断言用）。且其 label 校验 `set(labels) <= set(DECISIONS)` 与 §18.13 三元组题的自由 label（「采纳「{procedure}」」「我给别的等价方案」「挂起,如实报告」，questions.py:140-151）**互斥**——若将来把润色路径接上，三元组题必被误杀回落。与 1-1 二选一处置：删门+删幽灵描述，或修门兼容三元组 label。 |
| 1-3 | **P1** | `_shared.py:310` vs `resilience.py:311` vs CLAUDE.md | **`IST_FORK_WALLCLOCK_S` 默认值三处漂移**：V8 `fork_executor` 写死兜底 `or 900`；`ForkExecutor.__init__` 兜底 `or 600`；CLAUDE.md 记载「默认 600」；`ink/components/ist_app.py:440` 又写 `or 900`。实际行为：V8 引擎非 max fork=900s、max=1200s（`IST_FORK_WALLCLOCK_MAX_S`），非 V8 直构路径=600s。同一 env 的默认散落三处且值不同——改默认时必漏。建议收敛到 resilience 单点（`_shared.fork_executor` 不传 wallclock_s，或三处同值）+ CLAUDE.md 改述。 |
| 1-4 | P2 | `engine_tool.py:20` `_MAX_INTERRUPT_ROUNDS=12`；`nodes.py:38` `_MAX_ASK_ROUNDS=8` | 两个问询轮上限常数**无设计出处**（DESIGN/CLAUDE 均未记载）。行为是安全护栏（超 12 轮 interrupt 后 compile_engine_run 掉出循环、超 8 批×4 题后剩余欠定题静默留待下轮 gather），语义合理但数字来历不可考。候选回填设计文档一句。 |
| 1-5 | P2 | `nodes.py:2749-2764` vs DESIGN §16.3 | R5 两布尔的落账形态偏离：设计写「decision 事实随答积累 R5 两布尔」，实现是 closing 期统一投影成**独立 `decision_outcome` 事实**（effective 判据=收口时刻案已达终局）。语义等价且实现更合理（效果要到收口才知道），但与设计文本字面不符——建议设计侧改述为准。 |
| 1-6 | P2 | `_shared.py:290-302` `emit_tick` | `"wave": 0` 恒零、`"round": vol_seq`——V6 footer 契约字段的占位填充。显示契约与引擎解耦是对的，但 wave 恒 0 无注释说明「V6 契约占位」，读者会找 wave 的生产者。 |
| 1-7 | 合规 | `nodes.py:2054-2064` vs DESIGN §12.1-X2 | common_cause 事实只有 `{key, aids, run_id}`，无设计 X2 期望的「假设+受影响集+verbatim 证据引用+行动判例键」——**属 §16.2-C 已如实声明的「LLM 半留片4」**，非违约；列此仅为修复轮排期参考。 |
| 1-8 | 合规 | DESIGN §3 vs §16.1 | 设计文档内两张拓扑图并存（§3 旧草图含 anchor_gate/route 节点名，§16.1 重画为权威），§3 未标「已被 §16.1 取代」——文档内部一致性问题，移交 Design（任务 #5）处理。 |
| 1-9 | 合规 | `views.py:135-147`、`graph.py:50-61` | 「回归#2 修 B/修 C」（收口前置门 flush、卷指纹隔离）的设计锚在 `DESIGN_dongkl_finalization.md §⑥` 而非主设计文档——跨文档锚成立，但主文档 §16 无回指。移交 Design 补一行引用。 |
| 1-10 | 合规 | `nodes.py:944-948`、`nodes.py:706-725` | 两个 07-16 修复（run 节点 `stale_run_on_device` 归 busy 语义、终验幂等闸 broken 断批不吸收例外）目前**只有 commit message 与代码注释承载**（14c12163/b3ce3b4c），设计文档无对应段。候选回填 §16.4 片3/§18。 |

### 1.3 冗余注释清点（按 CLAUDE.md 注释纪律：只留「代码显示不出的约束」；来历/改动说明/对 reviewer 说话类删）

V8 代码注释的主体是「实证锚定型」（门/护栏 + 为什么存在 + 哪次实弹证明），**这类多数是合法的约束-why**（防止后人把看似冗余的分支删掉），不建议一刀切删。以下分三类清点：

**A 类·该删（纯改动记录/死引用/对 reviewer 说话，12 处）**：

| 位置 | 内容 | 理由 |
|---|---|---|
| `questions.py:299` | 「nodes stop/downgrade 落账分支 → 消费 stop_accounting(甲队文件,接线包见交付文档)」 | **死引用**：`stop_accounting` 全 repo 不存在（team3 文档明载终版未实现该函数、语义 inline 在 nodes）——注释指向幽灵实体 |
| `questions.py:5-6` | IST_ENGINE_ASKQ_LLM 润色描述 | 见 1-1，描述不存在的功能 |
| `questions.py:10-13` | 「2026-07-16 P0 收编自 engine_tool…接线与分工见 docs/forensics/team3_impl_ask.md」 | 收编完成后的迁移史；保留「本文件是 ask 面板语义单一事实源」一句即可 |
| `questions.py:296-299` | 「2026-07-16 P0-新②/N2 收编:题面组装…从 engine_tool/nodes 迁入」 | 同上，迁移史 |
| `questions.py:318-324` | 「止损落账(P0-新②b…)已由甲队按 N1a…落地在 nodes…本文件不再输出落账形态」 | 对 reviewer 交代分工的说明；语义已由测试锁（test_claim_stickiness），缩为「止损落账在 nodes.ask_contradiction,此处只管题面」一句 |
| `nodes.py:25-26` | 「Other 意图归类收编至 questions.py(2026-07-16 接线包 2a;import-as 绑定模块属性…)」 | 迁移史+import 技法说明；`N._answer_token` 测试路径依赖可留半句 |
| `engine_tool.py:174-177` | 「题面组装已收编至 questions.py(ask 面板语义单一事实源,2026-07-06 P0-新②:cap/env 缺陷臂…全在彼处」 | 迁移史；委托行自身已说明一切 |
| `_shared.py:316-319` | env_flag docstring 后半「V6 同名函数 V8 迁移时漏带——…被 _writeback_one 的 debug-except 静默吞…(2026-07-16 team3 实现轮抓获,补齐恢复)」 | 纯修复历史（回归锚已在 test_promote_env_flag_regression）；docstring 留前两行语义即可 |
| `uncertain.py:34-36` | 「动词表来自文法数据…(no,show,clear) 硬编码曾与文法漂移,红线评审 2026-07-08 低危项」 | 评审史；「动词表来自文法数据,两路同源」半句是约束可留 |
| `bed.py:330-335` | S4 区段横幅 6 行（run18 根因叙事） | 与 `own_writes_by_command`/`restore_mechanical` 两个 docstring 内容三重复；留 docstring 删横幅 |
| `main/ist_core/tools/device/__init__.py:8` | 「V6 验收切换(2026-07-10):出口指向 V8;V6 engine_tool 保留在盘待验收后删除」 | **过时**：V6 目录已删（见第三节），待办已完成 |
| `main/ist_core/tools/device/compile_prep.py:3` | 「供 V6 编译引擎(compile_engine)prep 节点调用」 | 过时：现役调用方是 V8 `nodes.prep`（nodes.py:113） |

**B 类·该并入设计文档后在代码内缩为引用（长期价值、代码内过长，6 处）**：

| 位置 | 内容 | 去向建议 |
|---|---|---|
| `nodes.py:706-725` | `_delivery_verify_skippable` docstring 20 行（终验幂等闸+K5 broken 断批例外的完整机理） | 回填 DESIGN §16.4 片3（现无锚，见 1-10），代码留判据三行+引用 |
| `nodes.py:944-956` | run 节点 stale_run_on_device/digest 留声两段实证叙事 | 回填 DESIGN（1-10 同批），代码缩一行 |
| `nodes.py:864-867` | merged run_id 带 seq 的地雷叙事 4 行 | §16.4 片3-⑤ 已有全文，代码缩为「见 DESIGN §16.4 片3⑤」+关键半句 |
| `views.py:135-141` | batch_view 卷指纹隔离 7 行（yzg 饿死 gather 机理） | DESIGN_dongkl_finalization §⑥ 已有，缩引用 |
| `bed.py:212-224` | `restorable_diff` docstring 13 行 run18 全叙事 | §18.8.1 已有几乎逐字的对应段，代码留判据（纯 added 无 removed 不恢复）+引用 |
| `nodes.py:1022-1029` | broken 连击护栏 per-case 非 per-artifact 的 8 行(含「这**是一次降秩**」理论说明) | 理论说明归 THEORY/DESIGN(dongkl 定稿 §⑥ 已有),代码留判据 |

**C 类·确认保留（约束-why，抽样确认合法，不动）**：`facts.py:93-95`（attribution 幂等键为何按 run_id）、`nodes.py:1003-1006`（卷外案陈腐记录不得入账）、`bed.py:301-303`（`all([]) 恒真曾让全局命令穿门`）、`questions.py:29-36`（为何按标点截断）、`views.py:89-91`（H2 按 question_id 配对的二义前科）、`graph.py` 全部边注释（图即文档，拓扑门锚）等——这类删了会导致护栏被后人「简化」掉，属 CLAUDE.md 允许的「代码显示不出的约束」。

### 1.4 交叉验证（leader 移交，Theory P0-3）：机械逆放是否残留群逆假设

**问题**：S 代数 (29) 文本仍写群逆恒等式「no X ∘ X = id」，K 理论 07-13 已裁决「no X 是对象级复位算子、非精确群逆」。核查 `bed.py` 机械逆放 + `nodes.py` τ 门到底按哪个语义走。

**结论：实现达标——按「对象级复位」保守语义走，「no X ∘ X = id」在代码里从未被当作定理消费；S (29) 属文档文本滞后，非代码缺陷。** 行级证据五组：

1. **仅案面自己创建的对象才逆放**：`bed.py:388-407 own_writes_by_command`——diff 行「己方」iff 案面 config 命令里有创建该对象的命令（`_creating_command`，bed.py:369-385：「找不到=案面没创建过该对象(基线/他人写/仅被访问)」）；foreign 只报不动（INV-9）；`pairs` 空时**全归 foreign**（bed.py:392-393「保守:宁可不恢复也不误删」）；命令源只认框架 `sends command in config:` 行（bed.py:357-366，dig 等访问不算写）。run18「删管理口 IP」形态在新判据下结构性走不通（port2 无案面创建命令 → foreign）。
2. **clear 类不机械逆放**（聚合复位≠逆元，正是 K 裁决语义在代码里的原话）：`bed.py:425` `if create and head and (pairs_lc.get(head) or {}).get("no"):`——head 只有 clear 无 no 逆元的**不发机械命令**、进 residual 走 LLM 后备+双门；docstring `bed.py:413-414`「只有 clear 的不机械逆放,clear 是聚合复位会误伤旁邻对象」；建议侧同语义（`tau_coverage.py:127`「3 公理:no=否定/**clear=聚合复位**/show=观测」）。
3. **不假设 no 精确——运行时复探验证替代代数假设**：`nodes.py:2624-2631`（closing）执行恢复命令后**重拍快照再 diff**，`verified = cmds if cmds and not residual else []`——复探不清零就不记 verified，residual 逐通道入床账（nodes.py:2632-2637）下批接力。逆放命令只是**候选动作生成器**，「id 是否成立」由复探裁决而非公理背书。
4. **破坏面上界=案面自身对象**（destructive-command 教训的边界要求）：机械通道发出的命令只有两种形态——`no <案面创建命令原文>`（bed.py:426，注释「negation,作用域=原命令」）与重放案面命令原文（bed.py:432）——每条命令实体 ⊆ 案面命令实体，结构上触不到案面之外的对象；LLM 后备另有 `entity_gate`（bed.py:296-303：实体 ⊆ 己方 diff 实体集，且「无实体 token 的全局命令(clear all/reboot 类)一律拒」——R-7 `all([]) 恒真穿门`已修）。
5. **τ 门侧零执行风险**：`check_tau_coverage` 是呈报器（missing+suggested_inverse **建议**），消费点 G1（emit 呈报不硬拒）/G2（题面出口）/G3（交付门）均不执行命令，建议经 brief 由 worker 判断、上机 oracle 终判；inverse_forms 数据缺席 → `gate_disabled` 入账+报告 K 健康度行（nodes.py:1972-1978，INV-11 式③不静默）。

**已知残余（对象级复位语义的固有精度边界，有安全网，非 P0）**：①「案面修改基线已有同名对象、且变更属性非身份 token（纯数字端口/权重被 `_identity_tokens` 排除，bed.py:254-265）」场景下，removed 旧形态行会误匹配案面新命令 → 重放新形态，机械恢复方向不完美（净效=恢复无效）——被复探如实揭穿 → residual 入账接力，下批 LLM 通道再试；瞬断窗口（先 no 后重建）在批后收敛期，破坏面仍 ⊆ 案面对象。②`no <create 全文>` 可能被设备语法拒（部分 CLI 的 no 形式不带全参）→ 执行失败复探不清零 → 入账，无副作用。两者均为精度/效率面，列观察不列缺陷。

**处置建议**：S 代数 (29) 文本改述为「no X 是对象级复位候选，作用域 ≡ X；成立性由执行后复探裁决，不作公理消费」——归 Theory（#4）/Design（#5）文档侧修订，代码零改动。

---

## 第二节（任务 #10）：函数命名/结构统一性与可读性

### 2.1 总体结论

三个范围的命名纪律**整体良好**：工具层 `compile_*/dev_*/kb_*/fs_*` 命名空间收口执行到位；V8 内部参数顺序高度一致（facts 族 `(fs, aid, …)` fs-first、节点 `(state)->dict`、_shared `(state, fs)`、bed 注入式 `probe_fn/exec_fn`-first）；返回形态一致（@tool 全返 str，bed 双元组全部「(正果, 余项)」语义）；语言分层执行到位（注释中文、LLM-facing 文案英文、用户面中文）。问题集中在**超长函数**与少量新旧并存。

### 2.2 超长函数/深嵌套（AST 全量扫描）

**>250 行（P1 级可读性，修复轮建议拆分）**：

| 位置 | 函数 | 行数 | 拆分建议 |
|---|---|---|---|
| `emit_xlsx_tool.py:958` | `compile_emit` | 656 | 门族已是独立函数，主体是三通道解析+门编排+落盘——可拆「载荷解析」「门流水线」「凭证落盘」三段 |
| `batch_tools.py:449` | `dev_run_batch` | 396 | deliver/轮询/收割三相 |
| `nodes.py:2539` | `closing` | 361 | 承载 8 个职责（uncertain 入库/床收敛/G3/机读报告/双人话报告/缺陷单/清理/双对账+收口卡）——至少「床收敛」（~80 行）与「报告+对账」可提独立函数，与 bed.py 对称 |
| `batch_tools.py:1114` | `dev_run_batch_digest` | 343（深 7） | 采集/窗口审计/机械预判三段 |
| `grade_extract_script.py:249` | `extract` | 293 | 5 检测器本就该各自成函数 |
| `emit_xlsx_tool.py:1647` | `compile_emit_merged` | 265 | — |
| `nodes.py:2081` | `ask_contradiction` | 263 | 题面组装已收编 questions 后仍 263 行——「共因合题分组」「答案消化 token 分支」可各提一函数 |
| `nodes.py:1377` | `attribute` | 253 | G6 前筛段（~60 行）可提 `_g6_prescreen` |

**100-200 行（P2，可接受但列账）**：`build_brief` 197、`reconcile` 195、`compile_fanout` 193、`ask_decision` 189、`build_questions` 179、`check_verifiability` 173、`dev_rest` 166、`merge` 161、`dev_run_case` 158、`build_ask_question` 155、`submit_ask_panel` 149、`bed_gate` 142、`cli_qhelp` 142、`dev_ssh` 141、`diagnose` 140、`expand_blocks` 137（深 7）、`_gate_command_existence` 133（深 6）等 33 个。

深嵌套真阳性（剔除 elif 链假阳后）：`dev_run_batch_digest`/`expand_blocks`/`structural_gate._check_capture_refs_defined`/`_framework_reserved_names`（各深 7）。`render.case_timeline` 的「深 10」是 AST 把平坦 elif 链计深的假阳，实际可读性无问题。

参数 >6 的函数全部是 @tool（`compile_emit` 15 参、`compile_report_underdetermined` 10 参等）——LLM 工具 schema 需要平铺参数，属合理豁免；唯 `fail_attribution._submit_attribution_locked`（8 参内部函数）可收拢为 dict。

### 2.3 命名一致性问题

| # | 级 | 位置 | 发现 |
|---|---|---|---|
| 2-1 | **P1** | `bed.py:268` vs `bed.py:388` | `own_writes`（旧判据，run18 删基线成因）与 `own_writes_by_command`（S4 新判据）**新旧并存**：生产面已全部走新函数（nodes.py:2601），旧函数零生产消费、仅 2 个测试文件仍在测（详见第三、四节）。留着=下一个维护者可能误用旧判据。 |
| 2-2 | P2 | `questions.py:92` vs `questions.py:446` | `build_questions`（欠定通道）与 `build_ask_question`（矛盾通道）——**单复数区分两个完全不同的题面族**，极易混淆。建议改名对齐通道语义（如 `build_decision_questions` / `build_contradiction_question`）。 |
| 2-3 | P2 | `_shared.py:39,43,47,61,260,332` | `append`/`manifest`/`view`/`emit`/`signal` 等极短泛名：依赖 `sh.` 前缀才可读；`manifest`/`view` 名词式 getter 与 `load_facts` 动词式混排。低危（模块内一致使用），改名收益有限，列账不催修。 |
| 2-4 | P2 | `nodes.py` 全文 | 区段分隔线两种风格混用：`# ── 注入点 ──…`（41 行）与 `# ------------- [mech] prep`（107 行起）。后者带节点类型标注是拓扑对照的有效信息，建议统一到带类型标注的一种。 |
| 2-5 | P2 | `engine_tool.py:23` | `import re as _re` 落在两个函数定义之间（模块中部）——PEP8 imports 顶置；nodes.py 的函数内 import 是刻意懒加载（fail-open 纪律）不算violation，但模块中部裸 import 无此理由。 |
| 2-6 | P2 | `nodes.py:1666` | `_fanout_pool_size` 定义在 ask_contradiction 辅助函数群与 diagnose 区段之间，但它服务 author（431）与 attribute（1554）两处——位置与消费者不邻接。挪到「注入点」区段更顺。 |

### 2.4 好的实践（如实记录，修复轮勿破坏）

- `_shared.py` 五个 `*_waiting` 谓词命名一族一律（cap/env_confirm/panel/suspended_resume/bed_treatment）；
- `facts.py` 派生谓词直接用理论词表名（deliverable/frozen/contradictions）而非 is_ 前缀——与 DESIGN §6「术语一致（contracts.md 定义一次）」对齐，一致性优先于命名惯例，正确取舍；
- `bed.py` 全模块注入式设计（probe_fn/exec_fn/llm_fn 参数化）使 31KB 模块可全量单测；
- domain_grammar.py 19 个数据 getter 全名词式（verbs/rejection_hints/…）风格统一。

---

## 第三节（任务 #11）：V6 前旧代码冲突清单（只列不动手）

### 3.1 现状核查

- **V6 目录 `main/ist_core/compile_engine/` 已不存在**（整删完成，DESIGN §9.5 承诺兑现）；
- **`runtime/` 下无任何 `.db`**（含旧 `compile_engine_checkpoints.db`——Test-Eng #1 清理后盘上为空；V8 用 `compile_engine_v8_checkpoints.db`，engine_tool.py:210 会按需再生，合法）；
- **`langgraph.json` 无旧图指针**：`compile_engine` 图 id 已指向 `compile_engine_v8/graph.py:graph`（id 名不带 v8 后缀属指针冻结约定，非残留）；
- grep `v5/V6/legacy` 的命中**绝大多数是注释里的历史叙述**，非活代码引用。

### 3.2 行动清单（每条：文件 / 性质 / 建议动作 / 影响面）

| # | 级 | 文件 | 性质 | 建议动作 | 影响面 |
|---|---|---|---|---|---|
| 3-1 | **P1** | `tools/device/compile_pipeline.py:35-57` `_grade_extract_facts` | **死代码**：docstring 声称的消费者 `compile_engine/nodes/compile_phase.py` 已随 V6 删除，全 repo 零调用 | 删函数 | 无（grep 确认零消费者；`grade_extract_script.py` 本体另有活消费者不受影响） |
| 3-2 | **P1** | `tools/device/compile_pipeline.py`（整文件 57 行） | 遗留壳：仅剩 `_emit_progress` 一个活函数，唯一消费者 `compile_engine_v8/_shared.py:262`；DESIGN §7 明载「三个 helper 归位后删文件——`_emit_progress` 仍被 v8 _shared 依赖,归位后方可删」 | `_emit_progress`（7 行自包含）归位进 `_shared.py`（或 events 层），随后**删整个文件** | `_shared.emit()` 一处 import 改；tests 无 import 依赖（test_resilience.py:132 只用字符串 "compile_pipeline" 作 fixture 名）；DESIGN §7 该行同步销账 |
| 3-3 | **P1** | `bed.py:268-285` `own_writes` | 被 `own_writes_by_command`（S4 兑现②）取代的旧判据，生产零消费 | 删函数；同批迁移 `test_bed_ledger_loop.py:43,45,53,68` 与 `test_baseline_face_no_autorestore.py:55` 共 5 处用例到新判据（`test_s4_mechanical_restore.py` 已覆盖新函数，迁移可参照其夹具） | 测试改动 2 文件；`split_maintained`（bed.py:127）docstring 提及 own_writes「判据同型」需改述 |
| 3-4 | **P1** | `questions.py:274-292` `validate_questions` + `questions.py:5-6` | 死门+幽灵开关（见 1-1/1-2） | 二选一：(a) 删门+删 docstring 承诺，同步改 3 个测试文件（test_questions_ask_semantics.py:155 / test_tau_coverage_gate.py:146 / test_command_existence_gate.py:170 改为直接断言题面结构）；(b) 保留作 eval 断言但修 label 校验兼容三元组题+docstring 改述「测试断言用」 | 方案 a 测试改 3 处；方案 b 代码 2 行+docstring |
| 3-5 | **P1** | `questions.py:299` | `stop_accounting` 死引用注释 | 删该行注释 | 无 |
| 3-6 | P2 | `tools/device/__init__.py:8` | 「V6 engine_tool 保留在盘待验收后删除」过时注释（V6 已删） | 删注释 | 无 |
| 3-7 | P2 | `tools/device/compile_prep.py:3` | docstring 称「供 V6 编译引擎(compile_engine)prep 节点调用」 | 改为「供 V8 引擎 prep 节点调用」 | 无 |
| 3-8 | P2 | `resilience.py:280,292-293` | 注释引 compile_pipeline 抽取史（「V6 步骤1 从 compile_pipeline 抽取」） | 随 3-2 删文件时同步改述或删 | 无 |
| 3-9 | P2 | `skills/loader.py:700,1066,1147`、`device_mcp_server/tools.py:712`、`case_compiler/device_mcp_client.py:850`、`precedent_tools.py:250` | 6 处注释提及 compile_pipeline（历史语境说明） | 低优先：随 3-2 一并把「compile_pipeline」改成「编译引擎」措辞；不改不影响行为 | 无 |
| 3-10 | 确认保留 | `verifiability_tool.py:310-317` legacy reason/suggested_fix 兼容通道；`batch_tools.py:889-935` `_fail_signatures_legacy` | 都有活消费（旧调用兼容/结构化行零时回退），**非死代码** | 不动 | — |
| 3-11 | 确认保留 | `case_compiler/` 全 16 模块 + `tools/device/` 注册表 20 工具 | 逐一 grep 引用核查：`xlsx_emit`（emit_xlsx_tool 两处消费）、`compile_fanout`（ist-verify skill+dyn-* 场景）、`compile_runtime_slots/fill`、`compile_attribute`、`compile_writeback`、`compile_expected_hits`、`dev_run_case/dev_init_device`（agent_define 白名单+loader 注册）等全部有活消费面（V8 引擎直调 / fork agents 白名单 / ist-verify skill / TUI），**无「只被旧链路使用」的死工具** | 不动 | — |

### 3.3 汇总

V6 清退完成度高：目录/checkpoint 库/图指针三大件干净。残留集中在**注释层**（8 处历史叙述）与**三个真死代码点**（`_grade_extract_facts`、`compile_pipeline.py` 壳、`bed.own_writes`）+ 一个死门（`validate_questions`）。全部动作合计 ≤2 小时工作量，无行为风险（死代码删除 + 注释清理 + 5 处测试迁移）。

---

## 第四节（任务 #12）：无用单测清点

### 4.1 全量基线（任务 #15 回归红线）

```
~/.venvs/infotest-engine/bin/python -m pytest tests/ -q
→ 2141 passed, 1 skipped, 0 failed, 0 error（55.64s）
--collect-only -q → 2142 collected, 0 collect 失败
```
- 时点：2026-07-17 00:49（#1 清理完成之后、#2 真编译启动之前），已第一时间报 team-lead。
- 唯一 skip：`tests/ist_core/tools/test_fail_signatures.py:192`——条件 skip（dongkl workspace 实数据不入 git），**合理保留，非失效测试**。
- collect 零失败 ⇒ **无 import 级失效测试**（没有引用已删模块的测试）。

### 4.2 失效/低效测试清单

| # | 级 | 位置 | 性质 | 建议 |
|---|---|---|---|---|
| 4-1 | **P1** | `tests/ist_core/memory/test_backend_routing.py:65` | **恒真断言**：`assert root.exists() or True` 永不失败（该测试前一行 `root.name == "memory"` 仍有效，测试整体不废） | 删该行，或改为真断言/条件 skip。全库恒真模式扫描仅此 1 处（test_ask_user.py:116 的 `or True` 是 lambda 返回值技巧非断言；test_multifault_and_card.py:45 是「已重写」的说明注释——G4 恒真断言前科已清） |
| 4-2 | **P1** | `test_bed_ledger_loop.py:43,45,53,68`、`test_baseline_face_no_autorestore.py:54-55` | **锁旧行为**：5 处直测 `B.own_writes`（已被 own_writes_by_command 取代的 run18 缺陷判据）。测试绿≠行为对——生产路径早已不走它 | 与 3-3 同批：迁移断言到新判据或删除（新判据已有 test_s4_mechanical_restore.py 覆盖） |
| 4-3 | P2 | `test_questions_ask_semantics.py:155`、`test_tau_coverage_gate.py:146`、`test_command_existence_gate.py:170` | 经由死门 `validate_questions` 断言题面（门生产零消费，见 1-2）——测试本身有效（间接锁 build_questions 输出），但绑在死门上 | 随 3-4 的处置方案联动 |
| 4-4 | 观察 | ask 族 5 文件共 1252 行（test_ask_panel 393 / test_questions_ask_semantics 309 / test_gather_ask 240 / test_f8c_fold_and_adopt 215 / test_ask_routing 95） | 疑似重复覆盖点抽查：五文件各测不同面（工具 schema 门 / 题面语义 / 批末聚合路由 / 折叠采信 / 图边判据），**未见同断言重复**——不判重复，仅提示后续新增 ask 测试先查此五处归属 | 不动 |
| 4-5 | 观察 | 测试-模块覆盖对照 | V8 16 源模块全部有专测或强间接覆盖（mirror_anchor 经 test_bed_gate/test_graph_scenarios；engine_tool._bridge/_panel 经 test_bed_gate 等；uncertain 经 memory/test_self_healing_loop）；fixtures/ 为 yzg 金标准回放（DESIGN §8 场景回归承诺 ✓） | 无裸奔模块 |

### 4.3 测试产物落点评估（leader 点名两项实证，已复核）

**① pytest 产物直接落交付区 `workspace/outputs/`（实锤）**

本次全量跑后实测新增（mtime 00:49-00:50）：`_pytest_merged`、`_pytest_prep_{dongkl,dup,redline,yzg,zhaiyq}`、`_pytest_runbatch`、`t_*`（14 个）、`R_sig` 等 20+ 目录——与真编译产物（`CNAME pool支持ipo算法_dongkl`、`2046517590250353xx` 案目录）**同池**，Test-Eng 的 excel 终检被迫人工区分。根因：这批测试直调 `compile_prep/compile_emit_merged` 等真函数，产物根 hardcode 在 `sh.outputs_root()`/工具内部的 `workspace/outputs/`，各测试自行 monkeypatch 不齐。

**② pytest stub 链路写生产日志目录 `runtime/logs/`（实锤 + 一处存疑）**

`compile_evidence.93127.{live.log,events.jsonl}`（00:49，内容为 B100/B101 stub fixture、0s 不走秒）确认为本次 pytest 进程按 `<pid>` 命名规则写入——与真编译 fastlog 同池同名规则（`compile_evidence.<pid>.…`），leader 已被误导一次判断「编译已启动」。另有 `compile_evidence.94478.*`（00:57，44KB）：时间与我的 collect-only 不吻合（collect 不执行测试体），更可能是 Test-Eng TUI 真编译进程所写——**不下断言**，交叉核对归 #3。

**这两件事本身是否合理：不合理。** 测试产物混入交付区违反「workspace/outputs 是 agent 交付面」的目录契约（CLAUDE.md 知识库/工作区分离节）；stub 日志混入生产 fastlog 池破坏「按 PID 找当前编译日志」的运维约定（`ls -t compile_evidence.*.live.log | head -1` 会抓到 pytest 尸体）。

**隔离方案（只列不动手，供 #15 决策）**：

- 产物隔离
  - **方案 A（推荐，测试侧）**：`tests/conftest.py` 加 autouse fixture，统一 monkeypatch `compile_engine_v8._shared.outputs_root` 与工具层的 outputs 根到 `tmp_path`——现状是部分测试各自 patch、部分裸跑，收敛为公共 fixture；生产代码零改动、沙箱评审面零变化。
  - 方案 B（代码侧）：`outputs_root()` 读 `IST_OUTPUTS_ROOT` env、conftest 设 tmp——一处改动覆盖全部直调，但给生产路径引入 env 可变性（`_agent_roots` 沙箱常量联动，需安全评审）。
  - 方案 C（约定侧，治标）：统一测试产物前缀 `_pytest_*` + conftest session 结束清扫——区分靠约定，t_*/R_sig 这类现有命名先要归一。
- 日志隔离
  - **方案 A（推荐，一处判定）**：fastlog/events 写入点（`skills/loader._fork_emit_event` 及 evidence log open 处）检测 pytest 自动注入的 `PYTEST_CURRENT_TEST` env——命中则改写 `tmp` 或跳写。生产行为零感知。
  - 方案 B：文件名加来源段（`compile_evidence.pytest.<pid>.…`）——可区分但仍同池占位。

### 4.4 时序纪律自查

本节 pytest 跑于 #1 completed 之后、#2 真编译启动之前（TaskList 时点核对过）；后续修复轮的回归重跑**须先与 Test-Eng 对表**（真编译在批时 outputs/ 与 runtime/logs 会继续互混，隔离方案落地前跑批期间不宜重跑全量）。

---

## 附：P0/P1/P2 索引（供 #15 汇总）

- **P0：无**。
- **P1（11）**：1-1 幽灵开关 IST_ENGINE_ASKQ_LLM；1-2 validate_questions 死门+三元组 label 互斥；1-3 IST_FORK_WALLCLOCK_S 三处默认漂移；3-1 `_grade_extract_facts` 死代码；3-2 compile_pipeline.py 壳待归位删除；3-3 bed.own_writes 旧判据并存；3-4 死门处置（与 1-2 同源）；3-5 stop_accounting 死引用；4-1 恒真断言 1 处；4-2 测试锁旧判据 5 处；4-3-①② pytest 产物/日志落生产区（结构问题）。
- **P2（10）**：1-4 问询轮常数无出处；1-5 decision_outcome 形态偏离设计文本；1-6 emit_tick wave 占位无注释；2-2 build_questions/build_ask_question 易混名；2-3 _shared 泛名；2-4 分隔线风格混用；2-5 engine_tool 模块中部 import；2-6 _fanout_pool_size 位置；3-6~3-9 过时注释族（4 处并 1 条）；2.2 节 100-200 行函数账（33 个，含 >250 行 8 个建议拆分项）。
- **移交**：1-8/1-9（设计文档内部一致性）→ Design（#5）；A 类注释删除+B 类注释并档 → #15 修复批；4-3 隔离方案 → #15 决策。

*Py-Eng · 2026-07-17 · 全程只读（本报告为唯一写入）*
