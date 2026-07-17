# IST-Core Agent 框架设计说明

> ⚠️ **历史存档（2026-07-17 归档,team4 docs 整编）**：2026-06 框架差异笔记,「待补齐项」多已落地(流式/skill 系统)。事实存档不删,现状勿引本文。

本文档记录 IST-Core 当前 agent 框架与业界标准 agent 框架（流式状态机 + skill 系统）的关键差异，明确**架构层差异**（合理保留）和**待补齐项**（后续优化）。

## 一、架构总体差异

| 维度 | 业界标准框架 | IST-Core 当前 | 类型 |
|---|---|---|---|
| 核心循环 | AsyncGenerator 状态机（`while + state = next`） | LangGraph StateGraph + deepagents ReAct | **架构差异** |
| 工具执行时机 | 流式中即时执行（StreamingToolExecutor） | LangChain 标准（等模型完整响应） | 架构差异 |
| 实时输出 | TUI 流式渲染所有 ToolMessage | TUI 流式 + runner CLI 兜底 final_answer | 部分差异 |
| 故障恢复 | 6 种内置策略（compact / token / model fallback） | 依赖 LangGraph 框架基础特性 | 待补齐 |
| Prompt 缓存 | global / ephemeral / section 三级 | 单一 build_system_prompt | 不需要 |
| 工具延迟加载 | shouldDefer + ToolSearch 动态加载 | 全部一次性注册 | 不需要 |

**架构差异不是 bug**——是 InfoTest_Engine 走 LangGraph + deepagents 二次封装路径的合理选择。整体改造代价过大且收益有限。

## 二、System Prompt

| 项 | 业界标准 | IST-Core | 状态 |
|---|---|---|---|
| 静态/动态分层（缓存边界） | ✅ SYSTEM_PROMPT_DYNAMIC_BOUNDARY | ❌ 单一 build_system_prompt | 不一致（DeepSeek 端点无 cache 优势，意义低） |
| CLAUDE.md 多层加载（5 层优先级） | ✅ system → user → project → .claude → 历史 | ⚠️ 仅项目 CLAUDE.md | 简化 |
| Section memoize | ✅ 缓存 / 缓存破坏两种 Section | ❌ 每轮 build 重算 | 简化 |

### 反偷懒约束 prompt sections（已对齐）

主 agent system prompt 的所有反偷懒 section 都已落实：
- `Verification Contract`（you cannot self-assign verdict / level）
- `Writing the prompt for task calls`（Brief like a smart colleague + Never delegate understanding + After the subagent returns）
- `When NOT to use task`（防过度委托）
- `Skills First`（命中 skill 必须先 invoke）
- `Task Tracking`（多步任务 write_todos 必用）
- `Reading is Not Verification`（grep / read_file 才算验证）
- `Faithful Reporting`（不许压制错误）
- `Communication Style`（简洁直接）
- `Tool usage` 含 `Parallel tool calls` + 多命令链式

## 三、工具系统

| 项 | 业界标准 | IST-Core | 状态 |
|---|---|---|---|
| 工具完整生命周期接口 | ✅ validateInput / checkPermissions / call / renderToolUseMessage | ⚠️ langchain @tool + attach_tool_metadata | 简化（核心能力一致） |
| 能力声明（isReadOnly / isConcurrencySafe） | ✅ 每工具自报 | ⚠️ 部分（attach_tool_metadata） | 部分一致 |
| 工具编排（并行只读 + 串行写入） | ✅ toolOrchestration | ⚠️ deepagents 框架决定 | 框架行为 |
| 中间件管道（Pre/Post tool hooks） | ✅ | ⚠️ deepagents middleware（简化） | 简化 |
| 工具延迟加载（ToolSearch） | ✅ | ❌ 全部加载 | 不需要（工具数量少） |

### 沙箱

- 多根沙箱（`knowledge/data/` + `workspace/` + `IST_SESSION_DIR` + `IST_USER_DIR`）—— 已对齐多根设计
- CWD 解析层抽到 `_sandbox.py` —— 模块化对齐
- 路径校验三闸（traversal / 平台黑名单 / 多根白名单）—— 等价于业界标准的 `pathInAllowedWorkingPath()`
- **未做**：CWD AsyncLocalStorage 并发隔离（IST-Core 单 agent 单会话用不上）
- **未做**：OS 级 sandbox-runtime（业界用 bwrap，Python 不可移植）

