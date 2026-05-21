---
name: test-case-review
description: 评审测试用例文件（xlsx / markdown / Test List），对照产品缺陷/需求和历史测试策略审视用例覆盖与缺口。TRIGGER when 用户输入包含"评审"、"测试用例评审"、"review test cases"、"按之前评审要求"、"测试用例文件"、"Test List"、"BUG-数字"、"xlsx 评审"，或用户提供 knowledge/data/markdown/qa/ 下的 .md 文件并要求检查覆盖、缺口、测试质量。SKIP when 用户只问 CLI 用法、产品规格说明、缺陷详情查询，或要求生成新用例（不评审现有用例）。
allowed-tools: qa_deepagent_read_file qa_deepagent_grep qa_deepagent_ls qa_exec qa_bash web_bug_search qa_sanity_check qa_ask_user
---

# 测试用例评审 Skill

## 评审任务

读产品缺陷/需求 → 全文读用例 → 调 qa_sanity_check → 写四段式报告。
不规定阅读顺序、不强制步骤、不打勾清单。你自己判断怎么读最高效。

## 两条提醒

1. **关注研发修改内容和具体产品实现**——了解当前产品缺陷或者需求时，逐项理解修改了什么参数、行为、选项；不要把修复细节当背景一扫而过
2. **参考以往测试用例和测试策略**——评审前了解以往的测试覆盖和测试方向，看类似功能历史上关注过什么维度，不要跑偏

## 输出格式（四段式）

一、读取到的证据
二、基于证据的判断（覆盖良好的方面 + 存在问题 P0/P1/P2）
三、证据缺口（知识库里没找到但可能影响判断的信息）
四、建议修改汇总（按 P0/P1/P2 分级，每条给出具体位置和修改方向）

## 工具

- `qa_sanity_check` 是机械字面检查工具，必须调一次
- `web_bug_search` 查缺陷/需求详情（BUG-/ZT-/STORY- 等 ticket）
- 最终输出报告时不要再调任何工具（避免 TUI 截断）

## 参考资料

`reference/` 目录是可选参考，按需读取：
- `REVIEW_BASELINE.md` — 评审基线维度
- `product-doc-map.md` — 产品文档索引
- `test-strategy-map.md` — 测试策略索引
- `field-spec.md` — 用例字段规范
- `evidence-discipline.md` — 证据纪律
- `output-format.md` — 输出格式详细说明
