---
name: ist-compile-grade
description: "Grade subflow — judge ONLY whether a case.xlsx's V-segment assertions cover the requirement's target behavior, by verifying the draft's Provenance IR instead of re-grepping the manual. The judgment rules live in the subagent system prompt; this task message only frames the case and enforces verify-sources-before-judging ordering. Read-only. Emits a machine-readable verdict line. Invoked by ist-compile with a structured brief as $ARGUMENTS."
context: fork
agent: ist-compile-grade
allowed-tools: compile_grade_extract, compile_score, compile_precedent, submit_verdict, fs_grep, fs_read, run_python
user-invocable: false
---

# 任务：审批一份 case.xlsx 的 V 段断言覆盖度

判断下面 brief 里这份 case.xlsx 的 V 段断言是否真覆盖需求要测的行为。

**怎么判（验 provenance 来源、两类"非弱断言"的判别细则、compile_score、对抗性核对）见你的系统提示词——此处只给任务和一条必须先做的事。**

**CRITICAL：先验来源，再判覆盖。** 在核对完 draft 记在 `case.provenance.json` 的来源之前，不要从零 grep 手册下判定。**为什么**：来源已由 draft 记在 provenance，你的活是**核它**、不是重查（曾出现 grade 去 grep 仓库根目录空转）。

两类**看着像弱断言、实为正确形态**的，不当弱断言砍（判别细则见系统提示词）：`<RUNTIME>`（`device_runtime`）诚实弃权、`found/not_found(寄存器)` 捕获比较断言。

## 硬规则（三段式）

- **禁忌**：**禁止给 observe-then-assert 恒真断言判 PASS。** 即"被测命令根本改不动断言查询的那张表，无论命令成败该断言都恒成立"的假阳性断言。
- **为什么**：恒真假阳性比 escalate 危害**更大**——它带着绿色 PASS 蒙混进 merge、污染交付，让人误以为已覆盖。
  典型形态：被测步骤动的是**运行时状态表**（会话/连接/统计），断言却去 found 一条自己前面配过的**静态配置**——两张不同的表，被测命令根本不动配置表，故无论命令成败该 found 恒成立 = 恒真假断言。
- **正路**（论文 §四 三层分解：覆盖只由 V 段断言判定）：
  1. 只有 **V 段断言**（dig/统计/session 等**行为观测**验业务行为）贡献覆盖；G 段配置存在性检查（show 配置→found 配置）是健全性前置、**不算覆盖**。
  2. 期望值必须**溯源手册/先例**（核 source_ref 真支撑），不许 observe-then-assert 瞎写。
  3. 主动识别"配 X→show X→found X 的配置存在性检查被标 V"= 伪覆盖——先调 `compile_grade_extract` 工具看 `layer_mismatch` / `is_genuine_v_assertion` / case 级 `weak_v_coverage_suspect` / `distribution_coverage_gap_suspect` 信号。

**流程见 [WORKFLOW.md](WORKFLOW.md)**（先跑 extract 探明 → 数据契约 → 互斥分支 A–E（含 C2/C2′ 分布类与 E 预期冲突审查）→ Validation → 机读标记）。

**结论定了，交付走 `submit_verdict` 工具**（judgment 参数化：verdict=PASS|CUT、CUT 附 root_cause=用例预期冲突|可修复、caveats 装上机注意事项、report_md 装完整报告）——凭证由工具落盘，合并门直接认。

**调完工具后，返回的最后一行仍单独成行输出文本标记** `判定：PASS` 或 `判定：CUT`（CUT 前一行 `根因：…`）——pipeline fallback 靠这行解析，双通道并存。

## Brief from orchestrator

$ARGUMENTS
