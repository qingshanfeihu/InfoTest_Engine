# Changelog

## [1.0.4] - 2026-05-29

### 发布前体检修复（安全 + 资源 + 文档）

**Web Terminal 安全加固**（`infotest --server`）：
- 密码改 PBKDF2-SHA256 哈希存储（`password_hash` 字段），登录走 `hmac.compare_digest` 恒定时间比较；明文 `password` 字段仅向后兼容并打 warning
- 会话 token 改 `secrets.token_urlsafe`，加 8h 过期（`IST_WEB_SESSION_TTL_SEC`）+ 新增 `/api/logout` 撤销
- 登录失败按 IP 滑动窗口限流（`IST_WEB_LOGIN_MAX_FAILURES` / `_WINDOW_SEC`，默认 5 次 / 300s）
- RBAC：上传端点强制 `role ∈ IST_WEB_WRITE_ROLES`（默认仅 admin）；reviewer 只读
- 上传修复路径遍历（仅取 basename + 解析后二次校验落在 `_SANDBOX` 内）+ 体积上限（`IST_WEB_MAX_UPLOAD_MB`，默认 50）
- WebSocket 断开时显式 `terminate()`/`kill()` 子进程 + `await gather` 收尾任务，杜绝僵尸进程与 fd 泄漏
- 前端下载列表改 DOM API 构建（`textContent`），消除文件名 XSS；新增 `ws.onerror`
- `ssh_users.example.json` 去除可用明文凭据，改 `password_hash` 占位符 + 生成命令说明

**沙箱与资源**：
- `file_tools` 平台黑名单改大小写不敏感比较，修复 macOS/Windows 大小写变体绕过（`MAIN/`、`Memory/` 等）
- `cli.py` Web server 子进程 stdout 文件句柄改 try/finally 关闭，修复每次启动泄漏一个 fd
- TUI `JsonlFileSink` 在 `run()` finally 块显式 `close()`，修复 fd 泄漏
- `events.py` 默认 EventBus 单例加双检锁，修复多线程下实例覆盖 / 订阅丢失竞态

**文档**：
- `ARCHITECTURE.md` §8 全量管线命令标 legacy（模块已归档至 `backup/main_legacy/`，不可 `python -m` 调用）
- 移除 §12.4.2 已删除的 `PreAnalysisInjectionMiddleware` 描述，指向 §13 v2.0 Verification 架构
- 版本号对齐：`pyproject.toml` / CLI / TUI 统一 1.0.4

详见 `know_issue.md`「2026-05-29 发布前体检」。

## [1.0.2] - 2026-05-25

### 破坏性变更：环境变量重命名 `QA_AGENT_*` → `IST_*`

`environment` 文件结构按 7 区重排（API 凭证 / 模型路由 / 持久化 / 记忆 / Postgres / 缺陷库 / KMS）。详见 `environment.example`。

**迁移对照表**：

| 旧 | 新 |
|---|---|
| `QA_AGENT_LLM_PROVIDER` | `IST_LLM_PROVIDER` |
| `QA_AGENT_MODEL` | `IST_MODEL` |
| `QA_AGENT_REVIEW_MODEL` | `IST_REVIEW_MODEL` |
| `QA_AGENT_ALLOWED_MODELS` | `IST_ALLOWED_MODELS` |
| `QA_AGENT_OPUS_MODEL` / `_SONNET_MODEL` / `_HAIKU_MODEL` | `IST_OPUS_MODEL` / `_SONNET_MODEL` / `_HAIKU_MODEL` |
| `QA_AGENT_REVIEW_DEPTH` / `_INTERRUPT_ON` / `_DEBUG_PAYLOAD` | `IST_REVIEW_DEPTH` / `_INTERRUPT_ON` / `_DEBUG_PAYLOAD` |
| `QA_AGENT_SQLITE_PATH` | `IST_SQLITE_PATH` |
| `QA_AGENT_POSTGRES_CHECKPOINT_DSN` / `_SETUP` | `IST_POSTGRES_CHECKPOINT_DSN` / `_SETUP` |
| `QA_AGENT_MEMORY_*`（约 7 个） | `IST_MEMORY_*` |
| `QA_AGENT_DREAM_*`（约 4 个） | `IST_DREAM_*` |
| `QA_PLATFORM_POSTGRES_*`（6 个） | `IST_POSTGRES_*` |

