# Claude Code 使用指南（InfoTest Engine）

> 基于对 **906 条历史 prompt（`~/.claude/history.jsonl`）+ 189 个会话记录 + 28 条长期记忆 + 35 篇 docs** 的画像分析（2026-07-07）生成。目的：把反复手打的工作流沉淀成可复用 skill + 可核对的完成标准，并把反复纠正的思维错误固化成 Opus 标准准则。

## 一、你用 Claude 做什么（画像）

主题关键词命中（736 条实质请求里）：`检查95 · skill62 · cmux54 · footprint47 · 用例46 · 修复45 · TUI44 · mimo39 · 上机38`。

| 类别 | 占比信号 | 说明 |
|---|---|---|
| 用例编译 → 上机验证闭环 | 用例46·上机38·脑图27·grade25 | **主战场**：脑图/xlsx 编译成真覆盖行为的 case，上机验证、归因、只重编 fail 子集 |
| 证据驱动根因调查 | 检查95·为什么32·根因7 | 贴 trace 问「为什么/是不是 bug」，**先查后改** |
| TUI/cmux 交互与显示 | cmux54·TUI44·ink15 | cmux 驱动 infotest 实跑 + 修显示 |
| skill/prompt 元工作 | skill62·prompt18 | 反复重写、审查、收口规范 |
| 模型/参数调优 | mimo39·模型32·token25 | provider 切换、思考档、控成本 |

## 二、总是重复做 / 手动重写的（→ 已沉淀为 skill）

| 反复手打的指令 | 出现次数 | 现落为 |
|---|---|---|
| 「清数据→cmux 喂用例完整跑→检查过程+结果→CUT 诚实报原因→通过才提交」 | 逐字 ≥6 | `/compile-e2e` |
| 「只读分析不要改代码。背景…任务:读<file>…写结论报告」 | 近乎同构 5 | `/investigate` |
| 「openpyxl 抽查断言质量:覆盖行为/observe-then-assert/溯源」 | 完整模板 | `/excel-spotcheck` |
| 「清理数据,重启 infotest 重新跑」 | ×15+ | `/restart-regen` |
| 「检查代码→更新文档→验证→提交 main」 | ×8 | `/ship-it` |
| 「less is more skill 六条规范」 | 整段反复粘贴 | 已并入 CLAUDE.md「skill/agent prompt 编写红线」 |

## 三、Skill 索引（何时用哪个）

| 场景 | Skill | 触发 |
|---|---|---|
| 一批用例真机全流程编译+核验+诚实结账 | `compile-e2e` | `/compile-e2e` |
| 只读根因调查、写结论报告、不改代码 | `investigate` | 说「只读分析/调查/写结论报告」或 `/investigate` |
| 抽查 case.xlsx 断言质量 | `excel-spotcheck` | 说「抽查断言质量」或 `/excel-spotcheck` |
| 清数据 + 干净重启 infotest | `restart-regen` | `/restart-regen` |
| 提交仪式（检查+文档+验证+push main） | `ship-it` | `/ship-it` |
| 跑窄测（venv 外 + --ignore） | `run-tests` | `/run-tests` |
| 编译链/prompt 红线评审 | `redline-reviewer`（agent） | 改到编译链/prompt 时 |
| 沙箱/凭据/记忆写入评审 | `security-reviewer`（agent） | 改到 file_tools/memory/沙箱常量时 |

## 四、工作流程目标（Definition of Done）

### 编译一批用例（`/compile-e2e`）
- [ ] **每一份**用例都产出 case.xlsx（不是大部分）
- [ ] CUT/有异议/上机不通过的**逐个诚实给原因**
- [ ] 过程证据看过（`compile_evidence.*.live.log` + `.events.jsonl`），没被 draft/grade 带偏
- [ ] 断言过 `/excel-spotcheck`（无 observe-then-assert、期望值溯源）
- [ ] 1–4 全达标才提交

### 只读调查（`/investigate`）
- [ ] git diff **全程干净**（零代码改动）
- [ ] 根因能**解释全部现象**（不是症状层兜底）
- [ ] 给铁证（file:line / 日志原文 / 先例对照）
- [ ] 结论报告落 `docs/`（DIAG_/RESEARCH_/AUDIT_/REVIEW_）
- [ ] 修法方向**不落地**，交用户拍板

### 提交（`/ship-it`）
- [ ] 改动审过、文档同步、窄测/关键路径验证过
- [ ] commit = 中文 conventional + `——`理由 + 回归测试名 + 遗留
- [ ] commit 草稿给用户看过再 push main

## 五、给 Opus 的标准工作准则

见 **CLAUDE.md「给 Opus 的标准工作准则（证据优先 12 条）」**——把 900+ 轮对话里反复纠正的思维错误固化成标准动作（症状反复=根因没找到 / 别猜 / 先记录再改 / 给 LLM 原始事实不喂关键字表 / 结构化判定不用关键字白名单 / 该上机别离线硬推 / …）。长期记忆全文可用 `kb_memory_search` 拉取。

## 六、维护

这份画像会随使用漂移。**重新生成**：遍历 `~/.claude/history.jsonl` 抽 `.display` 做频率与纠偏分析（grep 否定词 `别/不要/不对/为什么` 抓错误方法），对照 memory/ 更新本文件、各 skill、CLAUDE.md 准则块。
