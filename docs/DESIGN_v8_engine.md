# V8 编译引擎设计（理论驱动全新版，抛弃 V6 包袱）

> 2026-07-10。地基：`THEORY_k_state_machine.md`（三合取 / K 状态机 / §5.5 四公理）。
> 设计准则：①每个机制必须能指认它实现的理论构件——落不进理论=不进 V8；②skill 封装逐条对齐
> Claude 官方 Agent Skills 规范，做成标杆样本；③V6 的兼容包袱一律不背（清单见 §7）。
> 版本号 V8：V7 留给「V6+缺口 E 补丁」的假想线——我们不走那条线。

---

## 0. 一句话架构

**用例编译 = 在事件溯源台账上运行的三合取装配线**：
确定性图（py）搬运事实，语义判断进孔（fork skill），用户裁决走三条 ask 边；
一切上机裁决是**不可拒收的事实**，状态是事实流的**派生视图**——吞裁决在结构上不可能。

## 1. 理论 → 架构映射表（V8 的存在性证明）

| 理论构件 | V8 机制 | V6 的对应缺陷 |
|---|---|---|
| 合取③语境参数 Pass(c, ctx)（公式15） | 裁决事实携带 `ctx ∈ {subset, delivery}`；交付判据=派生谓词 `deliverable(c) ≝ latest_verdict(c, ctx=delivery)=pass` | passed 是无语境布尔，∃-pass 冒充交付-pass |
| oracle 残差公理（公式16） | **事件溯源台账**：裁决只能 append，不存在"写入被状态锁拒绝"；派生函数全函数化（每个事实组合都有定义的视图） | δ(passed, fail) 未定义→恒等补全→无痕吞 |
| 全射对账（公式17） | **reconcile 节点**（mech）：每轮 run 后遍历 dom(V) 折叠事实流，产出 `transitions + residuals`，残差清零才准出节点 | attribute 按 L⁻¹(failed) 反查，终验裁决整体落空 |
| 审计器权威（公式18） | 派生函数中的**权威序**：delivery-ctx 裁决 > subset-ctx 裁决 >（任何 LLM 判断）；后到的高权威事实自动改写视图 | 终验（审计器）被终态锁（被审计假设）压制 |
| K 状态机语境锚（§5.1） | 所有写回事实（先例凭证/footprint/uncertain 观察）携带 `(autoid, run_ts, build_self_reported)` 三元锚 | 锚记提交值（568 vs 实际 585）；uncertain 无锚 |
| 锚差监控 Δ(k)（公式7） | **prep 期锚差前置门**：跑前设备自述 build vs 配置 build vs K 主先例 build 三方比对，失配即 ask（不烧轮） | yzg@103 两轮 ¥160 后才靠人发现设备被换 |
| 分层可导性（§3.2） | attributor 判定树补**版本层**（show version 就在证据里）+ **跨案一致性对账**（系统性声明须与同批 pass 集分组对账） | 归因自然实验 2/19（无机械证据 0/17） |
| 矛盾即问（§5.5） | **第三条 ask 边**：`contradiction(c) ≝ ∃pass@subset ∧ later fail@delivery` 两次成立 → 开放式问用户 | ask 只有欠定/升级两条边，矛盾进不了状态机 |
| 验证盲区定理（§2） | 保真探针（intent gap）+ 单调门 + **载体维度探针**（新，A1 vlan 教训：配置对象类型词面比对）| 记录类型词面盲于载体维度 |
| 中心论断（§4） | K 健康度仪表进交付报告（先例命中率/锚差/污染标注计数），DS-4 行自动追加 | 无 |

## 2. 核心重设计：事件溯源台账（V8 ledger）

**这是 V8 与 V6 的分水岭。** 把 K 状态机 §5.3 的纪律（append-only 事实 + 派生谓词）原样搬给 case 台账：

### 2.1 事实模型（append-only，JSON lines，按批一文件）

```jsonc
{"ev":"authored",   "aid":"…", "round":1, "credential":{…}}          // 产出+过门凭证
{"ev":"decision",   "aid":"…", "question":"…", "answer":"…"}          // 用户欠定裁决
{"ev":"verdict",    "aid":"…", "ctx":"delivery|subset", "run_id":"…",
                    "result":"pass|fail", "signatures":[…],
                    "artifact":"<该案卷面指纹(凭证 mtime/hash)>",       // 对抗修:裁决绑卷面版本
                    "volume":"<整卷组成指纹(autoid集+各案指纹)>",       // 对抗修:delivery 裁决绑卷组成
                    "bed":"<跳板机/床 id>", "build":"<设备自述>", "run_ts":…}
{"ev":"attribution","aid":"…", "layer":"…", "disposition":"…", "evidence":"…"}
{"ev":"writeback",  "aid":"…", "targets":["precedent","footprint"], "voucher_run":"…"}
{"ev":"rollback",   "aid":"…", "of":"writeback", "reason":"contradicted_at_delivery"}
{"ev":"escalated" | "user_decided" | …}
```

规则：**只许 append，永不改写/删除**。V6 的 `.frozen.json`/`user_decision.json`/`last_run._attribution`
等散落 outputs/ 的旁车文件全部收编为事实类型（磁盘上只剩：事实流 + 卷面 + 交付物）。

