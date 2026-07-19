# 准入报告料①·22 交互路径 tracker 终对数（四批合并）

> 2026-07-19 · Test-Eng · 准入报告输入（模板 25f3f15f）。源清单 `team4_interaction_path_completeness.md`（Theory 机械枚举 22 路径）+ 四批 facts 踩点。
> **口径**：本表以**四批合并**（CNAME_dongkl / dongkl / yzg / zhaiyq 首跑+收官重调）为终账，非单 zhaiyq 视角。
> **诚实边界符**：✅=有具体批/案实弹；⚠=结构可达无手头实弹（需 facts 全量补实）；❌=结构可达且明确无实弹（含理论预测）。

## 终对数（22 主路径 = P1×2 + P2×17 + P3×3）

| ID | 面板点·问题种类 | 答案 token→下游 | 踩点（批/案） | 状态 |
|---|---|---|---|---|
| **P1-a** | bed_gate·床态体检 | 继续→author 照跑 | 全批常规 prep（dongkl/yzg/zhaiyq） | ✅ |
| **P1-b** | bed_gate·床态体检 | 停止→closing 修床同参重跑 | — | ⚠ 未踩（run14 疑似失联批无确证；zhaiyq 重调走 #37 resume 非 bed stop） |
| **P2-a** | ask_decision·欠定三选 | 改过程→author 重编 | 批2 dongkl 改过程×7 / zhaiyq 批末 gather（532436/532618 当轮答改过程） | ✅ |
| **P2-b** | ask_decision·欠定三选 | 改预期→author(带 form) | **批2 dongkl 改预期×1**（据缺陷单全量回溯处置分布补实） | ✅ |
| **P2-c** | ask_decision·欠定三选 | 改描述→suspended(S_PENDING) | 批3 #36 668族7案 / zhaiyq 532436/532618 终局 defer | ✅ |
| **P2-d** | ask_decision·test_point 采纳 | 采纳该等价方案→author | 批3 D12 / zhaiyq 588990 采纳先例 + 599838 采纳等价 | ✅ |
| **P2-e** | ask_decision·test_point 采纳 | 我给别的等价方案→brief 注入 | — | ⚠ 未踩→残余造场景 |
| **P2-f** | ask_decision·test_point 采纳 | 挂起,如实报告→S_PENDING | — | ⚠ 未踩（zhaiyq 挂起走 P2-l 挂起处理族,非采纳题挂起）→残余造场景 |
| **P2-g** | ask_decision·cap 轮次封顶 | continue 追加轮次→author | **zhaiyq 545249**（cap ①继续再修2轮,leader 裁健康迭代,5 选项全掌控） | ✅ |
| **P2-h** | ask_decision·cap | stop→user_stop→closing | 批4 zhaiyq 停止×1（处置分布佐证；案号 completeness 记 517027 系） | ✅ |
| **P2-i** | ask_decision·env 环境确认 | 确认环境→attribution(env_blocked) | — | ⚠ 未踩（**自纠**：zhaiyq E×3 系 attribution 层归因,非 env 确认 ask 面板；§6.1 乐观标记撤回）→残余造场景 |
| **P2-j** | ask_decision·env | retry 不接受→rerun_isolated | — | ⚠ 未踩→残余造场景 |
| **P2-k** | ask_decision·bed 床治理 | (床治理 token)→床恢复/呈报 | — | ⚠ 未踩→残余造场景 |
| **P2-l** | ask_decision·挂起处理 | suspend→suspended(reason=qid) | 多批 / zhaiyq 532349/532519 批末 gather 挂起 + 517196 livelock 人工挂起 armed | ✅ |
| **P2-m** | ask_decision·恢复问询 | keep 保持挂起→suspended(keep:)不重开 | **zhaiyq 重调 #37 resume gather 答②保持挂起×4**（532349/532519/532436/532618）——边界① keep 不重开实弹（RESUME_NOTE caveat 来源） | ✅ **新踩** |
| **P2-n** | ask_decision·恢复问询 | resume 恢复处理→resumed+重开欠定→gather | 批3 #37 守门 / #36 mini（答①恢复处理） | ✅ |
| **P2-o** | ask_decision·挂起处理 | defect 确认缺陷→defect_candidate | **zhaiyq 545097 + 545249 dispute ②确认产品缺陷**（bug-to-case 富集点命中） | ✅ **新踩** |
| **P2-p** | ask_decision·折叠广播(mem>1) | 任一 token→扇出全组逐案落 | 批3 D12 599838 folding / zhaiyq 批末 gather 4-per-chunk 折叠 | ✅ |
| **P2-q** | ask_decision·Other 自由输入 | 自由文本(token 空)→语义兜底 | — | ⚠ 未踩→残余造场景 |
| **P3-a** | ask_contradiction·contra | reorder 重排复验→merge 复验环 | **批4 zhaiyq 首跑 重排复验×2**（532519 等 contra 面板,据处置分布补实；收官重跑未再现） | ✅ |
| **P3-b** | ask_contradiction·contra | downgrade 如实降级→不入交付卷 | — | ⚠ 未踩→残余造场景 |
| **P3-c** | ask_contradiction·contra | confirm/correct→adjudication 写回 | — | ⚠ 未踩→残余造场景 |

