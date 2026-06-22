# 编译 v2：footprint 文法补全 + 先例意图检索轴 + 三层生成 + 全链结构化

> **本 plan 自包含**：新会话无上下文也能照做。所有文件路径、行号、数据源、机制、红线、验证都在内。
> 工作目录：`/Users/jiangyongze/Library/CloudStorage/SynologyDrive-home/Project/InfoTest_Engine`
> Python：`.venv/bin/python`（项目根）。
> 论文最终稿：`workspace/outputs/paper_v6/paper_v6.md`（11章13表，§3.7ter/§4.7bis/§5.6 是本 plan 的理论依据）。

## 〇、最终验收目标（本轮交付，本 plan 的成功标准）

**运行方式**：`infotest -p "请将 /Users/jiangyongze/Library/CloudStorage/SynologyDrive-home/Project/InfoTest_Engine/workspace/inputs/automatic_case 下的3份txt脑图生成10.5版本的自动化excel文档"`
（`-p` = print/CI 模式，`main/ist_core/tui/cli.py:44`；CLI 不路由任务类型，agent 靠 tool description 自识别。）

**预期产出**：用**新 v2 skill** 完成 **3 份完整 excel** —— 输入 `workspace/inputs/automatic_case/{dongkl,yzg,zhaiyq}.txt`（每份是一个完整脑图功能树、含**几十个** autoid 用例，非 3 个用例；yzg.txt 即含 655154/676654/676626/681588 等本 plan 追踪过的 case），每份脑图产出一个含其全部 case 的 excel。

**验收方式**：**人工检查 excel 产物质量，不上真实自动化环境跑**。对应论文 §5.6 的「静态对照」口径——只看产物、不上机的指标：骨架正确率 K、断言可溯源率 P、确定性 token 占比 D、不可达 IP 编造率、grade-PASS 率、**零悬空断言**。

**成功标准**：3 份 excel 完整生成（无 case 丢失，对照脑图 autoid 数）；产物结构合法（命令在 allowlist、断言挂观测算子非悬空、IP 全可达）；draft 往返较 v1 实测下降（676654 基线 21 轮）。

## 一、目标与理论依据

把论文《意图实现映射：信息论分解》的 G⊔E⊔V 三层落到编译实现，**根治 draft 慢 + 不稳定**。

**论文 §3.7ter 的精确分工（v2 设计的核心，勿简化）**——G 段不是铁板一块，分两半：
- **结构约束（structural constraint）**：命令头∈文法 allowlist、绑定地址∈环境表、**断言对象∈某前序观测算子值域（非悬空）**。与意图无关、可由确定性机制机械执行（查表/类型检查/约束生成或生成后过滤）。**命题3.18：这类错误可被"约束强制"在构造上根除（correct-by-construction）。**
- **骨架选择（skeleton selection）**：选哪些命令、什么顺序、什么断言形态（测 zone 还是 host、用 found 还是 abs_found）。**H_G≈1.7–2.2 bit、top-1 仅 60%（§4.5）——低熵但非零熵，必须语义模型读意图+先例，不可代码化**（否则重蹈被删的纯代码管线，commit 3d63f775）。

**核心主张（推论3.19）**：确定性机制**执行结构约束**，语义模型**负责骨架选择与取值**。既非"全交自由生成"（会崩，见 655203 悬空案例），亦非"全代码化"（H_G≠0 必失败）。

落到三层：
- **G**：① 命令文法可查表 → 补进 footprint，draft 查表命中即得不啃手册（治慢）；② 命令合法性 + 断言非悬空 = 结构约束门，确定性强制（治崩）；③ 骨架选择仍 LLM（查 footprint/先例做候选，LLM 选）。
- **E(环境常量)**：查表（env_facts 已有）。**论文 §5.6 点明的实现缺口：当前 E 段未真正独立——可达 IP 搭载在 lookup_pattern 先例返回里，没有独立查表通道。v2 应让 draft 直接调 env_facts，E 段独立于先例。**
- **V(业务语义)**：必须 LLM → draft 填，独立 grade 把关（不自评）。**但论文 §5.6 警告：grade 这种 LLM 语义自评抓不到"结构约束违反"（命题3.18 那类，两臂 grade-PASS 率相同 0.423 即证），结构正确性须靠独立的确定性结构门，不能只靠 grade。**

