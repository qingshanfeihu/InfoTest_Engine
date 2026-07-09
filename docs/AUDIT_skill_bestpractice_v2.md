# Skill 资产 × 官方 best-practices 逐条对照（第二轮，2026-07-09）

> 基准：platform.claude.com/docs/zh-CN/agents-and-tools/agent-skills/best-practices 全文（含 21 项 checklist）。
> 对象：12 个 SKILL.md + 6 个 agent md + loader + 参考文件（事实清单由只读盘点产出）。
> 第一轮（2026-07-05，AUDIT_skill_standard_alignment.md）已对齐 frontmatter 必填/XML 骨架/命名别名——本轮查其余全部细节。
> 判定：✅合规 / ❌违例（修法在列）/ ⚠建议改 / 📋立项。

## 一、官方条款逐项判定

| # | 官方条款 | 现状事实 | 判定 |
|---|---|---|---|
| 1 | SKILL.md ≤500 行 | 最长 193（test-list-review） | ✅ |
| 2 | 简洁：只写 Claude 不知道的 | 抽查无基础概念解释；实证/教训引用密度高但均为"Claude 不知道的坑" | ✅ |
| 3 | name：小写连字符/非模糊/动名词建议 | 全部小写连字符（动作导向=官方可接受形态）。**例外：agent `Explore` 首字母大写** | ⚠ 统一小写 `explore` |
| 4 | description 第三人称 | **escalate-when-stuck 通篇第二人称**（"当你已…时,调本 skill"）；compile-worker/config-answer-draft 祈使动词开头 | ❌ 修（重写为第三人称功能+触发） |
| 5 | description 功能+何时用 | inline 均有 when_to_use ✅；fork 靠 description ✅（fork 不参与发现，合理差异） | ✅ |
| 6 | description ≤1024 字符/无 XML | 全部合规 | ✅ |
| 7 | **语言一致** | description 10 中文 8 英文；正文中英混排（compile-worker skill 英文 description+中文正文） | ❌ 修——用户既有指示"别用中英文混杂写 prompt"，统一中文（术语/工具名保留英文原文） |
| 8 | 渐进披露：引用距 SKILL.md 一层 | **device-verify 三层链**：SKILL.md→ssh_template.md→apv_ssh_client.py（"参考实现见…"）。注意：skill→skill→agent 是 invoke_skill **执行链**非阅读引用，不算违例 | ❌ 修（SKILL.md 直列两个引用，ssh_template 内链删除） |
| 9 | 参考文件 >100 行加目录 | **EXCEL_FUNCTIONS.md 253 行无 Contents**（被 worker/ist-verify 按需读=官方点名场景）；ssh_template 70 行免 | ❌ 修（加目录节） |
| 10 | 复杂工作流给可复制 checklist | test-list-review 有 ✅；**ist-verify（Steps 1-8）、device-verify（Steps 1-7）无** | ⚠ 补两处 checklist 代码块 |
| 11 | 反馈循环（验证→修→重复） | config-answer(draft→verify→CUT 重做)、ist-verify(归因回流)、emit(门→violation→重 emit) | ✅ |
| 12 | 避免时效性条件 | 全 18 文件 0 处（日期均为实证引用，非条件分支） | ✅ |
| 13 | 术语一致 | **test-list-review 同一流程两套编号**：正文 Step 0-8 vs brief 模板 Phase 1-6（review-verifier 同用 Phase）——LLM 需自行对齐两套坐标 | ❌ 修（统一为 Step，brief 模板同步） |
| 14 | 模板模式（严格/灵活分档） | 机读尾行模板（worker/attributor/verifier）=严格档 ✅；报告模板=灵活档 ✅ | ✅ |
| 15 | 示例模式（输入/输出对） | compile-worker(desc 示例对)、config-answer-draft(输出模板) 有；多数 fork 有尾行模板 | ✅ |
| 16 | 条件工作流（决策点引导） | config-answer 生成/翻译分叉、ist-verify 按层路由 | ✅ |
| 17 | 反模式：Windows 路径/过多选项/魔法数字 | 路径全正斜杠 ✅；无多选项堆砌 ✅；**config-automation 的 python 常量未审**（scripts 类） | ⚠ 脚本常量补注释（低优先） |
| 18 | 明确执行 vs 参考阅读 | 事实清单确认各处语义明确（"emit 前读它"/"运行 …"） | ✅ |
| 19 | 假设包已安装 | ssh_template 用 paramiko（框架环境自带）未声明 | ⚠ 一行声明 |
| 20 | MCP 全限定名 | 不适用（无 MCP 工具引用） | — |
| 21 | **eval-first：每 skill ≥3 评估场景** | 体系级 eval 在（prompt 结构门/skill 标准包门/对照轮/theory_eval DS-1~4 覆盖编译链）；**per-skill 数据驱动评估无**（test-list-review/config-answer/device-verify 零评估集） | 📋 立项（评估格式用官方 JSON 结构，接 theory_eval 目录） |

