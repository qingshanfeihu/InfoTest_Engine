# Changelog

## [1.0.5-beta.1] - 2026-07-06

> 1.0.5 系列首个 beta 发布。下方 [1.0.5] - 2026-06-09 为内部里程碑（未发布 GitHub release）；本条覆盖其后约 84 个提交（V4 收口 → V5 编排 → **V6 循环驱动编译引擎**）与本次发布收口。

### V6 编译引擎：LangGraph StateGraph 图 DSL（`main/ist_core/compile_engine/`）

- **编译闭环 = 一张图**：8 节点三类（[mech] 直调工具 `.func` / [llm] 孔经 `execute_fork_skill` / [user] 孔经官方 `interrupt`+`Command(resume)`），条件边为 state 计数纯函数；main agent 只调薄工具 `compile_engine_run(mindmap, version)` 一次。回退 `IST_COMPILE_ENGINE=0` 走 v5 main-orchestrated
- **断点续跑**：独立 SqliteSaver 分库（`runtime/compile_engine_checkpoints.db`，thread_id=`engine:<out_name>`），同参重调即从 checkpoint 继续；`run_marker` 幂等防重烧设备轮。对照轮中实战恢复 2 次
- **EngineLedger 迁移合法性表**：`passed→pending_compile` 在数据层非法（修复轮改坏 pass 卷的事故形态写不出来）；pass 即锁卷面 mtime，交付前复核；派发审计（重派集 ⊆ fail 集）
- **欠定先问后落**：worker 报欠定 → 引擎 interrupt 挂起问用户（机械模板问题文本，含 autoid 与顺序语义句）→ 决策落 `user_decision.json` 带回重派；`compile_user_decision` 无含 autoid 的问答台账记录即拒（越权拍板的机器门）
- **终验整卷路由**（beta.1 收口修复）：子集轮收敛于「部分 pass+部分 terminal」时曾直接 writeback——终验整卷从未发生，主交付卷停留旧版。现收敛后先回 merge 终验整卷再收口，无环
- **三域对照轮**：dongkl 21/34（重灾域）→ yzg 25/26（豁免后 100%）→ zhaiyq 51/53（新域首跑 71.7%→豁免后 98.1%）；编排事故全程 0

### 断言质量门体系（`structural_gate`，全部从框架 mirror 源码语义推导）

- **恒真/恒假断言族必崩门**：框架 `found/not_found` 为 `re.DOTALL` 无 MULTILINE、窗口=命令回显+数据+提示符——由此机械成立六门：行首/结尾锚必假、断言模式命中命令原文（恒真假 PASS，588691 三轮 fail 的真根因形态）、零 check_point 卷恒 FAIL、I 注入 format 结构坏崩卷、H 撞框架名字空间（ast 解析 mirror 闭集）、cmd_config 多行拍平粘连
- capture 引用门（未定义引用 NameError 崩卷）从成品卷 lint 前移进 emit 无条件必崩门
- 存量反扫 325 卷：当前交付 pass 单卷零命中；3 个历史归档 PASS 卷证实携恒真断言（当年 PASS 为假验证）

### 归因与修法生效性闭环

- last_run 按 autoid merge 时保留上一轮 `_attribution` 为 `_prev_attribution`（曾整条覆盖丢失）；attributor 对重编后再 fail 的 case 先核对「上轮修法上卷了吗/同签名复现了吗」，方向已证伪禁同向再开
- `.frozen.json` 重写保留 `overrides` 换法历史；frozen 语义澄清：≠终态，是「重编必须换法」标记（emit `override_frozen_reason` 门强制声明），终态=frozen∧轮次封顶
- 机械预判收缩为协议级事实（G 语法拒标记/文件级崩溃签名），其余交 LLM 读原文归因；known_defects token 组匹配短路

### 知识闭环与构造式接口

