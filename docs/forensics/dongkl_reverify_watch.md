# dongkl 重验 — 目标案 watch 项(终版审)

> dongkl 34案,验 dongkl 特定定稿目标。round-0 emit 早期观察,**终版(设备跑+重编后)为准**。

## S1 分布形态(593516/593545) — 关键 watch

round-0 emit 形态分化:
- **593516**(WRR): `dig +short`×4 + found「第3次dig=p1成员IP」——dig 成员序列检查(abs_found式),合理。
- **593545**(WRR 3:2:1): `dig` + `show statistics sdns pool p1`→found **`Hit:\s+3`** ⚠️
  - 命令对(show statistics,per 用户card②),但断言=**脆的精确计数**,非区间法("大量发包+区间28-33验比例近似3:2:1")。
  - **终版判据**:
    - `Hit:\s+3` 上机fail→重编改区间 = S1 反馈环生效(可接受);
    - `Hit:\s+3` 侥幸pass交付 = S1 修不完整(worker.md 仍纵容精确Hit:,需再收紧)。

## 其余目标案(终版审,分派团队)

| 案 | 目标 | 判据 | 分派 |
|----|------|------|------|
| 593516/593545 | S1 分布 | 区间法 vs 写死Hit: | oracle |
| 994986 | 敲对门 | worker 探 SSH/APV_0 非console; attributor 读同案passed_cp | attribution |
| 777976 | 归因自查 | 读同卷Success/passed_cp≥1→不误env_blocked | attribution |
| 572708 | F1 | 双源平摆无默认; hypothesis中性; correct裁决 | attribution |
| 210998 | broken | pyATS七码子分类(Errored/Blocked) | gates |
| 994838/994869 | DNS | DNS lint 不误杀(cookie/TSIG/64hex) | gates |
| 全批 | 交付完整性 | deliverable/suspended; footprint provisional写回; eval | closeout |

## S2 F1 修 → 真机验证通过(572741 ask 面板,round1)

572741(`clear sdns host method` 语义案)触发真 ask 面板,逐条对标 S2 F1 修:
- **双源平摆**: sides=[手册 Ch20:432-434 原文 + device_context 原文],各带 quote+anchor,无一方优先 ✅
- **无默认/无"建议"**: ask 中性二选「理解为重置默认(改断言验rr)」vs「设备未正确删除(固件缺陷)」✅
- **中性措辞**: "情况梳理"(非"引擎的理解"),问句对称 ✅
- **缓存冲突正确重问**: retrieval_receipt `clear...删除算法配置→hit_conflicting`(命中但冲突)→ 正确重问不盲用 ✅
- conflict_shape=expected_vs_observed · intent_sig=clear-sdns-host-method-delete-vs-reset

**这也是 #2 交互正例真机 exercise**(yzg 被裁决缓存短路没弹,dongkl 弹出真面板)。

## 目标案 round1 归因(屏幕已完成)

- 593516/593545(分布) ✅归因完成 — 终版断言形态待审(593545 的 Hit:\s+3 watch)
- 572708(F1目标) ✅归因完成解决(有 case.xlsx,无 ask/needs_decision)
- 572741 → ask 面板(F1形态验证由它达成)
- 778012 归因 14m56s(慢,同 yzg paging 特征)

## 进度记录

- round0 写阶段: 15/34 emit @~13min, ¥24.6
- round0 上机: 通过16/失败0/欠定4 @~31min, ¥36
- round1 对账: awaiting_user 4 · failed 13 · deliverable 16 · pending 1 @1h13m, ¥45.6
  - ask 面板 572741 已成形(交互未弹,待 round1 收敛 interrupt)
- round1 交互面板弹出(2题) @1h37m, ¥48.7

---

## 真机揪出的问题(记录,未分析未改代码 — 2026-07-15)

### 问题1: 572741(clear sdns host method 语义案)— 用例断言写错
- 案自洽(步骤3自配 test2=wrr/test3=ga,步骤6-7设备验到通过),**非跨案污染**。
- 设备行为: `clear sdns host method` 把算法重置为默认 "rr"、**域名条目保留不删**。
- 用例断言步骤10-12 写 `not_found`(以为删除)→ FAIL。正确应 `found "rr"`。
- 交叉印证: 572708 测 `no sdns host method test2`,设备连带把 test3 的 ga 也重置 rr。
- 面板处置: env/缺陷都不贴,该 Other 写正确预期(或标产品行为待定)。**用户未答,待裁决**。

