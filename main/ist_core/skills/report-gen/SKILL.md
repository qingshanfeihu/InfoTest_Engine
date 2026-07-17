---
name: report-gen
description: Generates a structured test report from APV load-balancer test results (compile/verify artifacts under workspace/outputs/ — case.xlsx / engine_report.json / delivery_report.md) and saves it as a WeCom cloud document via report_to_doc.
context: fork
agent: report-generator
user-invocable: true
when_to_use: |
  Use when 用户要求"生成报告"、"创建测试报告"、"输出报告"、"/report"、
  "把结果写成文档"、"保存为文档"、"生成个文档链接"。
  Trigger keywords: 报告, 生成报告, 测试报告, 输出报告, 文档, 写成文档
  SKIP when: 用户只是普通技术问答，没有明确要求生成文档。
effort: medium
---

# Report Generator

Generate a structured test report from test execution results and save it as a WeCom cloud document.

## Inputs

- Test result data (`case.xlsx` / `engine_report.json` / `delivery_report.md` under `workspace/outputs/`)
- Test execution results from the conversation
- User-specified report title or topic (optional)
- Test task ID (optional, links the report in the ArtifactRegistry)

## Workflow

1. **Collect data**
   - Check the most recent test artifacts under `workspace/outputs/`
   - If `engine_report.json` exists, read the structured results
   - If `delivery_report.md` exists, read the summary
   - If `case.xlsx` exists, read the case list and statuses via `run_python`
   - If none exist, extract this round's test results from the conversation history

2. **Structured analysis**
   - Extract the TestCaseResult list (case_id / description / status / evidence)
   - Identify failed cases; analyze probable root causes from device_info and logs
   - Produce summary (1-3 sentences on the core outcome)
   - Produce conclusions (list)
   - Produce recommendations (list)
   - Identify defects (list)

3. **Generate the report**
   - Call the `report_to_doc` tool with the structured data
   - topic format: `test-report-{YYYY-MM-DD}-{批次名}`
   - If the user gave a task ID (or one is extractable from the artifacts), pass `task_id`
   - A linked task_id enables later queries like "all results produced by test task X"
   - Return the document link to the user

## Rules

- Report conclusions must rest on actual test data — never fabricate
- status must be one of PASSED / FAILED / BLOCKED / SKIPPED / ERROR
- evidence must come from real logs or device echo — never invent
- severity follows impact scope: critical = core function unusable / major = main function abnormal / minor = edge issue / info = informational
- No usable test data → tell the user 「未找到可用的测试结果，请先执行测试」
- Environment info comes from the artifacts under `workspace/outputs/` — never assume defaults
- Report Markdown total length ≤ 50000 characters (WeCom document limit)
