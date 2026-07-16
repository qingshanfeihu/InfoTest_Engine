# Team2 代码符合性 + 注释治理 + 命名统一 + 遗留处置(只读审计)

> 任务 #3+#4+#6。基准设计文档 = `docs/DESIGN_dongkl_finalization.md`(现工作树版,216 行)。
> 红线:偏差只记报告,**不改行为**;改名只做低爆炸半径模块内私有 helper。
> 写权域:`compile_engine_v8/**`、`case_compiler/**`、`tools/**`、顶层 7 个 py。
> 生成:2026-07-16。

---

## 1 · #3 代码 vs 设计文档符合性

**总结论:代码在我写权域内的全部机制与 `DESIGN_dongkl_finalization.md` 语义符合。**
无「设计有代码无」的真实缺口(两处「缺」实为改名后存在);无「语义不一致」。
仅有的偏差全部是**语义一致、命名/措辞/行号漂移**(设计文档措辞落后于已落地代码),报告不改。

### 1.1 逐机制核对表(设计§ → 代码 file:line)

| 设计§ | 机制 | 代码 file:line | 符合性 |
|---|---|---|---|
| §0.1 | 结构门整类保留(17 门,非删) | `structural_gate.py`: `check_structural_constraints:385` / `check_no_found_times_mandatory:430` / `check_crash_gates_mandatory:629` / `lint_xlsx_case:1147` | ✅ 符合 |
| §A | `compile_check_verifiability` advisory 回灌 | `tools/device/verifiability_tool.py`(工具在) | ✅ 符合 |
| §A | precedent 三标(采样敏感/机生血统/provisional) | `precedent_tools.py:31,354,448,458,566-685` | ✅ 符合 |
| §A | footprint **只标机生血统、不标 provisional** | `footprint_writeback.py:35-91`;锁测 `test_failopen_semantics.py::test_writeback_threads_provisional_keeps_footprint_device_verified` | ✅ 符合 |
| §B | ask_panel 去预设默认 / sides 平摆 | `ask_panel.py:75,80-81,130-131,152-153` | ✅ 符合 |
| §① | 两界面事实源 `VALID_TEST_ENV_HOSTS`(含 `console`) | `case_ir.py:29-32` | ✅ 源在(worker.md 注入非我域) |
| §③ | command_existence 不修;clean re-emit 不清旧台账=潜伏风险(记录不修) | `emit_xlsx_tool.py`(设计标 677-678,行号已漂移) | ✅ 符合(设计=不修) |
| §④ | broken 派生态 `S_BROKEN_ERRORED`/`S_BROKEN_BLOCKED`+计数 | `views.py:23,26,113-120` | ✅ 符合 |
| §④ | errored 机械短路 `disposition=reflow` 不调 LLM | `nodes.py:1028-1069`(1048 reflow / 1055 env_blocked) | ✅ 符合 |
| §④ | errored→attribute→diagnose→author 复用 reflow 路;blocked→ask 呈报 | `graph.py:110-112`(reconcile)、`126-128`(diagnose)、`108-109`(blocked→ask_contradiction) | ✅ 符合 |
| §④ | window-audit `false_fail`/`false_pass` 检测器 | `batch_tools.py:975-1027` | ✅ 符合 |
| §⑥-A/C① | broken per-case streak 降秩终止(streak≥2→escalated) | `nodes.py:1002-1032` | ✅ 符合 |
| §⑥-B | INV-flush:所有 pre-ask closing 边先过聚合门 | `graph.py:_gather_or_close:50`(设计名 `_flush_then_close`);边 43/47/78/93/94/100/107/117/131/143/148 | ⚠️ 语义符合·命名偏差(见 D1) |
| §⑥-C② | 卷指纹隔离(subset 复跑不 churn `current_volume`) | `views.py:134-152`、`report_gate.py:25`、`_shared.py:247 volume_fingerprint` | ✅ 符合 |
| §2 | DNS 裸标签 lint(去 TLD 白名单锚) | `structural_gate.py:1108 _check_dns_label_limit`(设计名 `_DOMAIN_TOKEN_RE` 不存在) | ⚠️ 语义符合·命名偏差(见 D2) |

### 1.2 偏差清单(全部语义一致、仅措辞/命名/行号漂移 —— 报告不改)

