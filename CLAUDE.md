# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 语言要求

所有回复必须使用中文。

**语言分层（2026-07-09 用户裁决，全仓纪律）**：LLM-facing 一律英文——skill/agent md 正文与 description、brief 信封与指令、probe/门违例反馈、grade_extract note、归因 reason、fork 机读契约；user-facing 一律中文——TUI 显示、ask_user 问询、delivery_report 等交付物、docs/ 文档、给用户的解释；代码注释中文（给维护者）。**例外必须保留中文**：when_to_use 的 Trigger keywords（匹配用户中文输入）、交付给用户的报告模板内容、有代码消费的既有机读令牌（如 `VERDICT:`/`[未在文档直接命中]`——改前先 grep 代码消费）。

## 项目目标

本项目展示名为 **InfoTest Engine**，agent 核心展示名为 **IST-Core**。代码包路径为 `main.ist_core`；LangGraph graph id 与 node 名保留 `qa_agent` 指针以兼容已有外部 API；环境变量统一 `IST_*` 前缀（vendor 专有 key 如 `OPENAI_*` / `DEEPSEEK_*` / `MINERU_*` 不变）。

InfoTest Engine 把技术文档（网络 / IPv6 / HTTP/2 / 网关配置指南等）和测试用例（xlsx）转成 markdown 落地，让 IST-Core agent 用 `fs_read` / `fs_grep` / `fs_ls` / `fs_write` / `fs_edit` 直读直写，配合可切换的 LLM provider（默认走 `OPENAI_*` 通用兼容端点，示例小米 MiMo `mimo-v2.5-pro`；可切 DeepSeek 原生端点）提供测试评审、用例编译与上机验证能力。

**架构原则**：`knowledge/data/orgin/` 经 KMS 分桶后转 markdown 直出；知识消费靠 agent 直读 + Footprint 已验证 CLI 事实树；用例编译走确定性 `compile_*` 工具链，与上机验证（`ist-verify`）解耦。

## 给 Opus 的标准工作准则（证据优先 12 条）

这一节把用户在 900+ 轮对话里反复纠正的思维错误固化成标准动作，每条＝一个实证反例 + 为什么 + 怎么做。相关长期记忆用 `[[名]]` 标注（`kb_memory_search` 或 `memory/` 拉全文）。落地这些动作的可复用 skill：`/investigate`、`/compile-e2e`、`/excel-spotcheck`、`/restart-regen`、`/ship-it`、`/run-tests`、**`/engine-verify-loop`（引擎问题标准处理循环：实证→理论→设计→实现→再实证，每层过对抗——后续引擎问题一律按它走）**，全景见 `docs/CLAUDE_USAGE_GUIDE.md`。

1. **症状反复出现＝根因没找到。** 别叠补丁/兜底/gapfill/全量重跑绕过去——停下，挖到能解释**全部**现象的那一个根因（常在自己的用法/配置里）再动手。实证：footprint 抽取漏命令一路打补丁烧掉一天 token，真根因是 function-calling 没开 strict（`[[footprint-mimo-strict-functioncalling]]`、`[[working-style-evidence-first]]`）。
2. **别猜。** 查不到就找参考实现（如 cc-switch 源码）、vendor 官方文档、web 搜索——用事实说话，不凭想象改代码。
3. **先记录/先看/先确认范围，再动手。** 调查类默认只读、零代码改动，把修法写进报告让用户拍板；大改/上机/全量跑前先确认范围，按 step-by-step 节奏，别自作主张铺开（`[[working-style-evidence-first]]`）。
4. **改代码前先确认问题是不是本次引入的。** git diff / stash 对照给铁证；分清「共性/系统性」与「个案」再谈修复优先级。
5. **给 LLM 原始事实，别喂预消化的关键字信号表。** 设备真实报错直接交给 LLM，别造 E_MARKERS / 裸数字 marker 之类关键字表替它判断（会误伤：裸 "429" 误中 autoid 4291）（`[[transient-error-bare-digit-marker]]`）。
6. **判定用结构化事实，别退化成关键字白名单。** 命令/断言性质读 F 列方法 + found/not_found 算子这类结构化信号，机械闭集从 mirror 源码解析——别 grep 命令文本套关键字白名单（强字典会误杀金标准，GA-CUT 回归即此）（`[[compile-judgment-structural-not-strongdict]]`）。
7. **该上机验证的别离线硬推。** 分清哪类必须上机找实际状态/结果，别自己脑补预期值当验证（`[[verify-loop-convergence-stoploss]]`）。
8. **debug LLM 行为要抓思维链，别猜。** 开思考模式，一条条看 draft/grade 到底怎么想的——不知道思考链去猜，永远不对。
9. **断言期望值溯源脑图/手册，不 observe-then-assert。** 把设备 show 回显照抄成断言期望值＝假验证（项目铁红线）。
10. **判「框架做不到」前先查是不是用错了已有能力。** 先确认不是自己用错（abs_found vs found 教训）再下结论（`[[framework-capability-before-limitation]]`）。
11. **改闸门前先画状态生命周期、核对设计意图。** 门的条件常与远处机制成对（如 frozen 闸配 override 通道）；门挂凭证路不挂编辑路（直改文件会绕过编辑入口门），翻案需行级证据（`[[gate-change-verify-design-intent]]`、`[[gates-on-credential-path-not-edit-path]]`）。
12. **写 prompt/skill 讲事实、按自由度分层。** 陈述现象+后果+为什么，别造术语、别把 ALL-CAPS「必须/绝不」当默认；高自由度给方向信任模型，低自由度才上精确护栏；参考文档只写机制、数据按引用（fs_read mirror 现查）（`[[prompt-facts-not-coined-terms]]`、`[[reference-docs-mechanism-not-data]]`）。

