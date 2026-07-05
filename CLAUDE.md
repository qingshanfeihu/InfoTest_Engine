# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 语言要求

所有回复必须使用中文。

## 项目目标

本项目展示名为 **InfoTest Engine**，agent 核心展示名为 **IST-Core**。代码包路径为 `main.ist_core`；LangGraph graph id 与 node 名保留 `qa_agent` 指针以兼容已有外部 API；环境变量统一 `IST_*` 前缀（vendor 专有 key 如 `OPENAI_*` / `DEEPSEEK_*` / `MINERU_*` 不变）。

InfoTest Engine 把技术文档（网络 / IPv6 / HTTP/2 / 网关配置指南等）和测试用例（xlsx）转成 markdown 落地，让 IST-Core agent 用 `fs_read` / `fs_grep` / `fs_ls` / `fs_write` / `fs_edit` 直读直写，配合可切换的 LLM provider（默认走 `OPENAI_*` 通用兼容端点，示例小米 MiMo `mimo-v2.5-pro`；可切 DeepSeek 原生端点）提供测试评审、用例编译与上机验证能力。

**架构原则**：`knowledge/data/orgin/` 经 KMS 分桶后转 markdown 直出；知识消费靠 agent 直读 + Footprint 已验证 CLI 事实树；用例编译走确定性 `compile_*` 工具链，与上机验证（`ist-verify`）解耦。

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

# 回归（venv 在 ~/.venvs/infotest-engine,不在仓库内）
~/.venvs/infotest-engine/bin/python -m pytest tests/ -q        # 全量(含 stub-LLM 链路 e2e + prompt 结构门 + skill 标准包门)
# 旧文档提过 scripts.debug.e2e_cookie_review_v2——该脚本从未入 git 已丢失,勿引用;
# prompt/编排改动的行为验证走 34-case 编译对照轮(cmux 实跑)。
```

## TUI 验证（优先用 cmux skill 直接抓屏，勿走后台）

改了 ink/Textual TUI（`main/ist_core/ink/` / `tui/`）后，**优先用 cmux skill 直接读终端 pane 验证**：`cmux read-screen --surface <id>` 实时抓屏，`cmux send` / `cmux send-key` 驱动输入。**不要用后台命令轮询抓屏**——不可靠、易看漏/看错。重启 infotest 若用 `kill`，先 `printf '\033[?1000l\033[?1002l\033[?1003l\033[?1006l'; stty sane; clear` 清鼠标跟踪；更稳的是 Ctrl-C + Ctrl-D 干净退出。编译 fork 步骤明细全量写 `runtime/logs/compile_evidence.<pid>.live.log`（fastlog，按 TUI 进程 PID 命名，用 `ls -t runtime/logs/compile_evidence.*.live.log | head -1` 找当前的），`tail -f` 看过程，TUI 内只摘要不刷高频明细。

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
                          / compile_precedent / compile_score / compile_check_verifiability / compile_grade_extract
                          / submit_verdict / submit_attribution
                          / compile_attribute / compile_runtime_slots / compile_runtime_fill
  knowledge/     — kb_footprint / kb_bug_search / kb_memory_search（长期记忆 BM25 拉式检索）
  ask_user/      — ask_user
  skills/        — invoke_skill / agent_define（动态生成 dyn-* 子 agent）
  memory_tool.py — remember
  _shared/       — metadata / env_facts / ablation
```

**工具命名（2026-06-23 收口）**：按能力域命名空间化——`fs_*` / `run_*` / `dev_*` / `compile_*` / `kb_*` + 裸名核心（`ask_user` / `invoke_skill` / `remember`）。`fs_*` 必带前缀以避开 deepagents 屏蔽的原生 `{read_file,ls,glob,grep,write_file,edit_file,execute}`。包名 `main.ist_core` / graph id `qa_agent` / env `IST_*` 冻结。

## Skills（`main/ist_core/skills/`）

