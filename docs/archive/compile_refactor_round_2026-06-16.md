# 编译流水线重构 + 端到端实证（2026-06-16 一轮汇总）

> ⚠️ **历史存档（2026-07-17 归档,team4 docs 整编）**：单轮重构记录(v3 时代)。事实存档不删,现状勿引本文。

> 本文档汇总本轮（2026-06-16）对用例编译流水线的全部改动、调研过程、真实运行数据与结论，供代码提交参考。所有数据来自真实运行（checkpoint / stream 日志 / 跳转机框架日志 / grade fork 重跑），非记忆。

## 一、本轮做了什么（一句话）

1. **入口统一**：删除 `ist_compile_orchestrate`，`ist_compile_batch` 成为唯一编译入口（单条/批量都走它，N=1 是特例）。
2. **编译与上机验证解耦**：编译链只产 excel（draft→grade 审批→merged），不上机；新增独立 `ist_verify` skill 做上机验证；两者用 ask_user 在交互层串成闭环。
3. **可观测性补强**：fork 子 agent 加 `fork_trace.log`；CLISink 修复 tool_result output 被 300 字符截断的 bug。
4. **端到端实证**：合并 yzg 26 case → 直连框架跑（不走 ist-core）→ 审计 grade 判分 vs 框架实跑。

## 二、根因链（为什么要这轮重构）

通过解 `ist_core.sqlite` checkpoint + stream 日志，实证了原架构的失败链（详见 `memory/compile-3txt-run-observation.md`）：

1. **入口选错**：`infotest -p "把3个txt转excel"` 时，主 agent 命中 `ist_compile_orchestrate`（单条编排器）的触发词 `txt转excel/脑图转excel` 即停（#1 reasoning_content 逐字为证），没比对 `ist_compile_batch`。两个 skill 触发词高度重叠，batch 是 orchestrate 的子集。
2. **单条编排器被喂批量**：`invoke_skill(ist_compile_draft, brief="将dongkl的34个用例编译成excel")`。
3. **draft 硬扛 34 条**：单步 reasoning 2.8 万字符，context 从 2万涨到 7.6万 token。
4. **产物粒度全错**：33 个独立 `<autoid>/case.xlsx`，用户要 3 个脑图级 excel。
5. **后续暴露**：即使入口修对走 batch，原"双绿才 merged"设计把"上机通过"当成"进 excel"硬前置 → 环境瞬态 fail（SSH/dig/DNS）→ 大批 case escalated → 出不了 excel。

## 三、代码改动清单

### 入口统一（删 orchestrate）
- **删** `main/ist_core/skills/ist_compile_orchestrate/SKILL.md`（整目录）
- `main/ist_core/skills/ist_compile_batch/SKILL.md`：描述/触发词吸收 orchestrate 全部词，覆盖单条+批量；version 1→2
- `main/ist_core/skills/ist_compile_{draft,run,grade}/SKILL.md`：`Invoked by ist_compile_orchestrate` → `ist_compile_batch`
- `main/ist_core/agents/_prompt.py`：删"单条 vs 批量"二分，统一引导编译任务走 `ist_compile_batch`
- `main/ist_core/middleware/per_turn_skill_reminder.py`：`_LISTING_PRIORITY` 删 orchestrate 项

### 编译/上机解耦
- `ist_compile_batch/SKILL.md`：流程改 `prep→fanout-draft→fanout-grade(审批)→grade-PASS即merged出excel`，run 移出编译链；判定改 grade-PASS 即交付（不再要求上机 pass）；第4步明确"部分PASS部分CUT是常态、自主决策不问用户"（修非交互 ask_user 空转）
- `main/ist_core/skills/ist_compile_grade/SKILL.md` + `main/ist_core/agents/ist-compile-grade.md`：device verdict 改可选输入，支持无上机静态断言审批
- **新增** `main/ist_core/skills/ist_verify/SKILL.md`：独立 inline+user-invocable skill，对成品 excel 用 `dev_run_batch` 串行上机、采集真实裁决、区分"真实断言失败"vs"环境瞬态失败"；末尾 ask_user 闭环（修复失败回流重编译）
- `_prompt.py` + `_LISTING_PRIORITY`：加 ist_verify 引导；batch 触发词移除"上机验证"（归 ist_verify，消除新触发词冲突）

