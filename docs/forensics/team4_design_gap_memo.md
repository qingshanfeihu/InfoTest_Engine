# team4 设计缺口 memo（Design 起草 · 2026-07-20）

**性质**：草文 memo，**未改 DESIGN 正文**——条款上正文需用户裁决（team-lead 2026-07-20 授权：只写 memo）。
**证据边界**：基于 `git show 1e0e0298`/`09373283` 全 diff、DESIGN_v8_engine.md + DESIGN_dongkl_finalization.md 全文 grep、THEORY_k_state_machine.md (15) 补注、`test_delivery_idempotency_gate.py` 逐行、上述实现文件行级读取确认；**未跑 pytest**（引用的 2329/2318 数字来自 commit message，非本次亲验）；未上设备。

**修订记录**：2026-07-20 ① 节整节重写（team-lead 授权）——原草文的「三态状态机」方案作废，改为「台账向事实流对齐 + 推广既有回执样板」，依据是 code review 新取证（见 §①）。同日 ②-A / ③-A 升级为**可直接采纳的条文草稿**（含挂点 §号、条文正文、守门测试锚），②-A 另据 E2 全库普查新增不变量⑶。②-B / ③-B 维持 memo 态未动。同日再补 §24 附「出处标记词体系」（team-lead 裁决②③落条：配对置信强档 + 第五 population 档名）。

**本轮新增证据的归属**：`config.py:83` 硬编码 build 兜底、`bed.py:518-520` 探针取实测值——**我本次亲读确认**；「全库 1110/1110 条 `build==568`、零真值」的统计数字来自 **team-lead 盘面复验**（我未自行普查），条文引用时按此归属。

---

## ① #62 needs_decision 台账卫生条款（草文 v2·2026-07-20 重写）

### 现状（读证实）

| 事实 | 锚点 |
|---|---|
| claim 落盘：同 case 多 claim 按 `claim_kind` 合并 | `verifiability_tool.py:142-161`（`_land_needs_decision`） |
| 同 kind 重落＝**整条替换**（先 filter 掉旧的再 append） | `verifiability_tool.py:160-161` |
| claim 被问询消费：台账是**锚**，问题文本由它派生 | `questions.py:3, 177-180` |
| 交付门读 `ev==needs_decision` 事实判收口 | `report_gate.py:54-58` |
| resume 重开：非欠定类/无 claims → 不重开 | `nodes.py:387-424` |
| **无 resolved/refuted 状态位，通用删除路径缺位** | grep `main/ist_core/**/*.py`：除 :160 同 kind 覆盖外，通用路径**零处**标记 claim 失效 |

**code review 补充取证（2026-07-20，本轮新增，改变了修法方向）**：

| 事实 | 锚点 |
|---|---|
| ⭐**回执样板已存在**：证据被接受后剔除同命令 stale claims、全空则**删整个文件** | `emit_xlsx_tool.py:698-712` |
| ⭐**回执语义已存在于事实流侧**：交付门按 `question_id` 配对判未答（有回执） | `report_gate.py:57-60` |
| 而问询层读**台账原件**组题（无回执）→ **双账不同源** | `questions.py:177-180, 190-198` |
| 第二生产者绕过 `_land_needs_decision`、自实现合并、裸写 | `emit_xlsx_tool.py:747, 831, 758, 841` |
| 消费侧零写回：读台账复制锚 → 只写 `user_decision.json` | `verifiability_tool.py:448-491` |
| stale claim 三处反噬：resume 重开 / 题面 / `_mech_only` 活锁复发 | `nodes.py:411-413`、`questions.py:190-198`、`verifiability_tool.py:470-472` |
| claims 随案存档跨批回喂（清理只删 manifest/last_run） | `nodes.py:3105-3125` |

**后果（#54 实证）**：SSL 003 的 YES claim 与 teardown claim **两条均误报**，但台账无失效期、无设备回写通道 → 归因链把 stale claim 当 ground truth，绕了一层弯路才由 `dev_run_case` 设备真错（全角逗号 → `get_parameter` 拆参失败 → importKey TypeError）收敛。教训见 `team4_calib_batch54.md:97`、长期记忆 `[[needs-decision-emit-claims-can-be-false-positive]]`。

### 条款草文（v2，2026-07-20 重写）

