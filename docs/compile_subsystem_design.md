# 用例编译子系统设计文档

> 2026-06-22 生成(多 agent 读真实代码 + plan 文档装配)。覆盖 plan1→现在的演进 + 每模块每函数。
> 配套:`docs/PLAN_footprint_v2_compile.md`(理论)、`docs/PLAN_v3_closed_loop_compile.md`、`docs/batch_compile_architecture.md`。

# 用例编译子系统设计总览

> 本文档描述 InfoTest Engine 中「人工测试用例（脑图）→ 自动化 `case.xlsx`」的编译子系统。开篇总览给出系统定位、架构全景、贯穿全设计的红线，以及分章导航;实现细节见后续七章。

## 一、这是什么

用例编译子系统把**人工测试用例脑图**（`workspace/inputs/automatic_case/*.txt`，mind-map JSON）编译成断言**真覆盖目标行为**的自动化 `case.xlsx`，交给跳转机上的 pytest 框架执行。

它**走平台正路**，不依赖任何外层 driver 脚本（旧 `scripts/debug/agent_compile_case.py` 已退役）：用户在 TUI 让 **main agent** 编译，main agent 作为**编排器**通过唯一编译入口 `ist_compile_batch` skill，把领域工作（查手册、查先例、生成命令、判分）**fan-out 给彼此隔离的 fresh fork 子 agent**。整脑图批量与单条用例走同一流程——单条只是 N=1 特例（prep 出 1 case manifest、fanout 并发度 1、merged 退化为单 case + 哨兵）。

**编译与上机验证解耦**（2026-06-16）：编译链只产出 excel（draft 生成 → grade 断言质量审批 → 合并打包），**不上机**;上机验证由独立的 `ist_verify` skill 对成品 excel 单独做，真机裁决可回流重编译。这样设备环境瞬态故障（SSH 中断、dig 超时、DNS 失败）不会阻塞 excel 产出。

## 二、架构全景

```
  用户(TUI) ──"把脑图编译成 excel" + 目标产品/版本(如 APV 10.5)──┐
                                                              ▼
┌──────────────────────────── main agent = 编排器 (ist_compile_batch skill) ────────────────────────────┐
│  只解析 / 调度 / 判定 / 重做 / 合并 / 上报;绝不自己 grep 手册 / 探设备 / 生成命令              │
│                                                                                                       │
│  [版本闸] 目标产品+版本未提供 → ask_user(不猜默认);版本 → 手册 glob(10.5_cli__part*.md)        │
│                                                                                                       │
│  ① prep                ② draft (fan-out 并发)        ③ grade (fan-out 并发)        ④ merge          │
│  compile_prep   →   compile_fanout         →   compile_fanout         →   compile_emit_merged│
│  脑图→manifest          (ist_compile_draft fork)      (ist_compile_grade fork)      同脑图 grade-PASS  │
│  (零命令,全 null)       fresh subagent / 互相隔离      fresh subagent / 互相隔离      合并+哨兵垫底     │
│       │                      │         ▲                     │         ▲              │             │
│       │                      │         │ 重做意见(回 draft)   │─────────┘ CUT 不救场   │             │
│       ▼                      ▼         │                     ▼                        ▼             │
│  manifest.json          compile_emit ──┤                compile_score      成品 case.xlsx      │
│  (autoid 主键)          [emit 出口闸]  │                (断言质量审批,纯本地)                       │
│                         · IP 可达投影  │                                                            │
│                         · strict_      │   ◄── 供给(只读) ──────────────────────────┐               │
│                           structural   │                                            │               │
│                         [结构门]       │   ┌────────────────┐  ┌──────────────────┐│               │
│                         · 命令头∈allow │   │ footprint 知识树 │  │ env_facts 环境事实 ││               │
│                         · 断言非悬空   │   │ CLI 文法/决策规则 │  │ IP 可达表/拓扑    ││               │
│                         · IP∈env_facts │   └────────────────┘  └──────────────────┘│               │
│                                        │   ┌─────────────────────────────────────┐ │               │
│                                        └───│ 先例检索 compile_precedent (无 embed) │─┘               │
│                                            └─────────────────────────────────────┘                 │
└───────────────────────────────────────────────────────────────────────────────────────────────────┘
                                                              │ 成品 excel(含 <RUNTIME> 占位)
                                                              ▼
┌──────────────────────── ist_verify skill (独立环节,串行上机) ─────────────────────────┐
│  dev_run_batch / dev_run_case(ist_compile_run fork,采 ground truth,不信 verdict 字符串) │
│       │                                                                               │
│  [四层归因] fail_attribution: G错/E错/V错 → 回流重编  |  瞬态(SSH/dig/DNS) → 不回流    │
│       │                                                                               │
│  [上机回填] runtime_fill: 真机真实值填 <RUNTIME> 槽位并**锁死**(只动仍含占位的格子,幂等)│
└───────────────────────────────────────────────────────────────────────────────────────┘
```

## 三、贯穿全设计的红线 / 原则

1. **零硬编码（领域内容不写死）**:skill / agent 定义里**零写死的 sdns / APV 具体命令**;命令、参数、断言期望值一律由 fork 子 agent 现场查手册（`*cli__part*.md`）/ 先例得来。`prep` 产出的 manifest 中 `init_commands` / `steps` / `assertions_provenance` 全部为 `null`,是这条红线的落地点。禁止逐 autoid 硬编码,必须提炼通用范式。
2. **correct-by-construction —— 确定性在闸,自由在过程**:语义决策（测什么 / 什么命令序列 / 什么断言形态,H_G≠0）永远交 LLM;确定性的**类型规则**落在闸里——emit 出口闸（IP 可达投影）+ 结构门（命令头∈手册 allowlist、断言挂在前序观测算子值域上、绑定 IP∈env_facts 可达表）。闸只挡幻觉 / 越界 / 悬空,绝不替 LLM 选骨架。
3. **不救场,诚实 escalate**:交付门槛是 grade 断言质量（弱断言 / 未覆盖 CUT 一律打回,不救场）;fail 如实记遗留,不替用例「想办法 pass」。连续 N 轮 CUT 则 escalate / `ask_user` 上报,不闷头硬编码。
4. **不猜留空 + 真机回填锁死**:离线不可知的运行时期望值,draft 写 `<RUNTIME>` 占位而非瞎猜;`runtime_fill` 只用上机真实输出回填,值抽不出就如实留空;一旦填上、格子不再含占位符 → 结构性幂等,永不被后续覆盖（锁死不靠自律）。
5. **生成 / 评分 / 上机三隔离,消除自评**:draft（生成）、grade（评分）、run（上机）是三个独立 fresh fork,彼此无记忆、互相隔离,根治「自生成自评估」。grade 是断言质量审批,不依赖上机裁决;上机只采 ground truth,不信 verdict 字符串。
6. **版本先行**:不同产品版本对应不同 CLI 手册 / 语法。编译前必须确定目标产品 + 版本（从用户原文提取,缺则 `ask_user`,**不从 config 猜默认**),据此推出手册 glob 写进每条 brief。

## 四、目录

- **一、设计演进**(plan1 → 现在)
- **二、case_compiler**(数据结构与产出底座)
- **三、编译流水线与编排**
- **四、确定性闸门**(emit 出口 + 结构门)
- **五、先例检索 / 上机验证 / 归因**
- **六、footprint 知识树 + 环境事实源**
- **七、skill / agent 编排层**

---

相关源文件路径(供后续章节引用):
- 批量架构现状:`/Users/jiangyongze/.../InfoTest_Engine/docs/batch_compile_architecture.md`
- case_compiler 底座:`/Users/jiangyongze/.../main/case_compiler/`(`case_ir.py` `xlsx_emit.py` `confidence_f.py` `corpus.py` `object_normalizer.py` `provenance_ir.py` `runtime_fill.py` `verify_cache.py`)
- 确定性闸门:`/Users/jiangyongze/.../main/ist_core/tools/device/structural_gate.py` + `emit_xlsx_tool.py`(`_gate_unreachable_ips`)
- 归因 / 回填:`/Users/jiangyongze/.../main/ist_core/tools/device/fail_attribution.py` + `case_compiler/runtime_fill.py`
- 先例 / 置信工具:`/Users/jiangyongze/.../main/ist_core/tools/device/precedent_tools.py`;批量编排:`batch_tools.py` + `compile_prep.py`
- skill / agent:`/Users/jiangyongze/.../main/ist_core/skills/`(`ist_compile_batch` `ist_compile_draft` `ist_compile_grade` `ist_compile_run` `ist_verify`)


---

# 一、设计演进（plan1 → 现在）

人工用例（脑图）→ 自动化 `case.xlsx` 编译子系统经历了五次主要形态。每一版的目标、关键模块、取舍如下。当前生产链是 **V3-R**（`.skill_overrides.json` 中 `ist_compile_v3=on`，`ist_compile_v2/ist_compile_batch=off`）。

## 时间线总览

```
v1 确定性管线  →  四子流程编排  →  入口统一+编译/上机解耦  →  V2 三层grounding  →  V3闭环(负收益)  →  V3-R(砍族摊销)
(纯代码,已删)    (ist_compile_*)    (ist_compile_batch)         (ist_compile_v2)    (回退)            (现生产链)
   41→1丢失       自评分离           grade-PASS即交付            G⊔E⊔V correct-      族摊销实测       provenance/写回/
                                                                by-construction      2634s白烧         四层归因(零额外fork)
```

理论主线是论文《意图实现映射：信息论分解》的 **G⊔E⊔V 三层分解**（`docs/theory_to_implementation_mapping.md`）：实现 token 按来源三分——G=骨架/文法、E=环境常量（IP/设备，查表可得）、V=业务语义（意图特有取值）。主定理 H=H_G+H_V'、E 段=0，定量界定"什么该确定性产、什么该交 LLM"，是 V2 之后所有版本的设计依据。

---

## v1：确定性管线（早期，已删除）

**目标**：把脑图用纯代码管线翻译成 xlsx——extract（抽用例）→ decompose（拆步骤）→ generate（填 xlsx）+ G 列填充 skill。LLM 只做填槽，正确性靠静态闸（pipeline/compiler/anchorer/gates/x1_validate 等共 22 个 `.py`）。

**关键模块（均已删）**：`qa_extract_test_cases` / `qa_decompose_test_cases` / `qa_generate_test_case_xlsx` / `qa_inject_init_and_deps`，配套 `automated-G-column-filling` / `g-column-filler` / `g-column-verify` 四个 skill。清单见 `docs/legacy_compile_pipeline_removal.md`。

**为什么被废弃（实跑实证，`legacy_compile_pipeline_removal.md:11`）**：
1. **41→1 数据丢失**：extract 识别 dongkl 41 用例，decompose 后 cases 数组只剩 1。
2. **自造模板非框架格式**：`test_case_xlsx_generator.py:69` 用 `openpyxl.Workbook()` 造空白簿，表头非框架认的 R28 锚点"自动化ID"→ 上机零 check_point。
3. **G 列空壳 + 计划无上机**：只有步骤骨架，CLI 命令/断言列全空，从不调 `dev_run_case`。

**取舍/教训**：纯代码管线对应 `H_G≠0` 的骨架选择（论文 §4.5 top-1 仅 60%），机械化必崩。这成了贯穿后续所有版本的**最高红线**——"混淆结构约束与骨架选择 = 重蹈被删的纯代码管线（commit `3d63f775`，41→1）"。

---

## v2-arch：四子流程编排架构（commit `88050fa9`）

**目标**：把编译从"确定性管线程序"翻转为"测试自动化工程师 agent"——走平台正路（用户在 TUI 让 main agent 编译），main agent 作**编排器**派发 fork 子流程，不依赖外层脚本（旧 `scripts/debug/agent_compile_case.py` 退役）。设计记录见 `docs/case_compile_orchestration.md`。

**核心变化（根治 v1 三缺陷，`case_compile_orchestration.md:11`）**：
1. **绕过外层脚本** → graph + skill + fork subagent 正路。
2. **自生成自评估分离** → draft（生成）与 grade（评分）拆成**互不通气的独立 fork**，从结构上消除"同一 agent 既生成又给自己打分"。
3. **质量判据有约束力** → grade 的 CUT 是强制反馈，编排器不得推翻后宣布交付。

**关键模块**：`ist_compile_orchestrate`（单条编排器）+ `ist_compile_draft` / `ist_compile_grade` / `ist_compile_run` 三 fork。早期参照"餐厅"比喻分工（仅设计沟通，commit `3aaf056d` 已从代码清除隐喻命名）。

**取舍**：此时是"生成→上机→评估→双绿才交付"，上机 pass 是进 excel 的硬前置。

---

## batch：入口统一 + 编译/上机解耦（2026-06-15 / 06-16）

这一阶段两件大事，对应 `docs/compile_refactor_round_2026-06-16.md` 与 `docs/batch_compile_architecture.md`。

**(a) 入口统一为 `ist_compile_batch`（2026-06-15，合并删 orchestrate）**
- **根因（`compile_refactor_round_2026-06-16.md:16`）**：`infotest -p "把3个txt转excel"` 时，main agent 命中单条编排器 `ist_compile_orchestrate` 的触发词即停，没比对 batch；两个 skill 触发词高度重叠。结果单条编排器被喂整脑图 → draft 单步硬扛 34 条（reasoning 2.8 万字符）→ 产 33 个碎文件而非用户要的 3 个脑图级 excel。
- **变化**：删 `ist_compile_orchestrate` 整目录，`ist_compile_batch` 成唯一入口。**单条是 N=1 特例**：prep 出 1 case manifest、fanout 并发度 1、merged 退化成单 case+哨兵，同一流程无特殊分支。
- **零硬编码红线落地点**：`compile_prep` 解析脑图 → manifest（`autoid` 为主键），但 case 的 `init_commands`/`steps`/`assertions_provenance` **全部为 null**——命令/断言由 draft 子 agent 现场查手册/先例回填。

**(b) 编译与上机验证解耦（2026-06-16）**
- **根因（`batch_compile_architecture.md:18`）**：上机大面积失败常是设备环境瞬态（SSH 中断、dig 超时、DNS 失败），把"上机通过"当成"进 excel"的硬前置 → 环境一坏就出不了任何 excel。
- **变化**：编译链只产 excel（draft 生成 → grade **断言质量审批** → `compile_emit_merged` 合并打包），**不上机**；上机独立成 `ist_verify` skill 对成品 excel 做。grade 的 device verdict 改**可选输入**，支持无上机静态审批。
- **交付门槛 = grade 断言质量**（弱断言/未覆盖仍 CUT，不救场），不再是上机 pass。两者经 `ask_user` 在交互层串成闭环。

**端到端实证（yzg 26 case，`compile_refactor_round_2026-06-16.md:66`）**：合并 xlsx 跑出框架两条硬约束——① check_point 必须紧跟产生回显的命令（655203 `check_point found "sdns on"` 跟在无回显配置命令后 → `lib/check_point.py` `TypeError`）；② 框架"一个 case 崩中断整包"，坏 case 之后 22 个全 no_log。

---

## V2-grounding：三层 G⊔E⊔V 生成（`docs/PLAN_footprint_v2_compile.md`）

**目标**：把论文 G⊔E⊔V 三层落到实现，**根治 draft 慢 + 不稳定**。v1 编译链零改动作实验基底，V2 新建，靠 `.skill_overrides.json` 切换共存。

**实证根因（`PLAN_footprint_v2_compile.md:40`，治"慢"）**：单 case draft = 21 轮/567s（case 676654），其中 #6-18 共 13 轮在反复 grep 手册找一条 `sdns listener <ip> [port]` 语法——该语法手册第 7395 行存在，但被噪声淹没捞不出。根因**不是手册缺，是 footprint 没把现成文法提进来**。

**关键变化与模块**：
- **阶段一 footprint 文法补全**：新建 `scripts/maintenance/footprint_backfill.py`，手册切片 → 复用现有 `extract_facts`→`route_facts`→`merge_fact` 提取链（零改 extractor/router/merger），灌 `nodes/<feature_id>.json`。`merger.py:106` 的 evidence 门（quote 须在源文件 ≥60% 命中）保证不编造。draft 查表命中即得，不啃手册。
- **阶段一·补 意图检索轴**：`compile_precedent` 加可选入参 `intent=""`（默认空 = v1 行为不变，向后兼容）。原工具只按 my_config 命令 token Jaccard 检索，draft 必须先猜出配什么命令；676654 类一句话需求猜不出 → 检索不到 → 啃手册。加意图轴后"知道测什么但没想好配啥命令"也能检索到骨架先例。
- **E 段独立**：draft 直接调 `env_facts` 拿可达 IP，独立于先例通道——治论文 §5.6 点的"E 段搭载在 lookup_pattern 返回里、无独立查表通道"缺口。
- **结构约束门（correct-by-construction，命题 3.18）**：在 `compile_emit` 出口做生成后过滤——命令头∈手册 allowlist、断言对象必须挂前序观测算子（非悬空）、绑定 IP∈env_facts 可达表。这是与 grade **独立**的确定性强制（grade 抓不到结构违反，两臂 grade-PASS 率同为 0.423 即证）。
- **V2 grade 瘦身**：只判 V 段语义覆盖度，走 `json_object`（不再正则抠 JSON），G/E 配置存在性不参与覆盖评分（治旧 grade 偏严）。

**实测收益（`PLAN_v3_closed_loop_compile.md:11`）**：dongkl 34 case，单 draft 288s（v1 579s，-50%）、轮数 11.3（v1 21.4）、grep 6.3/fork（v1 25）。

**核心红线（§3.7ter）**：确定性机制只**执行结构约束**（与意图无关的类型规则），**绝不替代骨架选择**（H_G≠0 的语义决策永远 LLM）；footprint/先例/意图索引都只给 LLM**候选**，不做决定。

---

## V3：闭环自演化（`docs/PLAN_v3_closed_loop_compile.md`，初版实测负收益）

**目标**：V2 本质是"喂得更饱的 v1 架构"，三个论文许可的结构跃迁没碰。V3 在 V2 基础上做架构跃迁，每个跃迁挂一条定理：

| 跃迁 | 论文依据 | 模块 |
|---|---|---|
| ① 闭环写回 | §3.14 定理3.22（扩库推高 ρ_k） | `main/ist_core/memory/compile_writeback.py` |
| ② 三层 Provenance IR | §3.5 定义3.6/3.7 | `main/case_compiler/provenance_ir.py` + `compile_emit` 加 `provenance_json=""` 入参 |
| ③ 意图族摊销 H_G | §3.7 定理3.10（同族 H_G 可共享） | `intent_cluster.py` + `qa_cluster_intents` |
| ④ 四层归因 | §5.4（G/E/V/瞬态四分） | `fail_attribution.py` + `compile_attribute` |
| ⑤ 并发自适应 | 工程 | `batch_tools.py` `_resolve_concurrency`，`_MAX_FANOUT` 4→16 |

