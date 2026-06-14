---
name: ist_compile_orchestrate
description: "把人工测试用例编译成上机能跑通、且断言真覆盖目标行为的 case.xlsx。本 skill 是编译流程的编排层：调用方作为编排器，不直接生成/上机/评分，而是依次派发三个 fork 子流程并汇总其反馈——ist_compile_draft(生成 xlsx 草稿)→ist_compile_run(上机执行并采集设备真实裁决)→ist_compile_grade(独立评估断言是否覆盖目标行为)。两路反馈(设备裁决+质量评估)均通过才判定交付；任一不通过则携带反馈派发重做；连续 N 轮不通过则上报。设计目标：消除单 agent 自生成自评估、以及 verdict=pass 但断言未覆盖目标行为的弱断言。"
context: inline
user-invocable: true
source: hand
version: "2"
effort: high
when_to_use: |
  Use 当要把一条人工测试用例(脑图/需求描述)编译成框架能上机执行、且断言真覆盖作者目标行为的 case.xlsx。
  调用方作为编排器统筹整个编译流程(派发生成→上机→评估→重做→上报)，自身不直接生成/上机/评分。
  典型触发：编译/改编单个用例；上机 verdict=pass 但需确认断言真覆盖目标行为；编译动态/时序/分布类
  行为(轮询、会话保持、计数变化)这类「能跑通但断言易退化成弱覆盖」的用例。
  Trigger keywords: 用例编译, 编译自动化, case.xlsx, 上机验证, 断言覆盖, 编排, 派发子流程。
  SKIP when: 只是查看一条 CLI 回显(用 qa_probe_show)。
---

# 编译编排层：派发三个子流程，汇总反馈判定交付

把人工测试用例编译成「上机跑通 **且** 断言真覆盖作者目标行为」的 case.xlsx。**调用方是编排器，不直接生成/上机/评分**——而是派发三个 fork 子流程、汇总其反馈来判定编译是否完成。生成/上机/评分由三个独立 fork 子 agent 承担，彼此隔离，从结构上消除"同一 agent 自生成又自评估"（该缺陷曾导致：单 agent 生成弱断言、自评低分后又自行推翻、最终误判可交付）。

## 三个子流程（均通过 qa_invoke_skill 派发，fork 出独立 fresh 子 agent）

| 子流程 | skill | 职责 | brief 传入 |
|---|---|---|---|
| 生成 | `ist_compile_draft` | 核查前置→检索同类先例→生成 xlsx 草稿（不上机、不自评）| 用例(autoid/模块/步骤/作者期望) + 前置说明；重做时附[上一版草稿+设备裁决+评估意见] |
| 上机 | `ist_compile_run` | 上机执行 + 采集设备真实裁决(framework ground truth) | xlsx 路径 + autoid |
| 评估 | `ist_compile_grade` | 独立评估断言是否覆盖目标行为(qa_confidence_score 判分 + 重做意见) | xlsx 路径 + 原始需求 + 设备真实裁决 |

## 编排流程（每步派发一个子流程，编排器自身不执行）

1. **派发生成**：`qa_invoke_skill(skill="ist_compile_draft", brief="用例autoid=.../模块=.../步骤=.../作者期望=...; 前置说明")`
   → 返回 xlsx 路径 + 该草稿的测试思路简述。

2. **派发上机**：`qa_invoke_skill(skill="ist_compile_run", brief="xlsx_path=...; autoid=...")`
   → 返回 verdict + **设备真实裁决**（逐 check_point Success/Fail Num、命中计数、是否超时、是否仅匹配域名等弱覆盖迹象）。
   **注意：verdict=pass 不等于编译完成**——还需通过评估子流程。

3. **派发评估**：`qa_invoke_skill(skill="ist_compile_grade", brief="xlsx_path=...; 原始需求=...; 设备真实裁决=<上机子流程返回的逐check_point裁决>")`
   → 返回 PASS/CUT + 置信分 + （CUT 时）具体重做意见。

4. **汇总两路反馈判定**（编排器依据反馈判定，不自行裁断）：
   - **上机报"行为已覆盖且通过"(verdict 真通过 + 裁决无弱覆盖) 且 评估报 PASS** → **编译完成，交付**。
   - **任一不通过**（上机报 fail/超时/弱覆盖，或评估 CUT）→ 进第 5 步重做。
   - **不得 self-assign『可交付』**：评估 CUT 后不得推翻其结论宣布交付；上机报告的弱覆盖不得忽略。

5. **携带反馈派发重做**：`qa_invoke_skill(skill="ist_compile_draft", brief="重做：上一版xlsx内容=...; 设备真实裁决=...; 评估重做意见=<评估子流程给出的具体改法>; 据此定向修改，保留上一版正确部分")`
   → 返回新草稿 → 回第 2 步重新上机+评估。

6. **连续 N 轮仍不通过**（建议 N=3）→ 不得提交弱覆盖产物充数，**上报**：qa_invoke_skill(skill="escalate-when-stuck", ...) 或 qa_ask_user（若可用），将"N 轮未通过 + 卡点（设备裁决+评估意见汇总）+ 可能的解决方向"交付人工裁决。

## 约束
- **编排器不直接执行**：不自行调用 qa_emit_xlsx(生成)、qa_run_case(上机)、qa_confidence_score(评估)。三者分别派发 ist_compile_draft/run/grade 子流程。编排器仅负责派发、汇总反馈、判定、派发重做、上报。
- **交付需两路反馈均通过**：设备裁决(行为已覆盖) + 评估(断言覆盖目标行为)，缺一不可。verdict=pass 不足够（能跑通≠覆盖目标行为），置信分高不足够（覆盖目标行为≠设备实跑通过）。
- **不得推翻子流程结论**：评估 CUT、上机弱覆盖报告均为强制反馈，据此重做或上报，不得忽略或推翻后宣布交付。
- **无法编译时如实上报**，不提交弱覆盖产物，不将弱断言写入记忆作为"有效经验"。