对抗审查补的三条工程纪律：
- **单写者**：只有引擎进程写事实流（fork 产物是文件，engine 收割后 append `authored`）；
  原子追加 + 容损恢复（tmp+rename 或行级 salvage，意图索引拼接损坏的教训沿用）。
- **幂等键**：每条事实带确定性幂等键（如 `(ev, aid, run_id)` / `(ev, aid, round)`），fold 去重——
  节点「append 后、checkpoint 前」崩溃重放不产生重复语义（INV-10）。
- **前向兼容**：fold 对未知 `ev` 类型跳过不炸（新事实类型可先于消费端上线）。

### 2.2 派生视图（纯函数 fold，全函数）

```
state(aid)        = fold(facts[aid])           // 全函数:任何事实序列都有定义的视图
deliverable(aid)  ≝ ∃v: v=latest(verdict, ctx=delivery) ∧ v.result==pass
                     ∧ v.artifact==当前卷面指纹 ∧ v.volume==当前交付集组成    // 对抗修:
                     // 旧卷面的 delivery-pass 不为新卷面背书(V6 凭证 mtime 教训的事实流版);
                     // 交付集组成变了(案子增删)旧整卷裁决同样失效
frozen(aid)       ≝ 最近两条同 ctx verdict 均 fail ∧ signatures 交集非空      // #7 根治:按 aid 不按路径
transient_recur(aid) ≝ 上一 attribution.layer==transient ∧ 其后又出现 fail verdict
contradiction(aid)   ≝ ∃ pass@subset ∧ 其后 fail@delivery                   // 矛盾是派生谓词,不是异常
needs_variation(aid) ≝ disposition∈{product_defect,defect_candidate} ∧ 无换形态 verdict
```

**吞裁决在此结构下不可能**：verdict 是事实，事实必被 append；视图是纯函数，任何新事实必然
反映（或显式被更高权威事实遮盖——遮盖关系本身可查询）。V6 三个同根病（瞬态护栏 dead code、
#7 冻结失活、#10 终验吞 fail）的病灶——「消费端按自有键选择性读取」——整个消失，因为**没有
消费端了，只有视图**。

### 2.3 权威序（fold 的核心裁决规则）

```
delivery-ctx verdict  >  subset-ctx verdict  >  机械门判定  >  LLM 判断
同权威级:后到覆盖先到(时间序)；跨权威级:高权威永远遮盖低权威(即使先到)
```

pass「锁」从写屏障降格为派生规则：`deliverable` 只认 delivery-ctx——低权威写不进视图，
但**事实照常入流**（审计/翻案永远有据）。frozen 同理成为派生谓词+emit 门的必答项（override
理由作为事实 append），不再是 digest side-effect 落的文件。

## 3. V8 图拓扑

```
prep ──▶ anchor_gate ──▶ author ──▶ ask(欠定) ──▶ merge ──▶ run ──▶ reconcile ─┬▶ attribute ──▶ route ─┐
[mech]    [mech+user]    [LLM孔]    [user孔]     [mech]    [mech]   [mech]      │   [LLM孔]      [mech] │
                                                                                │                       │
              ┌─────────────────────────────────────────────────────────────────┴───────────────────────┘
              ▼
        {全部 deliverable} ──▶ final_run(ctx=delivery) ──▶ reconcile ─┬▶ 无矛盾 ──▶ writeback ──▶ report
                                                                      └▶ contradiction ──▶ (首次)重编一轮 ┐
                                                                                           (再次)ask(矛盾) ┘
```

新增/重定义节点：

- **bed_gate（床态体检门）**（新，mech+user；由 anchor_gate 升格——版本只是床态的一维）：
  跑前只读体检床态向量 B，批后对称恢复。理论定位：语境 ctx 从「排列 π」扩成「(π, B)」，
  锚差监控 Δ 从 build 一维扩到床态多维（2026-07-10 手册取证：`clear sdns all` 官方明文
  **不清 SDNS 配置文件**；segment 删除留 `.conf.tmp` 尸体且同名重建会复活；`synconfig to`
  自动写**对端**硬盘；HA 同步态与 `config memory/file` 官方互斥）。
  - **体检项**（探针命令按红线从手册/文法数据现查，可探性已审计存在）：设备自述 build
    （版本距离策略：major.minor 同族放行并记锚，跨 minor 失配 → ask）、残留 segment 与
    `.conf.tmp`、synconfig peer/ha synconfig 开关态、本机磁盘残留配置文件。
  - **床账（per-host bed ledger，对抗审查新增）**：`runtime/bed_ledger/<host>.jsonl` 记
    本引擎每批 created/restored 配对（框架 IP 恢复契约的推广）。**自动清理只限床账内
    己方未复原产物；非己方残留一律 ask 不动手**——床是共享的，别人的现场不能清（INV-9）。
  - 批后恢复节点：按床账逆序恢复；恢复失败如实入账+报告，下批 bed_gate 据账接力。
- **reconcile**（新，mech，缺口 E 本体）：每轮 run 之后唯一入账口——把 digest 全量裁决
  append 进事实流（∀c∈dom(V)，全射），重算派生视图，emit 迁移信号；任何「入账后视图无变化
  且无显式一致确认」的裁决 → `verdict_unconsumed` 残差信号（不变量：该信号在健康运行中恒零）。
