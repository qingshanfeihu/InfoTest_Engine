# 旧版 Skill Prompt → 新版 SKILL.md 迁移指南

本文档说明如何将旧版 XML 风格的 skill prompt（`<Role>` / `<Rules>` / `<Agentic_Workflow>` / `<Output_Format>`）迁移到 `docs/skill_authoring_standard.md` 定义的结构化 SKILL.md 格式。

## 一、结构映射总览

| 旧版结构 | 新版对应位置 | 处理方式 |
|----------|-------------|----------|
| frontmatter `description` + `TRIGGER/SKIP` | `description` + `when_to_use` | 直接迁移，SKIP 条件必须保留 |
| frontmatter `allowed-tools`（空格分隔） | `allowed-tools`（列表语法） | 加 path 模式限制；移除已被架构替代的工具 |
| `<Role>` 核心定位 | `# Title` 一句话 + `## Principles` | 浓缩为 2-3 行 bullet |
| `<Rules>` 行为约束 | `## Principles` 或各 Step `**Rules**` | 通用 → Principles；步骤专属 → Step Rules |
| `<Agentic_Workflow>` 各 Step 段落 | `## Steps` 各步骤 4-5 句 | 大幅精简，维度信息下沉到 Artifacts |
| 各 Step "关键产出" | `**Artifacts**` 字段 | 逗号分隔的信息项列表 |
| 各 Step 完成条件（隐含） | `**Success criteria**` 字段 | "能回答什么问题"句式 |
| `<Output_Format>` 报告模板 | 分情况（见第六节） | 多 agent → verifier prompt；单 agent → 末尾 Step |
| `qa_sanity_check` / 自检 | `task(review-verification)` | 架构替代，不迁移 |
| checkbox 进度 `- [ ] Step N` | Step 0 `write_todos` | 改为用户友好中文 todo |

## 二、Frontmatter 迁移

### 旧版

```yaml
---
name: test-case-review
description: 评审测试用例...TRIGGER when...SKIP when...
allowed-tools: tool_a tool_b tool_c
---
```

### 新版

```yaml
---
name: test-case-review
description: 一句话功能描述（不含 TRIGGER/SKIP，那些放 when_to_use）
user-invocable: true
effort: high
allowed-tools:
  - qa_deepagent_read_file
  - qa_deepagent_grep(knowledge/data/markdown/product/*)
  - qa_deepagent_grep(knowledge/data/markdown/qa/*)
  - qa_deepagent_ls
  - web_bug_search
  - qa_footprint_lookup
  - task(review-verification)
when_to_use: |
  Use when ...
  Examples: "...", "..."
  Trigger phrases: ...
  SKIP when: ...
context: inline
---
```

### 迁移要点

1. `description` 只保留功能描述，触发/跳过条件移到 `when_to_use`
2. `allowed-tools` 改列表语法，加 path 模式（桶隔离）
3. 被架构替代的工具删掉（如 `qa_sanity_check` → `task(review-verification)`）
4. 通用工具不需要列（如 `qa_ask_user`，主 agent 本身就能用）
5. 新增 `effort`、`context`、`user-invocable` 等元数据字段

## 三、`<Role>` 段迁移

### 旧版

```markdown
<Role>
# 测试用例评审 Skill

你正在评审一份测试用例。核心原则：评审质量来自"读懂产品 + 读懂测试"，
不是"套规则字典"，定义的评审测试用例标准为 P0-P7 级别，区别如下：
P0：...
P1：...
</Role>
```

### 新版拆分

```markdown
# Test Case Review

对测试用例做独立、有证据的评审。

## Principles

- 评审质量来自"读懂产品 + 读懂测试"，不是"套规则字典"
- （从 <Rules> 迁移的行为约束）

## P 级别定义

- P0: ...
- P1: ...
```

### 迁移要点

1. `<Role>` 里的"你是谁 / 你在做什么"→ `# Title` 下一句话
2. 核心原则 → `## Principles`（2-3 行 bullet，不写段落）
3. 评级标准 → 独立的 `## XXX 定义` 段
4. 不要在 Principles 里重复 system prompt 已有的通用约束

## 四、`<Rules>` 段迁移

### 旧版

```markdown
<Rules>
## 两条提醒
1. **关注研发修改内容和具体产品实现**——了解当前产品缺陷或者需求时，逐项理解...
2. **参考以往测试用例和测试策略**——评审前了解以往的测试覆盖和测试方向...
</Rules>
```

### 新版：按作用域拆分到两个位置

| 规则类型 | 放哪里 | 格式 |
|----------|--------|------|
| 全局行为约束（整个流程都要遵守） | `## Principles` | bullet 列表 |
| 步骤专属约束（只在某个 Step 生效） | 对应 Step 的 `**Rules**` 字段 | 一行一条 |

### 示例

```markdown
## Principles
- 关注研发修改内容——不要把修复细节当背景一扫而过

### 6. 读当前用例全文
**Rules**: 未知命令/模块必须 grep product/ 确认语义；禁止凭名字推断
```

## 五、`<Agentic_Workflow>` 各 Step 迁移

### 旧版（每步一大段 + 关键产出）

```markdown
- [ ] **Step 3：读 CLI 手册**
  - 明确修改的 CLI 命令的具体配置方法和命令参数，grep
    `knowledge/data/markdown/product/cli__part*.md` 补全参数语义，
    找到 CLI 命令中有相关修改或新增 CLI 参数的其他引用，确认相关的
    CLI 命令或兼容关系，参数之间的依赖关系（如互斥、包含等），以及
    参数的合法值范围和默认值
  - 关键产出：命令完整参数表、使用方法、配置示例、合法值范围、默认值，
    参数之间的依赖关系（如互斥、包含等）
```