现有 **v1 编译链零改动**（作实验基底），**v2 新建**，靠 `.skill_overrides.json` 切换。

## 二、实证根因（已验证，勿重复调研）

证据文件：`docs/draft_slowness_rootcause.md`、`docs/yzg_grade_vs_run_audit.md`。追踪脚本：`scripts/debug/trace_draft_roundtrips.py`（单跑一个 draft fork、dump 内部每轮往返，已存在可直接用）。

1. **单 case draft = 21 轮往返 / 567 秒**（case 676654，zone forward）。工具分布：grep 26 次、read_file 6、probe 4、lookup_pattern 3、footprint_lookup 1、emit 1。
2. **21 轮里 #6-18 共 13 轮**在反复 grep 手册找一条基础命令语法 `sdns listener <ip> [port]`，reasoning 一路 "I can't find the sdns listener command syntax"。
3. **该语法手册第7395行完整存在**（`10.5_cli__part2_p201-400.md`），LLM 因 `sdns listener` 在手册出现几十处噪声而捞不出 → 修正认知：**不是手册缺，是 footprint 没把现成文法提进来，LLM 被迫现 grep**。
4. draft 第7轮调了 `qa_footprint_lookup("sdns zone forward name")` 返回"无"——**footprint 未覆盖**（现仅15节点，sdns 仅 `sdns`+`sdns.listener`，且 sdns.listener 只有 `show sdns listener`、无配置语法）。
5. **lookup_pattern 检索不到的原因**：它只按 my_config 命令 token 的 Jaccard 相似度检索，**draft 必须先猜出要配什么命令**；676654 需求只一句"访问成功"，猜不出 config → 检索不到 → 退回啃手册。
6. **676654 对照**（V 段自评不可信实例）：draft 自判"可交付"，独立 grade 判 **CUT**（理由：断言未验转发实际生效）。→ **V 段让生成者自评会放水**。
7. grade 判分 `score_case`（`main/case_compiler/confidence_f.py:127`）用 `json.loads(m.group(0))` 正则抠 JSON，未用 response_format → 脆弱。

## 三、关键事实（代码级，已确认）

- **footprint 不新建，改造即可**。提取链：`extract_facts(content:str, llm_chat, existing_facts) → route_facts → merge_fact`（目录 `main/ist_core/memory/footprint/`：extractor.py / router.py / merger.py / schema.py / index.py）。
  - `extract_facts`（extractor.py:322 起）入口是**任意文本**，不绑定对话。
  - system prompt（extractor.py:20-）**已定输出契约** `{"facts":[{fact_kind, feature_path, fact_key, cli_syntax, parameters, evidence_file, evidence_quote, ...}]}`，已要求 `<param>`/`[param]`/`{a|b}` 记法、parameters 数组、剥 no/show/clear 前缀。
  - merge evidence 门 `_evidence_supports`（merger.py:106）：evidence_quote 必须在 evidence_file **整段命中或最长连续片段≥60%覆盖**，否则丢弃 → 保证不编造。
  - route 主键 = `".".join(feature_path)` → `nodes/<feature_id>.json`（router.py:31）。
  - 节点 schema v3（实例 `knowledge/footprints/nodes/sdns.listener.json`）：`{schema_version, feature_id, level, cli:{commands:[{fact_key, command, parameters?, evidence:{source_file,quoted_text}}]}, decision_rules, behaviors, known_issues, children, version_scope, footprint_meta:{verified_count, source_threads}}`。