- **final_run(ctx=delivery)**：终验是**带语境标记的 run**，不是特殊路径——它的裁决经同一个
  reconcile 入账，高权威自动改写 deliverable 视图。矛盾处置（2026-07-10 用户裁决 + 对抗修正）：首次 → 自动回环一轮，
  但**回环由归因定向而非盲目重编**——interference 类矛盾的正解常是「重排/隔离复跑」而非改卷
  （卷面本身可能是对的；盲重编反而把正确卷面暴露给压力路径）。attributor 拿「单跑 pass vs
  连跑 fail + 床态通道」证据判处置：reflow（真编写问题）/ rerun_isolated（互扰，重排复跑）/
  env。第二次起
  **每一次矛盾都走第三条 ask 边**（开放式：如实降级交付 / 重排卷序再验 / 接受单跑语义并标注，
  不预设选项列表；问询携带累计矛盾历史与用户既往选择）——矛盾没有静默终点，自动路径只有
  首次那一轮，其后的每次收敛决定都归用户。
- **writeback**：子集 PASS 仍即时写回（兄弟流动价值双批实证），但写回事实标 `provisional`；
  终验矛盾对该案 append `rollback` 事实并执行撤销（mirror 删卷+footprint 摘条，本次人工清污
  脚本的机制化）；终验通过则 append 确认，provisional 转正。
- **report**：如实计数从视图取（`deliverable` 集合），天然不会出现「名义 26/26」。附 K 健康度
  仪表（DS-4 行自动追加）。

## 4. 上机数据面（#7 的结构性根治）

- **单一事实源**：每批一个事实流文件；digest 的角色收窄为「跑批+取证+机械预判」，其输出
  经 reconcile 入账——**digest 不再自带跨轮对照/frozen/瞬态副作用**（这些全部变成派生谓词）。
  子集卷/整卷只是 run 的参数（ctx 与 autoid 集），不再产生各自为政的 last_run 目录账本。
- run 产物（device_context/causality 大文本）仍按引用落盘（`runs/<run_id>/`），事实流只存
  指针+签名——LLM 上下文不承载 O(N×|回显|)（载荷通道纪律不变）。
- **双账职责声明（对抗审查）**：`verified_runs.jsonl` 保留为**全局跑账**（跨批、按 autoid，
  footprint merger 的 device_verified 门照常消费，写入路径同源不产生分叉）；批事实流是
  **批状态机**。两账由同一 digest 写入点同时追加，语义上事实流为批内真理、verified_runs
  为跨批凭证索引。

## 5. 孔（fork skill）的 V8 边界

- **compile-worker**：职责不变（单 case 自由理解编写）。brief 增量：锚差门产出的
  build 自述值随 brief 下发（工作在哪个 build 上是编写事实）。红线不变（零写死命令、
  期望值溯源、单调门、载体维度探针反馈）。
- **compile-attributor**：判定树补两步——
  ①**版本层**（读表级）：evidence 里的 show version 与批锚比对，是归因第一步（yzg 自然
  实验：这一步在场时正确率 2/2，缺席 0/17）；
  ②**跨案一致性**（对账级）：做「系统性」声明前必须与同批 pass 集的性质分组对账
  （「全批失败」被 3 个不走 dig 的 pass 案反证的形态）。
- 保存族编写建议（对抗审查，C 层）：持久化家族 case 建议**案内自清**（案首/案尾清理自己
  通道的产物，清理命令从手册现查——官方存在「清除本地所有 SDNS 配置文件」类命令）；
  机制替代（clear+reload 代真重启）须在 D 列声明。
- 新孔不加。ask 的三条边都是 user 孔（官方 interrupt），不是 LLM 孔。

## 5.5 Prompt 减法纪律（less is more，2026-07-10 用户裁决——V8 第一性原则之一）

V6 的 prompt 面（worker 137 行/attributor 71 行/大量「坑」叙事）是**旧非思考模型时代的补偿层**：
用 C 层散文补 A 层机械门未建的债。V8 门已补齐（单调门/reconcile/bed_gate/共存检查），
且现行体制（思考模型+首败即升+健康 K）下 R1=24/26 的实测表明大部分防御性散文是死重。

**纪律**：
- prompt 面（SKILL.md / agents md / brief 模板 / 门违例文案）**从零重写，不从 V6 删改**。
- 每条存留规则必须通过**三选一存在性检验**：
  ① 目标系统文法事实（如 found=DOTALL 无 MULTILINE——数据层，按引用指向文法/手册）；
  ② 理论构件直接投影（合取①②③/四公理/红线：期望值溯源=合取②，零写死命令=K 数据面纪律）；
  ③ **现行体制下实测的失效模式**（思考模型+门在场+K 健康时仍复发的——旧时代坑叙事不算数）。
- **门在则 prompt 不教**：机械门强制的约束从 prompt 删除——门违例文案即 just-in-time 教学，
  且文案本身只写「机制+改法」，不写事故史。
- 坑叙事的正确归宿是**判例层**（footprint 观察/策展标注，运行时检索），不是 prompt 常驻
  （自愈合架构本来就为此而建）。
