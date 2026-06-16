---
name: ist_compile_grade
description: Independently assess a case.xlsx draft against the requirement, judging whether assertions actually cover the targeted behavior (not merely whether the framework passed) via qa_confidence_score; on a CUT, writes concrete rework guidance. Device verdict is an OPTIONAL input — assessment is assertion-quality based (precedents + manual), does not require on-device run. Read-only, does not generate or run on-device. Invoked by ist_compile_batch; takes draft path + requirement (+ optional device verdict) as $ARGUMENTS.
context: fork
agent: ist-compile-grade
user-invocable: false
---

# 评估断言是否覆盖目标行为

依据下面的[草稿 + 原始需求]（**设备真实裁决可选**），独立判断**断言是否真覆盖需求的目标行为**（而非判断框架是否通过）：

- qa_confidence_score 判分（先用 qa_lookup_pattern 取同类先例、grep `*cli__part*.md` 取手册行为作为依据）。
- 独立核对：需求的核心动态行为，断言中是否有任何一条真覆盖？还是全验静态单点值？
- **审批不依赖上机**：编译产出阶段通常无设备裁决（上机是产出后的独立 ist_verify 环节），此时纯凭需求+draft+先例/手册做静态断言审批。若调用方附带了设备裁决（verify 回流场景），作为额外佐证（命中数值/超时/仅匹配域名判断是否被弱断言绕过），但有没有它都要能给结论。
- 结论：**PASS**（达标且真覆盖）放行；**CUT**（弱/未覆盖）判 CUT + 给**具体重做意见**（哪条弱、为什么、参照哪个先例/手册改成何种形态，具体到可据以修改）。
- **不自评、不修改、不上机**——评估对象是生成子流程的产物，修改属生成子流程。

## Brief from orchestrator

$ARGUMENTS