- **D1 · §⑥-B 命名 + 计数措辞**:设计规定「新增 `_flush_then_close(s)` 替换 graph.py **6 条裸 `return "closing"`**」。
  实际实现为 `_gather_or_close(s)`(graph.py:50),由**各终态条件边分别调用**达成同一不变量(有欠定→`ask_decision` gather,否则 `closing`)。
  实测所有 **pre-ask** closing 边(prep/bed/author/merge×2/run/reconcile×2/diagnose/ask_contradiction×2)**均**经该门;
  仅剩两处裸 `return "closing"`:graph.py:61(门自身终点)与 graph.py:86(post-ask `ask_decision` 耗尽终点)——**两处都是设计 §⑥-B「防无限环」明文豁免项**(post-ask 重问=活锁)。
  ∴ 代码语义完全符合、覆盖面比设计「6 条」措辞**更完整**;唯一差异是 helper 名 `_gather_or_close` ≠ 设计文本 `_flush_then_close`。
  **建议**:DESIGN 文档 §⑥-B 措辞回填为 `_gather_or_close`、把「6 条裸 return」更正为「所有 pre-ask closing 边」(文档非我写权域,交文档 owner)。

- **D2 · §2 DNS lint 命名**:设计规定「`_DOMAIN_TOKEN_RE` 去 TLD 白名单锚,改裸标签扫描」。
  实际实现为函数 `_check_dns_label_limit()`(structural_gate.py:1108),双闸(①DNS 名承载命令行:dig 名参数/sdns host name|pool/hostname;②纯域名 token,排除 flag/@server/key/续行),对每个 `.`-切分标签查 >63(RFC 1035)。
  语义与设计一致,且注释(1098-1102)明确规避「关键字行任意长串」强字典误杀(GA-CUT)。名 `_DOMAIN_TOKEN_RE` 不存在。**建议**:文档措辞回填。

- **D3 · §③ 行号漂移**:设计标「clean re-emit 不清旧台账,`emit_xlsx_tool.py:677-678`」。现 677-678 已漂移为命令匹配 misses 逻辑。设计裁决=**记录不修**,无需动作;仅注记行号漂移。

- **D4 · 旁支(非 dongkl-doc,CLAUDE.md 陈旧)**:CLAUDE.md 引用引擎路径 `main/ist_core/compile_engine/`(实为 `compile_engine_v8/`),并引用回归锚 `tests/ist_core/compile_engine/test_final_full_verify_routing.py`——全 `tests/` 不存在该文件。属 CLAUDE.md 文档陈旧,非我写权域(CLAUDE.md 不归任何代码流),记录交文档 owner。

- **D5 · 测试锚命名漂移(语义符合)**:设计各 §「测试锚」列的**函数名是示意性**的,已落地测试**断言同一不变量但函数名不同**:
  §⑥ `test_awaiting_user_not_starved_by_persistent_broken`→实 `test_gather_fires_despite_persistent_broken`(test_gather_ask.py:135);
  `test_awaiting_user_flushed_before_error_closing`→实 `test_flush_awaiting_user_before_error_and_stuck_closings`(:45);
  `test_broken_rerun_budget_terminates_per_case`→实 `test_reconcile_broken_streak_escalates`(test_broken_third_state.py:118)。
  §④ Errored/Blocked 路由由 `test_route_broken_errored_to_attribute_then_author`(:194,断言 `_after_reconcile({"n_broken_errored":1})=="attribute"` ∧ `_after_diagnose(...)=="author"`)+ `test_reconcile_errored_writes_mechanical_reflow`(:201,断言机械 reflow 不调 LLM)覆盖,与设计逐字对应。
  ∴ 测试**真验设计不变量**,仅名字与文档示意不符——与 D1/D2 同源(文档标识符落后于代码)。建议文档 owner 可选回填测试名。

---

## 2 · #3 冗余注释治理清单

**扫描**:40 个 `.py`(compile_engine_v8/case_compiler/tools),抽「≥3 行连续块 + 任意带日期/6 位案号的叙事型」,
docstring 不纳入(行为契约永久 KEEP)。共 **234 块**:**(a) 冗余于 dongkl 设计文档=16**、**(b) 有价值不在该文档=142**(~40 富矿/~100 中低)、**(c) 安全/契约/贴身 why 必保留=76**。

### 2.0 执行决策(重要 —— 本轮**不就地缩写**,只交付治理清单 + 富矿归档)