- 预算：worker md ≤60 行、attributor ≤50 行、SKILL.md ≤80 行；每条存留规则在
  references/theory-map.md 有归属行（理论构件或现行数据点）。
- 删除清单留档（`references/removed-rules.md`，一行一条+旧归属）：若新体制下某失效模式
  复现，按 ③ 以数据为据恢复——删除本身也是 eval 驱动的。

## 6. Skill 封装：官方 Agent Skills 规范逐条对齐（标杆样本）

```
main/ist_core/skills/ist-compile-engine/     # V8（user-invocable）
  SKILL.md                                   # ≤120 行:什么/何时/怎么调/怎么转述——只写主 agent 需要的
  references/
    contracts.md                             # 机读契约:事实类型表/信号闭集/尾块格式(机制,数据按引用)
    theory-map.md                            # 一页:节点→理论构件映射(评审/维护面)
main/ist_core/agents/
  compile-worker.md                          # <role>→<task>→<rules> 骨架不变
  compile-attributor.md                      # +版本层/跨案对账两步
main/ist_core/compile_engine_v8/             # py:图+节点+事实台账(纯函数 fold)
```

| 官方规范条目 | V8 落点 |
|---|---|
| Progressive disclosure 三级 | L1 frontmatter（name/description/when_to_use）常驻；L2 SKILL.md 体 ≤120 行只服务主 agent；L3 references/ 按需（contracts 只被孔/评审读） |
| Concise is key | §5.5 减法纪律：三选一存在性检验+门在则不教+坑叙事归判例层；worker ≤60 行 |
| 自由度匹配 | 确定性流程全在 py（零自由度）；领域判断在孔（高自由度，事实+why）；窄桥处精确护栏（emit 契约/尾块格式） |
| Scripts for determinism | reconcile/fold/门全是纯函数 py+测试，LLM 永不当胶水 |
| 无时效信息/无案卷号 | md 全部 "measured:" 句式；build/日期只存在于数据（事实流），不进 prompt |
| 术语一致 | 全栈词表统一：fact/verdict/ctx/residual/deliverable/provisional（contracts.md 定义一次） |
| 反模式规避 | 无 ALL-CAPS 默认强祈使；无内联数据表（闭集从源码/JSON 现查）；无「参考实现抄数据」 |
| Eval-first | §8 不变量测试先写后建 |

## 6.5 持久化家族表（domain_grammar 数据，四通道——2026-07-10 手册取证定形）

| 通道 | 动词族（识别） | 污染作用域 | 缓解（mitigation 字段） |
|---|---|---|---|
| ① 本机磁盘 | write memory/file/net/all、config memory/file/net/all | 卷内跨案 | merge 排卷尾（保持族内原序）+ 案内自清建议 |
| ② 对端节点 | synconfig to/from/rollback、ha synconfig runtime/bootup、带 peer 参数的配置命令（如 cluster virtual priority） | **跨设备**（to 方向自动落对端盘） | 排卷尾 + bed_gate 体检同步态 + 终验必含 |
| ③ 分区文件系统 | segment 生命周期、分区内 write | **跨批**（.conf.tmp 尸体复活） | bed_gate 体检+床账清理（排序无效） |
| ④ 床级互斥态 | HA 同步态 × config memory/file（官方互斥声明） | 状态共存约束 | merge 期共存检查：同卷含互斥对时告警/隔离 |

新通道 = 加一行 JSON（verbs/channel/mitigation），零代码——自愈合纪律。
排序规则的定理边界如实声明：**只对通道① 单调改善**；②③④ 靠体检门/床账/共存检查。

## 7. 抛弃的 V6 包袱（显式清单）

| 包袱 | V8 处置 |
|---|---|
| 状态枚举台账 + 迁移合法性表 | → 事实流+派生视图（合法性表变成 fold 的权威序） |
| digest 内嵌跨轮对照/frozen/瞬态护栏（路径键控） | → 派生谓词（按 aid，路径无关） |
| `.frozen.json`/`user_decision.json`/`last_run._attribution` 旁车文件 | → 事实类型 |
| 每轮子集目录各自 last_run 账本 | → 单一事实流 + runs/<run_id>/ 引用 |
| attribute 按 L⁻¹(failed) 反查 | → reconcile 全射入账后按视图派工 |
| `.grade_credential.json` 命名（grade 已死） | → `credential` 事实（source=lint） |
| compile_pipeline.py 遗留壳 | → 三个 helper 归位后删文件 |
| 终验后二次全量写回 | → provisional/确认/rollback 三段事实 |
| escalated-only 的 ask 面 | → 三条 ask 边（欠定/升级/矛盾） |
| 锚=提交 build（源②单源） | → 设备自述为准（源①），提交值仅作配置参数 |

**保留不动的资产**（与理论相容且实证过硬，V8 直接复用）：emit 全部机械门（17+单调门）、
blocks 组合子、verifiability 链、precedent/footprint 工具族、自愈环（uncertain/观察组/升级）、
domain_grammar 数据层、fanout 载荷通道纪律、性能双护栏、环境池。

## 8. 验收（eval-first，先写测试后写引擎）