**统计：13 踩 / 9 未踩（22 全覆盖）**。
- **✅ 已踩 13**：P1-a、P2-a、P2-b、P2-c、P2-d、P2-g、P2-h、P2-l、P2-m、P2-n、P2-o、P2-p、P3-a
- **⚠ 未踩 9**（残余造场景补踩清单）：P1-b、P2-e、P2-f、P2-i、P2-j、P2-k、P2-q、P3-b、P3-c

## 附·判例路径子矩阵（§3，5 条 pre-panel adopt 环）

| 判例路径 | 触发 | 踩点 | 状态 |
|---|---|---|---|
| 同 shape 采信（免问） | 案 shape==判例 shape ∧ 单 token | (21c) 正对照真FM案 / zhaiyq 588990 同 shape(ALL 合法性)正确匹配采纳 | ✅ |
| 异 shape 禁入 | 案 shape≠判例 shape | D12 shape-fix（vpa vs FM 误采信修复） | ✅ |
| 止损转人工 | 同 aid adopted≥2→gather | — | ⚠ 未踩（drift fix 守门锁绿,实弹待踩） |
| 判例沿用④ | adopted 案时间线沿用 | — | ⚠ 未踩 |
| 批序自指窗口(45c) | 批中早案 writeback→后案免问 | — | ❌ 未实弹（理论预测；**commit 5ce88c9d 注**：zhaiyq 588990 走 ask=巧合非设计,KEY_FIELDS 无批次分层,45c 路径未触发） |

## 诚实边界与补实溯源

- **两条据机读回溯补实**（P2-b/P3-a）：源=缺陷单 `ist_core_ask_interaction_defects.md` 批1-4 全量面板回溯表（43 面板机读提取处置分布）——Theory 清单原标"⚠ 待核"是抽样未全库 grep（清单 §4 自陈），本表按其预期动作补实为 ✅；leader 可据 facts.jsonl 逐案亲核。
- **一条自纠撤回**（P2-i）：§6.1 曾乐观列入已实弹9条,机读回溯无 env 处置类、E×3 属 attribution 层归因（非 env 确认 ask 面板弹出）,故降为未踩。
- **P2-h/P3-a 案号精度**：处置分布证"批4 有停止×1/重排×2",精确案号部分待 facts 核（不影响路径踩点结论）。
- **富集点验证**：leader 冒烟策略"bug-to-case 会话保持大概率自然出"坐实——zhaiyq 天然踩到 **P2-o defect（缺陷候选富集）+ P2-g cap continue + P2-m keep（收官重调）+ P3-a contra**，四条高价值路径大批天然覆盖。
