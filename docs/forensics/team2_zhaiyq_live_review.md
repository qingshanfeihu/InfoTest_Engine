# zhaiyq 在跑批 live 评审（team2 共写）

> 对象：2026-07-16 下午在跑的 zhaiyq 编译批（53 案，`workspace/outputs/zhaiyq/`，引擎 PID 29906）。抓取时引擎在轮次 6→8 收口，终态对账：**deliverable 41 / failed_terminal 2 / escalated 4 / suspended 2 / failed 2 / subset_verified 2**。
> **全程只读**——facts.jsonl / last_run.json / per-case 目录 / events.jsonl / surface:4 均只读快照，零按键、不 SSH、不 dev_*。
> 数据源：`workspace/outputs/zhaiyq/{facts.jsonl,last_run.json,manifest.json}` + `workspace/outputs/205271757988*/` + `runtime/logs/compile_evidence.29906.events.jsonl` + surface:4 抓屏。
> 分工：§1 失败案分类〔exec-replay 署名〕；§2 设计层根因/收紧建议〔design-review 待补〕。整理：2026-07-16。

---

## §1 失败案分类〔exec-replay〕

### 1.0 一句话结论

zhaiyq 非通过案测的是 **SDNS 会话保持（`sdns host persistence`）跨记录类型（A/AAAA/MX/CNAME/ALL）× IPv4/IPv6 访问** —— 这是与 dongkl（池选择 rr/wrr/ga 分布）**完全不同的子系统**。因此：**没有一个非通过案落入我 T1–T10 的"分布确定性"族（T1–T5/T10）或"池权重构造"族（T7）**；**失败的"类型学"全部是已知的**（设备行为与规格不符 / 复跑翻转 / broken-vacuous / 语法拒 / fork infra），但**具体的设备知识缺口全部是新的**（会话保持超时不清、service-ip 变更不同步、AAAA/MX/CNAME 记录不服务、IPv6 listener 访问）。即：**已知类型、新机制**。

### 1.1 逐案分类表（12 个非通过案）

> 归类列：`〔类型〕` 用 dongkl 审计三性质（A 断言缺陷 / B 配置构造 / C 设备·环境）+ 我的 T 编号（若命中）；`NEW-x` = T1–T10 未覆盖的新机制。引擎自归因层×处置一并列出（交叉印证）。

