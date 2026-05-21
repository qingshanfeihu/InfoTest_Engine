# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 语言要求

所有回复必须使用中文。

## 项目目标

本项目展示名为 **InfoTest Engine**，agent 核心展示名为 **IST-Core**。当前代码路径、graph id、工具名前缀和环境变量保留历史兼容名（如 `main.qa_agent`、`qa_agent`、`qa_*`），除非另有迁移计划，不要改这些运行时标识。

InfoTest Engine 把技术文档（网络 / IPv6 / HTTP/2 / 网关配置指南等）和测试用例（xlsx）转成 markdown 落地，让 IST-Core agent 用 `read_file` / `grep` / `ls` 直读，配合 `qwen3.6-plus` 提供测试评审、测试资产理解能力。

**架构原则（2026-05-20 简化收口）**：不再做 LLM 特征抽取 / Qdrant 向量索引 / RAG 检索。orgin/ 文档只做两件事：①KMS 分桶；②转 markdown 直出。

## 常用命令

```bash
# 安装依赖
pip install -r requirements.txt

# KMS 知识管线（TUI 内执行 slash command，或下面的等价 CLI）
# /kms status                          总览
# /kms product status                  分类预览（LLM 判定）
# /kms product update                  mineru_batch_export → knowledge/data/markdown/product/
# /kms qa status                       测试桶（test_case_list + test_strategy）预览
# /kms qa update                       xlsx → openpyxl 转 md；其他 → mineru → knowledge/data/markdown/qa/

# 等价 CLI
python -m main.mineru_batch_export                                     # 受 KMS_PRODUCT_FILES + KMS_OUTPUT_BUCKET env 控制
python -m main.xlsx_to_markdown <xlsx_path> [--out <md_path>]          # xlsx → GFM 表格

# IST-Core — 服务控制（PID 存 .langgraph_api/）
.\tests\qa_agent_backend.ps1 -Action start     # LangGraph dev server (2024，--no-reload)
.\tests\qa_agent_ui.ps1       -Action start    # agent-chat-ui (默认 4000)
.\tests\qa_agent_backend.ps1 -Action status    # 查 PID

# E2E 评审回归（cookie 121100 套件，约 3-6 min）
.venv\bin\python -m scripts.debug.e2e_cookie_review_v2 --tag <fix_name>
```

## 关键架构决策

- **不要 Qdrant**：实测 IST-Core agent 用 `read_file` / `grep` / `ls` + qwen3.6-plus 已满足业务需求，不再需要向量检索（详见 `todolist.md` 第 1 节）。
- **KMS 分桶**：`main/kms_classifier.py` 用 LLM 把 `knowledge/data/orgin/` 文件分到 `product` / `test_case_list` / `test_strategy` / `unclassified`。三层兜底：用户覆盖（`knowledge/.classifier_overrides.json`）→ 文件级缓存（`knowledge/.intermediate/.classifier_cache.json`，按 filename+mtime+size）→ LLM 判定。
- **markdown 直出**：
  - `mineru_batch_export.py` 解析 PDF / docx / pptx，从 zip 里把 `full.md` 写到 `knowledge/data/markdown/{product|qa}/{stem}.md`（由 `KMS_OUTPUT_BUCKET` env 决定）。
  - `xlsx_to_markdown.py` 用 openpyxl 直接转 GFM 表格，不调 LLM。
- **agent 视野**：agent 只看 `knowledge/data/`（含 `markdown/`、`defects/`、`baselines/`），`knowledge/.intermediate/` 由 `/kms` 命令维护。
  - **强制机制**：`main/qa_agent/tools/deepagent/file_tools.py` 用 `_AGENT_ROOT = knowledge/data/` 白名单 + `_PLATFORM_DENIED_TOP_LEVEL` / `_PLATFORM_DENIED_FILES` 黑名单兜底（含 `main/`、`tests/`、`scripts/`、`agent-chat-ui/`、`.venv*/`、`CLAUDE.md`、`requirements.txt` 等）。`_resolve_inside_root` 三闸：traversal → 平台黑名单 → 白名单。修改这些常量等于修改 agent 沙箱范围，需经安全评审。回归测试见 `tests/qa_agent/test_deepagent_large_file_tools.py`。

## 评审能力（最小方案）

详见 `todolist.md`。两件事：

