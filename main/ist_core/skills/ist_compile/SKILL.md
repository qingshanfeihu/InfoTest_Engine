---
name: ist_compile
description: "把人工测试用例（脑图 / txt）编译成自动化 case.xlsx 的编排主入口：一次调用确定性流水线 compile_pipeline 跑完解析→草稿→审批→合并打包。当用户要「编译用例」「把脑图/txt 转成 case.xlsx / excel」「用例编译」「编译这批脑图」，或拿到人工脑图用例想生成可上机的自动化 excel 时用。涉及脑图转 excel、txt 转用例、批量编译用例之类的需求都走这里。"
context: inline
user-invocable: true
source: hand
version: "4"
effort: high
when_to_use: |
  Use when 用户要把人工测试用例（脑图 / txt）编译成自动化 case.xlsx。
  Examples: "把这批脑图编译成 excel"、"编译这个 txt 用例"、"用例编译"、"脑图转 case.xlsx"。
  Trigger keywords: 编译用例, 脑图转excel, txt转excel, 用例编译, provenance编译, 闭环编译, case.xlsx。
  SKIP when: 只查一条 CLI 回显用 dev_probe；对已编译 excel 做上机复验走 ist_verify。
---

# 编译编排

## Overview

把人工用例（脑图 / txt）编译成断言真覆盖目标行为的自动化 `case.xlsx`。你是**编排器**：确认版本 → 对每个脑图调一次确定性流水线 `compile_pipeline` → 汇报。

编译序列（prep→draft 并发→grade 并发→合并）是**固定的，已锁进 `compile_pipeline` 工具**——你不自己拆步调 `compile_prep` / `compile_fanout` / `compile_emit_merged`。流水线内部派两个**严格有序**的 fork 子流程，各有自己的流程纪律：

- **`ist_compile_draft`**（生成草稿）：先读 brief 内联的预检索先例/footprint → 缺口才 probe/查 → 再设计 G→E→V 断言。详见 `ist_compile_draft/SKILL.md`。
- **`ist_compile_grade`**（语义审批）：先验 draft 记的来源 → 再判断言覆盖度。详见 `ist_compile_grade/SKILL.md`。

**本 skill 只产 excel，不上机。** 上机复验（采框架真实裁决 + 四层归因 + 回填 `<RUNTIME>`）走独立的 `ist_verify`。

## Quick Start

确认版本后，对每个脑图调一次：

```
compile_pipeline(mindmap_path="<脑图.txt>", product_version="<版本，如 10.5>", out_name="<脑图名>")
```

工具内部确定性跑完：解析 manifest → 每 case 独立流水线（draft 产 provenance → grade 验 provenance → CUT 带反馈重做 ≤3 轮）→ N case 并发**无屏障**（case A 在 grade 时 case B 还能 draft）→ grade-PASS 合并成一个 excel。命令 / 断言全由 draft fork **现场查**（零硬编码）。

## Steps

### 0. 确认版本（先探明，别猜）

从用户请求提取产品版本（如 "10.5"）。

**IMPORTANT**: 没写就 `ask_user` 问，**绝不猜**。版本错 → draft 查错版本手册 → 整批文法全错。版本是 draft 查哪个手册 glob 的唯一依据，宁可多问一句。

**Success criteria**: 拿到明确版本号。

### 1. 逐脑图调流水线

对每个脑图 txt 调一次 `compile_pipeline`（见 Quick Start）。

**Rules**:
- 多脑图**逐个调**（每脑图一次），不要一次喂多个。
- 不自己调 `compile_prep` / `compile_fanout` / `compile_emit_merged`——那是流水线内部的事。

**Success criteria**: 每个脑图返回 done 数 + excel 路径。

### 2. 汇报

每脑图一行：excel 路径 + case 数（done / escalated）。非交互（`infotest -p`）直接报完成；交互模式可问用户是否要 `ist_verify` 上机复验。

**escalated 每条带 `rounds`**（grade 各轮的裁定 + 完整理由 `feedback_full`）。某 autoid 的 CUT 原因即其 `rounds` 末轮的 `feedback_full`；`suspect_spec_conflict=True` 表示 grade 某轮判了 `根因：用例预期冲突`。汇报逐条给出 autoid 及其 CUT 原因。

**Success criteria**: 每脑图一行（excel 路径 + done/escalated 数）；每条 escalated 带原因摘要，疑似预期冲突的带人工核对提示。

## Quick Reference

| 任务 | 怎么做 |
|------|--------|
| 缺版本 | `ask_user` 问，不猜 |
| 编译一个脑图 | `compile_pipeline(mindmap_path, product_version, out_name)` |
| 多脑图 | 逐个调，每脑图一次 |
| 生成草稿的内部流程 | 流水线自动派 `ist_compile_draft`（见其 SKILL.md） |
| 审批断言的内部流程 | 流水线自动派 `ist_compile_grade`（见其 SKILL.md） |
| 上机复验成品 excel | 走 `ist_verify`（本 skill 不上机） |

## Next Steps

- 草稿生成的有序流程（先探设备再设计断言）：见 `ist_compile_draft/SKILL.md`
- 断言审批的有序流程（先验来源再判覆盖）：见 `ist_compile_grade/SKILL.md`
- 成品 excel 上机复验 + 四层归因 + 回填 `<RUNTIME>`：走 `ist_verify`

## 红线

- **上机解耦**：本 skill 只产 excel，不调 `dev_run_batch` / run。上机走 `ist_verify`。
- **不做意图族摊销 / 族骨架**（实测负收益，论文证明骨架层无稳健收益、收益在 grounding）。
- **escalated 如实上报**（≤3 轮仍 CUT），不拿弱产物充数——逐条带 autoid + grade 给的 CUT 原因（汇报细节见 Steps 2 汇报）。