| Skill | 类型 | 用途 |
|-------|------|------|
| `test-list-review` | user-invocable | 测试用例/策略评审（主入口） |
| `ist-compile` | inline | 脑图 → case.xlsx 编译编排（v5 main-orchestrated；`compile_pipeline` 为 fallback） |
| `compile-worker` | fork | 编译子流程：单 case 自由理解编写（main-orchestrated 主路 worker） |
| `ist-compile-draft` | fork | 编译子流程：先例检索 + emit 草稿（pipeline fallback 路径） |
| `ist-compile-grade` | fork | 编译子流程：断言质量审批 |
| `ist-verify` | user-invocable | 成品 excel 上机验证 + 归因 |
| `device-verify` | user-invocable | 设备 SSH 只读/配置验证 |
| `config-automation` | inline | 示例 IP → 环境真实 IP 替换 |
| `config-answer` | inline | 配置问答 |
| `review-verification` | fork | 评审验证子流程 |
| `escalate-when-stuck` | inline | 连续失败上报 |

user-invocable skill 同时注册为 TUI slash 命令（`/<skill-name>`）。

**资产封装标准**（2026-07-05 对标官方 Agent Skills 规范收口，全景见 `docs/AUDIT_skill_standard_alignment.md`）：skill 名一律小写连字符（旧下划线名经 `loader.resolve_skill_dirname` 别名互通，TUI slash 本就互通）；SKILL.md frontmatter 必带 name/description/context（fork 另带 agent），user-invocable 必带 when_to_use；agent 定义（`agents/*.md`）统一 `<role>→<task>→<rules>` XML 骨架（rules 收尾紧邻 brief），frontmatter 必带 tools 白名单；主 agent 系统提示五块 XML（`<role>/<rules>/<workflow>/<tool_guidance>/<env>`，`_prompt.py`）。机器门：`tests/ist_core/skills/test_skill_package_standard.py` + `tests/ist_core/agents/test_prompt_structure.py`（承重锚点保真）。**工具渐进披露**（`middleware/tool_gating.py`，`IST_TOOL_GATING_ENABLED=1` 开，默认关待对照轮翻默认）：基础组常驻，compile_*/submit_*/dev_* 按 invoke_skill 映射或既有使用激活，未知 skill fail-open——基础模式常驻工具 schema 67k→26k 字符。**动态子 agent**：`agent_define` 工具按同一骨架生成 `dyn-*` fork agent（tools ⊆ 注册表、inherit-parent-prompt 强制、runtime/ 落盘仅此一条有闸路径），invoke_skill 单发 / `compile_fanout(skill="dyn-…", briefs_path=…)` 批量派发。

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

## 用例编译（`main/case_compiler/` + 编译链 skill）

把人工测试用例（脑图）编译成断言真覆盖目标行为的 `case.xlsx`。**走平台正路**：用户在 TUI 让 main agent 编译，main agent 作为编排器派发子流程。**编译入口为 `ist-compile`（v5 起 main-orchestrated）**：main agent 自己当 orchestrator——`compile_prep` 解析脑图→manifest → 逐 case 派 `compile-worker` fork 编写（可批内并发；emit 过全部机械门即落结构凭证）→ 机械探针+抽查核验（`compile_grade_extract`；**不逐 case 派 grade**，见下方「交付门槛」换源条）→ `compile_emit_merged` 合并打包。`compile_pipeline` 保留作 fallback（单条是 N=1 特例）。**编译与上机验证解耦**：编译只产出 excel；上机走 `ist-verify`（唯一语义 oracle）。