**不变量族（新，V8 的宪法测试）**：
- INV-1 交付一致性：`report.passed == {c: latest_verdict(c, delivery)=pass}`——名义/实测分叉在测试层不可能通过
- INV-2 残差恒零：任一轮 reconcile 后 `verdict_unconsumed == ∅`
- INV-3 全函数：fold 对枚举出的全部 (视图, 事实) 组合有定义（property-based，含乱序/重复/矛盾序列）
- INV-4 矛盾可达 ask：构造 pass@subset→fail@delivery×2 序列，断言到达第三条 ask 边
- INV-5 锚差拦截：设备自述≠配置 build 时 anchor_gate 必问、零设备轮消耗
- INV-6 回滚完备：rollback 事实后 mirror/footprint 无该案残留（清污脚本机制化的回归）
- INV-7 账实分离：注入与事实流不一致的 checkpoint 业务缓存，断言恢复后视图取自事实流
- INV-8 裁决-卷面绑定：旧卷面/旧卷组成的 delivery-pass 不为新卷面/新组成背书
- INV-9 床权边界：bed_gate 永不自动清理床账之外的产物（非己方残留只 ask）
- INV-10 重放幂等：「append 后 checkpoint 前」崩溃重放，fold 语义不变（幂等键去重）
- 拓扑门：图↔SKILL↔NODE_TYPES 三方一致（沿用）；语言分层门（沿用）
**场景回归**：yzg 双回合作为金标准场景包固化（错锚批→anchor_gate 拦；保存族→终验矛盾→ask）。

## 9. 开放决策（实施前定）

1. ~~checkpoint 兼容~~ ✅ 已裁决（账实分离）：checkpoint 只存图游标+interrupt 挂起态+引用+入参
   （解剖实证 V6 checkpoint 本就 3.3KB 薄层）；业务游标(round/scope/计数)降为派生值；
   恢复时不一致以事实流为准（INV-7）。
2. ~~终验矛盾默认策略~~ ✅ 已裁决（2026-07-10）：首次自动回环；第二次起每次矛盾均 ask（带累计历史），永不静默吞终。
3. ~~落地形态~~ ✅ 已裁决：`compile_engine_v8/` 平行建，yzg 金标准场景全绿后一次切换 graph
   指针，V6 目录整删不留开关。
4. ~~保存族互扰~~ ✅ 已裁决（且经手册取证升级）：进 V8——通道①排卷尾 + bed_gate 床态体检门
   + 床账 + 通道④共存检查（见 §3/§6.5；synconfig/segment 两坑由用户点出、正典手册钉死）。

## 9.5 真机验收记录（2026-07-10，yzg@93——切换依据）

结果 `delivered_with_labels` 23/26+3 如实标注(vs V6 名义 26/26 实吞 3);四公理/三 ask 边/
排序/回滚全部真机兑现;验收发现 7 项全数修复或记录(详见 RUN_yzg_langfuse_monitor 第三回合)。
据此执行一次切换:compile_engine_run 出口→V8、SKILL/langgraph 指针→V8、V6 包+测试删除、
借用件(questions/uncertain ingest/behavior promote/轮存档)迁入 V8,V6 内件测试以 V8 语义
等价重建(test_briefs 五门+S4 存档断言)。

## 10. 对抗审查记录（2026-07-10，开工前）

对设计的自我攻击共 12 发现：**7 项改设计**（裁决-卷面/卷组成绑定、事实幂等键+单写者+前向兼容、
床账与床权边界、矛盾首环归因定向化、版本距离策略、双账职责声明、通道④共存检查）、
**5 项记录为接受的残余风险**：
- R1 非己方床残留只能 ask 不能清（共享床的权属边界，设计如此）；
- R2 跨批污染若来自「未跑 V8 的其他使用者」，床账无记录、体检只能报告异常不能归属；
- R3 W/R 精确集不可文本判定，保守家族近似会把「只读持久层」的 case 误挪卷尾（无害但改变卷序）；
- R4 尾簇（抽屉案之间）内部互扰排序不能消除，依赖终验+矛盾 ask 兜底（已有兜底路径）；
- R5 事实流单文件的规模上限（万级事实才需分段，当前批量 <千，不做过度设计）。

## 11. 用户面渲染层设计（G1–G4，2026-07-10 验收后立项，未实施）

真机验收暴露的共性缺口：诊断事实齐全（facts.jsonl 五条归因、83 条裁决、决策记录），但没有渲染成用户能行动的人话——delivery_report 只有 10 行骨架，`contradicted`/轮次等内部术语直接漏给用户。本节设计「最后一公里」，对标 opencode / MiMo CLI 的终端体验。

### 11.1 三条设计原则（钉住理论，逐条可审）

1. **一切用户叙事 = 事实流的确定性投影**。渲染层（`render.py`，纯函数）吃 facts.jsonl 产中文叙事，与 engine_report 同一 fold（INV-1 扩展到人话报告）；渲染时刻零 LLM 调用——LLM 不当胶水，胶水是确定性模板。
2. **需要 LLM 产的人话，在判断时刻一次性落成事实字段**。归因孔新增三个结构化字段（见 11.3），渲染层只取用不再生成。符合语言分层：`fix_direction` 保持英文（喂下轮 brief 的 LLM 面），`user_note` 中文（交付物面）——同一事实按受众双通道。
3. **对外零术语泄漏**。状态/语境/处置/层 → 人话词表（确定性映射，如 contradicted→「单独验证能过、整卷复验会挂」、delivery→「整卷连跑复验」、reflow→「重新编写」）；英文枚举、卷面/卷组成指纹哈希不出现在任何用户面。词表是用户面模板内容（语言分层的既定例外），随渲染模块落 py。

