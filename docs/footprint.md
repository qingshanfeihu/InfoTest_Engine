# Footprint 提取链路 — 职责边界契约

本文定义 footprint 知识树提取链路里**每个决策点归谁管**：哪些由 LLM 一次性输出，哪些由代码流程固定。所有代码改动必须对照本契约校验，避免"语义判断散落在代码里"或"结构操作交给 LLM 猜"的边界错位。

## 核心原则

1. **语义判断只属于 LLM**。"这条 fact 是什么 / 归哪个命令 / 和已有的是不是同一件事 / 值不值得记" —— 全部由 LLM 在见到原文 + 现有树上下文后决定。代码不得用关键词、正则、字段白名单、长度阈值替 LLM 做语义裁决。
2. **结构操作只属于代码**。"写哪个 JSON 字段 / 按什么键去重 / 落到哪个文件 / 怎么拼 prompt" —— 这些是确定性的机械操作，由代码固定，不交给 LLM。
3. **事实核查属于代码，但只核查、不猜测**。evidence 验证（quote 是否在原文出现）是代码该做的事实比对；但它不得夹带"路径长这样""片段至少多少字"这类对 LLM 输出形态的猜测。
4. **边界冲突时，宁可代码少管**。如果一个决策同时沾语义和结构，拆开：语义部分交回 LLM（通过 prompt 引导 + existing_facts 上下文），代码只保留纯结构部分。代码越界丢数据 = 静默的知识损失，比多存一条噪声更糟。

## 决策点归属表

| # | 决策点 | 归属 | 实现位置 | 说明 |
|---|--------|------|----------|------|
| D1 | fact 类型（cli_command/decision_rule/behavior/known_issue） | **LLM** | extractor prompt | 代码仅校验 ∈ 4 种枚举 |
| D2 | 命令路径 feature_path（语义归一） | **LLM** | extractor prompt | 含归一化（同特性收敛到真实命令路径） |
| D2b | feature_path 净化（剥 no/show/clear + 带记法参数 `<>`/`[]`/`{x\|y}`） | **代码（正则）** | extractor `_feature_path_from_syntax` | 对齐 CLI legend，确定性。cli_command 由 cli_syntax 派生 path |
| D3 | 去重键 fact_key | **LLM** | extractor prompt | 同义复述映射到同一 key |
| D4 | 参数表 parameters 各字段 | **LLM** | extractor prompt | 字段名/类型/约束全由 LLM 按原文给，代码不限定字段集 |
| D5 | condition/decision/content/issue_* 内容 | **LLM** | extractor prompt | LLM 概括，但 evidence_quote 须原文 |
| D6 | 层级 leaf/trunk/branch（按树高度叠加重算） | **代码** | reconcile | 俄罗斯方块：height 0=leaf/1=trunk/≥2=branch。非路径长度、非单 fact 属性 |
| D6b | CLI 命令 vs 架构概念区分 | **LLM** | extractor prompt | 架构名词解释（如 ustack 代号）不提取，只收 CLI 命令相关事实 |
| D7 | 写入哪个 JSON 字段（按 fact_kind 分发） | **代码** | merger `_DISPATCH` | 纯结构 |
| D8 | cli 命令按完整 cli_syntax 去重（no/show/clear/配置四态并存） | **代码** | merger `_append_cli_command` | 纯结构。键是 cli_syntax 字符串非 fact_key |
| D9 | 落盘扁平 `nodes/{feature_id}.json` | **代码** | router + merger | 纯结构。level 不进路径（reconcile 重算） |
| D9b | 补建中间节点 + 写 children 清单 | **代码** | reconcile | 显式树：每层祖先都落盘，children 自包含 |
| D10 | existing_facts 上下文拼装 | **代码** | dream `_load_existing_facts` + extractor `_format_existing_facts` | 纯结构，但必须回灌**全部** fact_kind |
| D11 | evidence 事实核查（quote 是否在原文） | **代码（仅核查）** | merger `_evidence_supports` | 只做存在性比对（覆盖率），不猜路径/不设字符阈值 |

## 功能树概念（D6 详解）

俄罗斯方块叠加：level 由节点**距叶子的高度**自底向上累加决定，不是路径 token 数。

```
height = 0                       终端 CLI 命令（无子节点）
height = max(子节点 height) + 1   否则
```

| height | level | 定义 | 例 |
|---|---|---|---|
| 0 | leaf | 终端 CLI 命令 | slb.policy.default、slb.all |
| 1 | trunk | 直接聚合命令的子模块 | slb.policy、slb.group、slb.mode |
| ≥2 | branch | 聚合子模块的大模块 | slb（含 leaf 子节点 slb.all） |

- 一个节点可同时是命令和父节点：`http.rewrite.body` 既有自己的 cli，又有子节点 `http.rewrite.body.limit` → trunk 但保留 cli 内容。
- 统一 schema（schema_version 3）：所有节点字段相同，level 只是位置标签，不 gate 内容。
- 中间节点（slb、slb.policy）由 reconcile 补建，可以是无 cli 的纯结构父节点。

## 明确的反模式（禁止）

- ❌ 代码用关键词正则判断 fact 属于哪个 slot（已废除的旧 `_determine_slot`）
- ❌ 代码用字段白名单裁剪 LLM 输出（已废除的 `_PARAM_FIELDS`）
- ❌ 代码用关键词映射把字符串转语义 bool（已废除的 required `"是"/"yes"→True`）
- ❌ 代码因路径长度=1 就丢弃 cli/rule/behavior（替 LLM 决定"这命令不值得记"）
- ❌ evidence 核查硬编码目录白名单 / 硬编码片段最小字符数
- ❌ level 按路径 token 数判定（应按树高度叠加重算，见 D6）
- ❌ trunk/branch 只允许 known_issue（统一 schema 后任何节点可承载任何内容）

## 修复记录（V1–V5 已闭环）

| # | 位置 | 越界类型 | 修法 |
|---|------|----------|------|
| V1 | feature_path 强制 `.lower()` | 疑似改写 LLM 输出 | 确认是结构不变量（lookup 强制小写），保留并注释 |
| V2 | router + LEVEL_KINDS 丢弃单 token 命令 | 替 LLM 做语义裁决 | **router 不再判级**，level 由 reconcile 全树重算；LEVEL_KINDS 放开 |
| V3 | `_resolve_evidence_path` 硬编码目录 | 核查夹带路径猜测 | 改 markdown 树下递归 basename 匹配 |
| V4 | `_evidence_supports` ≥12 字符硬阈值 | 核查夹带形态猜测 | 改覆盖率 0.6，语言无关、长度自适应 |
| V5 | existing_facts 回灌漏 known_issue/parameters | 结构操作不完整 | 补全四类 fact + 参数名 |

## C1–C3 结构修复（本轮）

| # | 改动 | 归属 | 解决 |
|---|------|------|------|
| C1 | feature_path 从 cli_syntax 正则派生（剥 no/show/clear + `<>`/`[]`/`{x\|y}`） | 代码（D2b） | show.running→running、`{on\|off}` 泄漏、参数泄漏 |
| C2 | cli 命令按完整 cli_syntax 去重，四态并存 | 代码（D8） | no/show/clear/配置 被 fact_key 误去重丢失 |
| C3 | 全树 reconcile：补建中间节点 + 树高重算 level + 写 children | 代码（D6/D9b） | slb 无 trunk、ha 偶然成 trunk、空心树 |
| — | extractor prompt：CLI vs 架构概念、规范语法优先 | LLM（D6b） | ustack 误判 leaf、示例行 on 当 token |