**为什么失败（`PLAN_v3R_revised.md:11`，2026-06-17 单 dongkl 实测）**：10 个"族骨架 fork"平均 18.7 轮/263s、耗 2634s **一个 case 都没产出**（V2 基线 34 case 直接产 xlsx、288s/轮）。停机核算定位根因——**把优化加在了论文证明"无稳健收益"的骨架层**：族骨架 fork（18.7 轮）单位成本 > 被摊销的单 case 成本（11.3 轮），数学必亏；且骨架塞 brief 当文本，case draft 照样自查 footprint，**叠加≠摊销，G 段付两遍**。

**论文三方对照纠偏**：①论文从未要求"先编共享骨架 fork"（虚构步骤）；②我们自己跑的 N≈101/102 三集双臂对照证明**骨架层两臂打平、唯一稳健收益是 E 段 grounding（IP 可达率 0% vs 69% 编造）**——优化错了维度。

---

## V3-R：砍族摊销，保 grounding + 信息流跃迁（`docs/PLAN_v3R_revised.md`，现生产链）

**目标**：① 砍掉族摊销（负收益、论文不支持）；② 保留并验证不烧钱的信息流跃迁；③ 收益维度是 grounding（E 段），V2 结构门已做对，**不在骨架层加戏**。

**形态**：编排流程**等于 V2**（prep → draft 并发 → grade 并发 → 合并），**不加聚族/族骨架两阶段**。只叠加三件零/负 fork 开销的信息流增强：

| 跃迁 | 增量 | fork 开销 |
|---|---|---|
| ① 三层 Provenance IR | draft emit 时旁挂 `case.provenance.json`（每步 G/E/V+来源） | 0（draft 本就知来源，只是记下来） |
| ② grade 验 provenance | grade 读 provenance 验来源，不重新 grep | **负**（省 grade 的 grep） |
| ③ 闭环写回 + 四层归因 | verify 上机 PASS 的 G 段写回 footprint（ρ_k↑）；fail 四层归因按层回流 | 0（写回是 verify 后处理） |

**每个现存件的处置（`PLAN_v3R_revised.md:46`）**：
- `provenance_ir.py` + emit 的 `provenance_json` 入参 → **保留**（零开销信息流）
- `ist-draft-v3` → **改**：删"复用族骨架"分支，回到 V2 draft 行为 + 产 provenance（轮数应回到 ~11，不再有 18.7 轮族骨架）
- `ist-grade-v3` / `compile_writeback.py` / `fail_attribution.py` / `ist_verify_v3` → **保留**
- `ist_compile_v3/SKILL.md` → **重写**：去掉聚族+族骨架两阶段，流程对齐 V2 + draft 走 v3 + grade 验 provenance
- `intent_cluster.py` / `qa_cluster_intents` → **保留代码、编排不调用**（无害、有单测、大族场景留作未来）

**红线**：不在骨架层加戏（实测骨架两臂打平）；provenance 是**记录不是规则**，只标 draft 已做的来源决策；写回只写**上机真 PASS 的 G 段**，evidence 门防幻觉，不写 V 段、不建意图→命令映射；V1/V2 链零回归。

---

## 贯穿全程的设计意图与红线

1. **结构约束 vs 骨架选择**（最高红线，§3.7ter）：确定性机制只执行结构约束（命令∈allowlist、断言挂观测算子、IP∈环境表），绝不替代骨架选择（H_G≠0 永远 LLM）。混淆即重蹈 v1（41→1）。
2. **零硬编码**：skill/agent 定义零写死的 sdns/APV 具体命令；footprint 给文法、先例给骨架候选、意图索引给检索候选——都是给 LLM 候选，不做决定。manifest 命令字段全 null 是落地点。
3. **correct-by-construction**：结构正确性靠独立确定性结构门（命题 3.18），不靠 grade 自评（grade 抓不到结构违反）。
4. **不救场**：交付门槛是 grade 断言质量，弱断言/未覆盖仍 CUT，连续 N 轮（建议 3）escalate，不拿弱产物充数。
5. **自评分离**：draft（生成）与 grade（评分）是隔离 fork，结构上消除自生成自评估。
6. **收益维度是 grounding（E 段）**，非骨架层——V3→V3-R 的核心纠偏，由我们自跑的 N≈101 三集双臂对照实测得出（非论文作者结论）。

**当前生产配置**：`.skill_overrides.json` 中 `ist_compile_v3=on`、`ist_compile_v2=off`、`ist_compile_batch=off`；并发 `_DEFAULT_FANOUT=4` / `_MAX_FANOUT=16`（`batch_tools.py:32-33`），auto 模式按待编译数自适应夹紧。

---

**相关文件**：`docs/PLAN_footprint_v2_compile.md`、`docs/PLAN_v3_closed_loop_compile.md`、`docs/PLAN_v3R_revised.md`、`docs/batch_compile_architecture.md`、`docs/compile_refactor_round_2026-06-16.md`、`docs/legacy_compile_pipeline_removal.md`、`docs/case_compile_orchestration.md`、`docs/theory_to_implementation_mapping.md`；生产配置 `main/ist_core/skills/.skill_overrides.json`；并发常量 `main/ist_core/tools/device/batch_tools.py:32-62`。


---

## 二、case_compiler（数据结构与产出底座）

`main/case_compiler/` 是编译链最底层的确定性基座：定义 xlsx 的数据结构（IR）、负责把 IR 落成框架可读的 `case.xlsx`、承载三层 Provenance 来源契约、提供上机回填/缓存/置信判分这些"非领域硬编码"的纯结构工具。**全模块红线**：任何"某模式该用某断言"的领域规则一律不写死，领域内容交给 LLM 现场查手册/先例；这一层只做 `correct-by-construction`（结构良构）和确定性变换（回填/锁死/哈希）。

### 2.1 `case_ir.py` — xlsx 单一事实源（数据结构 + 良构校验）

一句话职责：把"脑图自然语言用例"翻译成与跳转机框架 `lib/test_xlsx.py` 列语义对齐的 IR（`Row`/`Step`/`CaseIR`/`FileIR`），并提供值域良构校验。

**xlsx 九列语义**（`case_ir.py:5`，实证自框架）：A=自动化ID（case 首行）、B=优先级（首行）、C=语句类型、D=描述、E=测试对象、F=方法、G=数据、H=临时保存期望结果（输出存变量）、I=输入变量。C 语句类型：`0`=不执行（说明）、`1`=通用前置（文件级）、`2`=赋值/普通起始、`3`=循环、`≥4`递增；同一步骤多行共享一个 C（仅首行写 C/D，后续留空）。

**数据结构（dataclass）**：
- `Row`（`case_ir.py:43`）：一行 A-I 的数据载体，字段 `test_object`(E)/`method`(F)/`data`(G)/`save_as`(H)/`input_var`(I)。额外携带非 xlsx 列的 `provenance`（取值 `passthrough`/`author_intent`/`spec:*`/`llm_unsourced`/`None`），只在 IR 内流转供 W6 闸消费，`emit` 时丢弃。方法 `is_check_point()` 判断 E 是否为 `check_point`。
- `Step`（`case_ir.py:61`）：一个逻辑步骤，`stmt_type`(C)+`description`(D)+`rows: list[Row]`（同步骤多行如一个配置步骤跟多个 check_point）。
- `CaseIR`（`case_ir.py:70`）：单个用例，`autoid`(A)/`priority`(B)/`title`/`steps`+ provenance 诊断字段（`source_module`/`source_text`/`expected`/`confidence`/`notes`）。**关键红线字段** `is_passthrough`（`case_ir.py:87`）：精确 autoid 命中框架既验证语料的直转产物，为 `True` 时三确定性变换（assertion-fix/rr-rewrite/settle）一律跳过——原件已上机验证，任何重写都是破坏（实证 rr_stats 拆散 IP-Hit 配对致 fail）。`check_point_count()`(`case_ir.py:89`) 统计断言行数。
- `FileIR`（`case_ir.py:93`）：单 feature 单 xlsx，`feature`(文件名 stem)/`init_rows`(C=1 文件级前置)/`cases`+ `rejected`(不可自动化清单)/`questions`(用例质疑)。

**值域白名单**（`case_ir.py:22-40`）：`VALID_TEST_OBJECTS`(E 合法对象)、`VALID_TEST_ENV_HOSTS`(E=test_env 的合法主机名)、`VALID_CHECK_METHODS`({found, abs_found, not_found, found_times})、`VALID_APV_METHODS`(APV 通用反射方法)。

**公开函数**：
- `_effective_whitelists(snapshot)`（`case_ir.py:106`）：FIX-6 单一源收口——有 KP2 `CapabilitySnapshot` 时**以框架快照为准**（真实能力），缺则回退本地默认，避免四份白名单漂移。返回 `(check_methods, hosts, generic)`。
- `validate_row(row, snapshot)`（`case_ir.py:120`）：单行 W5/F 值域良构校验。E 不在合法集即返错；`check_point` 的 F 必在断言白名单且 `found_times` 需 I 列 times；`test_env` F 必为合法主机名；`time` 的 F 必为 `sleep`。返回违规说明 list（空=合法）。被 `validate_case` 逐行调用。
- `validate_case(case, snapshot)`（`case_ir.py:149`）：W4 断言完备 + 行级。**核心硬契约**：`check_point_count()==0` 直接报错（"无 check_point 上机必 fail，pass 需 success>0"）。snapshot 透传给行级（KP2 单一源）。在编译链里位于 emit 之前的良构门。

### 2.2 `xlsx_emit.py` — CaseIR → xlsx（克隆模板 + round-trip 对账）

一句话职责：克隆 smoke_test 原生模板（`sdns_listener.xlsx`，`xlsx_emit.py:28`），仅重写数据区（R29+），保留说明区/字典区/格式/合并单元格，最后回读对账。

**公开函数**：
- `emit_xlsx(file_ir, out_path)`（`xlsx_emit.py:62`）：编译链的产出端口（被 `compile_emit` 工具调用）。流程：`shutil.copy` 模板 → `detect_xlsx_layout` 动态探测数据起始行（不写死 R29）→ 清空旧数据区 → 写 author 说明行(C=0) → 写 `init_rows`(C=1) → 逐 case 逐 step 逐 row 写（首行写 A/B/C/D，同步骤后续行只写 E-I，case 间空一行）→ `wb.save` → 返回 `_readback` 对账统计。
- `_set_row(sheet, r, cols)`（`xlsx_emit.py:34`）：写一行 `{列号:值}`，未给的列清空。
- `_row_cols(row, stmt_type, description, autoid, priority)`（`xlsx_emit.py:40`）：构造一行列字典；`stmt_type/description=None` 表示该行不写 C/D（同步骤后续行）。
- `_readback(path)`（`xlsx_emit.py:121`）：**round-trip 闸**——用纯 openpyxl（同框架 `read_excel_with_openpyxl` 语义）回读，以 `header_anchor` 定位数据区，统计 `case_count`/`autoids`/`check_point_count`，供调用方对账 emit 是否如实落盘。

### 2.3 `provenance_ir.py` — 三层 Provenance IR（G⊔E⊔V + source.kind）

一句话职责：draft 产出 steps 的同时为每一步标注所属层（G 骨架文法 / E 环境常量 / V 业务语义）与来源类型，成为 draft↔grade↔verify↔writeback 的公共契约（论文 §3.5 带来源 G⊔E⊔V 分解）。**红线**（`provenance_ir.py:14`）：provenance 只**记录** draft 已做的来源决策，不替代骨架选择——layer/source 是 draft 的语义注解，不是确定性规则。

**source.kind 取值**（`provenance_ir.py:27`）：`footprint`(G)/`precedent`(G/V)/`env_facts`(E)/`manual`(V)/`intent`(V)/`skeleton`(G 族骨架)/`device_runtime`(V 离线不可知，值填 `<RUNTIME>` 占位)/`device_verified`(V 上机回填锁死)/`unknown`(兜底)。`RUNTIME_PLACEHOLDER = "<RUNTIME>"`（`provenance_ir.py:40`）是"不猜留空"的离线不可知占位符。

**数据结构**：`StepSource`(`kind`+`ref`，`__post_init__` 把非法 kind 归 `unknown`)、`StepIR`(`E`/`F`/`G`/`layer`/`source`，非法 layer 归 `V`)、`CaseProvenance`(`autoid`+`steps`+`skeleton_ref`族骨架引用+`provisional` 上机前为 True)。`CaseProvenance` 提供 `to_dict`/`to_json`/`from_dict`/`from_json`/`layer_steps(layer)`。

**公开函数**：
- `parse_provenance(provenance_json)`（`provenance_ir.py:116`）：容错解析，空/坏返回 `None`（调用方据此回退 V2 行为）。被 runtime_fill `_sync_provenance` 等消费。
- `steps_match(provenance, steps)`（`provenance_ir.py:126`）：校验 provenance 标注与实际 emit 的 steps 在 E/F/G 上一致（防 draft 标注与产物脱节），grade 步骤用。
- `check_runtime_consistency(provenance)`（`provenance_ir.py:136`）：**结构自洽硬契约**（不判值对错，离线本判不了）——`device_runtime`⟺G 含 `<RUNTIME>` 双向自洽。抓三类骗门写法：标 device_runtime 却填具体值（假弃权真编数）、填占位却谎称来源是 footprint/precedent、标 device_verified 却仍含占位（谎称已回填）。只看 check_point 步，返回违规说明 list。

### 2.4 `runtime_fill.py` — 上机回填（不猜留空 + 回填锁死）

一句话职责：把 `<RUNTIME>` 占位槽位用设备真实值回填并**锁死**，对应用户两条铁律——本模块只回填不编值。

**设计要点**（`runtime_fill.py:4`）：①不猜留空——值由调用方（ist-fill fork 读设备明细）给定，给空值＝抽不出，如实留空报告绝不猜；②不反复改（锁死）——回填**只动仍含 `<RUNTIME>` 的 G 格子**，一旦填上后续回填定位不到 → 天然幂等永不覆盖，锁是结构性的不靠调用方自律。数据区从第 29 行起（`_DATA_START_ROW=29`），遇 A 以 `999999` 开头的哨兵 case 停。

**数据结构**：`RuntimeSlot`（`runtime_fill.py:42`，一个待填槽位，**`slot_id=f"{autoid}#{row}"` 用行号做稳定标识**——填别的槽位不会让本 id 漂移，序号会漂是锁失效根因）、`FillResult`（`runtime_fill.py:97`，`filled`/`left_blank`/`not_found`/`details`+`summary()`）。

**公开函数**：
- `list_runtime_slots(xlsx_path)`（`runtime_fill.py:59`）：扫描数据区列出所有仍含 `<RUNTIME>` 的 check_point 槽位，已回填的不返回（天然体现锁）。逐行追踪 `last_obs_cmd`/`last_obs_obj`（紧邻前序观测步，供回填取值定位），新 case 起重置。被 verify 链调用枚举待填项。
- `apply_fills(xlsx_path, fills, project_root, run_meta)`（`runtime_fill.py:111`）：回填核心。`fills=[{slot_id, runtime_value, evidence}]`。**锁的硬保证**：先 `list_runtime_slots` 重扫（只含占位的才在列表），已填 slot_id 重扫时不存在 → `not_found` 绝不覆盖。`runtime_value` 空/缺 → `left_blank`(不猜)；rv 自身含占位符 → 拒填(防假回填)；否则 `G.replace(<RUNTIME>, rv)` 写回。`project_root` 给定则同步 provenance（device_runtime→device_verified，best-effort 失败不挡）。
- `_is_observation(e, f, g)`（`runtime_fill.py:30`）：判断该步是否产出可被 check_point 匹配的回显（test_env 触发 / APV 的 show/dig/statistics 等）。
- `_sync_provenance(project_root, autoid, changes, run_meta)`（`runtime_fill.py:179`）：按 old_g 精确匹配 check_point 步，命中则改 G + 来源转 `device_verified` + 写 evidence/run_meta 到 source.ref，回写 `outputs/<autoid>/case.provenance.json`。

### 2.5 `verify_cache.py` — 上机结果内容哈希缓存

一句话职责：用户铁律③——上机 pass 的 case 别反复跑（设备极慢），只对有问题的在交付前回填/重跑。缓存按 **case 内容哈希**键控，落 `workspace/outputs/<脑图名>/.verify_cache.json`。

**核心机制**：case 被重编译/回填后内容变 → 哈希变 → 缓存失效 → 重跑（旧 pass 不能蒙混）；pass 且无 `<RUNTIME>` 残留才记入缓存（没填完的不算交付级通过）。

**公开函数**：
- `case_rows_by_autoid(xlsx_path)`（`verify_cache.py:29`）：把合并 xlsx 数据区按 autoid 分组为 `{autoid: [{E,F,G}]}`（遇哨兵停）。
- `case_content_hash(rows)`（`verify_cache.py:50`）：E|F|G 规范化后取 sha256 前 16 位。回填/重编译改任一格哈希就变。
- `has_unfilled_runtime(rows)`（`verify_cache.py:56`）：该 case 是否还有未回填 `<RUNTIME>`（有则不算交付级通过）。
- `load_cache`/`save_cache`（`verify_cache.py:65`/`77`）：读写缓存 JSON，缺失/坏→空 dict，写失败仅 warning 不挂。
- `is_cached_pass(cache, autoid, content_hash)`（`verify_cache.py:85`）：该 autoid 当前内容下是否已缓存为 pass（**哈希必须匹配**，否则视作内容已变）。verify 链跳过判据。
- `record_pass`（`verify_cache.py:91`，调用方须自行确认 verdict=pass 且无未填占位）、`invalidate`（`verify_cache.py:98`，显式作废误判的旧 pass）。

### 2.6 `confidence_f.py` — v4 置信函数 f()（LLM 判分，非硬规则）

一句话职责：判 xlsx check_point 行"配不配得上它所测的配置行为"，作为上机 verdict 之外的第二判据（快筛+abstain，终判仍上机）。**设计红线**（`confidence_f.py:5`）：不写任何"某模式该用某断言"的规则、不派魔数分、不做关键词意图匹配——判分交给 LLM 看真实证据现场判。