### 新版（4-5 句 + 结构化标注）

```markdown
### 3. 读 CLI 手册

grep `cli__part*.md`，找到相关命令的完整参数表，确认参数间依赖关系
（互斥/包含）、合法值范围和默认值。同时查找该命令在其他位置的引用，
确认兼容关系。

**ONLY**: knowledge/data/markdown/product/cli__part*.md
**Success criteria**: 能列出命令完整参数表 + 使用方法 + 配置示例 + 参数间依赖关系
**Artifacts**: param_table, legal_values, defaults, param_dependencies, usage_examples
```

### 迁移规则

| 旧版元素 | 新版字段 | 写法 |
|----------|---------|------|
| 描述段落 | Step 正文 | 精简到 2-4 句，保留"做什么 + 怎么做" |
| "关键产出" | `**Artifacts**` | 逗号分隔的 snake_case 名词列表 |
| 隐含的完成条件 | `**Success criteria**` | "能回答/能列出/能对标..."句式 |
| "grep XXX 找 YYY" | Step 正文 | 保留具体路径和搜索方向 |
| 括号里的举例 | Step 正文或 Artifacts | 简短保留，作为搜索方向提示 |
| 独立的禁止项 | `**Rules**` | 一行一条 |
| 限定搜索范围 | `**ONLY**` | path/pattern |

### 精简原则

- 旧版一个 Step 动辄 5-8 行描述 → 新版正文 2-4 句，剩余信息下沉到标注字段
- 删除"确认 XXX 的 YYY，包括 ZZZ 和 WWW"展开式——改为 Artifacts 列表
- 维度举例（括号内容）如果对搜索方向有引导价值则保留在正文里

## 六、`<Output_Format>` 迁移

这是旧版和新版差异最大的部分，需要按架构分情况处理。

### 情况 A：多 agent 架构（有 verifier subagent）

旧版的输出格式模板**不放在主 skill 里**，而是拆分到多个位置：

| 内容 | 放哪里 |
|------|--------|
| 报告结构（证据/评级/缺口/建议） | verifier 的 fork skill prompt |
| 证据列表要求 | 主 skill Step N 的 brief 模板 `evidence_collected` |
| 证据缺口声明 | brief 模板 `evidence_gaps` 字段 |
| 建议分级 | brief 模板 `draft_findings` 分层结构 |

主 skill 最后一步（收尾）只写"评审完成。"——verifier 的 tool_result 就是用户看到的报告。

### 情况 B：单 agent 架构（无 subagent）

输出格式放在最后一个 Step 里：

```markdown
### N. 输出报告

按以下结构输出（输出时禁止再调任何工具）：

### 一、证据摘要
### 二、评级与理由
### 三、证据缺口
### 四、建议修改

**Rules**: 最终输出时禁止再调工具
**Success criteria**: 报告含完整四段结构
```

## 七、工具变更映射

旧版 skill 里的某些工具在新架构下已被替代：

| 旧工具 | 新架构替代 | 说明 |
|--------|-----------|------|
| `qa_sanity_check` | `task(review-verification)` | 字面自检 → 独立 subagent 交叉验证 |
| `qa_ask_user`（skill 专属列出） | 不列入 allowed-tools | 主 agent 本身就有此能力 |
| 手动 checkbox 进度 | `write_todos` (Step 0) | Plan 面板自动展示 |
| 直接输出报告 | verifier tool_result 透传 | 主 agent 静音收尾 |

## 八、迁移检查清单

拿到一个旧版 skill prompt，按此顺序操作：

1. **拆 frontmatter**：description 单独、TRIGGER/SKIP 移 when_to_use、tools 列表化 + path 模式
2. **识别核心原则**：从 `<Role>` + `<Rules>` 里提取 2-3 条 → `## Principles`
3. **拆评级/定义**：如有 → 独立 `## XXX 定义` 段
4. **逐步迁移 Workflow**：每步精简到 4-5 句 + 填 `ONLY` / `Success criteria` / `Artifacts` / `Rules`
5. **处理 Output Format**：多 agent → 灌入 brief 模板；单 agent → 放最后 Step
6. **删除已替代内容**：checkbox、sanity_check、大段描述
7. **补 Step 0**：如果是复杂流程（>5 步），加 `write_todos` 初始化
8. **检查 allowed-tools**：只保留该 skill 专属需要的，通用能力不列

## 九、常见踩坑

| 坑 | 表现 | 正确做法 |
|----|------|---------|
| Success criteria 写成工具产出物名 | `bug_summary + cli_command` | 改为"能回答什么问题"句式 |
| Principles 重复 system prompt | "必须有证据支撑" | 只写 skill 专属的领域约束 |
| 旧版维度举例全删了 | agent 搜索无方向，漏查 | 保留在正文里作为搜索方向提示 |
| Output Format 照搬到主 skill | verifier 和主 agent 都想控制输出 | 多 agent 时只放 verifier prompt |
| allowed-tools 带了通用工具 | 白名单膨胀，失去约束意义 | 只列 skill 专属工具 |
| Step 正文写了 7-8 句 | 超出"4-5 句"规范 | 多余信息下沉到 Artifacts/Rules |

## 十、参考

- 编写规范：`docs/skill_authoring_standard.md`
- 评审类完整实现：`main/ist_core/skills/test-case-review/SKILL.md`
- 外部设计规范：cc-haha Skills 系统使用指南 + 实现原理
