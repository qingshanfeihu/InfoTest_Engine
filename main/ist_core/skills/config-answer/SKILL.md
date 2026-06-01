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

## Steps

### 1. 确定场景

**Execution**: Direct

根据用户输入判定场景：要求生成新配置 → 走 2a/3a；要求翻译第三方配置 → 走 2b/3b。问题模糊时 qa_ask_user 追问。

**Success criteria**: 场景判定明确（生成 或 翻译）
**Artifacts**: scenario

### 2a. 定位命令语法 (when applicable: 生成配置)

**Execution**: Direct

提取功能模块、操作类型、资源类型。搜索策略：主力 grep `knowledge/data/markdown/product/cli_*_commands.md`（纯文本，命中精准）；补充 `cli_*part*.code_format.json`（Mineru 导出 JSON，CLI 在 `markdown` 字段，用 qa_exec + Python 提取对应章节）。

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

**关联完整性**：逐条检查引用资源是否已在前面命令中创建，先定义再关联。

**自检（每条必须通过）**：
1. 每个参数在文档中有直接定义？找不到 → 移除
2. 必选参数全部出现？参数顺序与文档一致？
3. 枚举值/数值范围符合文档约束？

不通过 → 退回 Step 2a 重查。

**Success criteria**: 自检 3 条全部通过
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

grep `cli_*_commands.md` 找每个 APV 模块完整命令参考。对每个映射到的 APV 命令调 `qa_footprint_lookup("<命令前缀>")`。

按「功能等价」映射，非语法逐行转换。算法名称对照文档（如 F5 `round-robin` → APV `rr`）。多条命令按依赖排序。

自检同 Step 3a。不通过 → 退回重查。

**Success criteria**: 自检通过 + 功能等价性确认
**Artifacts**: translated_commands, footprint_mapping_notes

### 4. 输出

**Execution**: Direct

按以下结构输出（输出时禁止再调任何工具）：

**生成场景**：
```
### 文档依据
<cli_*_commands.md + 章节，如有 code_format.json 注明>

### 配置命令
<命令序列>

### 验证说明
<参数来源/顺序/完整性自检结果>
```

**翻译场景**：
```
### 文档依据
<cli_*_commands.md + 章节，如有 code_format.json 注明>
<源配置功能清单 + 映射关系>

### 配置命令
<命令序列，注释标注每条对应源配置功能>

### 验证说明
<参数来源/顺序/完整性自检 + 功能等价性确认 + 不确定项>
```

**Rules**: 最终输出时禁止再调工具
**Success criteria**: 报告含完整三段结构（依据 + 命令 + 验证），每条命令参数可追溯到文档
