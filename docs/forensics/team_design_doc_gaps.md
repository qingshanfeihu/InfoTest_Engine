# 实证缺陷反查设计缺口 —— 五类失败 × 设计定位 × 缺口定性

> 任务:拿昨晚 dongkl/yzg 实机暴露的五类缺陷,反查**设计文档与方案**把缺口钉准(不开完整方案,先钉缺口)。
> 证据源:`dongkl_excel_quality_audit.md`(§五设备实机回显)+ `dongkl_yzg_langfuse_failures_review.md`。
> 设计源:`DESIGN_dongkl_finalization.md`(§0.1/§A/§B)、`THEORY_k_state_machine.md`((47)/(40)/(44)/§2.5/§2.7)、
> `enforcement_locus_research.md`、`compile-worker.md`、`verifiability.py`、`domain_grammar.json`、编译引擎 `uncertain.py`/`nodes.py`。
> 只读调查,零代码/配置改动。整理:2026-07-16。

---

## 零、总判(先读这段)

**五缺陷里只有一条(④ wrr 缺 priority)是干净的"结构门/文法层真空",其余四条都不该加硬门。** 这与团队 `enforcement_locus_research.md` 的 **⚠ 关键纠正**(2026-07-16 用户"为什么它死"挑战驱动)、DESIGN §0.1、K (47) 已裁决的方向**一致**:分布形态硬门化 = GA-CUT 回归。①②③⑤ 的病灶与 593516 **同型**——机制在场(verifiability/worker 指引/footprint 判例),但因 worker 分类灰区**不触发**,或因判例层触发路径**断裂**。

**但反查揭出两处比单案更值得修的结构耦合缺陷**(见§二):(A) 自愈观察入库门耦合到 case 终态、**漏 suspended**——正好掐断这五类最富信息的挂起案观察;(B) fail 处置**默认偏 reflow**(实证 19:2),"脑图前提被设备证伪→期望可疑/观察入库"的分流触发只有一例、未推广。

---

## 一、五缺陷 × 设计定位 × 缺口定性(主表)

| # | 缺陷(实证) | 现行设计条文 | 名义位阶 | 缺口定性 | 该补哪层 · 零代码检验 |
|---|---|---|---|---|---|
| ① | 跨客户端轮转前提被证伪(777976/778041/593484:client2 不轮到 p2、p2 恒 Hit:0) | worker.md:94-99(dig=运行时选中→分布 claim);verifiability `absolute_position`(:34,「某客户端命中第N个pool」→不可证伪→改预期) | L_model(分类)+L_oracle-B(verifiability) | **覆盖但未触发 + 判例触发路径断裂** | L_model(worker.md:脑图"某客户端→某池"= rewritable claim 须 falsify)+判例(footprint 需"本 build 无跨客户端全局轮转"观察)。footprint 半=数据✓,**但 ingest 漏 suspended→数据进不来**(见§二A) |
| ② | Hit 计数器不可靠(681749:dig 返回成员却 Hit:0) | worker.md:74-99(hit count 是 sample 非 invariant;channel 分 sample/member) | L_model(worker 构造) | **未覆盖** | 判例(footprint:"本 build Hit 可 0 despite 返回成员,不作分布唯一支点")+L_model(worker.md:分布验证须 dig 返回分布 ∧ statistics **两证据面**交叉)。均=数据/prompt✓,**非**文法/门。同受§二A 断裂 |
| ③ | 成员 IP 配错 show 命令(593516:成员 IP 断言配在只列池名的 `show sdns host pool`) | worker.md:100-109(667986 教训:断言前 dev_probe 确认实际输出 layout);domain_grammar **无**命令→输出域 schema(已验读) | L_oracle(probe)+L_model | **覆盖但未强制/未触发**(与 667986 同型) | 维持 L_oracle(dev_probe)+强化 worker.md(断言字面成员 IP 前先 probe 来源命令输出域)。**不建输出 schema 文法门**(输出形态是随 build 漂移的数据,建门会误杀,违 §0.1 A 层"不误杀好制品")。可选 footprint 提示=数据✓ |
| ④ | wrr 缺 priority(572672/572708:设备逐字"priority must be valid when method wrr") | CLAUDE.md"dangling-reference 类=加 reference_closures 零代码";domain_grammar `reference_closures` **仅 1 条**(cname),schema=references/defines(**为跨对象引用设计**) | (被 §0.1 分布路由/散文漏掉) | **类型缺失(设计缺类型)+ 数据缺失** | **文法层新增"共需参数(co-required)"闭合类型** → emit 结构门(config-completeness)。协议级硬事实(任何值都被拒、内容无关)= L_struct A 层合格。零代码检验:**首次需一次性加类型+读取器(代码)**,之后=数据✓。**∴ "零代码"承诺对本缺陷不成立** |
| ⑤ | 精确计数/单次落点/时序自洽(593484 Hit:3·Hit:2、778012 时序锚 vs 周期矛盾、777976 单次钉) | verifiability `weight_ratio`(需≥Σweights)/`absolute_position`/`new_member_last`;§0.1 分布→L_oracle-B advisory | L_oracle-B | **部分覆盖 + 一处可机判真空** | 计数充分性(593484/777976)= verifiability **覆盖**(若被调,同①灰区)。**778012 请求序列↔断言序列的周期自洽性:verifiability 入参全标量(algo/n_req/n_pool/weights),无逐位置序列→根本推不出;emit `claim_kinds_preserved` 也不做逐位置轮转数学→谁都不查**。可选 L_struct 窄门(位置↔周期,内容无关可机判)或扩 verifiability 收 position-sequence=一次性代码 |

