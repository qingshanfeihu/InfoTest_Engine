# V8 用户交互路径穷尽清单（理论侧完备性 · 机械枚举）

> 2026-07-18，Theory。D+1 开工令产物。**完备性由图拓扑+事件类型机械枚举保证，不靠回忆**。
> Test-Eng 按本清单执行冒烟；「未实弹」列即造场景踩点。带行号宣称属 leader 亲核层。
>
> **机械词表源（本轮 genuine 读，行号供亲核）**：
> - 图拓扑 `graph.py:155-169`（11 节点 + 条件边）
> - 3 个 interrupt/panel 点：`bed_gate`(nodes.py:298) / `ask_decision`(:774) / `ask_contradiction`(:2396)
> - token 词表 `_TOKEN_CN`(nodes.py:32-39)：confirm/correct/defect/continue/suspend/stop/retry/resume/keep/reorder/downgrade/reflow_tau + 欠定三选(改过程/改预期/改描述) + 采纳(test_point) + Other
> - 挂起 reason 谓词(nodes.py:400-408)：`user_decision:改描述` **∨** `auto:{panel|cap|contra}`(白名单 :406-408 重开)；`auto:{env|bed}`/`keep:` 不重开
> - 判例路径：shape-aware 采信(:622 (21c)) / 止损(:630 n_adopt≥2) / 免问派生 decision(provenance=adopted:*)
> - ev 事件类型(facts.py idem_key + batch facts)：run_start/bed_checked/needs_decision/authored/decision/verdict/attribution/writeback/rollback/resumed/suspended/adopted/ask_shown/user_stop/escalated/merged/diagnosis/s0_dispute/common_cause/sibling_contrast/cap_reached/strong_claim_unaddressed

## 0. 图拓扑骨架（交互路径的结构约束）

```
START→prep→[bed_gate|closing]
bed_gate[⏸P1]→[author|closing]
author→[ask_decision|merge|ask_contradiction|closing]
ask_decision[⏸P2]→[author|merge|closing]
merge→[run|ask_decision|closing]
run→[reconcile|closing]
reconcile→[ask_contradiction|attribute|merge|ask_decision|closing]
attribute→diagnose→[ask_contradiction|author|merge|ask_decision|closing]
ask_contradiction[⏸P3]→[attribute|merge|ask_decision|closing]
closing→END
```
**⏸ = 3 个用户交互点(interrupt)**：P1 `bed_gate` / P2 `ask_decision`(承载最多问题种类) / P3 `ask_contradiction`。
**完备性论断**：用户可被问的时机 = {P1,P2,P3} 穷尽（图中仅此 3 个 interrupt()）；每点的问题种类 × 答案 token × 下游路由 = 交互路径全集。

## 1. 交互路径全集（面板点 × 问题种类 × token × 下游）

