---
name: report-gen
description: 根据测试结果生成结构化报告并保存为企业微信云文档
context: fork
agent: report-generator
user-invocable: true
when_to_use: |
  Use when 用户要求"生成报告"、"创建测试报告"、"输出报告"、"/report"、
  "把结果写成文档"、"保存为文档"、"生成个文档链接"。
  Trigger phrases: 报告, 生成报告, 测试报告, 输出报告, 文档, 写成文档
  SKIP when: 用户只是普通技术问答，没有明确要求生成文档。
effort: medium
---

# Report Generator

根据测试执行结果，生成结构化测试报告并保存为企业微信云文档。

## Inputs

- 测试结果数据（workspace/outputs/ 下的 case.xlsx / engine_report.json / delivery_report.md）
- 用户对话中的测试执行结果
- 用户指定的报告标题或主题（可选）
- 测试任务 ID（可选，用于关联 ArtifactRegistry）

## Workflow

1. **收集数据**
   - 检查 workspace/outputs/ 最近的测试产物
   - 如果有 engine_report.json，读取结构化结果
   - 如果有 delivery_report.md，读取摘要信息
   - 如果有 case.xlsx，用 run_python 读取用例列表和状态
   - 如果上述都没有，从对话历史中提取本轮测试结果

2. **结构化分析**
   - 提取 TestCaseResult 列表（case_id / description / status / evidence）
   - 识别失败用例，从 device_info 和 logs 分析可能根因
   - 生成 summary（1-3 句话概括核心结果）
   - 生成 conclusions（结论列表）
   - 生成 recommendations（建议列表）
   - 识别 defects（缺陷列表）

3. **生成报告**
   - 调用 report_to_doc 工具，传入结构化数据
   - topic 格式：test-report-{YYYY-MM-DD}-{批次名}
   - 如果用户指定了任务 ID 或从测试产物中可提取任务 ID，传入 task_id 参数
   - task_id 关联后，支持后续查询「某测试任务产生的所有结果」
   - 返回文档链接给用户

## Rules

- 报告结论必须基于实际测试数据，不得编造
- status 必须是 PASSED / FAILED / BLOCKED / SKIPPED / ERROR 之一
- evidence 必须来自实际日志或设备回显，不得臆造
- severity 必须基于影响范围判断（critical = 核心功能不可用 / major = 主要功能异常 / minor = 边缘问题 / info = 信息性）
- 如果没有可用的测试数据，告知用户「未找到可用的测试结果，请先执行测试」
- 环境信息从 workspace/outputs/ 的产物中提取，不假设默认值
- 报告 Markdown 总长度不超过 50000 字符（企微文档限制）