按红线「零回归 / 行为零变化」+ CLAUDE.md #12「紧贴代码的 why 保留」权衡,**本轮不机械缩写注释**,理由三条:
1. **(b) 的冗余多是对更广语料(§18.x/(44)/(45)/§11.x 在 DESIGN_v8/THEORY_k)不是 dongkl 文档**——逐条确认目标§是否真收录需读那两份大文档(非我写权域),未确认即缩=可能丢案号级独有知识(违 #2「别猜」)。
2. **(a) 逐块细看多为承重的码址 why**(如 `graph.py:69-73/135-138` 解释 run17/668044 路由取舍;`nodes.py` 门配对 rationale)——缩成「见 DESIGN §X」会降低码址自解释性、把代码耦合到 delta 文档(该文档自述「取代 DESIGN_v8 §18.15」,§号未必稳)。
3. 活设备跑(zhaiyq)+ 5 队并发编辑期间,对 146KB nodes.py 等做数十处注释 churn,累积失手概率对「行为零变化」是实打实的风险面。
→ **交付**:①富矿 (b) 逐字已归档 `team2_designdoc_additions.md`(保全知识);②本节给**完整可执行清单**(逐块 file:line+类+目标§+动作);③建议缩写由**确认目标§收录后**的专项轮(文档 owner 参与)做。**team-lead 若要本轮执行缩写,给一句指令我按清单办**(先富矿归档在先,已就绪)。

### 2.1 (a) 类 16 块 —— 冗余于 dongkl 设计文档(缩写候选,保留契约行)

| # | 文件:行 | 设计§ | 动作(缩写时) |
|---|---|---|---|
| 1 | `compile_engine_v8/nodes.py:1027-1033` | §④ | 「见 DESIGN §④」+**保留 broken_subtype 契约枚举** |
| 2 | `compile_engine_v8/nodes.py:997-1004` | §⑥ | 「见 DESIGN §⑥/(44)」 |
| 3 | `compile_engine_v8/nodes.py:2245-2247` | §⑥-B | 「INV-flush,见 DESIGN §⑥-B」 |
| 4 | `compile_engine_v8/views.py:19-22` | §④ | 「见 DESIGN §④」 |
| 5 | `compile_engine_v8/views.py:111-114` | §④ | 「见 DESIGN §④」 |
| 6 | `tools/device/batch_tools.py:799-805` | §④ | 「见 DESIGN §④」+**保留硬码取值枚举** |
| 7 | `compile_engine_v8/graph.py:140-142` | §⑥-B | 「见 DESIGN §⑥-B」 |
| 8 | `tools/device/checker_tool.py:46-48` | §3.1 | 「成对机制 checker↔worker.md,见 DESIGN §3.1」 |
| 9 | `compile_engine_v8/engine_tool.py:212-214` | §B/§3.1 | 「见 DESIGN §B/§3.1」 |
| 10 | `tools/ask_user/__init__.py:88-91` | §2 | 「答后残留修复,见 DESIGN §2」 |
| 11 | `compile_engine_v8/graph.py:69-73` | §⑥ | 「见 DESIGN §⑥(§16.6 actionable)」 |
| 12 | `compile_engine_v8/graph.py:135-138` | §⑥ | 「见 DESIGN §⑥(部分作答不 closing)」 |
| 13 | `compile_engine_v8/_shared.py:228-230` | §⑥ | 「actionable 谓词,见 DESIGN §⑥」 |
| 14 | `compile_engine_v8/engine_tool.py:221-224` | §B/§3.1 | 「见 DESIGN §B/§3.1」 |
| 15 | `tools/device/batch_tools.py:755-762` | §④ | 「见 DESIGN §④ window-audit」 |
| 16 | `tools/device/structural_gate.py:1097-1102` | §2/§0.1 | **保留 RFC 63 契约首行**,缩 GA-CUT/994838 叙事 |

**注**:#1/#6/#16 内含机读契约成分(broken_subtype 枚举 / 硬码取值 / RFC 63 常量),缩写只删案号叙事、**契约行不动**。

### 2.2 (b) 富矿(逐字已归档 `team2_designdoc_additions.md`)

Top 8 + 候补见 additions 文件 §A/§B:`fail_attribution.py:26-35`(三 marker 表已删实证)、`nodes.py:755-760`(s₀ 复跑闸/写权律)、`nodes.py:257-262`(开工必净)、`nodes.py:1765-1769`(s₀ 截断顺序)、`emit_xlsx_tool.py:1384-1390`(\n token 经济学)、`run_case.py:192-201`(single-flight 为何不判静动)、`briefs.py:201-206`(词表→语义撤退)、`compile_prep.py:169-173`(族键量化)。候补:`structural_gate.py:669-677`、`batch_tools.py:738-745`、`distribution_assertion.py:188-190`、`footprint_writeback.py:61-63`。

### 2.3 (b) 中低价值缩写候选(逐块 file:line;缩=删日期/案号、留机制一句)

**nodes.py**(146KB,42 b):40-42(bed 残留)、118-120(§11.9 续跑)、167-170(床账接力/(26))、177-179(基线面 run18)、208-210(§18.3 mirror 锚)、324-326(§18.11 F6)、411-416(§19.5 台账缺口)、522-525(§18.11 F6 豁免)、567-577(§18.14/§18.13 形态)、735-746(§B F1/§14-R4)、786-789/826-850(合并/终验幂等)、947-980(§18.2 INV/合并契约)、1297-1346(§17/§18.6/echo)、1376-1450(X8/§11.11)、1559-1562(文法数据)、1746-1913(§18.12/§18.14 s₀)、2048-2163(问询折叠/(41)/(20))、2291-2377(基线面/床恢复/§17)、2440-2497(§14-R5/§11.9)。
**emit_xlsx_tool.py**(24 b):33-35/1079-80/1155-57/1177-81/1335-37/1434-36(载荷)、298-305/432-79(恢复识别/§18.11)、1074-77/1117-20(组合子/V6)、1208-52(冻结/user_decision·标§A)、1322-37(provenance)、1476-80(单调门·标§0.1)、1587-1724/1753-55(凭证门)、1874-77(runtime_fill)、593/884(低价值)。
**batch_tools.py**(15 b):625-662(可观测性/§18.5)、816-818((30))、1146-48(§3.2)、1192-1296(归因护栏/合并/信封)、1370-73(perf)、388/1161(低价值)。
**其余**:`structural_gate.py:197-99/588-89`;`device_mcp_client.py:816-18/1099-1101/1172-74`(1099≡1172 **逐字重复**,归 1 份缩两处);`grade_extract_script.py:91-107/336-70/463-65`(分布/membership·多标§A);`precedent_tools.py:81-345/675`(标§A/§B);`bed.py:330-584`(床态/床恢复);`fail_attribution.py:242-291`(§B/(40)/信封);`briefs.py:80-182`(echo/§18.11);`engine_tool.py:98/271-280`(折叠/echo);`views.py:88-97`(§18.11/合并);`questions.py:82-118`/`remedies.py:60-62`/`uncertain.py:115-117`;`blocks.py:37-122`;`footprint_lookup.py:20-331`;`runtime_fill_tools.py:120-25`;`verifiability_tool.py:303-346`;`compile_prep.py:204-206`;`ask_user/__init__.py:215-237`;`skills/__init__.py:88-90`。

### 2.4 (c) KEEP 76 块(一律不碰)

安全边界(沙箱 `file_tools.py:199-209`、凭据 `device_mcp_client.py:122-124`、毁灭命令 `structural_gate.py:663-664`/`run_case.py:576-578`/`config.py:98-100`、`agent_define.py:29-31`、`ssh.py:76-78`)、机读契约(框架分发/寄存器列义/协议 token/载荷通道/id 门/闭集来源)、≤2 行贴身 why——**即便自带日期/案号也 KEEP**(删这些 why=回归风险)。docstring 全 KEEP(含 `graph.py:51 _gather_or_close`〔非 `_flush_then_close`,见 §1.2 D1〕引 §⑥、`views.py:134` 卷指纹引 §⑥——行为契约不算冗余)。

---

## 3 · #4 命名与结构统一清单

**扫 86 文件(AST + 全 repo grep)**:camelCase 入侵=**0**、标识符含 CJK=**0**——callable/var 100% snake_case,
Chinese 只在注释/字符串/user-facing。命名纪律整体优秀。

### 3.1 已执行改名(4 个模块内私有 helper,零跨文件引用,已连带改齐 + 测试证零回归)

| 旧名 | file:line | 新名 | 验证 |
|---|---|---|---|
| `_ru` | `case_compiler/device_mcp_client.py:644`(嵌套闭包) | `_read_until` | 5 处全在文件内(def+4 call);规避 `_run_clientside` 子串碰撞(targeted edit) |
| `_mine` | `compile_engine_v8/remedies.py:25` | `_facts_for_aid` | 3 处;`_mine`(possessive/动词歧义)→表意清 |
| `_kids` | `tools/device/compile_prep.py:42` | `_node_children` | 4 处;补齐 `_node_*` 族(与既有 `_node_data:46` 一致) |
| `_text` | `tools/device/compile_prep.py:38` | `_node_text` | 6 处;规避 `.read_text()`/`.write_text()` 子串碰撞(targeted edit);补齐 `_node_*` 族 |

**安全护栏(执行前逐条过)**:①全 repo `\bNAME\b` 仅现于本文件、零 quoted/getattr;②新名零碰撞;③子串 vs 词界计数对比——
`_ru`/`_text` 子串碰撞(`_run_clientside`/`read_text`)→**禁 replace_all,改逐行 targeted**,`_mine`/`_kids` 计数相等→replace_all 安全。
**回归证据**:diff 纯 4 改名零副作用;`py_compile` 三文件 OK;`tests/ist_core` 1153 passed、`compile_engine_v8+case_compiler` 506 passed(含 object_normalizer 15)、全 `tests/` collect 2036 无 ImportError。

### 3.2 同概念异名 —— 全部报告不改(冻结或高爆炸半径)

- **`autoid`(477)vs `aid`(580)= 同一值**:`autoid`=盘上 JSON 台账**键**(engine_ledger/last_run,`f.get("autoid")` 全仓串引)=**冻结**;`aid`=内存变量简写。统一会砸序列化契约;真要统一只能改**变量** `aid`→`autoid`(580 处/19 文件,高爆炸半径,leave)。`case_id`(download_case)=外部禅道用例集 id,**另一概念、正确区分**。
- **`case`(468)/`volume`=卷(54)/`sheet`(33)**:xlsx 层级重载——`case.xlsx` 其实是**卷**(含 N case),`sheet` 兼指 openpyxl worksheet 与「卷 sheet/per-case sheet」。跨 42 文件,改=高爆炸半径,**观察记录不改**。
- **`fork`(99,机制)vs `worker`(99,角色)**:`nodes.py:91` 明写「与 fork 孔区分」,**刻意分**。`孔`/hole=文档伞概念、代码从不用(码↔doc 术语 gap,低危)。
- **`brief`(72)vs `task`(27)**:非冲突——`task` 是 deepagents 派发工具名(graph.py 串引**冻结**)/agent def `<task>` 节/`TaskType` 态/设备 task log 四义,无 brief 混用。
- **前缀不一致**:①校验门 `structural_gate._check_*`(19)vs `emit_xlsx_tool._gate_*`(7)——各自文件内一致、跨文件同概念两前缀(报告不改,跨文件统一属高风险重构);②`compile_prep` 的 `_node_data` vs `_text`/`_kids`——**本轮 §3.1 已修齐**。

### 3.3 结构(报告不改 —— 重构=行为风险)

**超 120 行函数 34 个**(最长:`emit_xlsx_tool.compile_emit` 657 行 958-1614、`batch_tools.dev_run_batch` 397、`dev_run_batch_digest` 338、`nodes.closing` 318、`grade_extract.extract` 294、`compile_emit_merged` 266、`nodes.ask_contradiction` 235、`nodes.attribute` 204、`nodes.reconcile` 196…);热点文件 `emit_xlsx_tool.py`/`batch_tools.py`/`nodes.py`(7 个引擎节点 135-318 行)。
**深嵌套 >4 层 24 个**(最深:`ist_core/graph.py:193 on_llm_end` 8 层、`batch_tools.py:1052 dev_run_batch_digest` 7、`structural_gate.py:1027` 7…)。
均**只记录**:引擎节点是 StateGraph 纯函数、重构=行为风险,违「零回归」红线,建议留待专项重构轮(带完整行为对照)。

---

## 4 · #6 V6 前遗留冲突处置清单

**方法**:全 repo grep(import + 字符串引用 + 动态加载 + tests + registry/json/md)逐机制核 DEAD/LIVE。
**独立复核纠错**:子 agent 把 `object_normalizer.py` 判为「仅被死 corpus.py 引用→git rm safe」——**实测错**:
`tests/case_compiler/test_object_normalizer.py` 直接 import 并跑 15 passed(现绿),它是 LIVE。若照子 agent 建议删对,
=测试崩=回归。∴ 对任何删除类结论**必自查 tests**,已逐条复核下表。

### 4.1 我写权域内的处置

| 机制/文件 | 判定 | 消费者证据 | 处置 |
|---|---|---|---|
| `case_compiler/object_normalizer.py` | **test-only 孤儿候选**(corpus 删后) | 生产消费方仅 `corpus.py`(已删);`object_normalizer.py:5` docstring 声称 `framework_sync 同步时一并采集`——**grep 证伪:`main/framework_sync.py` 从不 import object_normalizer**(旧 docstring 的虚假消费声称);现仅 `test_object_normalizer.py`(15 passed)覆盖 | **本轮保留**(team-lead 2026-07-16 裁决):①同日已被误判"可删"一次(实有 15 测试),二次反转无用户过目=正撞红线要防的误删类;②有测试、零成本保留;③删它连带删 15 通过测试——**留用户专项轮**连 framework_sync 虚假声称一并裁。docstring 已清 corpus 引用并注明 test-only 现状 |
| `case_compiler/corpus.py` | **DEAD → 已删** | import=0、公开符号(`IdiomCorpus`/`CorpusCase`/`_parse_py_case`)在 .py 零使用、tests=0、`__init__` 不自动导入 | **已 git rm(2026-07-16 team-lead 裁决)**;in-area 注释引用(object_normalizer docstring×2)已清;`framework_sync.py:36`/`r2_fixture_distribution.py:3` 注释非我写权域、CLAUDE.md 模块表行 team-lead 终局改。删后 collect 2042 无 ImportError + tests 1340 passed |
| `tools/device/compile_pipeline.py` | **LIVE** | `compile_engine_v8/_shared.py:258` import `_emit_progress`(唯一活消费);内含死 helper `_grade_extract_facts`/`_project_root`(0 caller) | **保留文件**;CLAUDE.md「compile_pipeline 全删」措辞不准(实剩 3 helper,`docs/REVIEW_theory_vs_impl.md:28` 已如实记) |
| `tools/device/grade_extract_script.py` | **LIVE** | `tests/ist_core/skills/test_grade_extract.py`(19 用例契约)+ `scripts/debug/grade_extract_equiv_sweep.py`(CLAUDE.md 引 511 卷反扫验收器);runtime 不可达(唯一 loader `_grade_extract_facts` 已死) | **保留**(测试+文档承重;docstring 5 检测器映射表被 CLAUDE.md 指为权威位) |
| `provenance_ir.py` `skeleton_ref` 字段 + `blocks.py` `"skeleton"` source.kind | **LIVE-inert** | schema 枚举,无生产者但序列化/校验仍读 | **保留**(删=provenance-JSON schema 变更,可能拒历史卷;非本轮范围) |
| `structural_gate.py:1148` `lint_xlsx_case` docstring | 陈旧引用 | 提到已删工具 `submit_verdict/compile_score`(现凭证路=`compile_emit` 落 `.grade_credential.json`) | 低风险文案订正候选(见 §2 注释治理;非行为契约) |
| `compile_pipeline.py:7-8` docstring | 陈旧路径 | 指向不存在的 `compile_engine/nodes/*` | 低风险文案订正候选 |
| `resilience.py:280,292-293` 注释 | 陈旧 | compile_pipeline 残留注释 | 低风险,归 §2 |

### 4.2 corpus.py — 推荐删但不擅删 → **已按 team-lead 裁决删除(2026-07-16)**

**结局**:team-lead 裁「corpus.py: 删」。已 `git rm`,in-area 注释引用(object_normalizer 两处 docstring)已清,CLAUDE.md 模块表行按指令留给 team-lead 终局。验证:collect 2042 无 ImportError + tests/ist_core+case_compiler 1340 passed。**副产**:object_normalizer.py 随之成 test-only(生产消费方仅 corpus),去留另裁。

以下为当时「不擅删」的评估留档(佐证为何先报告后删是对的):代码判据上 corpus.py 确为死码(其 docstring 自述被 `precedent_tools._load_mirror_corpus` 取代)。**不擅删的三条理由**:
① **CLAUDE.md 工具目录表把 `corpus` 列为 `main.case_compiler` 活模块**(`config / env_pool / device_mcp_client / corpus / xlsx_emit`)——删后该权威文档失真,而 CLAUDE.md 非我写权域,无法同步订正;
② 两处**注释引用**在非我写权域文件(`framework_sync.py:36`、`r2_fixture_distribution.py:3`),删后成悬空注释我无法清;
③ 子 agent 在**同目录姊妹文件**已误判一次(object_normalizer),destructive 动作在 6 队共享「不允许回归」红线下宜先经 team-lead 确认。
→ **建议**:team-lead 一句确认即 `git rm main/case_compiler/corpus.py`,随后我跑全量 `--collect-only` + `tests/case_compiler` 证无回归;并把 CLAUDE.md 模块表 `corpus` 删除交文档 owner。

### 4.3 非我写权域(仅报告,交对应 owner)

- **死 debug/eval 脚本**(`scripts/` 非我域):`run_v3_compile.py`/`diag_one_draft.py`/`measure_prefetch_ab.py`(import 已删符号)、`eval_distribution_assertions.py`/`eval_membership_assertions.py`(import 不存在的 `main.ist_core.skills.ist_compile_grade` 路径)——全已 broken、不在 CI,建议 owner git rm 或修 import 路径至 `main.ist_core.tools.device.grade_extract_script`。
- **模型 env(`agents/_llm.py` 非我域)**:`IST_REVIEW_MODEL`(`_llm.py:647`)/`IST_HAIKU_MODEL`(`_llm.py:668`)=活 back-compat 读、保留;`IST_OPUS_MODEL`/`IST_SONNET_MODEL`=读分支已删除、仅 docstring/CHANGELOG 残留、无死分支可删。
- **CLAUDE.md 陈旧**:引擎路径写 `compile_engine/`(实 `compile_engine_v8/`)、`compile_pipeline 全删`(实剩 3 helper)、回归锚 `test_final_full_verify_routing.py`(全 tests/ 不存在)。交文档 owner。

---

## 5 · 跨队移交处置(tui/hygiene 队移交到我写权域)

处置原则(team-lead):**能钉窄口 + 有测试兜底才修,否则记报告移交;零回归**。回归对账基线=**2026 passed**(`--ignore=tests/ist_core/tools/test_batch_compile_tools.py`——其 5 failed 是 SSH 忙碌床的既有环境依赖,非回归)。

### 5.1 【已修+测试】item1 · emit_tick 丢 broken 三态(tui 队移交)

- **根因**:`_shared.py` `emit_tick` 把 V8 内部 **13 态**投影回 footer **九态**词汇时,`broken`/`broken_errored`/`broken_blocked` **三态无桶可入**(活证 29906 round1:footer 桶和 51 < total 53,broken 案凭空消失)。
- **修法**(纯遥测完整性,**不碰编译行为**):broken 三态是"非通过/非终态/仍在编译环内(复跑/reflow/env 呈报)"→ 折进 `failed_active`(九态词汇里最近的非通过桶)。并把投影抽成纯函数 `_footer_bucket_counts()`(零行为变化、可单测)。
- **测试**:`tests/ist_core/compile_engine_v8/test_footer_projection.py`——**动态枚举 views 全部 case 状态**断言 Σ九桶==状态数(残差 0);日后新增状态漏投即红(正是本坑型)。
- **验证**:45 passed(含新 3)+ 广扫 ist_core/ink/tui **1461 passed**。

### 5.2 【已修+测试】item3 · needs_decision/user_decision 非原子写(hygiene 队移交)

- **根因**:`verifiability_tool.py:97/370` 两处 `write_text(json.dumps(...))` 非原子——Ctrl-C/崩溃打断留截断文件(96 份交付中 1 份 `needs_decision.json` 截断实证);`user_decision.json` 还是「先问后落」放行凭据,截断=凭据失效。
- **修法**(内容逐字节等价、仅崩溃安全性变化):加 `_write_json_atomic()`(tmp+os.replace,同 `batch_tools` last_run 先例),两处改调它。**兄弟扫描**:`last_run.json` 已原子(batch_tools:1270);`engine_report.json`/`attr_evidence`(nodes.py)是收尾/单轮写、非跨轮凭据台账,风险低,**未改**(记此备查)。
- **测试**:`tests/ist_core/tools/test_verifiability_atomic_write.py`(有效 JSON + 无 .tmp 残留 + 内容与旧 write_text 逐字节等价);既有 `test_user_decision_tool.py` 13 passed 继续绿。

### 5.3 【已修·方案 b(team-lead 裁决)】item2 · dongkl 主卷泄漏 failed_terminal 案

**结局**:team-lead 裁「本轮做方案 b——交付对账门加组成核对,方案 a(重合并)留行为修复专项轮」。已实现:
- **门**:`closing` 交付对账段加 `_volume_composition_check(mdir/case.xlsx, deliverable)`(`nodes.py`,复用 `batch_tools._xlsx_real_autoids` 读实际卷内 autoid 集)——比对 `case.xlsx` 实际组成 vs deliverable 集,`leaked`(卷含非交付案)/`absent`(交付案缺席物理卷)任一非空 → 落 `volume_composition_mismatch` 事实 + `outcome` 如实降级 `delivery_incomplete` + 报告标 `volume_composition_mismatch`。**纯加门,不碰 merge 元数据(moved_tail/coexist/merged 事实)不变量**;卷读不出 autoid→fail-open 不误报。
- **恢复设计符合性**:设计承诺「deliverable N == case.xlsx 内容」,本门令 swallowed verdict 结构上不再静默过关(778041 型:卷 23≠报告 22 → 门报 leaked + 降级)。方案 a(按 deliverable 重合并纠正物理卷)涉 moved_tail/coexist 重设计,留行为修复专项轮。
- **回归测试**:`tests/ist_core/compile_engine_v8/test_volume_composition_gate.py`——①failed_terminal 案在卷中→门必报 leaked ②卷==deliverable→零失配(happy-path 零降级)③deliverable 缺席物理卷→报 absent ④卷读不出→fail-open 不误报。4 passed。
- **验证**:closing 邻域 50 passed;full 忽略 batch_compile **2007 passed/0 failed**;full collect 2046。

以下为原始根因分析留档(方案抉择依据):

- **现象**:`workspace/outputs/dongkl/case.xlsx` 实 23 案 ≠ `engine_report` 的 22 deliverable;failed_terminal 案 `203031753342778041` 混入主卷。
- **根因链**(代码级钉死):
  1. 交付主卷 `case.xlsx` = **最后一次 delivery merge 的物理卷**(`nodes.py:841 compile_emit_merged(comp_ordered)`);其 `comp` 集(`nodes.py:780/782`)= **全部 live 案**(含 S_FAILED/S_BROKEN 等,非仅 deliverable)——为跑终验必须全纳入。
  2. `closing`(`nodes.py:2372`)只据**当前 view** 算 `deliverable`(22)写报告、`_stash(deliverable,"delivered")`——但**从不按 deliverable 重滤/重合并物理 `case.xlsx`**。
  3. 当某案(778041)"整卷复验过后被推翻(先例撤销)→ 经用户止损转 failed_terminal",且其后经 `ask_contradiction→closing` 路径**未再触发 delivery merge**(它已被止损、`live` 排除它,但没有新 merge 去重生 case.xlsx)→ 物理卷仍是含 778041 的旧卷。
  4. `closing` 的交付对账门(`nodes.py:2525`)只查交付物**文件存在性**,**不查 `case.xlsx` 的案数/组成 == deliverable 集**——故泄漏静默过门。
- **建议修法**(交 team-lead 定):`closing` 落交付前,若"最后 merged 卷 composition ≠ 最终 deliverable 集"→ 按 `deliverable` 重合并 `case.xlsx`(happy-path composition==deliverable 时为 no-op,零行为变化;仅泄漏批激活=正是纠正)。**难点/风险**:重合并需同步重算 `order_volume`/`moved_tail`/`coexist` 并更新 `merged` 事实,否则报告元数据与新 `case.xlsx` 不一致——此元数据一致性是不擅修的主因。**回归测试锚建议**:构造"曾 pass 后转 failed_terminal 的案 ∈ 最后 merged composition"的 state,断言交付 `case.xlsx` 的 autoid 集 == deliverable 集。
- **替代最小方案**(若不重合并):把交付对账门(2525)扩成"`case.xlsx` 案数 == deliverable"的**组成核对**,失配则 `outcome` 降级 `delivery_incomplete` + 落事实——**不修泄漏但止血(fail-loud)**,风险远低于重合并。二选一交 team-lead。

### 5.4 附:batch_tools 探测测试注入点(team-lead 问)

未深挖 `batch_tools.py` stale-run/SSH 探测逻辑(非我 item、且不宜对忙碌床发 SSH)。仅记:其密闭化归 hygiene 队(tests 侧),如需测试注入点建议由该队在 `_window_audit`/`fetch_batch_details(min_epoch=…)` 处注入 mock 跳板机 epoch/stat,而非真 SSH。