### 11.2 G-1 交付报告 + TUI 收口卡

- `delivery_report.md` 每个非交付案一节，三段式：**发生了什么**（verdict 序列机械翻译成时间线人话）／**怎么判断的**（归因 `user_note` + 引文对照）／**修复方案／取舍**（判定式输出，规则见 11.7——修法陈述句、问句只问取舍）。恢复 `unsuccessful_cases.md/xlsx` 交付。
- TUI 收口：closing 发一条结构化 summary 事件 → footer 上方「交付结果」卡一屏讲完（结果行＋需关注案每案一行人话＋报告路径），对齐 opencode 的 run 收尾摘要。
- 机器门：报告 lint 断言禁英文枚举词/禁 16 位指纹哈希；INV-1 测试扩展到「报告叙事中的数字=视图重算」。

### 11.3 G-2 归因契约补三字段

`submit_attribution` 增：`doc_quote`（手册/脑图原文引用＋出处路径）、`device_quote`（实机回显原文，复用 evidence 的「必须 device_context 子串」机械门）、`user_note`（中文一句话，给交付报告与 ask 面板）。三字段进 attribution 事实；「手册说 X / 实机是 Y」从散文变一等数据，判例层 uncertain 观察的 `observed_under` 可直取 device_quote 语境——自愈环数据同步变实。

### 11.4 G-3 问询面板增密

矛盾题面从「矛盾史＋选项」升级为：案件人话时间线（机械拼）＋ 最近归因 `user_note` ＋ 引文对照 ＋ 每个选项的后果一句话。仍走既有 ask_user 契约（≤4 题/批、`"{header}"="{answer}"` 解析），改的是题面内容不是组件。

### 11.5 G-4 收口前补齐归因（oracle 残差全覆盖）

ask_contradiction 未获答 → 不再直接 closing，改经 **attribute(final 模式)**：只对「最新 fail 裁决无归因事实」的案补一趟归因，final 模式禁止回 author/merge（有界一趟，防空转护条保持）。效果：任何 fail 裁决收口前必有归因叙事（668030 类案从「failed 轮次1」变成有故事可讲），公式16 的「显式残差」升级为「标签＋回滚＋叙事」。

### 11.6 TUI 过程体验（复用既有卡片机制）

- 问题案出现时按 `progress:{autoid}` key 挂一行人话状态原地更新（「⚠ 单独跑通过、整卷复验失败——正在分析原因」），复用上机心跳同款单行机制；
- footer 九态聚合词表复核一遍人话化；
- 全程零英文零哈希；验收用 cmux 抓屏 + 以本轮 yzg facts.jsonl 为金标准输入回放渲染。

### 11.7 判定式输出：修法归理论，取舍归用户（两轮对抗定形，2026-07-10；问询形态被 §11.11 终版收敛）

初稿「处置→通用三选项」与二稿「菜单生成器」同病：把**导出问题当选择问题**。668015 实判：
唯一正确修法=案尾自清理+保持卷尾（复合施加，THEORY 互扰消解推论）；「接受单跑」是量词偷换
（不符脑图交付预期）、「报缺陷」被四查机械排除（海量回显是手册内行为且正是被测对象）——菜单
里三分之二是错误答案，即设计制造跑偏。定形规则：

- **修法输出是陈述句**：渲染层对每个失败案先跑判定链（根因层→命中通道→知识导出修法）；修法
  唯一导出时直接陈述「修复方案（依据…）+引擎已执行状态」，**不设选项**；已排除的方向可列为
  「已排除及理由」（透明，非选项）。
- **问句只承载过程取舍**：继续消耗轮次复验 / 显式止损停此用例。止损项必须标注「不符合脑图
  预期，记入未通过卷」。与「矛盾第二次起必问」裁决相容——问的是取舍，不是修法。
- **选项级机械门**：缺陷选项仅当四查通过（行为与手册矛盾）才允许出现；止损选项仅当导出修法
  已试尽或用户主动叫停时出现。
- **真欠定才有多选**：知识层冲突或零命中时才呈现多方向，且每个方向必须理论自洽并附依据，
  明示「知识层无先例」。
- LLM 的 `user_note` 只解释机理；修法文本由判定链从知识条目渲染，LLM 不发明行动。
- **ask 充要条件（三轮定形，THEORY 三权分立推论）**：ask ⟺ 信息或权限不在引擎侧——①意图权
  （脑图欠定且实验穷尽仍不可裁）②资源/权属（床权/轮次续批/破坏性实验）③缺陷确认。**案进 ask
  的机械前提 = 导出修法队列为空**（队列由归因判定树×通道知识×判例机械生成；队列非空禁 ask，
  继续自愈环）。矛盾第二次必问裁决不变，但题面 = 进度呈报＋继续授权（「诊断X/已试Y/下一步Z：
  继续／换床复核／挂起到下批」），默认建议永远是继续；「接受单跑」不作为选项出现，仅接受用户
  主动输入。轮次封顶从终态改为资源问询（授权加轮或挂起续跑）；唯一非通过正当终态 = 缺陷候选。