## Claude Team 工作流（cmux claude-teams，2026-07-17 实战定型）

多 agent 协作任务（全量跑批+审计修复轮等）按 `docs/TEAM_WORKFLOW.md` 执行，机制骨架：

- **组建**：六角色 named teammates（Theory/Design/LLM-Eng/Py-Eng/TUI-Eng/Test-Eng——Test-Eng 是唯一行动角色，其余只读审计先行）；任务系统承载工作项与依赖，metadata 锚基线数字（断线不丢）。
- **编排**：侦察→并行审计∥跑批主线→域互斥修复→**批间隙合入窗口**（台账清理→leader 权威 pytest→分域 commit→重启加载→双保险放行令）→下一批实弹验证修复项→行为增强类改动押批后收口批。
- **评审链**（工程改动强制）：Eng 出 diff+测试（附消费点清单）→ **Theory+Design 双专家评审**（理论不变量/设计条款同步+影响面）→ redline-reviewer → **leader 亲跑权威 pytest** → leader commit。验证数字只认 leader 亲跑；成员不 commit；宪法级不变量必须带机器守门测试。
- **核心纪律**（全文十条见 TEAM_WORKFLOW §6）：证据边界声明（"基于 X 确认 Y，Z 未核"）、机读账优先于观察和记忆、工具成功≠落盘（grep 核实再报）、结论冲突先互对证据面再上报、勤落盘抗断线、编造观察=最严重违规（主动自曝+停手是唯一正确自纠）、设计变更须 leader 回执、裁决上呈不替用户决定（memo 格式+执行冻结待确认）。
- **Test-Eng 终检三铁律**：裁决执行链对账（decision→authored→verdict→终局，链断三分判据）、引擎自认异常字段（effective=false 等）零放过、该交付而没交付的比交付了什么更要查。

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

改了 ink/Textual TUI（`main/ist_core/ink/` / `tui/`）后，**优先用 cmux skill 直接读终端 pane 验证**：`cmux read-screen --surface <id>` 实时抓屏，`cmux send` / `cmux send-key` 驱动输入。**不要用后台命令轮询抓屏**——不可靠、易看漏/看错。重启 infotest 若用 `kill`，先 `printf '\033[?1000l\033[?1002l\033[?1003l\033[?1006l'; stty sane; clear` 清鼠标跟踪；更稳的是 Ctrl-C + Ctrl-D 干净退出。编译 fork 步骤明细全量写 `runtime/logs/compile_evidence.<pid>.live.log`（fastlog，按 TUI 进程 PID 命名，用 `ls -t runtime/logs/compile_evidence.*.live.log | head -1` 找当前的），`tail -f` 看过程。**子 agent 卡片显示**（2026-07-06，对标 opencode）：同 stem 的 `.events.jsonl` 双写结构化事件（fork_start/tool/tool_result/fork_end/run_meta/engine_tick/progress），TUI 默认卡片模式——每 fork 一张原地更新卡（spinner+当前工具+完成摘要）、上机心跳同 key 单行原地走秒；引擎聚合走 **footer 最底部常驻行**（快捷键提示行之下，进度条+文字计数：`编译 dongkl · 轮次0 编写 ██████░░ 26/34 · 产出26 编写中1 欠定7 通过0 失败0`，九个 ledger 状态全归属；任一 fork 处于 max 思考深度（升级末轮）时尾挂「最大深度思考中」，卡片标题用「第N次」标 per-case 写轮）；卡片状态在 reducer snapshot 内（ctrl+o/ctrl+t 重放一致）。`IST_FORK_CARDS=0` 整体回退旧平铺 `·` 行。

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
                   编译链：compile_engine_run / compile_prep / compile_fanout / compile_emit / compile_emit_merged
                          / compile_precedent / compile_check_verifiability / compile_expected_hits
                          / submit_attribution
                          / compile_attribute / compile_runtime_slots / compile_runtime_fill
  knowledge/     — kb_footprint / kb_bug_search / kb_memory_search（长期记忆 BM25 拉式检索）
  ask_user/      — ask_user
  skills/        — invoke_skill / agent_define（动态生成 dyn-* 子 agent）
  memory_tool.py — remember
  _shared/       — metadata / env_facts / ablation
