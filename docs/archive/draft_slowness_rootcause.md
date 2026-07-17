# draft 慢的真根因 + "数据如何帮 LLM" 实证报告

> ⚠️ **历史存档（2026-07-17 归档,team4 docs 整编）**：draft fork 已随 v5 于 2026-07-07 删除。事实存档不删,现状勿引本文。

> 2026-06-16。用 `scripts/debug/trace_draft_roundtrips.py` 单跑一个慢 case(676654 zone forward)的 draft fork,dump 21 轮完整往返(`/tmp/draft_trace_203601753067676654.json`),逐轮分析。结论全部基于真实往返记录 + 手册实际内容核实,非推测。

## 一、实测:单 case draft = 21 轮往返 / 567 秒

工具调用分布:
- **fs_grep: 26 次**(绝对大头)
- fs_read: 6 次
- dev_probe: 4 次
- compile_precedent: 3 次
- kb_footprint: 1 次
- compile_emit: 1 次(第 19 轮才生成)

## 二、逐轮真相:13/21 轮在反复找一条基础命令语法

| 轮次 | 在干什么 | 性质 |
|---|---|---|
| #1-2 | 查 `sdns zone forward` 语法 + probe 设备 | G段检索(正常) |
| #3-5 | 查到 zone forward,转去找 `sdns listener` 语法 | G段检索 |
| **#6-18（13轮）** | **反复 grep 找 `sdns listener` 命令语法,一直找不到** | **检索失败重试（可消除）** |
| #19 | 终于找到 `sdns listener <ip> [port]`,立即 emit | G段命中→生成 |
| #20-21 | 读回 xlsx 验证 | 收尾 |

reasoning 原文佐证(#6-18 一路是):"I still haven't found the sdns listener command syntax"、"I can't find..."、"Let me search more specifically/more broadly"。**这不是语义判断,是检索失败的重试循环。**

## 三、决定性核实:语法在手册里完整存在,是 LLM 找不到

`sdns listener` 语法在 10.5 手册里清清楚楚:
```
10.5_cli__part2_p201-400.md:7395  sdns listener <ip_address> [port]   ← 完整语法,无截断
10.5_cli__part2_p201-400.md:7414  show sdns listener
10.5_cli__part1_p1-200.md:4285    sdns listener
```

**语法在第 7395 行就有,LLM 却 grep 了 13 轮没定位到,最后在 8490 附近才"找到"(还不是最准的 7395)。** 根因:
- `sdns listener` 在手册出现几十处(说明文字、no/clear/show 变体、part1 的命令大表格),grep 命中**大量噪声**,LLM 在几百行上下文里**捞不出那一行干净的 `<ip_address> [port]` 定义**。
- 于是反复换关键词、换 offset、换 glob 试探——13 轮。

而且 `knowledge/framework/mirror/smoke_test/sdns/host_persistence/` 下有**大量现成 .py 先例**用了 sdns listener,LLM 本可直接看用法,却去啃手册了。

## 四、结论:数据能帮 LLM 的是"省检索",不是"替它判断"

之前我对"数据如何帮 LLM"有两次误判,这次实测厘清:

| 误判 | 实测真相 |
|---|---|
| "LLM 往返降不到几次(语义判断省不掉)" | **13/21 轮是检索失败重试,完全可消除**。真语义判断只占少数轮(#1 选结构、#17 想 service ip、#19 emit) |
| "G 段语义判断是大头" | **G 段的大头是基础命令语法检索,而且是失败重试**——不是判断,是"找不到" |

**真正该做的**:把 draft 反复 grep 不到的**命令语法,预先以结构化语法表喂进 brief**——
- 慢的 13 轮全因"在噪声手册里捞不到干净语法"。给它一张 `命令 → 干净语法` 表(`sdns listener <ip> [port]` / `sdns zone forward name <zone> <servers> <view>`),LLM 第 1 轮就有,直接进语义判断 + emit。
- **21 轮 → 约 5 轮**(#1 选骨架结构 + 想 service + emit + 验证)。这才是 88% LLM 往返的真正解法。

这正是论文 **G 段"命令文法确定、可查表"** 的实质——文法是确定的,但现在让 LLM 去**低效手册里现 grep**,而非给它确定的语法表。

## 五、载体:footprint 知识树(已有基础设施,覆盖不全)

- 第 7 轮 LLM 调了 `kb_footprint("sdns zone forward name")` 但返回"无"——**footprint 没覆盖这条命令**。
- footprint(`knowledge/footprints/nodes/*.json`)本就是按 CLI 命令前缀组织的产品事实树(记忆 `project_llm_endpoint_and_memory_subsystem`),设计上正是装"命令语法/行为"的地方。
- **所以方向**:把命令语法表落到 footprint(或类似结构化语法源),让 draft 先查语法表(命中即得)、查不到才 grep 手册(并把这次查到的沉淀进 footprint,下次不用再查)。这与论文 G 段、记忆 `compile-version-manual-binding-gap`(手册无版本锚点)、`mineru-cli-syntax-truncation`(手册命令行被 MinerU 截断)全部呼应。

## 六、与之前跑偏方案的区别

- 不是"确定性组装器全代码化 G 段"(调研证明骨架结构选择是语义,不能硬编码,会重蹈老管线)。
- 不是"prompt 让 draft 优先检索"(指望 LLM 自觉,治标)。
- **而是**:把 LLM **反复检索不到的确定性数据(命令语法)预先备好喂给它**——LLM 仍做语义判断(选骨架结构、填 V 段),但不再为"找一条基础命令语法"耗 13 轮。**数据帮 LLM = 消除其检索短板,不替它判断。**

## 七、待核实/待定(动手前)
- footprint 当前覆盖了哪些命令、缺多少(第7轮实证 zone forward 未覆盖)。
- "命令语法表"是扩 footprint 还是新建结构化语法源——取决于 footprint 的提取链路能否高质量提语法(记忆说 footprint 由 dream consolidate 从对话提取,质量待核)。
- 这个改动是否要进 v2(三层重构的 G 段载体),还是先作为独立的"draft 提速"增量(v1 也受益)——但注意 v1 完全隔离要求。