### 11.8 配套接线（数据+机械，自愈合纪律）

1. **文法层 mitigation 升级为双面结构**（纯数据变化）：每通道 `mitigation: {engine: …,
   case: {action, refs[手册出处的清理形态引用]}}`——案内自清理成为一等数据（local_disk 的
   case 侧即 CLI Ch20 文件级清理形态，provenance 已在库）；
2. **归因孔通道注入（机械）**：attribute 节点用既有 `case_channels` 机械算出该案及同卷邻案
   命中的通道条目（含双面 mitigation）注入归因 brief——归因 LLM 在知识给定的行动空间内判断；
   归因事实增机械字段 `channel`（命中通道 id，非 LLM 填）；
3. **worker reflow 闭环**：reflow brief 携带菜单生成器产出的结构化 remedy（action+refs），
   worker 按引用现查手册写清理步骤，prompt 零写死命令红线不破；
4. **联动检验点（下批实证）**：030 翻挂恰在尾序前驱 015 换卷之轮——015 补自清理后整卷复跑，
   观察 030 是否随之稳定（一个修法救两案=推论的可证伪预测）。


### 11.9 交付目录契约与临时数据清理（V6 契约全额继承 + 挂起态适配）

真机验收实况：__sub* 子集卷已清，但 26 个 per-autoid 临时目录全部残留在 workspace/outputs/
顶层，批目录内 manifest.json/last_run.json 未收，未通过双卷（xlsx/md）未产——V6 的交付契约
在 V8 closing 只落了一半。定形（closing 节点职责，全部机械）：

**交付目录 `workspace/outputs/<批名>/` 一处齐全**：
- `case.xlsx` — 通过卷（整卷终验背书的交付集）；
- `unsuccessful_cases.xlsx` — 未通过卷（全部非交付案,含人话标签/轮次/当前诊断列）；
- `delivery_report.md` — 判定式渲染的人话总报告（§11.2）；
- `unsuccessful_cases.md` — 失败案完整叙事（每案三段式全文：时间线/机理引文/修复方案与
  当前队列状态——比总报告详,续跑或人工接手的第一读物）；
- `engine_report.json` + `facts.jsonl` — 机读真理源（facts 必须保留：挂起续跑/审计/重放
  渲染都依赖它）。

**清理规则（挂起态适配,与 V6 的差异点）**：
- 已通过案的 per-autoid 目录 → 删除（凭证/子卷已无用途,真理在 facts+交付卷）；
- 未通过/挂起案的 per-autoid 目录（含 history/ 轮存档）→ **整体挪入 `<批名>/unfinished/
  <autoid>/`**——不是删除:导出修法队列未空的案要跨批续跑,卷面与轮史是续跑输入（§11.7
  挂起语义的物质基础）;
- 批内中间件 manifest.json/last_run.json/__sub* 子集卷 → 删除（last_run 的证据已按
  evidence_ref 进 facts）；
- TUI 收口卡（§11.2）末行列交付物清单（两卷+两报告路径）,与磁盘实况一致才算收口成功
  （对账断言进 closing,防「报告说有、盘上没有」）。

### 11.10 重做切片（2026-07-10 第5轮后定形；¥96 整批回退的教训=切薄逐片实弹验收）

§11 首次实施(f724ba5c)因整批过大回退(25275ea8);理论与设计结论不变(问询子系统按 §11.11 终版),实施改四片,
每片:建 → 金标准场景 → 小批真机 → 过了再下一片。顺序 A→B→D→C。

- **A 问询权**(决策权还给用户;第5轮三案实证:归因器自判 env_blocked 终结 655173/
  封顶自判 escalated 终结 668044/rerun 处方未执行 668030):ask 充要条件、封顶=资源
  问询(继续加2轮/挂起/停止)、suspended 挂起态(跨批续跑)、归因器 env_blocked 需用户
  确认才终态(user 来源的即时终态)、rerun 处方必达 merge 的路由修补、呈报式题面。
- **B 修法队列**:remedies 导出队列+authored.remedy 戳+队列空才准问。
- **D 归因增强**:user_note/doc_quote/device_quote 三字段+通道知识注入 brief。
- **C 判定式渲染**:人话双报告/未通过卷/收口卡/leak_scan+§11.9 交付清理契约。

### 11.11 Ask 子系统终版设计（2026-07-10 定稿 = THEORY §2.6 十参数 × 调研四定案）

依据:THEORY §2.6(is/ought 分界/K_ought 检索余项/收敛律/采信规则)+RESEARCH_ask_design_survey
(双源模式+run5 数据四裁决:机械采信/attributor 顺产/adjudications 新库/strict 工具弃
response_format——mimo 实测 response_format 双形态不守约,strict 工具双形态满分且与思考兼容)。