**纯客观事实部分（框架契约，非判断）**：
- `link_assertion_to_config(rows)`（`confidence_f.py:23`）：按框架派发契约把每个 check_point 关联到它前面最近的"产出输出的非 check_point 步骤"+ 截至该处的 APV 配置上下文。返回 `[{cp, tested_step, config_context}]`。这是 f() 的事实基座，也被 `build_judge_evidence` 复用。
- `build_judge_evidence(rows, need_intent, anchor_examples, manual_facts)`（`confidence_f.py:59`）：纯拼装证据包——原始需求 + 每个断言(及其所测配置) + 招牌菜先例(compile_precedent 给) + 手册行为(agent grep 给)，无判断逻辑。

**判分**：
- `score_case(rows, need_intent, anchor_examples, manual_facts, model, judge_timeout_s)`（`confidence_f.py:95`）：调 LLM 喂证据包，输出每行 0-1 置信。无 check_point→abstain；`model=None` 时尝试 `build_agent_chat_model()`，构建失败→abstain（**不退化成硬规则猜分**）。带 `ThreadPoolExecutor` 超时保护（默认 120s，实测无超时会 hang 死拖垮 batch），超时/解析失败→abstain 由上机兜底。`overall = min(各行分)`（最弱行拖垮，结构性规则非领域硬编码），`abstain = overall<0.5`。被 grade 子流程的 `compile_score` 工具消费。

### 2.7 `corpus.py` — idiom 平行语料库（先例 few-shot，纯查找无向量）

一句话职责：从镜像 `knowledge/framework/mirror/smoke_test/` 提取 (case → DSL 行) 平行语料供编译器 few-shot，检索是纯 token 查找（守 CLAUDE.md 无 RAG/Qdrant 原则）。

**数据结构**：`CorpusCase`（`corpus.py:21`，一个完整 case 的原始行+`init_rows`+检索 `tokens`+`source_kind`，`as_example_text()` 渲染紧凑 few-shot 表格）。`source_kind`：`xlsx`=声明式可直转(passthrough)；`py`=imperative 仅作 few-shot。

**公开类/函数**：
- `IdiomCorpus`（`corpus.py:213`）：懒加载内存索引。
  - `IdiomCorpus.build(subdirs, include_py)`（`corpus.py:237`）：从镜像构建，解析 xlsx + 可选 host_persistence 风格 pytest .py，共享一份 normalizer 单例避免逐文件重扫。
  - `by_autoid(autoid, passthrough_only)`（`corpus.py:223`）：精确 autoid 直取（框架自验编译，最高保真）；`passthrough_only=True` 时只返回 xlsx 派生（.py 是 imperative 不可声明式直转）。供 draft 命中既验证语料走 passthrough。
  - `nearest(query, module, k)`（`corpus.py:284`）：token Jaccard + 模块加权最近邻检索，`compile_precedent` 的底层。
- `_parse_file(path)`（`corpus.py:67`）：xlsx 拆多 CorpusCase；**case 边界判据是 A 列有 autoid**（对齐框架 `test_xlsx.py:220 row[0] is not None`），不可用 C==2 判首行（合法 DSL 允许 C 跳号）。
- `_parse_py_case(path, normalizer)`（`corpus.py:115`）：把 pytest .py 反编译成行级 DSL（`obj.method(args)`→E/F/G，赋值变量进 H，found_times 第二参进 I）；E 对象经 normalizer 归一，无法归类的行跳过。autoid 来自文件名。
- `_extract_g(argstr, eobj, method)`（`corpus.py:184`）：从调用参数串抽 G 值（kwargs 优先 cmd>command>config>value；起始引号配对匹配避免内层异种引号截断；time.sleep 取数字）。

### 2.8 `object_normalizer.py` — E 列对象名规范化器

一句话职责：把 .py 先例里的对象名（设备别名 Seg0/APV0_C、主机名等）归一成 xlsx 标准 E 列对象（`APV_0`/`check_point`/`test_env`/`time`）。**红线**（`object_normalizer.py:7`）：不写死某测试床的 `{APV_0, APV_1}` 具体集合，按结构规则归一，换测试床/加设备不用改代码。

**公开类/函数**：
- `ObjectNameNormalizer`（`object_normalizer.py:32`）：`device_aliases` 可由 conftest fixture 采集补充（运行时注入）。
  - `canon_object(obj)`（`object_normalizer.py:39`）：四级归一——①显式注入别名优先 → ②断言/环境/等待关键字(`_KEYWORD_CANON`) → ③被测设备别名(`_DEVICE_RE` 匹配 apv/seg/dut+序号)归 `APV_<n>` → ④其余主机名归 `test_env`；无法归类返回 `None`（调用方跳过该行）。被 corpus `_parse_py_case` 调用。
- `get_object_normalizer()`（`object_normalizer.py:64`）：`@lru_cache` 进程级单例，corpus 解析先例时复用。

### 2.9 `config.py` — 编译器单一事实源（去硬编码收口）

一句话职责：消除审计发现的 34+ 处硬编码（IP/路径/口令/build/行号/白名单）收口到一个配置对象，三层优先级 env(`IST_*`) > `runtime/compiler_config.json` > 代码安全默认。**敏感项**（跳转机/MySQL 口令）只从 env 或文件读，代码默认一律空绝不硬编码明文。

**数据结构**：`JumphostConfig`(`config.py:49`，SSH 接入，口令从 `password_env` 指向的 env 读不落盘，`server_cmd` 属性拼启动命令)、`XlsxLayout`(`config.py:65`，`header_row=28`/`data_start=29`/`header_anchor=自动化ID` 探测兜底默认)、`CompilerConfig`(`config.py:75`，顶层：build/target_version/staging_module/mysql_*/jumphost/xlsx/`default_init_lines`)。

**关键红线** `default_init_lines`（`config.py:95`）：**默认空，不写死任何命令**——agent 必须自查要测功能该建什么前置（看 conftest、看同类先例 init、grep 手册），仅当用户显式配置才用。`default_init_g()`（`config.py:134`）返回前导 4 空格的前置块。

**公开函数**：
- `CompilerConfig.load()`（`config.py:100`）：三层加载，`_pick(env_key, file_cfg, file_key, default)`（`config.py:39`）实现 env>文件>默认（空串视为未设置）。
- `get_config(reload)`（`config.py:149`）：进程级单例，被 xlsx_emit/corpus/device_mcp_client 等广泛引用。
- `detect_xlsx_layout(grid, cfg)`（`config.py:157`）：从已读 grid 动态探测表头行/数据起始行（A 列等于 header_anchor 的行=表头，下一行=数据起始），不写死 R28/R29，探测失败回退 cfg 默认。被 `emit_xlsx` 调用。

### 2.10 `device_mcp_client.py` — 跳转机框架 MCP client（上机通道）

一句话职责：IST-Core 本地侧（Py3.11）经 SSH + stdio JSON-RPC 驱动跳转机的 MCP server（Py3.8 离线），是编译链与真实设备框架之间的唯一上机通道，供 verify/probe 子流程采集 ground truth。凭据从 env `IST_JUMPHOST_PASS`/`JUMPHOST_PASS` 取，不落盘不回显（`_password()`，`device_mcp_client.py:26`）。

**公开类 `FrameworkMCPClient`**（`device_mcp_client.py:43`，每次调用开一个 server 会话，无状态命令）：
- `call(calls)`（`device_mcp_client.py:61`）：一个 server 会话内顺序调用多个 tool，按 tool 名返回结果。**带读超时保护**（默认 900s 按最慢 tool run_cases 留足），`so.read()` 无超时会无限 hang（pytest 卡住/deliver 慢），超时抛 RuntimeError 不无限阻塞。
- `list_capabilities()`（`device_mcp_client.py:113`）：拉框架能力快照（KP2 CapabilitySnapshot 源）。
- `probe_show(command, build)`（`device_mcp_client.py:116`）：只读设备探针，经跳转机在被测 APV 跑单条 show/get（server 侧硬白名单首 token），取真实回显。本测试床 APV 只能经跳转机访问。`dev_probe` 工具底层。
- `deliver(module, autoid, xlsx_path)`（`device_mcp_client.py:125`）：base64 编码 xlsx 经 `write_case` 投递到跳转机。
- `run(module, autoid, build)`（`device_mcp_client.py:129`）/`status(...)`（`device_mcp_client.py:135`）：提交上机/查状态。
- `run_and_wait(module, autoid, build, case_ids, poll_s, max_s)`（`device_mcp_client.py:139`）：提交并轮询到 done。**撞锁不静默放弃**——把 server 结构化 `device_busy` 信号（含 running_autoid/elapsed_s/message）原样上抛，由上层 agent 决定等/跳/报，不把"环境忙"误当"提交失败"。
- `fetch_case_detail(autoid, max_chars)`（`device_mcp_client.py:167`）：拉框架逐步骤明细 + check_point 真实裁决。**实证路径关键**：`Success/Fail Num` 写在每 case 专属子日志 `test_xlsx/case.xlsx/<autoid>/<autoid>.txt`（非总日志 test_xlsx.txt，后者只到 begin case），故优先取专属日志缺则回退。verify 区分真实断言失败 vs 环境瞬态失败的 ground truth 来源。
- `fetch_device_context(autoid, max_chars)`（`device_mcp_client.py:194`）：拉完整设备上下文（失败诊断用）——①设备配置会话原文(每条命令+真实响应，含 "Failed to execute X because Y" → 知道哪条命令为何被拒)；②触发端会话(RouterA/clientc 的 dig 真实输出含 ANSWER SECTION/解析 IP → 知道设备实际返回什么、怎么填 `<RUNTIME>`)。原样取来不解析。

---

**编译链定位小结**：`config`(事实源) 与 `object_normalizer`(归一规则) 是无依赖底座；`corpus` 依赖二者构建先例语料供 draft 检索（`compile_precedent`）；`case_ir`→`xlsx_emit` 是 draft 的产出路径（`compile_emit`，emit 前过 `validate_case` 良构门、emit 后 round-trip 对账）；`provenance_ir` 是贯穿 draft/grade/verify/writeback 的来源契约；`confidence_f` 是 grade 的判分（`compile_score`）；`device_mcp_client` 是 verify 的上机通道，`runtime_fill`(回填锁死) + `verify_cache`(内容哈希跳过) 是 verify 链的两个确定性工具。

文件路径（均绝对）：
- `/Users/jiangyongze/Library/CloudStorage/SynologyDrive-home/Project/InfoTest_Engine/main/case_compiler/{case_ir,xlsx_emit,provenance_ir,runtime_fill,verify_cache,confidence_f,corpus,object_normalizer,config,device_mcp_client}.py`


---

## 三、编译流水线与编排

把一份人工脑图（mind-map JSON）编译成断言真覆盖目标行为的 `case.xlsx`。本章覆盖三个文件：`compile_prep.py`（脑图→需求 manifest）、`compile_pipeline.py`（确定性 prep→draft→grade→merge 主流水线 + 变体保真 + 自适应并发）、`batch_tools.py`（fan-out / 上机批跑 / 合并打包三个可复用编排工具）。

### 数据流总览

```
脑图 txt
  │  compile_prep              （compile_prep.py）—— 只产需求，零命令
  ▼
manifest.json  { cases:[{autoid,title,group_path,step_intents,…null…}], groups }
  │  compile_pipeline._run_pipeline  （compile_pipeline.py）—— 确定性锁死全序列
  │    每 case 一条独立任务，N 任务并发（AdaptiveLimiter 闸住），无屏障：
  │      _preretrieve_precedent（确定性预检索 1 次）
  │        → _build_case_brief（机械模板化五要素 brief）
  │        → _draft_once  (fork ist_draft_v3)  → case.xlsx 草稿 + provenance
  │        → _check_variant_fidelity（B 层保真，偷换/缺配 → 回流重做）
  │        → _grade_once  (fork ist_grade_v3)  → PASS / CUT
  │        → CUT 带反馈重做 ≤ _MAX_REWORK_ROUNDS(3) 轮，仍不过 → escalated
  ▼
grade-PASS 的 case
  │  compile_emit_merged          （emit_xlsx_tool.py，经 _load_case_rows 读回 steps）
  ▼
workspace/outputs/<out_name>/case.xlsx   （N 真 case + 1 哨兵；不上机）
```

`batch_tools.py` 的 `compile_fanout` / `dev_run_batch` 是更早期/外部可复用的阶段工具；`compile_pipeline` 现在把 draft/grade 的 fan-out **内联**进 `_run_pipeline`（直接调 `execute_fork_skill` + `AdaptiveLimiter`），不再走 `compile_fanout`。上机验证（`dev_run_batch`）属独立 `ist_verify` 环节，编译流水线**不上机**。

---

### 3.1 `compile_prep.py` — 脑图 → 需求 manifest

**一句话职责**：把一个 mind-map JSON 脑图解析成结构化 manifest（每个 `autoid` 一个 case 的原始需求 + 分组），是批量编译的第一步；**只产需求，绝不产任何命令/参数/断言**（零硬编码红线，第一原则）。

- **`_load_mindmap(path) -> list`** (`compile_prep.py:29`)：读脑图文件，跳过 BOM/噪声前缀定位到首个 `[`，按 utf-8 解析 JSON。脑图格式实证自 dongkl/yzg/zhaiyq：顶层 `[root]`，节点 `{data:{text,autoid?,…}, children:[…]}`。
- **`_text` / `_kids` / `_node_data`** (`compile_prep.py:38-47`)：节点字段安全取值小工具（`data.text` / `children` / `data`）。
- **`_extract_cases(root) -> list[dict]`** (`compile_prep.py:50`)：深度遍历，**带 `data.autoid` 的节点即一个 case**。约定层级：case 节点 `text`=标题，其 `children`=步骤描述，步骤的 `children`=期望值。命中 autoid 即停（autoid 节点是叶层 case 单元，不再下钻找嵌套 case）；非 case 节点把自身 `text` 压进 `group_path` 分组链继续下钻。每个 case 产出 `autoid/title/group_path/priority/step_intents`，并把 `init_commands/steps/assertions_provenance` 显式置 `None`（标注 `_filled_by_draft`：draft 子 agent 查证后回填），`compile_state` 初始化为 `pending`。
- **`compile_prep(mindmap_path, out_name="") -> str`** (`compile_prep.py:97`，`@tool`)：
  - **作用**：解析整脑图 → 落盘 manifest。**编译链入口的第 1 步**，被 `_run_pipeline` 调用一次（`compile_pipeline.py:360`）。
  - **关键入参**：`mindmap_path`（`workspace/inputs/automatic_case/*.txt`，走 `_resolve_inside_root` agent 沙箱多根解析，失败回退项目根拼接）；`out_name`（落盘子目录，空则用脑图文件名去扩展名）。
  - **返回**：人读字符串（manifest 路径 + case 总数/分组/重名标题统计 + autoid 重复告警）。真正的数据载体是落盘的 `workspace/outputs/<sub>/manifest.json`。
  - **关键契约（红线）**：autoid 是主键，**标题重名不去重**（yzg/zhaiyq 大量同名 case，区别只在参数）；分组只按 `group_path` 末级 `Counter` 聚合，**不做语义判断、不按关键字分支、不推断命令**。

---

### 3.2 `compile_pipeline.py` — 确定性主流水线（V3 approach A）

**一句话职责**：把固定序列 prep→draft→grade→筛 PASS→merge **锁进一个工具调用**，主 agent 只调一次，杜绝自行编排导致的序列失控（实测主 agent 会 prep×3、fanout×2、误调上机验证 skill）。**设计意图**：编译是低自由度任务（脆弱、一致性关键），故降级成确定性机制执行流程；语义自由度只配在 draft/grade 的 fork 内部（现场查命令/断言），不配在编排层。

#### 公开入口

- **`compile_pipeline(mindmap_path, product_version, out_name="") -> str`** (`compile_pipeline.py:495`，`@tool`)：
  - **作用**：一次跑完一个脑图的全编译序列，产出合并 `case.xlsx`。**整个编译子系统对主 agent 暴露的唯一编排入口**。
  - **关键入参**：`product_version` 不可臆测（决定查哪版手册），缺失直接返回 error 提示先 `ask_user`；`out_name` 空则用脑图 stem，并 `replace("/","_")` 防路径注入。
  - **内部**：固定 `draft_skill="ist_draft_v3"`、`grade_skill="ist_grade_v3"` 调 `_run_pipeline`，捕获全异常进 result（不抛）。
  - **返回**：结构化进度（各 phase + done/escalated 的 autoid 列表 + errors + 产出路径）。
  - **红线声明（docstring）**：不上机（上机走 `ist_verify_v3`）；多脑图逐个调本工具；命令/断言全由 draft fork 现场查，零硬编码。

#### 编排核心

- **`_run_pipeline(mindmap_path, product_version, out_name, *, draft_skill, grade_skill) -> dict`** (`compile_pipeline.py:346`)：确定性跑完全程，错误进 `result["errors"]` 不抛。三段：
  1. **prep（一次）**：调 `compile_prep`，读回 `manifest.json` 拿 `cases` + `groups`；无 manifest / 无 case 即提前返回。
  2. **每 case 独立流水线并发**：用 `_resolve_concurrency(0, n_items=len(cases))` 求并发上限 `ceiling`，建 `AdaptiveLimiter(start=max(2, ceiling//2), min=1, max=ceiling)`；`ThreadPoolExecutor(max_workers=ceiling)` 提交 N 个 `_compile_one_case`，**实际并发由 limiter 闸住**（线程阻塞在 `acquire`）。**消除 P7 屏障**——不再"全部 draft 完才开 grade"，case A 在 grade 时 case B 还能 draft。`as_completed` 收集，区分 `done` / `escalated`，把 limiter 轨迹写进 phases（可观测）。
  3. **merge（一次）**：对每个 done case 用 `_load_case_rows(xlsx)`（`precedent_tools.py:133`）读回 steps，组装 `merged_cases`，调 `compile_emit_merged`（`emit_xlsx_tool.py:494`）合并成单 excel + 尾部哨兵。

- **`_fork_call(skill, brief) -> str`** (`compile_pipeline.py:384`，闭包)：调 `execute_fork_skill`（`loader.py:391`，渲染 SKILL.md body 为 HumanMessage、用 `agents/<agent>.md` 作 system_prompt 跑 subagent）。**transient 退避**：fork 返回 `ERROR:` 且 `is_transient_error`（`resilience.py:56`，匹配丢连接/流中断/429/overloaded）为真时 → `limiter.record_overload()` 降并发 + 指数退避（`_TRANSIENT_BASE_SLEEP*2**attempt`，最多 `_TRANSIENT_RETRIES=4` 次），不消耗质量重做预算；成功则 `record_success()`。

