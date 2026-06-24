# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 语言要求

所有回复必须使用中文。

## 项目目标

本项目展示名为 **InfoTest Engine**，agent 核心展示名为 **IST-Core**。代码包路径升级为 `main.ist_core`，而编译和通信 graph id 保留为 `qa_agent` 指针以兼顾已有外部 API 连接；环境变量已统一迁移到 `IST_*` 前缀（vendor 专有 key 如 `OPENAI_*` / `DEEPSEEK_*` / `MINERU_*` 不变）。

InfoTest Engine 把技术文档（网络 / IPv6 / HTTP/2 / 网关配置指南等）和测试用例（xlsx）转成 markdown 落地，让 IST-Core agent 用 `read_file` / `grep` / `ls` / `write_file` / `edit_file` 直读直写，配合可切换的 LLM provider（默认走 `OPENAI_*` 通用兼容端点，示例为小米 MiMo mimo-v2.5-pro；可切 DeepSeek 原生端点）提供测试评审、测试资产理解能力。

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

# IST-Core — 交互入口
infotest                                       # Textual 终端 TUI（默认）
infotest --server                              # Web Terminal（ink，默认 :8080；PID 见 .web_server.pid）
langgraph dev --no-browser --port 2024           # 可选：LangGraph dev server（Studio/debug）

# E2E 评审回归（cookie 121100 套件，约 3-6 min）
.venv\bin\python -m scripts.debug.e2e_cookie_review_v2 --tag <fix_name>
```

## 关键架构决策

- **不要 Qdrant**：实测 IST-Core agent 用 `read_file` / `grep` / `ls` + 评审模型已满足业务需求，不再需要向量检索（详见 `todolist.md` 第 1 节）。
- **KMS 分桶**：`main/kms_classifier.py` 用 LLM 把 `knowledge/data/orgin/` 文件分到 `product` / `test_case_list` / `test_strategy` / `unclassified`。三层兜底：用户覆盖（`knowledge/.classifier_overrides.json`）→ 文件级缓存（`knowledge/.intermediate/.classifier_cache.json`，按 filename+mtime+size）→ LLM 判定。
- **markdown 直出**：
  - `mineru_batch_export.py` 解析 PDF / docx / pptx，从 zip 里把 `full.md` 写到 `knowledge/data/markdown/{product|qa}/{stem}.md`（由 `KMS_OUTPUT_BUCKET` env 决定）。
  - `xlsx_to_markdown.py` 用 openpyxl 直接转 GFM 表格，不调 LLM。
- **知识库与工作区分离**（2026-05-24）：
  - `knowledge/data/` — 纯只读知识库（`orgin/` 源文档 + `markdown/` KMS 产出）
  - `workspace/` — agent 工作区：`inputs/`（用户上传）、`outputs/`（agent 产出，唯一可写）、`defects/`（缺陷缓存）
  - **强制机制**：`file_tools.py` 实现 `_agent_roots()` 多根沙箱（knowledge/data + workspace + IST_SESSION_DIR + IST_USER_DIR），`_resolve_inside_root` 三闸（traversal → 平台黑名单 → 多根白名单），`_resolve_writable_path` 四闸（traversal → 黑名单 → workspace 根 → outputs 子目录白名单）。修改 these 常量等于修改 agent 沙箱范围，需经安全评审。
  - 回归测试：`tests/ist_core/test_deepagent_large_file_tools.py`（读）+ `test_deepagent_write_tools.py`（写）+ `test_deepagent_multi_root_sandbox.py`（多根）
- **运行时产物**：`runtime/` 目录收纳 `logs/`、`conversation_history/`、`large_tool_results/`、`users/`，均在 `_PLATFORM_DENIED_TOP_LEVEL` 黑名单中。
- **死循环护栏**（`middleware/loop_guard.py`）：`LoopGuardMiddleware` 在 `wrap_model_call` 检测 agent 原地空转——最近 `IST_LOOP_WINDOW`（默认 8）个工具调用的滑动窗口里，同一 `(tool+args)` 指纹频次 ≥`IST_LOOP_DUP_THRESHOLD`（默认 3，能抓 A/B/A/B 交替）、空结果数 ≥`IST_LOOP_EMPTY_THRESHOLD`（默认 4）、或本轮 tool_call 超 `IST_LOOP_SOFT_BUDGET`（默认 25）——注入收敛 reminder（不写回 state）。`IST_LOOP_GUARD_ENABLED=0` 可关。配套：主 agent prompt 的 `Don't Spin` 反空转 section（fork subagent 经 `build_verifier_inherited_sections` 继承）。
- **Web 上传/下载结构化信号**：Web Terminal 经 PTY 桥接 spawn TUI 子进程。上传/下载不走文本流靠正则猜，而走自定义 OSC 序列（文件名 base64，任意字符无损）：上传 `ESC]7001;...`（前端 ws → `web_server` 包 OSC → ink `parse_keypress` 识别 `UploadEvent` → 插入 `inputs/<file>`）；下载 `ESC]7002;...`（agent 写 `workspace/outputs/` → `run_done` diff 新文件 → ink `write_passthrough` 发 OSC → 前端 `registerOscHandler` 刷新下载面板 + 角标）。本地 TUI 手敲文件名走 `input_preprocessor` 兜底。