**直接删除**（不再读取，请从 environment 中删掉）：

- `QA_AGENT_FALLBACK_MODEL` — 改用 `IST_LLM_PROVIDER` 直接路由
- `QA_AGENT_ACTIVE_MODEL`、`DASHSCOPE_DEFAULT_SYNTHESIS_MODEL`、`DASHSCOPE_DEFAULT_MAX_MODEL`、`DASHSCOPE_MODEL`
- `QDRANT_*`、`RAG_RERANK_*`、`DASHSCOPE_EMBEDDING_*`、`QA_PLATFORM_POSTGRES_VECTOR_DSN`
- `BAILIAN_ANTHROPIC_BASE_URL` / `ANTHROPIC_*` 兼容层

**保留不动**（厂商命名规范）：`DASHSCOPE_API_KEY` / `BAILIAN_API_KEY` / `DEEPSEEK_API_KEY`、`MINERU_TOKEN`、`LANGSMITH_*`、`PORTAL_*` / `BUGZILLA_*` / `ZENTAO_*` / `PLAYWRIGHT_*` / `DEFECT_*` / `KMS_*`。

### LLM Provider 抽象简化

`main/ist_core/agents/_llm.py` 重构：

- 删除 `_build_anthropic_compat`（百炼 Anthropic 兼容路径，已被 usage metadata bug 绕开）
- 删除 ChatTongyi fallback 与 `init_chat_model:` 分支（无调用方）
- 合并 `_build_openai_compat` + `_build_deepseek_compat` → `_build_chat_model(provider, model)`，按 `IST_LLM_PROVIDER` 决定 base_url / api_key / extra_body
- 删除 `build_synthesis_model` / `build_max_model`（无调用方）
- `build_agent_chat_model` 改为按 `IST_LLM_PROVIDER` + `IST_MODEL` 直接路由

### environment.example 7 区结构

按语义分区重写：① API 凭证（DashScope / DeepSeek / MinerU / LangSmith） / ② 模型路由（dashscope / deepseek 平等并列） / ③ 持久化 / ④ 记忆子系统 / ⑤ 产品测试 PostgreSQL / ⑥ 缺陷库抓取 / ⑦ KMS 管线。

### 修复 checkpointer sync/async 死锁

`runner.py` print 模式（`infotest -p`）配合 `IST_SQLITE_PATH` 时死锁（22 分钟仅 2.7s CPU，全部线程卡在 `_pthread_cond_wait`）。根因：`graph.invoke()` 同步路径调 `AsyncSqliteSaver`，违反 LangGraph `aio.py:164` 契约。

修复：`_make_checkpointer(mode="sync"|"async")` 区分双路径——
- `mode="sync"`（runner 非 stream）→ `SqliteSaver`（同步 `sqlite3` + `threading.Lock`）
- `mode="async"`（TUI / langgraph dev / `astream_events`）→ `AsyncSqliteSaver`（不变）
- 共享同一 SQLite 文件（WAL 模式），sync 写 + async 读完全兼容

### 新增 `/reset` 命令 + `infotest reset` 子命令

清理对话历史与 agent 临时存储：SQLite checkpoint、`memory/working/*.md`、`runtime/large_tool_results/`、`runtime/conversation_history/`、`memory/.dream/`（保留 `running.pid`）。`--all` 同时清长期记忆。CLI 默认交互确认，`--yes` 跳过。TUI `/reset` 主动输入即为确认。

### 生产化默认值

- `LANGSMITH_TRACING=false`（默认关闭，避免 prompt + 响应全文上传 SaaS）
- `environment.example` 删除 vendor key 占位值，鼓励用户显式填入

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
