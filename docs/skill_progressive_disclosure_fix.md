# Skill 渐进披露修复（对标 cc-haha 本地三层机制）

> 2026-06-15。修复「main agent 面对编译脑图用例任务时没命中 `ist_compile_orchestrate`，
> 转而用 qa_exec/qa_bash 手搓」的问题。设计与取舍记录于此，代码只留必要注释。

## 问题与根因

实跑 `infotest -p "把 automatic_case 下 3 个 txt 脑图转成 3 个 excel"`，main agent 连续 25 次
工具调用全是 qa_exec/qa_bash/ls/read_file 自己手搓解析脑图，**一次没调 `ist_compile_orchestrate`**。
（前一轮还先走了已退役的旧管线工具 qa_extract/decompose/generate_test_case_xlsx，已先行删除，
见 `legacy_compile_pipeline_removal.md`。）旧工具删掉后仍不命中编排 skill，根因是 skill 渐进披露
机制本身有五个叠加缺陷（均在 `middleware/per_turn_skill_reminder.py`）：

1. **触发词永远提取不到**：`_parse_skill_frontmatter` 把 `when_to_use` 多行用空格 join 成一行，
   但 `_format_skill_list` 靠 `when.split("\n")` 找 `Trigger keywords:` 行首——join 后无换行，
   永远匹配不到，`[触发: ...]` 从不出现。模型看不到「用例编译/脑图」这类最强匹配信号。
2. **description 截断 + 预算过小**：`_PER_SKILL_DESC_CAP=200`（orchestrate 原 description 304 字
   被腰斩）、`_LISTING_CHAR_BUDGET=1200`（靠后 skill 降级为纯名字无描述）。
3. **`_prompt.py` 的 `_skills_first_section` 无编译路径引导**：只举 config-answer 例。
4. **双路 listing 冲突**：deepagents 原生 SkillsMiddleware（system prompt 末尾，教模型用 read_file
   读 SKILL.md 全文）+ 自研 PerTurnSkillReminder（每轮 HumanMessage，教用 qa_invoke_skill）重复
   注入；且 read_file 已被 `_ToolExclusionMiddleware` 屏蔽 → 原生那套是死指令，还和自研路径矛盾。
5. **`_has_recent_reminder` 去重失效**：判据 `"qa_invoke_skill tool"` 与模板实际串不匹配，恒 False。

## 对标事实：cc-haha 真正生效的是什么

调研 cc-haha（本地 Claude Code 实现）确认：其 `skillSearch/*`（远程/向量/索引/预取）+
`DiscoverSkillsTool` 在开源 build 里**全是 @generated stub，DCE 后不执行**（ant-only 实验功能）。
**真正生效的是纯本地两段式渐进披露**——不需要索引/向量（与本项目「不要 Qdrant」决策一致）：

- L1 metadata listing：`name + description + when_to_use` 拼接，占上下文 **1%（≈8000 字符）**，
  每条 ≤**250 字符**，超预算三级降级（完整→截断→names-only，核心 skill 永不截断）。
- L2 skill body：invoke 时才展开（贵，按需）。
- L3 reference files：靠 `Base directory for this skill: <dir>` 前缀 + body 散文引用 + Read 按需读，
  **无 frontmatter 声明字段**。

关键措辞（cc-haha SkillTool prompt，100% 生效真代码）：
> When a skill matches the user's request, this is a **BLOCKING REQUIREMENT**: invoke the relevant
> Skill tool BEFORE generating any other response about the task.
> NEVER mention a skill without actually calling this tool.

## 修复（已落地）

### P0（直接导致命不中，必修）

