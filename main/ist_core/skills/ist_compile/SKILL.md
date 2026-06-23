---
name: ist_compile
description: "把人工测试用例（脑图 / txt）编译成自动化 case.xlsx 的编排链。一次调用确定性流水线 compile_pipeline 跑完 prep→draft 并发→grade 并发→合并，draft 旁挂三层 Provenance IR、grade 验来源不重 grep。编译新用例时用。"
context: inline
user-invocable: true
source: hand
version: "3"
effort: high
when_to_use: |
  Use when 用户要把人工测试用例（脑图 / txt）编译成自动化 case.xlsx。
  Examples: "把这批脑图编译成 excel"、"编译这个 txt 用例"、"用例编译"、"脑图转 case.xlsx"。
  Trigger keywords: 编译用例, 脑图转excel, txt转excel, 用例编译, provenance编译, 闭环编译。
  SKIP when: 只查一条 CLI 回显用 dev_probe；对已编译 excel 上机验证走 ist_verify。
---

# 编译编排

把人工用例编译成自动化 case.xlsx。编译流水线（prep→draft→grade→合并）是固定序列，已锁进确定性工具 `compile_pipeline`——你只负责确认版本、对每个脑图调它一次、汇报结果，不自己拆步调 prep/fanout/merge。

## Steps

### 0. 确认版本
从用户请求提取产品版本（如 APV 10.5）。没写就 `ask_user` 问，别猜——版本决定查哪个手册，错了 draft 查到的文法就是错的。

**Success criteria**: 拿到明确版本号（如 "10.5"）

### 1. 逐脑图调流水线
对每个脑图 txt 调一次：
```
compile_pipeline(mindmap_path="<脑图.txt>", product_version="<版本>", out_name="<脑图名>")
```
工具内部确定性跑完：解析 manifest → 每个 case 独立流水线（draft 产 provenance → grade 验 provenance → CUT 带反馈重做 ≤3 轮）→ N case 并发且**无屏障**（case A 在 grade 时 case B 还能 draft，不必等全部 draft 完才开 grade）→ grade-PASS 合并成一个 excel。命令/断言全由 draft fork 现场查（零硬编码）。

**Success criteria**: 每个脑图返回 done 数 + excel 路径
**Rules**: 多脑图逐个调（每脑图一次），不要一次喂多个；不要自己调 compile_prep / compile_fanout / compile_emit_merged——那是流水线内部的事

### 2. 汇报
列出每个脑图产出的 excel 路径 + case 数（done / escalated）。非交互（`infotest -p`）直接报完成；交互模式可问用户是否上机验证（`ist_verify` 四层归因 + 闭环写回）。

**Success criteria**: 每脑图一行（excel 路径 + done/escalated 数）

## 红线
- 上机解耦：本 skill 只产 excel，不调 dev_run_batch / run。上机走 ist_verify。
- 不做意图族摊销/族骨架（实测负收益，论文证明骨架层无稳健收益、收益在 grounding）。
- escalated（≤3 轮仍 CUT）如实上报，不拿弱产物充数。