| ID | 面板点 | 问题种类 | 答案 token | 下游路由 | 已实弹(批/案) | 未实弹→Test-Eng 踩 |
|---|---|---|---|---|---|---|
| P1-a | bed_gate | 床态体检 | 继续(proceed) | →author 照跑 | ✅ yzg/dongkl 常规 prep | — |
| P1-b | bed_gate | 床态体检 | 停止(stop) | →closing 修床后同参重跑 | ⚠ 待核(run14 失联批疑似) | 造：床残留→停止→同参续跑幂等 |
| P2-a | ask_decision | 欠定三选(h_absent) | 改过程 | decision→author 重编 | ✅ dongkl/yzg | — |
| P2-b | ask_decision | 欠定三选 | 改预期 | decision→author 重编(带 form) | ⚠ 待核 | 造：改预期→emit form 门→重编 |
| P2-c | ask_decision | 欠定三选 | 改描述 | suspended(user_decision:改描述)→S_PENDING | ✅ #36 668族7案 | — |
| P2-d | ask_decision | test_point 采纳(三元组) | 采纳该等价方案 | decision→author | ✅ D12/zhaiyq | — |
| P2-e | ask_decision | test_point 采纳 | 我给别的等价方案 | decision(用户原文)→author | ⚠ 待核 | 造：Other 式自给方案→brief 注入 |
| P2-f | ask_decision | test_point 采纳 | 挂起,如实报告 | suspended→S_PENDING | ⚠ 待核 | 造：采纳题挂起→后续 resume |
| P2-g | ask_decision | cap(轮次封顶) | continue(追加轮次) | granted_rounds 上移→author | ⚠ 待核 | 造：轮次封顶→加轮→再上机 |
| P2-h | ask_decision | cap | stop | user_stop→closing | ✅ zhaiyq 三例(517027/600046/533020 r99) | — |
| P2-i | ask_decision | env(环境确认) | 确认环境(env_blocked) | attribution(E/env_blocked r99) | ✅ zhaiyq r99 | — |
| P2-j | ask_decision | env | retry(不接受 env) | rerun_isolated→merge 待验 | ⚠ 待核 | 造：用户驳 env→隔离复跑 |
| P2-k | ask_decision | bed(床治理) | (床治理 token) | →床恢复/呈报 | ⚠ 待核 | 造：批内 bed 面板治理 |
| P2-l | ask_decision | 挂起处理 | suspend | suspended(reason=qid) | ✅ 多批 | — |
| P2-m | ask_decision | 挂起处理 | keep(保持挂起) | suspended(keep:qid)不重开 | ⚠ 待核 | 造：keep→resume 不重开(边界①) |
| P2-n | ask_decision | 恢复问询 | resume(恢复处理) | resumed+重开欠定(新nd:2)→S_AWAITING_USER→gather | ✅ #37 守门/#36 mini | — |
| P2-o | ask_decision | 挂起处理 | defect(确认缺陷) | defect_candidate(product_defect r99) | ⚠ 待核 | 造：用户确认缺陷→候选单 |
| P2-p | ask_decision | 折叠广播(gather,mem>1) | 任一 token | 代表答案扇出全组、逐案落 | ✅ D12 folding(599838) | — |
| P2-q | ask_decision | Other(自定义自由输入) | 自由文本(token 空) | 语义兜底(node 侧) | ⚠ 待核 | 造：Other 自由输入→兜底路由 |
| P3-a | ask_contradiction | contra(矛盾即问) | reorder(重排复验) | →merge 复验环 | ⚠ 待核 | 造：contra≥2→重排 |
| P3-b | ask_contradiction | contra | downgrade(如实降级) | attribution 降级(不入交付卷) | ⚠ 待核 | 造：矛盾→降级未通过卷 |
| P3-c | ask_contradiction | contra | confirm/correct | adjudication 写回(下批免问) | ⚠ 待核 | 造：contra confirm→判例写回 |

## 2. 挂起 kind × 恢复场景 子矩阵（P2-n resume 路径展开）

reopen 谓词(nodes.py:405-408)：`reason == "user_decision:改描述"` **∨** (`auto:` 前缀 ∧ 原 panel kind∈{panel,cap,contra})——`auto:{panel|cap|contra}` **确实重开**（:406-408 白名单，守门 `test_predicate_auto_env_bed_not_reopened` 锁绿、已合入 HEAD 3dcc3af8）；`auto:{env|bed}`/`keep:` 不重开（外因未变/用户明确保持）。〔勘误 2026-07-18：初版误标「代码仅认改描述」= Theory 增量审停读 :405 漏 :406-408 白名单，leader 亲核 HEAD 销案。〕

| 挂起 kind | resume 应否重开 | 批中 resume | 跨批重入(unfinished/) | re-ask(重开后再问) | 已实弹 |
|---|---|---|---|---|---|
| user_decision:改描述 | ✅ 重开(新nd:2) | ✅ #37 | ⚠ 待核 | ✅ #37 gather | ✅ #36 7案 |
| auto:panel | ✅ 重开(白名单:406-408) | ⚠ 守门锁、实弹待踩 | ⚠ | ⚠ | ⚠ 待踩(重开已实现) |
| auto:cap | ✅ 重开(白名单) | ⚠ 守门 test 锁绿 | ⚠ | ⚠ | ⚠ 待踩 |
| auto:contra | ✅ 重开(白名单) | ⚠ 守门锁 | ⚠ | ⚠ | ⚠ 待踩 |
| auto:env | ❌ 不重开(外因未变) | — | ⚠ | — | ⚠ 待核 |
| auto:bed | ❌ 不重开 | — | ⚠ | — | ⚠ 待核 |
| keep | ❌ 不重开(用户明确保持) | — | ⚠ | — | ⚠ 待核 |