- **`_compile_one_case(case) -> dict`** (`compile_pipeline.py:424`，闭包)：单 case 完整流水线，被线程池调度。`_preretrieve_precedent(case)` 预检索一次（轨迹缩减）；`with limiter:` 占名额后进重做循环 `_MAX_REWORK_ROUNDS=3` 轮：
  - `_draft_once` 产 xlsx；为 None → 反馈"未产出"重试。
  - `_check_variant_fidelity` 偷换/缺配 → 把违规当反馈重做。
  - `_grade_once` PASS → `state="done"` 返回；CUT → 取 `gout[:600]` 当反馈重做。
  - 三轮仍不过 → `state="escalated"`（**不救场**，如实上报）。

- **`_draft_once(case, aid, feedback, rnd, precedent_text="") -> Path|None`** (`compile_pipeline.py:400`)：`_build_case_brief` 拼 brief，重做轮追加 grade 反馈；记 `t0=time.time()` 开工时间戳；`_fork_call(draft_skill, brief)`；`_extract_xlsx_path(out, aid, since=t0)` 定位并做新鲜度校验。
- **`_grade_once(case, aid, xp) -> tuple[bool,str]`** (`compile_pipeline.py:414`)：brief = `xlsx_path + provenance_path + 原始需求`（从 `step_intents` 的 `desc→expected` 拼），`_fork_call(grade_skill, …)`，`_parse_grade_verdict` 解析裁定。

#### 确定性预检索与 brief（轨迹缩减）

- **`_preretrieve_precedent(case) -> str`** (`compile_pipeline.py:57`)：把"draft 在 ReAct 轮里调 `compile_precedent`"前移到流水线确定性预跑（draft 退化成近单发生成）。从 `title + step desc` 拼意图，调 `compile_precedent.invoke({my_config:"", intent, limit:2})`。**低置信不内联**：`_precedent_best_score(out) < _PRECEDENT_MIN_SCORE`（`IST_PRECEDENT_MIN_SCORE`，默认 **0.20**）时返回 `""`——烂先例（尤其算法类常带错变体）内联只会白塞 ~7.5K token + 误导支配，不如让 draft 回落 footprint 自查。
- **`_precedent_best_score(text) -> float`** (`compile_pipeline.py:47`)：用 `_PRECEDENT_SCORE_RE` 从召回文本抽"意图x / 配置x+意图y"分，取最高。
- **`_precedent_block(precedent_text) -> str`** (`compile_pipeline.py:82`)：渲染先例为 brief 末尾内联块；空召回时给降级提示（自己 `kb_footprint` + grep 手册）。
- **`_build_case_brief(case, *, product_version, manual_glob, groups, precedent_text="") -> str`** (`compile_pipeline.py:231`)：从 manifest 一个 case **机械模板化**生成 draft 五要素 brief（需求/现状/规则/指路/边界）——纯字段拼装，**非语义判断**，故可确定性产出。命令/期望值绝不写进 brief（零硬编码红线）。内嵌动态块：`save_variant` 命中时拼"配置保存/持久化（clear→恢复范式，绝不真重启）"块并要求 `compile_emit` 传 `expected_save_variant`；算法命中时拼"算法以需求为准、别照抄先例"块。规则段固化"写不准就留空、不 observe-then-assert、运行时值标 `<RUNTIME>` / `source.kind=device_runtime` 由 `ist_verify_v3` 上机回填"。
- **`_derive_save_variant(case) -> str`** (`compile_pipeline.py:93`)：用 `_SAVE_VARIANT_RE` 从脑图原文确定性解析保存变体（memory/file/all/net），供持久化门校验 draft 没偷换。**零硬编码**（按命令词解析，不按 autoid）。

#### B 层变体保真（correct-by-construction，需求点名 → 产出必须真用）

- **`_intent_methods(case) -> set`** (`compile_pipeline.py:127`)：需求点名的算法集合，只从 `title + step desc` 抽（**不含 expected**，断言里"与 rr 不同"类对比会污染），`finditer` 取全（多算法用例）。
- **`_actual_methods(config_text) -> tuple[set,bool]`** (`compile_pipeline.py:137`)：逐行解析产出 APV 配置实际配的算法 + 是否出现过 method 行；跳过 `no/show/clear`（`_OP_PREFIX_RE`，非生效行），host/pool 按位置取算法参数（防域名误命中）。
- **`_method_satisfied(named, actual) -> bool`** (`compile_pipeline.py:152`)：点名基础 `rr`/`wrr` 时，全局变体 `grr`/`gwrr`（`_GLOBAL_OF`）也算满足（**防误杀**合法严格实现）。
- **`_actual_save_variants(config_text) -> tuple[set,bool]`** (`compile_pipeline.py:160`)：同理解析 `write memory/file/all/net`。
- **`_read_xlsx_apv_config(xlsx_path) -> str`** (`compile_pipeline.py:172`)：openpyxl 读产出 xlsx，遇 `999` 哨兵停，抽 E 列以 `APV` 开头行的 G 列命令文本。
- **`_check_variant_fidelity(case, xlsx_path) -> str`** (`compile_pipeline.py:190`)：B 层保真校验主函数，被 `_compile_one_case` 在 draft 后、grade 前调用。**数据驱动非 per-case**：需求没点名某维度 → 跳过（no-op，零回归）。每维度三态：满足（放行）/ 换族（偷换违规）/ 缺配（点名了但产出无该类命令——堵"空配静默放行"）。违规返回带修复指引的回流反馈（如"算法以需求为准、别照抄先例—改用 sdns host/pool method … ；ga=优先级故障切换非轮转"），无违规返回 `""`。
- **算法枚举快照**：`_SDNS_METHODS`（`compile_pipeline.py:113`）是手册 7190/7566 算法枚举的**冻结快照**（footprint 尚未结构化存枚举，手册改版需手动同步，TODO 待 footprint 补全后改运行时派生）。

#### 新鲜度与裁定解析（治旧草稿污染 / 防误读）

- **`_extract_xlsx_path(fork_output, autoid, since=0.0) -> Path|None`** (`compile_pipeline.py:309`)：按落盘规律定位 `workspace/outputs/<autoid>/case.xlsx`。**新鲜度校验**：`since>0` 时文件 `mtime` 必须晚于本轮 draft 开工时间（容 1s 时钟抖动），否则视作"本轮没真产出新文件（沿用了上一轮旧草稿）"→ 返回 None，绝不把旧 buggy 草稿当本轮产物合并。
- **`_parse_grade_verdict(out) -> bool`** (`compile_pipeline.py:330`)：取**最后出现**的裁定词（PASS vs CUT 的 `rfind` 比位置）——grade 报告会先讨论 `compile_score` 的分（可能含 CUT）再下结论，朴素的 `"PASS" in out and "CUT" not in out` 会把"工具说 CUT 但我判 PASS"误读成重做，造成无谓 churn。`ERROR:` 开头一律不通过。

#### 自适应并发（`AdaptiveLimiter`，`resilience.py:70`）

AIMD 拥塞控制类比（加性增 / 乘性减），替代手动调 `IST_FANOUT_CONCURRENCY`：

- **`acquire()/release()`** (`resilience.py:93/99`)：`threading.Condition` 闸名额；`acquire` 在 `_active >= self.limit` 时 `wait(timeout=1.0)` 周期复检（limit 可能被调高）。`__enter__/__exit__` 包成上下文管理器（`with limiter:`）。
- **`record_success()`** (`resilience.py:111`)：**加性增**——连续成功数 ≥ 当前 limit 才 `+1`（慢升，避免再冲爆端点），记 `↑N` 轨迹。
- **`record_overload()`** (`resilience.py:121`)：**乘性减**——`limit//2`（夹到 min），记 `↓N`；**不 notify**（要更少并发，让在飞的自然回落）。
- **`current`**（property）/ `history`：当前并发 + 变化轨迹，被 `_run_pipeline` 写进 result phases 供观测。

---

### 3.3 `batch_tools.py` — fan-out / 上机批跑 / 合并打包

**一句话职责**：把"逐 case 串行"改成"按阶段批量并行/串行"的三个可复用编排工具；**并行的物理边界落在工具内部实现，不靠 prompt 自律**。零硬编码红线：只做"调度 + 结果汇总"，不含任何 APV/sdns 命令、不解析领域语义。

- **`_resolve_concurrency(requested, n_items=0) -> int`** (`batch_tools.py:43`)：定 fan-out 并发度。优先级 **env 硬覆盖(`IST_FANOUT_CONCURRENCY`) > 调用方显式值 > auto**。auto = `min(_MAX_FANOUT(16), max(_DEFAULT_FANOUT(4), n_items))`——少时不空开线程、多时铺到上限。**亦被 `_run_pipeline` 复用**求 ceiling（`compile_pipeline.py:381`）。
- **`_is_rate_limit_error(exc) -> bool`** (`batch_tools.py:65`)：靠消息匹配判 429/rate limit/overloaded（跨 SDK 兜底）。

- **`compile_fanout(skill, briefs_json, concurrency=0) -> str`** (`batch_tools.py:71`，`@tool`)：
  - **作用**：并发派发**同一个 fork skill** 给多个 brief，收齐输出。用于 draft/grade 这类**可并行**阶段（纯 LLM + 检索/本地写，不碰设备可变态）。比逐个串行快 ≈N 倍，各 fork 互相隔离不串话。
  - **关键入参**：`briefs_json`（JSON 数组，每项 `{key, brief}`，key 仅用于把输出对回 case）；`concurrency` 默认 0=auto。
  - **返回**：JSON 数组 `{key, ok, output}`，顺序与输入一致；单 fork 失败（`ok=false`）不影响其它。
  - **实现**：`ThreadPoolExecutor(max_workers=_resolve_concurrency)`，`_run` 内对 429 指数退避（`_RATE_LIMIT_MAX_RETRIES=4`），单 fork 超时 `_FORK_TIMEOUT_S=900`。
  - **位置**：编译链 draft/grade 阶段的可复用 fan-out 原语；`_run_pipeline` 选择内联自管 fan-out，故主流水线未走它，但它是 fan-out 阶段的独立工具/外部入口。
  - **红线**：**上机绝不用本工具**（注释明确：上机受框架全局锁 + 设备共享态约束，必须串行）。

- **`dev_run_batch(xlsx_path, autoids_json, module="", build="", max_s_each=600) -> str`** (`batch_tools.py:163`，`@tool`)：
  - **作用**：把一个合并 xlsx 里多个 case **顺序上机**，逐个回 verdict + 框架真实裁决。属 `ist_verify` 上机环节（**不在编译流水线内**）。
  - **串行硬约束**：跳转机框架有全局运行锁（`run_and_wait` 拿不到 task_id 即"submit failed (lock held?)"）+ 设备配置/统计全局共享态——内部就是一条 SSH 会话的 for 循环，**物理上不可能并发上机**。与 `dev_run_case` 区别：跑同一 xlsx 的一批 autoid，省 N-1 次 SSH 连接开销。
  - **关键入参**：`xlsx_path`（走 `_resolve_inside_root` 多根解析）、`autoids_json`（顺序即上机顺序）、`module`/`build`（默认取 `compiler config`）、`max_s_each`（夹紧 30~1200）。
  - **返回**：JSON 数组 `{autoid, verdict, task_id, causality(check_point 真实裁决行), detail_tail}`；非 pass 附 `device_context`（配置会话每条命令的设备响应 + dig 真实输出，供 agent 改配置/填 `<RUNTIME>`）。
  - **verdict 语义**：来自框架 MySQL 每个 check_point，pass = fail num 全 0 且 success>0；**pytest "1 passed" 不代表断言通过**。`busy`（撞锁）显式标出交 agent 决策，不误判为编译错误；单 case error 不中断后续。

- **`compile_emit_merged(cases_json, shared_init="", out_name="") -> str`** (`emit_xlsx_tool.py:494`，`@tool`)：
  - **作用**：把多个 case 合并成一个 `case.xlsx`（每脑图一个 excel 的打包工具），末尾自动垫**哨兵 case**（框架延迟执行契约，保前 N 个真 case 全部正常执行）。**编译链最后一步（merge）**，被 `_run_pipeline` 调用一次（`compile_pipeline.py:488`）。
  - **关键入参**：`cases_json`（每项 `{autoid, steps, init, title?}`，**每 case 自带自包含 init**——框架每跑一个 case 前清设备配置，基线不同各写各的，绝不共用）；`shared_init` 仅用于所有 case 真正共享且每 case 前都要重跑的文件级前置（C=1，多数留空）。
  - **返回**：产出路径 + round-trip 对账（case 数应=输入数+1 哨兵）。
  - **红线**：本工具不产任何命令，init/steps 全由查过手册/先例的子 agent 提供（零硬编码）。

---

### 红线/设计意图汇总

- **零硬编码**：prep/fanout/pipeline/merge 全程不含任何 sdns/APV 具体命令；命令、期望值由 draft fork 现场查 footprint/手册/先例产出。算法枚举 `_SDNS_METHODS` 是唯一例外（手册快照，已标 TODO 待 footprint 补全后运行时派生）。
- **自由度分配**：确定性机制在编排层（固定 prep→draft→grade→merge 序列锁进工具），语义自由只在 draft/grade fork 内部——对照 Cursor create-skill "Degrees of Freedom" / ngs-analysis 范式。
- **correct-by-construction**：B 层 `_check_variant_fidelity` 在 grade 前拦截"偷换/缺配"变体；`_extract_xlsx_path` 新鲜度校验拦旧草稿污染；`_parse_grade_verdict` 取末位裁定防误读 churn。
- **不救场**：grade 连续 `_MAX_REWORK_ROUNDS=3` 轮 CUT → `escalated` 如实上报，不降标准放行。
- **编译/上机解耦**：编译流水线**不上机**（`compile_pipeline` 只产 excel）；`dev_run_batch` 属独立 `ist_verify` 环节，运行时值留 `<RUNTIME>` 待上机回填。
- **可观测性**：limiter `history` 轨迹、fork trace、phases 进度全落进 result，escalated/errors 显式回报。

相关文件（绝对路径）：
- `/Users/jiangyongze/Library/CloudStorage/SynologyDrive-home/Project/InfoTest_Engine/main/ist_core/tools/device/compile_pipeline.py`
- `/Users/jiangyongze/Library/CloudStorage/SynologyDrive-home/Project/InfoTest_Engine/main/ist_core/tools/device/compile_prep.py`
- `/Users/jiangyongze/Library/CloudStorage/SynologyDrive-home/Project/InfoTest_Engine/main/ist_core/tools/device/batch_tools.py`
- `/Users/jiangyongze/Library/CloudStorage/SynologyDrive-home/Project/InfoTest_Engine/main/ist_core/resilience.py`（`AdaptiveLimiter` / `is_transient_error`）
- `/Users/jiangyongze/Library/CloudStorage/SynologyDrive-home/Project/InfoTest_Engine/main/ist_core/tools/device/emit_xlsx_tool.py`（`compile_emit_merged`）
- `/Users/jiangyongze/Library/CloudStorage/SynologyDrive-home/Project/InfoTest_Engine/main/ist_core/skills/loader.py`（`execute_fork_skill`）


---

## 四、确定性闸门(emit 出口 + 结构门)

编译链的最后一道关卡。draft 子流程查手册/先例后产出步骤列表,通过 `compile_emit` / `compile_emit_merged` 落地为框架原生 `case.xlsx`。这两个工具不是简单的格式转换器,而是**确定性闸门集合的执行点**:在产出 xlsx 之前,串行跑过一组 `_gate_*` 与可选的结构门,任何一道挡住即打回 draft 并附带可执行的修正指引。

**核心设计意图:correct-by-construction(对应论文命题 3.18)**。所有门只执行**与意图无关的确定性结构/类型规则**(IP 是否可达、命令是否破坏性、持久化命令对是否配对、命令模块是否在手册树里、断言是否悬空),**绝不替 LLM 决定"测什么/用什么命令序列/写什么断言"**(H_G≠0 的语义决策永远交给 LLM)。门是确定性的"闸",过程是自由的"路"。

**红线**:门内零硬编码具体 IP/命令——IP 可达集从 `env_facts` 派生,命令 allowlist 从 footprint 知识树派生。下面逐门拆解。

---

### 4.1 emit 出口工具

#### `compile_emit`(单 case 出口)
`emit_xlsx_tool.py:350-491`

一句话职责:从步骤列表产出**结构 100% 合法**的单 case `case.xlsx`(克隆框架原生模板,只重写数据区)。

- **关键入参**:
  - `autoid` — case 主键(写入 A 列)。
  - `steps_json` — JSON 数组字符串,每项 `{E,F,G,H?,I?,desc?}`(E=操作对象 / F=方法 / G=数据,H/I 跨步骤传值)。
  - `init_commands` — 文件级前置(C=1),空则取 `get_config().default_init_g()`。
  - `strict_structural` — v2 编译链置 `True` 时启用结构门(命令 allowlist + 断言非悬空);v1 默认 `False` 行为零变化。
  - `provenance_json` — v3 三层 Provenance IR;传入则旁挂 `case.provenance.json`,且在 `strict_structural=True` 时强制 `device_runtime ⟺ <RUNTIME>` 占位自洽(`emit_xlsx_tool.py:472-479`)。
  - `expected_save_variant` — 仅持久化类用例传(`memory|file|all|net`),供持久化门校验意图变体(P1c)。
- **返回**:产出路径 + round-trip 行数统计 + provenance 旁挂提示;失败返回 `error: ...`。
- **在编译链里的位置**:`ist_compile_draft` fork 子流程查完前置/先例后调用,是 draft 的产出动作。门挡回时 draft 据 `error` 文本重写。
- **门执行顺序**(`emit_xlsx_tool.py:416-442`):`_gate_unreachable_ips` → `_gate_unreachable_listener` → `_gate_destructive_commands` → `_gate_save_restore_pairing` →(opt-in)`check_structural_constraints` → `_steps_to_caseir` → 垫哨兵 → `emit_xlsx`。

#### `compile_emit_merged`(批量打包出口)
`emit_xlsx_tool.py:494-610`

一句话职责:把同一脑图里逐个生成好的 N 个 case 合并成一个 `case.xlsx`(每脑图一个 excel 的收尾打包),末尾垫哨兵保证前 N 个真 case 全执行。