- **json_object 已就位**：`main/function_llm.py:119` 硬编码 `response_format:{"type":"json_object"}`。**硬约束：顶层只能是对象**（dream.py:35 注释 + 记忆）→ 所有 schema 顶层 `{}` 包一层（如 `{"facts":[...]}` `{"steps":[...]}`，不能顶层数组）。
- **lookup_pattern**（`main/ist_core/tools/device/precedent_tools.py:68-145`）：扫 `knowledge/framework/mirror/**/*.xlsx`，只按 my_config Jaccard 排序；my_config 空则 error；先例无意图标签。
- **env_facts**（`main/ist_core/tools/_shared/env_facts.py`）：`get_env_facts().is_reachable/unreachable_ipv4s/summary_for_agent/service_ips`，数据 `knowledge/data/auto_env/network_topology.json`。
- **切换**：`main/ist_core/skills/.skill_overrides.json` 四态（on/name-only/user-invocable-only/off）+ `/skill` TUI 命令；v2 不同名即共存。skill 目录 `main/ist_core/skills/`，agent 目录 `main/ist_core/agents/`。

## 四、数据源（用户已提供，路径固定）

- **手册**（G 文法源）：`knowledge/data/markdown/product/10.5_cli__part*.md`。命令定义规整（见 §五-1）。
- **Z2 已验证 xlsx**：`knowledge/framework/backups/automation_smoke_test_xlsx_20260616_095939.zip`，380 文件/377 唯一 xlsx，内部结构 `smoke_test/...` 与 mirror 同构。比现 mirror（211）多 **166** 个。
- **csv 配对**（φ 语料 + 意图标签源）：`/Users/jiangyongze/Downloads/files/pairs_manifest_full.csv`，6600 行。列：`autoid,keying,intent_file,intent_depth,intent_path,intent_leaf_text,xlsx_file,xlsx_category,xlsx_steps,n_intent_candidates,n_xlsx_candidates`。`intent_path` 是带 `>` 分隔的脑图细化链（如 `161148 - [工行信创SDNS]支持IQUERY > 两台设备分别是rhost和vhost > SSL通道能够建立`），`xlsx_file` 是对应实现。Z2 能 100% 覆盖 csv 的 354 唯一 xlsx。
- **Z1 脑图**：`/Users/jiangyongze/Library/Containers/com.tencent.WeWorkMac/Data/Documents/Profiles/B99713DC8550682B8FDD60346BFF52BE/Caches/Files/2026-06/0cce90ec65d59e1b207840843ae930d5/AgileData.zip`，94 个意图 json（脑图源）。

## 五、实施步骤

### 阶段一：footprint 文法补全（先做，独立可验证提速）

新建 `scripts/maintenance/footprint_backfill.py`。流程「切片 → extract_facts → route → merge」，**复用现有提取链，零改 extractor/router/merger/schema**。

**1. 手册切片器（纯代码，确定性）**
手册命令定义规整（实证 `10.5_cli__part2_p201-400.md` 第7393-7420行）：
```
## 21.4. SDNS监听IP地址            ← 章节标题
sdns listener <ip_address> [port]   ← 命令签名行（行首=命令token串 + <param>/[param]）
该命令⽤于设置...                   ← 说明段（"该命令用于"开头）
<table>...ip_address...port...</table>  ← 参数表（每参数一行，含取值/默认值）
## 注意：write memory 不保存 port     ← 可选注意段（含 decision_rule）
no sdns listener <...>             ← no 变体（各自成一条命令）
show sdns listener / clear ...      ← show/clear 变体
```
切片规则：正则锚命令签名行（行首 `^[a-z][\w ]*\s+[<\[]` 或紧跟 `## N.N 标题` 后首行）；一片 = 签名行 + 说明段 + `<table>` 参数表 + 注意段，到下一签名行/`##` 止。no/show/clear 各自成片。遍历 `10.5_cli__part*.md` 全部。