## 二、事实清单暴露的额外不一致（官方"一致性"精神项）

| 项 | 事实 | 修法 |
|---|---|---|
| skill↔agent 命名错位 ×2 | `config-answer-verify`↔`config-answer-verifier`；`review-verification`↔`review-verifier` | 统一为同名（改 skill 名或 agent 名，取 agent 名为准——skill 目录改名走 loader 别名互通） |
| description 引用不存在的锚点 | config-answer-verify 自称 "Called by config-answer **Step 3.5**"，而 config-answer 正文步骤为 1/2/4（**跳号无 3**） | 修 config-answer 步骤连号（1/2/3/4），verify description 同步 |
| `allowed-tools` 三种值形态 | YAML 列表 / 空格分隔 / 逗号分隔字符串并存（loader 兼容） | 统一 YAML 列表；loader 兼容层保留 |
| `tools` vs `allowed-tools` 双字段名 | agents 用 tools、skills 用 allowed-tools | 保持（两类资产语义不同），在 loader docstring 写明约定 |
| `source: hand`/`version` 仅 3 文件带 | 无消费方 | 删或全量补——查 loader/测试无读取则删（减少漂移面） |
| `inherit-parent-prompt` explore 缺失 | 其余 5 agent 均有 | explore 是通用只读 agent，缺失=不继承（行为正确），补显式 `inherit-parent-prompt: false` 消除歧义 |

## 三、重构执行清单（batch 顺序，每步过机器门）

**B1 机械小修（零语义风险，一次提交）**
1. escalate-when-stuck description 重写第三人称
2. test-list-review Step/Phase 统一 + config-answer 步骤连号 + verify description 锚点修正
3. allowed-tools 统一 YAML 列表；agent `Explore`→`explore`；source/version 处置（查消费后）
4. explore 补 `inherit-parent-prompt: false`；ssh_template paramiko 声明

**B2 结构修（渐进披露）**
5. device-verify 引用链拍平为一层（SKILL.md 直列 ssh_template.md 与 apv_ssh_client.py）
6. EXCEL_FUNCTIONS.md 顶部加 Contents 目录节
7. ist-verify / device-verify 补可复制 checklist 代码块

**B3 语言分层（2026-07-09 用户裁决：内部实现全英文，前端 TUI 中文）**

语言分层准则（LANGUAGE POLICY，一次定死，全仓适用）：
- **LLM-facing = English**：全部 SKILL.md / agent md 正文与 description、`_build_brief` 信封与指令区、
  probe/emit/门违例反馈文案（worker 读）、grade_extract 的 `*_note`、attributor 机械预判 reason、
  fanout 反馈、dev_help 返回、k_signals payload——理由：目标模型英文指令性能与 token 效率更优。
- **User-facing = 中文**：TUI 全部显示（footer/卡片/`sh.emit` 进度行）、ask_user 问询与选项、
  delivery_report.md / unsuccessful_cases.md 交付物、docs/ 文档、异常给用户的解释。
- **代码注释 = 中文**（给维护者，非 prompt，沿现状）。
- **机读契约**（worker 尾块 `状态：/产物：`、`判定：PASS/CUT`）属 LLM↔引擎接口 → 英文化
  （`STATUS:/ARTIFACT:/VERDICT:`），解析器（_TAIL_RE/loader）、TUI 卡片翻译层、测试同步改。

8. 18 个 md 资产全文英文化（语义保真翻译；翻译时顺手修掉该文件在 §一 的 ❌ 项——一步到位）；
   热路径（compile-worker/compile-attributor/ist-compile-engine/ist-verify）人工精翻，
   外围批量翻译+抽查；`tests/ist_core/agents/test_prompt_structure.py` 中文锚点断言同步英文化。

**B4 命名对齐**
9. skill `config-answer-verify`→`config-answer-verifier`、`review-verification`→`review-verifier`（目录改名+调用点 grep 全改+loader 别名兜底）

**B5 引擎内嵌 LLM-facing 文案英文化（随 B3 语言分层）**
10. `_build_brief` 全部 XML 区块文案（round_task/prior_hypothesis/intent note/structural_facts note）
11. emit/lint/必崩门违例文案（worker 收到的 error 串）、probe 反馈注入文案
12. grade_extract `*_note`、fail_attribution reason、fanout 机读反馈
13. 机读尾块契约迁移：`状态：/产物：`→`STATUS:/ARTIFACT:`、`判定：`→`VERDICT:`（worker/attributor/verifier md + _TAIL_RE + loader 解析 + TUI 卡片中文翻译层 + 测试）

**📋 立项（不在本轮）**
14. per-skill 评估集（官方 JSON 格式，落 knowledge/data/theory_eval/skill_evals/，先 test-list-review 与 config-answer 各 3 场景打样）
15. config-automation python 常量自文档化审计

**机器门**：每 batch 跑 `tests/ist_core/skills/test_skill_package_standard.py` + `tests/ist_core/agents/test_prompt_structure.py` + 全量 pytest；B4 另跑 TUI slash 注册验证。