- **device_verified 第二权威源**：digest 落 `runtime/logs/verified_runs.jsonl` 防篡改台账（agent 沙箱黑名单内），footprint 写回经三重校验（台账存在∧pass∧命令∈卷面）——运行时命令不在手册导致的写回全 skip 就此修通
- **行为知识两段闸**：`submit_behavior_fact` 候选登记（observe_cmd∈卷面校验）→ 真 PASS 晋升挂 footprint 叶节点
- **blocks 构造式接口**：`compile_emit(blocks=…)` 组合子 + `ref` 字段（`footprint:`/`manual:`/`precedent:`/`config_derived`/`intent`）自动组装 provenance；emit 打回率从基线 48-52% 降至 12-20%
- 载荷通道一致性：批量入参原生数组+workspace 文件双通道，批量出参落盘全文+内联留尾

### Token 计量与 TUI

- **fork 计量重做**（beta.1 收口）：废弃「末态 messages 累计」（摘要撤史/transient 重试/看门狗超时全丢计，系统性偏小、与供应商官方统计对不上），改为 fork invoke 显式挂 `_ForkUsageTally` 回调——每次 LLM 调用即时取 API usage，与官方同源；fork cache 命中进成本公式（此前全按 miss 价高估）
- footer busy 行相位单箭头：上传相位只显 `↑ 本轮增量`，思考/生成相位只显 `↓ 本轮累计(+当次实时)`
- 多供应商适配（minimax/deepseek）；mimo 深度思考多轮 reasoning_content 非流式漏收修复；TUI 渲染修复（灰块阴影/think 内联/零响应消毒）

### 死循环护栏 + 上传/下载结构化信号 + 文档去外部来源引用

**死循环护栏（LoopGuardMiddleware）**：
- 新增 `main/ist_core/middleware/loop_guard.py`：`wrap_model_call` 注入收敛 reminder（不写回 state）。基于**最近 N 个工具调用的滑动窗口频次**检测（`IST_LOOP_WINDOW`，默认 8）——能抓住 A/B/A/B 交替空转，不止连续重复；模型改变行为后窗口自然复位。三类触发：窗口内同一 `(tool+args)` 指纹 ≥`IST_LOOP_DUP_THRESHOLD`（默认 3）、窗口内空结果 ≥`IST_LOOP_EMPTY_THRESHOLD`（默认 4）、本轮 tool_call 超 `IST_LOOP_SOFT_BUDGET`（默认 25）。`IST_LOOP_GUARD_ENABLED=0` 可关
- 挂载于主 agent（`main_agent.py`），inline skill 在主循环执行时自动受约束
- 主 agent prompt 新增 `Don't Spin` 反空转 section（`_prompt.py`），同时进 `build_verifier_inherited_sections` 让 fork subagent 继承
- `config-answer` SKILL.md：Step 3a/3b 的"退回重查"加上界（最多一次），二次找不到则标注 `[未在文档直接命中]` 收敛，不再无限重搜
- `_last_human_index` 前缀匹配带属性的 `<system-reminder`（修窗口起点错位）；`_is_empty_result` 加 200 字符护栏（长结果含"未找到"字样不误判为空）

**Web 上传/下载结构化带外信号（OSC）**：
- 根因：原方案把上传文件名当键盘字节塞进 PTY 文本流，下游靠正则猜——文件名含空格/中文/特殊字符时不可靠。Web Terminal 经 PTY 桥接 spawn TUI 子进程，输入/输出都走该通道
- **上传**：前端发结构化 `{type:"upload"}` ws 消息 → `web_server` 包成自定义 OSC `ESC]7001;<base64(filename)>BEL` → ink 解析器（`parse_keypress.py`）识别为 `UploadEvent` → `ist_app` 把 `inputs/<file>` 精确插入输入框。文件名走 base64，任何字符无损
- **下载**：agent 写文件到 `workspace/outputs/` 后，回合结束（`run_done`）diff 出新文件 → ink app `write_passthrough` 发 OSC `7002` → 前端 `registerOscHandler` 自动刷新下载面板 + 按钮红色角标。补 agent prompt 交付契约（要文件时写 outputs 才能下载）
- 保留 `input_preprocessor` 裸名正则（含 CJK + 点分文件名识别）作为本地 TUI 手敲文件名的兜底