### 可观测性
- `main/ist_core/skills/loader.py`：加 `_summarize_fork_messages`（统计 fork 内部 ai_rounds/tool_results/逐工具调用次数）+ `_trace_fork`（落 `runtime/logs/fork_trace.log`），接在 `execute_fork_skill` 的 invoke 前后；env `IST_FORK_TRACE_LOG`
- `main/ist_core/sinks/cli_sink.py`：修 verbose 分支 `json.dumps(extra)[:300]` 把 tool_result output 截断的 bug——output 单独拎出用 `_OUTPUT_CAP`（默认 20000，env `IST_CLI_OUTPUT_CAP`）完整打印

### 文档
- `CLAUDE.md`、`docs/batch_compile_architecture.md`、`docs/case_compile_orchestration.md`：更新解耦后流程
- `docs/skill_progressive_disclosure_fix.md`、`docs/legacy_compile_pipeline_removal.md`：加 orchestrate 已删的历史注记
- **新增** `docs/yzg_grade_vs_run_audit.md`：grade 判分 vs 框架实跑审计报告

### 测试
- `tests/ist_core/middleware/test_per_turn_skill_listing_filter.py`：断言 orchestrate→batch + 新增 verify 解耦回归
- `tests/ist_core/test_event_sinks.py`：新增 CLISink 长 output 不截断回归
- **新增** `tests/ist_core/skills/test_fork_observability.py`：fork trace 3 测试
- **状态**：相关套件 **113 passed**

### 调研脚本（scripts/debug/，一次性，可不进库或单独归档）
- `diag_compile_stream.py`：stream 模式跑单脑图留 reasoning 证据
- `run_yzg_direct.py`：直连框架跑（每 autoid 循环——此为错误跑法，留作记录）
- `run_yzg_correct.py`：正确跑法（deliver 1次+run 1次+读各 case 子日志）
- `regrade_yzg.py`：直接调 grade fork 对 26 case 重判分

## 四、端到端实证数据

### 4.1 入口修复验证（stream 直接证据）
两次运行首个 tool_call 均 `invoke_skill(ist_compile_batch)` → `compile_prep` → 产出 `dongkl/yzg/zhaiyq` 三脑图 manifest（113 case，零命令契约：init_commands/steps 全 null）。**原"选错入口→碎文件"根因已修**。

### 4.2 解耦验证（编译链不上机）
yzg 解耦跑：全程 `run` 类调用（dev_run_case/dev_run_batch/ist_compile_run）= **0**，draft fanout 26/26 全产出，grade 26 审批。编译链确实不被上机阻塞。

### 4.3 合并 + 框架直跑（不走 ist-core）
- **合并**：`compile_emit_merged.func` 把 26 draft 合并 → `workspace/outputs/yzg/case.xlsx`（26 case + 哨兵，65 check_point，round-trip 过）
- **正确跑法实跑**（deliver 1次+run 1次）：框架 state=done，但**只跑前 4 个 case 就整包中断**：655154/173/188 fail（各 S=2 F=2），655203 崩（TypeError），后 22 个 no_log
- **655203 崩溃根因（实证）**：`check_point found "sdns on"` 紧跟无回显的配置命令 → `lib/check_point.py:24 regexp.search(None)` TypeError → **中断整包后续**
- **3 个 fail 模式**：`successed to find sdns listener`（配置断言过）+ `fail to find 172.16.35.231`（dig 无有效响应，172.16.35.231 经核实是框架真实后端 IP，非臆造）

### 4.4 grade 判分审计（26 case 完整理由）
- **12 PASS / 14 CUT**（详见 `docs/yzg_grade_vs_run_audit.md`）
- **更正了"grade 过严"的误判**：担心被误杀的 dig 解析断言 case，grade 全判 PASS；14 个 CUT 大多有手册/先例依据（端口未验、伪断言、递归未验解析、配置存在性拖垮）
- grade 与框架实跑正交：grade PASS 的 case 框架可能因环境 fail，互不矛盾

## 五、待办（本轮发现、未做）

1. **emit 加 check_point 结构校验门**：check_point 前必须有产生输出的命令（show/dig），挡住悬空断言（根治 655203 类崩溃 + 框架整包中断）
2. **grade "最弱拖垮全局"微调**：有强断言覆盖核心行为时，配置存在性前置检查不单独触发 CUT（影响 655248/681556）
3. **dig 解析 fail 归因**：查 172.16.35.231 不命中是环境（后端服务/网络）还是 sdns 设备配置链路未生效——属环境侧
4. **合并 xlsx 跑法**：框架"一个 case 崩中断整包"，需 case 间隔离或先剔除会崩的 case
5. **draft 防 check_point 悬空**：生成阶段约束断言必须紧跟产出命令

## 六、不属于本轮（提交时排除）
- `.gitignore`（加 `knowledge/framework/backups/` 忽略）、`.mcp.json`：早先环境改动，与编译重构无关，单独处理
