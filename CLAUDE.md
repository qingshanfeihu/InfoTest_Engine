# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 语言要求

所有回复必须使用中文。

## 项目目标

本项目展示名为 **InfoTest Engine**，agent 核心展示名为 **IST-Core**。代码包路径为 `main.ist_core`；LangGraph graph id 与 node 名保留 `qa_agent` 指针以兼容已有外部 API；环境变量统一 `IST_*` 前缀（vendor 专有 key 如 `OPENAI_*` / `DEEPSEEK_*` / `MINERU_*` 不变）。

InfoTest Engine 把技术文档（网络 / IPv6 / HTTP/2 / 网关配置指南等）和测试用例（xlsx）转成 markdown 落地，让 IST-Core agent 用 `fs_read` / `fs_grep` / `fs_ls` / `fs_write` / `fs_edit` 直读直写，配合可切换的 LLM provider（默认走 `OPENAI_*` 通用兼容端点，示例小米 MiMo `mimo-v2.5-pro`；可切 DeepSeek 原生端点）提供测试评审、用例编译与上机验证能力。

**架构原则**：`knowledge/data/orgin/` 经 KMS 分桶后转 markdown 直出；知识消费靠 agent 直读 + Footprint 已验证 CLI 事实树；用例编译走确定性 `compile_*` 工具链，与上机验证（`ist_verify`）解耦。

## 常用命令

```bash
# 安装依赖
pip install -r requirements.txt

# KMS 知识管线（TUI 内 slash command，或等价 CLI）
# /kms status                          总览
# /kms product status                  分类预览（LLM 判定）
# /kms product update                  mineru_batch_export → knowledge/data/markdown/product/
# /kms qa status                       测试桶（test_case_list + test_strategy）预览
# /kms qa update                       xlsx → openpyxl 转 md；其他 → mineru → knowledge/data/markdown/qa/

# 等价 CLI
python -m main.mineru_batch_export                                     # 受 KMS_PRODUCT_FILES + KMS_OUTPUT_BUCKET env 控制
python -m main.xlsx_to_markdown <xlsx_path> [--out <md_path>]          # xlsx → GFM 表格

# IST-Core — 交互入口
infotest                                       # Textual 终端 TUI（默认）
infotest --server                              # Web Terminal（ink，默认 :8080；PID 见 .web_server.pid）
langgraph dev --no-browser --port 2024         # 可选：LangGraph dev server（Studio/debug）

# E2E 评审回归（cookie 121100 套件，约 3-6 min）
.venv/bin/python -m scripts.debug.e2e_cookie_review_v2 --tag <fix_name>
```

## TUI 验证（优先用 cmux skill 直接抓屏，勿走后台）

改了 ink/Textual TUI（`main/ist_core/ink/` / `tui/`）后，**优先用 cmux skill 直接读终端 pane 验证**：`cmux read-screen --surface <id>` 实时抓屏，`cmux send` / `cmux send-key` 驱动输入。**不要用后台命令轮询抓屏**——不可靠、易看漏/看错。重启 infotest 若用 `kill`，先 `printf '\033[?1000l\033[?1002l\033[?1003l\033[?1006l'; stty sane; clear` 清鼠标跟踪；更稳的是 Ctrl-C + Ctrl-D 干净退出。编译 fork 步骤明细全量写 `runtime/logs/compile_evidence.live.log`（fastlog），`tail -f` 看过程，TUI 内只摘要不刷高频明细。

## 关键架构决策

- **KMS 分桶**：`main/kms_classifier.py` 用 LLM 把 `knowledge/data/orgin/` 文件分到 `product` / `test_case_list` / `test_strategy` / `unclassified`。三层兜底：用户覆盖（`knowledge/.classifier_overrides.json`）→ 文件级缓存（`knowledge/.intermediate/.classifier_cache.json`，按 filename+mtime+size）→ LLM 判定。
- **markdown 直出**：
  - `mineru_batch_export.py` 解析 PDF / docx / pptx，从 zip 里把 `full.md` 写到 `knowledge/data/markdown/{product|qa}/{stem}.md`（由 `KMS_OUTPUT_BUCKET` env 决定）。
  - `xlsx_to_markdown.py` 用 openpyxl 直接转 GFM 表格，不调 LLM。