**方案更替说明**：v1 草文提「claim 三态状态机（open/resolved/refuted）」。**作废**——上表两条 ⭐ 取证显示：回执机制在系统里**已经存在两处**（emit 的失效样板 + 事实流的 `question_id` 配对），缺的不是状态机，是**台账没接上这两处**。新造状态机＝在已有构造旁边再立一套，违 `[[framework-capability-before-limitation]]`（判"框架做不到"前先查是不是没用已有能力）。v2 改为**对齐 + 推广**。

> **§X. needs_decision 台账卫生（#62）**
>
> **一、权威序（不变，v1 唯一保留项）**：`device error（上机实测） > gate claim（编译期静态判据）`。gate claim 是**假设**不是事实——`(18) 审计器权威` 的推论：被审计假设不得反向压过审计机制。归因链正确姿势＝读机读账拿 claim → claim 须经 device run 验证 → device error 才是终判（`[[needs-decision-emit-claims-can-be-false-positive]]`，#54 SSL 003 两误报实证）。
>
> **二、台账向事实流对齐（治「消费无回执」）**：交付门已按 `question_id` 配对判未答（`report_gate.py:57-60`），**该配对即回执**。故 claim 落盘时记其 `question_id`；问询层组题（`questions.py:190-198`）与 resume 重开判据（`nodes.py:411-413`）**改读「有无已配对 decision」，不再读「claims 是否非空」**。事实流是唯一真理源（INV-1），台账降为**投影**——不新增第二套生命周期状态。
>
> **三、推广既有失效样板（治「stale 不消失」）**：`emit_xlsx_tool.py:698-712` 已实现正确形态——**证伪即回执**：证据被接受 → 剔除同命令 stale claims → 全空则删文件。把它从 command_existence 一处**提升为通用能力**（落进 `_land_needs_decision` 同址的 `_retract_claims(autoid, predicate)`），供三类触发调用：①门本轮未复现该 claim（重编后自然消解）；②device error 定位到不同源根因（设备证伪）；③用户裁决已覆盖该 claim。
>
> **四、不做的事**：不自动改卷；不据证伪反推修法（worker 判断面）；claim 仍是**呈报不硬拒**形态（沿 D5/S6，DESIGN:717/742）；台账不承载语义判断——它只是「门说过什么 + 有没有被回执」的机读投影。

### 与现形态的迁移说明（v2）

- **兼容**：`claims[]` 结构与 `claim_kind` 键**完全不变**；新增 `question_id` 可选字段（旧账无此键 → 退现语义，零迁移）。相比 v1 少一个 `state` 字段与全部状态迁移逻辑。
- **改动面（比 v1 小）**：①`_land_needs_decision` 记 `question_id`；②抽 `_retract_claims` 通用函数（内容＝把 `emit_xlsx_tool.py:698-712` 挪出来）；③`questions.py` / `nodes.py:411-413` 两处判据改读事实流配对；④三个 retract 触发点接线。**`report_gate.py` 不动**——它本来就读事实流、口径正确，v1 曾误列为改动面。
- **风险（比 v1 低）**：不触及交付收口门（v1 的主要风险源已消失）。剩余风险在 ②：判据从「claims 非空」换到「事实流配对」属闸门语义变更，按 `[[gate-change-verify-design-intent]]` 需先画状态生命周期（本节即草图）＋机器守门测试；须覆盖「同案二次欠定」形态（`report_gate.py:55-57` 记的 yzg 668 族根因即此）。
- **前置依赖**：P0-1（台账损坏静默清空 + 非原子写，`emit_xlsx_tool.py:735-741/757-758`）已派批前修；本条款的「两出口整体改走 `_land_needs_decision` 统一合并语义」属行为面变更，**排在 #62 评审之后**（team-lead 2026-07-20 分诊）。

### 挂 #62 的位阶复核项（code review 转入，不批前动）

| 项 | 锚点 | Design 定性 |
|---|---|---|
| `dev_help:` attestation 无条件接受 | `emit_xlsx_tool.py:625-626` | L_model 对自身产物自证充当质量门，撞 (47) 红线（grade 之死/DS-2）；位阶应为 L_oracle（探针回执落盘）或降呈报不放行 |
| `forbidden_mechanism` 硬拒且不落 claim | `emit_xlsx_tool.py:328-350`（判据 `domain_grammar.py:110-114` 词表命中意图**原文**） | **#54 两误报最直系兄弟**：内容相关判断落 emit 硬拒位阶（塌缩进 L_struct）＋ 不落账＝reject-and-strand 无台账，用户面无题可问，双违 (47) |