**文档去外部来源引用**：
- 移除代码注释 / 文档中把外部参考实现当设计来源的字样，改为通用描述（保留 `CLAUDE.md` 文件名等功能性引用）

**测试**：新增 `test_loop_guard.py`（11）+ `test_input_preprocessor_bare_filename.py`（10）+ `test_osc_upload.py`（12）+ `test_download_notify.py`（4）

## [1.0.5] - 2026-06-09

### LLM 架构收口 + 记忆子系统修复 + 交互能力 + 仓库清理

**LLM 统一 OpenAI 兼容端点**（移除 provider 分支）：
- `_llm.py` / `runner.py` / `function_llm.py` / `kms_classifier.py` / `exec_tools.py` 统一走 `OPENAI_BASE_URL` + `OPENAI_API_KEY`，删除 `IST_LLM_PROVIDER` 的 dashscope/deepseek 分支与 `resolve_llm_provider`
- 换厂商（DeepSeek 原生口 / DashScope 兼容口 / 自建网关）只改 `OPENAI_BASE_URL` + key + `IST_MODEL`
- env 校验只认 `OPENAI_API_KEY`；示例模型小米 MiMo `mimo-v2.5-pro`（评审）/ `mimo-v2.5`（haiku tier）

**Skill 渐进披露**：
- `per_turn_skill_reminder` 加单条 description 截断（`IST_SKILL_DESC_CAP`，默认 200）+ 全局 listing 预算（`IST_SKILL_LISTING_BUDGET`，默认 1200）+ 溢出降级为 name-only；常驻 listing 从 ~3.5KB 降到 ~734 字符
- `when_to_use` 移出常驻 listing（触发后才从 SKILL.md body 读）；config-automation description 瘦身

**记忆子系统（dream）修复**：
- 进程内自调度 `maybe_trigger_dream_async`：TUI 启动后台守护线程跑一次（受五道闸约束），不再依赖系统 crontab；`IST_DREAM_INPROC=0` 可关
- `IST_HAIKU_MODEL` 坏模型 `mimo-v2-flash`（端点不存在）→ `mimo-v2.5`，footprint 提取恢复
- consolidate 适配 `response_format: json_object`：prompt 改输出 `{"decisions":[...]}` + `_coerce_decisions` 兼容多形态，AGENTS.md 蒸馏不再空转
- footprint extractor prompt 原则化（cli_syntax 还原完整调用签名，不照抄残缺标题行）

**qa_ask_user 交互式问答**：
- 工具注册 + `events`/`reducer`/`message_model` 链路 + `ask_user_view` 会话状态机
- `ask_user_panel` 固定面板（仿 PlanPanel，选项不随对话滚走）+ 选中行着色 + 答完完成提示 + 多题 `←→`/`Tab` 双向导航
- 抑制 qa_ask_user 标准工具行，不暴露内部工具名/参数

**TUI 渲染修复**：
- think 块展开消失：去掉 thinking 渲染的 `replace_range` 误删逻辑（thinking 间夹 tool_use 时误删后续行）
- 并行工具结果归位：按 `tool_use_id` 把 `⎿` 结果插到对应 `⏺` 行下方（toolUseID 分组）

**仓库清理**：
- 删除 `backup/`（1.6G 历史归档）、`logs/`、`ist_core.sqlite*` checkpoint、`__pycache__`/`.DS_Store`/空目录等运行时产物
- 文档全量更新：README / ARCHITECTURE / know_issue / todolist / WHATS_NEW 对齐统一 OpenAI 架构，移除 backup 悬空引用

（原 `WHATS_NEW.md` 已并入本文，1.0.5-beta.1 清理时移除。）

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
