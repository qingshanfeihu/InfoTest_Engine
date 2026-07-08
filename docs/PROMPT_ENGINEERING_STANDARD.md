# IST-Core 提示面构建标准（2026-07-08 定稿）

> 来源：Anthropic 官方《提示最佳实践》《Sonnet 5 提示指南》全类目 × 本仓红线（CLAUDE.md「skill/agent prompt 编写红线」）合成。
> 全类目审计矩阵与逐批落地记录见 plan 归档；本文是**此后新增/修改任何提示面时的验收标准**。
> 机器门：`tests/ist_core/skills/test_skill_package_standard.py` + `tests/ist_core/agents/test_prompt_structure.py` + `tests/ist_core/test_escalation_and_streaming.py`（brief 布局）。

## 一、消息布局（官方长上下文实践，实测生效）

- **长数据置顶、指令与查询在末**。fork 的 HumanMessage 顺序：`brief 数据区` → `SKILL <instructions>`（任务指令收尾）。brief 内部：首行机读 JSON 信封（卡片/解析契约）→ `<device_evidence>`（最长的在最前，逐轮 `<document label=… attribution=…>`）→ `<prior_config_rolls>` → `<structural_facts>` → `<prior_hypothesis>` → `<intent>` → `<round_task>`（指令）。
- **意图紧邻指令区**＝recency 注意力最高位；上一轮归因假设居中＝响度降级（去劫持的**位置**实现）。
- **本仓 A/B 实证**（035413 末轮重放，同 brief 换布局）：拓扑洞察 5→48、dig 形态质疑 33→42、priority 定势 122→84、修法从"剪掉绑定"变"接通链路"。批2+3 叠加后 48→74 / 42→66。
- 实现锚点：`compile_phase.py::_build_brief`、`loader.py::_render_skill_body`、`batch_tools.py` evidence 注入（插信封首行后）。

## 二、指令写法

- **三要素**：动作 + 期望产出 + 完成判据（新员工测试：没读过上下文的同事能照做）。
- **带 why 的祈使合法**；缺 why 的「必须/绝不」补实证或后果；不发明术语（既有红线 `[[prompt-facts-not-coined-terms]]`）。
- **说要做什么优先于不要做什么**：反例保留时必须配正例（如 desc 列：`<examples>` 三例 + "不是执行工程师的语言——出现即重写"）。
- **自由度分层**（总纲不变）：高自由度给方向与事实，低自由度（机读契约/固定序列）用精确约束。

## 三、示例规范

- **输出形态示例可给、领域判断答案不可给**（红线不变）。形态示例：机读尾块、`<quotes>`→evidence 拷贝、判定尾行、返回骨架。
- 单个包 `<example>`，多个包 `<examples>`；示例值用中性占位（RFC 保留测试域/私网假值/`<占位>`），别用真实设备命令教配置。
- 3-5 个、贴用例、覆盖变化（如尾块给 produced 与 needs_user_decision 两态）。

## 四、XML 词表（全仓统一，勿另造同义标签）

`<inherited_rules>` `<brief_from_caller>` `<instructions>` `<device_evidence>` `<document>` `<prior_config_rolls>` `<structural_facts>` `<prior_hypothesis>` `<intent>` `<round_task>` `<quotes>` `<budget_notice>` `<examples>/<example>` `<run_summary>` `<cross_run_alerts>`。
新增标签先查此表；同一概念自始至终一个词。

## 五、工具 docstring 模板（标杆：`kb_footprint`）

1 句摘要 → **何时用** → **何时不用**（指向替代工具）→ 输出形态迷你示例（须与真实返回逐字同形——凭印象写示例=幻觉，实证 digest 示例第一版就写错）→ Args → Returns。
机制写进 docstring，数据按引用（清单/注册表指向源文件现查，红线 `[[reference-docs-mechanism-not-data]]`）。

## 六、工具调用节奏（fork 经 `<inherited_rules>` 注入，`_prompt.py::_tool_cadence_section`）

- 无依赖查证同轮并发（端点实测：deepseek-v4 默认即返回多 tool_calls，无需 `parallel_tool_calls` 配置——2026-07-08 实测记录）；有依赖才串行；不用占位符猜参数。
- 收到工具结果先评估再行动（interleaved 反思）。
- 只做任务要求的改动（防过度工程）。

