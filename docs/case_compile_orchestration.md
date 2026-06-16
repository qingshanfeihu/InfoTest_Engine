# 人工用例编译流程：编排架构（编译 + 独立上机验证）

> 设计与实现记录。代码中只保留必要的"做什么"注释；设计理念、演进背景、踩过的坑沉淀于此。
>
> 本文档讲**编译子流程（draft/grade）+ 独立上机验证（ist_verify）的编排设计**。编译入口已统一为 `ist_compile_batch`（2026-06-15 合并：原 `ist_compile_orchestrate` 单条编排器已删除，单条用例是 N=1 特例、走同一批量流程）。批量层（解析 manifest → 分阶段并行调度 → 合并打包）见 [`batch_compile_architecture.md`](batch_compile_architecture.md)。**2026-06-16 编译与上机验证解耦**：编译链只产 excel（不上机），上机验证独立成 `ist_verify`——详见下文架构表。

## 解决的问题

把人工测试用例（脑图描述）编译成框架能上机执行、且断言真覆盖作者目标行为的 `case.xlsx`。

历史上这条流程由一个外层脚本 `scripts/debug/agent_compile_case.py` 驱动：手动 `agent.stream()` 跑单个 agent、正则捕获 verdict、写结果 json、入库、回流。该方案有三个根本缺陷：

1. **绕过了平台架构**。测试评审等能力走的是 graph + skill + fork subagent 正路（用户在 TUI 对话、main agent 自主完成）；编译用例没有理由用外层脚本，脚本做的"捕获/入库/回流"都应由 skill + 记忆机制承担。
2. **单 agent 自生成又自评估**。编译 skill 曾是 inline，导致同一个 agent 既生成 xlsx 又给自己的产物打分——自评必然不可信（实测：某用例生成弱断言、自评低分后又自行推翻、最终误判可交付）。
3. **质量判据无约束力**。置信判分只是 main agent 手里的一个工具，agent 可无视/推翻其结论。

## 架构：编排器 + 子流程（2026-06-16 编译/上机验证解耦后）

全部在 main agent 内部、用平台自有的 fork skill + `qa_invoke_skill` 编排完成，不依赖外层脚本。

> **重要（2026-06-16 解耦）**：编译链**不再包含上机**。原"生成→上机→评估→双绿才交付"已拆成两段：**编译**（draft 生成 → grade 断言质量审批 → 合并出 excel，不上机）+ **独立上机验证**（`ist_verify` skill 对成品 excel 上机）。下表的 `ist_compile_run` 现归 `ist_verify` 调用，不在编译交付链内。

| 角色 | skill / agent | 职责 |
|---|---|---|
| 编排器 | `ist_compile_batch`（inline，main agent 读取并编排，唯一编译入口） | 派发生成/审批、汇总反馈、判定交付、派发重做、上报。不直接生成/上机/评分 |
| 生成 | `ist_compile_draft` / `ist-compile-draft`（fork） | 核查前置→检索先例→`qa_emit_xlsx` 生成草稿。不上机、不自评 |
| 评估 | `ist_compile_grade` / `ist-compile-grade`（fork） | `qa_confidence_score` 判断断言是否覆盖目标行为 + 给重做意见。**断言质量审批，device verdict 可选输入，不依赖上机**。不生成、不上机 |
| 上机（独立环节，非编译链） | `ist_compile_run` / `ist-compile-run`（fork，由 `ist_verify` 调用） | `qa_run_case` 上机执行 + 采集框架真实裁决（ground truth）。不修改、不评估 |

### 编译流程（产出 excel，不上机）

```
派发生成(draft) → 拿到 xlsx 草稿
派发评估(grade) → 拿到 PASS/CUT + 置信分 + 重做意见（基于需求+先例+手册，不依赖上机）
判定:
  grade PASS → status=done，进合并打包出 excel
  grade CUT  → 携带[上一版 + grade 重做意见]派发重做(draft) → 回到评估
  连续 N 轮(建议3)仍 CUT → escalate-when-stuck / qa_ask_user 上报
合并(qa_emit_xlsx_merged) → 脑图级 excel 落地
```