### 逐条详述(关键证据 + 定性推理)

**① 跨客户端轮转前提** — 这不只是"excel 假设了确定顺序",设备实测把**脑图作者的预期本身**("客户端2→命中第二个 pool")证伪了(routerA/routerB 都从 p1 起、p2 恒 Hit:0)。三层缺口:
- (a) worker 把脑图前提当 ground truth、不当 rewritable_claim → 不调 `compile_check_verifiability`(与 593516 claim_kind 灰区**同型**);
- (b) 即便调了,verifiability 对 absolute_position 的 remedy 是"改预期→relation_diff(连续两次不同池)"——但这**仍预设跨客户端轮转存在**;而设备证伪的正是这个前提。"本 build 无跨客户端全局轮转"是 **L_oracle(上机)**才能定的地面真值,verifiability 的标量数学推不出;
- (c) 判例层没有这条观察。**已验读** `knowledge/footprints/nodes/statistics.sdns.pool.json`:有单次落点非确定(6b921beb)、有 Hit 累计不清零(68d00a54),**无跨客户端轮转缺失**。且这些案全挂起(S_SUSPENDED),observation-ingest 漏此态(§二A)→ 未来 worker 无触发路径质疑前提。

**② Hit 计数器不可靠** — worker.md 已把 hit count 当"**会波动的样本**"(sample-vs-invariant),但不知它可能"**坏**"(该增没增,681749 dig 返回 213/Success 却 `Hit:0`)。"分布验证需多证据面(dig 返回分布 ∧ statistics 交叉)"这条要求**设计里不存在**。footprint 的 68d00a54 是"多算了(累计)"、方向相反,不覆盖"该增没增"。→ 判例(观察)+ worker 指引,**非**机械可判(不可能机械断"计数器坏了")。

**③ 成员 IP 配错 show 命令** — worker.md:100-109 的 667986 教训**已经**要求"断言前用 dev_probe 确认实际输出 layout(clean 编译期设备也显命令行列形态)"。593516 的残留正是**没 probe** → 把成员 IP pattern 放到只列池名的命令。要 emit 门机械拦"断言 pattern 与来源命令输出域不匹配",就得把**每命令输出 schema** 建进文法 = 恰是项目红线禁止的"随 build 漂移的数据表"(`[[reference-docs-mechanism-not-data]]`)。∴ 设计**有意**不机械化,落 L_oracle(probe)+L_model;缺口是**该 probe 没 probe**(强制不足),与 667986 同族,不是设计缺类型。

**④ wrr 缺 priority** — **回答"为什么这条没有"**:这**不是**"设计正确、数据没喂",是**类型装不下**。wrr 缺 priority **不是悬空引用**(X 引用未定义的 Y),而是**同语句内共需参数**(method=wrr → 必带 priority)。现行 `reference_closures` 的 schema(references/defines/normalize/footprint_node)是为**跨对象引用闭合**设计的,`statements`/`anchoring_chains` 也无参数依赖类型(已验读顶层键)。CLAUDE.md 的"dangling-reference 零代码"承诺**范围本就不含**共需参数——被 forensics 归成"dangling-reference 类"是**归错类**。而此约束是**协议级硬事实**(设备逐字拒、任何值都拒、内容无关)→ 按 §0.1 判据("任何设备回显下恒真/恒假/必崩、内容无关"→结构门)+ A 层"误判即必然真错、不误杀好制品"(无合法的 wrr-without-priority 卷)→ **L_struct 合格门**。这是五缺陷里**唯一**干净的文法门真空。(注:778012 的"host does not exist"是另一类——悬空引用/锚定链完整性,理论上 `anchoring_chains`/`reference_closures` 可覆盖,与 wrr-priority 不同族。)