| 根因 | 改动 | 文件:位置 |
|---|---|---|
| 1 触发词 | `when_to_use` 改 `"\n".join` 保留换行；提取改正则 `r"trigger\s+(keywords\|phrases)\s*[:：]"`（大小写无关 + 中英冒号） | `per_turn_skill_reminder.py` `_parse_skill_frontmatter` / `_format_skill_list` |
| 2 预算 | `_PER_SKILL_DESC_CAP` 200→**250**、`_LISTING_CHAR_BUDGET` 1200→**8000**（对齐 cc-haha） | `per_turn_skill_reminder.py` 模块常量 |
| 4 双路冲突 | **不挂 deepagents 原生 SkillsMiddleware**（删挂载块，留注释说明）；listing 由自研 per_turn 单路负责 | `main_agent.py` middleware 装配处 |
| 2/5 措辞 | `_SKILL_LISTING_TEMPLATE` 改写为 BLOCKING REQUIREMENT + 「ANY point 不只 first tool_call」+「别用 qa_exec/qa_bash/qa_emit_xlsx 手搓 skill 覆盖的活」 | `per_turn_skill_reminder.py` 模板 |
| 4 description | `ist_compile_orchestrate` description 压到 ~200 字、首句含「脑图/txt/excel/改编」用户词；when_to_use 补 Examples + 扩充 Trigger keywords（脑图转excel/txt转excel） | `skills/ist_compile_orchestrate/SKILL.md` |
| 3 prompt | `_skills_first_section` 补编译路由示例（脑图/txt→excel → qa_invoke_skill orchestrate，禁手搓） | `_prompt.py` |

### P1（质量）

- 删 dead-code `_has_recent_reminder`（根因 5）：reminder 经 wrap_model_call override 不写回 state，
  历史里永远没有 reminder，去重检查对象恒为空 → 该函数从设计上就是死代码。每轮注入是 per_turn 本意。
- 核心 skill 优先排序（`_LISTING_PRIORITY`）：预算紧张时核心 skill 最后被降级。当前 2k<8k 不触发降级，
  纯未来兜底，不改变当前输出。

### 放弃的方案（重要取舍）

设计初稿建议给 fork skill（draft/run/grade/review-verification）加 `disable-model-invocation: true`
或从 listing 隐藏，防主 agent 越权直调。**实测否决**：
- `qa_invoke_skill` 对 `disable-model-invocation: true` 直接 ERROR 拒绝；而这些 fork skill 正是由
  **inline 编排 skill 的 body 引导主 agent 经 qa_invoke_skill 派发**（orchestrate→draft/run/grade、
  test-list-review Step 7→review-verification）。派发者就是主 agent，加 disable 会连合法派发一起切断。
- 从 listing 隐藏（user-invocable:false 不列）同样会让主 agent 按 body 指示调用时「找不到」，
  且破坏 test-list-review 既定协作（`test_disable_model_invocation.py` 明确要求 review-verification
  对模型可见）。
- 结论：**防越权靠编排 skill 的 body 纪律 + prompt 引导（用户说编译→先调 orchestrate→body 指导派发），
  不靠从 listing 隐藏。** fork skill 维持 user-invocable:false（仅不进 TUI /skill 菜单）+ listing 可见。

## L3 reference files / 主动发现工具：YAGNI

cc-haha 开源版这两套都不跑；本项目 skill 仅 10 个，listing 实测 2034 字符 << 8000 预算，全量塞得下，
模型每轮看到完整 name+description+触发词。**明确不做**，避免过度设计。触发条件（满足任一再回头做）：
skill 数 > 30，或单 SKILL.md body > 2000 行需拆分。

## 验证

- 单测：`tests/ist_core/middleware/test_per_turn_skill_listing_filter.py` 新增触发词提取回归
  （`test_trigger_keywords_extracted_into_listing` / `_case_and_colon_variants` /
  `test_real_orchestrate_skill_listing_has_triggers`），防 bug#1 复发。
- 实测 listing：`ist_compile_orchestrate` 渲染 236 字符、含完整触发词、未截断；核心 skill 排前。
- 回归：`tests/ist_core/middleware/` + `tests/ist_core/skills/` 共 41+3 测试全绿；main agent + graph 构建 OK。
- 端到端（待跑）：`infotest -p "编译脑图用例"` 首个 tool_call 应为 qa_invoke_skill(ist_compile_orchestrate)。