## 七、上下文与预算

- **模型窗口 profile**：`_llm.py` 按实测窗口挂 `profile={"max_input_tokens": 1048565}`（deepseek-v4-pro/flash 同值，超限报错原文取证；`IST_MODEL_CTX` 覆盖，0=关）——deepagents 摘要 fraction(0.85/0.10) 由此生效；此前 profile 恒 None，一直走 170k 绝对阈值+keep 6 条的兜底档。
- **轮次预算感知**：fork 的 LoopGuard 带 `recursion_budget`（=IST_FORK_RECURSION_LIMIT，默认 120），75%/90% 起尾挂 `<budget_notice>` 收敛提示——撞 recursion_limit 从"事后 escalate"变"临限有感知"。无状态设计（中间件实例被并发 fork 共享，不能存 per-run 状态）。
- **缓存前缀稳定**：system 与 SKILL 模板稳定；逐轮变动内容集中 Human 尾区；tool_gating 激活单调递增不回收（mimo PR#1207 教训）。

## 七点五、端到端对照轮实证（2026-07-08，批 `CNAME_ipo_pe1`，本标准全量上车后首跑）

| 指标 | dongkl | rerun2 | **pe1（本标准）** |
|---|---|---|---|
| 通过 | 10/13 | 11/13 | 11/13 |
| **R1 首发通过** | 6/13 | 7/13 | **9/13** |
| 终态处置 | 1 escalated＋2 未验证 defect | 2 defect（有据） | **2 escalated（worker 拒产假卷、诚实上报）** |
| 035453 | defect terminal | defect terminal | **末轮 PASS（两批缺陷标签翻案，断言真验 cname1→cname2 切换）** |
| 成本 | —（百万级 token 时代） | ¥36.31 / ↑11.4M | **¥24.29 / ↑7.5M（-33%）** |
| 设备轮次 | 4 | 4 | 4 |

**行为级差异（LangSmith 逐字）**：R2 worker（035608）在归因假设＝"改断言迁就"时**拒绝跟随**——"prior hypothesis correct about the cause, and the intent conflicts with product behavior → `状态：failed`"，宁可上报不产假验证卷（dongkl 时代是盲从三轮）；并自发 `dev_probe` 核实状态语义。quote-first/同批交叉/hedged-defect 纪律全程在思维链中可见。

**暴露的新缺口（570/608 escalated 的根因）**：知识条件性断层——footprint 种子规则写成无条件式（"disable 不抑制别名池"），而 rerun2 035570 R2 实测的**条件行为**（成员配成本地域名时 disable→CNAME ANSWER:0）因"fail 候选永不入库"进不了知识库，正确配置形态对后续轮不可见。待办：定向设备实验钉死条件行为→修种子为条件式；评估"缺陷候选附带的行为观察"入库通道（带 defect-pending 标记而非丢弃）。

## 八、eval-first 流程（prompt 改动的验收）

1. 固化 before 基线：035413 末轮重放 recipe（新进程 `execute_fork_skill('compile-worker', <R3 同款 brief>, effort='max')`，LangSmith 取 reasoning）。
2. 机读判据：拓扑洞察/dig 形态质疑（应≥基线）、定势词频（应≤）、机读尾块一次成、产出卷 lint PASS、修法方向（接通≻规避）。
3. 判据不劣化才合并；agents/SKILL md 改动过 redline-reviewer。
4. 大改后端到端对照轮（cmux 重跑 CNAME 批，基线 rerun2=11/13）。

## 九、明确不做（含理由，防反复议）

- 模型自我认知提示：非 Claude 端点，无模型串生成需求。
- 文档创建提示：delivery_report 由引擎机械代码生成。
- LLM 自查/自评层：942 对实证判别力 3pp，lint/checker 机械门替代。
- 强制周期进度汇报：官方建议移除，本仓从未引入（LoopGuard 软预算提示反向声明"无需汇报"）。
- ALL-CAPS reminder（PerTurnSkillReminder 的 BLOCKING 措辞）立即降级：skills-first 曾因 under-trigger 加硬，降级需对照轮数据支撑——观察项。
