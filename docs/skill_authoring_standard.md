# IST-Core Skill 编写模板与规范

本文档是 InfoTest_Engine 后续开发新 skill 的标准模板和编写规范。所有新 skill 必须遵循此规范，已有 skill 在重构时迁移到此规范。

## 一、Skill 目录结构

```
main/qa_agent/skills/<skill-name>/
├── SKILL.md             ← 主 skill 文件（必须）
├── reference/           ← 可选：reference 文件供 read_file 按需读取
│   └── *.md
└── scripts/             ← 可选：辅助脚本
    └── *.py
```

`<skill-name>` 必须是 kebab-case，全局唯一。

## 二、SKILL.md 结构

```markdown
---
<frontmatter>
---

# <Skill Title>

<一句话概述：这个 skill 干什么>

## Inputs（可选）
- 输入说明

## Goal（可选）
- 期望产出

## Steps

### 0. ...（可选：初始化步骤）

### 1. ...

### 2. ...

...
```

## 三、Frontmatter 字段

```yaml
---
name: skill-name                              # 必填，kebab-case，全局唯一
description: 一句话功能描述                   # 必填，含 TRIGGER 关键词
allowed-tools:                                # 必填，工具白名单（列表语法）
  - tool_name
  - tool_name(path/pattern/*)
when_to_use: |                                # 必填，触发条件 + SKIP 条件
  Use when ...
  Examples: "...", "..."
  Trigger phrases: ...
  SKIP when: ...
context: inline                               # 可选，inline（默认）或 fork
argument-hint: "<placeholder>"                # 可选，参数占位符
arguments:                                    # 可选，参数列表
  - arg_name
---
```

### 字段约束

| 字段 | 必填 | 规则 |
|---|---|---|
| `name` | YES | kebab-case，与目录名一致 |
| `description` | YES | 一句话；含触发关键词 |
| `allowed-tools` | YES | 列表语法；工具名后可加 path 模式限制（如 `qa_deepagent_grep(qa/*)`） |
| `when_to_use` | YES | 必须含 `Use when ...` + `Trigger phrases: ...` + `SKIP when: ...` |
| `context` | NO | `inline`（默认，注入主对话）或 `fork`（独立 subagent） |
| `argument-hint` / `arguments` | NO | 仅在 skill 接受用户参数时用 |

`when_to_use` 是 **CRITICAL** 字段——决定 LLM 何时自动触发这个 skill。`SKIP when` 子句尤其重要，否则通用 QA 会误调。

## 四、Steps 编写规范

每个 Step 必须有 `Success criteria`，按需追加可选标注：

```markdown
### N. <Step 名称>

<动作描述：具体、可执行>

**ONLY**: <path/pattern>          # 可选：限定工具访问的 path（桶隔离）
**Execution**: Direct | Task agent | Teammate | [human]
                                  # 可选：默认 Direct
**Success criteria**: <完成判据>   # 必填
**Artifacts**: <数据 / 制品>       # 可选：后续 step 依赖时填
**Human checkpoint**: <暂停时机>   # 可选：不可逆操作时填
**Rules**: <硬约束>                # 可选：业务专项约束
```

### Step 标注语义

- `Success criteria`：本步完成后什么状态——LLM 据此决定能否进入下一步
- `Execution`：
  - `Direct`（默认）：主 agent 直接执行
  - `Task agent`：spawn subagent 执行（需配合 `task(subagent_type=...)`）
  - `Teammate`：多 agent 协作（暂未支持）
  - `[human]`：要求用户操作（标在 Step 标题）
- `ONLY`：限定该 Step 工具访问的 path 范围（桶隔离专用）
- `Rules`：业务硬约束（如"NEVER use qa/ paths for product semantics"）

### Step 编号规则

- 顺序步骤：1 / 2 / 3 / ...
- 并发步骤：3a / 3b / 3c（同一阶段并行）
- 可选步骤：标注 `(optional)`
- 多 sheet / 多分支：尾部追加 `(when applicable)`

## 五、Skill 触发与执行流程

### 5.1 LLM 看到的 skill listing

每轮对话开始时，`PerTurnSkillReminderMiddleware` 把已注册 skill 列表注入为 `<system-reminder>`：

```
The following skills are available for use with the qa_invoke_skill tool:

- **<skill-name>**: <description>
  _When to use_: <when_to_use 完整内容含 SKIP>
- **<other-skill>**: ...
  _When to use_: ...

When a skill's description matches the user's current request, this is a 
BLOCKING REQUIREMENT: invoke the relevant qa_invoke_skill tool BEFORE 
generating any other response or calling any other tool about the task.
```

LLM 拿到用户请求 → 比对 skill description / when_to_use → 命中则调 `qa_invoke_skill(skill="...")`。

### 5.2 SKILL.md 内容注入

`qa_invoke_skill` 工具被调用时，返回 SKILL.md 完整内容（含 reference 文件路径列表）作为 ToolMessage。LLM 拿到后**严格按 Steps 顺序执行**。

### 5.3 Subagent 调用（评审 / 验证类 skill 专用）

某些 Step 需要独立 subagent 执行（`Execution: Task agent`），LLM 调 `task(subagent_type=...)` 触发。

注册 subagent 在 `main_agent.py:218-241`：