- **grade 凭证机械门**（2026-07-03，A 层强制）：`compile_emit_merged(autoids=…)` 校验每个 autoid 在**当前** case.xlsx 上实跑过 grade——`submit_verdict`/`compile_score` 落盘 `outputs/<autoid>/.grade_credential.json`（校验内容 `xlsx_mtime` 精确签名，LLM 手写文件冒充不了），缺失、过期（重编后未重新 grade）、或判定是 CUT 都拒绝合并。起因：34-case 实跑中 main agent 长上下文下把 grade 从 plan 里遗忘、零审批直接合并交付——prompt 约束再硬也只是 C 层，必派类事实要代码强制。
- **接口结构化（2026-07-03，取证驱动）**：两轮全量运行取证结论——事故全部出在「过程事实只存在于散文里」，据此把**信封/凭证/台账/载荷**结构化、**判断/评审理由/修法方向**保持自由文本。落地：① emit 步骤载荷三通道（`steps` 原生数组首选 / `steps_path` workspace 文件 / `steps_json` 字符串兼容——字符串通道经供应商序列化实证单轮 73% 拖尾解析失败）；`IST_TOOLS_STRICT=1` 可全局开 function-calling strict。② 批量工具入参双收原生数组（`autoids_json`/`briefs_json`/`fills_json`），`dev_run_batch*` 对 autoid 做 xlsx 全集校验（治手抄截断 id 静默误匹配）。③ grade 交付走 `submit_verdict` 工具（verdict/root_cause 枚举 + caveats 落盘供 verify 消费 + report_md 自由文本）；worker 返回末两行机读尾块（`状态：/产物：`），orchestrator 以落盘文件为 produced 事实源。④ 归因结论走 `submit_attribution` 落盘 last_run.json（layer×disposition + evidence 必须原文子串），瞬态跨轮护栏读它；last_run.json 按 autoid merge + `_round`/`_fail_signatures`（不再整文件覆盖）。⑤ 欠定台账 `needs_decision.json`（含 `ordering_sensitive`）+ 用户决策 `user_decision.json`——emit 出口机械核对断言形态与顺序锚（577976 选分布产关系、593516 有序语义静默降级两类跑偏变必崩门）。⑥ 冻结闸门：digest 跨轮同签名 fail 落 `outputs/<autoid>/.frozen.json`，重编必须传 `override_frozen_reason`；`compile_fanout(evidence_from_xlsx=…)` 自动注入 device_context 原文防转述失真。
- **编写/审批 fork**（彼此隔离，消除自生成自评估）：
  - `compile-worker`（agent `compile-worker`，main-orchestrated 主路）：复刻 main 的自由理解逻辑、限定单 case；欠定 claim 经 `compile_check_verifiability` 证伪 → `NEEDS_USER_DECISION` 由 orchestrator 汇总一次 `ask_user`（改描述/改过程/改预期）后带决策重派。
  - `ist-compile-draft`（pipeline fallback 路径的编写 fork）：核查前置 → `compile_precedent` 检索先例 → `compile_emit` 生成草稿。
  - `ist-compile-grade`：第一步调 `compile_grade_extract` 探确定性信号 → 验 provenance 来源 → `compile_score` 判分 → **交付调 `submit_verdict`**（判定/根因枚举+caveats+report_md，凭证落盘）。返回末行仍带文本标记 `判定：PASS|CUT`（pipeline fallback 的 `_parse_grade_verdict` 兼容）。
- **emit 出口结构门**（`emit_xlsx_tool` + `structural_gate`，确定性强制）：
  - **crash-gate**：带 H 的观测步不更新 `result` → 断言前须有「不带 H 的观测步」；捕获比较走 `dig(H=v1)→dig(无H)→check_point(H=v1)`。
  - **found_times 拒绝门**：框架只传 2 参，拒绝 `found_times`。
  - **found→abs_found**：check_point 引用 H 寄存器时自动转字面匹配。
  - **test_env 主机名小写**：`getattr(env, F)` 不转小写。
  - **persistence 掩码**：prefix `24` → 点分 `255.255.255.0`。