## 四、Skill 系统（核心一致）

| 项 | 业界标准 | IST-Core | 状态 |
|---|---|---|---|
| Frontmatter 字段 | name / description / when_to_use / allowed-tools / context / paths / hooks | name / description / when_to_use / allowed-tools / context | **核心一致**（缺 paths/hooks） |
| Skill 加载来源 | bundled / managed / user / project / plugin / mcp（6 种） | 单一 `main/ist_core/skills/` | 简化 |
| Skill listing 注入 | `<system-reminder>` 每轮注入 | ✅ PerTurnSkillReminderMiddleware 同款 | **一致** |
| listing 字段（name + description + when_to_use） | ✅ | ✅ | **一致** |
| Inline / Fork 执行 | 显式两种 context | 只走 inline | 简化 |
| getPromptForCommand 闭包（动态参数替换） | ✅ | ⚠️ 静态 SKILL.md 全文返回 | 简化（功能等价） |
| 条件激活（paths glob） | ✅ 文件操作触发 | ❌ | 待补 |
| 生命周期 hooks | ✅ PreToolUse / PostToolUse / Stop | ❌ | 待补 |

### 未实现的 skill 高级特性（按需补）

- **paths 条件激活**：用户拖文件进来自动触发 skill（业界 `paths: "src/**/*.ts"` glob 匹配）
- **fork context**：自包含任务用独立 subagent 执行，主对话不污染
- **hooks**：skill 调用时注册 `PreToolUse` / `Stop` 等生命周期钩子
- **getPromptForCommand 动态展开**：支持 `${CLAUDE_SKILL_DIR}` / `$arg_name` 等变量替换
- **shell 内联执行**：SKILL.md 中 ``` `!command` ``` 自动执行（MCP 安全限制）

## 五、Subagent 系统

| 项 | 业界标准 | IST-Core | 状态 |
|---|---|---|---|
| Subagent 注册 | bundled agent + SKILL.md fork agent | deepagents subagents 列表 | **一致** |
| Subagent 调用接口 | AgentTool（task tool） | deepagents 的 task 工具 | **一致** |
| Fresh 零上下文 | forkSubagent 字节级继承 parent system prompt | deepagents `subagent_state['messages'] = [HumanMessage(description)]` | **一致** |
| Subagent prompt 含 "caller will relay" | ✅ generalPurposeAgent | ✅ explore / verifier 都已加 | **一致** |
| 主 agent relay subagent 输出 | TUI 流式渲染 ToolMessage | TUI sink 截 500 字 + finalize 工程兜底 | 部分一致 |

### Verifier subagent（评审专项）

完整实现 `review-verification` subagent：
- "try to break it" + "verification avoidance" 失败模式
- 强制 OUTPUT FORMAT（Verification command + Output observed + Result）
- VERDICT / LEVEL 行
- "Your output IS the user-facing review report" 声明（caller will relay）

## 六、上下文管理

| 项 | 业界标准 | IST-Core | 状态 |
|---|---|---|---|
| Memory 系统 | ✅ CLAUDE.md / 用户记忆 | ✅ MemoryInjectionMiddleware（footprint / working / long_term） | 一致 |
| 上下文压缩 4 级（snip / micro / collapse / auto compact） | ✅ | ⚠️ deepagents summarization_middleware（max_tokens=28000） | 简化 |
| System Reminder | ✅ skill listing / memory reminder 等 | ✅ PerTurnSkillReminderMiddleware + MemoryInjectionMiddleware | **一致** |

## 七、权限与安全

| 项 | 业界标准 | IST-Core | 状态 |
|---|---|---|---|
| 权限规则 4 层（rules / modes / hooks / classifier） | ✅ | ❌ 仅沙箱根校验 | 简化 |
| 工具白名单（按 skill 限制工具池） | ✅ allowed-tools 严格执行 | ⚠️ allowed-tools 是指引性（不强制） | 待补（评审场景低风险） |
| 命令黑名单（rm / sudo / ssh / curl 等） | ✅ | ✅ run_shell 黑名单 | 一致 |
| 写文件路径白名单（只能落 outputs/） | ✅ | ✅ `_resolve_writable_path` | 一致 |