**2. 每片喂 `extract_facts(content=片, llm_chat=function_llm包装)`**
- llm_chat 包装 `main/function_llm.py` 的 chat_completion（已 json_object）。
- 它吐目标 schema（示例，sdns listener 那条）：
```json
{"facts":[{
  "fact_kind":"cli_command",
  "feature_path":["sdns","listener"],
  "fact_key":"syntax_sdns_listener",
  "cli_syntax":"sdns listener <ip_address> [port]",
  "parameters":[{"name":"ip_address","required":true,"type":"IPv4/IPv6"},
                {"name":"sdns_listener_port","required":false,"default":53,"value_range":"1-65000"}],
  "evidence_file":"knowledge/data/markdown/product/10.5_cli__part2_p201-400.md",
  "evidence_quote":"sdns listener <ip\\_address> [port]"}]}
```
- extractor system prompt 加一句"也可读 CLI 手册段落"（现写"读 agent 工作记忆"，字段规则对手册同样适用，加一句适配、不重写）。
- 注意段 → 自动提 `decision_rule`（condition/decision），落同节点。
- 批量并发 + function_llm 缓存（手册全量 + Z2，量大）。

**3. merge evidence 门保证不编造**：evidence_file=手册路径、evidence_quote=片里原文签名行 → grep 命中通过；LLM 编的 grep 不到 → 自动丢（merger.py:106 已实现）。

**4. 灌入**：`facts → route_facts → merge_fact`，落 `nodes/<feature_id>.json`，version_scope=10.5，verified_count 累积。

**5. 源B Z2 xlsx（印证 + behavior，非文法源）**：xlsx 是实例值（`sdns listener 172.16.34.70`，无 `<param>` 记法）→ 不作 cli_syntax 来源；作用：印证命令真实存在 → 提 behavior fact，evidence=xlsx 路径。cli_syntax 文法只来自手册 `<>/[]` 记法行。

**6. 验证提速（用数据说话，不臆测倍数）**：
- 统计 footprint 节点数（15 → 覆盖 csv 命令域）；确认 `sdns.listener.json` 多出 `sdns listener <ip_address> [port]`。
- 重跑 `.venv/bin/python -m scripts.debug.trace_draft_roundtrips 203601753067676654`，对比往返（v1 基线 21 轮）。**论文 §4.7bis 诚实边界：步骤分布"确定7.7%+文法G34.1%+语义V58.2%"是 token/步骤来源刻画，≠ 成本下降比例。故提速幅度以实测为准，不预设"约5轮"。**

### 阶段一·补：先例库意图检索轴（治"分布外猜不出 config 就检索不到"）

**问题**：lookup_pattern 只按 my_config 命令 token Jaccard 检索，draft 须先猜命令；676654 类需求一句话的分布外 case 猜不出 → 检索不到 → 啃手册。

**做法（改 `main/ist_core/tools/device/precedent_tools.py` 的 qa_lookup_pattern——注意这是 v1/v2 共用工具，改动须向后兼容、不破坏 v1）**：
1. **建意图标签索引**（新数据，不改代码逻辑）：从 csv 读 `xlsx_file → intent_path` 映射，生成 `knowledge/framework/mirror_intent_index.json`（`{xlsx文件名: [intent_path,...]}`，一个 xlsx 可对多意图）。
2. **lookup_pattern 加可选入参 `intent: str = ""`**（默认空 = 行为与现在完全一致，v1 不受影响）：
   - 传了 intent：对每个先例，除 config Jaccard 外，再算 intent 与该 xlsx 的 intent_path 文本相似度（词重叠/可后续上向量）；
   - 融合排序（config 相似度 + 意图相似度，意图轴让"没想好配啥命令但知道要测啥"也能检索到）；
   - my_config 为空但 intent 非空时不再 error，改用纯意图轴检索。
3. draft（v2）调用时带上意图描述，分布外 case 也能凭意图找到骨架先例。