## 评审能力（最小方案）

详见 `todolist.md`。两件事：

1. **评审主链路走 IST_MODEL**（示例 mimo-v2.5-pro）。统一通过 `_build_chat_model` 走 OpenAI 兼容端点：`OPENAI_BASE_URL` + `OPENAI_API_KEY`，不再做 provider 分支。换厂商（含 DeepSeek 原生口 / DashScope 兼容口 / 自建网关）只改 `OPENAI_BASE_URL` + key + `IST_MODEL`。Anthropic 兼容路径已移除。
2. **追加最小 Review Prompt**（证据纪律 + 评审基线 + 输出结构）。详见 todolist 第 2.2 节。

不做：Excel 专用 parser、`qa_invoke_reviewer`、hierarchical reviewer、`ReviewResult` schema、Qdrant 检索、`qa_search_*` 工具组等。需要时由实际失败样本或产品需求触发。

## 工具目录结构

```
main/ist_core/tools/
  deepagent/     — 通用文件/执行原语：fs_ls / fs_glob / fs_grep / fs_read / fs_write / fs_edit / run_python / run_shell
  device/        — 设备/跳板机：dev_ssh / dev_rest / dev_probe / dev_run_case / dev_run_batch
                   编译链：compile_pipeline / compile_prep / compile_fanout / compile_emit / compile_emit_merged
                          / compile_precedent / compile_score / compile_attribute / compile_runtime_slots / compile_runtime_fill
  knowledge/     — 知识检索：kb_footprint / kb_bug_search
  ask_user/      — ask_user（向用户提问）
  skills/        — invoke_skill（加载 skill）
  memory_tool.py — remember（追加偏好记忆）
  _shared/       — metadata（工具元数据注册）/ env_facts / ablation
```

**工具命名（2026-06-23 硬改名收口）**：去 `qa_` 前缀，按能力域命名空间化——`fs_*`（文件系统）/ `run_*`（本地执行）/ `dev_*`（设备）/ `compile_*`（编译链）/ `kb_*`（知识）+ 裸名核心（`ask_user` / `invoke_skill` / `remember`）。工具名 = `@tool` 函数名；`fs_*` 必带前缀以避开 deepagents 屏蔽的原生 `{read_file,ls,glob,grep,write_file,edit_file,execute}`。历史 `review_inputs/*.json` 回放兼容面经核实已不存在，故工具名不再冻结；包名 `main.ist_core` / graph id 与 graph node `qa_agent` / env `IST_*` 仍冻结。

## main 子包结构

| 子包 | 职责 | 模块 |
|------|------|------|
| `main.common`   | 通用工具与外部依赖封装 | paths / env / qwen / utils / progress / cli_commands / release_markers |
| `main.ingest`   | HTML 抓取（Bugzilla / 禅道）+ MinerU 旧依赖（保留兼容） | defect_fetch / defect_parse / html_extractors/ |
| `main.ist_core` | IST-Core 对话式评审 Agent | graph / runner / server_graph / state / schemas / events + agents/{main_agent, _llm} + tools/ + sinks/ |

顶层管线模块：

