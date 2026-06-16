---
name: ist_compile_run
description: Deliver a case.xlsx to the jumphost framework, run it on-device, and collect the framework ground-truth verdict (per-checkpoint Success/Fail Num, not just the verdict string). Reports the structured device verdict to the orchestrator; does not edit the case or assess quality. Invoked by ist_compile_batch; takes xlsx path + autoid as $ARGUMENTS.
context: fork
agent: ist-compile-run
user-invocable: false
---

# 上机执行并采集设备真实裁决

把下面这个 case.xlsx 下发到跳转机框架上机执行（qa_run_case），**采集设备与框架的真实裁决**并回报：

- **不以 verdict 字符串为准**——`pass` 不代表断言真覆盖目标行为。看框架真实裁决明细（逐 check_point 的 Success/Fail Num、fail to find/successed to find、dig 是否超时、命中计数实际值）。
- 回报：verdict + 逐 check_point 真实裁决 + 一句覆盖性判定（"断言真覆盖目标行为且通过 / verdict=pass 但未覆盖 / 哪个 check_point 失败"，依据明细而非 verdict 字符串）。
- **不修改产物、不评估质量、不重做**——仅上机执行 + 忠实采集裁决。

## Brief from orchestrator

$ARGUMENTS