```

**工具命名（2026-06-23 收口）**：按能力域命名空间化——`fs_*` / `run_*` / `dev_*` / `compile_*` / `kb_*` + 裸名核心（`ask_user` / `invoke_skill` / `remember`）。`fs_*` 必带前缀以避开 deepagents 屏蔽的原生 `{read_file,ls,glob,grep,write_file,edit_file,execute}`。包名 `main.ist_core` / graph id `qa_agent` / env `IST_*` 冻结。

## Skills（`main/ist_core/skills/`）

| Skill | 类型（执行形态 · 触发方式） | 用途 |
|-------|------|------|
| `test-list-review` | inline · 用户可调 | 测试用例/策略评审（主入口） |
| `ist-compile-engine` | inline · 用户可调 | **V8 编译唯一入口**:一句话跑整条闭环(事件溯源 StateGraph 引擎,断点续跑) |
| `compile-worker` | fork · 内部 | 编译孔:单 case 自由理解编写(引擎 author 节点派发) |
| `compile-attributor` | fork · 内部 | V8 归因孔:上机 fail 读原文判层(+h 位置候选/ask panel),submit_attribution 落盘 |
| `ist-verify` | inline · 用户可调 | 成品 excel 上机验证 + 归因(reflow 派 compile-worker) |
| `device-verify` | inline · 用户可调 | 设备 SSH 只读/配置验证 |
| `config-automation` | inline · 用户可调 | 示例 IP → 环境真实 IP 替换 |
| `config-answer` | inline · 用户可调 | 配置问答 |
| `config-answer-draft` / `config-answer-verifier` | fork · 内部 | 配置问答的起草/复核孔 |
| `review-verifier` | fork · 内部 | 评审验证子流程（独立对抗复核评审草稿） |
| `escalate-when-stuck` | inline · 用户可调 | 连续失败上报 |
| `doc-authoring` / `report-gen` | fork · 用户可调 | 文档撰写 / 报告生成（2026-07 新增,gating 映射已入） |

**类型两维正交**（2026-07-18 Design 裁定，纠正原单列 inline/user-invocable 维度混淆）：**执行形态** `inline`（注入主对话）/ `fork`（独立子 agent 孔）；**触发方式** `用户可调`（`user-invocable:true`，注册为 TUI slash 命令 `/<skill-name>`、进用户菜单）/ `内部`（`user-invocable:false`，仅 LLM 经 invoke_skill 派发、不进用户菜单）。二维独立——`fork · 用户可调`（doc-authoring/report-gen：用户可 slash、执行走 fork）合法。

**资产封装标准**（2026-07-05 对标官方 Agent Skills 规范收口，全景见 `docs/AUDIT_skill_bestpractice_v2.md`（第二轮,覆盖第一轮全部条目））：skill 名一律小写连字符（旧下划线名经 `loader.resolve_skill_dirname` 别名互通，TUI slash 本就互通）；SKILL.md frontmatter 必带 name/description/context（fork 另带 agent），user-invocable 必带 when_to_use；agent 定义（`agents/*.md`）统一 `<role>→<task>→<rules>` XML 骨架（rules 收尾紧邻 brief），frontmatter 必带 tools 白名单；主 agent 系统提示五块 XML（`<role>/<rules>/<workflow>/<tool_guidance>/<env>`，`_prompt.py`）。机器门：`tests/ist_core/skills/test_skill_package_standard.py` + `tests/ist_core/agents/test_prompt_structure.py`（承重锚点保真）。**工具渐进披露**（`middleware/tool_gating.py`，默认开——dongkl 对照轮实测零 gating 异常后翻默认，`IST_TOOL_GATING_ENABLED=0` 关）：基础组常驻，compile_*/submit_*/dev_* 按 invoke_skill 映射或既有使用激活，未知 skill fail-open——基础模式常驻工具 schema 67k→26k 字符。**动态子 agent**：`agent_define` 工具按同一骨架生成 `dyn-*` fork agent（tools ⊆ 注册表、inherit-parent-prompt 强制、runtime/ 落盘仅此一条有闸路径），invoke_skill 单发 / `compile_fanout(skill="dyn-…", briefs_path=…)` 批量派发。

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
- **参考文档只写机制，数据按引用**：框架动作注册表/命令清单/主机方法表是**数据**（随框架版本增长，抄进文档必漂移）；文档写分发机制、语法契约、静默失败模式 + **源码路径**，让 LLM 编写时现查（mirror 在盘上 fs_read 直读）。别把清单内联进 md 替模型思考——违背「LLM 走控制面、数据按引用流」构造（实证 2026-07-05：execute 27 动作分组清单+用途点评被用户拦下）。机械门同理：闭集判定从 mirror 源码解析，不硬编码。
- **引擎不得向 LLM 注入具体命令建议（2026-07-13 用户裁决，两床被跑死的实证）**：引擎能给的只有两类——①**机械可推导**的引用（如 inverse_forms 从 command_inventory 的签名配对现查：`no X` 是 `X` 的逆元，闭合于手册版本、作用域恒等于原命令）②**安全边界禁令**（destructive_commands：`clear config all` 类整机清配置一律拒，属窄桥护栏非知识）。**经验性知识一律走判例层**（设备行为观察入 footprint），由 worker 检索后自主查手册决策。反例：曾在文法层放一条 `suggested_teardown: "clear slb all"`（人写的经验命令），worker 朝"清得更干净"升级成 `clear config all`，93/105 两台设备床被跑死——**给 LLM 一条它不知道边界的命令建议，等于把作用域判断权交出去**。
- **改 prompt 前先有 eval（官方 eval-first）**：把要防的回归固化成可机读断言（如「产出 excel 不含写死的 `Hit:\s+1` / 命中 IP」），改完跑 eval + baseline 对比，别只靠肉眼看一次产物就下结论。

## main 子包结构