- `main/kms_classifier.py` — orgin 分桶（LLM）
- `main/mineru_batch_export.py` — PDF/docx → markdown
- `main/xlsx_to_markdown.py` — xlsx → GFM 表格
- `main/knowledge_paths.py` — 路径常量 + `source_authority()` 权威度
- `main/function_llm.py` — DashScope chat_completion（kms_classifier + memory dream consolidate 用）
- `main/langchain_env.py` — `environment` 文件 dotenv loader
- `main/utils.py` — JSON I/O、原子写入、SHA256、UTC 时间戳
- `main/terminal_progress.py` — 单行刷新进度条（`NO_PROGRESS=1` 降级）

## 用例编译（人工用例 → 自动化 case.xlsx，`main/case_compiler/` + `ist_compile_*` skill）

把人工测试用例（脑图）编译成断言真覆盖目标行为的 `case.xlsx`。**走平台正路**：用户在 TUI 让 main agent 编译，main agent 作为**编排器**派发子流程，不依赖外层脚本。**编译入口为 `ist_compile`**（inline skill）：main agent 对每个脑图只调一次确定性流水线工具 `compile_pipeline`，单条用例与整脑图批量走同一流程（单条是 N=1 特例）。**编译与上机验证解耦**：编译只产出 excel（draft 生成 → grade 断言质量审批 → 合并打包），不上机；上机验证由独立的 `ist_verify` skill 对成品 excel 做。

- **统一编排** `ist_compile`（inline skill，唯一编译入口）：main agent 对每个脑图调一次 `compile_pipeline`，工具内部确定性跑完——`compile_prep` 解析脑图→manifest（只含需求，零命令）→ 每 case 独立流水线（draft 产 provenance → grade 验 provenance → CUT 带反馈重做 ≤3 轮，N case 并发无屏障）→ `compile_emit_merged` 合并打包。**不上机**（上机走 ist_verify）。主 agent **不自己拆步调 prep/fanout/merge**——固定序列锁在 pipeline 工具内（自由度只在 draft/grade fork 内现场查命令）。
- **两个 fork 子流程**（编译链内，独立 fresh subagent，彼此隔离，消除"自生成自评估"）：
  - `ist_compile_draft`（agent `ist-compile-draft`）：核查前置 → 检索先例 → `compile_emit` 生成 xlsx 草稿。
  - `ist_compile_grade`（agent `ist-compile-grade`）：`compile_score` 判断断言是否覆盖目标行为 + 给重做意见。**断言质量审批，不依赖上机裁决**（device verdict 可选输入）。grade fork 末行输出机读裁定标记 `判定：PASS|CUT`，`compile_pipeline._parse_grade_verdict` 优先认它（治"CUT 重做意见里含 PASS 字样被误读"）。
- **emit 出口 correct-by-construction 归一化 + 结构门**（`emit_xlsx_tool` + `structural_gate`，与 grade 语义评分独立的确定性强制，**都有框架源码/footprint 实证**，不靠 prompt 自觉）：
  - **crash-gate（H 感知悬空断言门）**：check_point 的被测值取框架 `result`；带 H(save_as) 的步只存寄存器**不更新 result**、配置步返回 None → 若断言紧前没有「不带 H 的观测步」则 `found(None)` 抛 TypeError **崩整份文件**。门要求捕获比较走三步式 `dig(H=v1)→dig(无H)→check_point(H=v1)`。
  - **found_times 拒绝门**：框架 xlsx 分派只传 2 参，`found_times(expect,result,times)` 需 3 参 → 必崩。拒绝并要求改 `found`/`abs_found`。
  - **found→abs_found（捕获比较）**：check_point 引用 H 寄存器时自动转——框架 `found` 把 expect 当正则、捕获值含 `+`/`.`/`@` 元字符自匹配都 fail；`abs_found` 用 `re.escape` 字面匹配。
  - **test_env 主机名小写**：框架 `getattr(env, F)` 不转小写，`routerB` 大写 → AttributeError、dig 不执行。
  - **persistence 断言掩码 prefix→点分**：`show sdns host persistence` 回显掩码是点分 `255.255.255.0` 非 prefix `24`，断言据此归一。
