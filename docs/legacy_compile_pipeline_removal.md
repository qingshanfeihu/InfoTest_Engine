# 旧用例编译管线全删清单（2026-06-15）

> **后续更新（2026-06-15 同日）**：本文档提到的 `ist_compile_orchestrate` 编排架构已于同日删除，编译入口统一为 `ist_compile_batch`（单条/批量都走它）。下文 `ist_compile_orchestrate` 引用为当时历史。

## 背景
`infotest -p` 全量编译 3 脑图实跑发现：main agent 没命中 `ist_compile_orchestrate` 编排架构，而是走了并存的**旧确定性管线工具**（`qa_extract_test_cases`→`qa_decompose_test_cases`→`qa_generate_test_case_xlsx`+G列填充 skill）。

## 根因
2026-06-14 commit「用例编译重构为 ist_compile 四子流程编排架构」落地了新编排架构，但**旧管线四工具仍常驻绑定在 `main_agent.py:66-69`**，名字直白、零调用成本，LLM 必然优先选它而非绕一层 invoke 编排 skill。重构遗留未清。

## 旧管线的硬伤（实跑实证）
1. **41→1 数据丢失**：extract 识别 dongkl 41 用例，decompose 后 cases 数组只剩 1。
2. **自造模板非框架格式**：`qa_generate_test_case_xlsx` 用 `openpyxl.Workbook()` 造空白簿（test_case_xlsx_generator.py:69），表头是「autoid/优先级/步骤...」，**非框架认的 R28 表头/锚点'自动化ID'**（emit_xlsx 克隆 sdns_listener 模板那套）→ 上机零 check_point。
3. **G 列空壳**：生成的 xlsx 只有步骤骨架，CLI命令/断言期望列全空。
4. **计划无上机**：纯生成管线，从不调 dev_run_case。

## 编排架构独立性（已验证）
`ist_compile_*` skill/agent + loader `_TOOL_REGISTRY` 零依赖旧工具，用的是 `compile_emit`/`dev_run_case`/`compile_score`/`compile_precedent`/`dev_probe`。删旧管线不影响编排架构。

## 删除清单

### 1. main_agent.py 解绑（main/ist_core/agents/main_agent.py）
- 删 import：28-31 行（test_case_extractor / test_case_decomposer / inject_init_and_deps / test_case_xlsx_generator）
- 删绑定：66-69 行（qa_extract_test_cases / qa_decompose_test_cases / qa_inject_init_and_deps / qa_generate_test_case_xlsx）

### 2. 工具文件（main/ist_core/tools/skills/）— 5 个
- test_case_extractor.py（qa_extract_test_cases）
- test_case_decomposer.py（qa_decompose_test_cases，71KB）
- test_case_xlsx_generator.py（qa_generate_test_case_xlsx）
- inject_init_and_deps.py（qa_inject_init_and_deps）
- test_case_fetcher.py（qa_fetch_test_cases，死代码，含硬编码禅道 cookie）

### 3. skill 目录（main/ist_core/skills/）— 4 个
- automated-G-column-filling/
- decompose-test-cases/
- g-column-filler/
- g-column-verify/

### 4. 配套 agent 定义（main/ist_core/agents/）— 2 个
- g-column-filler.md
- g-column-verifier.md

### 5. 连带引用清理
- main/case_compiler/case_extract.py（薄封装 extract_cases，调 qa_extract_test_cases）— 整文件删（无人引用，grep 误报的 main_agent 实为子串匹配）
- scripts/debug/selfchallenge_rr.py — 引用 qa_generate_test_case_xlsx，需清理或删
- main/case_compiler/skill_lib/schema.py:8 — 注释里举例 g-column-filler，改注释去掉指代

## 无连带破坏（已验证）
- skills/__init__.py 未导出旧工具
- tests/ 无针对这四工具的测试
- skill_lib 被 config.py import 的是包本身，与旧管线无关，保留
