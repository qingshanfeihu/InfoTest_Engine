# yzg 重验:回归run(修复前) vs 本轮(修复后) 对照

> 用户裁决:"对比之前运行的 yzg 的输出才能判断是否是回归还是改进"
> 基线来源:`runtime/backups/yzg_reverify_pre_20260715/yzg/engine_report.json`(dc435c93 提交前那次跑,即揭出 3 回归的 run)

## 基线(修复前,回归run)

```
totals: cases 26 · subset_verified 17 · awaiting_user 7 · broken 2 · deliverable 0
ask:    {answered 1, effective 0, freeform 0}
outcome: "delivered_with_labels"(实际 0 交付)
bed:    10.4.127.103 · InfosecOS Beta.APV-HG-K.10.5.0.585
```

**三处病灶实证**:
1. **deliverable 0** — 17 案过 subset 验证却无一 deliverable,全停"待整卷复验"(整卷终验从未发生,run 降级卡死)。
2. **ask effective 0** — ask 答过 1 次却零生效,7 欠定全悬空(印证用户"ask 没机会修改")。
3. **bed_gate 误报残留** — worker 全卡"编写中26"探不了设备(轮次20 死循环)。

## 本轮(修复后)进行中观察

- **#3 bed_gate**:✅ 26 worker 真机自由探针,轮次0 正常起步(bed_gate 不再误报残留)。
- **#1 worker 纪律**:✅ 6 案正当 punt 欠定(VLAN新IP不可达 / write mem重启不可验),无假断言 observe-then-assert。
- **round0 上机**:14 PASS / 0 FAIL(干净,无假fail崩卷)。ledger `deliverable 14 / awaiting_user 5 / failed 7`。
- **#2 ask 面板**:⏳ 待收敛触发(5 欠定案排队)。

## 本轮最终(修复后,dc435c93)

```
totals: cases 26 · deliverable 25 · suspended 1 · broken 0
ask:    {answered 5, effective 5, freeform 0}
outcome: "delivered_with_labels"(实际 25 交付)
轮次分布: {0:1(挂起) · 1:16 · 2:8 · 3:1}  frozen 0  contradictions 0
用时/成本: ~1h37m · ¥46.85 · ↑14.8M ↓420k tokens
```

## 对照判据裁决

| 判据 | 基线 | 本轮 | 裁定 |
|------|------|------|------|
| deliverable | 0 | **25** | ✅ 整卷终验路由通(基线全停"待整卷复验") |
| ask effective | 0 | **5** | ✅ #2 ask liveness 修生效(欠定案路由到 ask_decision) |
| awaiting/悬空 | 7 | 0(1 suspended) | ✅ 无悬空,1 案按缓存裁决合法挂起 |
| broken | 2 | 0 | ✅ |
| frozen/矛盾 | — | 0/0 | ✅ 干净收敛 |

## 三修真机裁定

- **#3 bed_gate**:✅ 26 worker 真机自由探针(vs 回归卡"编写中26"探不了)。
- **#1 worker 纪律**:✅ 6 案正当 punt 欠定(VLAN新IP不可达/write mem重启不可验),无 observe-then-assert。
- **#2 ask 路由**:✅ 欠定案路由到 ask_decision(复用真人历史裁决"免问")→ 25 交付 vs 基线 0。
  - 注:本轮交互面板被**裁决缓存短路**(`knowledge/adjudications/eq--*.md` + `user_decision.json`,run21/run25 真人答过)——路由验证成立,交互显示由 test_gather_ask.py 覆盖。

## 合法性审计(无红线违规)

- **无污染**:主卷 25 yzg案(203601)+1哨兵,0 dongkl混入("34"是我读表头的假象)。
- **缓存裁决真实**:`eq--forbidden-mechanism--10-5.md` 内容具体(改forward目标为可达172.16.34.71)、run25今天真人答;非引擎自答。
- **25 交付真过终验**:engine_report 标 deliverable(整卷终验后才打),非硬 deliver;重编1-3轮真机跑过。

## 效率观察(非回归,非阻塞)

- 归因慢:667986 翻 last_run.json 9min/11次、676668 交叉grep 5.5min/20次——**既有 offload-large-result 病**(大 last_run 该进程内消化 digest,不该 LLM 逐页翻);我的 S2 自查只占 ~1/20 grep、非主因。
- 成本 ¥46.85 高于基线 ~¥40:max 思考多轮重编(轮次0-6)+ 归因 paging 推高。dongkl(34案)会同特征放大。

## 待你确认

- lineage 标 `user_proxy`:这些复用的裁决是你此前 run 里亲自答的吗?