- **独立上机验证** `ist_verify`（inline skill，user-invocable）：对成品 excel 用 `dev_run_batch` 上机、采集框架真实裁决。`dev_run_batch` **整份单跑 O(N)**：框架把整份 xlsx 当一个套件整跑，故只 deliver+run 一次（用首个 autoid 提交），再从该 staging 一把读回全部 case 裁决；超时随 case 数自适应（`clamp(max(floor, N×45s), 600, 2400)`）。旧逐 autoid 跑法 O(N²)+撞 600s 上限（"跑 20min 无结果"根因）已废。先 `compile_runtime_fill` 用设备真实输出回填 draft 留空的 `<RUNTIME>` 断言并锁死，再用 `compile_attribute` 对每个 fail 做四层归因（G错/E错/V错/瞬态）——G/E/V 错带层级反馈回流 `ist_compile` 重编对应层、瞬态不回流；上机真 PASS 的 case 把 G 段文法写回 footprint。不信 verdict 字符串，以框架逐 check_point 明细为准。
- **交付门槛是 grade 断言质量**（弱断言/未覆盖 CUT，不救场）；上机 pass 不再是交付前置——环境瞬态失败不挡 excel 产出。verify 发现的真实断言问题可回流重编译。连续 N 轮 CUT 则 escalate/ask_user 上报。
- **case_compiler 现存活件**（早期确定性管线已删）：`case_ir`+`xlsx_emit`（xlsx 数据结构与产出）/`confidence_f`（LLM 置信判分，非硬编码规则）/`corpus`+`object_normalizer`（先例语料与 E 列对象名规范化）/`config`/`device_mcp_client`（跳转机通道）。
- **关键工具**：`compile_precedent`（按配置结构相似度检索已验证先例，无 embedding）/`compile_score`（判分，返回结构化 JSON）/`compile_emit`/`dev_run_case`/`dev_probe`/`compile_prep`/`compile_fanout`/`dev_run_batch`/`compile_emit_merged`——均在 `skills/loader.py` 的 `_TOOL_REGISTRY` 注册供 fork 子流程取用。检索与置信工具在 `tools/device/precedent_tools.py`，批量编排工具在 `tools/device/batch_tools.py`+`compile_prep.py`。
- **红线**：skill/agent 定义零写死的 sdns/APV 具体命令（领域内容靠 LLM 现场查手册 `*cli__part*.md`/先例）；断言期望值溯源先例/手册，不 observe-then-assert。

## 记忆子系统（`main/ist_core/memory/`）

三层架构（auto memory + deepagents memory 设计）+ **Footprint 知识树**（autodream 增强）：

| 层 | 路径 | 注入位置 | 写入触发 | 持久化 |
|---|---|---|---|---|
| L1 工作记忆 | `memory/working/<thread_id>.md` | reminder 末尾（每轮）| `MemoryWriteMiddleware.after_model` 规则抽取 | 真实磁盘 |
| L2 长期记忆 | `memory/long_term/{preferences,feedback,project,reference}` | reminder（关键词 top-k=3）| `/remember` 显式 + `MemoryWriteMiddleware` distill 触发 fork agent | 真实磁盘 |
| L3 项目指令 | `memory/AGENTS.md` | system prompt（启动时由 deepagents `MemoryMiddleware`）| dream task LLM 蒸馏 / 手工 | 真实磁盘（git 跟踪） |
| **Footprint** | `knowledge/footprints/nodes/*.json`（扁平目录，文件名=feature_id 点分命令前缀；leaf/trunk/branch 是 JSON 内 `level` 字段，非物理子目录）| reminder（自动注入 top-k=2）+ `kb_footprint` tool | dream consolidate LLM 提取 → router + merger | 真实磁盘 JSON |

**关键模块**：