**Test-Eng 重点**：①`auto:{panel/cap/contra}` 挂起案 resume——白名单(:406-408)已实现重开、守门 `test_predicate_auto_env_bed_not_reopened` 锁绿，**实弹待踩**（尤其批中/跨批场景，实测证重开链走通到 gather）；②跨批重入(unfinished/ 目录续跑)后 resume 的 nd_seq replay 稳定性（(48) 跨批场景）。

## 3. 判例路径子矩阵（P2 pre-panel adopt 环）

| 判例路径 | 触发 | 结果 | 已实弹 | 未实弹→踩 |
|---|---|---|---|---|
| 同 shape 采信(免问) | 案 shape==判例 shape ∧ 单 token | adopted decision→免问推进 | ✅ (21c)正对照(真FM案) | — |
| 异 shape 禁入 | 案 shape≠判例 shape | 不采信→正常上面板问 | ✅ D12 shape-fix(vpa vs FM) | — |
| 止损转人工 | 同 aid adopted≥2 | adopt_stalled→gather 问人 | ⚠ 待核(drift fix 守门有,实弹?) | 造：同案判例连采 3 轮→止损 |
| 判例沿用④ | adopted 案时间线沿用 | render「直接沿用(免问)」行 | ⚠ 待核 | 造：跨批同键免问沿用 |
| 批序自指窗口(45c) | 批中早案 writeback 新鲜判例被后案免问 | 跳过面板 | ❌ 未实弹(理论预测) | 造：批中判例写入→后案免问跳面板 |

## 4. 完备性自证与缺口

- **交互点完备**：图中 interrupt() 仅 3 处(P1/P2/P3)，穷尽——无遗漏的用户可被问时机（graph.py:155-169 机械可证）。
- **P2 问题种类完备**：build_questions/token 处理覆盖 kind∈{h_absent 欠定三选, test_point 采纳, cap, env, bed, 挂起处理, 恢复, 折叠, Other}——与 leader 面板类型清单逐项对齐。
- **未实弹富集区(Test-Eng 优先踩)**：①P3 contra 全族(reorder/downgrade/confirm)几乎未实弹；②cap continue/env retry/defect 三条用户主动路径；③`auto:{panel/cap/contra}` resume 重开(白名单已实现、守门锁,实弹待踩)；④跨批重入 resume 的 (48) 稳定性；⑤判例止损/沿用/批序自指(45c)。
- **诚实边界**：✅ 已实弹均引本轮具体批/案；⚠ 待核=我无手头实弹证据但结构可达(需 Test-Eng 或 facts 复核)；❌ 未实弹=结构可达且明确无实弹(含理论预测的 45c)。「已实弹」判定基于本会话证据+facts，**未全库 grep 历史批**，属抽样——leader/Test-Eng 可据 facts.jsonl 全量补实 ✅ 标记。

## 5. 附带：quarantine 案底最小形态（11 条误标判例 §5 poisoned 处置）

给 Py-Eng 顺手落的最小形态（(45)/§5 poisoned=不删、留案底+引用清算）：

```jsonc
// 每条误标判例（FM 名空间实为 vpa）追加隔离标记，不删原条目：
{
  "quarantine": {
    "reason": "shape_mislabel_readwrite_common_cause",   // 读写共因硬写 FM 致 shape 误标
    "true_shape": "verification_path_absent",            // 实际 claim_kind
    "labeled_shape": "forbidden_mechanism",              // 被污染的标记
    "ts": <落盘时间>,                                     // 案底时间戳
    "provenance": "D12_root_cause_migration_dryrun"      // 溯源
  }
}
// 消费端：find_adjudications 跳过 quarantine≠∅ 的条目(不进采信候选);
// 引用清算(follow-up,非本形态):grep 历史 adopted 事实的 slug∈这11条→标受影响案待复核(668000 是其一)。
```
**最小落地**：①11 条各加 `quarantine` 字段（不删）；②`find_adjudications` 加一行 `if h.get("quarantine"): continue`；③引用清算列为独立 follow-up（不阻塞）。形态对齐 §5「poisoned 记案底可查、负信息量严禁进 brief」+ (45) 防自指。