- **关键入参**:`cases_json`(JSON 数组,每项 `{autoid, steps, init?, title?, expected_save_variant?}`)、`shared_init`(文件级共享前置,通常留空)、`out_name`(输出子目录)。
- **每 case 自包含前置**:框架每跑一个 case 前会清设备配置,所以每个 case 的基线必须放进它自己的 `init`(emit 成该 case 首个 `APV_0` 配置步骤,`emit_xlsx_tool.py:578-581`)。不同 case 基线不同时各写各的,绝不共用。
- **逐 case 跑同一组四门**(`emit_xlsx_tool.py:558-576`):与单 case 完全相同的 `_gate_*`,只是 `init=case_init` 逐 case 校验、错误前缀 `cases[{idx}]`。`autoid` 去重(主键,`emit_xlsx_tool.py:546-548`)。
- **位置**:`ist_compile_batch` 编排的 `compile_emit_merged` 合并阶段,fan-out 出 N 个 case 后的打包动作。

#### 两个共用的死知识契约
- **哨兵垫底**(`_SENTINEL_AUTOID="999999999999999"`,`_build_sentinel` @ `emit_xlsx_tool.py:32-39`):框架 `test_xlsx.py` 是**延迟执行模型**——最后一个 case 走 `if last_case` 收尾分支不执行步骤。所以 xlsx 末尾必须垫一个 `show version`(无副作用只读)哨兵,让所有真 case 都不是最后一个、走正常执行路径。
- **`_steps_to_caseir`**(`emit_xlsx_tool.py:42-71`):步骤列表 → `CaseIR` 的单一构造点,单 case 与合并多 case 共用,保证 stmt_type 递增/列语义一致;**内含 check_point 必存校验**——无任何 check_point 步骤直接打回(`emit_xlsx_tool.py:66-68`,"pass 需 success>0,上机必 fail")。

---

### 4.2 可达性门 `_gate_unreachable_ips`(IP 连接可达性)
`emit_xlsx_tool.py:74-119`

- **挡什么病**:draft 凭空写 `1.1.1.1` / `2.2.2.2` 等示例 IP 当 service IP → 设备不可达 → dig 失败 → 断言全 fail(`draft-assertion-systematic-fails` 病根 1)。
- **判定逻辑**:只校验**配置类**(`APV*` 的 `cmd_config/cmds_config`)与 `test_env` 触发步骤的 G 列 + `init`,对每段文本调 `facts.unreachable_ipv4s(t)`(`emit_xlsx_tool.py:106-113`)。`check_point` 期望文本里的正则/IP 片段不拦(那是断言匹配目标,不是要连接的设备)。
- **为什么是确定性结构规则**:"IP 是否落在测试床任何子网内"是拓扑客观事实,与"测什么"无关。是**事实源白名单投影**——发现不可达就打回并把可达集(`facts.summary_for_agent()`)原样告诉 draft 让它重写(供给+校验,不做事后猜测映射,非死字典)。
- **回归护栏**:`facts.devices` 缺失(JSON 不存在)→ 宽松降级不拦(`emit_xlsx_tool.py:93`,与 `ssh.py` 一致);消融实验 Arm-E(`is_baseline()`)跳过此门模拟裸生成(`emit_xlsx_tool.py:88-89`)。

### 4.3 触发可达性门 `_gate_unreachable_listener`
`emit_xlsx_tool.py:301-346`

- **挡什么病**(655233 类):listener/VIP 配在 APV 的纯管理/纯后端段接口(如 `172.16.35.70`),该网段没有路由器/客户端(触发源),dig/curl 源够不着 → NXDOMAIN/无应答、断言全 fail。
- **判定逻辑**:取 `facts.unreachable_lb_ips()` 作为"触发够不着"盲区集(`emit_xlsx_tool.py:316`);扫配置 listener/VIP 的 `APV*` 步骤 + `test_env` 触发步骤的所有 IP,命中盲区即打回,并给出触发设备够得着的 `facts.listener_ips()`(`emit_xlsx_tool.py:340-345`)。
- **与 4.2 的区别**:4.2 管"IP 在不在任何子网"(连接可达),本门管"IP 在不在**触发同段**"(触发可达)——两个正交的拓扑事实。
- **为什么确定性**:"IP 是否在触发同段"是拓扑客观事实,对 dig/curl/任意触发通用,不针对具体命令。env_facts 派生,零硬编码 IP。
- **回归护栏**:`is_baseline()` 跳过、`facts.devices` 空降级、`blind` 集为空降级(`emit_xlsx_tool.py:311-317`)。

### 4.4 破坏性命令门 `_gate_destructive_commands`(安全门)
`emit_xlsx_tool.py:122-162`

- **挡什么病**:`system reboot/reload/shutdown/halt/poweroff` 等设备生命周期命令(词边界正则 `_DESTRUCTIVE_RE` @ `emit_xlsx_tool.py:124`)。
- **两条理由**(都与意图无关、确定性可判):① 共享设备——上机 verify 跑到 `system reboot` 会真把别人在用的 APV 重启;② 框架不支持——`apv_ssh` 单连接、`read_until 5s`、无重连,重启后必在死通道读空 → 必 fail。
- **判定逻辑**:逐行扫 `init` + `APV*` 配置步骤的 G,命中即打回,并指引持久化意图改用不重启的 `clear→恢复` 范式(`emit_xlsx_tool.py:159-162`)。
- **为什么不误伤**:只匹配生命周期命令,**不碰** `clear/config`(持久化范式本身要用)。
- **回归护栏**:无破坏性命令 → 直接 `None`(`emit_xlsx_tool.py:154-155`),99% 用例零影响。

### 4.5 持久化结构门 `_gate_save_restore_pairing`(P0a/P0b/P1a/P1b/P1c)
`emit_xlsx_tool.py:213-298`

一句话职责:按执行顺序的有限状态校验,专治"配置保存/持久化"类用例的结构病(`write↔config` 对称命令对,先例 `log_backup`)。

- **触发条件(★ 核心回归护栏)**:`_ordered_apv_cmds` 取按执行顺序的 APV 命令行后,**仅当含 `config memory/file/all/net` 恢复命令时才进闸**(`emit_xlsx_tool.py:233-235`)。listener/forward/rr/pool 等 99% 用例无恢复命令 → 直接 no-op,行为零变化。
- **五条子门**(都与意图无关、确定性可判):
  - **P0a 基线污染**(`emit_xlsx_tool.py:241-246`):首个 listener 配置之前不得有 `write` 保存(否则 `config` 恢复的是配 listener 之前的旧快照 → `not_found` 假通过,668015 类)。
  - **P0b 紧邻配对**(`emit_xlsx_tool.py:249-260`):每个 `config X` 须配对其**前最近**的 `write Y` 且同族(`memory/file/all/net` 各恢复各的存储),不是无序集合成员。
  - **P1a 清除步**(`emit_xlsx_tool.py:263-267`):配 listener 与首个 `config` 恢复之间须有 `no sdns listener / clear sdns`(否则恢复成空操作、`not_found` 永真、测试空转,668015/044 类)。
  - **P1b 参数完整**(`emit_xlsx_tool.py:270-275`):`file/all/net` 变体须带参数(裸 `write net` 设备拒,668044 类);`memory` 无参合法(`_SAVE_REMOTE` @ `emit_xlsx_tool.py:169`)。
  - **P1c 意图变体**(`emit_xlsx_tool.py:278-291`):被 `config` 配对的 save 变体须 == manifest 透传的 `expected_save_variant`(防 draft 偷换 `write all→write memory`,668030 类)。**缺 expected 则 no-op 放行**(防误拒)。
- **辅助函数**:`_save_family`/`_restore_family`(`emit_xlsx_tool.py:177-184`)正则提族;`_norm_family`(`emit_xlsx_tool.py:172-174`)把 `mem→memory` 归一;`_param_tail`(`emit_xlsx_tool.py:207-210`)取命令族词后参数尾判缺参。
- **为什么是结构规则而非领域路由**:save/restore 必须同族配对、清除步必须存在、变体不能偷换——这些是持久化语义的**对称守恒约束**(命令对的有限状态机),与"测哪个功能"无关;能离线机械判定,无需上机。指引附正确范式 + 先例 `smoke_test/sdns/log_backup`(`emit_xlsx_tool.py:296-298`)。

### 4.6 结构约束门 `structural_gate.py`(opt-in,命令 allowlist + 断言非悬空)
`structural_gate.py` 全文 / 入口 `check_structural_constraints` @ `structural_gate.py:191-201`

一句话职责:与 grade(LLM 语义自评)**独立**的确定性强制,只在 v2 链 `strict_structural=True` 时启用(`emit_xlsx_tool.py:438-442`);v1 默认跳过,行为零变化。

数据结构:`StructuralViolation`(code/detail/step_index)+ `StructuralResult`(`.add()` 置 `ok=False`、`.render(autoid)` 渲染反馈给 draft)。两条子门:

- **① 命令 allowlist** `_check_command_allowlist`(`structural_gate.py:107-146`):
  - **挡什么病**:幻觉/越界命令。
  - **判定**:`_command_head_tokens`(`structural_gate.py:62-81`)剥 `no/show/clear` 前缀、剥参数值后取命令主体 token(如 `"no slb real http rs1"→["slb","real","http"]`);allowlist 从 footprint 知识树派生(`_load_allowlist_prefixes` @ `structural_gate.py:84-104`,取所有节点 `feature_id` 点分形式 + 一级模块根)。
  - **分级判定防误杀**(§八风险):footprint 空 → 整体跳过;命令**一级模块**(首 token)不在任何 footprint 模块 → 判违规(明显越界);模块在、具体命令路径不在 → 只 `logger` 记录不拦(footprint 可能没覆盖该子命令)。
  - **零硬编码**:allowlist 不是写死命令清单,而是 footprint 已验证命令集的投影。
- **② 断言非悬空** `_check_dangling_assertions`(`structural_gate.py:165-188`):
  - **挡什么病**(655203 崩溃类):悬空断言——`check_point` 之前最近的非 check_point 步骤不是观测算子(紧跟写配置后、或开篇就断言)→ 无回显可匹配 → 上机 Hit=0 必 fail。
  - **判定**:框架契约是 `check_point` 校验"上一个非 check_point 步骤"的输出;遍历步骤维护 `seen_observation` 标志,遇 `check_point` 时若前面无观测算子即违规(`structural_gate.py:173-188`)。`check_point` 自身不改 `seen_observation`(消费上一步输出、不产新回显)。
  - **观测算子判定** `_is_observation_step`(`structural_gate.py:149-162`):`test_env` 触发(dig/clientc/routera)天然回显;`APV*` 的 `show/statistics/dig/...`(`_OBSERVE_RE` 词边界匹配,避免 `listener` 误命中 `list`)算观测;纯写配置不算。
- **与 emit 既有门的分工**:IP 可达由 `_gate_unreachable_ips` 做,本门不重复(`structural_gate.py:6`)。
- **红线**(`structural_gate.py:8-9`、`render` 末句 `structural_gate.py:55-58`):只执行命令合法性 / 断言非悬空 / IP 可达这类与意图无关的类型规则,**绝不替 LLM 决定骨架选择**(命令序列/断言形态)。

---

### 设计意图小结

| 门 | 挡的病(典型 autoid) | 判定依据 | 零硬编码来源 | 回归护栏 |
|---|---|---|---|---|
| `_gate_unreachable_ips` | 不可达示例 IP(1.1.1.1) | IP∈子网可达集 | `env_facts` | devices 空降级 / baseline 跳过 |
| `_gate_unreachable_listener` | 触发够不着段(655233) | IP∈触发同段 | `env_facts` | blind 空降级 / baseline 跳过 |
| `_gate_destructive_commands` | reboot/reload 重启共享设备 | 词边界生命周期命令 | — | 无命中 no-op |
| `_gate_save_restore_pairing` | save/restore 失配(668015/044/030) | 有序状态机对称守恒 | — | 无 config 恢复命令不进闸 |
| `structural_gate ①` | 幻觉越界命令 | 命令模块∈footprint | footprint 树 | footprint 空跳过 / 子命令仅记录 |
| `structural_gate ②` | 悬空断言(655203) | 断言前须有观测算子 | 框架契约 | opt-in(strict_structural) |

所有门共享同一哲学:**确定性可机械判定的结构错误必须在 emit 出口挡死并反馈可执行修正**,语义决策一律不碰——这是 correct-by-construction 与"不救场"在工具层的落地。

相关文件:
- `/Users/jiangyongze/Library/CloudStorage/SynologyDrive-home/Project/InfoTest_Engine/main/ist_core/tools/device/emit_xlsx_tool.py`
- `/Users/jiangyongze/Library/CloudStorage/SynologyDrive-home/Project/InfoTest_Engine/main/ist_core/tools/device/structural_gate.py`


---

## 五、先例检索 / 上机验证 / 归因

> 本章覆盖 `main/ist_core/tools/device/` 下的检索、上机、回填、归因五个模块。它们共同支撑「编译只产 excel，ist_verify 独立上机回填」的解耦架构——**编译期不上机，上机期不改写断言形态**，真机裁决一律以框架 MySQL 的 `Success/Fail Num` 为准,绝不信 pytest 的 `=== 1 passed ===` 字符串。

### 5.1 先例检索与置信判分 —— `precedent_tools.py`

**一句话职责**：把「已验证先例检索」与「断言质量置信判分 f()」包成 agent 可调 tool；检索只按客观配置/意图结构相似度，判分交给 LLM 看真实证据，**两者都不写「某模式该用某断言」的规则表**。

**红线（文件头 `precedent_tools.py:3-12`）**：不写规则表、不做关键词意图匹配、不派魔数分；`f()` 只做快筛 + abstain，绝不单独定生死，终判仍上机。

#### 内部缓存与分词

- **`_load_mirror_corpus()`**（`precedent_tools.py:40`）：一次性解析 `knowledge/framework/mirror/**/*.xlsx` 全部先例并缓存为 `[{fn, cfg_tokens, seq}, ...]`，返回缓存列表。
  - 双检 + `threading.Lock`（`_MIRROR_CORPUS_LOCK`）线程安全：16 并发 draft 首调时只有一个线程做 openpyxl 解析，其余复用。**这是编译慢的主修复**——原来每次调用都全量加载 380+ 个 xlsx，被 GIL 串行化成 CPU 墙（`precedent_tools.py:33-37` 注释）。
  - 数据区从第 29 行起读 E/F/G 列；`cfg` 取 E 以 `APV` 开头行的 G 列拼成配置基线；`seq` 保留 `test_env/check_point/time` 与 `APV*` 行的**完整触发→断言链**（截 40 条）。
  - **设计意图（`precedent_tools.py:70-72`）**：旧版只留 show/method、把 `sdns on` 等启用基线滤掉，导致 draft 拼出残缺配置（服务不起、dig 零解析、断言全 fail）。现在基线原样可见，draft 才能照抄。
- **`_load_intent_index()`**（`precedent_tools.py:81`）：懒加载 `knowledge/framework/mirror_intent_index.json`（`{xlsx_basename: [intent_path,...]}`）。损坏/缺失返回空 dict → 意图轴自动退化，config 轴照常。
- **`_intent_tokens(text)`**（`precedent_tools.py:99`）/ **`_cmd_tokens(text)`**（`precedent_tools.py:150`）：分词。intent 走中英混排（字母词 + 中文 2-gram，无分词器、YAGNI 不上向量库）；cmd 只取字母开头的词、丢具体值（IP/数字/引号串）→ 只比「配了什么命令」，客观无领域偏好。
- **`_intent_similarity` / `_load_case_rows` / `_resolve_xlsx`**（`precedent_tools.py:116/133/158`）：Jaccard 意图相似度、读 case 数据区（遇 `999999` 哨兵停）、走 agent 沙箱多根解析定位 xlsx。

#### `compile_precedent(my_config, limit=3, intent="")` → str（`precedent_tools.py:174`）

- **作用**：给本用例配置/意图，返回最像的已验证先例（含完整触发→断言链）当参考。**双轴融合相似度**：config 轴（先例配置命令词与 `my_config` 的 Jaccard）+ intent 轴（`intent` 需求文本与先例脑图 `intent_path` 的词重叠）。
- **关键入参**：`my_config`（可空，走纯意图轴）；`intent`（原始需求原文，治「分布外猜不出 config 就检索不到」，`precedent_tools.py:184-186`）；两者都空才报错（`:208`）。
- **排序逻辑（`precedent_tools.py:224-229`）**：两轴都启用取等权和 `cfg_sim + intent_sim`；只一轴退化为该轴。无命中时返回「分布外/新类型，没现成范式可抄」提示（`:237`），引导 escalate-when-stuck。
- **消融臂**：`is_baseline()`（Arm-E 基线裸生成）时直接返回「本臂不检索先例」（`precedent_tools.py:198-204`）。
- **出口附真值（`precedent_tools.py:260-268`）**：返回里追加 `env_facts.summary_for_agent()` 本测试床真实可达集合——先例 G 列可能混历史脏 IP（`1.1.1.1`），agent 写 IP 时取真值，emit 出口会按此校验、不可达必打回。
- **链中位置 / 被谁调用**：`ist_compile_draft` fork 检索先例阶段调用，是 draft「照先例完整基线写」的弹药源。

#### `compile_score(xlsx_path, need_intent="", anchor_examples="", manual_facts="")` → str（`precedent_tools.py:272`）

- **作用**：判 case.xlsx 的断言「配不配得上它所测的配置行为」，给 CUT/PASS 决策。这是**第二判据，不是 verdict**（`:277-278`）——verdict 看「能不能跑通」，f() 看「断言有没有咬住需求要测的行为」。
- **关键入参**：`anchor_examples`（`compile_precedent` 返回的先例文本，判分锚点，强烈建议填）+ `manual_facts`（grep 手册得到的「该配置该产生什么可观测行为」）——证据越全判得越准。
- **返回（结构化 JSON，`precedent_tools.py:331-345`）**：`overall` / `abstain` / `decision` / 逐 check_point 的 `score+reasons` + `how_to_use`。`overall<0.5 → CUT`；**最弱 check_point 拖垮全局**（结构规则防强断言掩护弱断言，非领域硬编码，`:286`）。缺 LLM 时返回 `abstain` 而非硬猜分（`:324-330`）。
- **底层**：调 `main.case_compiler.confidence_f.score_case`（LLM 现场判，无硬规则）。
- **链中位置 / 被谁调用**：`ist_compile_grade` fork 的断言质量审批核心——**编译期质量门，不依赖上机裁决**（device verdict 可选）。