- `backend.py` — `CompositeBackend` + `_user_namespace` factory + InMemory/SQLite/Postgres store
- `store.py` — `MemoryStore` facade + 三闸路径校验（traversal / 平台黑名单 / 子目录白名单）+ frontmatter 解析（仿 SKILL.md 风格，yaml-free）；`read_footprints()` / `lookup_footprint()` 走 FootprintIndex
- `middleware.py` — `MemoryInjectionMiddleware`（每轮把 L1 工作记忆 + L2 长期记忆 + Footprint 拼成 `<memory-context>` HumanMessage 注入到 user query 之前）+ `MemoryWriteMiddleware`（after_model 调 `extract_working_entry` 写 L1 + `_should_distill` 判定后触发 fork agent 蒸馏 L1→L2；同时保留 finalizer 路径供评审场景用）
- `extractor.py` / `extractor_agent.py` — fork agent（extractMemories 模式：5 turn 上限 + 互斥锁 + 受限工具）+ `run_extractor_async` 后台线程入口
- `dream.py` — DreamTask 五道闸（功能开关 / 24h / 10min / ≥5sessions / fcntl PID 锁）+ 四阶段（Orient → Gather → Consolidate → Prune）；consolidate 同时跑 footprint 提取（haiku tier 模型，逐文件 LLM 调用）和 AGENTS.md 蒸馏；prune 阶段把 >7 天 working 移到 `working/.archive/`，long_term 加 `archived: true` 标记
- `dream_graph.py` — 包成 LangGraph，注册到 `langgraph.json::memory_dream`
- `scripts/maintenance/memory_dream.py` — 系统 cron 入口
- `footprint/` — `index.py`（懒加载内存索引，单例）+ `extractor.py`（LLM 提取产品事实）+ `router.py`（CLI 命令前缀路由）+ `merger.py`（dedup + verified_count 累积）

**Footprint 知识树**（`knowledge/footprints/`，autodream 增强）：

按 CLI 命令前缀组织的产品/测试知识树。每个节点是一个 JSON 文件，包含从对话中验证过的事实（CLI 语法、决策规则、行为说明、已知缺陷）。

- **物理结构**：`knowledge/footprints/nodes/<feature_id>.json` 扁平目录，文件名即点分命令前缀（如 `slb.group.member.json`）。节点 schema（v3）字段：`feature_id` / `level`（leaf/trunk/branch）/ `cli.commands[]` / `decision_rules[]` / `behaviors[]` / `known_issues[]` / `children[]`（子节点构成树）/ `version_scope` / `footprint_meta`（`verified_count` + `source_threads` + `created_at`）。每条事实带 `fact_key` + 内容 + `evidence`（`source_file` + `quoted_text` 可溯源）。branch/trunk 多为索引空壳，实际事实集中在 leaf。
- **数据来源**：dream consolidate 阶段用 LLM (`IST_HAIKU_MODEL`，默认 mimo-v2.5) 从 working memory 中提取，每文件一次调用，结果走 `function_llm.chat_completion` 缓存
- **路由规则**：剥离 `no/show/clear` 操作前缀 → 命令 token 化 → 按公共前缀分组写入 `level` 字段（≥2 token=leaf；同模块多功能=trunk；跨模块=branch，均为逻辑分层非物理目录）；无 CLI 命令的 fact 直接丢弃，不污染功能树
- **检索路径**：`MemoryInjectionMiddleware` 自动注入（自然语言查询） + `kb_footprint` tool（agent 主动按命令名精确查询）
- **TUI 入口**：`/footprint` 总览、`/footprint show <command>`、`/footprint search <query>`、`/footprint stats`、`/footprint list [level]`
- **关键 env**：`FOOTPRINT_ENABLED=1`（开关）、`IST_HAIKU_MODEL`（提取模型）

**TUI 集成**：
- `/memory` — 总览 / 查看 / 清除（list / show / clear / status）
- `/remember <text>` — 显式追加偏好（默认 user 类）
- `/remember --feedback|--project|--reference <topic> <text>` — 四类记忆
- `/footprint` — Footprint 知识树查看 / 搜索 / 统计
- 底栏 dreaming 指示：`💭 dreaming` / `✓ memory consolidated`（检测 `memory/.dream/running.pid` 与 `last_run`）

**写入路径白名单（三闸）**：
1. 拒 `..` / 绝对外部路径 / `~`
2. 必须 `/working/` 或 `/memories/` 前缀；写入时再过子目录白名单
3. basename 字符必须 `[A-Za-z0-9_\-.]+`

**安全边界**：
- 主 agent 通过 `_ToolExclusionMiddleware` 屏蔽 `read_file/write_file/edit_file/ls/glob/grep/execute`，无法直接操作 backend 虚拟 fs
- agent 视野隔离：`memory/` 已在 `file_tools._PLATFORM_DENIED_TOP_LEVEL`，`fs_*` 拦截
- fork extractor agent 唯一例外：可调 `read_file/edit_file`，但 prompt 强约束 + facade 三闸双保险
- 所有写入入口失败一律静默（logger.warning），主流程不挂