**构件一:`submit_ask_panel` 工具**(strict=True 单点开;仅 attributor 白名单)
AskPanel schema(扁平/全 required/additionalProperties:false/enum 小写,全局一版):
```
{intent_signature: str,                          ← 判例键之一(语义 slug 素材)
 conflict_shape: enum{manual_vs_device, expected_vs_observed,
                      method_vs_implementation, ordering_vs_persistence, other},
 version_family: str,
 sides: [{source_ref: str, quote: str, anchor: str|null}],   ← ≥2;quote 过 verbatim 子串门
        (device 侧对 last_run 原文校验,doc 侧对源文件校验——poka-yoke,错误信息点名字段+
         期望形态+最近似匹配,模型自纠)
 retrieval_receipt: [{slug: str, outcome: enum{miss, hit_conflicting, hit_adopted_blocked}}],
        (≥1 必填——空手问在 schema 层不可能;B 片前允许 slug="manual_declared" outcome=miss)
 hypothesis: str,                                ← 引擎的理解 Z(中文;唯一自由段)
 ask: str}                                       ← 一句中文问句
```
行为:校验→落盘 outputs/<aid>/ask_panel.json→引擎收割为 ask_panel 事实。三字段归并声明:
原 D 片的 doc_quote/device_quote 即 sides 两侧,user_note 即 hypothesis——D 片并入本件,不另做。

**构件二:`kb_intent_search` 工具**(通用注册,tool-gating 随 compile 激活;B 片)
参数 (query, source_type: enum{spec, precedent_case, bug_adjudication, decision, all},
version_family: str|null, response_format: enum{concise, detailed})。fan-in:spec→FTS5 新索引
(KMS product md 1720 份,复用 kb_memory_search CJK bigram 底座);precedent_case→compile_precedent
委托;bug_adjudication→kb_bug_search 委托;decision→knowledge/adjudications/ FTS5。返回 concise=
slug+title+命中引文+anchor(version,ts,lineage),截断附收窄指引;description 写明何时不该用
(常规编写不用;同形判据命中/verifiability 欠定才用——A9 触发门控)。

**构件三:`kb_adjudication_write`**(引擎专用,不进任何 fork 白名单——A5 人源专属;B 片)
(key{intent_signature, conflict_shape, version_family}, ruling 中文, evidence_refs)→渲染 md
(frontmatter=key+anchor{version=device_build, ts, lineage:"user_proxy"})→验证器(schema/slug
合法/同键碰撞→追加 revision 段)→落 knowledge/adjudications/<slug>.md→FTS5 reconcile。
plan-validate-execute;收敛律 eval:同键第二批零 ask。

**构件四:attributor 孔职扩展**(A 片)
判 ought-欠定(同形判据命中:两投影冲突且选边改写某方意图)时→(B 片起先 kb_intent_search)→
submit_ask_panel;VERDICT 尾块增 `ASK: panel|none`。判断仍自由,落账仍 strict 工具。

**构件五:引擎机械采信**(attribute 收割后,B 片;run5 漂移数据裁定不交孔)
三条件:命中记载间无互斥 ∧ 与实机不冲突(记载期望形态 vs 最新回显签名;不可比=未知→不采)
∧ 填充型(不与 D 文本/既有 E 语义相抵)→ adopted 事实(带 slug 引用,不写回)+按记载重编;
任一不满足→panel 进 ask 目标。

**构件六:问询节点终形**(A 片;节点名 ask_contradiction 保留——拓扑门三方一致)
目标 = 未答 ask_panel ∪ cap_reached 二分(有 panel→呈报之;无→escalated 工程故障呈报,附证据)
∪ contra≥2(题面呈报式) ∪ env_blocked 待确认。题面渲染自 panel(差异呈报+已检索+理解 Z);
options=[确认,按此继续 / 纠正(Other 自由输入=CorrectedError 语义,feedback 事实注入重编 brief)
/ 确认产品缺陷(走候选单)];decision 存小写 token confirm|correct|defect;挂起/停止=TUI 常驻
特权(自由输入兜底),不作引擎选项。confirm→(B 片)kb_adjudication_write。
安全件(MiMo-Code 移植):_PENDING teardown fail-all;非交互/超时→自动「挂起」带可行动反馈。

**eval 断言(eval-first,随片落测试)**:①空手问 schema 级不可能;②quote 非子串被拒且错误
信息含最近似;③panel 未答时 cap 必呈报之(二分);④adopted 不触发写回;⑤(B 片)同键第二批
零 ask(金标准回放);⑥挂起案跨批续跑恢复。

**切片重排(D 并入 A)**:A=构件一+四+六+既有 WIP 收尾 → B=构件二+三+五 → C=渲染层(11.2-11.9)。

**A 片 WIP 现状**(工作区未提交;compact 后由 git status+本节恢复上下文):已改 views
(S_SUSPENDED+env_blocked 终态收窄到用户来源 _user_sourced)/_shared(cap_waiting/granted_rounds/
env_confirm_waiting/ask_targets/suspended 计数桶)/nodes(author cap_reached 资源化+attribute
已归因跳过+ask_contradiction 三类题面初版+env「继续」开隔离复跑处方)/graph(_after_author 四路:
补 ask 边与 rerun 处方必达 merge——668030 路由洞)。待重整:ask_targets 加 panel 目标源;
题面从三类内联改 panel 渲染;engine_tool._bridge 未改待写;submit_ask_panel 工具未建;测试未跑。