### 5.2 上机验证 oracle —— `run_case.py`

**一句话职责**：把整个 case.xlsx 下发到跳转机 pytest 框架真机跑完整流程，回设备 + 框架的真实裁决；这是**执行验证 oracle，不是 agent 自评**。

#### `dev_run_case(xlsx_path, autoid, module="", build="", max_s=600)` → str（`run_case.py:30`）

- **作用**：deliver xlsx 到跳转机 staging（框架自动 xlsx→python）→ `run_and_wait` 轮询到 done → 取 MySQL result。`pass` 条件 = `fail==0 且 success>0`（纯配置无断言必 fail，`run_case.py:51`）。
- **verdict 不信字符串（核心红线，`run_case.py:53-57` / `:166-170`）**：verdict 来自框架 MySQL 每个 check_point 结果，**不是 pytest 那行**。日志 `=== 1 passed ===` 只表示壳跑完没崩，**不代表断言通过**；真正看 `fail num is N`，任一 N>0 即 fail。工具把 `Success/Fail Num` 因果行单独抽出高亮（`:146-159`）。
- **关键入参**：`autoid`（xlsx A 列，单 case 跑指定那个）；`module`/`build` 默认取 `case_compiler.config.get_config()`（单一事实源，`run_case.py:96-102`）；`max_s` 夹紧到 `[30, 1200]`。
- **设备上下文（`run_case.py:137-140`）**：取 `client.fetch_case_detail(autoid)` 逐步骤执行明细（每条命令实发什么、断言拿什么和什么比，**ground truth**，原样回不解析）；非 pass 时额外 `fetch_device_context(autoid)` 拉配置会话每条命令的设备响应 + dig 真实输出，让 agent 知道怎么改配置/填 `<RUNTIME>`。
- **busy 信号（`run_case.py:123-127`）**：设备正验上一个 case 时显式 `verdict=busy`（非编译错），交 agent 决定等待/重试/上报。
- **底层**：复用 `case_compiler.device_mcp_client.FrameworkMCPClient`（单一事实源，跳转机 SSH 口令从 env `IST_JUMPHOST_PASS`/`JUMPHOST_PASS` 取，不落盘不回显）。
- **链中位置 / 被谁调用**：`ist_compile_run`（`ist-compile-run` agent，ist_verify skill 的执行核心）逐 case 上机采 ground truth。

#### `dev_probe(command)` → str（`run_case.py:182`）

- **作用**：经跳转机在被测 APV 上跑**单条只读 show/get 命令**，取真实回显。硬白名单：首 token 必须 `show`/`get`（`run_case.py:217`）。
- **拓扑约束（`run_case.py:184-188`）**：APV 只能经跳转机访问，`dev_ssh`/`dev_rest` 直打 APV IP 不通——是拓扑使然非掉线。
- **核心策略（`run_case.py:193-199`）**：把「难直接断言的动态行为」（会话保持、rr 轮询分布、连接保持）转成「可文本查找的稳定输出」——先探出对应 show 命令、看输出，再把断言改成对稳定输出做 found/not_found，把 xlsx 表达不了的动态比对降成文本查找。
- **红线**：断言期望值仍须有出处（作者意图/规范/先例），**不要「看这次输出是啥就照抄成期望」**（`run_case.py:210-211`）——反 observe-then-assert。

### 5.3 上机回填 —— `runtime_fill_tools.py`

**一句话职责**：列 `<RUNTIME>` 槽位 + 把设备真实值**锁死回填**进 case.xlsx；本模块不编值、不解析领域语义，值由 fork 看设备真实输出给定，锁由结构性保证。

#### `compile_runtime_slots(xlsx_path)` → str（`runtime_fill_tools.py:39`）

- **作用**：列出所有**待回填的 `<RUNTIME>` 槽位**（draft 诚实留空的离线不可知期望值）。每槽给 `slot_id/autoid/row/current_g/method/observe_obj/observe_cmd`（**紧邻前序观测步命令**——回填值就从这条命令的设备真实输出里抽）。
- **幂等（`runtime_fill_tools.py:50-51`）**：已回填槽位填完即不含 `<RUNTIME>`，天然不再出现在列表里 → 重复调用幂等。`count=0` 表示无待填。
- **底层**：`case_compiler.runtime_fill.list_runtime_slots`。

#### `compile_runtime_fill(xlsx_path, fills_json, run_meta="")` → str（`runtime_fill_tools.py:71`）

- **作用**：把设备真实值锁死回填进 `<RUNTIME>` 槽位。**结构性锁（`runtime_fill_tools.py:73-78`）**：只动仍含 `<RUNTIME>` 的格子；填上后该格不再含占位符 → 后续任何回填都定位不到，**永不覆盖已填值**（锁不靠自律，靠结构）。同一槽位只能填一次,填错需人工介入。
- **关键入参**：`fills_json`（JSON 数组，每项 `slot_id`/`runtime_value`/可选 `evidence`）。值必须来自设备真实输出（`dev_run_batch`/`dev_run_case`/`dev_probe`），**抽不出就给空值＝如实留空，绝不猜一个**（`runtime_fill_tools.py:79-81`）。`run_meta` 写入 provenance 溯源。
- **返回**：`filled` / `left_blank(如实留空)` / `not_found(已锁死/id 错)` 各 slot_id + 明细 + 仍待回填槽位数。
- **底层**：`case_compiler.runtime_fill.apply_fills`。
- **链中位置 / 被谁调用**：ist-fill fork——先 `dev_run_batch`/`dev_run_case` 拿设备输出，再 `compile_runtime_slots` 看待填槽位，最后 `compile_runtime_fill` 锁死写入（`runtime_fill_tools.py:3-8`）。这是「编译留 `<RUNTIME>` 空 → 上机回填真值」解耦的回填半环。

### 5.4 四层归因 —— `fail_attribution.py`

**一句话职责**：把一个上机 fail 的 check_point 确定性归到 G/E/V/瞬态四层之一并按层路由回流（论文 §5.4）。

- **`AttributionResult`**（`fail_attribution.py:43`）：`layer` / `reason` / `reflow`（是否回流，瞬态=False）/ `target_layer`（回流给 draft 改哪层）。`render()` 给一行式渲染。
- **`attribute_fail(verdict_detail, *, failing_assertion_layer="", failing_assertion_source_kind="")`**（`fail_attribution.py:64`）：确定性分类，**优先级（`:79-96`）**：① 瞬态信号最高优先（SSH/超时/NXDOMAIN，环境抖动**不回流**）→ ② E 错（dig 无解析/后端不通，回流 E）→ ③ G 错（命令非法/配置未生效，回流 G）→ ④ 默认 V 错（有回显但断言不命中，回流目标优先用 provenance 的 `failing_assertion_layer`）。三组关键词表见 `_TRANSIENT_MARKERS`/`_E_MARKERS`/`_G_MARKERS`（`:25-40`）。
- **`compile_attribute(...)`** → str（`fail_attribution.py:99`）：tool 包装，返回 JSON `{layer,reason,reflow,target_layer,render}`。供 verify 子流程对每个 fail 先确定性初分、再人工核对语义。
- **设计意图（`fail_attribution.py:9-12`）**：这是**确定性分类器，不替代 verify agent 的语义判断**——agent 用它做初分。瞬态与编译质量无关、不回流；G/E/V 错带回流目标层反馈 draft，是「verify 发现真实断言问题→回流重编译」的分诊器。

### 5.5 意图族聚类 —— `intent_cluster.py`

**一句话职责**：把一批待编译 case 按意图相似度聚成族，族内共享一次骨架（G 段）推导，把 `H_G` 从「×case 数」降到「×族数」（论文定理 3.10）。

- **`cluster_by_intent(cases, threshold=0.5)`**（`intent_cluster.py:41`）：贪心连通分量聚类（`sim≥threshold` 即同族），`cases=[{"key":autoid,"intent":需求文本},...]`，族首=族内第一个出现的 case。**纯确定性，同输入同输出，不调 LLM、不读环境**（`:48`）。复用 `precedent_tools._intent_tokens` 做 Jaccard（`_pair_similarity`，`:21`），不上向量库。
- **`IntentFamily`**（`intent_cluster.py:29`）：`family_id`/`member_keys`/`head_key`/`head_intent` + `size()`。
- **`summarize_families(families)`**（`intent_cluster.py:78`）：一行摘要（族数/最大族/单元素族数/`H_G` 摊销比 `total→len(families)`）。
- **`qa_cluster_intents(cases_json, threshold=0.5)`** → str（`intent_cluster.py:91`）：tool 包装，返回 `{summary, families:[{family_id,head_key,head_intent,member_keys}]}`。
- **链中位置 / 被谁调用**：编排器（`ist_compile_batch`/fanout）据此**每族只编一次族骨架**，再把族骨架塞进同族 member 的 draft brief；**聚类只决定「哪些 case 共享一次骨架推导」，骨架内容仍由 draft（族首）的 LLM 决策**，不替代骨架内容（`intent_cluster.py:7-8`）。

### 5.6 解耦与「真机裁决不信 verdict 字符串」总结

- **编译产 excel / ist_verify 上机回填解耦**：编译链（draft→grade）只产 excel，离线不可知的运行时值由 draft 诚实留 `<RUNTIME>`（5.1 检索 + 5.3 列槽）；`ist_verify` 独立对成品 excel 上机（5.2 `dev_run_case`）采真值后 `compile_runtime_fill` 锁死回填（5.3）。两半通过 `<RUNTIME>` 占位符 + 结构性锁衔接，互不污染。
- **真机裁决不信 verdict 字符串**：`dev_run_case` 显式以框架 MySQL `Success/Fail Num` 为唯一裁决，主动抽因果行高亮、原样回执行明细 ground truth，并文档化警告 `=== 1 passed ===` 不代表断言通过（`run_case.py:53-57/146-170`）。
- **三道不救场红线贯穿**：检索无命中 → escalate（5.1）；判分缺 LLM → abstain 不硬猜（5.1）；回填抽不出真值 → 如实留空绝不猜 + 结构锁防覆盖（5.3）；fail 瞬态 → 不回流（5.4）。

**相关文件**（绝对路径）：
- `/Users/jiangyongze/Library/CloudStorage/SynologyDrive-home/Project/InfoTest_Engine/main/ist_core/tools/device/precedent_tools.py`
- `/Users/jiangyongze/Library/CloudStorage/SynologyDrive-home/Project/InfoTest_Engine/main/ist_core/tools/device/run_case.py`
- `/Users/jiangyongze/Library/CloudStorage/SynologyDrive-home/Project/InfoTest_Engine/main/ist_core/tools/device/runtime_fill_tools.py`
- `/Users/jiangyongze/Library/CloudStorage/SynologyDrive-home/Project/InfoTest_Engine/main/ist_core/tools/device/fail_attribution.py`
- `/Users/jiangyongze/Library/CloudStorage/SynologyDrive-home/Project/InfoTest_Engine/main/ist_core/tools/device/intent_cluster.py`


---

## 六、footprint 知识树 + 环境事实源

这一层给 draft 子流程供"命令语法 / 配置语义 / 期望真值"两类 grounding：**footprint 知识树**回答"这条 CLI 命令怎么写、有什么规则/缺陷"（手册事实树），**env_facts** 回答"IP 该填哪个真实可达值"（从拓扑 JSON 派生，零硬编码）。两者都遵守同一红线：领域内容不写死在代码里，全部来自可编辑事实源（手册原文 / 拓扑 JSON），代码只做结构与校验。

### 6.1 footprint 数据结构（`memory/footprint/schema.py`）

一句话职责：定义 footprint 节点 schema v3 与三个流水线 dataclass，是 extract→route→merge→reconcile 全链共享的契约。

- **`RawFact`**（`schema.py:17`）— extractor 反序列化 LLM 输出的一条原始事实。关键字段：`fact_kind`（`cli_command|decision_rule|behavior|known_issue` 四选一）、`feature_path`（命令主体 token 序列）、`fact_key`（同 path 下的 dedup 短标识）、按 kind 分别填的 `cli_syntax`/`parameters`/`condition`+`decision`/`content`/`issue_id`+`issue_title`，以及 `evidence_file`+`evidence_quote`（merge 闸校验用）和 `source_thread`。
- **`RoutedFact`**（`schema.py:43`）— route 阶段产物：`fact` + `level`（路由阶段恒 `leaf`，真实 level 由 reconcile 重算）+ `target_file`。
- **`MergeResult`**（`schema.py:52`）— merge 单条结果：`action`（`create`/`append`/`update`/`skip`）+ `target_file` + `detail`。
- **`node_template(feature_id, level="leaf")`**（`schema.py:70`）— v3 节点 JSON 模板。schema v3 字段：`schema_version=3`、`feature_id`、`level`、`cli.commands[]`、`decision_rules[]`、`behaviors[]`、`known_issues[]`、`children[]`、`version_scope`、`footprint_meta`（`created_at`/`verified_count`/`source_threads`）。`leaf/trunk/branch/root_template` 是它的薄封装；`TEMPLATE_MAP`（`schema.py:110`）按 level 取模板。
- **`LEVEL_KINDS`**（`schema.py:120`）— level→允许的 fact_kind 集合。当前四种 level 全部放行四种 kind（merge 里只作兜底 gating）。

设计意图：LLM 一次输出对齐 schema 的全部结构化字段，代码"只做反序列化、路由、合并"，**不再用关键词正则判断 slot / level**（`schema.py:3`）。

### 6.2 提取（`memory/footprint/extractor.py`）

一句话职责：用 LLM 把一份 working memory 文本读成 `list[RawFact]`，代码只做反序列化和最小校验，不做语义切分。在编译链外、由 dream consolidate 阶段调用。

- **`extract_facts(content, *, llm_chat, existing_facts)`**（`extractor.py:322`）— 唯一公开入口。把 `_format_existing_facts(existing_facts)` 拼到 `content` 前作 user prompt，配 `_SYSTEM_PROMPT` 调 `llm_chat(system, user)`，再交 `_parse_llm_response` 反序列化。`llm_chat=None` 时直接返回 `[]`（无 LLM 即静默降级）。被 `dream.py:526` 调用。
- **`_SYSTEM_PROMPT`**（`extractor.py:20`）— 提取契约。约束 LLM：cli_syntax 必须是**完整规范签名**（综合参数表还原，不照抄残片、不把示例具体值当命令 token）；`no/show/clear/配置` 四态各自提取（feature_path 相同会自动归一节点）；evidence_quote 必须是原文片段（merge 会 grep 验证）；架构名词/项目代号不收；known_issue 的 issue_title 照抄 `kb_bug_search` 原文。
- **`_parse_llm_response(raw, thread_id)`**（`extractor.py:220`）— 反序列化 + 最小校验：kind 须在白名单；cli_command 须有 cli_syntax；decision_rule 须 condition+decision 双填；behavior 须 content；known_issue 须 issue_id；feature_path/fact_key 为空则丢。evidence_quote 截断到 300 字符。
- **`_feature_path_from_syntax(cli_syntax)`**（`extractor.py:147`）— **cli_command 的 path 由代码从签名确定性派生**（不信 LLM 给的 path）：剥前导 `no/show/clear`（`_OP_PREFIXES`，仅这 3 个 legend 保留词）、剥所有记法参数 token（`<x>`/`[x]`/`{a|b}`/含 `|`）、去 markdown 转义。这保证 `slb real http <rs>` / `no slb real http` / `show slb real http` 三态归到同一 `feature_id`。
- **`_coerce_parameters(v)`**（`extractor.py:183`）— 清理参数表，只保证每参数有 `name`（dedup 键）、值是标量/标量列表；**不做字段白名单、不做关键词→bool 映射**，LLM 给什么存什么。
- **`_format_existing_facts(existing_facts)`**（`extractor.py:292`）— 把现有节点的 fact_key 清单注入 prompt，逼 LLM 复用同一 fact_key、收敛到已有节点，避免同义分裂。

红线：负面约束明确禁止提取 agent 工作计划 / 评审建议 / 文件导航日志 / 无原文证据的推测（`extractor.py:116`）。

### 6.3 路由（`memory/footprint/router.py`）

一句话职责：把 `RawFact` 按 `feature_path` 点分成 `feature_id`，落到扁平的 `nodes/<feature_id>.json`。纯结构判断。

- **`route_facts(facts, footprint_dir=None)`**（`router.py:19`）— 对每条 fact：`feature_id = ".".join(feature_path)`，产出 `RoutedFact(level="leaf", target_file=f"nodes/{feature_id}.json")`。`footprint_dir` 参数未使用。被 `dream.py:530` 与 `compile_writeback.py:118` 调用。

设计意图：level **不在这里定**——存储扁平，level 由 reconcile 全树重算后写回；不替 LLM 做"这命令值不值得记"的语义裁决，给了 fact 就落盘（`router.py:5`）。

### 6.4 合并 + 60% evidence 门（`memory/footprint/merger.py`）

一句话职责：把 `RoutedFact` 写入/合并到目标 JSON 的对应 schema slot，并守一道 evidence 校验闸防 LLM 幻觉。

- **`merge_fact(routed, footprint_dir)`**（`merger.py:298`）— 主入口。流程：① level/kind gating 兜底；② **evidence 闸**——非 known_issue 必须过 `_evidence_supports`，不过则 `skip(detail="evidence not found in source file")`；③ 按 `_DISPATCH` 分发到 4 个 `_append_*`；④ 文件不存在则用模板新建（`create`），存在则读出合并；⑤ 成功则 `_update_meta` 累加 `verified_count`、追加 `source_threads`（capped 10）。被 `dream.py:532` 与 `compile_writeback.py:124` 调用。
- **`_evidence_supports(fact)`**（`merger.py:106`）— evidence 门核心。known_issue 凭 issue_id 自带凭证免检；cli/rule/behavior 缺 quote/file 直接 false。先归一化（去行号/省略号/全角空格）后整段子串命中即过；否则走覆盖率。
- **`_covers_quote(quote, haystack)`**（`merger.py:89`）— **60% evidence 门**：`_EVIDENCE_COVERAGE = 0.6`（`merger.py:86`），检测 quote 中是否存在长度 ≥ 60% 的连续子串逐字出现在源文件里。容忍 LLM 首尾轻微改写，但不容忍整体编造；阈值与语言/绝对长度无关，**不用 `>=N 字符` 硬阈值**。
- **`_resolve_evidence_path(evidence_file)`**（`merger.py:44`）— 不硬编码 product/qa 子目录：先当相对/绝对路径，再在 `knowledge/data/markdown` 下按 basename `rglob` 兜底（兼容 LLM 只给文件名）。
- **`_append_cli_command(fp, fact)`**（`merger.py:200`）— **按完整 cli_syntax 去重（非 fact_key）**，让四态命令并存；syntax 完全相同则 `_merge_parameters`（`merger.py:177`，按 name 补全空字段）。其余 `_append_decision_rule`/`_append_behavior`（`merger.py:232`/`246`）按 fact_key 去重，`_append_known_issue`（`merger.py:259`）按 issue_id 去重并回填 title/affected_versions、leaf 节点同步进 `version_scope.product_versions`。