**⑤ 精确计数/单次落点/时序自洽** — 拆三段:
- 593484 Hit:3/Hit:2(精确计数)= `weight_ratio`(3 < Σ6),777976 单次钉 = `absolute_position` → verifiability **能判**(若被调,同①灰区);
- **778012 时序锚 vs 轮转周期矛盾** = 真空:"found 225 于第 4–8 次"但 RR 周期 4 → 第 5/6/7 次必命中 p1/p2/p3(必假)。`check_verifiability(algo, n_requests, n_pools, weights, claim_kind, existing_pools)` 入参**全是标量**,**无逐位置序列**,推不出跨步矛盾;emit `claim_kinds_preserved` 只核对 decided claim_kind vs 产出形态(见 593545 欠定原文),不做逐位置轮转数学。**593545 是 worker 自己**推出 WRR 周期 vs absolute_position 锚不兼容并 raise NEEDS_USER_DECISION——**靠 worker 自觉,非机制保障**;778012 就没被自觉逮住。

### §0.1 把分布类路由到 L_oracle-B(advisory),对这五类都对吗?——**不全对**

| # | §0.1/dist 路由 | 是否适配 |
|---|---|---|
| ① | L_oracle-B advisory | **不足**:verifiability flag 后 remedy 仍预设跨客户端轮转存在→需 L_oracle(上机地面真值)+判例;advisory-only 会每批重 fail |
| ② | (归入分布) | **不适用**:计数器不可靠非 verifiability 数学问题→判例+worker |
| ③ | (归入分布) | **不适用**:命令→输出域非 verifiability 触及→probe+worker |
| ④ | (被分布路由带过) | **错**:根本非分布,是 config-completeness→L_struct 文法 |
| ⑤ | L_oracle-B advisory | 计数充分性**对**;**序列自洽性 verifiability 标量模型盖不住→留白**(可机判却没做) |

**结论**:§0.1 把"分布类→L_oracle-B advisory"作为**统一路由**过粗——④非分布(应 L_struct)、②③非 verifiability 数学(应判例/probe)、⑤有一段可机判却在 advisory 路由下留白。只有①的欠定面与⑤的计数充分性真正落在 L_oracle-B。

---

## 二、横切结构缺陷(两处,比单案更值得修)

### A. 自愈观察入库门耦合到 case 终态,**漏 S_SUSPENDED**(掐断①②③⑤的判例触发路径)

- **机制在场**:K §2.7 行动论 (22)-(25)"判断开放、入库门闭合";`compile_engine_v8/uncertain.py::_ingest_uncertain_observations` 把 fail/escalated 案的设备观察以 `validity="uncertain"`+`observed_under` 入 footprint,PASS 实证后 merger 升 verified。
- **断裂点(已验读代码)**:`nodes.py:2270-2277` 的适配器 `_Led.in_state` 只映射 `"failed_terminal"→S_TERMINAL`、`"escalated"→S_ESCALATED`,**不含 `S_SUSPENDED`**。而 `views.py:33` `S_SUSPENDED="用户裁决挂起(非终态:下批同参续跑)"`。
- **后果**:dongkl 8 个分布案(777976/778012/778072/593484/593516/681749/572672/572708)全被用户**挂起**(langfuse 台账:"你选挂起,留待下批")= S_SUSPENDED → **它们的设备观察永不入 footprint**。这正是暴露①(跨客户端)②(Hit:0)③(错命令)⑤(周期矛盾)最富信息的一批案。这解释了为什么 footprint `statistics.sdns.pool` 缺这几条观察。
- **定性**:**设计耦合缺陷**——把**知识增长**绑死在**行动侧处置**(terminal/escalated)上,与 §2.7 自身论旨("知识可自愈生长、行动不能——不对称即缺口";知识侧应独立于行动侧生长)**相悖**。观察是否有效取决于"是否做了设备观察",不该取决于"用户把案子挂起还是判终态"。
- **补在哪**:ingest 状态谓词纳入 S_SUSPENDED(挂起=非终态但已上机、已有回显)。一次性代码改 `_Led.in_state` 白名单;之后观察=数据✓。**这是①②能真正落地的前置**(否则 worker.md/footprint 两半改了,数据仍进不来)。

### B. fail 处置**默认偏 reflow**,"脑图前提被证伪→期望可疑/观察入库"触发只有一例