| 子包 | 职责 | 模块 |
|------|------|------|
| `main.common`   | 通用工具与外部依赖封装 | paths / env / utils / progress / cli_commands |
| `main.ingest`   | HTML 抓取（Bugzilla / 禅道） | defect_fetch / defect_parse / html_extractors/ |
| `main.ist_core` | IST-Core 对话式 Agent | graph / runner / tui/ / ink/ + agents/ + tools/ + memory/ |
| `main.case_compiler` | 用例编译运行时 | config / env_pool / device_mcp_client / xlsx_emit |

顶层管线模块：

- `main/kms_classifier.py` — orgin 分桶（LLM）
- `main/mineru_batch_export.py` — PDF/docx → markdown
- `main/xlsx_to_markdown.py` — xlsx → GFM 表格
- `main/knowledge_paths.py` — 路径常量 + `source_authority()` 权威度
- `main/function_llm.py` — DashScope chat_completion（kms_classifier + memory dream consolidate 用）
- `main/langchain_env.py` — `environment` 文件 dotenv loader

## 用例编译（`main/case_compiler/` + 编译链 skill）

把人工测试用例（脑图）编译成断言真覆盖目标行为的 `case.xlsx`。

**V8 引擎主路（2026-07-10 一次切换,`main/ist_core/compile_engine_v8/`；V6 包+测试已删,见 DESIGN_v8 §9.5）**：编译闭环 = 事件溯源台账上的一张 LangGraph StateGraph（11 节点三类:[mech] 直调工具 .func / [llm] 孔经 execute_fork_skill / [user] 孔官方 interrupt+Command(resume)；拓扑=prep→bed_gate→author→merge→run→reconcile→attribute→diagnose+三 ask 位,见 DESIGN_v8 §3 现役图），main agent 只调薄工具 `compile_engine_run(mindmap, version)` 一次——床态体检→编写（欠定案 suspended 不产卷不阻塞兄弟案,山穷水尽批末 gather 问询,§14-R4）→合并（凭证门+权威序派生视图）→上机→reconcile 全射入账（verdict 四值 pass/fail/**broken**/not_run,broken 不计签名不烧轮）→归因（机械预判/s₀ 前筛/LLM 只填 undetermined,+h 位置候选）→diagnose 批级裁决→只重编 fail 子集→循环到不动点→终验（ctx=delivery 经同一 reconcile,幂等闸防 livelock）→真 PASS 双写回（先例+footprint 经 device_verified 第二权威源,终验矛盾自动 rollback）。**交付目录**（`workspace/outputs/<批名>/`）一处齐全：主卷 `case.xlsx`（通过）+ `unsuccessful_cases.xlsx`/`unsuccessful_cases.md`（未通过卷与详报）+ 人话 `delivery_report.md`（判定式渲染,零 LLM）+ `engine_report.json` + **`facts.jsonl`**（事件溯源事实流,审计/续跑真理源）；清理按 DESIGN_v8 §11.9 契约——已通过案 per-autoid 目录挪 `delivered/` 存档、未决/挂起案挪 `unfinished/`（跨批续跑输入）、中间件（manifest/last_run/子集卷）删除,closing 交付对账断言防「报告说有盘上没有」。断点续跑:同参数重调即从 checkpoint 继续,已跑设备轮不重烧（run_marker 幂等;checkpoint 只存图游标,业务态以事实流为准,INV-7）。**编译只有 V8 这一条路**（2026-07-07 v5/`compile_pipeline`/grade 闸全删,2026-07-10 V6→V8 切换）。资产包 `skills/ist-compile-engine/SKILL.md`,拓扑门断言图↔SKILL↔NODE_TYPES 三方一致;Studio 可视化经 langgraph.json。设计唯一权威=`docs/DESIGN_v8_engine.md`（+`DESIGN_dongkl_finalization.md` 定稿增补）。

**三层栈数据形态判定表（架构红线,新资产落地前先过此表）**：人定义的→md（frontmatter=YAML 元数据+XML 分节正文）;确定性流程→py（LangGraph 图,节点=纯函数）;机器间传的→JSON（盘上台账,按引用流,整份不进 LLM 上下文）;进 LLM 上下文的→XML 信封;会因场景而异的语义判断→skill（fork）;只有一条正确做法的→tool（py,引擎直调 .func）;**LLM 永远不当胶水**——胶水是图的条件边。机械闭集从 mirror 源码解析不手抄。

**自愈合知识引擎（2026-07-08 P1+P2,回答"新坑是否还要人追加代码"）**：检测/知识按四层封闭——A 层目标系统文法门（17 门,闭合于框架版本）/ 原理层 5 通用检测器（零信息断言·秩亏·出处缺失·引用图·预期冲突,闭合于数学,`grade_extract_script.py` docstring 有映射表）/ 文法层（`knowledge/data/compile_ref/domain_grammar.json`：sdns 对象定义/引用形态、算法分类、动词/语义词表,每条带 provenance;加载器 `main/case_compiler/domain_grammar.py`,新增 dangling-reference 类检查=加 JSON 条目零代码）/ 判例层（footprint 观察,唯一无限增长层,全自动）。**自愈环**：fail/escalated 轮行为观察以 `validity=uncertain`+`observed_under` 语境入库（closing `_ingest_uncertain_observations`,`FOOTPRINT_UNCERTAIN_WRITEBACK=0` 关）→ 渲染层同节点多语境观察自动组头（纯计数触发,不做机械矛盾判定,`footprint_lookup`）→ worker 检索见观察组自主设备实验仲裁（A/B 实证 035570）→ PASS 实证 merger 升级分支就地转 verified（不降级）。坑叙事文案运行时从判例现取（`_closure_case_law_note`）,不写死在 .py。验收器：`tests/ist_core/memory/test_self_healing_loop.py`（自愈演练:响应新坑全程零 .py 变化）+ `scripts/debug/grade_extract_equiv_sweep.py`（改词面/文法后 511 卷事实输出逐卷 diff）。

