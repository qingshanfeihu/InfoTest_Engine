# 准入报告料②·zhaiyq unfinished 11 案去向表

> 2026-07-19 · Test-Eng · 准入报告输入。源 `workspace/outputs/zhaiyq/unfinished/RESUME_NOTE.md`（§11.9 归档随附）+ run_log §6.5/6.7/6.8。
> **zhaiyq 收官真值**：delivered **42** / unfinished **11** = 53（D31 checker-bug 修复后重渲实证,详见 `zhaiyq_recon_gate_D31/`）。

## 11 案去向分类（4 类）

| 案（尾6） | 类别 | 终局 | 跨批 resume 行为 | 去向 |
|---|---|---|---|---|
| 532349 | 挂起（批末 gather 用户裁挂起） | 待人工厘清·IPv6 无触发机真床限制 | 见下 CAVEAT（keep 不自动回 gather） | 换床/人工输入后显式重提 |
| 532519 | 挂起（批末 gather 用户裁挂起） | 待人工厘清·IPv6 前缀 runtime 本体（本案独有价值,①IPv4 等价会吞没本体） | 见下 CAVEAT | 换床/人工输入后显式重提 |
| 532436 | 改描述（改过程证伪→defer 待人工厘清） | 待人工厘清·可验性边界（加请求类修法不解决本体） | 见下 CAVEAT | 更新脑图/描述后显式重提 |
| 532618 | 改描述（改过程证伪→defer 待人工厘清） | 待人工厘清·可验性边界 | 见下 CAVEAT | 更新脑图/描述后显式重提 |
| 545097 | 缺陷候选（user_confirmed product_defect） | 缺陷结案·ALL 20s vs A 10s 优先级语义（歧义 note①） | 产品确认后另议 | **交产品复核链**（见下歧义 note） |
| 545249 | 缺陷候选（user_confirmed product_defect） | 缺陷结案·show 表空 vs dig 双证活跃矛盾（歧义 note②） | 产品确认后另议 | **交产品复核链**（见下歧义 note） |
| 517027 | escalated（引擎无法继续需人工） | honest 未通过·fork no-output 并发型 | 降并发/换环境重调可能救回 | 后批重调候选 |
| 600113 | escalated | honest 未通过·fork no-output 并发型 | 降并发/换环境重调可能救回 | 后批重调候选 |
| 588766 | escalated | honest 未通过·broken+E 环境床 | 换环境重调可能救回 | 后批重调候选 |
| 589503 | escalated | honest 未通过·broken+E 环境床 | 换环境重调可能救回 | 后批重调候选 |
| 589432 | escalated | honest 未通过·broken+E 环境床 | 换环境重调可能救回 | 后批重调候选 |

**类别小计**：挂起 2 / 改描述 defer 2 / 缺陷候选 2 / escalated 5 = **11**。

## ⚡ CAVEAT（跨批 resume·防 defer 变丢，leader 令入注）

**本批对 532349/532519/532436/532618 四案答「保持挂起」后，#37 resume 白名单排除 keep 类决策——这 4 案未来 resume 时不会再自动回 gather。**
- **`defer ≠ 丢`**，但拾起靠**主动重新提交**（人工厘清到位/更新脑图输入→走 `user_decision` 更新→再调批），**不靠自动 resume**。
- 机制溯源：nodes.py:405-408 reopen 谓词——`user_decision:改描述` ∨ `auto:{panel|cap|contra}` 重开；`keep:` / `auto:{env|bed}` **不重开**（用户明确保持/外因未变）。四案答 keep 落 `suspended(keep:qid)`,故不自动拾起。
- **实弹佐证**：本 caveat 即路径 tracker **P2-m（keep 不重开）zhaiyq 重调实弹**的直接产物——收官重调触发 #37 resume gather 4 题、答②保持挂起×4、续跑不再回 gather,边界①坐实。

## 缺陷候选歧义 note（进产品复核链，2 条）

1. **ALL 与特定类型同配的优先级语义**（545097）：会话保持 ALL 20s vs A 10s,设备 11s 后 A 仍绑同 pool（ALL 覆盖 A 的 10s）。手册 line 485 有 per-type timeout 但**无 ALL-vs-特定优先级条款**——待产品确认「特定类型 timeout 是否应独立于 ALL 生效」。
2. **show sdns session persistence 是否显 post-timeout 轮转后的新持久化条目**（545249）：会话保持功能正常（dig 连续两次 .225 证活跃持久化）但 show 表空,手册 L512 本职显当前会话状态、L512 未细分——行为与职能矛盾,待产品确认。

## 去向汇总口径（供准入报告未决案节）

- **可后批救回（7）**：5 escalated（降并发/换环境重调）+ 2 挂起（IPv6 换床）——非产品缺陷,工程/环境侧。
- **待人工厘清（2）**：532436/532618 改描述 defer——可验性边界,需更新脑图输入。
- **交产品复核链（2）**：545097/545249——真产品缺陷候选,与准入报告料③缺陷单（我方交互缺陷）分属不同性质,勿混置。