### 问题2: 593516(新增pool p4,WRR)— S1分布验证方式不当 + 归因误退env
- **用户 V6 历史结论(权威)**: 该案 V6 调很久,结论=**需改步骤**,因"访问1、2、3无法满足要求";**ask 的问题不对**(env/缺陷框定错)。
- 现象: worker 写少量 dig 查特定成员IP出现(step21-22 验 p4成员226),RouterA dig 恒返213不轮转/RouterB dig 超时 → Fail Num1(找不到226),Passed 6(config全对)。
- 归因判 `env_blocked`(evidence: `;; connection timed out`),S2自查有注意到 6/6 passed(fix_direction 写了"All device-side config correct"),但仍落 env_blocked→ ask 问成"环境 vs 缺陷"。
- **性质(按用户 V6)**: 真根因是 **WRR 验证步骤不当**(该走 card② 大量发包+show statistics+区间验证,而非少量dig成员检查),既非环境也非产品缺陷。
- **暴露的引擎缺口(记录,不改)**:
  - S1 分布指引对 WRR 案不够硬——593516 未走统计法(同批593545走了show statistics);
  - 归因缺"验证方式不当→改步骤"出口,分布验不出误退 env_blocked → ask 框定错。
- **我的 SLB 占用推断(撤回)**: 曾据配置会话 `Warning: ...may already be occupied by SLB virtual service` + RouterA恒213/RouterB超时,推"SLB vip 污染listener"。经用户 V6 实证,该 Warning 是配 listener 时**每次都打的预防性提示**,非占用确证——**属 over-reach,撤回**。真问题是步骤设计(见上)。

### 观察: 593545 的 Hit:\s+3(见上 S1 分布形态 watch,待终版)

---

## 修法后重跑2 终结果（2026-07-16，通道消歧修法 + langfuse）

**yzg 零回归**：deliverable 25 / suspended 1（655233 VLAN），逐字匹配基线；**6 欠定全非分布案**（VLAN/重启/命令存在）——**通道消歧零误触发非分布案**（#1 过度泛化教训通过）。

**dongkl 完整生成**：`delivered_with_labels` · deliverable 22 · suspended 9 · failed_terminal 1 · pending 1 · escalated 1 · ask{answered 11, effective 10}。没崩没 livelock（引擎正确 escalate 硬案，用户授权我处理）。

**修法 langfuse 铁证生效**：593545 worker 调 `compile_check_verifiability`（入参 claim_kind=weight_ratio）→ NEEDS_USER_DECISION；思维链"g p1 is deterministic, not sampling-sensitive. No need for compile_check_verifiability" / "RR轮转是确定性映射不涉及h-in-λ" —— worker **区分分布 vs 确定性**、认对分类。593516 用 show statistics+Hit:≥1（首次重跑是纯 dig membership）。

**infotest 正确提问验证通过**：分布欠定的 ask 是**改过程(dist ≥6次+compile_expected_hits) / 改预期(关系归属)**——**非 env-vs-缺陷假框定**；stuck 案 escalate(继续/挂起/停止)；778041 跨案互扰(重排/降级)；105941 CNAME 匹配已知缺陷 149877。**修法把 ask 掰对了。**

**12 非通过案性质（inherent 硬案，非修法回归）**：
- 分布构造残留（worker 认对分类但构造仍有错）：593484 精确Hit(WRR非确定,该区间)、593516 用错命令(show sdns host pool 不显成员IP,该 show statistics)、778012 缺前置(host name 先于 host pool)、681749 成员IP错、572672 缺 priority 参、572708 命令语法错。→ **未来 worker.md 改进 findings**（哪命令显什么、区间vs精确、前置序）。
- 真设备行为/缺陷：777976+778072 A记录 dig 返空(AAAA正常)、778041 运行时加的 pool 不入轮转、105941 CNAME 池命令已知缺陷 149877。→ 缺陷候选/待可执行环境。
- 分布验证方法正确但构造难：593545 改过程→dist 重编（pending，收尾时 mid-recompile）。

**成本**：yzg ~¥35 / dongkl ~¥103（failed 12 硬案 max 思考多轮重编 + 归因 paging 推高）。归因 paging 是既有效率债（非本次回归）。