红线：evidence 60% 门是"防 LLM 幻觉/agent thought 复述污染"的硬闸（`merger.py:7`）——这正是 footprint 是"手册事实树"而非"模型自由发挥"的保证。

### 6.5 全树重算（`memory/footprint/reconcile.py`）

一句话职责：所有 fact 落盘后跑一遍，补建中间节点 + 自底向上重算 level + 写 children，让磁盘树完整自包含。纯结构操作。

- **`reconcile(footprint_dir)`**（`reconcile.py:41`）— ① 扫 `nodes/*.json` 建前缀树；② 按点号补建缺失的中间父节点（如 `slb`、`slb.policy` 空壳，用 `node_template`），计 `created`；③ 自底向上算 height（叶=0，父=max(子)+1）；④ `_height_to_level`（`reconcile.py:26`）：0=leaf / 1=trunk / ≥2=branch（"俄罗斯方块叠加"）；⑤ 每节点写回 `level` + 排序后的 `children`。返回 `{total, created, by_level}`。被 `dream.py:541` 在提取+合并全部完成后调用一次。

设计意图：树在磁盘上完整且自包含，**不依赖运行时前缀匹配**（`reconcile.py:10`）——但 index 仍保留前缀匹配兜底（见 6.6）。

### 6.6 内存索引（`memory/footprint/index.py`）

一句话职责：从 `nodes/*.json` 懒加载，建 dict 索引，提供精确查找 / 模糊搜索 / 统计，是 `kb_footprint` 与 reminder 自动注入的共用后端。进程级单例。

- **`FootprintIndex`**（`index.py:53`）— 三索引：`_nodes`（fid→data）、`_bug_index`（BUG-id→fid）、`_token_index`（token→fid 集）。`_ensure_loaded`（`index.py:67`）首访构建（~50ms/500 节点），把 feature_id 点分 token 与全 JSON 内容 token 一并入 `_token_index`。
- **`lookup(command)`**（`index.py:106`）— 精确查找。`key = ".".join(command.lower().split())`。命中节点：返回内容，缺 `children` 时回退前缀匹配补上（disk children 优先）；未命中但有 `key.` 前缀子节点：合成一个 `level="branch"` 的虚节点列子命令；都没有返回 None。
- **`search(query, *, top_k=3)`**（`index.py:147`）— 模糊搜索三路打分：BUG 命中 +100、token 命中 +5、都无则全文 token 计数兜底。返回 `[(fid, 格式化摘要)]`。
- **`stats()`**（`index.py:175`）/ **`list_nodes(level)`**（`index.py:203`）— 供 `/footprint stats` 与 `/footprint list`。
- **`invalidate()`**（`index.py:213`）/ 模块级 **`get_footprint_index()`**（`index.py:224`，单例，目录取自 `kp.KNOWLEDGE_FOOTPRINTS`）/ **`invalidate_footprint_index()`**（`index.py:234`，dream 写盘后失效，CLAUDE.md 记载的 reminder 自动注入即走此索引）。

### 6.7 查询工具 + 模块总开关上溯（`tools/knowledge/footprint_lookup.py`）

一句话职责：agent 在 draft/评审时按 CLI 命令名查 footprint，附带"模块总开关"硬提醒。给 draft 供命令语法/语义 grounding 的主入口。

- **`kb_footprint(command)`**（`footprint_lookup.py:96`，`@tool`）— 走 `get_footprint_index().lookup`。返回逻辑分四路：① 命中带命令节点→`_format_node` + 子命令清单；② 命中 branch 空壳→`_collect_descendant_command_nodes` 递归展开子树里**所有带命令的后代节点**（治"命令在孙节点单层展开会漏"）；③ branch 整树无命令→如实说明，不用 branch token 全树模糊（避免误导 draft）；④ lookup 返回 None（自然措辞如 "sdns host method rr"）→ `search` 模糊兜底只收带命令叶子。在 `metadata.py:187` 注册为 `read_only/concurrency_safe`，intent=`search`。
- **`_module_enable_hint(idx, command)`**（`footprint_lookup.py:25`）— **总开关上溯**。对任何 `<module> <sub...>` 查询，`idx.lookup(root)` 取模块根，用 `_ENABLE_CMD_RE`（`footprint_lookup.py:19`，匹配 `{on|off}`/`{enable|disable}`/结尾 `on`/`enable`）找根节点的启用命令，附在结果前作"用任何 {module} 功能前**必须先执行**"的硬提醒。根因（实测）：`sdns on` 存在模块根 `sdns` 节点里，查子功能时检索不到 → draft 漏总开关 → 服务不起、上机全 fail。**通用于任何模块，不写死具体命令**（`footprint_lookup.py:31`）。
- **`_format_node(data)`**（`footprint_lookup.py:51`）— footprint JSON → 人可读摘要（CLI/规则/行为/缺陷/版本，各截断）。

### 6.8 环境事实源（`tools/_shared/env_facts.py`）

一句话职责：网络拓扑的唯一真相，从 `knowledge/data/auto_env/network_topology.json` 派生"可达性投影"，同时供 draft 写 IP 前查真值（供给）与 emit 出口校验（校验门）。**零硬编码**——不写任何具体 IP/网段/设备类型常量，换测试床只改 JSON。

- **`EnvFacts`**（`env_facts.py:38`）— 拓扑内存投影。`_build`（`env_facts.py:48`）从设备 `ipv4` CIDR 派生 `_exact_ips`（精确白名单）与 `_subnets`（从掩码派生子网，如 172.16.35.231/24→172.16.35.0/24，**不写死网段**）；IPv6 仅精确白名单不派生子网。
  - **供给侧**：`service_ips()`（`env_facts.py:88`，后端服务器真实 IP，draft 写 service/pool 后端用）、`reachable_subnets()`、`summary_for_agent()`（`env_facts.py:169`，给 draft 子 agent 的事实摘要：listener 选址 + 后端 IP + 设备清单 + 选址规则 + "禁止裸用 1.1.1.1/10.x 示例 IP"）。
  - **校验侧**：`is_reachable(ip)`（`env_facts.py:67`，精确等于某设备 IP 或落在某子网内）、`unreachable_ipv4s(text)`（`env_facts.py:78`，从文本挑出所有不可达 IPv4）。
  - **触发可达派生**（listener/VIP 选址）：`listener_ips()`（`env_facts.py:141`）只返回**所在网段同时有触发设备（路由器/客户端）的 APV 接口 IP**——dig/curl 从触发设备发起须 L2 够得着；`unreachable_lb_ips()`（`env_facts.py:155`）返回纯管理/纯后端段的 APV 接口 IP（**禁止配 listener**，上机必不解析）。两者经 `_types_per_subnet`（`env_facts.py:109`）+ `_lb_ips_with_subnet`（`env_facts.py:124`）从拓扑 `type` 字段派生，设备类型分组词（`_SERVER_TYPES`/`_LB_TYPES`/`_TRIGGER_TYPES`，`env_facts.py:34`）也来自 JSON `type` 字段而非领域规则。
- **`get_env_facts()`**（`env_facts.py:198`，`lru_cache` 单例）/ **`is_reachable`** / **`unreachable_ipv4s`** 便捷函数。**宽松降级**：JSON 缺失/解析失败 → 空事实源，`is_reachable` 恒 True（放行不误杀，与 `ssh.py` 一致）。

设计红线：**白名单投影非黑名单翻译**（`env_facts.py:5`）——不去枚举"什么是示例 IP"，而是从拓扑客观派生"什么可达"，可达集之外（如 1.1.1.1）一律非法。子网从掩码派生，不写死网段。

**在编译链里的位置（消费方）**：
- `precedent_tools.py:266` — 先例检索时把 `summary_for_agent()` 拼进给 draft 的 grounding。
- `emit_xlsx_tool.py:111/119` — emit 出口用 `unreachable_ipv4s` 兜底拦不可达 IP；`emit_xlsx_tool.py:316/340/346` 用 `unreachable_lb_ips`/`listener_ips`/`summary_for_agent` 做 listener 选址校验。
- `ssh.py:108` — 上机前用 `is_reachable(host)` 守门。

### 6.9 消融开关（`tools/_shared/ablation.py`）

一句话职责：论文 §5 双臂对照（Arm-L 完整分层 vs Arm-E 基线裸生成）的唯一开关，生产默认不改变行为。

- **`current_arm()`**（`ablation.py:26`）/ **`is_baseline()`**（`ablation.py:32`）/ **`arm_tag()`**（`ablation.py:37`）— 读 env `IST_ABLATION_ARM`，非 `'E'` 一律按 `'L'`。Arm-E 在三注入点分叉：G 段 `compile_precedent` 不返先例、E 段 `compile_emit` 跳过可达校验门、V 段 `compile_score` 直接放行。设计红线：默认 L、只读 env 不写状态、每次现读便于同进程切臂跑对照。

### 6.10 工具元数据（`tools/_shared/metadata.py`）

一句话职责：runtime 工具元数据 registry，启动时由 `build_main_agent` 注入 LangChain Tool 的 `.metadata`。footprint/env 相关工具在此声明并发/只读语义。

- **`TOOL_METADATA`**（`metadata.py:31`）— 字段语义：`read_only`/`concurrency_safe`/`fallback_for`/`intent`。`kb_footprint`（`metadata.py:187`）声明 `read_only=True, concurrency_safe=True, intent="search"`；编译链的 `compile_precedent`/`compile_score`/`compile_emit`/`qa_compile_*` 等同在此表。
- **`attach_tool_metadata(tool_obj, *, strict=False)`**（`metadata.py:206`）— 合并不覆盖地注入 `.metadata`；未注册工具 `strict=False` 记 warning（红线：新增工具**必须**在此注册）。`get_tool_metadata`/`is_concurrency_safe`/`is_read_only` 为便捷查询（A3 partition 与 plan-mode 门用）。

---

### footprint 全链路位置小结

写入链（编译链外，dream consolidate 阶段，`dream.py:491-541`）：working memory → `extract_facts`（LLM + existing_facts 收敛）→ `route_facts`（点分 feature_id）→ `merge_fact`（60% evidence 门 + 按 kind 落 slot + verified_count 累加）→ `reconcile`（补中间节点 + 重算 level/children）→ `invalidate_footprint_index`。另有 `compile_writeback.py` 把编译期 G 层 provenance step 转成 cli_command RawFact 走同一 `route_facts`+`merge_fact` 写回（同样过 evidence 门）。

读取链（编译链内，给 draft grounding）：`kb_footprint`（agent 主动按命令名查，带模块总开关上溯）+ reminder 自动注入（`MemoryInjectionMiddleware` 走 `FootprintIndex`）→ 供命令语法/规则/缺陷；并行 `env_facts.summary_for_agent()` 供 IP 真值。两者共同构成 draft "correct-by-construction" 的事实供给，配 merge 的 60% evidence 门与 emit 的可达校验门实现"不救场、零硬编码"。

相关绝对路径：
- `/Users/jiangyongze/Library/CloudStorage/SynologyDrive-home/Project/InfoTest_Engine/main/ist_core/tools/knowledge/footprint_lookup.py`
- `/Users/jiangyongze/Library/CloudStorage/SynologyDrive-home/Project/InfoTest_Engine/main/ist_core/memory/footprint/{schema,extractor,router,merger,reconcile,index,__init__}.py`
- `/Users/jiangyongze/Library/CloudStorage/SynologyDrive-home/Project/InfoTest_Engine/main/ist_core/tools/_shared/{env_facts,ablation,metadata}.py`
- 消费方：`main/ist_core/tools/device/{precedent_tools.py:263-266,emit_xlsx_tool.py:84-346,ssh.py:103-108}`、`main/ist_core/memory/{dream.py:491-541,compile_writeback.py:103-124}`


---

## 七、skill / agent 编排层

把"主 agent 编排器 → 派发 fork 子流程"这件事落到代码。核心机制三件：①SKILL.md/agent.md 的双文件加载（`loader.py`）；②`invoke_skill`/`compile_fanout` 把任务文本派发进隔离 fresh subagent；③渐进披露 + 零写死命令红线。设计意图是用**进程级隔离**消除"自生成自评估"——draft 生成、grade 审批跑在彼此看不见、各自全新上下文的 subagent 里。

### 7.1 加载器 `main/ist_core/skills/loader.py`

一句话职责：解析 `skills/<name>/SKILL.md` 与 `agents/<name>.md` 两类定义文件，把 fork skill 装配成可执行的 LangChain subagent runnable 并驱动执行，同时落 fork 可观测性日志。

**双文件模型（设计意图，`loader.py:1-12`、`391-402`）**：fork skill 由两份文件拼成——SKILL.md 的 body 是**任务**（带 `$ARGUMENTS` 占位，渲染后作 `HumanMessage` 传入），`agents/<agent>.md` 的 body 是 subagent 的 **system_prompt**（容器行为约束/装配纪律）。两者职责严格分离：SKILL.md 描述"这次要做什么"，agent.md 描述"你是谁、守什么纪律"。

逐个公开函数：

- **`execute_fork_skill(skill_name, brief="") -> str`**（`loader.py:391`）——fork 执行总入口，编译链每一次派发子流程的落点。流程（`loader.py:404-476`）：①读 SKILL.md，校验 `context: fork`（非 fork 直接报错 `loader.py:413`）；②取 frontmatter `agent:` 字段，缺失即报错（fork skill 必须声明执行容器，`loader.py:416-422`）；③`get_subagent_runnable(agent_name)` 拿到 runnable；④`_render_skill_body` 把 SKILL.md body 的 `$ARGUMENTS` 替换为 `brief`；⑤`runnable.invoke({"messages":[HumanMessage(rendered_body)]})`；⑥从返回 messages 里**倒序**找最后一条非空 AIMessage 文本回传（`loader.py:453-466`）。被 `invoke_skill`（`tools/skills/__init__.py:81`）和 `compile_fanout`（`batch_tools.py:125`）调用。关键：subagent 的 system_prompt 来自 agent.md，**不是** SKILL.md body（`loader.py:402`）。

- **`get_subagent_runnable(name) -> runnable|None`**（`loader.py:332`）——按 name 缓存（`_SUBAGENT_RUNNABLE_CACHE`，`loader.py:143`）构建 LangChain agent：`load_subagent` 拿 spec → `_MODEL_MAP` 把 `model` 字段映射成 tier（`loader.py:136-140`、`349-351`）→ `build_agent_chat_model(ist_core_tier_model(tier))` → `_resolve_tools(spec["tools_spec"])` → `create_agent(...).with_config({"recursion_limit": 200})`（`loader.py:355-360`）。`recursion_limit=200` 是单个 fork 子流程内部的步数上限。`clear_subagent_cache()`（`loader.py:369`）供测试/热重载清缓存。

- **`load_subagent(name) -> dict|None`**（`loader.py:290`）——读 `agents/<name>.md`，返回 `{name, description, system_prompt, tools_spec, model}`。关键扩展字段 **`inherit-parent-prompt: bool`**（`loader.py:316-321`）：为 true 时在 agent body 前 prepend `build_verifier_inherited_sections()`——把主 agent 的反偷懒约束块（Read-Only / Evidence Discipline / Reading-vs-Verification / Faithful Reporting / Don't Spin）继承给 fork 子 agent。ist-compile-draft、ist-compile-grade 都开了此项（见 7.4 frontmatter）。

- **`_get_tool_registry() -> dict`** / `_TOOL_REGISTRY`（`loader.py:142-219`）——延迟加载的工具白名单。fork subagent 只能用注册表里的工具，frontmatter `tools:` 里写的名字必须在此命中才会被 `_resolve_tools`（`loader.py:262-282`）解析成真实工具对象，命不中静默丢弃。注册的编译相关工具：`compile_precedent`/`compile_score`（先例与判分，`loader.py:210-216`）、`compile_emit`/`dev_run_case`/`dev_probe`（单 case，`loader.py:184-194`）、`compile_prep`/`compile_emit_merged`/`compile_fanout`/`dev_run_batch`（批量编排，`loader.py:196-208`）、`kb_footprint`、`fs_grep/read_file/ls` 等。**这是 fork 子 agent 的能力边界硬约束**——draft 拿不到 grade 的判分工具、grade 拿不到 emit/run 工具（见 7.4），靠 frontmatter `tools:` + 注册表双重过滤实现。

- **可观测性三函数**（`loader.py:45-133`）：fork 内部 LLM 往返不进主 stream，故每次 fork 执行落两份日志。`_summarize_fork_messages`（`loader.py:73`）统计工具调用分布/AI 轮数/ToolMessage 数，并抽出 `fs_grep`/`kb_footprint` 的实际查询词（诊断"在查什么"）；`_trace_fork`（`loader.py:107`）写人读摘要到 `runtime/logs/fork_trace.log`；`_record_fork_status`（`loader.py:45`）写机读 JSONL 到 `runtime/logs/fork_status.jsonl`（崩溃时"哪些 fork 已完成、产出什么"不丢）。三者失败一律静默，绝不挂主流程（`loader.py:69`、`132`）。

- **渐进披露辅助**：`read_skill_frontmatter`（`loader.py:240`）、`skill_disable_model_invocation`（`loader.py:235`，`disable-model-invocation: true` 禁止主 agent 经 `invoke_skill` 加载）、`list_subagents`（`loader.py:374`）。

### 7.2 派发入口：`invoke_skill` 与 `compile_fanout`

- **`invoke_skill(skill, brief)`**（`tools/skills/__init__.py:25`）——主 agent 调技能的统一入口。校验技能名合法性、存在性、`is_callable_by_model`（渐进披露状态门，`__init__.py:58-65`）、`disable-model-invocation`（`__init__.py:72`）后分流：`context: fork` → `execute_fork_skill`（`__init__.py:79-81`）；inline → 直接返回 SKILL.md 文本注入主对话（`__init__.py:84`）。`docstring` 里的 **BLOCKING REQUIREMENT**（`__init__.py:32-34`）是渐进披露的措辞约束：技能描述命中用户请求时，必须先调本工具再做别的。