- **成品卷 lint**（`structural_gate.lint_xlsx_case`，2026-07-04 取证驱动）：门只放 emit 编辑入口挡不住绕行——orchestrator 曾用 `run_python` 直改 case.xlsx，直改版带「dig(H)后直接断言」上机 39 秒崩整份 pytest（连续两轮）。lint 反解成品卷复用崩溃门全集，另加：autoid 18 位（截断 id 曾混进终卷成 35 case）、断言正则可编译（`[^` 曾进卷）、`+short` 与 status 类断言互斥（211027 两轮 fail 根因）、寄存器引用必先捕获、DNS 单标签 ≤63（994838 三轮 fail 根因）。挂**凭证与合并双卡点**：`submit_verdict` 违例拒落 PASS（CUT 放行并把违例并进 caveats）、`compile_score` 违例强制 decision=CUT/lint、`compile_emit_merged` 合并前逐卷再扫（最后防线，防凭证后直改）。回归：`tests/ist_core/tools/test_xlsx_lint_gates.py`。
- **翻案需新证据**（`submit_verdict`）：同一份卷面（xlsx_mtime 未变）已有 PASS 凭证再判 CUT，意见必须含行级引用（rN/row N/行N）——34 卷收口期实证同卷 PASS↔CUT 随审查抽样漂移翻案 5 轮、无一条编译期可修，无行级新证据的翻案被工具拒绝。grade prompt 同步「意见分级」事实：上机才能回答的疑虑（回显格式/计数器行为/轮转起点）写 caveats 不构成 CUT。
- **上机互斥**（`dev_run_batch`/`digest`，2026-07-04 取证驱动）：orchestrator 曾同 turn 连发 digest 2-3 次，设备床多 pytest 并发互踩配置、三轮结果报废；且 client 被 Ctrl-C 后设备侧 run 不死，新调用读到**旧执行**的日志（causality 时间戳是照妖镜）。两层防：进程内非阻塞锁（重复调用立即 `run_in_progress` 拒绝）+ deliver 前经跳板机 SSH 探测残留 `pytest.*ist_staging` 进程（有残留默认拒绝，确认弃跑后 `force_clean=True` 清场重跑）。
- **性能双护栏**（2026-07-04 取证：34 卷闭环 mimo 双会话 ↑≈100M token/¥320+，设备侧单日 25 次真实上机、其中约六成是并发重复/崩溃截断/假 fail 触发的无效轮）：
  - **run-identity 绑定**（治假结果→无效修复轮）：staging 目录跨 run 复用，被打断执行的旧日志曾被新 digest 收割成 0/34、1/34 假结果。`dev_run_batch` 在 deliver 后取跳板机 epoch 为基线，`fetch_batch_details(min_epoch=…)` 对每个 `<inner>.txt` stat mtime，早于基线的判 `stale_log`→unknown 不采信（同机时钟比较，无设备 +5h40m 时差问题）。
  - **fresh-PASS grade 短路**（治 token）：`compile_fanout` 对 grade 类派发默认跳过「凭证新鲜且 PASS」的 case（返回 `SKIPPED_FRESH_PASS` 项）——收口期重复 grade 十余次 ≈5-10M token 零信息增量；卷面改动会使凭证过期自然放行，确有行级新证据传 `force_regrade=True`。
  - **子集复测**（治上机次数）：修复轮只合并 fail 子集上机（digest 摘要在 fail 占少数时给出带 autoid 列表的节流提示），全过后整卷跑一次做交付确认——框架每 case 前清配置、case 间独立，子集与整卷单 case 行为一致。回归：`tests/ist_core/tools/test_perf_gates.py`。