1. **评审任务路由到 `openai:qwen3.6-plus`**（DashScope OpenAI 兼容端点）。`anthropic:qwen3.6-plus` 路径暂存在 usage metadata 兼容错误，绕开。
2. **追加最小 Review Prompt**（证据纪律 + 评审基线 + 输出结构）。详见 todolist 第 2.2 节。

不做：Excel 专用 parser、`qa_invoke_reviewer`、hierarchical reviewer、`ReviewResult` schema、Qdrant 检索、`qa_search_*` 工具组等。需要时由实际失败样本或产品需求触发。

## 工具目录结构

```
main/qa_agent/tools/
  defect/                — 缺陷搜索 / 抓取（search / fetch_direct / fetch_on_demand / cache）
  asset/search.py        — 测试资产 KB
  knowledge/             — RFC / 参考资料（ref_search / web_search / cli_command 等）
  baseline/load_rules.py — 测试基线规则
  pipeline/              — ingest / scope / run / check_updates / summarize
  reviewer/              — invoke / invoke_async / check_status / resume / cancel / read_large_result / trace_change
  _shared/               — metadata / orchestration / shared / text_sanitizers / web_search / defect_helpers
```

`@tool` 装饰器的 `name=` 字符串保持原样（如 `qa_invoke_reviewer` / `defect_search_kb`），review_inputs/*.json 历史 tool_calls 引用兼容。

## main 子包结构

| 子包 | 职责 | 模块 |
|------|------|------|
| `main.common`   | 通用工具与外部依赖封装 | paths / env / qwen / utils / progress / cli_commands / release_markers |
| `main.ingest`   | HTML 抓取（Bugzilla / 禅道）+ MinerU 旧依赖（保留兼容） | defect_fetch / defect_parse / html_extractors/ |
| `main.qa_agent` | IST-Core 对话式评审 Agent | graph / runner / server_graph / state / schemas / events + agents/{main_agent, _llm} + tools/ + sinks/ |

顶层管线模块：

- `main/kms_classifier.py` — orgin 分桶（LLM）
- `main/mineru_batch_export.py` — PDF/docx → markdown
- `main/xlsx_to_markdown.py` — xlsx → GFM 表格
- `main/knowledge_paths.py` — 路径常量 + `source_authority()` 权威度
- `main/function_llm.py` — DashScope chat_completion（kms_classifier + memory dream consolidate 用）
- `main/langchain_env.py` — `environment` 文件 dotenv loader
- `main/utils.py` — JSON I/O、原子写入、SHA256、UTC 时间戳
- `main/terminal_progress.py` — 单行刷新进度条（`NO_PROGRESS=1` 降级）

## 记忆子系统（`main/qa_agent/memory/`）

三层架构（仿 Claude Code auto memory + deepagents memory 设计）：

| 层 | 路径 | 注入位置 | 写入触发 | 持久化 |
|---|---|---|---|---|
| L1 工作记忆 | `memory/working/<thread_id>.md` | reminder 末尾（每轮）| `MemoryWriteMiddleware.after_model` 规则抽取 | 真实磁盘 |
| L2 长期记忆 | `memory/long_term/{preferences,feedback,project,reference}` | reminder（关键词 top-k=3）| `/remember` 显式 + `MemoryWriteMiddleware` distill 触发 fork agent | 真实磁盘 |
| L3 项目指令 | `memory/AGENTS.md` | system prompt（启动时由 deepagents `MemoryMiddleware`）| dream task LLM 蒸馏 / 手工 | 真实磁盘（git 跟踪） |

**关键模块**：

- `backend.py` — `CompositeBackend` + `_user_namespace` factory + InMemory/SQLite/Postgres store
- `store.py` — `MemoryStore` facade + 三闸路径校验（traversal / 平台黑名单 / 子目录白名单）+ frontmatter 解析（仿 SKILL.md 风格，yaml-free）
- `middleware.py` — `MemoryInjectionMiddleware`（每轮把 L1 工作记忆 + L2 长期记忆拼成 `<memory-context>` HumanMessage 注入到 user query 之前）+ `MemoryWriteMiddleware`（after_model 调 `extract_working_entry` 写 L1 + `_should_distill` 判定后触发 fork agent 蒸馏 L1→L2；同时保留 finalizer 路径供评审场景用）
- `extractor.py` / `extractor_agent.py` — fork agent（仿 cc-haha extractMemories：5 turn 上限 + 互斥锁 + 受限工具）+ `run_extractor_async` 后台线程入口
- `dream.py` — DreamTask 五道闸（功能开关 / 24h / 10min / ≥5sessions / fcntl PID 锁）+ 四阶段（Orient → Gather → Consolidate → Prune）；prune 阶段把 >7 天 working 移到 `working/.archive/`，long_term 加 `archived: true` 标记
- `dream_graph.py` — 包成 LangGraph，注册到 `langgraph.json::memory_dream`
- `scripts/maintenance/memory_dream.py` — 系统 cron 入口

**TUI 集成**：
- `/memory` — 总览 / 查看 / 清除（list / show / clear / status）
- `/remember <text>` — 显式追加偏好（默认 user 类）
- `/remember --feedback|--project|--reference <topic> <text>` — 仿 cc-haha 四类
- 底栏 dreaming 指示：`💭 dreaming` / `✓ memory consolidated`（检测 `memory/.dream/running.pid` 与 `last_run`）

**写入路径白名单（三闸）**：
1. 拒 `..` / 绝对外部路径 / `~`
2. 必须 `/working/` 或 `/memories/` 前缀；写入时再过子目录白名单
3. basename 字符必须 `[A-Za-z0-9_\-.]+`

**安全边界**：
- 主 agent 通过 `_ToolExclusionMiddleware` 屏蔽 `read_file/write_file/edit_file/ls/glob/grep/execute`，无法直接操作 backend 虚拟 fs
- agent 视野隔离：`memory/` 已在 `file_tools._PLATFORM_DENIED_TOP_LEVEL`，`qa_deepagent_*` 拦截
- fork extractor agent 唯一例外：可调 `read_file/edit_file`，但 prompt 强约束 + facade 三闸双保险
- 所有写入入口失败一律静默（logger.warning），主流程不挂

**关键 env**：
- `QA_AGENT_MEMORY_ENABLED=1`（总开关；`0` 时所有 middleware 不挂）
- `QA_AGENT_MEMORY_ROOT=<repo>/memory`（根目录）
- `QA_AGENT_MEMORY_STORE_DSN`（空 → InMemory；`sqlite:///path` 或 `postgresql://...`）
- `QA_AGENT_MEMORY_L2_TOPK=3`、`QA_AGENT_MEMORY_DISTILL_EVERY_N=10`、`QA_AGENT_MEMORY_STALE_DAYS=30`
- `QA_AGENT_DREAM_ENABLED=1`、`QA_AGENT_DREAM_LOOKBACK_DAYS=7`、`QA_AGENT_DREAM_PRUNE_DAYS=7`
- `QA_AGENT_MEMORY_DISABLE_LLM=1`（仅规则抽取，不调 fork agent + dream）

## Token 安全

- `MINERU_TOKEN`、`DASHSCOPE_API_KEY` 通过项目根目录 `environment` 文件注入（`KEY=value`）
- `kms_classifier` 缺 `DASHSCOPE_API_KEY` 时返回 `unclassified`（不污染 mineru 链）
- `environment` 已在 `.gitignore`；模板为 `environment.example`
- 禁止在代码、注释、日志中打印 Token 或 API Key

### 可选环境变量

- `KMS_PRODUCT_FILES`（逗号分隔文件名）— mineru_batch_export 白名单过滤，由 `/kms product update` / `/kms qa update` 设置
- `KMS_OUTPUT_BUCKET=product|qa` — mineru_batch_export 决定 markdown 落到哪个子目录
- `QA_WEB_SEARCH_REPEAT_LIMIT` / `QA_WEB_SEARCH_REPEAT_WINDOW_S`（默认 2 / 600s）— `qa_web_search` 同 query 重复调用上限
- `CAPTCHA_OCR_RETRY`（默认 10）— `defect_fetch_on_demand` 验证码识别重试次数
- `NO_PROGRESS=1` — 非 TTY 环境禁用进度条

## 技术栈

- Python 3.11+（`deepagents>=0.5.3` 强约束），`requests`，`python-dotenv`，`langchain` ≥ 1.2.15，`langgraph` ≥ 1.1
- 推荐用 `py -3.11 -m venv .venv311` 建本地虚拟环境；激活后 `pip install -r requirements.txt`
- MinerU 精准解析 API（`https://mineru.net/api/v4/`）—— 仅用于 PDF / docx → markdown
- DashScope OpenAI 兼容端点：chat（`qwen-plus` 用于 KMS 分类，`qwen3.6-plus` 用于评审）
- 不再依赖 Qdrant / podman；移除了 `langchain-qdrant` / `qdrant-client`
