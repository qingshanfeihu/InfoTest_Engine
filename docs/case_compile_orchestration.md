# 人工用例编译流程：四子流程编排架构

> 设计与实现记录。代码中只保留必要的"做什么"注释；设计理念、演进背景、踩过的坑沉淀于此。

## 解决的问题

把人工测试用例（脑图描述）编译成框架能上机执行、且断言真覆盖作者目标行为的 `case.xlsx`。

历史上这条流程由一个外层脚本 `scripts/debug/agent_compile_case.py` 驱动：手动 `agent.stream()` 跑单个 agent、正则捕获 verdict、写结果 json、入库、回流。该方案有三个根本缺陷：

1. **绕过了平台架构**。测试评审等能力走的是 graph + skill + fork subagent 正路（用户在 TUI 对话、main agent 自主完成）；编译用例没有理由用外层脚本，脚本做的"捕获/入库/回流"都应由 skill + 记忆机制承担。
2. **单 agent 自生成又自评估**。编译 skill 曾是 inline，导致同一个 agent 既生成 xlsx 又给自己的产物打分——自评必然不可信（实测：某用例生成弱断言、自评低分后又自行推翻、最终误判可交付）。
3. **质量判据无约束力**。置信判分只是 main agent 手里的一个工具，agent 可无视/推翻其结论。

## 架构：编排器 + 三个 fork 子流程

全部在 main agent 内部、用平台自有的 fork skill + `qa_invoke_skill` 编排完成，不依赖外层脚本。

| 角色 | skill / agent | 职责 |
|---|---|---|
| 编排器 | `ist_compile_orchestrate`（inline，main agent 读取并编排） | 派发子流程、汇总反馈、判定交付、派发重做、上报。不直接生成/上机/评估 |
| 生成 | `ist_compile_draft` / `ist-compile-draft`（fork） | 核查前置→检索先例→`qa_emit_xlsx` 生成草稿。不上机、不自评 |
| 上机 | `ist_compile_run` / `ist-compile-run`（fork） | `qa_run_case` 上机执行 + 采集框架真实裁决（ground truth）。不修改、不评估 |
| 评估 | `ist_compile_grade` / `ist-compile-grade`（fork） | `qa_confidence_score` 判断断言是否覆盖目标行为 + 给重做意见。不生成、不上机 |

### 编排流程

```
派发生成(draft) → 拿到 xlsx 草稿
派发上机(run)   → 拿到设备真实裁决(逐 check_point Success/Fail、命中计数、是否超时)
派发评估(grade) → 拿到 PASS/CUT + 置信分 + 重做意见
汇总两路反馈:
  上机"行为已覆盖且通过" 且 评估 PASS → 交付
  任一不通过 → 携带[设备裁决 + 评估意见]派发重做(draft) → 回到上机
  连续 N 轮(建议3)不通过 → escalate-when-stuck / qa_ask_user 上报
```

### 为什么这样设计

- **生成/上机/评估是三个独立 fork 子 agent，彼此隔离**——从结构上消除"同一 agent 自生成自评估"。这是缺陷 2 的根治。
- **交付需两路反馈均通过**：设备裁决（能否跑通）+ 评估（是否覆盖目标行为）。verdict=pass 不足够（能跑通 ≠ 覆盖目标行为），置信分高不足够（覆盖目标行为 ≠ 设备实跑通过）。
- **评估的 CUT、上机的弱覆盖报告是强制反馈**，编排器不得推翻后宣布交付。这给了质量判据约束力（缺陷 3）。
- 参照范式：`review-verification`（test-list-review 中主 agent 写草稿、fork 独立 verifier 复核，主 agent 不 self-assign 结论）。

## 关键实现点

- **工具注册**：`skills/loader.py` 的 `_TOOL_REGISTRY` 注册了 `qa_emit_xlsx`/`qa_run_case`/`qa_confidence_score`/`qa_lookup_pattern`/`qa_probe_show`，fork 子 agent 才能取用。
- **置信判分** `case_compiler/confidence_f.py`：LLM 依据证据（需求 + 配置上下文 + 同类先例 + 手册行为）判分，非硬编码规则；缺判分模型时 abstain，不以硬规则猜分。`qa_confidence_score` 返回结构化 JSON（overall / decision / 逐 check_point score+reasons）。
- **检索与评估工具** `tools/device/kitchen_tools.py`：`qa_lookup_pattern`（按配置结构相似度检索已验证先例，纯结构距离、无 embedding）、`qa_confidence_score`（判分入口）。

## 演进中清理的历史包袱

- 删除旧确定性管线（pipeline/compiler/anchorer/gates/x1_validate/... 共 22 个 .py）——它们是早期"LLM 填槽 + 静态闸"方案的主体，agent 路径不再使用。
- 删除按特定算法写死的断言重写（rr_stats）及其 skill——属逐用例硬编码，与"通用编译"目标冲突。
- 修复全项目手册路径引用：曾散落 `cli_*_commands.md`（不存在）/ `cli__part*.md`（缺前导通配）等错误路径，导致 agent 检索手册落空、误判"手册无此命令"而遗漏前置配置。统一为 `*cli__part*.md`（匹配各版本命令手册卷）。
- 修复上机读取无超时：`device_mcp_client.call()` 的 `so.read()` 阻塞读，server 端工具卡住会无限挂起；加 900s 读超时兜底。

## 设计比喻说明（仅文档，不进代码）

讨论本架构时曾用"餐厅"比喻辅助厘清角色分工（编排器=统筹、生成=备料下厨、上机=送检取反馈、评估=质检）。该比喻仅用于设计沟通，**不写入生产代码**——代码与 prompt 使用专业术语（编排器 / 草稿生成 / 上机执行 / 质量评估）。

## 入口

走平台正路：用户在 infotest TUI 中要求"把某脑图的某用例编译成 case 并上机验证"，main agent 触发 `ist_compile_orchestrate` 自主完成。不再使用 `scripts/debug/agent_compile_case.py`（已退役）。