两者均属**门策略变更（用户可见行为）**，随 #62 一并呈用户裁决。

### 批中观察点（不预修，实弹取证）

P1-6 stale claims 跨批回喂（`nodes.py:3105-3125`）：B-1 五案全是带旧 `needs_decision.json` 的续跑案，必然实弹经过。观察靶＝**用户是否被问到已消解的问题**（撞 R5 验收标准①「问人的必须是真问题」，DESIGN:690），证据直接喂本条款。

---

## ② 三处「有实现无条文」补注（草文）

### ②-A footprint 知识可达性（surfacing + 检索可靠性，建议合一节）

DESIGN 全文 grep `surfacing|known_issue|nodes_<version>`：**零命中**——两块修复均无条文。

| 实现 | 锚点 | commit |
|---|---|---|
| 父查浮现子节点 known_issue 标签（治「知识可达但不浮现」） | `footprint_lookup.py:99, 128-131` | 1e0e0298 |
| known_issue 双 schema 渲染（老 `{issue_id,title}` / 新观察式 `{fact_key,content}`） | `footprint_lookup.py:82-93, 215-217` | 1e0e0298 |
| 版本子目录不存在 → 回退默认 `nodes/`（Fix A） | `index.py:392-400` | 09373283 |
| 载入完整性守卫：JSON 损坏＝永久跳过、OSError＝瞬态计数（Fix B） | `index.py:105-125` | 09373283 |

**建议挂点**：新增 **§24**，紧接 §22（worker 数据通道边界）——同属「知识供应链」面：§22 管**通道可达**（worker 够不够得着），§24 管**内容可信**（够着了之后，检索到的东西是不是真的、全的、标注对的）。二者互补不重叠。

> **§24. footprint 知识保真三不变量（#58/#61 驱动）**
>
> footprint 是自愈合四层架构的**判例层**——唯一无限增长层，也是 worker 的经验知识来源。它的失效不像门违例那样报错，而是**静默返空/漏渲/标错**，worker 据此自行探索、重踩已知坑。故立三条不变量：
>
> **⑴ 检索不得静默降级**。版本分区等可选特性缺位时**回退默认树**而非返空（`index.py:392-400`）；载入失败必须区分**永久**（JSON 损坏 → 跳过并告警）与**瞬态**（OSError，如云盘 online-only/sync-lag → 计数、可重试），**不得把两者都吞成「无此节点」**（`index.py:105-125`）。判据锚 `[[signal-licenses-only-what-measured]]`：**零产出 ≠ 结构排除**——查无只授权「本次没查到」，不授权「该事实不存在」。
>
> **⑵ 知识可达 ⇒ 可浮现**。父节点查询必须浮现子节点的 known_issue 标签＋指针（`footprint_lookup.py:99, 128-131`），否则树形组织本身成为知识屏障——知识在库里却读不回，等价于没有。渲染器须兼容自愈环产出的**观察式 schema**（uncertain 观察由 `_ingest_uncertain_observations` 自动入库，渲成空＝自愈环断在最后一米，`footprint_lookup.py:82-93, 215-217`）。
>
> **⑶ 作用域标注不得强于其证据**（2026-07-20 新增，E2 全库普查驱动）。节点上的版本/床作用域锚（`device_run.build` 等）若取自**配置兜底**而非探针实测，必须显式标注来源（`build_source: "config_fallback"`），渲染层**不得**将其呈现为已验证作用域。实证：全库 **1110/1110** 条 `build==568` 全部来自 `config.py:83` 硬编码兜底、**零真值**（设备实测为 585，来自 `bed.py:518-528` 探针）——一个会静默生效的硬编码默认值，让 K 锚在无人察觉时长期失真。这是⑴的**标注维**：⑴管「查不到别装作不存在」，⑶管「不知道别装作知道」。
>
> **不做的事**：本节不规定 footprint 的**写入准入**（那是 #62/R2 的通道纪律面，见本 memo §① 与 knowledge_fidelity_gaps 缺口①）；不规定知识内容的正确性判定（判例层的语义仲裁走 worker 设备实验，非引擎门）。