| autoid(尾6) | 意图 | 失败签名（设备实证） | 引擎归因 | **归类** |
|---|---|---|---|---|
| **517027** | AAAA 会话保持·IPv4 访问 | r1: `dig AAAA` 无返回；r2 修好 AAAA(改用 IPv6 service IP)，唯挂 step12：超时后持久表条目**不消失**(`www.zyq.com 172.16.34.0 AAAA 0 fc00::231`, Timeout=0) | V/defect_candidate→失联 env_blocked(user 停) | 〔C〕**NEW-1 会话保持超时不清除**（类型≈T5「测试暴露设备-规格差」；failed_terminal） |
| **532862** | AAAA 会话保持·IPv6 访问(空 host) | 超时后条目 `www.zyq.com 3ffb:: AAAA 0 fc00::231` 仍在(Timeout=0)；IPv4 同测(517027)超时后表为空 | **product_defect**/defect_candidate → suspended | 〔C〕**NEW-1 同上·IPv6 尤甚**（缺陷候选；suspended） |
| **600046** | 会话保持后改 service ip | 改 service ip 后旧 IP 持久条目不清(`www.zyq.com 172.16.34.0 A 9 172.16.35.231` 旧.231+新.213 并存)；手册空白 | V/defect_candidate + G/reflow(`^`) → env_blocked(user 停) | 〔C〕**NEW-2 service-ip 变更不同步会话表**（failed_terminal） |
| **516576** | CNAME 会话保持·IPv6 访问 | `dig @172.16.34.70 www.zyq.com AAAA +short` 无返回；ask 主题 = CNAME 持久下 AAAA 查询语义 | V/**expectation_suspect** → suspended | 〔C〕**NEW-3 记录类型/查询类型语义**（脑图预期存疑；suspended） |
| **588990** | clear session，QueryType=ALL | 期望设备**拒** ALL 参数(`不支持/Invalid`)，设备实际**接受不报错**(`clear sdns session persistence www.zyq.com ALL` 无错误回显) | V/**expectation_suspect** → decision「预期以实机为准」 | 〔C〕**脑图预期照抄**（作者前提错，≈dongkl 588990/681749 型；已裁决 correct） |
| **516942** | AAAA 会话保持·IPv6 访问 | `dig @3ffc::70 AAAA` + 持久表 AAAA 行找不到(池只配 IPv4 service IP)；且 fork 无输出触发 escalated | V/defect_candidate + **fork watchdog** → escalated | **NEW-4 AAAA 记录不服务**(池缺 IPv6 service) + **δ fork infra**（escalated） |
| **516484** | ALL 会话保持·IPv4 访问 | A 有返回；**AAAA/MX/CNAME dig 全空**(`fail to find dig @... AAAA/MX/CNAME +short`) | G/reflow(ALL 语法) + contradicted→failed | **NEW-4 非 A 记录服务缺口**（+复跑翻转 contradicted，≈dongkl 778041 型） |
| **588691** | clear session，QueryType=CNAME | `dig @... CNAME +short` 空 + 持久表 CNAME 行找不到；`show statistics sdns session persistence` 后带 `^` | G/reflow(`^`) + V/rerun_isolated → contradicted→failed | **NEW-4 CNAME 记录不服务**（+语法拒≈T8 + 复跑翻转） |
| **533020** | A 会话保持·IPv6 访问(空 host) | `dig @3ffc::70 www.zyq.com A +short` 无响应；屏注「fork 判 s₀ 但机械配对判无污染者——不升格」 | V/rerun_isolated → contradicted→failed | **NEW-5 IPv6 listener(3ffc::70)访问无响应**（+复跑翻转） |
| **561213** | 删除不存在的会话保持配置 | 连续 2 轮 broken/not_run；`Host not found`；执行失败标记致后续断言 vacuous(44) | **E/reflow**(vacuous) → escalated | 〔C〕**γ 执行 broken/vacuous**（≈dongkl 994957 型；infra/床） |
| **589503** | 删除当前不存在的会话 | 连续 2 轮 broken/not_run；`fail to find 172.16.33.254`(疑床/管理面地址) | **E/reflow**(vacuous) → escalated | 〔C〕**γ 执行 broken/vacuous**（infra/床；escalated） |
| **532436** | ALL 会话保持·IPv4 访问 | fork 无输出(tail=none，墙钟看门狗)，从未产出 last_run 设备结论 | escalated(no fork output) | **δ fork infra**（引擎侧墙钟，非 excel 逻辑；escalated·未上机） |

### 1.2 与 T1–T10 / dongkl 类别的映射结论

**（a）T1–T10 分布/权重族命中数 = 0。** zhaiyq 非通过案无一测池分布 rr/wrr/ga，故 T1（落点钉死）、T2（跨客户端轮转）、T3（Hit 计数）、T4（WRR 模型）、T5（GA 恒选）、T7（wrr 漏权重）、T10（新池入轮）**全不适用**。潜在残影：会话保持断言"10s 后命中**不同的** pool"隐含一个 T1 式假设（超时后下一次落在特定的另一池）——但它**不是本批任何失败的成因**（失败都在 AAAA-不服务 / 超时不清 / infra），仅标为潜在脆点供设计层留意。

**（b）失败"类型学"已知（命中率高），但机制全新。** 逐案的类型都能落进 dongkl 审计的 C 性质或引擎既有 infra 类：
- **〔C〕设备行为与规格不符**（测试正确暴露设备-规格差，同 dongkl 发现①②、681749 GA、T5 型）：517027、532862、600046、516576、588990 —— **5 案**。
- **〔C〕复跑翻转 contradicted**（同 dongkl 778041 型床/复跑不稳）：516484、588691、533020（叠加）—— writeback 交付时被复跑推翻回滚。
- **〔C〕broken/vacuous 执行失败**（同 dongkl 994957 型，原理层 (44)）：561213、589503 —— **2 案**。
- **语法拒 `^`**（同 dongkl T8 型，G 层）：588691、600046、516484 的 persistence 命令带 `^`。
- **δ fork infra**（引擎侧墙钟看门狗，非 excel/设备）：532436、516942 —— **2 案**，属编排层非编写逻辑。

**（c）新机制（NEW，需入判例/缺陷候选，非 T1–T10 能覆盖）——这是本批真正的增量：**
- **NEW-1 会话保持超时不清除**：超时后 `show ... session persistence` 条目应消失，设备保留且 Timeout=0；IPv6（532862）比 IPv4（517027）更严重。→ **产品缺陷候选**。
- **NEW-2 service-ip 变更不同步会话表**：改被保持的 service ip 后旧 IP 条目不清（600046）；手册空白。→ **缺陷候选/需产品澄清**。
- **NEW-3 记录类型/查询类型语义**：CNAME 持久下用 AAAA 查询（516576）、clear ALL 参数是否受支持（588990）——脑图预期与设备语义不符。
- **NEW-4 AAAA/MX/CNAME 记录不服务**：池只配 IPv4 service IP 时 AAAA 查询无返回（516942/516484）、CNAME/MX 同样空（588691/516484）。→ **配置构造知识**：serve 某记录类型需池内配对应族的 service（AAAA 需 IPv6 service IP）；或设备本不服务该记录类型（需实机确认）。
- **NEW-5 IPv6 listener 访问无响应**：`dig @3ffc::70`（IPv6 监听地址）无解析回应（533020/532862/516942）。→ 需确认 IPv6 listener 配置/床 IPv6 连通性。

### 1.3 引擎处置是否框定正确（旁证）

引擎自归因与用户裁决口径一致、无 env-vs-缺陷假框定：517027/532862/600046 判 defect_candidate（其中 532862 已入 `product_defect` 层）；516576/588990 判 expectation_suspect（脑图预期存疑，走 ask）；561213/589503 判 E 层 vacuous reflow（执行失败）；533020/588691 fork 疑 s₀ 但机械配对无污染者→不升格、保留深归因（正确的保守）。**结论：引擎把"设备缺陷/预期存疑/执行失败/污染存疑"四类分得清，与 dongkl 同期水平一致。**

---

## §2 设计缺口命中与设计层根因〔design-review〕

> 对照 `team_design_doc_gaps.md`（五缺陷设计定位）+ `team_final_synthesis_fix_plan.md`（第⑥步修复方案 A–H）核对：zhaiyq 是不同子系统（会话保持，非池分布），却**再次实弹命中了同一批"闭环断腿"结构缺口**，且暴露两个清单外的新缺口。证据全部机读自 `facts.jsonl`（365 事件）+ `last_run.json`（52 案）逐案归因序列。

### 2.0 一句话

**理论路由（不加内容依赖硬门）继续被背书**——本批 expectation_suspect / defect_candidate 出口**真的firing了**（588990/532862，比 dongkl「0 落方法桶」有实质改善）。但 fix_plan 点名的**三条闭环断腿在 zhaiyq 原样复现**：①观察入库漏 S_SUSPENDED——本批最高价值的一条设备缺陷观察（532862 IPv6 会话保持不清除）正走向 suspended、**将被结构性丢弃**；②对照差分不机械触发——517027/532862/600046 是**同一设备行为**却拿到**三种不同处置**（reflow/defect_candidate/env_blocked），因为跨兄弟对照只发生在 attributor 散文里、无机械触发；③归因随轮次churn、无单调粘性——defect_candidate 早达却被后轮 reflow 覆盖。另有两个新缺口（§2.2）。

### 2.1 已知缺口命中清单（fix_plan A–H 对照）

| 缺口(来源) | zhaiyq 是否再命中 | 实弹证据 | 与 dongkl 对比 |
|---|---|---|---|
| **(A) 观察入库漏 S_SUSPENDED**（team_gaps §二A / fix_plan B3·A2；"本次最重要单点发现"）| **命中，且casualty更重** | `nodes.py:2270-77` 只收 `S_TERMINAL+S_ESCALATED`（已只读复核，未改）。本批 `suspended=2`（516576/532862），`uncertain_ingested=0`。**532862 归因=`defect_candidate`**（引擎自判"产品缺陷"级！fix_direction 已含 IPv6 超时不清+IPv4 对照），但状态=suspended（auto-cap:3 无人应答）→ **这条 defect-grade 观察永不入 footprint**。入库门键**case 状态**非**观察价值**：引擎判了缺陷、状态门却把它丢了——比 dongkl（观察价值更低）**更尖锐的自相矛盾实例** | dongkl 8 挂起案观察丢失；zhaiyq 丢的是**已被引擎判为缺陷候选**的那条 |
| **(B) fail→reflow 偏置 / 前提证伪不触发非重编出口**（team_gaps §二B / fix_plan F11）| **命中（部分改善）** | 处置分布：**reflow 10** / env_blocked 2 / defect_candidate 2 / expectation_suspect 2 / rerun_isolated 2（reflow 仍占多数 10/18=56%）。**改善**：非重编出口firing了（588990→expectation_suspect靠**手册**反证 ALL 合法；532862→defect_candidate靠**兄弟对照**）。**残留**：device-runtime 前提证伪（无手册钩子）仍走 reflow——517027 step12「超时后条目不消失」、533020「超时后不换池仍 p1」都是前提被设备证伪，却拿 reflow/rerun_isolated | dongkl 19:2 极端；zhaiyq 10:8 —— 有**文档钩子**（手册/兄弟）时能转出口，**纯设备行为矛盾**仍偏 reflow |
| **F11 对照差分机械触发缺失**（fix_plan F11·E10a）| **命中（关键）** | 9 个 `common_cause` 事件全按**共享 dig 命令**分组（找污染者用），**不是**"兄弟案同断言 PASS ∧ 本案 FAIL→前提证伪"。真正的跨兄弟对照只发生在 **attributor 散文**里（532862 cap 面板逐字引 517027："IPv4 超时表为空、IPv6 条目仍在"）。后果=**同一设备行为三种处置**（532862 defect_candidate / 517027 reflow→env_blocked / 600046 env_blocked）——LLM 各案独立判、无机械对照器统一，**靠散文碰运气** | dongkl 未跑该对照；zhaiyq 正面复验，坐实"对照在场但只在散文层、未机械化" |
| **§0.1 advisory 唯一可机判留白：序列↔周期自洽**（team_gaps ⑤ / fix_plan E10b）| **本批未触发**（无分布案） | zhaiyq 零池分布案，E10b 无用武之地。**潜在残影**（exec-replay §1.2a 同判）：会话保持"超时后命中**不同**池"隐含 T1 式确定序列假设（533020 的"应换 p2"）——同族脆点，本批非成因 | 待下批分布案复验 |
| **footer emit_tick 丢 broken 三态**（tui 队已锤 51<53）| **命中，可交叉印证** | 台账 latest-verdict：pass 43 / fail 7 / **broken 2**（561213/589503，均"2 连 broken/not_run"escalated）。**53 − 2(broken) = 51**，恰等 tui 队 footer 数——**broken 三态在台账有 verdict 却不进 footer tick**，两队独立数据吻合 | 同一 emit_tick 缺陷跨批稳定复现 |

### 2.2 清单外新缺口（zhaiyq 首次暴露）

**新缺口 N1 — 归因随轮次 churn、无单调粘性（disposition 非单调）**。逐案归因序列（`facts.jsonl` attribution 事件）：
- 517027：`(r1 defect_candidate)→(r2 defect_candidate)→(r3 reflow)→(r99 env_blocked)`
- 600046：`(r1 rerun_isolated)→(r1 defect_candidate)→(r2 reflow)→(r3 defect_candidate)→(r99 env_blocked)`

同一案的处置在 defect_candidate / reflow / env_blocked 间反复横跳，**最强/最特异出口（defect_candidate）早达却被后轮 reflow 覆盖、终态落 env_blocked**。fix_plan F11 管「怎么触发」非重编出口，DESIGN §A「归因修法生效性闭环」管「证伪的方向别再开」——**都没管「已达的强出口要粘住、别被后轮弱化」**。缺一条**处置单调律**（disposition 应朝终态特异性单调：defect_candidate/expectation_suspect 一旦有据达成，后轮非有新反证不得退回 reflow）。这与 (40) 满射「每类一出口」正交——(40) 说去哪，没说**跨轮别乱跳**。

**新缺口 N2 — 「fork 疑 s₀ ∧ 机械配对无污染者」默认 rerun_isolated → subset-pass 与 delivery-fail 振荡（livelock 风险）**。533020：`diagnosis: h_position=h_s0, polluters=[], basis="fork candidate (no batch-level counter-evidence)"` → 处置 `rerun_isolated` → 2 案隔离子集 PASS → provisional 写回 → **但整卷 delivery 被 `rollback reason=contradicted_at_delivery` 推翻**（与 516484/517027/588691 同一 delivery:70 批量回滚 4 案）→ 又回子集 PASS。**振荡形态**：subset 过、整卷挂（[[run13-regenerating-polluter]] 同型）。exec-replay §1.3 视其为"正确的保守"，但设计层看：fork 的 s₀ 假设（会话态自污染）与机械配对的"无污染者"**分歧未被裁决**，引擎默认走**受害者出口**（rerun_isolated）；若 533020 实为 s₀ 自污染，隔离 PASS 是**假阴性**、下次整卷必再 contradicted——(40) 明写"自污染者被错配受害者出口(复跑)=毒药出口"。**回滚洗白机制在场（好），但无"subset-pass→delivery-fail 后找前驱恢复案"的收敛通路** → 停在振荡。缺一条**污染判定分歧的裁决规则**（fork h_s0 假设 vs 机械无污染者冲突时，路由到 ask/深归因 而非默认 rerun_isolated）。

### 2.3 §1.2(c) NEW 机制的分层归属（回应 §2 placeholder 之问）

| NEW 机制 | 层归属 | 依据（team_gaps/(47)/(40)） |
|---|---|---|
| NEW-1 会话保持超时不清除 / NEW-2 service-ip 变更不同步 | **产品缺陷候选**（出缺陷单）+ 判例层观察（`validity=uncertain`）| 设备行为与规格矛盾、无手册依据、多案复现（517027/532862/600046 交叉印证）→ (40)「真缺陷」出口；**前提是入库腿修好（A2/B3）否则观察进不去** |
| NEW-4 AAAA/MX/CNAME 记录不服务（池需配对应族 service）| **worker.md 构造知识**（L_model 陈述式）+ 判例层 | "serve AAAA 需池内配 IPv6 service IP"是**配置构造依赖**——类同 team_gaps ④（wrr 缺 priority）的**共需/依赖类**；可入 fix_plan B1' 的 co-required 类型（若上机钉死记录类型↔service 族匹配是硬约束），否则先判例层观察 |
| NEW-3 记录/查询类型语义（CNAME 下 AAAA、clear ALL 支持性）| **L_human（expectation_suspect→ask）** | 脑图预期 vs 设备语义分歧、且**有手册可裁**（588990 靠手册反证）→ (40)「期望可疑」；已正确firing，无需新机制 |
| NEW-5 IPv6 listener 访问无响应 | **判例层观察 + C7 上机钉死清单** | 需实机确认是 listener 配置缺失还是床 IPv6 连通性 → 归 fix_plan C7「必须上机钉死」清单，钉死后转 verified |

**会话保持"超时换池"T1 残影**（placeholder 之问）：本批非成因，但 533020 的"超时后应换 p2"确是 T1 式确定序列假设。建议 worker.md 收紧（fix_plan D8 同款陈述式）：会话保持超时后的**下一次落点**由运行时定、不假设特定池，验证轴应是"超时后**条目状态变化**"（清除/Timeout 归零）而非"落到某具体池"——这恰好也是本批真正被测到的（NEW-1）、且是设备行为分歧点。

### 2.4 结论

zhaiyq 用一个**完全不同的子系统**（会话保持 × A/AAAA/MX/CNAME × IPv4/IPv6）复验了 dongkl 合成的结论：**理论路由对（不加内容依赖硬门，非重编出口本批真的firing了）；病在闭环三条断腿**——(A) 观察入库漏 S_SUSPENDED（本批丢的是 defect_candidate 级观察，比 dongkl 更尖锐）、(F11) 对照差分只在散文层无机械触发（同一设备行为三种处置）、(B) reflow 仍偏置且**归因跨轮 churn 无粘性**（N1）。外加一个新的**污染判定分歧振荡**（N2，533020 subset-pass↔delivery-fail）。fix_plan 的 A2/B3（入库补 suspended）、F11（对照差分机械触发）是**最高杠杆**，本批实弹再次坐实其必要性；建议补 **N1 处置单调律** 与 **N2 污染分歧裁决律** 两条。〔design-review 署名〕