**编译与上机验证解耦**：编译（引擎）只产出 excel；上机走 `ist-verify`（唯一语义 oracle）。下面的机械门/结构化接口都由引擎节点（`.func`）与两个孔（`compile-worker`/`compile-attributor`）复用。

- **lint 凭证机械门**（A 层强制）：`compile_emit_merged(autoids=…)` 校验每个 autoid 在**当前** case.xlsx 上过 `compile_emit` 的全部机械门——过门时自动落 `outputs/<autoid>/.grade_credential.json`（source=lint、`xlsx_mtime` 精确签名，LLM 手写文件冒充不了），缺失或过期（重编后未重新 emit）拒绝合并。起因：34-case 实跑中长上下文下零凭证直接合并交付——prompt 约束再硬也只是 C 层，必派类事实要代码强制。语义终判在上机（`ist-verify`），不在编译期 LLM 自评。
- **接口结构化（2026-07-03，取证驱动）**：两轮全量运行取证结论——事故全部出在「过程事实只存在于散文里」，据此把**信封/凭证/台账/载荷**结构化、**判断/评审理由/修法方向**保持自由文本。落地：① emit 步骤载荷三通道（`steps` 原生数组首选 / `steps_path` workspace 文件 / `steps_json` 字符串兼容——字符串通道经供应商序列化实证单轮 73% 拖尾解析失败）；`IST_TOOLS_STRICT=1` 可全局开 function-calling strict。② 批量工具入参双收原生数组（`autoids_json`/`briefs_json`/`fills_json`），`dev_run_batch*` 对 autoid 做 xlsx 全集校验（治手抄截断 id 静默误匹配）。③ worker 返回末两行机读尾块（`状态：/产物：`），引擎以落盘文件（`outputs/<autoid>/case.xlsx`）为 produced 事实源。④ 归因结论走 `submit_attribution` 落盘 last_run.json（layer×disposition + evidence 必须原文子串），瞬态跨轮护栏读它；last_run.json 按 autoid merge + `_round`/`_fail_signatures`（不再整文件覆盖）。⑤ 欠定台账 `needs_decision.json`（含 `ordering_sensitive`）+ 用户决策 `user_decision.json`——emit 出口机械核对断言形态与顺序锚（577976 选分布产关系、593516 有序语义静默降级两类跑偏变必崩门）。⑥ 冻结闸门：digest 跨轮同签名 fail 落 `outputs/<autoid>/.frozen.json`，重编必须传 `override_frozen_reason`；`compile_fanout(evidence_from_xlsx=…)` 自动注入 device_context 原文防转述失真。
- **编写 fork**（`compile-worker`，引擎 worker_fanout 孔，隔离消除自生成自评估）：复刻自由理解逻辑、限定单 case；欠定 claim 经 `compile_check_verifiability` 证伪 → `NEEDS_USER_DECISION` 由引擎汇总 `ask_user`（改描述/改过程/改预期）后带决策重派。`compile_precedent` 检索先例、`compile_expected_hits` checker 状态机供 worker 自查。
- **emit 出口结构门**（`emit_xlsx_tool` + `structural_gate`，确定性强制）：
  - **crash-gate**：带 H 的观测步不更新 `result` → 断言前须有「不带 H 的观测步」；捕获比较走 `dig(H=v1)→dig(无H)→check_point(H=v1)`。
  - **found_times 拒绝门**：框架只传 2 参，拒绝 `found_times`。
  - **found→abs_found**：check_point 引用 H 寄存器时自动转字面匹配。
  - **test_env 主机名小写**：`getattr(env, F)` 不转小写。
  - **persistence 掩码**：prefix `24` → 点分 `255.255.255.0`。