#### §24⑵ 细化：观察组二分——浮现 ≠ 冒充仲裁（Theory 反向质疑裁定②，2026-07-20）

⑵要求「知识可达 ⇒ 可浮现」，但**浮现的形态不得强于证据本身**（与⑶同源）。观察组须按**语境的来源结构**二分，两类挂不同渲染：

| 类型 | 结构 | 语义 | 渲染 |
|---|---|---|---|
| **印证组** | **单条目**多语境（合并语义产物） | 同一条知识在不同语境下**复现**——是泛化证据，**不是分歧** | 标「泛化证据」，**不挂仲裁指引** |
| **潜在分歧组** | **≥2 条目**各带语境 | 不同条目的语境差异，行为**可能条件相关** | 挂仲裁指引（worker 自主设备实验裁定） |

**为什么这条必须与 B 终形同批**：B 的合并语义会把同节点多语境塌进**一个条目的列表**（正是我会签里指出、需与组头判据同批改的那件事）。合并一上线，若渲染层不做此二分，**所有印证组都会挂上仲裁指引** → worker 被派去仲裁一个**结构上并不存在的分歧**。这是「结构性假仲裁任务」：不是判错，是任务本身不成立——比判错更浪费，且会训练 worker 忽略仲裁指引（狼来了）。

**归族**：本条属⑵的形态维——⑵管「知识浮不浮得出来」，本条管「浮出来之后别把复现说成分歧」。三条不变量的共同形态由此完整：⑴不知道别装作不存在、⑶不知道别装作知道、⑵浮出来但别装作比证据更强。

#### §24 附：出处标记词体系（2026-07-20 team-lead 裁决 ②③ 落条）

不变量⑶不是一条孤立规则——系统里已经长出**三个同型标记**，第五 population 又要再加一个。若各起各的名，三个月后没人知道它们是一回事。故统一成一个族：

> **命名律**：每个标记回答同一个问题——**这一维的知识是怎么来的**。统一形态 `<维度>_provenance`，值域按**强度降序**枚举，弱档值必须自解释（看值即知弱在哪）。

**值域三位（硬要求）**：每维值域统一为**三位 + 空**，位次含义固定——
`强档`（有实测/有出处）｜ **`unspecified`**（**声明了「不知道」**）｜ `弱档`（有具体的弱来源）｜ `""`（字段缺席＝旧账，读侧退保守）。
中间位是关键：`unspecified` **不是弱档**，是**诚实的未知**——正是⑶「不知道别装作知道」的字段级兑现。缺这一位，调用方只能在「谎称强」和「谎称弱」之间二选一。

| 维度 | 字段 | 强档 | 未声明 | 弱档 | 状态 |
|---|---|---|---|---|---|
| 作用域 | `build_source` | `probe` | `unspecified` | `config_fallback` | **已落地**（`batch_tools.py:991, 1371-1386`，出处由调用方声明、函数内不猜） |
| 语法 | `syntax_provenance` | `manual_signature` | `unspecified` | `device_run_verbatim` | S2 已裁，待落 |
| 观察配对 | `pairing` | `volume_verified` | `unspecified` | `heuristic` | 裁决②，待落 |
| 证据出处 | `evidence_provenance` | `sourced` | `unspecified` | **`unsourced_legacy`** | 裁决③（404 条目），待落 |

**字段后缀不强求统一（Design 决定，防返工）**：`build_source` 已随 S3 落地并带三值语义，**不为后缀美观返工**；`syntax_provenance` 已在 S2 裁定。故——**值域统一是硬要求（三位含义必须一致），后缀统一是软要求**（新立字段建议 `_provenance`，已落地的保留原名，本表即对照表）。理由：命名一致性的收益是可读性，返工已验证代码的成本是回归风险，后者更贵。

**⚠第五 population 档名：建议 `unsourced_legacy`，不用 `unverified_legacy`——避免与 `validity` 轴撞车。**
`validity: verified | uncertain` 是**既有且正在用**的轴（自愈环升格判据就在它上面）。用 `unverified_*` 命名会让人以为它是 validity 的一个值，但两轴**正交**：一条条目完全可以 `validity=verified`（行为已被 PASS 实证）却 `evidence_provenance=unsourced_legacy`（当年入库时没记出处）。二者混同会直接污染升格判据的读法——这正是缺口①「三条写回路键空间混淆」的同型病，命名阶段就该拦住。