### 阶段一·配套：补先例库本体

把 Z2 缺失的 166 个 xlsx 解压进 `knowledge/framework/mirror/`（同构、零代码，lookup_pattern 自动扫到）。**先校验同名差集**（`comm` 比对 Z2 与 mirror 的 basename），同名不覆盖现有、只补缺失。footprint 给命令文法、先例给骨架结构、意图索引给检索轴——三者互补。

### 阶段二：v2 编译链（三层生成 + 全链结构化；v1 完全不动）

**2.1** 新建（不同名）：`main/ist_core/skills/ist_compile_v2/SKILL.md`（编排器）+ `ist_draft_v2`/`ist_grade_v2`/`ist_verify_v2/SKILL.md` + `main/ist_core/agents/ist-draft-v2.md` 等。复用全部现有工具（lookup_pattern/footprint_lookup/emit_xlsx/run_case/env_facts），不改工具。

**2.2 v2 draft：G→E→V 三层生成**
- **G-文法**：先 `qa_footprint_lookup` 拿参数文法（命中即得不啃手册）。
- **G-骨架**：`qa_lookup_pattern(my_config, intent=需求)` 拿骨架候选（带意图轴）；**骨架选择由 LLM 做**（H_G≠0，§4.5），footprint/先例只给候选。
- **E**：draft **直接调 env_facts** 拿可达 IP（**独立于先例通道**——治论文 §5.6 点的"E 段依附 lookup"缺口）；IP 不可达当场换（确定性比对，676654 已证 draft 能准确做）。
- **V**：LLM 填业务值，期望值溯源先例/手册。
- **结构化**：产 steps 走 json_object + schema（顶层 `{"steps":[...]}`）。
- **结构约束门（correct-by-construction，论文命题3.18）**：这是与 grade 独立的确定性强制，不是 LLM 自评——
  - 命令头必须∈手册 allowlist（footprint 已有的命令集）；
  - **断言对象必须挂在某前序观测算子（show/dig 等产出回显的步骤）的值域上**——断言对象的类型规则，与意图无关、机械可判，根治 655203 悬空崩溃；
  - 绑定 IP 必须∈env_facts 可达表。
  - 落点：在 `qa_emit_xlsx`（v2 走的 emit 路径）出口做生成后过滤，违反则拒绝 + 返回结构化原因让 draft 改。**注意：这是结构约束，不碰骨架选择（不替 LLM 决定测什么）。**

**2.3 v2 grade：瘦身只判 V 段语义**
- 只判"V 段断言是否真覆盖目标行为"（676654 那种"未验转发生效"要能判出）；G/E 配置存在性不参与覆盖度评分（治旧 grade 偏严）。
- 输出走 json_object（`{"rows":[{"score":..,"reason":..}],"overall":..,"decision":".."}`），不再正则抠。
- **论文 §5.6 教训：grade 抓不到"结构约束违反"（命题3.18），那类必须靠 2.2 的结构约束门，不是 grade。grade 只负责 V 段语义覆盖度——明确分工，别让 grade 兜结构。**

**2.4 v2 verify：四层归因**（论文 §5.4）
- fail 四分：G错（命令非法）/E错（不可达）/V错（语义值错）/环境瞬态（SSH断/超时/NXDOMAIN）；G/E/V 错回流重编译（带层级反馈），瞬态标注不回流。结构化输出。
- **本轮验收不上机**（§〇），verify 的上机归因留作后续；本轮 verify 退化为对产物的静态结构检查（K/P/IP可达/非悬空）。

**2.5 切换**：`.skill_overrides.json` 默认 v1 on / v2 off；实验时 `/skill off ist_compile_batch; /skill on ist_compile_v2`。

## 六、验证（对齐 §〇 验收：人工检查产物、不上机；口径=论文 §5.6 静态对照）