**关键 env**：
- `IST_MEMORY_ENABLED=1`（总开关；`0` 时所有 middleware 不挂）
- `IST_MEMORY_ROOT=<repo>/memory`（根目录）
- `IST_SQLITE_PATH` — LangGraph checkpoint（TUI 用 **AsyncSqliteSaver**，需 `aiosqlite`；勿用同步 SqliteSaver + `astream_events`）
- `IST_MEMORY_STORE_DSN`（空 → InMemory；`sqlite:///path` 或 `postgresql://...`）
- `IST_MEMORY_L2_TOPK=3`、`IST_MEMORY_DISTILL_EVERY_N=10`、`IST_MEMORY_STALE_DAYS=30`
- `IST_DREAM_ENABLED=1`、`IST_DREAM_LOOKBACK_DAYS=7`、`IST_DREAM_PRUNE_DAYS=7`
- `IST_MEMORY_DISABLE_LLM=1`（仅规则抽取，不调 fork agent + dream）

## Token 安全

- `MINERU_TOKEN`、`OPENAI_API_KEY`（或 `DEEPSEEK_API_KEY`）通过项目根目录 `environment` 文件注入（`KEY=value`）
- `kms_classifier` 缺 `OPENAI_API_KEY` 时返回 `unclassified`（不污染 mineru 链）；分类走主链路同一 provider（`OPENAI_*`）+ haiku tier 模型
- `environment` 已在 `.gitignore`；模板为 `environment.example`
- 禁止在代码、注释、日志中打印 Token 或 API Key

### 可选环境变量

- `KMS_PRODUCT_FILES`（逗号分隔文件名）— mineru_batch_export 白名单过滤，由 `/kms product update` / `/kms qa update` 设置
- `KMS_OUTPUT_BUCKET=product|qa` — mineru_batch_export 决定 markdown 落到哪个子目录
- `MINERU_BATCH_SIZE`（默认 30）— MinerU API 每批文件数（全量在子进程内串行多批）
- `KMS_UPDATE_TIMEOUT_SEC`（默认 7200）— TUI `/kms * update` 子进程超时秒数
- TUI 日志：`knowledge/.intermediate/.kms_product_update.log` / `.kms_qa_update.log`（子进程输出；TUI 每 `KMS_LOG_POLL_INTERVAL_SEC` 秒 tail 到 transcript + 输入框上方状态行）
- `KMS_LOG_POLL_INTERVAL_SEC`（默认 2）— TUI 刷新 MinerU 进度的轮询间隔
- `QA_WEB_SEARCH_REPEAT_LIMIT` / `QA_WEB_SEARCH_REPEAT_WINDOW_S`（默认 2 / 600s）— `qa_web_search` 同 query 重复调用上限
- `CAPTCHA_OCR_RETRY`（默认 10）— `defect_fetch_on_demand` 验证码识别重试次数
- `NO_PROGRESS=1` — 非 TTY 环境禁用进度条
- `IST_LLM_STREAMING`（默认 `1` 开）— `_build_chat_model`/`build_explore_model` 是否流式。TUI `astream_events` 需开；**`0` 关流式**用于不稳定端点的批量 agent 跑（如 `infotest -p` 跑编译流水线）：某些 OpenAI 兼容网关流式会周期性发空 chunk、令 httpx 每 chunk 重置读超时 → 整体永不完成也永不超时（0% CPU 死挂）。非流式走单次请求 + 干净的整体 `request_timeout`，遇 stall 按时超时重试。

## 技术栈

- Python 3.11+（`deepagents>=0.5.3` 强约束），`requests`，`python-dotenv`，`langchain` ≥ 1.2.15，`langgraph` ≥ 1.1
- 推荐用 `py -3.11 -m venv .venv311` 建本地虚拟环境；激活后 `pip install -r requirements.txt`
- MinerU 精准解析 API（`https://mineru.net/api/v4/`）—— 仅用于 PDF / docx → markdown
- OpenAI 兼容端点（默认走 `OPENAI_*`，示例小米 MiMo `mimo-v2.5-pro` 评审 / `mimo-v2-flash` haiku tier 含 KMS 分类）；可切 DeepSeek 原生端点
- 不再依赖 Qdrant / podman；移除了 `langchain-qdrant` / `qdrant-client`