**裁决②落条（配对置信·强档）**：`extra_candidates` 派生的 uncertain 条目打 `pairing_provenance: "heuristic"`，且**不参与 R2 自动升格**——需显式确认方可升格。理由同⑶：启发式得来的配对不得呈现为已确认的观察；而升格是**不可逆的知识强度提升**（uncertain→verified 后不再降级，`merger.py:427-430` 反向不覆盖），对不可逆动作取保守档是正确侧。

> **⚠行号时效声明（2026-07-20 复核发现）**：本 memo 全部 `file:line` 锚点记于 HEAD `1e0e0298` 的工作树。此后 Py-Eng 的批前修已改动 `merger.py` / `footprint_lookup.py` / `verifiability_tool.py` / `emit_xlsx_tool.py` 等文件（本条锚点即因此从 `362-370` 重定位到 `427-430`）。**条文采纳前须按当时工作树重新定位所有锚点**；语义结论不受影响（我复核了升级分支语义未变），受影响的只是行号。

**已有守门测试**（本节⑴⑵已有覆盖，采纳后可直接引为条文测试锚）：`tests/ist_core/memory/test_footprint_reliability.py`（#58 Fix A/B）、`tests/ist_core/tools/test_footprint_known_issue_surfacing.py`（#61 浮现+双 schema）。**⑶ 无覆盖**——需新增（建议：断言 `build_source` 缺失或为 fallback 时渲染层不输出版本作用域断言）。

（注：⑵ 的 schema 双写兼容是过渡态，`#63 schema 迁移` 收敛后本注需同步。）

### ②-B 可观测/脱敏（建议挂安全面，不与上节合并）

| 实现 | 锚点 | commit |
|---|---|---|
| `<skill_references>` 死指针块整体删除（非修单复数） | `tools/skills/__init__.py:85-100` | 09373283（已有 §22 条文覆盖） |
| 工具事件记全参含 kwargs（治 unlogged-kwarg 诊断死角） | 09373283 diff · observability C | 09373283 |
| 凭证键脱敏（`\bkey\b` 词边界，18/18 无误伤） | 09373283 diff · observability C；sec 报告 `team4_sec58_report.md` | 09373283 |

> **条款草文（挂安全面）**：诊断可观测性与凭证保密是**同一处的两个方向**——记全参治诊断死角（kwargs 不入日志＝故障无法复现），但扩大记录面即扩大泄露面，故二者必须同批落地：日志记录面每扩一次，脱敏词表同步过一次 security 评审（`\b` 词边界而非子串匹配，防 `key` 误伤 `keyword`/`monkey` 类合法字段）。锚 CLAUDE.md「禁止在代码、注释、日志中打印 Token 或 API Key」。

---

## ③ §16.4 ①A 两处欠记补注（草文）

**先行结论：条文与测试语义一致，无矛盾。** DESIGN §16.4（`DESIGN_v8_engine.md:870`）「另增两条件」＝ THEORY (15) 补注的 ⒈⒉（`THEORY_k_state_machine.md:1494-1503`）；⒊「broken 不吸收」是既有语义（测试 `test_broken_composition_breaks_idempotency` 覆盖，锚 commit b3ce3b4b）。测试文件标题「三条件」＝⒈⒉新增＋⒊既有的合称，非条文遗漏。判定纯函数 `nodes.py:913`，调用点 `nodes.py:1076`。

### ③-A 缺字段保守吸收——**条文欠记，建议补注**

- **实现/测试**：旧账无 `bed`/`build`，或当前无 bed → **仍吸收**（`test_missing_bed_build_conservative_skips_1A`，测试注释类比 `_s0_parked` 床锚容错）。
- **条文**：THEORY ⒈ 只写「B 维一变即非同一 ctx_delivery，等价前提破」，未覆盖 **B 维未知**这一档；DESIGN §16.4 同样未记。
- **性质**：这是把「未知」按「同一」处理的**放宽**，方向与条款⒉的安全侧取舍（宁多跑）**相反**——⒉ 保守＝多跑，本处保守＝少跑。旧账升级期确有必要（否则历史卷全部失去幂等），但属显式取舍，应入条文而非只活在测试注释里。
**建议挂点**：DESIGN §16.4（`DESIGN_v8_engine.md:870`）①A 缝合扩展句尾，与既有「续跑代价注」并列；THEORY (15) 补注 ⒈（`THEORY_k_state_machine.md:1496-1497`）同步一句。**不改判定逻辑**，纯条文显式化。