**最终验收（本轮目标）**：跑 `infotest -p "...3份txt脑图生成10.5版本的自动化excel..."`，v2 产 3 份 excel，人工检查：
- **完整性**：3 份 excel 各含对应脑图全部 autoid case（对照脑图 autoid 数，无丢失——治旧管线 41→1 数据丢失）。
- **结构约束（确定性可查，论文命题3.18）**：命令∈allowlist、**断言对象非悬空（挂观测算子）**、IP 全可达（0% 编造）。
- **论文 §5.6 静态指标作基线对比**（v1/Arm-L 已测值）：骨架正确率 K（基线0.954）、断言可溯源率 P（基线0.955）、确定性 token 占比 D（基线0.797）、不可达 IP 编造率（基线0%）、grade-PASS 率（基线0.423）。v2 应不劣于这些。

**过程验证**：
1. footprint：抽样核对 cli_syntax/parameters/evidence；节点覆盖 csv 命令域比例。
2. 提速：676654 draft 往返较 v1 基线 21 轮下降，fork_trace 显示 grep 降、footprint_lookup 命中（幅度实测，不预设）。
3. 意图轴：676654 类分布外 case，带 intent 能检索到 sdns 骨架先例（之前 config 空检索不到）。
4. E 段独立：draft 不依赖 lookup 命中也能从 env_facts 拿可达 IP（治论文 §5.6 缺口）。
5. 结构化：v2 各 LLM 调用走 json_object、顶层皆对象、无正则抠。
6. 结构门独立于 grade：人为构造悬空断言/越界 IP，结构门拦截（不靠 grade）。
7. 隔离：v1 代码零改动；切回 v1 行为不变；pytest 全绿（含 footprint/memory 测试）。

## 七、红线 / 不做
- **结构约束 vs 骨架选择（论文 §3.7ter，最重要的红线）**：确定性机制只**执行结构约束**（命令∈allowlist、断言挂观测算子、IP∈环境表——与意图无关的类型规则），**绝不替代骨架选择**（测什么、什么命令序列、什么断言形态——H_G≠0 的语义决策，永远 LLM）。混淆二者 = 重蹈被删的纯代码管线（22 个 .py，commit 3d63f775，41 用例丢成 1）。
- **不硬编码语义**：footprint 给文法、先例给骨架候选、意图索引给检索候选——**都是给 LLM 候选，不是做决定**。绝不建"这个意图→必用这些命令"的确定性规则。
- footprint 不新建（改造现有）；不走 dream 批量（dream 管对话增量，批量是一次性灌已验证语料）。
- v1 编译链/score_case/draft 一行不改；结构化/三层只在 v2 新文件。lookup_pattern 加 intent 入参须默认空、向后兼容。
- json_object 顶层必对象。
- 意图描述**不进 footprint**（footprint 主键是 CLI 命令，意图是用例语义，进了污染命令树——extractor prompt 第58行红线：非命令行为不提取）；意图进**先例索引**。
- **本轮不上机**（§〇）：verify 上机归因、跨次一致性 C_S/C_V、执行通过率留作后续；本轮只做静态产物检查。

## 八、风险
- 手册 MinerU 截断（记忆 mineru-cli-syntax-truncation，截断率 98.8%）→ 文法可能不全：Z2 真实用法双源交叉、缺的标注而非编造。
- 命令 token→feature_path 歧义（`sdns zone forward name` 路由层级）：复用 router 现有剥前缀逻辑。
- 提取量大：批量并发 + function_llm 缓存。
- lookup_pattern 是 v1/v2 共用：intent 入参默认空保证 v1 不变，改完跑 v1 编译回归确认。
- 意图相似度初版用词重叠即可，别一上来上向量库（YAGNI）。

## 九、执行顺序建议
1. 阶段一（footprint 补全）→ 验证 676654 提速。**这步独立、收益可量化、不碰 v2，先做。**
2. 阶段一·补（意图轴 + 补先例库本体）。
3. 阶段二（v2 编译链）——大工程，前两步验证有效后再做。
