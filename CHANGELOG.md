# Changelog

## [1.0.1] - 2026-05-22

### 新增

- **Explore Sub-Agent**：基于 deepagents SubAgentMiddleware 的只读检索代理，主 agent 可通过 `task(subagent_type="explore")` 隔离复杂搜索的上下文
- **Memory 通用回调架构**：MemoryInjectionMiddleware + MemoryWriteMiddleware，支持评审 adapter 回调（query_extractor / key_resolvers / finalizer）
- **SKILL.md 行为指导风格**：6 步阅读链 + P0-P7 评级标准 + 四段式输出格式，模型自主决定工具调度
- **TUI SubAgentTaskMessage**：`task` 工具专属渲染（subagent_type + description 摘要 + spinner）
- **PerTurnSkillReminderMiddleware**：每轮 before_model 注入 skill listing，兼容非 Anthropic 模型
- **build_explore_model()**：独立的 Explore 模型工厂（flash + thinking=disabled）
- **qa_sanity_check 工具**：测试用例字面自检（重复段落、错字、格式、空字段统计）

### 改进

- Explore 工具集去重：只传 `web_bug_search` + `qa_sanity_check`，FilesystemMiddleware 自动提供 ls/glob/grep/read_file
- SKILL.md 不再强制 6 次 task() 调用模板——模型按 deepagents 设计原则自主编排
- TodoList 防跳步机制验证通过（write_todos 5 次调用，6 步全执行）
- 评审建议质量提升：15 条建议，0 误报，4 条独家发现（IPv6、异常 cookie、RFC 长度、WAF 联动）

### 修复

- 修复 SubAgent 工具重复导致过度调用（133 次 → 22 次）
- 修复 CompiledSubAgent 方式与 deepagents 内部 SubAgentMiddleware 冲突

### 架构决策

- **Tasks 防跳步**：TodoListMiddleware 保证每步执行
- **Skill 行为指导**：告诉模型做什么和关注什么
- **Explore 上下文隔离**：复杂多步搜索不污染主 context
- **直接工具调用**：简单单次查询不走 explore

## [0.1.0] - 2026-05-20

- 初始版本：IST-Core 测试评审平台