> **条文草稿（可直接粘贴）**：**缺字段容错注**：⒈的 B 维比对在**字段缺失**时取宽——旧账未记 `bed`/`build`，或当前无床锚时，视同满足⒈（`_delivery_verify_skippable` 现行为，测试锚 `test_missing_bed_build_conservative_skips_1A`）。这是**升级期兼容取舍**：否则 bed/build 字段落账之前的历史卷全部失去幂等、每次续跑整卷重验。**方向声明**：本处保守＝**少拒**（放行吸收），与条款⒉的保守＝**多跑**方向相反——两处「保守」不同义，勿互相类推。**代价**：旧账卷跨床续跑存在漏拒窗口（换床但旧裁决无 bed 记录时会被误吸收）。**收紧条件**：待 `bed`/`build` 全量落账后，改为「缺字段 ⇒ 拒吸收」。

**为什么值得入条文**（给用户的一句话）：这是系统里**唯一**一处「保守＝放行」的取舍，且它与紧邻的另一条「保守＝拦截」写在同一条款下——不显式化，后来者按邻近条款的方向类推就会改错向。

**守门测试**：已有（`test_missing_bed_build_conservative_skips_1A`），采纳后直接引为条文测试锚；收紧时该测试的断言需同步翻转，即**测试本身是收紧动作的提醒器**。

### ③-B π 连续维无人检查——**标注为待校验点，非缺陷**

- **条文**：THEORY ⒈ 全文为「同床同版本·**执行连续**……且 π 连续（日志时间链无缺口）」——**两维**。
- **实现**：`_delivery_verify_skippable` 只比对 `cur_bed`/`cur_build`（B 维），**π 连续（日志时间链无缺口）无对应断言**，测试亦无。
- **交叉印证**：`team4_task45_acceptance_checklist.md:18` 记「①A 缝合等价 ◑ 条款在位·仍待断批」「yzg 重跑无断批、未触发」；`team4_leader_research.md:16` 明确把「三条件各自是否有任何一条在现有机制下**无人检查**」列为待校验点——**本次读证实：⒈的 π 维正是那一条**。
- **定性**：**待校验点，不定为缺陷**。理由：⑴ π 断裂的主要现实来源是断批，而断批已由 ⒊ broken 例外从另一侧拦住（覆盖面重叠但不等同）；⑵ 实弹从未触发，无实证判断残余风险大小；⑶ 补 π 检查需定义"日志时间链无缺口"的机械判据（run_marker 时间戳链？stale_log 基线？），属新设计而非补注。
- **建议**：条文加一行「π 连续维当前由 ⒊ broken 例外间接覆盖，未独立接线——待断批实弹校验后决定是否单独机械化」，并保留在验收清单待校验位。

---

## 呈用户裁决清单（Design 建议排序）

1. **#62 台账卫生**——建议立项，条款先行、实现后随。v2 方案＝对齐事实流 + 推广既有失效样板（不新造状态机），改动面与风险均小于 v1；连同两项位阶复核（`dev_help` 自证 / `forbidden_mechanism` 硬拒不落账）一并呈裁。
2. **②-A → 新增 §24 footprint 知识保真三不变量**——条文已备可直接采纳。⑴⑵ 有现成守门测试，⑶（作用域标注不得强于证据）是本轮 E2 普查新增、**无覆盖需补测**。建议与 #62 同批呈裁：#62 管台账卫生、§24 管知识层卫生，同属「机读账可信度」主题。
3. **③-A → §16.4 缺字段容错注**——一句条文、零逻辑改动、已有测试锚，**最低成本项**，建议直接采纳。
4. **②-B 可观测/脱敏**、**③-B π 连续维**——维持 memo 态：前者已由 §22 + sec 报告覆盖大半，后者证据不足以定条款（待断批实弹）。

**四项的共同主题（给用户的一句话）**：#62、§24、§16.4 补注三项都在回答同一个问题——**机器读的账，什么时候可以信**。台账里的 claim 会过期（#62）、知识树的查无与标注会骗人（§24）、幂等闸的"未知"被当成"相同"（③-A）。三处都是「系统说了它不知道，但下游当成了它知道」的同一形态。
