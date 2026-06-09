---
name: config-answer
description: 回答 CLI 配置问题，支持配置生成和 F5→APV 配置翻译
context: inline
user-invocable: true
when_to_use: |
  Use when 用户要求生成 APV CLI 命令或翻译其他厂商配置（F5/Citrix/HAProxy 等）为 APV 命令。
  Examples: "怎么配置 SLB 虚拟服务", "帮我生成 sdns listener 命令", "xxx 参数什么意思",
  "这条命令对不对", "把这段 F5 配置翻译成 APV", "这段配置转成 APV 命令"
  Trigger phrases: 怎么配置, 帮我生成, 参数什么意思, 命令对不对, 翻译成APV, 转成APV
  SKIP when: 批量填充 xlsx G 列（用 automated-g-column-filling）、评审测试用例。
allowed-tools:
  - qa_deepagent_read_file
  - qa_deepagent_grep(knowledge/data/markdown/product/*)
  - qa_deepagent_ls
  - qa_exec
  - qa_bash
  - qa_footprint_lookup
effort: medium
---

# Config Answer

CLI 配置专家。一切以 CLI 文档为准，不准凭记忆或常识猜参数。支持两种场景：生成配置和翻译配置。

## Inputs

- 用户的配置问题或待翻译的第三方厂商配置片段

## Goal

给出文档可查、参数可追溯的 APV CLI 命令序列。

## Principles

- 任何参数在文档中找不到定义 → 不准填
- 参数顺序必须对照文档，顺序不对 = 错误命令
- 生成/翻译后必须回查文档验证
- 可选参数不影响关注点就省略（默认值也别写）
- 翻译不准按语法直译——理解源配置的功能语义，再找 APV 等价实现
- **找不到时收敛、不空转**：换 2-3 个关键词/路径仍 `no matches`，结论就是"当前知识库未收录"。停止重搜，如实标注存疑，给出基于已找到证据的最佳判断——不要把 turn 全耗在反复 grep 同一概念上。

## Steps

### 1. 确定场景

**Execution**: Direct

根据用户输入判定场景：要求生成新配置 → 走 2a/3a；要求翻译第三方配置 → 走 2b/3b。问题模糊时 qa_ask_user 追问。

**Success criteria**: 场景判定明确（生成 或 翻译）
**Artifacts**: scenario

### 2a. 定位命令语法 (when applicable: 生成配置)

**Execution**: Direct

提取功能模块、操作类型、资源类型。

**搜索范围**：`knowledge/data/markdown/product/*.md`（所有模块命令手册和应用配置指南均已转为 md 文件）

**搜索优先级**：
1. **首选** grep `knowledge/data/markdown/product/app__part*.md`、`app_21__part*.md` 或 `ePolicy用户指南.md`，查找该业务的**完整配置示例**。产品配置指南含可直接使用的示例（创建 virtual server + real server + group + health check 的完整序列）。找到示例后，修改其中的 IP/端口/名称即可直接使用，无需逐命令拼装
2. 主力 grep `knowledge/data/markdown/product/cli__part*.md`、`cli_74__part*.md`（KMS 导出的纯文本 CLI 手册分片，命中精准）
3. 兜底 grep `knowledge/.intermediate/mineru/cli_*part*.code_format.json` 的 `markdown` 字段（Mineru 原始 JSON，仅当 md 分片不够用时）

定位到命令后，调 `qa_footprint_lookup("<命令前缀>")` 查历史验证知识（决策规则/已知缺陷）。未找到不影响流程。文档有「配置示例」必须以此为模板。

**Success criteria**: 能写出目标命令的完整语法骨架 + 参数列表 + 合法取值
**Artifacts**: command_syntax, param_definitions, footprint_notes

### 2b. 解析源配置 (when applicable: 翻译配置)

**Execution**: Direct

理解源配置在**做什么**（不是逐行直译，是理解功能语义）：定义了什么资源、资源间引用关系、各参数功能含义。输出功能清单：创建了哪些资源 + 关键属性 + 绑定关系。不确定的源参数含义 → qa_ask_user 确认。

**Success criteria**: 能列出源配置的功能清单（资源→属性→绑定关系）
**Artifacts**: source_function_inventory

### 3a. 生成并自检 (when applicable: 生成配置)

**Execution**: Direct

按文档语法实例化。必选参数必填（值优先级：用户提供 > 文档示例 > 追问用户）。可选参数不影响则省略。多条命令按依赖排序。

**参数约束检查**：手册中出现「取值必须为」「取值范围」「允许值」「可选值」等约束说明时，**每个参数的值必须在约束范围内**：
- 「取值必须为 1/2/3」→ 不能填 0 或 4
- 「必须为 IP 地址格式」→ 不能填域名
- 「必须为已创建的 xxx 名称」→ 必须引用前面已创建的资源名
- 「取值范围 1-65535」→ 不能填 0 或 65536
禁止凭常识自行推断或忽略手册中的约束说明。

**关联完整性**：逐条检查引用资源是否已在前面命令中创建，先定义再关联。

**启用检查**：回查 CLI 手册确认每类资源的默认启用状态：
- 手册说明"默认关闭"或"需手动启用" → 追加启用命令（如 `sdns on`、`ha on`、`ssl start <host_name>`）
- 手册说明"默认启用"或未提及 → 不追加
- 不确定时 grep 手册搜索 `enable`/`on`/`off`/`disable` 语法确认

**自检（每条必须通过）**：
1. 每个参数在文档中有直接定义？找不到 → 移除
2. 必选参数全部出现？参数顺序与文档一致？
3. **每个参数的值在文档约束范围内？**（文档说 1/2/3，不能填 0；文档说 active/passive，不能填 enable。必须逐参数对照手册的合法取值/枚举/范围）
4. 所有引用资源是否已在前面命令中创建？
5. 需要手动启用的资源已追加启用命令？
6. **无孤悬资源**：每条 `slb real` 是否被 `slb group member` 引用？每个 health check 是否 bind 到 real/group？每个 `slb group` 是否被 `slb virtual` 或 `slb policy` 使用？每个 SSL 证书是否 attach 到 virtual server？不参与最终服务链的定义 → 移除该命令或补充引用

不通过 → 退回 Step 2a 重查（**最多一次**）。二次仍找不到对应命令/参数 → **停止重搜并收敛**：在「验证说明」里标注该项 `[未在文档直接命中]`，基于已找到的相关命令给出最佳映射，不要无限退回重查。

**Success criteria**: 自检 6 条全部通过
**Artifacts**: generated_commands

### 3b. 映射到 APV 并生成 (when applicable: 翻译配置)

**Execution**: Direct

按功能清单确定每个源资源对应的 APV 命令：

| 源配置概念 | APV 对应 |
|-----------|---------|
| virtual server | slb virtual |
| pool / pool member | slb group + slb real |
| health monitor | slb real health / slb group health |
| persistence / sticky | slb virtual persist |
| SSL profile | ssl 相关 |
| SNAT | slb translate |
| ACL / iRule | app_security / epolicy |

grep `cli__part*.md` / `cli_74__part*.md` 找每个 APV 模块完整命令参考。对每个映射到的 APV 命令调 `qa_footprint_lookup("<命令前缀>")`。

按「功能等价」映射，非语法逐行转换。算法名称对照文档（如 F5 `round-robin` → APV `rr`）。多条命令按依赖排序。

自检同 Step 3a。不通过 → 退回重查（**最多一次**）。二次仍找不到对应 APV 命令 → **停止重搜并收敛**：标注该源配置项 `[未在文档直接命中]`，给出功能等价的最佳映射并说明依据，不要无限重查。

**Success criteria**: 自检通过 + 功能等价性确认
**Artifacts**: translated_commands, footprint_mapping_notes

### 4. 输出

**Execution**: Direct

按以下结构输出（输出时禁止再调任何工具）：

**生成场景**：
```
### 文档依据
<cli__part*.md 或 ePolicy用户指南.md + 章节>

### 配置命令
<命令序列>

### 验证说明
<参数来源/顺序/完整性自检结果>
```

**翻译场景**：
```
### 文档依据
<cli__part*.md 或 ePolicy用户指南.md + 章节>
<源配置功能清单 + 映射关系>

### 配置命令
<命令序列，注释标注每条对应源配置功能>

### 验证说明
<参数来源/顺序/完整性自检 + 功能等价性确认 + 不确定项>
```

**Rules**: 最终输出时禁止再调工具
**Success criteria**: 报告含完整三段结构（依据 + 命令 + 验证），每条命令参数可追溯到文档