- **`compile_fanout(skill, briefs_json, concurrency=0)`**（`tools/device/batch_tools.py:72`）——批量并发派发。把 `briefs_json`（`[{"key":..., "brief":...}]` 数组）的每条 brief 通过 `execute_fork_skill(skill, item["brief"])` 在线程池里并发执行（`batch_tools.py:116-125`），返回每个 key 的产物。设计意图：比逐个 `invoke_skill` 串行快 N 倍且各 fork 互相隔离不串话（`batch_tools.py:77`）。**每条 brief 就是本来要传给 invoke_skill 的那段文本**（`batch_tools.py:83`）——fanout 只是并发包装，不改变单条派发语义。这是编排器把 draft/grade 阶段并发铺开的物理手段。

### 7.3 编排层四个 SKILL.md 的职责

| skill | context | 入口性 | 职责 | 关键约束 |
|---|---|---|---|---|
| `ist_compile_batch` | inline | user-invocable | **唯一编译入口/编排器**：通读用例→`compile_prep` 解析 manifest→`compile_fanout(draft)` 并发生成→`compile_fanout(grade)` 并发审批→`compile_emit_merged` 合并打包。单条是 N=1 特例同流程。 | 不上机（解耦）、编排器步数纪律、零命令进 brief |
| `ist_compile_draft` | fork (`agent: ist-compile-draft`) | 否 | 把一条用例生成单 case xlsx 草稿：核查前置→检索先例→`compile_emit`。 | 不上机、不自评、IP 只用测试床真实可达值 |
| `ist_compile_grade` | fork (`agent: ist-compile-grade`) | 否 | 独立审批 draft 断言是否真覆盖目标行为：`compile_score` → PASS/CUT + 重做意见。 | 只读、不生成不上机、审批不依赖上机裁决 |
| `ist_verify_v3` | inline | user-invocable | 对成品 excel 串行上机验证 v3 链：上机回填 `<RUNTIME>`→采集裁决→`compile_attribute` 四层归因(G/E/V/瞬态)按层回流→上机真 PASS 写回 footprint。 | 只验不生成、上机串行、只写回 G 段 |

**`ist_compile_batch`（编排器，`ist_compile_batch/SKILL.md`）要点**：

- **第一原则·零硬编码纯引导**（`SKILL.md:26-28`）：编排器和所有子流程的 brief 里绝不出现任何具体设备命令（sdns/slb CLI）、不按关键字分支、不逐 autoid 特殊处理。命令/参数/断言全由 draft 子 agent 现场查手册/查先例得出。
- **物理边界落在工具里**（`SKILL.md:30-37`）：解析/打包各一次、draft/grade 并发——这是工具层强制的并行性，不靠自律。
- **编译与上机验证解耦**（2026-06-16，`SKILL.md:38-39`、`134-137`）：本 skill 只产 excel，流程内**不调** `dev_run_batch`/`ist_compile_run`；上机走独立 `ist_verify`。原因：上机大面积失败常是设备环境瞬态（SSH 中断/dig 超时/DNS 失败），不该阻塞产出。
- **编排器步数纪律**（`SKILL.md:41-45`）：编排器有 recursion_limit 硬上限，**绝不自己逐 case grep 手册/probe 设备/查先例**（那会在解析阶段耗光步数让整批半途而废，有前车之鉴）。每脑图只允许 `prep(1)→读manifest→fanout(draft,1)→fanout(grade,1)→判定→重做fanout→emit_merged(1)`。
- **交付门槛是 grade 断言质量不是上机 pass**（`SKILL.md:87-92`、`136`）：grade CUT 即弱断言/未覆盖，**不救场**；连续 N 轮（建议 3）仍 CUT 标 `escalated`，不拿弱产物充数。
- **不救场+不空转**（`SKILL.md:88`、`94`）：合并哪些/要不要重做是编排器自主决策，**绝不 ask_user 问用户**；部分 PASS 部分 CUT 是常态（PASS 先合并、CUT 另行重做），非交互模式尤其不能卡在 ask_user 空转（撞 ask_user error 反复 ls/ask 转圈会被 loop guard 拦截）。
- **brief 五要素**（`SKILL.md:122-132`）：每条 draft brief 只含需求/现状/规则/指路/边界，逐项过滤"答案"。**自检三问**（`SKILL.md:132`）：这句是需求还是命令/期望值（后者删）；删后子 agent 是"查不到"还是"想不到"（查不到补"去哪查"不补答案）；换 build/设备还成立吗（不成立=领域写死了）。
- **版本校验前置**（`SKILL.md:49-54`）：缺版本立即 `ask_user`，不猜默认值；版本推出对版本手册 glob（`10.5` → `10.5_cli__part*.md`，禁用通配以免命中别版本）写进每条 brief 的指路。

**`ist_verify_v3` 要点**：相对 v2 三个增强（`SKILL.md:21-32`）——①上机回填 `<RUNTIME>`（draft 对离线不可知值诚实留占位、不猜；verify 用设备真实输出填且**锁死不反复改**，`compile_runtime_fill` 只动仍含 `<RUNTIME>` 的格子）；②四层归因（`compile_attribute` 把每个 fail 归 G/E/V/瞬态，按层定向回流比整条打回省）；③闭环写回（上机真 PASS 的 G 段文法写回 footprint，evidence 门防幻觉，V 段断言/E 段具体 IP 不写回以免污染，`SKILL.md:39`、`82`）。红线：裁决以框架逐 check_point 真实明细为准不信 verdict 字符串（`SKILL.md:36`）、归因如实不救场（`SKILL.md:38`）、上机串行只走 `dev_run_batch` 不并发（`SKILL.md:40`）。

### 7.4 两个 fork 子 agent 的角色与装配纪律

**`ist-compile-draft`（`agents/ist-compile-draft.md`）**——草稿生成子流程。

- frontmatter（`md:1-7`）：`tools: compile_precedent, compile_emit, dev_probe, fs_grep, fs_read, kb_footprint`；`model: opus`；`inherit-parent-prompt: true`。**工具集里没有 `dev_run_case`（不上机）、没有 `compile_score`（不自评）**——能力边界靠工具白名单物理切断，不靠提示词自律。
- 装配纪律（`md:9`、`19-37`）：核查前置（`compile_precedent` 取先例**完整 init** 完整沿用、`dev_probe` 查设备现状、grep **对版本**手册）→检索先例确定测法→`compile_emit` 生成。红线：**CLI 文档是唯一权威**（`md:34`，未明确定义的参数标"未生成"不推断）；**期望值溯源**不 observe-then-assert（`md:35`）；**不自评不上机**（`md:36`）；**IP 只用测试床真实可达值**，绝不照抄先例/手册示例 IP（1.1.1.1/10.x 等不可达，dig 必失败 Hit=0；`compile_emit` 出口按事实源校验打回，`draft/SKILL.md:16`）。

**`ist-compile-grade`（`agents/ist-compile-grade.md`）**——质量评估子流程。

- frontmatter（`md:1-7`）：`tools: compile_score, compile_precedent, fs_grep, fs_read`；`model: opus`；`inherit-parent-prompt: true`。**只读工具集，没有 `compile_emit`/`dev_run_case`**——物理上无法生成或上机，只能判分。
- 装配纪律（`md:9-41`）：判据是**断言覆盖度**这一与"能否跑通"正交的维度（`md:13-16`，即便跑通弱断言也判 CUT，这正是本子流程存在意义）；`compile_score` 判分 + **对抗性独立核对**（不只依赖判分，对照需求核心动态行为/对照先例，`md:28-32`）；CUT 必给**具体到可据以修改**的重做意见（哪条弱/为什么/参照哪个先例改成何形态，`md:35`）。红线：**不自评不重做**（评估对象是生成子流程产物非自身，修改属生成子流程，`md:38`）；**审批不卡上机**（环境能否跑通是 ist_verify 的事，`md:39`）；每个"此条弱"判断须引用 xlsx 行号+需求原文+先例/手册出处（`md:41`）。

### 7.5 编排层贯穿红线（设计意图汇总）

1. **隔离消除自评（correct-by-construction）**：draft（生成）/grade（审批）/run（上机）是三个独立 fresh subagent，各自全新上下文、彼此看不见——`execute_fork_skill` 每次新建 `HumanMessage` 会话，工具集互不重叠。"自生成自评估"在结构上不可能发生，不靠提示词约束。
2. **零写死 sdns/APV 命令**：编排器 brief 五要素 + 自检三问、draft "CLI 文档唯一权威"、grade "不硬编码命令"——任何具体设备命令都只能由子 agent 现场 grep 对版本手册/`compile_precedent` 查先例得出，进 brief/manifest 即视为滑回被推翻的硬编码老路。
3. **能力边界靠工具白名单物理切断**：`_TOOL_REGISTRY` + 各 agent.md `tools:` 字段双重过滤，draft 拿不到判分/上机工具、grade 拿不到生成/上机工具。
4. **不救场**：grade 严判弱断言/未覆盖判 CUT，连续 N 轮 CUT 标 escalated 不充数；ist_verify 归因如实不把环境失败粉饰成通过、不把断言失败甩锅环境。
5. **编译/上机解耦**：ist_compile_batch 流程内不上机，环境瞬态失败不挡 excel 产出；上机验证是独立 ist_verify 环节，由交互层 ask_user 串成回流闭环。

**相关文件**（绝对路径）：
- `/Users/jiangyongze/Library/CloudStorage/SynologyDrive-home/Project/InfoTest_Engine/main/ist_core/skills/loader.py`
- `/Users/jiangyongze/Library/CloudStorage/SynologyDrive-home/Project/InfoTest_Engine/main/ist_core/tools/skills/__init__.py`（`invoke_skill`）
- `/Users/jiangyongze/Library/CloudStorage/SynologyDrive-home/Project/InfoTest_Engine/main/ist_core/tools/device/batch_tools.py`（`compile_fanout`）
- `/Users/jiangyongze/Library/CloudStorage/SynologyDrive-home/Project/InfoTest_Engine/main/ist_core/skills/ist_compile_batch/SKILL.md`
- `/Users/jiangyongze/Library/CloudStorage/SynologyDrive-home/Project/InfoTest_Engine/main/ist_core/skills/ist_compile_draft/SKILL.md`
- `/Users/jiangyongze/Library/CloudStorage/SynologyDrive-home/Project/InfoTest_Engine/main/ist_core/skills/ist_compile_grade/SKILL.md`
- `/Users/jiangyongze/Library/CloudStorage/SynologyDrive-home/Project/InfoTest_Engine/main/ist_core/skills/ist_verify_v3/SKILL.md`
- `/Users/jiangyongze/Library/CloudStorage/SynologyDrive-home/Project/InfoTest_Engine/main/ist_core/agents/ist-compile-draft.md`
- `/Users/jiangyongze/Library/CloudStorage/SynologyDrive-home/Project/InfoTest_Engine/main/ist_core/agents/ist-compile-grade.md`

注：当前 skills/ 目录下另有并存的版本化变体（`ist_compile_v2`/`ist_compile_v3`/`ist_draft_v3`/`ist_grade_v3` 等，多为未提交的实验链路），本章按用户指定的 `ist_compile_batch`/`ist_compile_draft`/`ist_compile_grade`/`ist_verify_v3` 主线文档化。


---

# 八、当前问题、根因与天花板(2026-06-22 三脑图实测)

> 本章是诚实的实测记录:三个脑图(yzg/dongkl/zhaiyq)全程编译 + 逐个核因后的结论,含若干**自我修正**。

## 8.1 三脑图编译结果

| 脑图 | 主题 | 编译 emit | escalated | 备注 |
|---|---|---|---|---|
| yzg | SDNS 监听器(26) | 26/26 | 0 | 早期上机仅 6-7/24,修一串 bug 后(见 8.3) |
| dongkl | SDNS 域名算法 rr/wrr/ga(34) | 31/34 | 3(grade CUT) | ga 簇曾系统性错(见 8.4) |
| zhaiyq | 会话保持按记录类型(53) | 34/53 | 19(grade CUT) | 36% escalated,逐个核因见 8.5 |

## 8.2 失败的系统性分层(三脑图共性)

所有 fail 归三层,**责任主体不同**——这是看清"能不能修"的关键:

1. **编译器/draft 质量(AI 可修)**:变体偷换、漏绑定、选错 IP、凭空编值。已用 grounding + 确定性闸修掉大部分。
2. **xlsx DSL 表达力天花板(目标框架的,非 AI)**:跨步运行时值的捕获 + 比较表达不了。
3. **环境(测试床的)**:IPv6 段不存在、转发上游不可达、不支持重启。

## 8.3 yzg 详情

- **listener 可达性**:655233 等把 listener 配在触发设备够不着的网段(172.16.35.x 无路由器/客户端)→ dig NXDOMAIN。Fix2 触发可达性门修正(env 派生 ★ 可达段)。⚠ **遗留缺口:Fix2 门只查 IPv4,IPv6 listener(3ffc::)漏网**(zhaiyq ipv6 簇撞同一处)。
- **持久化簇(668000/15/30/44)**:原 draft 写 `system reboot`(会重启共享设备 + 框架不重连必 fail)。① 破坏性命令门拦 + ② footprint 补 config.memory/file/all/net + P0-P1 持久化结构门 → 改用 `write→clear→config 恢复→show→断言` 范式(参考人工先例 log_backup)。
- **长尾(ANSWER:0)**:dig 到达但无答案——后端健康检查/forward 上游/级联转发,属运行时/环境,非可达性。

## 8.4 dongkl 详情

- **ga 簇系统性 bug(681749/783/811/841 全配 wrr 而非 ga)**:draft 缺 ga grounding + brief"优先照先例"+ 预检索给的是 wrr 先例 → 先例支配。与持久化 668030(write all→memory)**同一类病:意图点名某枚举变体,draft 缺 grounding 就换成会的**。
  - 修:A 层 footprint 补算法枚举 + ga 行为(优先级故障切换);⚠ **实测 A 层单独不够**(draft 看到 grounding 仍抄 wrr 先例)。B 层变体保真门 + brief 算法提示对冲先例支配 → 实测两个 ga 首轮就产对 ga。
- **轮询断言是强断言**(非弱):用 `show statistics sdns pool` 的 Hit 计数验轮转,运行时计数正确留 `<RUNTIME>`。dongkl 最担心的"弱断言测不出轮询"未发生。
- 3 escalated 诚实弃权(grade 多轮 CUT)。

## 8.5 zhaiyq 19 escalated 逐个根因(19-agent workflow 实测)

| 桶 | 数量 | case | 性质 |
|---|---|---|---|
| **DSL 硬限制** | 13 | 533097,517112,532618,545172,545020,560932,545097,560861,588691,588842,600249,600318,561141 | 会话保持"两次 dig 同/不同成员"= 跨步值比较,xlsx 表达不了 |
| **env 不可达** | 3 | 516576,532700,532349 | 意图强制 IPv6 访问,测试床无 v6 段(3ffc:: 不在拓扑)|
| **draft 可修** | 3 | 516389,532436,588990 | 凭空编 MX/CNAME、dig 选错目标、负向测试咬错对象 |
| **grade 误杀可重跑** | **0** | — | 逐个核实,无评分抖动,全是真质量缺口 |

附带挖出 2 个**工程 bug**(非天花板):588691/600318 的 `<RUNTIME>` 未回填、588691 末尾与前序逻辑矛盾的 `not_found` —— draft/runtime_fill 链 bug。

grade 真实 CUT 理由(以 516389 为例,已抓原文):覆盖率仅 25%、持久化断言假阳性(A|B 二选一没测"不同")、MX/CNAME 凭空编值、AAAA 与 pool 绑定矛盾、首查过精确。**grade 判 CUT 全部正确,是系统按"不救场"设计在工作。**

## 8.6 天花板的本质 + 可能性证明

- **xlsx 只支持"精确值 oracle"**(输出里有没有字面 X);会话保持需要**"关系/蜕变 oracle"**(第二次输出 vs 第一次的关系)。这是经典**测试 Oracle 问题**,蜕变测试/性质测试是成熟解法。
- **可行性铁证**:本框架**人工 pytest `.py` 用例已自动化了会话保持**——`re.findall` 捕获 dig 返回 IP 存变量 + 跨步比较(`host_persistence/` 目录 314 处 assert/==/!=/findall)。**所以不是"做不到",是 xlsx DSL(框架 Python 能力的严格子集)砍掉了捕获+比较。**
- **真机填写的边界**:它救的是"运行时才知道的**值**"(观察一次→锁死),救不了"表达不了的**关系**"。填值 ≠ 比较两个值。

## 8.7 设计层结论(含自我修正)

- **修正一**:我曾把 zhaiyq 36% escalated 归为"端点 flaky 灌水、可重跑"——**错**。实测日志仅 4 次端点断连;0 个可重跑;escalation 是真 grade CUT。
- **修正二**:我曾断言"会话保持 xlsx 根本表达不了 = 13 个天花板"——**部分过悲观**。在**闭环观察作者 + 观察锁定**下,"窗口内同成员"可塌缩成"观察首次值 V→锁→两次都断言 found V",**不需新 DSL、不需写 Python**;只有"任意两值全通用比较"才是硬限。
- **根本病(整体设计)**:当前是**瀑布式盲生成**——`意图→一次性生成完整用例(配置+值+断言)→事后 grade 判→最后才上机`,所有决定在**还没碰设备**时拍定。三脑图所有 fail 都是盲猜的症状,闸/grounding 是在追着堵猜错(治标)。
- **构造性解法(方向,未实现)**:**闭环观察作者**——draft 在编写时就用只读探测(dig/show,共享设备允许)观察设备,按"需求预言的性质"从观察建断言,编写与验证并入一个循环;真机填写从"最后填值"前移到"编写期裁性质"。
- **红线澄清**:断言**关系**(性质来自需求,锚点值来自观察)≠ 禁止的 observe-then-assert **值**(把设备输出当对错标准、循环论证)。蜕变断言合法。

## 8.8 下一步候选(未决)

1. **整体设计**:闭环观察作者范式(把 draft 从盲生成器改为交互式测试工程师)。最根本,改动最大。
2. **收口可修项**:zhaiyq 3 个 draft 可修 + 2 个 runtime_fill bug + IPv6 可达门补全(Fix2 当前只 IPv4)。
3. **DSL 硬限 13 个**:框架级决策——扩 DSL 加"跨步取值+比较"原语,或把比较挪到 ist_verify 上机阶段,或诚实 escalate 标注遗留。
