---
name: ist_verify
description: "对已编译好的成品 excel（case.xlsx）做独立上机验证：下发到跳转机框架串行上机、采集每个 case 的框架真实裁决（逐 check_point Success/Fail Num、命中计数、dig 是否超时），产出结构化 verify 报告并区分『真实断言失败』与『设备环境瞬态失败（SSH 中断/dig 超时/DNS 解析失败）』。验证与编译解耦——本 skill 只验证已有 excel，不生成不改 case。结果可回流给 ist_compile_batch 重编译真实断言有问题的 case。"
context: inline
user-invocable: true
source: hand
version: "1"
effort: medium
when_to_use: |
  Use when 用户要对**已经编译好的 excel / case.xlsx** 做上机验证、上机复验、跑一遍看结果、确认能不能在设备上跑通。
  Examples: "把 yzg 的 excel 上机验证", "把这个 case.xlsx 上机跑一遍看结果", "验证一下编译好的用例能不能跑通", "对 workspace/outputs/dongkl 的 excel 复验", "上机复验"。
  Trigger keywords: 上机验证, 上机复验, 上机跑, 验证excel, 验证用例, 跑一遍, 复验, 设备验证已编译用例。
  SKIP when: 要**编译/生成**新用例（用 ist_compile_batch）；只查一条 CLI 回显（qa_probe_show）；评审用例文件质量但不上机（test-list-review）。
---

# 上机验证编排：对成品 excel 串行上机，采集真实裁决，区分断言失败 vs 环境失败

把**已编译好的 excel**（脑图级合并 case.xlsx，或单 case.xlsx）下发到跳转机框架上机执行，采集每个 case 的框架真实裁决，产出结构化 verify 报告。**本 skill 不生成、不修改 case**——只对已有产物做上机验证。

## 与编译解耦（为什么独立成 skill）

编译（`ist_compile_batch`）只产出 excel（draft 生成 → grade 断言质量审批 → 合并打包），不上机。上机验证是**独立环节**:
- 上机大面积失败常是**设备环境瞬态**（SSH 会话 case 切换时中断、dig 超时、DNS 解析 NXDOMAIN/SERVFAIL），不该阻塞编译产出。
- 本 skill 把上机结果**如实采集 + 分类**:哪些是真实断言问题（需回流重编译）、哪些是环境瞬态（重跑/修环境即可，不必改 case）。

## 流程

### 1. 定位待验证 excel
- 用户给的 excel 路径（如 `workspace/outputs/yzg/case.xlsx`），或脑图名（→ `workspace/outputs/<脑图名>/case.xlsx`）。
- 确定要验证的 autoid 列表（合并 excel 里的全部 case；或用户指定的子集）。
- 确定 build/版本（从用户请求或 excel 来源推断；缺失且无法推断时 `qa_ask_user`）。

### 2. 串行上机：`qa_run_batch`
```
qa_run_batch(xlsx_path="workspace/outputs/<脑图名>/case.xlsx",
             autoids_json='["<autoid1>","<autoid2>", ...]',
             module="<模块,如sdns>", build="<build>")
```
- **上机必须串行**（框架全局锁 + 设备共享态，并发互相污染）——`qa_run_batch` 内部就是 for 循环，一条接一条。
- 返回每个 case 的 verdict + 框架真实裁决明细（逐 check_point Success/Fail Num、命中计数、dig 超时、SSH 异常等）。
- **不以 verdict 字符串为准**:看真实裁决明细判断断言是否真覆盖目标行为。

### 3. 分类裁决 + 产出 verify 报告
逐 case 把裁决归类（依据真实明细，不依据 verdict 字符串）：
- **真实通过**:框架 pass 且断言真覆盖目标行为（check_point 命中目标动态行为，非仅匹配静态单点）。
- **真实断言失败**:断言写错/未覆盖/期望值错——命令正常执行但断言不命中目标。**这类需回流重编译**（见第 4 步）。
- **环境瞬态失败**:SSH 会话中断（`Socket is closed` / OSError）、dig 超时（`connection timed out`）、DNS 解析失败（NXDOMAIN/SERVFAIL）、device_busy——**这类标注但不回流**（重做 case 也没用，是环境/网络问题，需环境侧排查或换时间重跑）。

报告结构（每 case）:`autoid | verdict | 分类(真通过/断言失败/环境失败) | 关键裁决明细 | 是否建议回流`。

### 4. 输出验证 summary + 询问是否修复（闭环）
1. **输出验证 summary**：总数 / 真通过 / 真实断言失败 / 环境瞬态失败 各几个；逐 case 一行（autoid | verdict | 分类 | 关键裁决明细/具体报错）。**真通过、断言失败、环境失败分开列清,具体报错信息(SSH 中断原文 / dig 超时 / NXDOMAIN / 断言不命中明细)如实贴出**,不含糊。
2. **询问是否修复**：若存在**真实断言失败**的 case,`qa_ask_user`「上机验证发现 N 个 case 断言失败（非环境问题）。是否调用编译流程修复这些 case？」
   - 用户选**是** → `qa_invoke_skill(skill="ist_compile_batch", brief="重编译以下断言失败的 case:<逐 autoid 列出裁决明细 + 应改方向>;只重编译这些,基于上一版改")`,把真实断言失败回流重编译。
   - 用户选**否** → 到此结束,验证报告已交付。
3. **环境瞬态失败的 case 不进修复询问**——它们 case 内容可能没问题,如实列出 + 建议「环境排查或换时间重跑」,不回流（重做 case 没用）。

> 非交互模式（`infotest -p`）：直接输出验证 summary,不阻塞等待 ask_user——修复作为独立步骤由调用方另行发起。

## 约束（红线）
- **只验证不生成/不改**:本 skill 不调 qa_emit_xlsx / qa_compile_fanout(draft) 生成 case；只对已有 excel 上机。生成/改 case 是 ist_compile_batch 的事。
- **上机串行**:只走 `qa_run_batch`（内部 for 循环串行），绝不并发上机。
- **裁决 = 框架 ground truth**:以逐 check_point 真实明细为准，不信 verdict 字符串。
- **如实分类不救场**:断言失败就是断言失败，环境失败就标环境失败，不把环境失败粉饰成"已通过"，也不把断言失败甩锅给环境。分类依据是裁决明细里的具体错误特征。
- **零硬编码命令**:本 skill 不产任何设备命令——只下发已有 excel、采集裁决、分类。