- **成品卷 lint**（`structural_gate.lint_xlsx_case`，2026-07-04 取证驱动）：门只放 emit 编辑入口挡不住绕行——orchestrator 曾用 `run_python` 直改 case.xlsx，直改版带「dig(H)后直接断言」上机 39 秒崩整份 pytest（连续两轮）。lint 反解成品卷复用崩溃门全集，另加：autoid 18 位（截断 id 曾混进终卷成 35 case）、断言正则可编译（`[^` 曾进卷）、`+short` 与 status 类断言互斥（211027 两轮 fail 根因）、寄存器引用必先捕获、DNS 单标签 ≤63（994838 三轮 fail 根因）。挂**凭证与合并双卡点**：`compile_emit` 违例即不落 lint 凭证（拒绝产出）、`compile_emit_merged` 合并前逐卷再扫（最后防线，防凭证后直改）。回归：`tests/ist_core/tools/test_xlsx_lint_gates.py`。
- **恒真/恒假断言族必崩门**（2026-07-06，588691 三轮取证驱动，全部从 mirror 源码语义推导）：框架 `found/not_found` 是 `re.DOTALL` **无 MULTILINE**、窗口=命令回显+数据+提示符（`send(cmd)+read_until(prompt)`）——由此机械成立六门进 `check_crash_gates_mandatory`：①`^`/`\A`/`$`/`\Z` 锚必假（found 恒 fail、not_found 恒真假 PASS）；②断言 pattern 在被测窗口来源步的**命令原文**上命中=恒真/恒 fail（588691 round1 卷面即「found 恒真+not_found 恒 fail」双恒形态，三轮修法从未触及）；③零 check_point 卷恒 FAIL（`close()` 对 `success==0` 判 fail）；④I 注入 format 结构坏（裸大括号/命名占位/多占位）崩整卷；⑤H 撞框架执行器名字空间（ast 解析 mirror test_xlsx.py 闭集）；⑥cmd_config 含换行被执行层拍平粘连。capture 引用门同步从 lint 前移进必崩门。存量反扫 325 卷：三域当前 pass 单卷零命中，归档区 3 个历史 PASS 卷携恒真断言（当年 PASS 是假验证）。
- **归因修法生效性闭环**（2026-07-06）：last_run merge 时 fail 记录保留上一轮 `_attribution` 为 `_prev_attribution`（曾整条覆盖丢失）——attributor 对重编后再 fail 先核对「上轮修法上卷了吗/同签名复现了吗」，方向已证伪禁同向再开；`.frozen.json` 重写保留 `overrides` 换法历史。frozen 语义：**frozen≠终态**，是「重编必须换法」标记（emit `override_frozen_reason` 门强制声明），终态=frozen∧轮次封顶——勿改成「frozen 即终态」（override 换法通道会整个死掉）。
- **终验路由与幂等闸**（V6 时代 zhaiyq 实证曾修「终验整卷从未发生」,该修复与测试已随 V6 删除；V8 语义=终验是 ctx=delivery 的 run 经同一 reconcile 入账,高权威自动改写 deliverable 视图,终验幂等闸防 livelock——同卷组成指纹 delivery 裁决在案 ∧ 无待升格 ∧ **组成内无 broken 三态案** 才跳过,broken 断批例外见 DESIGN_v8 §16.4 片3-④,回归 `tests/ist_core/compile_engine_v8/test_delivery_idempotency_gate.py`）。
- **上机互斥**（`dev_run_batch`/`digest`，2026-07-04 取证驱动）：orchestrator 曾同 turn 连发 digest 2-3 次，设备床多 pytest 并发互踩配置、三轮结果报废；且 client 被 Ctrl-C 后设备侧 run 不死，新调用读到**旧执行**的日志（causality 时间戳是照妖镜）。两层防：进程内非阻塞锁（重复调用立即 `run_in_progress` 拒绝）+ deliver 前经跳板机 SSH 探测残留 `pytest.*ist_staging` 进程（有残留默认拒绝，确认弃跑后 `force_clean=True` 清场重跑）。
- **性能双护栏**（2026-07-04 取证：34 卷闭环 mimo 双会话 ↑≈100M token/¥320+，设备侧单日 25 次真实上机、其中约六成是并发重复/崩溃截断/假 fail 触发的无效轮）：
  - **run-identity 绑定**（治假结果→无效修复轮）：staging 目录跨 run 复用，被打断执行的旧日志曾被新 digest 收割成 0/34、1/34 假结果。`dev_run_batch` 在 deliver 后取跳板机 epoch 为基线，`fetch_batch_details(min_epoch=…)` 对每个 `<inner>.txt` stat mtime，早于基线的判 `stale_log`→unknown 不采信（同机时钟比较，无设备 +5h40m 时差问题）。
  - **子集复测**（治上机次数）：修复轮只合并 fail 子集上机（digest 摘要在 fail 占少数时给出带 autoid 列表的节流提示），全过后整卷跑一次做交付确认——框架每 case 前清配置、case 间独立，子集与整卷单 case 行为一致。回归：`tests/ist_core/tools/test_perf_gates.py`。（旧「fresh-PASS grade 短路」护栏随 grade 闸于 2026-07-07 删除——机械等价物=lint 凭证 mtime 新鲜性+pass 卷面锁,DESIGN_v8 §19.8。）