```python
subagents_list: list[dict[str, Any]] = [explore_subagent]
try:
    from main.qa_agent.agents.<your_subagent_module> import build_<subagent_name>
    subagents_list.append(build_<subagent_name>())
except Exception as exc:
    logger.warning("<subagent_name> 注册失败: %s", exc)
subagents_kwarg["subagents"] = subagents_list
```

### 5.4 Subagent 输出 → 用户

deepagents `task` 工具返回 ToolMessage（subagent 最后 AIMessage 的 text），主 agent 看到并决定如何 relay 给用户。

如果 subagent 输出本身**就是给用户的最终报告**（评审 verifier 等场景），在 subagent system prompt 顶部声明：

```
**Your output IS the user-facing report**——the caller (main agent) will
relay your report to the user; structure it as the final form the user
should see.
```

并在 `finalize` 节点（graph.py）加工程兜底，自动把该 subagent ToolMessage 内容当 `final_answer`（避免 LLM 总结环节丢失内容）。

## 六、命名规范

### Skill 名 / Subagent 名 / Tool 名

- Skill：`kebab-case`（如 `test-case-review`）
- Subagent：`kebab-case`（如 `review-verification`、`explore`）
- Tool：`snake_case`（如 `qa_deepagent_grep`、`qa_invoke_skill`）

### 工具白名单 path 模式

```yaml
allowed-tools:
  - qa_deepagent_grep                                # 通用，无路径限制
  - qa_deepagent_grep(knowledge/data/markdown/qa/*)  # 限定到 qa/ 桶
  - task(review-verification)                        # 限定调指定 subagent
```

工具白名单当前是**指引性**（LLM 应遵守，但工具层不强制）。需要严格执行时在工具实现层做校验。

## 七、状态字段命名（如需扩展 state）

如果 skill 需要在 `state.py` 中加跨 step 状态字段，遵循以下模式：

```python
class QaAgentState(TypedDict, total=False):
    # 通用 gate 字段（可被多种 skill 复用）
    gate_retry_count: int
    gate_status: Literal["pending", "passed", "failed"]
    gate_missing_reason: str

    # Skill 专项字段：用 skill 名前缀避免冲突
    review_xxx: ...      # test-case-review skill 专用
    <skill_name>_xxx: ...
```

## 八、文档与注释

### SKILL.md 文档风格

- **简洁**：cc-haha simplify Phase 3 风格——4-5 句一个 Step，关键约束一行
- **不暴露实现细节**：不引用具体源码文件名 / 行号
- **不重复主 agent 顶层约束**：通用反偷懒（Reading is Not Verification / Faithful Reporting）已在 system prompt，SKILL.md 写工作流即可

### 代码注释规范

- 不要在 docstring / 注释里引用第三方项目源码路径（如 `xxx.ts:N`）
- 用"业界 agent 设计"、"标准 agent 框架做法"等通用描述
- 业务专项注释正常写（如 review_gate 节点的功能 / 触发条件）

## 九、Skill 类型分类（已有的 skill 模式参考）

### 9.1 评审类 skill（如 test-case-review）

特征：主 agent 收集证据 → spawn verifier subagent → relay verifier 报告。

模板：
- `context: inline`
- 含 7-8 个 Steps（读证据 + 调 verifier + 输出报告）
- 配套的 verifier subagent 在 `agents/<x>_check_agent.py`
- review_gate 节点拦截"未调 verifier 就出报告"

### 9.2 检索 / 综述类 skill（暂无实例）

特征：主 agent 跨多文件检索 → 综合多源证据 → 给用户答案。

模板：
- `context: inline`
- 含 3-5 个 Steps（确定范围 → 检索 → 综合）
- 通常无需 subagent

### 9.3 操作 / 自动化类 skill（暂无实例）

特征：触发外部动作（运行 dev server、调 web API 等）。

模板：
- `context: fork`（独立上下文，避免污染主对话）
- 含 `Human checkpoint` 在不可逆操作前
- `allowed-tools` 严格限定到必要工具

## 十、新 skill 实施清单

新建 skill 时按此清单走：

1. ✅ 在 `main/qa_agent/skills/<skill-name>/` 创建目录
2. ✅ 写 SKILL.md：frontmatter（含 when_to_use SKIP 条件）+ Steps（每步 Success criteria）
3. ✅ 如需 subagent：在 `agents/` 加 `build_<x>_subagent()` + `main_agent.py:218` 注册
4. ✅ 如需 state 字段：在 `state.py` 加 skill 专项字段
5. ✅ 如需 gate / finalize 工程兜底：在 `nodes/` + `graph.py:finalize` 扩展
6. ✅ 测试：`tests/qa_agent/skills/test_<skill_name>_*.py`
7. ✅ 跑 e2e：`runner.py "<触发词>..." --stream`
8. ✅ 跑通用 QA："如何配置 X"（不应误触新 skill）

## 十一、参考实现

- 评审类完整实现：`main/qa_agent/skills/test-case-review/`
- 主 agent prompt：`main/qa_agent/agents/_prompt.py`
- Skill 注入中间件：`main/qa_agent/middleware/per_turn_skill_reminder.py`
- 硬闸节点：`main/qa_agent/nodes/review_gate.py`
- 工程兜底：`main/qa_agent/graph.py:finalize`