- **知识库与工作区分离**（2026-05-24）：
  - `knowledge/data/` — 纯只读知识库（`orgin/` 源文档 + `markdown/` KMS 产出 + `auto_env/` 自动化拓扑）
  - `workspace/` — agent 工作区：`inputs/`（用户上传）、`outputs/`（agent 产出，唯一可写）、`defects/`（缺陷缓存）
  - **强制机制**：`file_tools.py` 实现 `_agent_roots()` 多根沙箱（knowledge/data + workspace + IST_SESSION_DIR + IST_USER_DIR），`_resolve_inside_root` 三闸（traversal → 平台黑名单 → 多根白名单），`_resolve_writable_path` 四闸（traversal → 黑名单 → workspace 根 → outputs 子目录白名单）。修改 these 常量等于修改 agent 沙箱范围，需经安全评审。
  - 回归测试：`tests/ist_core/test_deepagent_large_file_tools.py`（读）+ `test_deepagent_write_tools.py`（写）+ `test_deepagent_multi_root_sandbox.py`（多根）
- **自动化环境拓扑**（`knowledge/data/auto_env/`）：
  - `network_topology.json` — 设备 IP / 子网可达性的唯一事实源（`env_facts.py` 投影；换测试床只改 JSON）
  - `network_topology_rag.md` — 给人/agent 读的拓扑说明
  - `execute_actions.json` — 合法动作词表
  - `config-automation` skill — 把 LLM 生成的示例 IP 替换为环境真实 IP
- **运行时产物**：`runtime/` 目录收纳 `logs/`、`conversation_history/`、`large_tool_results/`、`users/`，均在 `_PLATFORM_DENIED_TOP_LEVEL` 黑名单中。可选落盘配置 `runtime/compiler_config.json`（不入 git，含 `environments` 等）。
- **死循环护栏**（`middleware/loop_guard.py`）：`LoopGuardMiddleware` 在 `wrap_model_call` 检测 agent 原地空转——最近 `IST_LOOP_WINDOW`（默认 8）个工具调用的滑动窗口里，同一 `(tool+args)` 指纹频次 ≥`IST_LOOP_DUP_THRESHOLD`（默认 3）、空结果数 ≥`IST_LOOP_EMPTY_THRESHOLD`（默认 4）、或本轮 tool_call 超 `IST_LOOP_SOFT_BUDGET`（默认 25）——注入收敛 reminder（不写回 state）。`IST_LOOP_GUARD_ENABLED=0` 可关。
- **Web 上传/下载结构化信号**：Web Terminal 经 PTY 桥接 spawn TUI 子进程。上传/下载走自定义 OSC 序列（文件名 base64）：上传 `ESC]7001;...`；下载 `ESC]7002;...`（agent 写 `workspace/outputs/` → `run_done` diff → 前端刷新下载面板）。本地 TUI 手敲文件名走 `input_preprocessor` 兜底。

## 评审能力

1. **评审主链路走 IST_MODEL**（示例 `mimo-v2.5-pro`）。统一通过 `_build_chat_model` 走 OpenAI 兼容端点：`OPENAI_BASE_URL` + `OPENAI_API_KEY`。换厂商只改 `OPENAI_BASE_URL` + key + `IST_MODEL`。
2. **入口 skill**：`test-list-review`（用户说「评审」时 main agent 第一个 tool_call 调 `invoke_skill`）。
3. **证据纪律 + 评审基线 + 输出结构** 写在 skill/agent prompt 内；缺陷检索走 `kb_bug_search`（Bugzilla/禅道 fixtures 或 live 抓取）。

## 工具目录结构

```
main/ist_core/tools/
  deepagent/     — 通用文件/执行原语：fs_ls / fs_glob / fs_grep / fs_read / fs_write / fs_edit / run_python / run_shell
  device/        — 设备/跳板机：dev_ssh / dev_rest / dev_probe / dev_run_case / dev_run_batch
                   编译链：compile_pipeline / compile_prep / compile_fanout / compile_emit / compile_emit_merged
                          / compile_precedent / compile_score / compile_attribute / compile_runtime_slots / compile_runtime_fill
  knowledge/     — kb_footprint / kb_bug_search
  ask_user/      — ask_user
  skills/        — invoke_skill
  memory_tool.py — remember
  _shared/       — metadata / env_facts / ablation
```

**工具命名（2026-06-23 收口）**：按能力域命名空间化——`fs_*` / `run_*` / `dev_*` / `compile_*` / `kb_*` + 裸名核心（`ask_user` / `invoke_skill` / `remember`）。`fs_*` 必带前缀以避开 deepagents 屏蔽的原生 `{read_file,ls,glob,grep,write_file,edit_file,execute}`。包名 `main.ist_core` / graph id `qa_agent` / env `IST_*` 冻结。