- Brief 5 data-miner 实证:combined fail 处置 = **reflow 19 主导** / env 1 / expectation 1 / defect 2;**分布敏感 fail 6 → 5 reflow + 1 env → 0 落"期望可疑/方法不当"桶**。
- (40) 处置分类学(§2.12.1)有"期望可疑(R 与实机+第三源矛盾)→F1 面板""真缺陷→缺陷候选单"格子,但分布失败**实际几乎全默认 reflow**,没被判成"脑图前提被设备证伪"。DESIGN §A 的 attributor 自查只覆盖**一种**触发(配比×样本量≫0 却 Hit:0 → 提示缺陷),**未推广**到①的"跨客户端前提被证伪"。
- **定性**:(40) 满射在**实践中偏斜**——理论骨架全,但触发弱、缺省出口是 reflow,把"测试暴露了设备-规格差"的价值当成"excel 写错了"一味重编。

---

## 三、元问题审查:fail→重编 vs fail→观察入库/缺陷候选 的分流判据

**在哪文档哪节**:K §2.12.1 (40) 处置分类学(`THEORY:706-730`,7 类满射)+ §2.7 行动论(观察入库机制)+ §2.6.6 对称怀疑(冲突→标记交裁)+ DESIGN §A(配比×样本量→缺陷提示)/§B(env_blocked 同案自查)。

**清晰吗**:**原则层清晰**(7 类完备、每类一出口)。**触发层不够**,三处实证短板:
1. **缺显式触发**:"脑图前提 vs 设备行为矛盾 → 期望可疑(非 reflow)"只有配比×样本量一个特例(§A),未推广到跨客户端前提(①)、GA 恒选性(681749)、pool stat 不涨(778072)这些"设备-规格差"实况。
2. **默认出口偏斜**:实证 reflow:defect = 19:2,分布敏感 fail 0 落期望可疑桶——满射在实践中塌向 reflow。
3. **观察入库腿被掐**:§二A 的 suspended-exclusion 使"转成设备行为观察(footprint)/缺陷候选"这条腿对挂起案**物理不通**——而挂起案正是设备-规格差的高发地。

**够不够**:**不够**。判据有骨架(7 类),但(测试的价值=暴露设备-规格差) vs (缺陷) vs (重编)的三分,在**触发**与**默认出口**两处偏向 reflow,且观察入库腿被 suspended 掐断。forensics §五结论 5 已点名:"777976/778041/593484/681749 应转成设备行为观察/缺陷候选,而非一味重编去迁就可能过时的脑图预期"——现行设计接不住这句。

---

## 四、结论与修法落点优先级(先钉缺口,不开完整方案)

1. **唯一干净的结构门真空 = ④**:文法层加"共需参数(co-required)"闭合类型 + config-completeness emit 门(A 层安全,协议硬事实)。附带纠正 CLAUDE.md"dangling-reference 零代码"承诺的**类型边界**(共需参数≠悬空引用)。**优先级高**(一次性加类型,之后纯数据;且 forensics §四.4 已表态"该在 emit 门前拦")。
2. **前置基建 = §二A**:observation-ingest 纳入 S_SUSPENDED。**优先级最高**——不修它,①②的 worker.md/footprint 改动**数据进不来**,等于空转。
3. **①②③⑤ 主体 = 不加硬门,接通已在场机制**(与 (47)/§0.1/⚠纠正一致):
   - ① worker.md:脑图"某客户端→某池"= rewritable claim 须 falsify;footprint 载"本 build 无跨客户端全局轮转";
   - ② worker.md:分布验证须 dig 返回分布 ∧ statistics **双证据面**;footprint 载"Hit 可 0 despite 返回成员";
   - ③ worker.md:断言字面成员 IP 前先 dev_probe 来源命令输出域(强化 667986);
   - ⑤ 计数充分性接通 verifiability 触发(同①灰区);**778012 序列自洽性**是可选窄门(位置↔周期,内容无关可机判)或扩 verifiability 收 position-sequence——这是 §0.1 advisory 路由**唯一**留白的可机判 check,值得单独定夺。
4. **分流判据 = §二B**:attributor 自查从"配比×样本量"一例**推广**到"脑图前提被设备行为证伪→期望可疑/观察入库,非 reflow";并给分布失败一个非-reflow 缺省的显式判据(否则 (40) 满射实践偏斜)。

**一句话**:五缺陷里 ④是真·结构门缺口(且暴露文法类型边界),①②③⑤是"机制在场、触发/入库断裂"——**别再加分布硬门(=GA-CUT)**,该修的是 worker 分类灰区、footprint 触发路径、以及两处结构耦合(挂起案观察入库、fail 处置默认偏 reflow)。