- **独立上机验证** `ist-verify`：对成品 excel 用 `dev_run_batch_digest` 上机（跑批进度实时写 evidence fastlog）。整份 xlsx 单跑 O(N)（deliver+run 一次，超时 `clamp(max(floor, N×45s), 600, 2400)`）。`compile_runtime_fill` 回填 `<RUNTIME>` 断言。**归因（2026-07-02 收缩重写）**：机械预判只认两个协议级事实——`compile_attribute` 返回 **G(^)**（设备语法拒绝标记，上游根因、直接采信）与 `found_times` 等文件级崩溃签名（编译缺陷）；**其余一律 undetermined，device_context 原文交 LLM 归因**（E/V/瞬态/疑似产品缺陷——曾有瞬态/E/G marker 关键字表，实证误归已删，勿加回）。digest 跨轮对照机械点名「连续两轮同签名 fail=冻结同法重编」「上轮瞬态本轮复现=误归」；确定性止损跑完为先，真 PASS 写回 footprint。
- **交付门槛 = 机械 lint + 上机 oracle**（2026-07-04 换源，用户拍板；grade 闸 2026-07-07 删除）：942 对时点配对实证 LLM grade 判 PASS→上机 56% / 判 CUT→53%（判别力 3pp、CUT 重做零增益）——LLM 审 LLM 不构成质量门，故 grade 整条删。emit 过全部机械门即落 lint 凭证（source=lint）可合并；语义终判在上机（`ist-verify`）。连续同签名 fail 走冻结/`escalate-when-stuck`/`ask_user`。
- **历史演进**：V4 计划见 `docs/archive/PLAN_v4_engine.md`（V4→V6→V8,当前引擎设计唯一权威=`docs/DESIGN_v8_engine.md`）。V4 存活至今的资产：provenance 必传门（`IST_PROVENANCE_OPTIONAL=1` 回退）、blocks 组合子（`compile_emit(blocks=…)` 最优先通道）、闭环写回（`compile_writeback` + `compile_footprint_writeback` 双写回，ist-verify 步骤7）、checker 状态机（`compile_expected_hits`）。工程红线：结构化数据一律原生数组/对象通道（字符串通道实证 73% 序列化失败），tools 入参机读校验，prompt 按自由度分层。
- **载荷通道一致性**（2026-07-04 步骤7，跨版本根因收口，见 `docs/REVIEW_payload_channel_gap.md`）：LLM 只走控制面（决策/判断/路由），数据按**引用**流（路径/autoid/凭证）——入参随 N 增长的工具必须有原生数组+workspace 文件双通道（`compile_fanout(briefs_path=…)` 同 emit `steps_path` 样板，围栏 resolve+is_relative_to）；批量出参必须落盘全文+内联只留尾部/摘要（fanout 单项超 2000 字符自动落 `outputs/<autoid>/fanout_<skill>.md`，机读尾块在末尾不受影响）。LLM 上下文不承载 O(N×|payload|) 数据。实证：18-case briefs 内联被序列化截断→被迫逐个派发、并发全失（20min 6 卷）；198 个历史 run-jsonl「截断×55/分批×34/太大×25」跨版本同病。编排纪律（V8 更新）：引擎主路 author 节点逐案构建 brief 单发 fork,不再需要批量通道；`briefs_path` 保留给 `compile_fanout(skill="dyn-*")` 动态子 agent 场景（>6 case 派发仍必走它,briefs 机械拼装、不流经 orchestrator 上下文,DESIGN_v8 §19.8）。
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

- **模型**（2026-07-06 两档收敛）：`IST_MODEL` 主档（全局，思考默认开、effort 默认 high——34-case 实跑对照 max 无更好表现只多烧 token，已降回）/ `IST_FLASH` 省钱档（explore/footprint 提取/dream 等轻任务，同样思考+high）；`IST_EFFORT=max` 全局升思考深度，fork 经 agents md frontmatter `effort:` 按点覆盖；**首败即升深度**（2026-07-09 用户裁决：重编轮 `rounds_used≥1` 一律 max 思考 + `_build_brief` 喂全历史设备回显/逐轮归因/前几次配置卷 `history/case.r{N}.xlsx`——旧「末轮才升」让 R2 普通思考白烧、ask_user 第三轮触发时用户答案已无重生成机会，dongkl 批 11 升级人工实证），footbar 挂「最大深度思考中」；旧 `IST_REVIEW/OPUS/SONNET/HAIKU_MODEL` 已合并（读取兼容保留）；`IST_THINKING=off` 仅调试逃生口
- **流式与守卫**（2026-07-07 fork 翻案）：主 agent + fork **默认流式**（`_resolve_streaming()`）。`ChatOpenAIWithReasoning._stream/_astream` 双守卫防挂死/截断：① **停滞守卫** `_chunk_has_substance`——保活空 chunk 骗得过 httpx 读超时、骗不过它，连续 `IST_LLM_STALL_TIMEOUT`（默认 180s）无实质增量即断流重发（深思考期 reasoning 持续增量不误杀）；② **finish_reason 终止校验**（`IST_LLM_VERIFY_FINISH=0` 关）——流结束却没见终止信号=网关中途断流，零内容安全重发、有内容告警（**抓不了 finish_reason=stop 自截断**，取证确认那类 stop 照来）。fork 06-28 曾强制非流式止血，守卫 07-05 上线后翻回流式（深思考 worker 靠"有真输出就续期"不被固定墙钟误杀）；`IST_LLM_STREAMING=0` 批量回落非流式（并发批量更稳）。
- **fork 墙钟两层**（`resilience.ForkExecutor`；单次墙钟分层非漂移，2026-07-17 裁决）：单次墙钟 `IST_FORK_WALLCLOCK_S`——**通用默认 600**（resilience.py，看门狗硬死线、流式重置不了），**V8 引擎 fanout 特化 900**（compile_engine_v8/_shared.py，26 案并发+深思考实测 600 偏紧，run18 迟到产出 935s 佐证）；+ 重试总墙钟 `IST_FORK_TRANSIENT_WALLCLOCK_S`（默认 1200）；**max 思考自动放宽**为 `IST_FORK_WALLCLOCK_MAX_S`（默认 1200）/ `IST_FORK_TRANSIENT_WALLCLOCK_MAX_S`（默认 2400）+ 单次 LLM `IST_LLM_TIMEOUT_MAX`（默认 600，仅非流式模式生效）。单次 LLM request_timeout `IST_LLM_TIMEOUT`（默认 300）。
- **KMS**：`KMS_PRODUCT_FILES`、`KMS_OUTPUT_BUCKET`、`MINERU_BATCH_SIZE`、`KMS_UPDATE_TIMEOUT_SEC`
- **缺陷库**：`DEFECT_BACKEND`、`DEFECT_ON_DEMAND_ENABLED`、`CAPTCHA_OCR_RETRY`
- **设备 SSH**（`device-verify`）：`APV_DEVICE_IP`、`APV_USERNAME`、`APV_PASSWORD`
- **环境池**：`IST_JUMPHOST_PASS`、`IST_JUMPHOST_HOST`、`IST_ENV_POOL_ENABLED`、`IST_ENV_POOL_HOSTS`
- **企微机器人**（`wecom_bot/`）：`WECOM_TOKEN`、`WECOM_ENCODING_AES_KEY`、`WECOM_CORP_ID`、`WECOM_AGENT_ID`、`WECOM_APP_SECRET`