- **独立上机验证** `ist-verify`：对成品 excel 用 `dev_run_batch_digest` 上机（跑批进度实时写 evidence fastlog）。整份 xlsx 单跑 O(N)（deliver+run 一次，超时 `clamp(max(floor, N×45s), 600, 2400)`）。`compile_runtime_fill` 回填 `<RUNTIME>` 断言。**归因（2026-07-02 收缩重写）**：机械预判只认两个协议级事实——`compile_attribute` 返回 **G(^)**（设备语法拒绝标记，上游根因、直接采信）与 `found_times` 等文件级崩溃签名（编译缺陷）；**其余一律 undetermined，device_context 原文交 LLM 归因**（E/V/瞬态/疑似产品缺陷——曾有瞬态/E/G marker 关键字表，实证误归已删，勿加回）。digest 跨轮对照机械点名「连续两轮同签名 fail=冻结同法重编」「上轮瞬态本轮复现=误归」；确定性止损跑完为先，真 PASS 写回 footprint。
- **交付门槛 = 机械 lint + 上机 oracle**（2026-07-04 V4 步骤1 换源，用户拍板）：942 对时点配对实证 grade 判 PASS→上机 56% / 判 CUT→53%（判别力 3pp、CUT 重做零增益）——LLM 审 LLM 不构成质量门。emit 过全部机械门即落结构凭证（source=lint）可合并；语义终判在上机。`ist-compile-grade` 保留两个非主路位置：上机 fail 后语义归因辅助、欠定/新形态升级用户前过滤。`IST_GRADE_MAINPATH=1` 一键恢复旧主路（凭证门只认 source=grade）。连续同签名 fail 走冻结/`escalate-when-stuck`/`ask_user`。
- **V4 引擎计划**：`docs/PLAN_v4_engine.md`（实证驱动：10 项盘上数据调研钉死每步可行性——942 对配对、组合子 round-trip 33/34、参数化句式聚类 14 族、族内骨架重合 45-51%）。步骤 0-5 已全部落地：provenance 必传门（`IST_PROVENANCE_OPTIONAL=1` 回退）、凭证换源、blocks 组合子（`compile_emit(blocks=…)` 最优先通道）、族摊销（`compile_skeleton`）、闭环写回（`compile_writeback` + `compile_footprint_writeback` 双写回，ist-verify 步骤7）、checker 状态机（`compile_expected_hits`）；待验收：34-case 全量对照轮。工程红线：结构化数据一律原生数组/对象通道（字符串通道实证 73% 序列化失败），tools 入参机读校验，prompt 按自由度分层。
- **载荷通道一致性**（2026-07-04 步骤7，跨版本根因收口，见 `docs/REVIEW_payload_channel_gap.md`）：LLM 只走控制面（决策/判断/路由），数据按**引用**流（路径/autoid/凭证）——入参随 N 增长的工具必须有原生数组+workspace 文件双通道（`compile_fanout(briefs_path=…)` 同 emit `steps_path` 样板，围栏 resolve+is_relative_to）；批量出参必须落盘全文+内联只留尾部/摘要（fanout 单项超 2000 字符自动落 `outputs/<autoid>/fanout_<skill>.md`，机读尾块在末尾不受影响）。LLM 上下文不承载 O(N×|payload|) 数据。实证：18-case briefs 内联被序列化截断→被迫逐个派发、并发全失（20min 6 卷）；198 个历史 run-jsonl「截断×55/分批×34/太大×25」跨版本同病。编排纪律：>6 case 派发必走 `briefs_path`，briefs 用 `run_python`/`fs_write` 从 manifest 机械拼装、不流经 orchestrator 上下文。
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

**拉式回忆通道**（2026-07-05，MiMo-Code 对照补齐，见 `docs/RESEARCH_mimocode_backfill.md`）：注入是推、`kb_memory_search` 是拉——memory/ 在文件工具黑名单内 agent 读不到，本工具经 SQLite FTS5+BM25（懒 reconcile、CJK bigram、长数字尾 6 位衍生 token、相对分数地板 0.15×top1）检索并**把正文带回**。**上下文压缩**：deepagents `create_deep_agent` **自动挂**默认摘要中间件（fraction 阈值+撤出历史落 `runtime/conversation_history/` 可回读+溢出兜底）——勿再传自建摘要实例（双摘要）；旧 `summarization_middleware(max_tokens=28000)` 系死导入从未生效（2026-07-05 已删）。摘要之前另有确定性**工具结果剪枝**（`middleware/tool_result_prune.py`，MiMo prune 移植）：旧工具结果保头 160 字符+剪枝标记，最近 2 轮/invoke_skill/ask_user/小于 2k 的豁免，可剪总量 <20k 不动手（不破缓存）；`IST_PRUNE_TOOL_OUTPUTS=0` 关、`IST_PRUNE_PROTECT_CHARS` 调预算（默认 15 万字符）。

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
