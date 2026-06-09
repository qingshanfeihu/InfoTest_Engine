# What's New

## 2026-06-09（v1.0.5：架构收口 + 记忆修复 + 交互 + 清理）

### 统一 OpenAI 兼容端点
移除 `IST_LLM_PROVIDER` 的 dashscope/deepseek 分支，`_llm.py` / `runner.py` / `function_llm.py` / `kms_classifier.py` / `exec_tools.py` 统一走 `OPENAI_BASE_URL` + `OPENAI_API_KEY`。换厂商只改 base_url + key + `IST_MODEL`。示例模型小米 MiMo `mimo-v2.5-pro`。

### Skill 渐进披露
`per_turn_skill_reminder` 加单条 description 截断 + 全局 listing 预算 + 溢出降级；常驻 listing ~3.5KB → ~734 字符。`when_to_use` 移出常驻 listing。

### 记忆子系统（dream）修复
- 进程内自调度 `maybe_trigger_dream_async`，不再依赖 crontab（`IST_DREAM_INPROC=0` 可关）。
- `IST_HAIKU_MODEL` 坏模型 `mimo-v2-flash` → `mimo-v2.5`，footprint 提取恢复（实测落地 22 节点）。
- consolidate 适配 `json_object`（返回 `{"decisions":[...]}` + `_coerce_decisions`），AGENTS.md 蒸馏不再空转。
- footprint extractor prompt 原则化（cli_syntax 还原完整调用签名）。

### qa_ask_user 交互式问答（对齐 cc-haha）
工具注册 + events/reducer 链路 + `ask_user_panel` 固定面板（选项不随对话滚走）+ 选中着色 + 完成提示 + 多题 `←→`/`Tab` 双向导航；抑制标准工具行不暴露内部名。

### TUI 渲染修复
- think 块展开消失：去掉 thinking 渲染的 `replace_range` 误删逻辑。
- 并行工具结果归位：按 `tool_use_id` 把结果插到对应 `⏺` 行下方。

### 仓库清理
删除 `backup/`（1.6G）、`logs/`、`ist_core.sqlite*`、`__pycache__`/`.DS_Store`/空目录；文档全量更新对齐统一 OpenAI 架构，移除 backup 悬空引用。

## 2026-05-27（清理）

- **移除 `agent-chat-ui`**：LangChain Next.js 可选前端已从仓库删除；交互统一为 `infotest`（Textual）与 `infotest --server`（Web Terminal :8080）。`ARCHITECTURE.md` §12 标为历史；`CLAUDE.md` 启动说明已更新。

## 2026-05-27（cc-haha Skill 分层）

### 评审 inline/fork 单源与客户友好 TUI

- **Verifier 单源**：`skills/review-verification/SKILL.md` 为完整 prompt 真源；`semantic_check_agent.py` 瘦身为 shim；运行时仅 `load_fork_skills()` 注册
- **cc-haha 交付契约**：fork 产出含 VERDICT/LEVEL 的完整报告；main fork 返回后静音（仅「评审完成」），禁止再调工具；`finalize` 不再把 main 补刀 prefix 到 verifier 前
- **test-case-review**：footprint 前移至交叉验证前；Step 8 静音；多 sheet 分支前置；todo 禁内部实现词
- **客户友好**：`display_labels.py`（交叉验证 / 评审报告）；`PerTurnSkillReminder` 仅 listing `inline` + `user-invocable: true`；TUI 评审报告默认全文展开

## 2026-05-27

### Skill 系统对齐业界标准

完成测试评审 skill 与业界 agent 框架（Claude Code 风格）的全面对齐改造，覆盖通用 agent 行为、tools 使用、skill 注入三个层面。详见 `todolist.md` 第 9 节。

**核心修订**：

- **通用反偷懒约束**：主 agent system prompt 加 7 个通用 sections（Verification Contract / Writing the prompt for task calls / When NOT to use task / Task Tracking / Reading is Not Verification / Faithful Reporting / Communication Style）+ 工具并发指引
- **Subagent 设计对齐**：explore subagent 加 "caller will relay this to the user" 声明；review-verification verifier subagent 完整实现（"try to break it" + 强制输出格式 + VERDICT/LEVEL）
- **Skill listing 增强**：`PerTurnSkillReminderMiddleware` 注入 listing 时同时输出 `when_to_use`（含 SKIP 条件），通用 QA 不再误触 skill
- **Review 工作流硬闸**：`review_gate` 节点强制检测 verifier 调用 + VERDICT 行；`finalize` 节点工程兜底把 verifier 报告自动当 final_answer
- **桶隔离**：SKILL.md 每 Step 限 ONLY path（product/ vs qa/，禁止从测试用例反推产品定义）
- **沙箱接口统一**：抽 `_sandbox.py` 模块，多根 CWD 解析；qa_bash / qa_exec 路径展开为绝对路径；新增 cp 命令支持（落 workspace/outputs/）
- **删 qa_ask_user 工具**：实测在评审场景被错误调用导致 derail，参数格式 LLM 经常写错
- **memory 源头治理**：`review_finalizer` 不再把评审结论写入 memory（避免下次评审复用历史）；新增 archive 脚本清理历史 findings
- **TUI 渲染清理**：删除 `subagent_start/end` 死事件类型，task 工具状态机靠 LangChain 标准 tool_call/tool_result 驱动

**新增文档**：
- `docs/skill_authoring_standard.md`：新 skill 编写完整模板与规范
- `docs/framework_design_notes.md`：当前框架与业界标准 agent 框架的差异说明（合理保留 + 待补齐项）

**实测**：
- 通用 QA "如何配置 HTTP SLB"：主 agent 不调 skill，直接 grep `product/` 给完整 2800+ 字配置说明
- 评审 BUG-121100：verifier 真被调用 + 返回 9000+ 字完整报告 + finalize 兜底确保 runner CLI 模式 final_answer 完整
- 测试：401 passed + 1 预存 fail

## 2026-05-19

- Trimmed the IST-Core tool metadata registry to the current runtime tool surface:
  `qa_deepagent_ls`, `qa_deepagent_glob`, `qa_deepagent_grep`,
  `qa_deepagent_read_file`, `python_exec`, and `bash_exec`.
- Removed legacy QA/RAG/reviewer/platform tool names from runtime metadata while
  keeping TUI historical event rendering separate.
- Restored the IST-Core event sink modules required by streaming and replay imports:
  `JsonlFileSink` and `LangSmithSink`.
- Confirmed no additional dependency installation is needed for this fix; the project
  virtual environment already provides `langchain_core`, `deepagents`, and `langsmith`.
- Added focused event sink tests covering package exports, JSONL event persistence,
  CLI replay ordering, token flush behavior, and the default-disabled LangSmith sink.