## 八、TUI / 输出

| 项 | 业界标准 | IST-Core | 状态 |
|---|---|---|---|
| 流式 TUI 渲染 | React + ink | Textual TUI + EventBus | 一致风格 |
| 实时显示 ToolMessage 内容 | ✅ 完整 | ⚠️ TUI sink 截到 500 字 | **待优化**：长 ToolMessage（如 verifier 9000 字报告）只显示前 500 字 |
| runner CLI 单点输出 | print final_answer | print final_answer + 评审场景工程兜底 | 一致 |

### finalize 工程兜底

`graph.py:finalize` 节点检测：
- `gate_status == "passed"` 且 messages 中存在 `task(review-verification)` ToolMessage 含 VERDICT/LEVEL
- → 强制把 verifier ToolMessage 完整内容当 `final_answer`（绕过主 agent 总结环节）

业界标准不需要这层（流式 TUI 让用户实时看到 ToolMessage），InfoTest_Engine 的 runner 模式必须工程层保证 final_answer 完整。

## 九、待补齐项（按优先级）

### P1（影响用户体验）

- [ ] **TUI sink ToolMessage 内容截断**：当前 500 字截太狠，长 verifier 报告显示不全。改为可展开 / 翻页 / 写文件链接
- [ ] **CLI sink content 过滤**：当前 `_print_event` 把 payload.content 过滤掉，runner --stream 模式看不到 tool 实际内容

### P2（高级特性）

- [ ] **Skill paths 条件激活**：用户上传 xlsx 自动激活评审 skill
- [ ] **Skill fork context**：自包含 skill 走独立 subagent
- [ ] **Skill hooks**：生命周期钩子注册

### P3（工程优化）

- [ ] **Prompt 缓存边界**：DeepSeek 不支持 prompt cache，待 Anthropic 兼容端点接入再做
- [ ] **工具延迟加载（ToolSearch）**：当前工具数 < 20，意义不大
- [ ] **CWD AsyncLocalStorage 并发隔离**：单会话场景用不上

### P4（架构层）

- [ ] **AsyncGenerator 状态机**：替换 LangGraph 整体架构改造，ROI 不高，长期不做

## 十、合理保留的差异

以下差异**故意不补齐**，理由如下：

1. **AsyncGenerator vs LangGraph**：架构层差异，整体重写代价过大
2. **流式工具执行**：deepagents/LangChain 标准是同步 invoke，框架决定
3. **6 种故障恢复策略**：依赖业界状态机设计，LangGraph 简化版够用
4. **Prompt 缓存边界**：DeepSeek 端点无 cache 优势
5. **OS 级沙箱**：bwrap 不可移植 Python；进程隔离 + cwd + env 已足够
6. **Permission rules 4 层**：评审场景低风险，沙箱保护是底线

## 十一、参考实现

| 模块 | 文件 | 业界标准对应 |
|---|---|---|
| 主 agent prompt 装配 | `main/ist_core/agents/_prompt.py` | constants/prompts.ts |
| 工具沙箱模块 | `main/ist_core/tools/deepagent/_sandbox.py` | utils/permissions/filesystem.ts |
| Skill 注入 middleware | `main/ist_core/middleware/per_turn_skill_reminder.py` | utils/attachments.ts skill_listing |
| Skill 工具入口 | `main/ist_core/tools/skills/__init__.py` | tools/SkillTool/SkillTool.ts |
| Verifier subagent | `main/ist_core/agents/semantic_check_agent.py` | tools/AgentTool/built-in/verificationAgent.ts |
| 硬闸节点 | `main/ist_core/nodes/review_gate.py` | utils/hooks/hookHelpers.ts |
| 主 graph 装配 | `main/ist_core/graph.py` | query.ts |
| Subagent 执行（deepagents 依赖） | `.venv/.../deepagents/middleware/subagents.py` | tools/AgentTool/forkSubagent.ts |
