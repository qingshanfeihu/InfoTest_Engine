---
name: config-answer
description: 任何涉及 APV CLI 命令的问题（查看/生成/解释/翻译/验证），必须查 CLI 手册回答
context: inline
user-invocable: true
when_to_use: |
  Use when the user's request requires APV CLI commands as part of the answer —
  configuration generation, command explanation, parameter lookup, or config translation.
  Trigger keywords (match any): 怎么配置, 配置cli, 配置命令, 配置方式, 命令怎么写, 生成命令, 参数什么意思, 翻译成APV, 命令对不对, CLI命令, 给出配置, 会话保持配置, 健康检查配置
  SKIP when: 批量填充 xlsx G 列（用 automated-g-column-filling）、评审测试用例、设备验证（用 device-verify）。
allowed-tools:
  - fs_read
  - fs_grep(knowledge/data/markdown/product/*)
  - fs_ls
  - run_python
  - run_shell
  - kb_footprint
effort: medium
---

# Config Answer

CLI 配置专家。一切以 CLI 文档为准，不准凭记忆或常识猜参数。支持两种场景：生成配置和翻译配置。

## 硬约束（不可违反，高于一切）

**不准凭记忆写任何命令。** 你的训练数据里没有 APV CLI 手册——你"记得"的命令格式（如 `slb policy qos`）大概率不存在或语法错误。**每条命令的每个参数都必须是本轮 grep 亲手从手册查到的**，不能是"我以前见过"、"常识是这样的"、"类似的命令大概是这个格式"。

违反本条的典型表现（就是本次发生的问题）：
- 不调 grep 就直接写出了配置命令序列
- 命令中的关键词（如 `qos`）在手册里根本没出现过，是凭空编的
- 自检说"通过"但实际一条都没查——因为根本没 grep 过，拿什么对照？

**如果你打算写的某条命令，你还一次都没 grep 过它的语法 → 先停下手，grep 完再写。不准先写完再去 grep"验证"——验证的意思是"我查过了，确认无误"，不是"我写完了，补一个 grep 假装查过"。**

## Principles

- **写前必查**：每条命令在写之前，必须先用 `fs_grep` 从手册找到其完整语法。先 grep 后写，不准先写后补 grep
- 任何参数在文档中找不到定义 → 不准填
- 参数顺序必须对照文档，顺序不对 = 错误命令
- 可选参数不影响关注点就省略（默认值也别写）
- 翻译不准按语法直译——理解源配置的功能语义，再找 APV 等价实现
- **找不到时收敛、不空转**：换 2-3 个关键词/路径仍 `no matches`，结论就是"当前知识库未收录"。停止重搜，如实标注存疑，给出基于已找到证据的最佳判断——不要把 turn 全耗在反复 grep 同一概念上
- **收敛 ≠ 不查**：收敛规则适用于"认真搜了 2-3 次确实没有"的情况，**不适用于"还没搜就认定找不到于是自己编"**。前者是诚实的边界，后者是跳过流程

## Steps

### 1. 确定场景

**Execution**: Direct

根据用户输入判定场景：要求生成新配置 → 走 2a/3a；要求翻译第三方配置 → 走 2b/3b。问题模糊时 ask_user 追问。

**Success criteria**: 场景判定明确（生成 或 翻译）
**Artifacts**: scenario

### 2a. 定位命令语法 (when applicable: 生成配置)

**Execution**: Direct（**必须先调 fs_grep，不准跳过直接写命令**）

提取功能模块、操作类型、资源类型。

**搜索范围**：`knowledge/data/markdown/product/*.md`（命令手册 `cli_*_Chapter*.md` + `cli_*_Appendix*.md`、应用配置指南 `app_*_Chapter*.md` + `app_*_appendix*.md`、以及 `ePolicy用户指南.md`；`*` 匹配任意版本如 10.5/11.0）

**搜索优先级**：
1. **首选** `fs_grep` `knowledge/data/markdown/product/app_*_Chapter*.md` + `ePolicy用户指南.md`，查找该业务的**完整配置示例**。产品配置指南含可直接使用的示例（创建 virtual server + real server + group + health check 的完整序列）。找到示例后，修改其中的 IP/端口/名称即可直接使用，无需逐命令拼装
2. 主力 `fs_grep` `knowledge/data/markdown/product/cli_*_Chapter*.md` + `cli_*_Appendix*.md`（KMS 导出的纯文本 CLI 手册，命中精准）

**门禁：本步骤至少执行一次 fs_grep，不准跳过。** 你打算输出的每条命令，都必须在本步骤中亲手 grep 到它的语法。如果 grep 结果里没有某条命令的语法 → 这条命令不能出现在最终输出中（除非诚实标注 `[未在文档直接命中]` 并给出最佳推测）。

定位到命令后，调 `kb_footprint("<命令前缀>")` 查历史验证知识（决策规则/已知缺陷）。未找到不影响流程。文档有「配置示例」必须以此为模板。

**Success criteria**: 每条目标命令都能在 grep 结果中找到语法定义（或诚实标注未找到）
**Artifacts**: command_syntax（含手册出处：文件名+行号）, param_definitions, footprint_notes

### 2b. 解析源配置 (when applicable: 翻译配置)

**Execution**: Direct

理解源配置在**做什么**（不是逐行直译，是理解功能语义）：定义了什么资源、资源间引用关系、各参数功能含义。输出功能清单：创建了哪些资源 + 关键属性 + 绑定关系。不确定的源参数含义 → ask_user 确认。

**Success criteria**: 能列出源配置的功能清单（资源→属性→绑定关系）
**Artifacts**: source_function_inventory

### 3a. 生成并自检 (when applicable: 生成配置)

**Execution**: Direct

按文档语法实例化。必选参数必填（值优先级：用户提供 > 文档示例 > 追问用户）。可选参数不影响则省略。多条命令按依赖排序。

**⚠️ 完整性要求：配置示例必须是可直接执行的完整服务栈，不能只给关键命令。** 用户问"如何配置 xxx 算法"时，需要的是完整的资源创建链：

| 模块 | 完整服务栈                                                 | 最少命令数 |
|------|-------------------------------------------------------|-----------|
| SLB | real server → group(method) → virtual server → policy | ≥4 |
| SDNS (GSLB) | sdns on → host → service → pool → listener            | ≥4 |
| SDNS (DNS)  | sdns zone name → sdns record → sdns zone record → sdns fulldns on → sdns on | ≥5 |
| HA | ha unit → ha group → ha fip                           | ≥3 |

只给 `slb group method` 不给 real server/virtual server/policy = 不完整。只给 `sdns record` 不给 `sdns zone name` + `sdns zone record` = 不完整。必须从底层资源开始逐层创建。

**参数约束检查**：手册中出现「取值必须为」「取值范围」「允许值」「可选值」等约束说明时，**每个参数的值必须在约束范围内**：
- 「取值必须为 1/2/3」→ 不能填 0 或 4
- 「必须为 IP 地址格式」→ 不能填域名
- 「必须为域名格式」→ 不能填 IP（如 NS 记录的第三参数必须是域名 `ns1.com.`，不能是 IP `172.16.35.232`）
- 「必须为已创建的 xxx 名称」→ 必须引用前面已创建的资源名
- 「取值范围 1-65535」→ 不能填 0 或 65536
- **约束中的类型名是类别，不是具体值**：手册说"TCP类型的后台服务" → 实际协议类型取决于场景（SSL 场景用 `tcps`，普通场景用 `tcp`）。必须结合用户的业务场景确定具体值，不能字面取约束中的类别名

禁止凭常识自行推断或忽略手册中的约束说明。

**关联完整性**：逐条检查引用资源是否已在前面命令中创建，先定义再关联。特别注意**隐式依赖**：
- **SDNS 资源记录引用的 zone** → 必须先通过 `sdns zone name` 创建 zone，再用 `sdns zone record` 将 record 关联到 zone（只创建 record 不创建 zone + 关联 = record 不生效）
- NS 记录引用的域名（如 `ns1.com.`）→ 必须先创建该域名的 A 记录
- CNAME 记录引用的目标域名 → 必须先创建该域名的 A 记录
- pool 引用的健康检查 → 必须先创建健康检查命令
- policy 引用的 group/virtual server → 必须先创建

**启用检查**：回查 CLI 手册确认每类资源的默认启用状态：
- 手册说明"默认关闭"或"需手动启用" → 追加启用命令（如 `sdns on`、`sdns fulldns on`、`ha on`、`ssl start <host_name>`）
- 手册说明"默认启用"或未提及 → 不追加
- 不确定时 grep 手册搜索 `enable`/`on`/`off`/`disable` 语法确认
- **SDNS DNS 特别注意**：`sdns on`（默认禁用）和 `sdns fulldns on`（默认启用但需显式开启以支持全类型记录解析）两者都需检查

**自检（每条必须通过，不准跳）**：

逐条过，不准笼统说"全部通过"。每条检查必须引用具体的 grep 结果或手册出处。

1. 每个参数在文档中有直接定义？找不到 → 移除，**并标注 `[未在文档直接命中]`**。不准把找不到的参数悄悄留在命令里。
2. 必选参数全部出现？参数顺序与文档一致？——对照 grep 结果中的命令语法行逐参数核对。
3. 每个参数的值在文档约束范围内？（文档说 1/2/3，不能填 0；文档说 active/passive，不能填 enable）
4. 所有引用资源是否已在前面命令中创建？
5. 需要手动启用的资源已追加启用命令？
6. 服务栈完整？（SLB：real server + group + virtual server + policy 都有？SDNS GSLB：on + host + service + pool + listener 都有？SDNS DNS：zone name + record + zone record + fulldns on + sdns on 都有？）
7. 无孤悬资源：每条 `slb real` 是否被 `slb group member` 引用？不参与最终服务链的定义 → 移除或补充引用。

**自检防造假**：第 1-3 条检查的是"命令是否与手册一致"，而这要求你**真的 grep 过手册**。如果你回答"全部通过"但本轮一次 fs_grep 都没调过 → 自检是假的，你只是凭记忆确认了自己编的命令。自检的"通过"意味着"我对照了 grep 结果，每条都对得上"，不是"我觉得应该对"。

不通过 → 退回 Step 2a 重查（**最多一次**）。二次仍找不到对应命令/参数 → **停止重搜并收敛**：在「验证说明」里标注该项 `[未在文档直接命中]`，基于已找到的相关命令给出最佳映射，不要无限退回重查。

**Success criteria**: 自检 7 条全部通过，且本轮至少有一次 fs_grep 调用作为证据
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

grep `knowledge/data/markdown/product/cli_*_Chapter*.md` + `cli_*_Appendix*.md` 找每个 APV 模块完整命令参考。对每个映射到的 APV 命令调 `kb_footprint("<命令前缀>")`。

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
<cli_*_Chapter*.md 或 app_*_Chapter*.md 或 ePolicy用户指南.md + 章节>
<每条命令的出处：文件名 + 行号>

### 配置命令
<命令序列，每条命令后注释其手册出处>

### 验证说明
<7 条自检逐条结果 + 本轮 fs_grep 调用摘要（搜了什么、命中什么文件）>
```

**翻译场景**：
```
### 文档依据
<cli_*_Chapter*.md 或 app_*_Chapter*.md 或 ePolicy用户指南.md + 章节>
<每条命令的出处 + 源配置功能清单 + 映射关系>

### 配置命令
<命令序列，注释标注每条对应源配置功能 + 手册出处>

### 验证说明
<7 条自检逐条结果 + 功能等价性确认 + 不确定项 + 本轮 fs_grep 调用摘要>
```

**Rules**: 最终输出时禁止再调工具。如果输出了任何命令但「文档依据」段没有对应的手册文件名+行号 → 视为违反硬约束（凭记忆写的）。
**Success criteria**: 报告含完整三段结构，每条命令参数可追溯到具体的手册文件名+行号