## 企业微信自建应用机器人（`wecom_bot/`）

FastAPI 中间件，接收企微加密回调 → 调用 IST-Core → 异步推送 Markdown 结果。

### 架构

| 模块 | 职责 |
|------|------|
| `main.py` | FastAPI 路由：GET URL 验证 / POST 消息接收 / health |
| `wxcrypt.py` | 加解密薄封装（委托 `wechatpy.crypto.WeChatCrypto`） |
| `wecom_api.py` | 企微 API 客户端：`requests` 同步获取 token + 推送 Markdown |
| `task_handler.py` | 消息路由 + IST-Core 调用 + 后台任务 + 心跳 + 多轮对话 |

### 消息流程

1. 解密 → `parse_message_xml()` 提取 FromUser/Content
2. `handle_message()` 路由：
   - 帮助/状态/新对话/停止/会话 → 同步秒回
   - 其他 → 异步：回 ack → 后台线程 IST-Core → `requests.post(message/send)` 推送 Markdown
3. 多轮对话：每个用户固定 `thread_id` + `SqliteSaver` 持久化
4. 心跳：每 5 分钟推送进度，`/stop` 用 `ctypes` 注入 SystemExit 强制终止

### 启动

```bash
pip install wechatpy
python -m wecom_bot.main
# systemd: sudo systemctl start wecom-bot
```

### frp 穿透（纯 IP 无域名）

`setup_frp.py` 一键部署：自签证书（CN/SAN 用 `wecom.<IP>.nip.io`）+ 写 frpc.toml + 重启 frpc。
企微后台 URL：`https://wecom.<IP>.nip.io/wecom/callback`

## 企业微信智能机器人 — WebSocket 长连接模式（`wecom_bot_smart/`）

免公网 URL、免 frp——直接通过 WebSocket 长连接对接企微网关，内网即可用。
鉴权只需 Bot ID + Secret，消息体为 JSON 明文，**无** CorpID / EncodingAESKey / 加解密。

### 协议

1. WS 连接 → 发 ``aibot_subscribe{"bot_id","secret"}`` 鉴权
2. 收到 ``aibot_msg_callback`` → 5s 内回 ``aibot_respond_msg(finish=false)`` 占位
3. IST-Core 完成后 → 同一 stream_id 回 ``finish=true``，客户端原位替换
4. 断线指数退避自动重连

### 架构 vs 旧 HTTP 模式

| 维度 | 旧 HTTP（`wecom_bot/`） | 新 WebSocket（`wecom_bot_smart/`） |
|------|----------------------|-------------------------------|
| 连接方式 | 企微主动 POST 回调 | 本机主动 WS 连企微网关 |
| 鉴权 | Token + EncodingAESKey + CorpID | Bot ID + Secret |
| 公网需求 | 需要域名 + frp 穿透 | 无——内网直连 |
| 消息体 | WXBizMsgCrypt 加密 XML | JSON 明文 |
| 回复方式 | `requests.post(message/send)` | 同一 WS 连接 `aibot_respond_msg` |
| 流式 | 不支持 | stream 原位替换（finish=false → true） |
| 并发隔离 | 多线程 + `_active_tasks` | 多线程 + `_task_registry`（按 user_id） |

### 模块

| 模块 | 职责 |
|------|------|
| `wecom_bot_smart/main.py` | 启动入口 |
| `wecom_bot_smart/gateway.py` | WS 长连接 + 鉴权 + IST-Core 调度 + 流式回复 + 任务注册表 |
| `wecom_bot_smart/config.py` | `environment` 加载 |

### 启动

```bash
pip install websocket-client
python -m wecom_bot_smart.main
```

### 关键环境变量

`WECOM_SMART_BOT_ID` / `WECOM_SMART_SECRET` / `WECOM_SMART_GATEWAY_URL`（见 `environment.example` §十三）

## 技术栈

- Python 3.11+（`deepagents>=0.5.3` 强约束），`langchain` ≥ 1.2.15，`langgraph` ≥ 1.1，`textual` TUI + `fastapi` Web Terminal
- MinerU API — PDF / docx → markdown
- OpenAI 兼容端点（默认 `OPENAI_*`，示例小米 MiMo `mimo-v2.5-pro` 评审 / `mimo-v2.5` haiku tier）
- 推荐：`python3.11 -m venv .venv && pip install -r requirements.txt`