### 上机验证流程（独立，走 ist_verify，产出 excel 之后）

```
ist_verify 对成品 excel → qa_run_batch 串行上机 → 采集每 case 框架真实裁决
分类: 真实断言失败(回流重编译) / 环境瞬态失败(SSH/dig/DNS,标注不回流)
回流: 真实断言失败的 case 带反馈调 ist_compile_batch 重编译
```

编译与验证经 **ask_user 在交互层串成闭环**：batch 出 excel→问"要验证吗"→是则 ist_verify；verify 出报告→问"要修复吗"→是则回流重编译。

### 为什么这样设计

- **生成/评估是独立 fork 子 agent，彼此隔离**——从结构上消除"同一 agent 自生成自评估"。这是缺陷 2 的根治。
- **交付门槛是 grade 断言质量**（断言是否覆盖目标行为），**不是上机 pass**。原因（2026-06-16 实证）：上机大面积失败常是设备环境瞬态（SSH 会话中断、dig 超时、DNS 解析失败），把"上机通过"当成"进 excel"硬前置会让环境一坏就出不了任何 excel。grade 是断言质量门槛（弱断言/未覆盖仍 CUT，不救场），上机是产出后的独立验证 + 回流依据。
- **评估的 CUT 是强制反馈**，编排器不得推翻后宣布交付。这给了质量判据约束力（缺陷 3）。
- 参照范式：`review-verification`（test-list-review 中主 agent 写草稿、fork 独立 verifier 复核，主 agent 不 self-assign 结论）。

## 关键实现点

- **工具注册**：`skills/loader.py` 的 `_TOOL_REGISTRY` 注册了 `qa_emit_xlsx`/`qa_run_case`/`qa_confidence_score`/`qa_lookup_pattern`/`qa_probe_show`，fork 子 agent 才能取用。
- **置信判分** `case_compiler/confidence_f.py`：LLM 依据证据（需求 + 配置上下文 + 同类先例 + 手册行为）判分，非硬编码规则；缺判分模型时 abstain，不以硬规则猜分。`qa_confidence_score` 返回结构化 JSON（overall / decision / 逐 check_point score+reasons）。
- **检索与评估工具** `tools/device/precedent_tools.py`：`qa_lookup_pattern`（按配置结构相似度检索已验证先例，纯结构距离、无 embedding）、`qa_confidence_score`（判分入口）。

## 演进中清理的历史包袱

- 删除旧确定性管线（pipeline/compiler/anchorer/gates/x1_validate/... 共 22 个 .py）——它们是早期"LLM 填槽 + 静态闸"方案的主体，agent 路径不再使用。
- 删除按特定算法写死的断言重写（rr_stats）及其 skill——属逐用例硬编码，与"通用编译"目标冲突。
- 修复全项目手册路径引用：曾散落 `cli_*_commands.md`（不存在）/ `cli__part*.md`（缺前导通配）等错误路径，导致 agent 检索手册落空、误判"手册无此命令"而遗漏前置配置。统一为 `*cli__part*.md`（匹配各版本命令手册卷）。
- 修复上机读取无超时：`device_mcp_client.call()` 的 `so.read()` 阻塞读，server 端工具卡住会无限挂起；加 900s 读超时兜底。

## 设计比喻说明（仅文档，不进代码）

讨论本架构时曾用"餐厅"比喻辅助厘清角色分工（编排器=统筹、生成=备料下厨、上机=送检取反馈、评估=质检）。该比喻仅用于设计沟通，**不写入生产代码**——代码与 prompt 使用专业术语（编排器 / 草稿生成 / 上机执行 / 质量评估）。

## 入口

走平台正路：用户在 infotest TUI 中要求"把某脑图的某用例编译成 case 并上机验证"，main agent 触发 `ist_compile_batch` 自主完成。不再使用 `scripts/debug/agent_compile_case.py`（已退役）。