## Skills（`main/ist_core/skills/`）

| Skill | 类型 | 用途 |
|-------|------|------|
| `test-list-review` | user-invocable | 测试用例/策略评审（主入口） |
| `ist_compile` | inline | 脑图 → case.xlsx 编译编排（调 `compile_pipeline`） |
| `ist_compile_draft` | fork | 编译子流程：先例检索 + emit 草稿 |
| `ist_compile_grade` | fork | 编译子流程：断言质量审批 |
| `ist_verify` | user-invocable | 成品 excel 上机验证 + 归因 |
| `device-verify` | user-invocable | 设备 SSH 只读/配置验证 |
| `config-automation` | inline | 示例 IP → 环境真实 IP 替换 |
| `config-answer` | inline | 配置问答 |
| `review-verification` | fork | 评审验证子流程 |
| `escalate-when-stuck` | inline | 连续失败上报 |

user-invocable skill 同时注册为 TUI slash 命令（`/<skill-name>`）。

### skill/agent prompt 编写红线

写 skill/agent 的 `.md` prompt 时（融合 Anthropic 官方 [skill best practices](https://platform.claude.com/docs/en/agents-and-tools/agent-skills/best-practices) + 本项目实证；官方 meta-skill `skill-creator` 在 github.com/anthropics/skills）：

- **按「自由度」匹配语气（官方 degrees of freedom——这是总纲）**：先判这一步是哪种路况——
  - **高自由度**（多种做法都对、靠上下文定，如「该探哪条命令 / 该用什么形态断言」这类领域判断）：陈述事实与现象 + 用祈使把动作说清 + 解释**为什么**，让 LLM 据此自己判断；期望值不写死答案（见下）。如开阔田野，给方向、信任模型。
  - **低自由度**（脆弱、只有一条安全路径，如 emit 结构契约、固定执行序列）：可用精确约束（「按 X→Y→Z 顺序」「这条命令不改」）。如窄桥两侧悬崖，精确护栏在这里是对的、不算违规。
  - **真正要避免的**：把 ALL-CAPS 的「必须/务必/绝不/永远」当**默认**手段、且不解释 why（官方称 yellow flag）。**不是避免一切祈使**——官方默认 prefer 祈使式（「先读 X，再做 Y」）；把该说清的动作藏成模糊名词化陈述，反而让 LLM 多解码一层、语义发虚。（旧版「只陈述、一律禁指令」在这点上走过头了。）
- **零写死领域命令**：prompt 里不出现具体设备命令（如 `show statistics sdns pool` / `Hit:N` / 具体 sdns 语法）；该探/该断言哪条命令，靠 LLM 查手册/先例/footprint 得出。
- **示例分两类，别一刀切禁**：
  - **输出形态/格式**的示例（断言长什么样、provenance JSON 的结构骨架）——官方鼓励，帮 LLM 看清形态，可给。
  - **领域判断答案**的具体例子（「算法类应改成 `show statistics`」）——禁。LLM 会当通用规则一刀切套用、误伤异类。实证：grade 重做意见写死「算法类补 `show statistics`」→ GA 本该 `dig` 验命中、却被迫套出 `Hit:\d+` 恒真断言 → 3 个 GA case 连续 CUT 回归。
- **术语一致 + 假设 LLM 已聪明**：同一概念自始至终用同一个词（别一会儿「成员 IP」一会儿「落点」——术语漂移会让 LLM 误判同/异）；不解释 LLM 已知的基础（RR 是什么、dig 是什么），把 token 留给真正的踩坑点。
- **改 prompt 前先有 eval（官方 eval-first）**：把要防的回归固化成可机读断言（如「产出 excel 不含写死的 `Hit:\s+1` / 命中 IP」），改完跑 eval + baseline 对比，别只靠肉眼看一次产物就下结论。

## main 子包结构

| 子包 | 职责 | 模块 |
|------|------|------|
| `main.common`   | 通用工具与外部依赖封装 | paths / env / utils / progress / cli_commands |
| `main.ingest`   | HTML 抓取（Bugzilla / 禅道） | defect_fetch / defect_parse / html_extractors/ |
| `main.ist_core` | IST-Core 对话式 Agent | graph / runner / tui/ / ink/ + agents/ + tools/ + memory/ |
| `main.case_compiler` | 用例编译运行时 | config / env_pool / device_mcp_client / corpus / xlsx_emit |

顶层管线模块：

- `main/kms_classifier.py` — orgin 分桶（LLM）
- `main/mineru_batch_export.py` — PDF/docx → markdown
- `main/xlsx_to_markdown.py` — xlsx → GFM 表格
- `main/knowledge_paths.py` — 路径常量 + `source_authority()` 权威度
- `main/function_llm.py` — DashScope chat_completion（kms_classifier + memory dream consolidate 用）
- `main/langchain_env.py` — `environment` 文件 dotenv loader

## 用例编译（`main/case_compiler/` + `ist_compile_*` skill）

把人工测试用例（脑图）编译成断言真覆盖目标行为的 `case.xlsx`。**走平台正路**：用户在 TUI 让 main agent 编译，main agent 作为编排器派发子流程。**编译入口为 `ist_compile`**：对每个脑图只调一次 `compile_pipeline`（单条是 N=1 特例）。**编译与上机验证解耦**：编译只产出 excel；上机走 `ist_verify`。

- **统一编排** `ist_compile`：main agent 对每个脑图调一次 `compile_pipeline`——`compile_prep` 解析脑图→manifest → 每 case 独立流水线（draft → grade → CUT 重做 ≤3 轮，N case 并发）→ `compile_emit_merged` 合并打包。主 agent **不自己拆步调 prep/fanout/merge**。
- **两个 fork 子流程**（彼此隔离，消除自生成自评估）：
  - `ist_compile_draft`：核查前置 → `compile_precedent` 检索先例 → `compile_emit` 生成草稿。
  - `ist_compile_grade`：`compile_score` 断言质量审批。末行机读标记 `判定：PASS|CUT`，`compile_pipeline._parse_grade_verdict` 优先认它。
- **emit 出口结构门**（`emit_xlsx_tool` + `structural_gate`，确定性强制）：
  - **crash-gate**：带 H 的观测步不更新 `result` → 断言前须有「不带 H 的观测步」；捕获比较走 `dig(H=v1)→dig(无H)→check_point(H=v1)`。
  - **found_times 拒绝门**：框架只传 2 参，拒绝 `found_times`。
  - **found→abs_found**：check_point 引用 H 寄存器时自动转字面匹配。
  - **test_env 主机名小写**：`getattr(env, F)` 不转小写。
  - **persistence 掩码**：prefix `24` → 点分 `255.255.255.0`。
- **独立上机验证** `ist_verify`：对成品 excel 用 `dev_run_batch_digest` 上机（跑批进度实时写 evidence fastlog）。整份 xlsx 单跑 O(N)（deliver+run 一次，超时 `clamp(max(floor, N×45s), 600, 2400)`）。`compile_runtime_fill` 回填 `<RUNTIME>` 断言。**归因（2026-07-02 收缩重写）**：机械预判只认两个协议级事实——`compile_attribute` 返回 **G(^)**（设备语法拒绝标记，上游根因、直接采信）与 `found_times` 等文件级崩溃签名（编译缺陷）；**其余一律 undetermined，device_context 原文交 LLM 归因**（E/V/瞬态/疑似产品缺陷——曾有瞬态/E/G marker 关键字表，实证误归已删，勿加回）。digest 跨轮对照机械点名「连续两轮同签名 fail=冻结同法重编」「上轮瞬态本轮复现=误归」；确定性止损跑完为先，真 PASS 写回 footprint。
- **交付门槛是 grade 断言质量**；上机 pass 不是交付前置。连续 CUT 走 `escalate-when-stuck` / `ask_user`。
- **红线**：skill/agent 零写死领域命令（靠 LLM 查 `*cli__part*.md`/先例/footprint）；断言期望值溯源先例/手册，不 observe-then-assert。

## 自动化环境池（多跳板机并行 verify，默认关）

跳板机 = 框架 stdio MCP server 入口（`FrameworkMCPClient` 经 SSH 驱动 `dev_run_batch`）。

| 配置位置 | 内容 |
|----------|------|
| `environment` / `environment.example` §十 | `IST_JUMPHOST_PASS`、`IST_JUMPHOST_HOST`、`IST_ENV_POOL_ENABLED`、`IST_ENV_POOL_HOSTS` |
| `main/case_compiler/config.py` | `Environment` 数据类 + `load_environments()`；内置默认 4 机 `10.4.127.103/93/79/105` |
| `main/case_compiler/env_pool.py` | `acquire()` / `release()` + fcntl 跨进程锁 + `framework_ready` health-check |
| `runtime/compiler_config.json` | 池开启时 `environments` 列表优先于 env |
| `scripts/maintenance/deploy_framework_to_envs.py` | 把 103 的旧 stdio 框架克隆到新机（入池前置） |

- **池关**（默认）：只用现役单跳板机（`IST_JUMPHOST_HOST`，缺省 103），零行为变化。
- **池开**（`IST_ENV_POOL_ENABLED=1`）：4 机各自独立设备床；`dev_run_batch` 经 `env_pool.acquire()` 认领空闲就绪环境。单环境内串行（设备级全局锁），跨环境并行（多份 excel 同时发多个 `dev_run_batch`）。
- 4 台跳板机共用 `knowledge/data/auto_env/network_topology.json`（设备床隔离克隆，地址相同）。

## 记忆子系统（`main/ist_core/memory/`）

三层架构 + **Footprint 知识树**（autodream 增强）：

| 层 | 路径 | 注入位置 | 写入触发 |
|---|---|---|---|
| L1 工作记忆 | `memory/working/<thread_id>.md` | reminder 末尾 | `MemoryWriteMiddleware` 规则抽取 |
| L2 长期记忆 | `memory/long_term/{preferences,feedback,project,reference}` | reminder top-k=3 | `/remember` + distill fork |
| L3 项目指令 | `memory/AGENTS.md` | system prompt | dream 蒸馏 / 手工 |
| **Footprint** | `knowledge/footprints/nodes/*.json` | reminder top-k=2 + `kb_footprint` | dream consolidate → router + merger |

**Footprint 知识树**：按 CLI 命令前缀组织的已验证产品事实（语法、决策规则、行为、已知缺陷）。物理结构为扁平 `nodes/<feature_id>.json`（`leaf`/`trunk`/`branch` 是 JSON 内 `level` 字段）。TUI：`/footprint` / `/footprint show` / `/footprint search` / `/footprint stats`。

**TUI 记忆命令**：`/memory`、`/remember`、`/footprint`；底栏 `💭 dreaming` / `✓ memory consolidated`。

**关键 env**：`IST_MEMORY_ENABLED`、`FOOTPRINT_ENABLED`、`IST_HAIKU_MODEL`（footprint 提取）、`IST_DREAM_ENABLED`、`IST_SQLITE_PATH`（LangGraph checkpoint，TUI 用 AsyncSqliteSaver + `aiosqlite`）。

## Token 安全

- API key 通过项目根目录 `environment` 文件注入（`KEY=value`）；模板为 `environment.example`（已在 `.gitignore`）
- `kms_classifier` 缺 `OPENAI_API_KEY` 时返回 `unclassified`（不污染 mineru 链）
- 禁止在代码、注释、日志中打印 Token 或 API Key

### 常用环境变量

- **模型**：`IST_MODEL` / `IST_OPUS_MODEL` / `IST_SONNET_MODEL` / `IST_HAIKU_MODEL`；`IST_THINKING=off` 加速 agentic loop
- **流式**：`IST_LLM_STREAMING=0` 关流式（批量编译跑 `infotest -p` 时防网关空 chunk 死挂）
- **KMS**：`KMS_PRODUCT_FILES`、`KMS_OUTPUT_BUCKET`、`MINERU_BATCH_SIZE`、`KMS_UPDATE_TIMEOUT_SEC`
- **缺陷库**：`DEFECT_BACKEND`、`DEFECT_ON_DEMAND_ENABLED`、`CAPTCHA_OCR_RETRY`
- **设备 SSH**（`device-verify`）：`APV_DEVICE_IP`、`APV_USERNAME`、`APV_PASSWORD`
- **环境池**：`IST_JUMPHOST_PASS`、`IST_JUMPHOST_HOST`、`IST_ENV_POOL_ENABLED`、`IST_ENV_POOL_HOSTS`
- **其他**：`NO_PROGRESS=1`、`IST_LOOP_GUARD_ENABLED`

## 技术栈

- Python 3.11+（`deepagents>=0.5.3` 强约束），`langchain` ≥ 1.2.15，`langgraph` ≥ 1.1，`textual` TUI + `fastapi` Web Terminal
- MinerU API — PDF / docx → markdown
- OpenAI 兼容端点（默认 `OPENAI_*`，示例小米 MiMo `mimo-v2.5-pro` 评审 / `mimo-v2.5` haiku tier）
- 推荐：`python3.11 -m venv .venv && pip install -r requirements.txt`
