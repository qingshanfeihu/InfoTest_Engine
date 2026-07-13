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
                    "result":"pass|fail|broken|not_run", "signatures":[…],
                    // broken=案没跑成(执行相位失败:级联崩溃/stale/超时/setup 被拒),
                    // 结论无效≠断言红——xUnit ERROR≠FAILURE(§18.1);采集侧五值
                    // (run_case/digest)保真透传,禁在入账层折叠成二值(审计坑#1)
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

**上述保证的边界与失败语义**（2026-07-13 审计坑#3 修订——「不可能」只在事实入流之后成立，
入流前有三个必须显式定义失败语义的口子）：①**输入通道**：last_run.json 读取/解析失败不得
fail-open 置空（那等于整轮裁决静默蒸发）——解析失败=reconcile 出 error 态硬停；②**写回/回滚
执行**：动作失败不得落成功事实——失败落 `writeback_failed`/`rollback_failed` 事实（台账
只为真发生的动作背书）；③**残差门**：INV-2 由真实的 `verdict_unconsumed` 计算强制（§8），
非结构论证替代。

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
| compile_pipeline.py 遗留壳 | → 三个 helper 归位后删文件（2026-07-13 审计坑#28 如实标注:`_emit_progress` 仍被 v8 _shared 依赖,归位后方可删——当前保留） |
| 终验后二次全量写回 | → provisional/确认/rollback 三段事实 |
| escalated-only 的 ask 面 | → 三条 ask 边（欠定/升级/矛盾） |
| 锚=提交 build（源②单源） | → 设备自述为准（源①），提交值仅作配置参数 |

**保留不动的资产**（与理论相容且实证过硬，V8 直接复用）：emit 全部机械门（17+单调门）、
blocks 组合子、verifiability 链、precedent/footprint 工具族、自愈环（uncertain/观察组/升级）、
domain_grammar 数据层、fanout 载荷通道纪律、性能双护栏、环境池。

## 8. 验收（eval-first，先写测试后写引擎）

**不变量族（新，V8 的宪法测试）**：
- INV-1 交付一致性：`report.passed == {c: latest_verdict(c, delivery)=pass}`——名义/实测分叉在测试层不可能通过
- INV-2 残差恒零：任一轮 reconcile 后 `verdict_unconsumed == ∅`——**由真实计算强制**
  （2026-07-13 审计坑#2：此前无执行体,仅结构论证——reconcile 现遍历本轮 last_run 全部
  autoid,比对入账 verdict 集,残差非零=error 态硬停,不是 warning）
- INV-3 全函数：fold 对枚举出的全部 (视图, 事实) 组合有定义（property-based，含乱序/重复/矛盾序列）
- INV-4 矛盾可达 ask：构造 pass@subset→fail@delivery×2 序列，断言到达第三条 ask 边
- INV-5 锚差拦截：设备自述≠配置 build 时 anchor_gate 必问、零设备轮消耗
- INV-6 回滚完备：rollback 事实后 mirror/footprint 无该案残留（清污脚本机制化的回归）
- INV-7 账实分离：注入与事实流不一致的 checkpoint 业务缓存，断言恢复后视图取自事实流
- INV-8 裁决-卷面绑定：旧卷面/旧卷组成的 delivery-pass 不为新卷面/新组成背书
- INV-9 床权边界：bed_gate 永不自动清理床账之外的产物（非己方残留只 ask）
- INV-10 重放幂等：「append 后 checkpoint 前」崩溃重放，fold 语义不变（幂等键去重）
- INV-11 失败语义红线（2026-07-13 审计新增,治全函数假设族坑#3/4/11/12/14/17/18）：
  **任何跨进程/跨设备/跨文件的动作必须定义失败语义,「静默继续」不是合法选项**——
  具体三式:输入解析失败=error 态(禁 default-空);动作失败=failed 事实(禁落成功事实);
  门数据面缺席=显式 `gate_disabled` 事实入账+报告声明(禁静默 no-op)。任何新 try/except
  必须归入三式之一,review 时对表
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

**A 片已落地**(9d59c08f,2026-07-11;红线评审 PASS,全量 1695 绿):构件一/四/六全部
+eval ①②③⑥(test_ask_panel.py 17 例)。实施中修正三处设计盲点:①`list[dict]` 注解经
strict 转换成「强制空对象」,LLM 无法传字段——嵌套结构必须显式 pydantic 模型;②特权词
(挂起/停止)只对短指令生效(≤8 字或句首),长句是叙述(「不要挂起,按…」按题面默认);
③_user_sourced 收窄 round==99 单信号(evidence 串可被回显常见词撞上;round 由工具内部
取自台账,fork 伪造不了)。另加形态-侧别一致门:record-vs-device 类差异必须有记载侧原文
出场,防文档侧意图只活在 hypothesis 转述里。
**B 片已落地**(fa47eef6,2026-07-11):构件二(kb_intent_search 一工具四源:spec=product
md 1720 份 FTS5 懒建/先例委托/缺陷缓存扫/决策史)+三(adjudication_store 纯函数——
不进任何注册表比白名单更强的人源专属;同键 Revision 追加)+五(_try_adopt 三条件:
同键∧无互斥∧判例 device 引文仍是本轮回显子串,比不出=不采;defect/stop 不跨批采信)
+收敛律写回接线+eval ④⑤(test_adjudication_loop.py 13 例)。
**C 片已落地**(2026-07-11):render.py 判定式人话双报告(diagnosis 优先取 panel 的
hypothesis——判断时刻的中文,渲染零 LLM;remedy_text 事实流机械判定六分支;leak_scan
扩 A/B 新枚举)+closing 终形(双报告/unsuccessful_cases.xlsx+md/§11.9 清理/交付对账/
收口卡)+TUI engine_summary 卡(reducer+ink)+yzg 金标准回放。实施中修正参考实现
(f724ba5c)的两个续跑断链洞:①未决案挪 unfinished/ 无还原逻辑→prep 开工还原;
②deliverable 目录直接删→挂起案恢复后终验重组全卷时 merge 缺其 xlsx→改挪
delivered/ 存档,prep 一并还原(test_render_closing.py 14 例)。
**D 片(立项,不阻塞真机)**:remedies 修法队列门(§11.7 导出修法队列空才 ask,
含 domain_grammar case_mitigation 数据面)+收口前补齐归因(_attribute_batch 抽取)。
真机验收:A+B+C 一次合跑。


## 12. 行动论修订：既有设计与 THEORY §2.7 的冲突审计（2026-07-11，yzg 233 实证驱动；只改设计，代码修改另议）

依据：THEORY §2.7 公理 (22)-(25) + 两轮对抗（R1 架构 7 攻 / R2 效率 7 攻）+ 文献坐实
（Voyager/AWM/SkillGuard/SkillAdaptor/DGM/EvoMemBench）。触发实证：233 interface 污染链
——两个归因孔散文全对，被 disposition 枚举拍扁、per-case 架构让 9 个 fork 重讲同一故事
（9×849k↑ token）、正确修法（恢复床）在系统里无处安放。

### 12.1 冲突审计表（现设计 → 理论裁定 → 修订方向）

| # | 现设计 | 与 §2.7 的冲突 | 修订方向（落地序位置） |
|---|---|---|---|
| X1 | 归因 per-case 逐案派发（attribute 节点 20 fail=20 fork） | 违 (24)：无机械前筛，公共原因批 N 份重复深归因（E1/E7：9×849k↑ vs 分层 1.06M↑，差 86%） | fail 签名机械聚类前筛（零 token）；最大簇占比≥θ → 代表案深归因+成员 flash 轻校验+批级合成一次；无簇 → 现状不变（序②） |
| X2 | disposition 枚举承载双重语义：既是场景判断（env_blocked=「环境」）又是路由指令（不重编） | 缺口②实证：E 层混叠 E_ext（外因，止损归用户）与 E_pollution（批内污染，引擎有权处置），233 的正确认知被枚举拍扁；同因两孔给出两处置（233=reflow, 248=env_blocked） | disposition 保留为路由词表（fold 全函数性必要条件，A6）；新增**批级公共原因假设**事实（common_cause：签名簇+假设+受影响集+verbatim 证据引用+行动判例键），路由消费假设而非仅枚举；env 呈报题面按有无假设分形态（12.3）（序②） |
| X3 | 图拓扑无批级判断位（归因→ask/author/merge 直连） | §2.7 缺口本体：孔与孔之间无「按公共原因组织应对」的路 | 新增 [llm] 节点 diagnose（**产假设事实的观察者**：不调工具不发动作，吃簇内原始事实按引用，产 common_cause 事实；假设须 per-case 证据交叉验证——A1 裁决）；拓扑门三方一致随动（序②） |
| X4 | 床态清理=cleanup_refs 文法数据（人编辑 JSON 加条目） | 违 (22) 增长方式：形态是行动判例库的雏形（已验证动作+provenance），但**增长靠人写场景条目**——每类新残留人加一条 | 形态保留（已验证判例继续机械执行）；**增长机制**改走 (25) 通路二：新残留形态 → LLM 提案（清理命令+验证探针成对，SkillGuard 契约形态）→ 人批 → 探针验证通过 → 自动落 cleanup_refs（provenance=行动判例）。人不再手编条目（序③） |
| X5 | worker 对设备的持久写无记账（框架仅对 test_env ip addr 记账） | (25) 通路一（机械逆放）前提缺失；「识别持久写」本身是枚举问题（A2 承认的循环） | **修正（2.7.7）**：记账主体第一人=引擎床账——不做「持久写识别器」，改做**床态快照 diff**（观测结果不解析意图；投影集=平台状态面级≈资源规则，R4-G2）；X11 即其接线。识别器路线维持不做 |
| X6 | A 片 env 确认题面二选（「确认环境停止/不认可隔离复跑」） | 缺口②下二选不完备：233 场景两选皆非正解（不是环境问题；隔离复跑在床未恢复时照样超时）；run9 追加：账内命中时该题面**根本不该出现**（(26) 非法 ask） | **零 ask 分层**：床账命中己方→自动恢复零问询（X11）；账 miss 且 diagnose 有假设→批级呈报（假设+受影响集+提案）；都无→现二选（合法兜底=真环境故障/非己方残留）（序②③衔接） |
| X7 | D 片 remedies.derive_queue 纯文法数据驱动（persistence_channels case_mitigation） | 半冲突：队列来源是场景数据；但 ACTION_CN 的 self_cleanup/rerun_isolated/vary_form/recompile_directed 恰是**能力原语**（A3 裁决的正确枚举对象） | 原语枚举保留并正名（能力原语表=行动侧的路由词表）；队列**来源**扩容：文法判例（已验证）+common_cause 提案（新形态）；§11.7「队列空才 ask」充要条件重述为「簇假设已验证/证伪 ∧ 队列空 ∧ 权限外」（序②与 D 片合并） |
| X8 | 归因 brief 喂全历史设备回显（_round_evidence 每轮 6000 字符内联；实测 fork 均价 849k↑=run5 的 3.3 倍） | R2-E5：效率债第一位——新构件收益会被既有泄漏淹没 | 载荷按引用改造：brief 内联最新轮摘要+历史轮引用（fs_read 现查），与「LLM 走控制面、数据按引用流」既有纪律对齐（序①，已落 c4a272a7）。**已知代价面（run8 实证，THEORY 2.7.6）**：单案主读让跨案根因追溯变浅（run7 整批视野两 fork 追到 233 源头，run8 未追到）——不回退，由 X3 diagnose 结构性兜住（其实证论据②） |
| X10 | worker/attributor 对「意图 vs 环境能力」形态的 panel 触发缺失（233 两轮均硬编未呈报：测 VLAN listener 而触发端 untagged 打不了 tagged 流量） | §2.6 意图触碰面与 conflict_shape 枚举（method_vs_implementation）**均已覆盖**——判断层未触发，非理论/schema 缺口 | C 层提示**必须带等价类限定**（R3-P1：先穷尽 §3.3 正解等价类内变形——如改物理口等价验证，那是实然自决；**无任何等价路径**才呈报）；与 P3 的跨案加固合并 ≤2 句、并入既有段不开新段（R3-P4 prompt 减法纪律）；diagnose 位（X3）为结构性兜底 |
| X11 | 床账（bed ledger）设计在案未接线（O-3）：上批己方污染本批 → env ask 抛给用户 | 违 (26) 非法 ask（信息=账应载、权限=INV-9 账内自动清理既定授权，均在引擎侧应然可达集）；run9 用户裁决实证 | **接线为序②之首**：bed_gate 批前快照落盘→closing 批后复探 diff→diff 项与本批命令面交叉验证认己方（R4-G4，机械 grep last_run 的 sends-command 行）→己方项恢复命令**生成归 LLM**（flash 直调；它懂任何状态面的 show↔配置对应——vlan/路由/ACL 同一条路，**零模板零场景枚举**，2026-07-11 用户拦下模板库路线后修正）+机械双门（实体越界门：命令 token ⊆ diff 身份集；执行后复探 diff 清零验证）→未清项入账（diff 随账），下批 bed_gate 据账接力（账内命令=已验证记录机械回放——G3 本义；无命令账项 LLM 再生成过门）。账空存量=一次性清偿（R4-G1，run9 的 4 题是账空时代最后合法 ask）；非己方 diff→ask 依然合法 |
| X9 | compile_emit blocks 无字符串双收（本轮 26 案自纠往返实测） | R2-E5 同项 | blocks: list\|str 双收+_coerce（steps 通道样板；#65 已立案）（序①） |

### 12.2 被理论再确认的设计（不动清单——防止行动论被误读为推翻一切）

- **emit 机械门全集/verbatim 子串门/上机互斥/lint 凭证**：窄桥低自由度，A6 裁决「闭集是
  fold 全函数性的必要条件」的同族；SkillAdaptor 坐实「失败归因到具体步骤」优于全轨迹反思。
- **事实流 append-only+幂等键+派生视图**：行动论的执行落账（(23) 落账归引擎）直接复用。
- **B 片判例库+机械采信+收敛律**：知行对称律 (23) 的知识侧原型；行动判例键/免批复用原样
  移植其机制。
- **版本锚体系**（version_family/device_verified/凭证 mtime/床态 build 锚）：SkillGuard 的
  契约验证范式，我方先行且更严。
- **床权边界 INV-9**：升格为 (25)——不是被行动论松动，是被表述为公理。
- **fork 隔离/孔内自由判断**：233/248 散文全对证明孔的能力形态正确，问题只在认知的出口。

### 12.3 修订后的问询形态谱（§11.7/§11.11 增量，非替换）

```
床态门(既有)        : 残留/锚差/探测未完成 → 继续/停止
欠定门(既有)        : needs_decision → 改过程/改预期/改描述
差异呈报(A片既有)    : ought-欠定 panel → 确认/纠正(Other)/缺陷
批级呈报(新,X6)     : common_cause 假设 → 批准提案并重跑受影响集/不认可/挂起
                      (提案携行动判例键;批准即写回;同键复现免批轻确认——(25))
资源问询(既有)      : cap 二分/挂起恢复 → 继续/挂起/停止
```

### 12.4 落地序与验收（R2 裁决原文；每步独立可验收，数据不支持即停）

① **还效率债**（X8/X9；#65 扩容）——验收：归因 fork 均价回落 run5 量级（≤300k↑），
   emit 首发成功率 >80%（Langfuse 对照）。**run8 首证（2026-07-11）：编写期
   ↑5.85M/¥18.6 vs run7 ↑13.2M/¥41.4（省 56%——单点非区间，run7 混入 zombie/重启
   扰动，R3-P6），参数层整调拒 0 次（run7 十几次）；归因期 ≤300k↑ 指标待齐后序①
   才算验收完成。**
② **床账接线（X11，序②之首——比 diagnose 更机械更省，直接消灭 run9 形态）+机械前筛+diagnose 节点+批级呈报**（X1/X2/X3/X6/X7；X10 的 md 小补已落 721553a7）——
   验收：233 形态金标准回放（签名簇→假设→受影响集全中；run7/run8 双份真机事实流
   可直接做 fixtures）；公共原因批归因 token ↓≥70%；独立失败批零变化；diagnose 假设
   的 verbatim 交叉验证门测试。
③ **行动判例化**（X4/X5）——验收：cleanup_refs 新条目由「提案→人批→探针验证」链路
   产生（自愈演练同款：全程零 .py 变化）；同键复现免批命中。**首个演练标的已指定
   （THEORY 2.7.6）：interface/vlan 通道条目——由 233 事故提案产生，禁止人手写**
   （persistence_channels 同项随动：emit 缺清理步门与 merge 通道①排尾同枚举双面）。
   **空窗期路线（R3-P2）**：「禁手写」禁的是通道枚举（防未来的案），不禁个案卷面
   修复——233 眼前就治：归因 fix_direction→定向重编让其长出案尾清理步（既有自愈环，
   零新机制零新成本）；枚举条目防的是「未来别的案同形态」，等序③。
   **X8 空窗加固（R3-P3，序②落地即由 diagnose 取代）**：attributor md 一句——同批
   多案同签名时 fs_grep 全批对齐并读最早 fail 案的证据文件（~30k 仅同签名多发时，
   比误归多烧 2 轮便宜两个量级）。
④ **同键免批复用**——验收：金标准回放第二批零人批（(20) 收敛律行动侧）。

监测预注册（THEORY C12）：库命中率与人批频率不随批次单调降 ⇒ (22)-(25) 成本模型被打，
落地序中止回退。

### 12.5 引擎问题标准处理循环（方法论固化，2026-07-11 用户裁决）

后续一切引擎问题按 `/engine-verify-loop`（`.claude/skills/engine-verify-loop/SKILL.md`）走：
真机上机（cmux+Langfuse+fastlog 三通道监控）→ log+Langfuse 取证定位 → 查理论（更新+
反向质疑补充）→ 对照设计（冲突审计+反向质疑）→ 修复实现（薄片+eval-first）→ 清理临时
数据 → cmux 重新上机验证——循环到无问题。**每层必过对抗、不许跳层**；跳层代价在案
（跳理论=检测器膨胀被三连否；跳对抗=¥96 回退）。本节 §12.1-12.4 即该循环第 2-4 步的
一次完整产物。

### 12.6 全库合规审计（2026-07-11，用户「还有没有类似不符」指令；判据=(22)-(26)）

| 项 | 裁定 | 处置 |
|---|---|---|
| bed_restore_syntax 模板库（W1） | **违规**：模板库=规则库，每状态面一条=场景枚举增长——(22) 被实现走样 | 已删；恢复命令生成归 LLM+实体越界门+执行验证双门（本批落地） |
| _answer_token 对预置 label 关键词猜（W3） | 糙：label 是引擎自己产的，「in」猜测多余且可误 | 已修：_bridge 每题携带 label→token 同源精确映射；语义兜底只剩 Other 自由输入 |
| cleanup_refs/persistence_channels/coexist/bed_probes 的人手写增长 | 同族（存量合法：provenance 数据；增长方式违 (22)） | 序③提案链路（恢复通道的 LLM 生成+双门已通用，cleanup 可复用同通道） |
| verifiability 的 claim_kind | 合法：判断归 worker（LLM），工具只收 enum——与 conflict_shape 同型 | 不动 |
| FORM_BY_KIND（欠定选项的形态建议） | 合法：决策辅助显示，判断权在 LLM（kind）与用户（拍板），emit 门核对 | 不动 |
| is_transient_error markers | 合法：自家 LLM 端点传输层契约词（异常类名/标准 HTTP 错误文本），非领域判断；裸数字坑已修在案 | 不动 |
| 渲染词表（STATUS_CN/LAYER_CN/_SHAPE_CN 等） | 合法：机器枚举→中文的显示映射，非判断 | 不动 |
| A 层机械门/原理层检测器/资源规则 | 合法（P1/P2 与 R2 已定性） | 不动 |

## 13. 基础设施可靠性设计审计（2026-07-12，对照 THEORY_infra_reliability；缺漏=I 行）

依据：`THEORY_infra_reliability.md`（R5 数据校准后）。§12 审计的是行动论冲突，本节
审计的是 infra 域**设计缺漏**——理论已有位、设计全无的构件。

### 13.1 缺漏表（I1-I8，按理论 §9 优先级）

| # | 理论位 | 现设计 | 缺漏与设计方向 |
|---|---|---|---|
| I1 | L3 床基线恢复（§4；原语已查实；54% T1 结构性根治） | bed_gate/closing 只有床账（L1） | **全无**。设计方向：真机验证 save/restore 配对语义后——bed_gate 批前落基线（`config save` 类原语到专属槽位）+closing 批后恢复基线+探针对账；床账降级为审计（记「恢复发生过」而非承载恢复）。验证实验卷=explore 级一次上机（基线→弄脏→恢复→diff 清零断言） |
| I2 | #67 归属一致性门（§7 通用形态） | reconcile/attribute 无证据校验 | **全无**。设计方向：digest/attribute 收证时对每份取证附件跑「执行目标 vs 卷面 G 列」机械比对；不一致=`evidence_suspect` 事实+attr_evidence.json 内标记+brief 声明段；切分 bug 本体另修（框架侧或 digest 侧） |
| I3 | mirror 同步锚（§6 第 0 条） | **已落地（2026-07-14 审计修正标记——此前误标全无）**：`mirror_anchor.py::check_sync` 接入 bed_gate（nodes.py §bed_gate），`.sync_anchor.json` hash 对账，mismatch=needs_ask 呈报「恒真门/found 门推导前提可疑」，unknown=告警入 findings 不拦批 | 落地形态与本行设计方向一致；见 §18.3 |
| I4 | quarantine 态（§5，与 suspended 分立） | 视图无此状态；瞬态案占轮次烧归因 | **全无**。设计方向：新派生标签 S_QUARANTINED（attribution.layer==transient 自动进区；进区案不入重编队列不进交付分母，报告单列「隔离区 N 案待仲裁」）；仲裁=小批复跑（重跑预算=资源规则）；复现→出区转正常 fail 流，通过→出区转 pass。fold 全函数性随动（状态语义先定义再上线，A6 纪律） |
| I5 | 契约测试套件（§6） | 恒真门推导散在 emit 实现内；无组织 | 半缺。设计方向：`tests/framework_contracts/` 套件化——0.8 模糊匹配契约/切分标记契约/清理范围契约/IP 记账契约/found DOTALL 契约,直接跑 mirror;I3 的锚是第 0 条 |
| I6 | OD 主动检测/污染配对（§3） | 矛盾谓词=被动;diagnose(X1/X3 序②)未实施 | 已有位（§12 X1/X3）,本审计只补输入结构化引用:配对=diff 实体×受害案触碰实体交集 |
| I7 | flake 率指标（§5） | engine_report 无此字段;DS-4 无前置排除 | 设计方向:report.totals 加 transient_rate;K 健康度仪表(DS-4)按 §2.8 以此为前置排除项 |
| I8 | L2 命名空间机械门（§4） | worker md C 层倡导,无机械门 | 设计方向:emit 门加「持久对象名含 autoid 尾缀」检查(限持久化家族案);低成本 |

### 13.2 与既有落地序的合并（已被 §15.3 合流队列 v3 取代）

infra 域优先级（理论 §9）与行动论落地序（§12.4）曾在此合流；2026-07-12 S 代数
冲突审计（§15）后，**唯一权威队列见 §15.3**（S1/S6 插队、S4 并入序③、S3 影子
运行新增、S7 sleep 维持末位）。本节保留作演化记录，不再维护。

## 14. 需求边界（2026-07-12 用户裁决——七项范围需求定档）

缘起：v1→v8 全史考古发现——核心编译回路的需求已被理论钉死，但七项范围/外延
需求从未声明过，且它们不以 fail 显形（engine-verify-loop 是失败驱动的，结构性
撞不上），只能人来定。2026-07-12 用户逐条裁决如下。**本节是范围需求的唯一权威
记载；后续机制立项前先对照本节判「在册/越界/todo」。**

| # | 需求项 | 裁决 | 设计推论 |
|---|---|---|---|
| R1 | 评审能力定位 | 测试用例评审暂**不与编译流水线接轨**——服务不同流程；统一为 todo | 评审不立理论、不建 eval 集；维持「尽力而为参考意见」现状，不再有质量焦虑 |
| R2 | 交付下游契约 | 发现缺陷/文档不一致**如实写报告，由人处理下游**；全场景自动化（自动提单/研发回复回流）为 todo | 引擎职责止于交付目录内的如实报告；known_defects 版本区间等回流通道暂靠人工 |
| R3 | 泛化与成本取向 | **不考虑成本的泛用**——只要能正确生成 excel，用 token 和时间换质量完全没问题 | 「花钱买质量」类构件（首败升深度/难度预测升采样/新域冷启动学费）有常设授权，不设成本门；新域首批不设预算上限 |
| R4 | 无人值守与输出最大化 | 目标=**能输出尽量全输出，山穷水尽才 ask**；可接受代价=部分用例事后重跑，不可接受=整批停在中间态 | **设计变更（待落地）**：单案待人不得阻塞全批——欠定/待决案标挂起继续跑其余，问询尽量批末汇总一次呈报；夜跑最坏结果=晨起答题+子集重跑 |
| R5 | 自愈验收标准 | 四条：①问人的必须是**真问题**（非功能理解错误/逻辑混乱造出的假问题）；②选项必须**真解决问题**（选了不是绕弯重跑）；③**同类问题 ask 过一次后续自动处理**，不反复问；④真标准只有一个——**人工怎么处理的，agent 就按同法处理** | DS-5 增列质量维度：裁决写回时标注「真问题?/选项有效?」两布尔（用户答题即标注，零额外成本）；③=收敛律既有；④=判例采信率。数量阈值不设，按四标准红绿灯 |
| R6 | 床污染责任二分 | **环境级**（版本不对/license 失效/非己方残留等，可机械判定）→**呈报人解决**；**用例间干扰级**（上下用例互扰/清理缺失等）→**引擎问题，自己解决**，不许问人 | bed_gate 体检呈报=第一类合法出口；案间干扰全谱（自清理/排序/床账/L3 类工具）归引擎自愈责任域。L3 实验动生产床仍需执行时一次性授权 |
| R7 | 成本度量换轴 | **成本不是关键，关键是成本代价导致的输出效率** | 不设 ¥ 预算；监测轴换为**输出效率**（单位墙钟真 PASS 产出/批周转时间）；效率退化才治，烧钱换质量是 R3 授权的 |

**与既有机制的张力（如实记录）**：R4 与「先问后落」强制（V6 遗产：欠定 interrupt
阻塞图）方向相反——R4 裁决后，欠定问询从「编译期阻塞」改造为「案级挂起+批末
汇总」是新的设计债，落点在 ask_decision/问询节点（收口卡已有汇总形态可复用）；
挂起特权/矛盾即问语义不变。R3/R7 与 §12.4 效率债验收数字不矛盾——效率债治的
是**无效烧钱**（重复派发/假结果/序列化失败），R3 授权的是**有效烧钱**（换质量）。

## 15. 被测系统代数（S 代数）设计冲突审计（2026-07-12；含对抗检查与合流队列 v3）

依据：`THEORY_target_system_algebra.md`（公式 28-33，R6 对抗后）+ 五路检验汇总
`RESEARCH_theory_data_checks.md`（数据/文献裁决的持久证据锚）。缘起：全史考古
发现 **S 代数是三份理论中唯一未被任何设计文档接住的**——§12 审行动论、§13 审
infra，S 代数的六条工程推论悬空，其中 (32) 层界判据实质上已判现设计一处枚举
增长方向死刑。本节补齐第三角的冲突审计。

### 15.1 冲突/缺漏表（S1-S8）

| # | 理论位 | 现设计 | 裁定与修订方向 |
|---|---|---|---|
| S1 | 类型图解析（(28)：手册命令签名→依赖边模板，文法层数据） | 无 | **缺**。一次性解析脚本：29 分册签名行→`domain_grammar.json` 新段（参数占位符类型边+层标注+时变参数标记——检验一的 5.7% 时变签名表同管道产出）；闭合于手册版本，带覆盖率自检（解析签名数/粗体签名行数），失配报警（信任根纪律，与 I3 同型） |
| S2 | 影响面=实例图上闭包（(31)：污染者-受害者配对的精确形态） | diagnose 位（X1/X3，序②未实施）规划为签名前筛+自由聚类 | **修订序②输入**：配对=实例图上闭包（卷面命令+床态快照运行时实例化，类型图供边模板）——比自由聚类更强且毫秒级；I6 的「diff 实体×受害案触碰实体交集」是其退化近似，类型图未落时先用近似 |
| S3 | 层界危险度单一判据（(32) 推论：「层<4 的写」替代持久化通道枚举） | §6.5 持久化家族四通道枚举+cleanup_refs（人手写增长，X4/W-cleanup 已判增长方式违规） | **方向成立，过渡双轨**：枚举门继续执勤（zhaiyq 门效实证在案，不许裸切）；类型图落地后层界判据**影子运行**逐批对照（影子判定 vs 枚举判定 diff 落报告），影子零漏报 ≥2 批才切主、枚举降级为回归对照 |
| S4 | 清理=设备自带 no 逆元逆放（(29)：配置面逆元，机械回放） | X11 床态恢复=LLM 生成恢复命令+entity_gate 双门 | **修订恢复优先序**：账内己方 config 写的恢复**首选机械逆放**（config X→no X，形态从手册签名机械派生，非人写模板——与 W1 死刑不冲突，见 D1）；LLM 生成降为逆元派生不出/逆放探针不清零时的后备；状态面写（文件/统计/对端）仍归 infra（快照/L3），(29)-G6 边界不动。**完成度（2026-07-13 run18 兑现②，#76 收口）：①逆元数据已备（§18.4 inverse_forms,860 对机械派生）且 τ 门/床账回放已消费;②bed 新 diff 恢复**机械逆放先行已落地**——`parse_config_commands` 从 corpus 解析案面 config 命令（框架 `sends command in config:` 行,mirror apv_ccypher.py:152 权威格式）,`own_writes_by_command` 判据升级为「案面有创建该对象的命令」（取代旧 own_writes 的「token 在 corpus 文本出现」——run18 高危 bug 的直接成因:dig 访问过的基线 IP 被误判己方致删管理口）,`restore_mechanical` 对己方 diff 取 inverse_forms 的 no 逆元（negation of 案面创建命令,作用域恒等于原命令,天然不越界）;机械派生不出的（inverse_forms 缺 no、只 clear）才走 LLM 后备+entity_gate。恢复只碰案面真创建过的对象——基线/仅访问的实体不碰。测试锚:`test_s4_mechanical_restore.py`（run18 基线访问不判己方 / run9 创建对象机械逆放）+ `test_bed_ledger_loop.py`（closing 集成）。**这是 run18 高危 bug 的根因修复**（症状层护栏见 §18.8.1 restorable_diff 方案 C,两者互补） |
| S5 | 归因链 OSI 下降（§5：L7 断言 fail→L4 在听→L3 可达→L2 邻接，逐层 show 探针序） | attributor 有版本层下降（dev_help 接线），无承载链下降 | **缺**。近期：attributor md 补结构指引一句（C 层，高自由度——指方向不写命令）；远期：diagnose 位（序②）把探针序作为机械选项产出（层间距离=修 233 类跨层归因的成本尺） |
| S6 | 命令存在性门（(33)：emit 期查「命令∈S(build) 版本专属手册命令集」） | ~~bed_gate 只做 build 三方比对；emit 无此门~~ **已落地**（emit_xlsx_tool `command_existence` 门；2026-07-13 复核纠正:此前审计误标「缺」，实为看漏 emit 侧此门） | **已落地（D5 呈报形态）**：emit 查命令 ∈ command_inventory 版本专属签名集(3572 签名,解析覆盖率 1.0)，未命中→落 `command_existence` claim 到 needs_decision.json(附最近似记载+已检索证明)+拒落卷,走欠定问询;用户裁决(改过程/改预期)后同键不复问((20) 收敛律)。run19@79 实证:668059 的 `sdns fulldns on` 未命中→command_existence claim + worker dev_help 实机验证 verification_path_absent,机械门+实证双确认 fulldns 在此版本不可用 |
| S7 | 时间轴（候选 (34)：状态面断言须时间索引） | 卷面 sleep 治理在队列末位 | **缓立（检验一裁决）**：yzg 数据不支持（富集是混杂假象+2 例配置面翻转反例+翻转由床污染主导），域外背书强（liveness/QuickLTL/RFC6412）；处置=时变签名表先落文法层（S1 捎带，零代码）、**不立门**；前置=persistence/health-check 域批次原始数据；sleep 治理维持末位 |
| S8 | 多写者边界（理论修正回写项） | —— | ~~待回写~~ **已回写**（S §0.5/§10：他案写=h-in-s₀ 归 infra T1） |
| S9 | **h 位置归因轴**（S §0.5;2026-07-13 校准:误归漂移现象与其结构解释是可复核定性事实——655154 三 run 三标签/668030 单 run 五标签轨迹在盘,「8 案重标」精确计数依赖已丢脚本,不作定量宣称） | disposition 词表：env_blocked×50 无「批内前驱污染」词位；瞬态与床污染共用 rerun_isolated（668030 同签名三 run 三标签） | **归因结构升级方向（序②并入）**：attributor 产出增加 h 位置维度（h-in-λ 欠定/h-in-s₀ 己方账/h-in-s₀ 他人写/h-in-π 通道/无 h），diagnose 位据此路由对策——s₀ 类禁 rerun_isolated（复跑 h 冻结不可救,直接查账/床治理），π 类才复跑。词表演进非推翻：disposition 保留为路由词,h 位置是其上游判据。可判性诚实：s₀/π/E 单案观测等价,判定挂批级算子（同批对账/床账/跨轮）——恰是 diagnose 位（X3）的理论职责说明 |
| S10 | **互扰预测器**（S §0.3 交换子判据;2026-07-13 校准:⇐ 方向为必要非充分,判据本体=可机械计算的预测器且判定核在库——diagnose 的 s₀ 配对活代码;查全/精确率标定数字来自单 yzg 域、脚本已丢,不作定量宣称） | I6 的「diff 实体×受害案触碰实体交集」近似 | **序② diagnose 输入的精确形态**：共享矩阵=「A 的复位差集写实体（含承载图闭包）∩ B 的触碰实体」为必要条件预筛，加「B 的观测 π 依赖该分量所在面」细化降假阳；**排卷输入**：merge 前用该矩阵把 s₀ 危险案排尾/隔离（s₀ 危险案判据可推导且判定核在库——`_s0_pair`/diagnose 落 h_s0 活代码;版本分辨由「规则跟卷面走非案号黑名单」构造保证;查全数字不作宣称,S §0.4）。持久面写（write memory/file/net）触碰「全局配置存储」分量=全机耦合，一律排尾+批末床态收敛核对（保存族跨面洗白路径的结构对策） |

**不动清单**：床账（X11 快照 diff+己方交叉验证+跨批接力）、INV-9 床权边界、
bed_gate 体检呈报、emit 机械门全集、事实流 append-only——S 代数给它们数学根源
（(31)(32)），不改其行为。

### 15.2 对抗检查（7 攻 2 修 5 站）

| # | 攻击 | 裁决 |
|---|---|---|
| D1 | S4 逆元回放=W1 模板库还魂？用户刚判过模板库死刑 | 站住（区别声明）：W1 死刑判的是**人手写场景条目**（vlan 信号）；逆元是从手册签名**机械派生**（config X→no X），数据闭合于手册版本、零场景枚举，与 G3 文法层同一封闭类；且逆放后必跑验证探针（diff 应清零），失败→LLM 后备→ask，护栏链不变 |
| D2 | S3 双轨期两套判定并存=复杂度翻倍，影子判定谁消费？ | 修正（收窄）：影子只产**对照事实**（`shadow_layer_verdict` 落 facts，不进任何路由/门）；消费者=切换决策本身（≥2 批零漏报）；到期不切即删影子——影子有日落条款，不许永久双轨 |
| D3 | S1 类型图解析靠正则啃 29 分册，签名格式变体会静默漏边 | 修正（补自检）：解析器带覆盖率自检+漏解析行样本落盘人审一次；手册版本 hash 入信任根登记（与 I3 mirror 锚同型）；漏边的后果面=S2 配对候选集偏小（必要非充分本就由 G5 兜底），非门误杀 |
| D4 | S2 上闭包依赖实例图，实例图依赖床态快照投影集——投影核外的写配对必漏 | 站住（已裁）：R6-G5 已定静态上闭包=必要非充分候选集（⊇真影响），漏网由矛盾谓词/终验兜底；本审计不新增宣称 |
| D5 | S6 命令存在性门误杀：MinerU 截断致手册文法覆盖上限 98.8%，合法命令可能查无记载 | **修正（定形态）**：门=呈报不硬拒——未命中产 needs_decision（附「查过哪些分册、权威序结论」检索证明），人确认后判例写回、同键不复问（(20)）；fulldns 实证正是记载互斥而非简单缺失，硬拒必误杀 |
| D6 | R4 批末化问询与「先问后落」A 层强制冲突——欠定案不阻塞了，worker 会不会又硬编欠定值？ | 站住（语义澄清）：R4 改的是**问的时机与阻塞范围**（该案挂起、其余继续、批末汇总），不是「先问后落」本身——挂起案在答题前**不产卷**，硬编路径依然被代码封死；防线不变，只是别的案不陪等 |
| D7 | 本节自身=理论自我扩张第四次（C13）？ | 站住：S 代数已过 R6 对抗+YANG 工业背书；本节零新本体，只把已裁理论接进设计，且 S7 展示了反向纪律（数据不支持即缓立） |
| D8 | S9 的 h 位置判定挂批级算子——单案归因 fork 根本判不动，upgrade 是空中楼阁？ | 站住（分工声明）：h 位置的**候选**由单案证据产（fork 标「疑 s₀/疑 π」），**裁决**归 diagnose 位/引擎批级机械对账（同批 pass 集/床账/跨轮签名）——与 X1 代表案深归因+成员轻校验的分工同构；fork 只降不判死 |
| D9 | S10 排卷会打乱用户脑图给定的用例顺序——越权改写意图？ | 站住（权威归属）：卷序是执行编排非测试意图（脑图未声明顺序语义；ordering_sensitive 案例外——needs_decision 已有该键）；排卷=实验室规程（S §0.4 卫生段权威分离定理：规程权威在引擎），ordering_sensitive 声明过的案不动 |

### 15.3 合流执行队列 v3（取代 §13.2 队列）

按「离线零风险优先、实验授权单点确认、数据不支持即停」排：

1. **L3 真机验证**（I1；save/restore 配对语义一次实验——**动生产床，执行前经
   §14-R6 约定的一次性授权**）；
2. **#67+I2 归属一致性门**（已落 I2 防御侧，切分本体待修）；
3. **I3 mirror 同步锚 + S1 类型图解析**（同为「信任根+一次性离线解析」族：hash
   对账与签名解析同批做，S6 命令集、S7 时变签名表同管道捎带产出。**可复现原料已在**
   ——3572 条命令签名、解析覆盖 99.64%（与提交的 command_inventory_10.5.json 逐位
   一致,可复核）;**依赖边 DAG+层标注尚未构建**（S §0.3,2026-07-13 校准——旧「层映射
   数据表已在」宣称不成立）,工作量=「差距四项」工程化：定义-引用自动归纳/前缀消歧/
   参数说明表消费/provenance 合流）；
4. **S6 命令存在性呈报门**（数据就绪即上，D5 形态）；
5. **序② diagnose+机械前筛**（X1/X2/X3/X6/X10 兜底；输入按 S2/S10 升级为
   上闭包+交换子配对（判据=必要条件预筛,判定核在库;定量查全不作宣称——S §0.3），
   归因结构并入 S9 h 位置轴；类型图未熟先用 I6 近似）；
6. **I4 quarantine 态**；
7. **序③ 行动判例化**（X4/X7/W-cleanup；**S4 逆元回放并入**——恢复优先序：机械
   逆放→LLM 后备→ask）；
8. **S3 层界判据影子运行**（依赖 S1；D2 日落条款）；
9. **I5 契约套件 → I7/I8 → S5 远期探针序 → sleep 治理（S7 缓立，末位）**。

R4 非阻塞问询改造（§14 设计债）已并入 **§16 V8.5 后半场重画**（2026-07-12 用户
裁决「先写」）——队列 v3 的中段项（序②/D 片/S9/S10）由 §16 统稿，外围项
（L3/S1/I3/quarantine/I5+）不受影响、照旧独立。
每步独立验收、数据不支持即停（(22) 纪律不变）。

## 16. V8.5：fail 后半场重画（2026-07-12 立项设计；用户裁决「基座不动、后半场一次重画」；对抗 R9）

### 16.0 决策记录（重构 vs 缝补）

判据沿 v6→v8 先例：**重写当且仅当病在基座结构上写不出来/修不动**。审计：
- **基座五件零结构病**（事实流/fold/权威序/lint 凭证/床账）——S 代数四路反扫脚本
  与 DS-5 曲线全在这套基座上跑通（反扫的定量结论已按 2026-07-13 校准降级,不影响
  本处「基座可承载」论据——跑通是事实,数字才是被降的），理论重推导加固了它而非
  动摇它；S9 h 轴=facts 加字段、quarantine=fold 加派生标签，全是基座的原生扩展
  形态。**推翻基座=烧掉刚验证的资产**（¥96 教训+存量断点续跑契约）。
- **图前半场健康**（prep→bed_gate→author→merge→run→reconcile）——不在任何债表。
- **图后半场四债叠加**：①R4（「先问后落 interrupt 阻塞全图」与「山穷水尽才 ask、
  不阻塞全批、批末汇总」方向相反——interrupt 位置/suspended 路由/汇总点都要挪）
  ②D 片（选项无 remedies 队列约束→668059「要么撞墙要么不靠谱」，R5 四标准①②
  无工程载体）③X3（diagnose 批级位缺）④S9/S10（h 位置判定挂批级算子，需 diagnose
  存在才有归宿）。四债咬合在同一段（ask 的**时机×来源×形态**是一个问题的三面），
  分四次补丁=每片都改 ask/attribute 语义、互相回归。
- **668059 病理标本**：h 框架下=无 h 确定性拒绝+版本参数化——正确设计下 S6 呈报
  门在 **emit 期**就转 needs_decision 携检索证明，轮不到烧三轮设备走 cap 面板。
  三层病：错误的时机（编译期该问的拖到封顶）×错误的来源（选项自由发挥）×错误
  的形态（资源问询的壳装应然裁决的瓤）。

**裁决**：不 v9、不缝补——**v8.5 图语义版本**：数据层契约（facts schema 前向
兼容/凭证/床账/交付目录/断点续跑）零破坏，重画限于图中段路由与问询语义。

### 16.1 重画后的拓扑（fail 后半场）

```
prep ─▶ bed_gate ─▶ author ─▶ merge(可用子集) ─▶ run ─▶ reconcile ─▶ attribute(+h) ─▶ diagnose ─▶ remedies ─▶ route
              │        │ 欠定/S6存在性未命中                                              │
              │        ▼                                                                  │ 队列非空: 自动执行
              │   suspended(案级,不产卷) ◀────── 队列空 ∧ 应然待决 ◀──────────────────────┘ (reflow/重排/隔离复跑/
              │        │                                                                    床账逆放) → 循环
              ▼        ▼
        (白名单即时ask) 批末 ask_gather(一次呈报全部待决,面板批中即挂出)
                       ─▶ 用户裁决 ─▶ 判例写回 + 复活子集续跑到不动点 ─▶ final_run ─▶ closing
```

**问询语义三态**（取代「author 后 interrupt 阻塞全图」）：
- **编译期欠定/存在性未命中** → 该案 suspended 继续跑其余（先问后落不破——
  suspended 案答题前**不产卷**，硬编路径依然被代码封死，D6 语义沿用）；
- **runtime fail** → attribute(+h)→diagnose→remedies，队列非空自动执行**不问人**
  （真问题判据=队列空 ∧ 应然待决——R5 标准①的工程定义）；
- **批末 ask_gather** → 呈报-确认式（§2.6.3 不变）逐题携「检索证明+修法队列已空
  证明」；**面板批中即挂出、批末必有聚合点**——人在随时可答（挂起特权双向），
  人不在批不停；终验矛盾（第三 ask 边）天然发生在批末，归位 gather 不改语义。
- **即时 ask 白名单**（资源规则，批级前提非案级欠定，阻塞正确）：bed_gate 非己方
  残留（INV-9）、跨 minor 版本失配——批都没资格开工的问题。

**R4 保证兑现**：夜跑最坏=晨起答题+子集重跑，整批不停在中间态。

### 16.2 六构件

| # | 构件 | 内容 | 理论锚 |
|---|---|---|---|
| A | suspend-and-continue | needs_decision→案级 suspended（fold 既有标签语义扩展），merge 取可用子集；suspended 案进 unsuccessful 卷待复活 | R4；D6 |
| B | attribute+h 轴 | 归因 fork 产 h 位置**候选**（疑 s₀/疑 π/h-in-λ/无 h，只降不判死），attribution 事实加 `h_position` 字段（append-only 兼容，老事实按 unknown） | S §0.5；D8 |
| C | diagnose 节点 | 批级观察者（X3 终形）：输入=本轮 fail 全集+交换子配对（S10,必要条件预筛,判定核在库;定量不作宣称）+床账+同批 pass 对账；产 common_cause 假设事实+h 位置**裁决**；触发=机械前筛 (24)。**完成度（2026-07-13 审计坑#7 如实分半）：机械半已落地（s₀ 配对+词干聚类）;「LLM 观察者/同批 pass 对账/verbatim 交叉验证门」属片4 未落地——本行验收项以机械半为准,LLM 半落地时再挂验收** | S9/S10；X1/X3 |
| D | remedies 队列 | 来源=归因判定树×能力原语表×判例检索（kb_intent_search）×common_cause 提案；队列项=可执行动作（recompile_directed/rerun_isolated/reflow/床账逆放/vary_form）；**s₀ 类禁 rerun_isolated**（h 冻结不可救）；队列非空→自动执行 | §11.7/X7；S9 |
| E | ask_gather | 选项=判例命中项或引擎理解 Z（呈报-确认式），**不再自由发挥**；decision 事实随答积累 R5 两布尔（真问题?/选项有效?） | §11.11；R5①② |
| F | S6 存在性呈报门 | emit 段前置：命令未命中版本专属命令集→needs_decision 携权威序检索证明→编译期 suspended，零设备轮 | (33)；D5 |

### 16.3 机器验收（R5 四标准落地）

①问题真实率、②选项有效率（decision 两布尔，用户答题即标注）；③同键复问率
（收敛律既有）；④判例采信率。结构验收：668059 类存在性问题 emit 期拦截率=100%
（零设备轮）；除白名单外 ask 全部聚合呈报；批阻塞等待时间=0（suspended 不阻塞
兄弟案）。

### 16.4 实施切片（设计一次、实施切薄——¥96 教训的正确应用）

| 片 | 内容 | 依赖 | 验收 |
|---|---|---|---|
| 片1 | F（S6 呈报门，数据来自 S1 管道） | S1 命令集（原型已在） | 668059 形态回放：emit 期转 needs_decision |
| 片2 | A+E（suspend-and-continue + gather，图语义主改） | 无 | 欠定案不阻塞兄弟案；批末聚合面板；夜跑演练 |
| 片3 | B+C（h 轴+diagnose） | 无（S10 配对可先用 I6 近似） | 668030 形态回放：s₀ 裁决非 rerun_isolated |

**片3 实施定形（2026-07-12 落地+redline 四修，超出原草图的部分如实记）**：
①判定形态全部文法数据化（persistence_channels 复用+新增 bed_l23_write_forms/
occupancy_semantics 两键带 provenance，加载器三函数——手抄闭集三副本漂移被
redline 拦下，synconfig 跨设备通道随数据自动生效）；②持久面写配对**不受卷序限制**
（快照跨轮存活，排尾只降卷内暴露——668030 排尾后仍翻挂的机理），L2/L3 共享实体
保留卷序条件（I6 近似）；③ **s₀ 停车位+bed 呈报**：复跑处方∧h_s0 裁决 → 不入
merge ready（复跑不可救，防 livelock），且**必进 bed 问询**（§11.7 床权在用户：
挂起到下批[默认]/床已处理复跑验证[落 user_cleared 诊断覆盖，闸自动放行]/如实
降级；未答走自动挂起安全件——不静默停车）；④ **终验幂等闸**：同卷组成指纹的
delivery 裁决在案∧组成内无 subset_verified 待升格案 → 不重跑（livelock 防护；
瞬态恢复的升格终验放行——redline 实证回归）；⑤附带根治既有地雷：merged 事实
run_id 带 seq——同 volume 重合并曾被内容幂等键跨轮去重，run/reconcile 读 mf[-1]
拿到陈腐子集组成 → delivery 裁决落错 volume 无限循环（纯复跑不重编路径必现，
生产被「通常有重编」掩盖）。
| 片4 | D（remedies 队列+选项约束） | 片3（common_cause 来源） | 队列非空零 ask；选项全部携判例/队列空证明 |

顺序 1→2→3→4；片间全量测试+对照轮。落地前现行 interrupt 机制不动（过渡期无
真空）。与队列 v3：片3=序②、片4=D 片+序③部分；外围项照旧并行。

### 16.5 对抗检查 R9（8 攻 2 修 6 站）

| # | 攻击 | 裁决 |
|---|---|---|
| P1 | 批末聚合让欠定案白等一批——早问早答早产卷 | 站住（已两全）：面板**批中即挂出**，人在随时答、答了即复活；批末只是必然聚合点。牺牲的只是「无人值守时的单案时延」，R4 裁决明确取全批吞吐 |
| P2 | suspended 案变多，交付分母塌 | 站住：R4 原文「能输出尽量全输出」——suspended 进 unsuccessful 卷+晨起复活子集，优于整批停在中间态（用户原话）；且 F 片把存在性类提前到编译期，净 suspended 数预期降不升 |
| P3 | remedies 自动执行=行动权扩张，顶穿 INV-9 | 站住：队列项全部是**既有合法动作**（重编/重排/复跑/床账逆放），无新写通路；(25) 双通路与床权边界原样 |
| P4 | 三个新构件一次上=违反薄片纪律 | **修正（已内化）**：设计一次、实施四片各自独立验收（16.4）——¥96 教训切的是实施不是设计 |
| P5 | h_position 字段=facts schema 演化风险 | 站住：append-only 加字段前向兼容，fold 对缺字段容错（unknown）；无迁移 |
| P6 | 编译期 suspended 不产卷，兄弟案可能依赖其配置（卷内顺序依赖） | 站住（引 S10）：交换子矩阵判依赖——无共享分量不受影响；有依赖如实标注（ordering_sensitive 既有键，罕见） |
| P7 | gather 撞 contradiction ask（第三 ask 边）语义 | 站住（归位）：终验矛盾本就发生在批末，天然是 gather 成员；呈报位置统一、边语义不变 |
| P8 | 「v8.5」是 v9 换皮，版本号游戏 | **修正（以契约为准的声明）**：数据层契约零破坏+断点续跑跨版本有效是硬判据（16.0），不是措辞——若实施中任何一片被迫破坏 facts 兼容/凭证/床账契约，即刻升版并重审 |

### 16.6 问询路由两向校准（2026-07-13 run17 实弹;goal 循环缺陷#4——这次带机制定位）

run17@79 实录:9 挂起案 3 题恢复问询只提交 1 题((41)④ 面板部分提交)——668044
resumed 产生可推进工作,却被 `_after_ask_contradiction` 旧边「n_ask_contradiction>0
即 closing」直接收口,零复跑交付。对称方向的坑:若把 n_failed 简单前置于 ask,
封顶/env/bed 待问案会让 merge 空转、cap 资源问询被跳过(违 §11.7)。修(graph.py+
counts):

- **actionable 判据**:`n_failed_actionable` = 失败/矛盾 ∧ 不在任何问询等待集
  (panel/contra/cap/env/bed/suspended 并集)——「有活」以此计,处方复跑先于 ask
  (§16 山穷水尽语义的修正实现:旧 `_after_author` 把 ask 排在 merge 兜底之前,
  与设计文本相反);
- **真·未获答判据**:ask_contradiction 节点回传 `ask_answers_consumed`(本轮实答数,
  自动挂起的空答不计)——closing 禁空转卫兵只在「零实答 ∧ 仍有等待」时触发;
  部分作答走可推进工作路由,剩余未答题在下一山穷水尽点/下批再呈。

测试锚:`test_ask_routing.py`(8 项:部分作答不吞/零答仍收口/全挂起答案如实收口/
处方复跑先于 ask/封顶等待仍必问/actionable 计数剔除等待案)。

## 17. R10 落地设计：六门一通道（2026-07-12；理论锚=(38)-(42)+域分诊；片4.5+片5）

run12 实弹+R10 审计产出的七项理论修正（commit 20fd56b6）的工程接线。每门带
理论锚与验收；对抗面已在 R11 打过理论层，此处只列设计决策。

### 17.1 六门一通道

| # | 构件 | 理论锚 | 机制与卡点 | 验收 |
|---|---|---|---|---|
| G1 | **配对恢复门**（emit 期） | (39) τ/(32) 复位差集 | emit 扫卷面：差集内写（bed_l23_write_forms+persistence_channels 文法数据，片3 已载）⊆ 恢复步覆盖（同实体的 no/删除形态）；缺失→**呈报不硬拒**（同 S6 形态：needs_decision 携「缺 τ 清单+机械派生的逆元建议序列」，worker 可采纳重 emit 或上呈）。逆元派生=(29) no 回放（config X→no X，手册签名机械推导） | 655203/233 卷面回放：emit 期呈报缺 τ+给出 no bond/no vlan 建议；补 τ 后放行；48 存量 PASS 卷零误报 |
| G2 | **面板重编出口**（片4.5-a） | (40) 分类学 | bed/env 面板对 diagnose 判定的**自污染者**（自扰判定∨触碰画像含差集内写而无 τ 步）不再给「复跑」出口——出口集换为：重编补 τ（默认，落 reflow+brief 注入缺 τ 清单）/挂起到下批/如实降级 | run12 形态回放：203 的题面首选项=重编补 τ；「复跑」不出现 |
| G3 | **污染者交付门**（片4.5-b） | (40)/(35) 对象×过程链接缝 | deliverable 判据增补：diagnose 判为 polluter 的案，交付前机械核对卷面 τ 覆盖（同 G1 判定器）——未覆盖=不入交付卷（防「每次执行都毁床的卷」带病交付，run12 实测 203 subset pass 差点交付） | 203 卷（无 τ）终验 pass 也不 deliverable，报告注明缺 τ |
| G4 | **决策 echo-back**（(41)③） | (41) 问询链保真 | ask_contradiction/ask_decision 消化答案后，把 token 化的决策以人话复述 append 进面板历史与收口卡（「你的裁决:…→引擎理解为:…」）；纯展示零应答成本。**完成度（审计坑#21→§18.6 兑现;2026-07-13 二次审计修正）：echo 已入收口卡(nodes.py `_g4_decision_echoes`);初版「回放测试」系恒真断言(`… or True` 永不失败)——已重写为走真实构建路径的 run12 截断误判回放(test_multifault_and_card.py)** | run12 截断事故回放：「停止:…」被兜底成 retry 时，echo 立即暴露误判 |
| G5 | **报告重算门**（(42)） | (42) 报告保真 | closing 生成报告后，独立代码路径从 facts 重算交付终态陈述与报告头行，与 render 输出逐项比对；失配=**拒绝背书**（outcome 翻 report_mismatch+顶部警示条+REPORT_MISMATCH.json,交付物保留供审计——审计坑#19 措辞收窄:非物理扣卷）+告警。**类别边界（坑#20）：本门只对账「报告 vs 事实流」,「事实流 vs 设备现实」由 INV-2 残差门+失败语义红线(INV-11)另行设防** | 注入一条 render 篡改的单测：门必拦 |
| G6 | **域分诊前筛**（判定树第零层） | Ω⑥/§3.2 | diagnose 的 s₀ 配对**前移**到归因派发之前（attribute 节点先跑机械前筛：s₀ 配对命中的案不派深归因 fork，直接落 h_s0 诊断+轻量归因事实）——run12 的 22 个归因 fork 大半可省（X1 批级前筛的正名落地） | 床污染批：归因 fork 数 ≈ 非 s₀ fail 数；诊断正确率不降 |
| C1 | **维护日志通道**（(38)） | (38) 写者全集 | 运维写入账：`scripts/maintenance/log_bed_maintenance.py`（谁/何时/何命令/为何,append 进 runtime/bed_ledger/<host>.jsonl 的 maintenance 事实）；bed_gate diff 解释时消费（维护写≠非己方残留≠案残留）；人工修床纪律=修完必登记 | run12 五次修床形态回放：下批 bed_gate 对 port2 恢复不再误判 |

### 17.2 落地序（并入队列 v3 → v4）——**已全部落地（2026-07-12）**

**片4.5**（G2+G3+G4，面板与交付语义,一次改）→ **G1 配对恢复门**（emit,独立）
→ **G5 报告重算门**（closing,半天）→ **C1 维护日志**（脚本+bed_gate 消费,半天）
→ **G6 域分诊前筛**（attribute 重构,与序② X1 合并）。
队列 v3 其余外围项（L3/S1 正式版/I3/quarantine）顺延,优先级不变——G1/G3 是
L3 未落地期的止血带,L3 落地后二者从「必需」降为「纵深」。

落地记录：G1-G4 见 commit 6ec5de43（tau_coverage.py 判定核+emit 门,26 卷校准
仅 655203 命中零误伤;bed 面板自污染者出口;closing delivery_blocked;决策
echo-back）。G5=report_gate.py（独立重算路径,故意不复用 views/facts 派生函数;
失配→REPORT_MISMATCH.json+outcome 翻转+报告顶警示条;顺带修复 G3 接线缺陷——
封堵案状态未写回 vw 本体致报告仍计通过,恰为 G5 目标形态的活证）。C1=
log_bed_maintenance.py 登记 ev=maintenance 床账+三消费点（bed_check 残留解释/
bed_cleanup 圈定排除【维护写=合法基线不可清】/closing 批后 foreign 分流）,全覆盖
才解释、部分命中不解释（宽松侧防洗白）;run12 六次修床已按新纪律补账@93。G6=
attribute 派发前 _s0_pair 前筛（与 diagnose 共用判定核）,命中案免深归因 fork、
机械落 diagnosis(diag:pre:)+轻量 attribution(E/rerun_isolated/h_s0),停车位/
bed 面板/G2 出口消费链原样接通;验收测试断言床污染案零 attributor fork。

### 17.3 设计决策记录

- G1 呈报不硬拒的理由同 D5：τ 判定器依赖文法数据（有截断上限）,硬拒会误杀
  「有清理但形态不在词表」的卷;呈报+逆元建议使 worker 单轮可自纠。
- G2 不给自污染者「复跑」出口是 (40) 终止性的直接要求（R11-P2:终止性以 G1 为
  前提——G1 保证补 τ 的重编真的补上了）。
- G6 前移不动 attribute 的 LLM 孔本身（非 s₀ 案照旧深归因）——改的是派发前筛,
  X1 的「代表案深归因+成员轻校验」在 s₀ 族上退化为「零派发」（机械证据已足）。

### 17.4 run13 实弹修正（2026-07-13,#74 修复批）

- **merge 预检单案化**（缺陷②,二次实证:单案凭证拒绝曾 error→closing 全批 26 案
  零上机）:merge 节点合并前逐案预检（`precheck_merge_case`:凭证新鲜+成品卷
  lint,与 emit_merged 门同构）,不就绪案落 **emit_invalid 事实**踢出本卷,其余
  照常合并;fold 新语义「最新 authored 之后有 emit_invalid → 回 S_PENDING 重编」
  （优先级低于终态/挂起/awaiting——打回不覆盖用户裁决）。被踢案重编后经新
  merge 换组成指纹,INV-8 自动强制重新终验。工具本体 compile_emit_merged 的
  全拒行为不变（手动编排最后防线）。
- **G6 诊断幂等键带 verdict run**（缺陷⑤）:diag:pre:{volume}:{aid} 改
  diag:pre:{verdict run_id}——同 volume 二次 fail 的新诊断曾被幂等键静默去重,
  复跑闸读到旧 user_cleared 多放行一圈。
- **恢复类命令泄漏清理**（缺陷⑥第一版,数据驱动）:domain_grammar 新增
  `restore_leak_teardown`（run13 668000 实证 provenance:config 恢复在设备内部
  注册 SLB 占用对象,对象级 no/clear 不消,仅 clear-slb 级清理可清——产品缺陷
  候选已报）;tau_coverage 消费该条目:恢复步后案内无 required_teardown 形态
  → G1 呈报（suggested 来自数据）。G1/G2/G3 既有消费链自动覆盖此族。残余
  课题（pass 案 quarantine 入口/框架 per-case clear 加强）仍在 #74 登记。
- **skill 禁旁路**（缺陷④）:ist-compile-engine SKILL.md 增引擎异常处置约束
  （只能同参续跑或如实上报;禁手动合并/手动上机/直改 xlsx——绕门断审计链,
  run13 实证直改致凭证失效全批停摆）。

## 18. 审计响应设计（2026-07-13；输入=AUDIT_design_theory_gaps.md 28 坑+转化率 20%+xUnit 对标）

设计红线（本章全部构件共同遵守）：**「机械强制」字样必须配三件套——判定代码+失败语义
+测试锚，缺一降级措辞**；跨进程/设备/文件动作的失败语义按 INV-11 三式。

### 18.1 broken 第三态全链（共振洞：「案没跑成」三层无名）

- **理论**（THEORY_k_state_machine (43)(44)，2026-07-13 形式化加固后形态）：带错误吸收态
  的 LTS——Σ\*=Σ∪{⊥_err}，动作步 g 带 ok(g) 谓词（从回显机械判），¬ok ⇒ 迁移入 ⊥_err
  且吸收（后续步不逃逸）；断言求值三分 Evaluate ∈ {Broken, Pass, Fail}，Broken 当且仅当
  s=⊥_err（≙ xUnit ERROR，非 pass 非 fail）。初版「部分函数+未定义态求值」表述已废
  （破坏指称语义严格性）——本节 schema/fold/报告设计与两种表述均相容,吸收态形态是其
  严格化。668030 空真（恢复步 TFTP 失败→not_found 恒真"过"）即该公理缺失的实弹。
- **schema**：verdict.result ∈ {pass, fail, broken, not_run}（§2.1 已改）。
- **入账**：reconcile 保真透传采集侧五值（digest 的 unknown/stale→not_run;error→broken），
  禁 `"pass" if ... else "fail"` 折叠。
- **fold**：新派生态 S_BROKEN——**不计 fail 签名**（防误 frozen）、不进 attribute 深归因
  （机械短路:级联受害/未执行,归因事实 layer=E disposition=rerun_isolated 或随崩点点名）、
  重编不烧轮次授权。
- **报告**：broken 单列分母（「N 案未跑成（原因）」），不进 fail 叙事。
- **验收**：级联崩溃场景回放——文件级崩后余案入账为 not_run 而非 fail;668030 型恢复步
  失败案入账 broken。

### 18.2 fail-open 族清算（坑#3/4/11/12/14/17/18，INV-11 执行清单)

| 位置 | 现状 | 失败语义（三式归类） |
|---|---|---|
| reconcile 读 last_run | 解析失败→[] 静默 | 式①:error 态硬停 |
| writeback/rollback | 失败吞+落成功事实 | 式②:落 writeback_failed/rollback_failed 事实,报告声明 |
| user_decision 落盘 | 失败吞,decision 照落 | 式②:落盘失败=decision 不落账,面板重问 |
| 批后床态收敛外壳 | 整块吞 | 式②:落 bed_closure_failed 事实+下批 bed_gate needs_ask |
| merge 预检调用 | 无保护 | 式②:异常=该案 emit_invalid(reason=precheck_error),不杀批 |
| 门数据面缺席（grammar/inventory/画像） | 静默 no-op | 式③:落 gate_disabled 事实+报告 K 健康度行。**完成度(2026-07-13 三面补齐):①grammar 面(diagnose_s0)②inventory 面(inverse_forms 空→gate_disabled,τ 覆盖门/bed 机械恢复降级)③画像面(_case_touch_profile 提取失败→批末 gate_disabled,s₀ 配对对其失明)全部落账;render 渲染「⚠ K 健康度:N 个判定门本轮因数据面缺席而降级」行(用户可见,非只机读)。测试:test_k_health_gates.py** |
| 探针空回显 | 判"干净" | 式③:空串=probe_failed(床态未知),入 findings |

### 18.3 mirror 同步锚（公式 D 级最危险项）

`prep`/`bed_gate` 期对 mirror 关键文件（test_xlsx.py/check_point.py/ssh_server.py/
conftest.py）算内容 hash，与跳板机真机框架对应文件 hash 比对（SSH cat|sha256）；失配=
恒真门/found 语义门全族的推导前提失效——needs_ask 呈报（不硬停:用户可确认框架升级后
更新 mirror）。hash 基线落 `knowledge/framework/mirror/.sync_anchor.json`。

### 18.4 τ 推导化（坑#5,词表→结构推导;run13 推导实验已验证:全域 62% 可推,run13 主角全命中）

- 一次性脚本从 command_inventory 派生 create↔no/clear 配对表 → `domain_grammar.json`
  新键 `inverse_forms`（每条带 src 手册行锚;闭合于框架版本,随 inventory 重建）。
- tau_coverage 判定核改消费 inverse_forms（3 公理:no=否定/clear=清理/show=观测）;
  `_CREATE_FORMS` 3 族正则退役为回归对照（等价性断言:推导版结论 ⊇ 词表版,差异逐条人审）。
- bed 恢复接机械逆放先行（S4 声称兑现）：己方 diff 行 → inventory 头匹配 → inverse_forms
  查逆元 → 推得出=机械回放（entity_gate+复探照旧）;推不出=LLM 后备（现行为）。
- τ 责任集公式落地=构造写 − 框架 per-case 清理辖区（F2,从 mirror conftest/clear 解析,
  机械闭集）− 案内已逆。

### 18.4.1 命令注入禁令（2026-07-13 用户裁决；两床被跑死的架构教训）

`restore_leak_teardown`（文法层的一条经验规则+具体命令建议 `clear slb all`）已**整条删除**。
教训的一般形式：**引擎向 LLM 注入具体命令 = 把作用域判断权交给一个不知道边界的建议**——
worker 把 `clear slb all` 朝"清得更干净"升级成 `clear config all`（整机清配置含管理口 IP），
93/105 两台床被跑死。

引擎允许提供的只有两类，其余一律禁止：

| 类 | 判据 | 实例 |
|---|---|---|
| **机械可推导的引用** | 数据源=产品手册/框架源码；派生规则是元语义（3 公理）；作用域恒等于原命令 | `inverse_forms`（inventory 签名配对：`no X` 是 `X` 的逆元）；`framework_cleanup_scopes`（mirror 源码解析） |
| **安全边界禁令** | 「误判即真错」的窄桥护栏，不教做法只禁毁灭 | `destructive_commands`（整机清配置/重启族 A 层无条件拒） |

**经验性知识（"某命令会留下不可见占用对象"这类）一律走判例层**：以设备行为观察入 footprint
（`validity=uncertain` + `observed_under` 语境），worker 检索到现象后自己查手册/试验决定做法。
668000 的泄漏现象已按此形态写入 `config.memory/file/all` 三节点的 behaviors。

### 18.5 采集面三扫描器（xUnit 运行时四相位,Top2-4;markers 全部入文法数据）

- **teardown verdict**：digest 对恢复步（案内 τ 段）回显扫执行失败 markers（`Failed to
  execute`/`Failed to get`/RTNETLINK 族——`domain_grammar.exec_failure_markers` 数据键,
  带 provenance）→ 失败=案 broken+床账标未复原。封 668030 型空真的机制位。
- **setup 相位**：init 段（C=1 行）回显扫同 markers+设备拒绝形态 → setup_failed 事实
  → 归因机械短路（禁 V 层同向重编）。
- **case timeout**：心跳解析已能定位当前案——同案心跳持续超阈（N×单案均值）→
  timeout_suspect 事实随归因携带。T1 三症状（hang/污染/真 fail）机械可分。

### 18.6 多因与消费补全（坑#8/9/21/23/25/26）

- diagnosis 事实支持多因并列（polluters 之外增 co_factors 数组）;G6 命中改「降优先级
  仍轻量派发」在 s₀ 之外证据(独立错误行)存在时;词干聚类按全签名集（非 sigs[:1]）。
- fail 案回显中的独立错误行（Error:/Failed 族,文法数据）提取为 `anomaly_lines` 结构化
  事实随归因/报告并列呈现——原始证据与机械诊断平权（坑#24 弱化残余同治）。
- **s₀ 归因 echo-grounding（2026-07-13 run19 实弹,详见 `AUDIT_attribution_ask_worker_gaps.md`）**：
  `anomaly_lines`/`exec_failure_markers` 判据本就对,但**喂它的日志此前只有断言摘要 `<inner>.txt`,
  不含主设备完整会话 `apv_*.txt`**——668030 的失败机理「write all 撞交互 YES → 命令流错位 →
  Failed to execute」在主设备会话里,扫不到 → G6 免派深归因 → 把「自身命令流错位」误判成床污染。
  修:①`fetch_batch_details` 喂 anomaly 的扫描范围扩到主设备完整会话(fail 案 device_context 提前
  拉一次复用)②`fetch_device_context_under` 防中段截断(失败/交互标记行优先保留)③diagnosis 落
  `echo_support`(占用回显佐证 echo_confirmed / 无 necessity_only),题面据此校准语气——necessity_only
  时提醒「也可能是本案自身命令写法,看完整回显」。**不做「验污染源 pass/fail」**(S 代数反驳:s₀ 独立
  于前驱 verdict,跨面洗白允许 pass 的前驱影响下游)。测试:`test_s0_echo_grounding.py`。
- common_cause 事实接消费方：ask 呈报题面聚合展示「N 案同签名词干」。
- G4 echo 入收口卡 payload+截断误判回放测试;交付对账 missing 非空=outcome 降级;
  leak_scan denylist 从枚举源（views S_*/render 词表键/tokens）机械生成;INV-7 补测试。

### 18.8 设备可达性第零层与问询有效性（run14 实弹,2026-07-13;goal=「ask 真实有效+回答一次出全部 excel」）

run14 实证:被测设备批中失联(双口 ping 100% loss),11 案 fail 全部是失联的下游
症状——s₀ 交换子配对(必要条件,失联批里共享实体恒命中)批量误诊为床污染,
11 题「床残留,唯一根治是清床」全部乱断言。三构件:

- **可达性前筛**((30) 承载合取律的链底消费,此前 C 级零实现):digest 批内出现
  fail 即探设备(跳板机 ping,协议级判定)——不可达=全部非 pass 降
  broken(device_unreachable),禁进 s₀ 配对;dev_run_batch 入口同探,失联拒跑
  (省整轮盲跑)。探测自身失败=未知不改判(护栏非闸门)。
- **共因合题**(「回答一次」的机械保证):bed 呈报按 (诊断依据,污染者集) 分组,
  同组只出组长一题(题面注明代表案集与广播语义),答案经组长映射广播全组。
  run14 形态回放:11 题 → 1 题。
- **题面证据强度校准**:交换子配对是必要条件推断(假阳 20-26% 理论自认),题面
  从「判为污染…唯一根治」改为「疑似…必要条件推断(非确证),设备/环境异常呈
  同样症状」——断言语气与证据强度匹配是问询有效性(goal 判据①)的文案面。
  **校准贯穿全部输出通道(2026-07-14 审计修,run20 实弹)**:①panel 题面按
  `echo_support` 分档(echo_confirmed「回显含占用形态直接佐证」/necessity_only
  「也可能是本案自身命令写法」);②occupancy 判定为**行级**否定——负向词只否决
  同一行的正向命中,不做全窗一票否决(步骤描述横幅「恢复后应不存在」曾把 668030
  真占用 Warning 全窗否决,强档错降弱档);③G6 免派归因的 `fix_direction` 同分档
  (`_g6_fix_direction`)——旧固定话术对 necessity_only 也说 "evidence sufficient",
  且对持久面毒源仍推荐 tail placement(run11 已实证排尾消不掉跨轮通路,与
  `_s0_pair` 注释自相矛盾);该文案随 attribution 流入重编 brief,一并分档、持久面
  毒源删排尾路线。测试锚:`test_s0_echo_grounding.py`。

### 18.8.1 床态探针失败契约与同因合题（2026-07-13 实弹;105 床 SSH 挂死的四种谎报形态）

105 床被 `clear config all` 跑死后(§18.4.1 同一事故),bed_gate 对不可达设备产出了
成套误导呈报:「分区配置残留+SDNS 配置文件残留」(实为 SSH 报错行被当探针内容)、
「⚠ 版本不匹配:设备(空) vs 配置…」(build 探针失败被当解析结果)、93 床账 4 条垃圾
created(批后快照垃圾 diff 入账,下批接力会驱动 restore_via_llm 自动生成配置写)。
根因+修复(全部协议/契约级,零内容关键字):

- **工具失败契约收严**:`_do_probe` 的契约是「失败返回 `error:` 前缀」,但 fastmcp
  路径曾把服务端错误文本包进 `=== dev_probe (fastmcp apv_ssh) ===` 横幅——修:失败
  文本裸返;`_probe_failed` 同时防御性识别「横幅后首个内容行以 error 开头」。
- **版本锚过失败判定**:build 探针先过 `_probe_failed`,失败=anchor status
  `probe_failed`(床态未知)——「版本不匹配」只留给两侧都解析成功的真异族;探针跑通
  但解析不出=`unknown`,题面说「版本未知」。
- **题面同因合题**(§18.8 共因合题在 bed_gate 的对应物):probe_failed 发现按失败
  签名(剥横幅/契约行后的错误载荷行,逐字相等)分组,≥2 路同签名 → 一句「N 路探针
  同因失败——疑似设备不可达,床态未知」;mirror_sync/bed_closure_failed 是引擎内部
  发现,按 detail 原文呈报、不叫"残留"、不进 bed_cleanup。
- **观测自身的韧性同型修**(observability.py):Langfuse auth_check 瞬态超时曾=进程
  终身禁用(02:16 TUI 进程全天两轮 run 零 trace);修:失败冷却重试(默认 300s,
  `IST_OBS_RETRY_COOLDOWN_S`),异常日志升 WARNING 落 tui.log。
- **探针瞬态复探**(2026-07-13 run18 实弹,同型前科 2026-07-11):合法 show 命令单次
  被设备回 `% Invalid input`(框架 SSH 读窗串位 P1 的采集面显形),同一通道立即复探
  即成功——`probe_resilient` 对协议级失败复探一次,两次都失败才算真失败(返回**首次**
  回显:复探路径的新错误会误导诊断)。不复探=一次瞬态产「通道床态未知」假问询打断
  用户,而床是干净的(run18 实测三通道复探全空)。bed_check/bed_snapshot 双消费。
  测试锚:`test_bed_gate.py::test_probe_transient_invalid_retried_not_asked` /
  `test_probe_persistent_failure_still_reported` / `test_probe_resilient_returns_first_echo_on_double_failure`。
- **平台基线面不自动删接口 IP**(run18 实弹;本轮最高危 bug——差点删管理 IP):
  批后床态收敛(bed_snapshot diff → own_writes → restore_via_llm → entity_gate →
  exec)对「本批漂移」自动生成恢复命令。批前 `show ip address` 探针被 SSH 读窗串位
  截断成 1 行(status:success 未判 failed,probe_resilient 救不了截断),批后完整 6 个
  基线地址 − 残缺 1 个 = 5 个纯 added 被误判漂移 → own_writes 因案面配过 port2/port3
  归己方 → 生成 `no ip address port2 172.16.34.70`(删管理 IP)→ entity_gate 放行
  (实体确在错误 diff 里)→ 执行。**四道防线因源头 diff 错而全失效**,设备靠框架 IP
  恢复契约侥幸存活。根治(`restorable_diff` 方案 C):**snapshot_only 平台基线面
  (接口地址等,test_env 拓扑+框架契约管理)只有 diff 含 `removed`(批前快照见证消失=
  完整可信,真替换如 run9 vlan100)才可自动恢复;纯 `added` 无 `removed`(截断嫌疑/
  纯新增)一律只呈报入 foreign**。批后收敛 + bed_gate 床账接力两条 restore 路径都过
  此判据;历史账里的假漂移接力时跳过。测试锚:`test_baseline_face_no_autorestore.py`(6 项,
  含 run9 有-removed 仍恢复的不伤回归)。删接口 IP 是「误判即断设备」操作,与
  destructive_commands 同类红线(§18.4.1):引擎对共享设备发删除命令必须极度保守。
- **迟到产出回收**(run18 实弹;资源与交付双重损失):fork 墙钟超时 ≠ worker 无产出
  ——看门狗超时只是**引擎放弃等待**,fork 线程在 Python 里杀不掉。实录:655233 派发后
  600s 超时判 `escalated: no output`,worker 在 **935s** 时 `compile_emit` 成功,合格卷
  (11KB)+ lint 凭证躺在盘上,案已被标 escalated 永不再看——烧掉 15 分钟与整案 token,
  产出被丢弃。修两处:①**escalated 语义**改「最后一个 escalated 之后有 authored 即
  解除」(与 suspended/resumed 同型——escalated 是关于**当时**无产出的判断,新产出使
  其前提失效;真·无产出案永远等不到 authored,升级人工语义不削弱);②**merge 开工
  回收**(`_reclaim_late_artifacts`):扫 escalated 案的盘上产出,xlsx 在 ∧ lint 凭证
  有效(=emit 全门已过的物理证据)∧ 该卷面未入账 → 落 authored 收回。裸 xlsx 无凭证
  不收(门不可绕),已入账不重收(幂等)。测试锚:`test_late_artifact_reclaim.py`(5 项)。
  **运维旁注**:26 案并发+深思考时 600s 单次墙钟偏紧(`IST_FORK_WALLCLOCK_S` 可调),
  回收是兜底不是许可——墙钟仍应按实际编写耗时校准。
- **欠定台账通道缺口 → 已补齐(通用欠定上报工具,2026-07-13)**:worker md 声明两类
  欠定——①分布类断言不可验(`compile_check_verifiability` 自落 needs_decision.json)
  ②**意图的验证路径在本床不存在**(触发主机发不出意图要求的流量形态)。此前该工具
  入参只表达①(algo/n_requests/n_pools),承载不了②——worker 返回
  `STATUS: needs_user_decision` 却无台账,引擎按「先问后落」不认散文声称判 escalated
  (655173 实录)。补 `compile_report_underdetermined`(claim_kind=verification_path_absent,
  与 verifiability 共用 `_land_needs_decision` 落结构化 needs_decision.json;worker md
  白名单+正文指向它,author 消化路径不变)。测试:`test_report_underdetermined.py`。
- **(41)④ 提交保真门(登记待建,TUI 侧)**:多题 ask 面板按键语义(数字只高亮、Tab
  切题不落答案、Enter 只提交聚焦题)使 run15 与 run17 两次 3 题各丢 2 答——失真
  发生在 (41)①②③ 之前,echo 缺失行是唯一事后信号。门形态:Enter 确认时存在未答
  题 → 挡板提示「还有 N 题未答」,不静默部分提交;落地前的操作纪律=逐题
  「数字→enter」+答后核对 echo 行数(已入长期记忆)。理论锚=(41)④(K §2.12.2)。
- **fastmcp_call 墙钟死线**(device_mcp_client.py):`urlopen(timeout=)` 只是 socket
  idle 超时,SSE keep-alive 会不断续租——服务端工具调用卡死时单发 `resp.read()`
  挂 20min+(全量回归在 bed 探针上级联挂死实证)。修:逐块读+总墙钟=timeout,拿到
  result/error 事件即停;死线触发按不可达处理(回退 stdio/如实报错)。测试面配套:
  rig 必须桩掉 bed_snapshot/check_sync——bed_gate 与 closing 独立调它们,漏桩=单测
  真连跳板机并真探设备床。

测试锚:`test_bed_gate.py::test_probe_failure_fastmcp_banner_error_form` /
`test_bed_snapshot_fastmcp_banner_error_marks_failed` /
`test_bridge_common_cause_merges_dead_device_question` /
`test_build_probe_failure_is_probe_failed_not_mismatch` /
`test_dev_probe_error_contract.py` / `test_observability_retry.py`。

### 18.9 意图盖章与合取①最小面（2026-07-14 run20 实弹;P1c 证据源修正）

run20 实证:668030 脑图意图「执行 **write all** 后重启」,worker 首版把机制静默换成
`write memory`——执行干净、结构合法、74 门无一拦截,与 668000(本就是 write mem 案)
撞题,write-all 覆盖轴丢失;若非床污染恰好挡下,将以 write all 之名 PASS 交付**假覆盖**,
并以 write-all 标题写回 write-memory 内容成**投毒先例**(未来按意图检索先例反向污染)。
理论位:合取①(σ 入意图等价类)闭包检查,K §8 早已登记未建。

**根因不是缺门是证据源**:P1c 意图变体门(`_gate_save_restore_pairing`)当时已存在、
注释即写「防 draft 偷换 write all→write memory,668030 类」,但 `expected_save_variant`
仅由 **worker 自我申报**(单案路径入参、merge 路径 `c.get(...)`)——漂移的 worker 恰恰
不会申报,门 no-op 放行。被检方供证,门形同虚设。

修正(engine-stamped intent,产者不解释/消费者不转述):
- **盖章**:author 派发前引擎把 manifest 意图**原文**(title/step_intents)落
  `outputs/<autoid>/intent.json`(`_stamp_intent`,worker 不可影响其来源);
- **消费端推导**:emit 的 P1c 从盖章原文用闭集词表(`write|config ×
  all|mem(ory)?|file|net`,CJK 紧邻用显式收尾断言而非 `\b`)自行推导 expected
  (`_intent_save_variant`),worker 申报降级为兜底;盖章缺失/意图无保存族词 →
  推导空 → 维持既有 no-op(非引擎路径与存量零回归);
- **posture**:P1c 违例=拒落卷+改法指引(同族 crash-gate 姿势),worker 重试自纠。

**边界(诚实声明)**:这只是合取①在保存族(闭集可判)上的最小面;一般形态的意图
机制忠实(任意等价类的 σ∈[intent])仍属 K §8 未建的 φ(D) 提取器族——按「数据不
支持不立门」纪律,扩族前先取新失效类的实弹。测试锚:
`test_save_restore_pairing_gate.py`(intent 推导 4 例)+
`test_s0_echo_grounding.py::test_stamp_intent_writes_manifest_verbatim`。

### 18.7 完成度纪律

本章各构件落地时在本节表格挂测试锚;未挂锚前,任何位置引用本章构件必须带「设计中」
字样。审计报告 AUDIT_design_theory_gaps.md 为本章的事实依据,28 坑逐条在 §18.1-18.6
有归属;第 6/7 类（范式缺口/声称落差）由 18.1 与全文如实标注（S4/§16.2-C/G4/G5/§7）收口。

## 19. worker 面资产与知识回路（V6 遗产盘点回填,2026-07-13）

V8 文档此前对 compile-worker 只有一句「职责不变」——worker 的工作面、brief 契约、
emit 构造通道、知识闭环全部散落在 V6 文档与代码注释里。本章按「机制+代码锚」回填,
连同 V6→V8 的形态变化与已废项如实标注。全部条目 2026-07-13 逐一对照 v8 活代码核实。

### 19.1 为什么保留 worker 自由理解孔（架构 WHY,E4 实验）

E4 对照(V6 验收期实测,存档结论):固定管线 pipeline 55.9% vs main-orchestrated 64.7%
——**提升来自 worker 自由理解孔,不来自「编排交给 LLM」**。V6 据此把编排收回代码
(StateGraph)、保留唯一的自由理解孔(compile-worker);V8/V8.5 全部重画发生在编排侧,
这个孔的职责与边界一直未动。推论(引擎演进红线):优化编排不许侵入孔内(给 worker
注入具体命令/写死领域判断——§18.4.1 的另一面);孔的质量问题走知识回路(§19.5)与
brief 证据面(§19.3),不走编排补丁。

### 19.2 worker 工作面（白名单+检索序+溯源红线）

工具白名单(`agents/compile-worker.md` frontmatter,fork 强制):`fs_read / fs_grep /
fs_glob / run_python / kb_footprint / compile_precedent / compile_check_verifiability /
compile_emit / compile_expected_hits / dev_probe / dev_help`——只读知识+受门构造+
只读探针,无 dev_run/dev_ssh(编写与上机解耦的工具层执行)。

**知识检索序**(worker md 明文,按可信度递减):`compile_precedent`(同意图已验形态)
→ `kb_footprint`(已验语法/行为;uncertain 观察带语境标注,冲突时设备实验仲裁)→
版本手册 `knowledge/data/markdown/product/manual_<version>/` → `dev_probe`/`dev_help`
(活语法)。**溯源红线**:断言期望值必须溯源手册/先例/意图,禁 observe-then-assert
(照抄设备当前回显=假验证,全仓铁律)。

**V6→V8 变化(知识路由反转)**:V6 引擎侧预检索块(footprint/先例预注入 brief,
IST_FOOTPRINT_PREFETCH)在 V8 已移除——知识获取全部改为 **worker 自拉**(白名单
工具+检索序指引)。理由:预注入是引擎替 worker 选知识(框定效应,(37) 的工程对应),
自拉让检索深度随 case 难度自适应;brief 只承载**事实性证据**(设备回显/裁决/意图),
不承载预消化的知识选择。

### 19.3 brief 组装契约（`briefs.py`,V8 形态）

布局(官方长上下文实践+trace 取证定形):**首行机读信封**(autoid/manifest_path/
product_version/device_build/round/user_decision_path)→ **数据区**(响度降级排列)→
**意图**(recency 高位,紧邻指令)→ **指令区**(最末)。

- **逐轮设备证据按引用分级**(X8 载荷纪律):只有最新失败轮的 `device_context` 全文
  内联(≤6000 字符),更早轮降级为归因结论行+`ref` 路径(worker 需要时 `fs_read`
  现查)——旧版全轮内联随轮数线性膨胀。
- **前几轮配置卷**:`outputs/<aid>/history/case.r{N}.xlsx` 路径清单注入,worker 自行
  diff(重编不盲改)。
- **重编轮增量**:max 思考深度标记(首败即升,2026-07-09 裁决)/FINAL attempt 标记/
  **矛盾案对照指引**(单跑过∧连跑挂 → 先疑跨案持久态干扰,优先案内自净,不无差别
  改卷)/**独立重判指令**(采信上轮归因前先对每轮回显独立回答「配置实现意图了吗」
  ——形态错配常在配置结构,不在断言润色)。
- **ought 裁决注入**(§11.11):panel 呈报获用户答案后,brief 携带差异原文+引擎理解+
  用户裁决(confirm=按假设编/correct=用户原文最高权威/adopted=同键历史判例背书)。
- **defect_candidate 换形态指令**:上轮疑产品缺陷 → 本轮同意图换配置形态实现
  (先检索同意图先例)——异形态复现才坐实缺陷,pass 则证明是形态问题。

### 19.4 构造式 emit 接口（blocks 组合子+ref 前缀溯源）

worker 产卷首选 `compile_emit(blocks=…)` 组合子通道(steps 仅留给 blocks 表达不了的
形态——worker md 明文)。**ref 前缀溯源**(`main/case_compiler/blocks.py`):worker 在
组合子上标 `footprint:<节点>` / `manual:<分册>:<行锚>` / `precedent:<autoid>` /
`config_derived` / `intent`,`expand_blocks` 机械组装 provenance IR——**LLM 不拼
IR JSON**(结构化数据机器拼,LLM 只做选择)。打回率持续量化落
`runtime/logs/emit_stats.jsonl`(V6 验收期实测:blocks 通道使 emit 打回率
48-52%→12-20%,带日期历史测量)。

### 19.5 worker 自查工具（编写期自证伪,不自评估）

| 工具 | 用途 | 锚 |
|---|---|---|
| `compile_check_verifiability` | 欠定 claim 证伪:命中数/分布类断言对 rr 等机制是否可验——不可验 → `NEEDS_USER_DECISION` 走引擎欠定问询(先问后落,A 层强制) | verifiability_tool.py |
| `compile_expected_hits` | checker 状态机:命中数断言的可验性/期望值自查(dig 序列→计数语义) | checker_tool.py |
| `dev_probe` | 只读探针(show/get 白名单):验命令语法/看回显形态;**空回显≠失败**——编译期设备是干净态,统计/会话面必空(工具自带注记,防重复空探) | run_case.py |
| `dev_help` | 设备 `?` 上下文帮助,零副作用协议(直连交互 shell,Ctrl-U 杀行不回车——`apv_ssh_execute` 会把截断前缀真执行一次,故不复用) | device_mcp_client.py |

界线:worker **只生成不自评**(生成/评估隔离,worker md description 明文);语义终判
在上机 oracle,结构判定在 emit 机械门。

### 19.6 知识闭环（写回/两段闸/回滚——V8 增强版）

- **真 PASS 双写回**:先例+footprint,经 **device_verified 第二权威源**——digest 每
  case 落 `runtime/logs/verified_runs.jsonl`(agent 沙箱黑名单内防篡改),footprint
  merger 三重校验(台账存在 ∧ verdict=pass ∧ 命令∈卷面)——解决「运行时命令不在
  手册 → 写回全 skip → 知识循环堵死」(V6 遗产,V8 沿用同源写入路径)。
- **行为知识两段闸**:归因/编写中发现的设备行为经 `submit_behavior_fact` 落候选
  (observe_cmd∈卷面校验,behavior_tool.py)→ 该 case 真 PASS 才晋升挂 footprint
  叶节点——未经 oracle 的观察不得直接变知识。
- **V8 新增·写回回滚**:终验 fail 时,此前已 writeback 的先例**回滚撤销**(半毒先例
  不留库,nodes.py closing 段)——V6 只有写入无撤销,「写回后被终验推翻」的毒窗口
  在 V8 关闭。与自愈环(§CLAUDE 自愈合知识引擎)组合:fail 轮观察以
  `validity=uncertain`+语境入库,PASS 实证才升级,双向都有闸。

### 19.7 归因修法生效性（`_prev_attribution` 闭环,V6 遗产沿用）

last_run 按 autoid merge 时保留上一轮归因为 `_prev_attribution`(batch_tools.py;
曾整条覆盖丢失)——attributor 对重编后再 fail **先核对**:上轮修法上卷了吗(diff
history 卷)/同签名复现了吗(`_fail_signatures` 跨轮)——**方向已证伪禁同向再开**
(588691 实证:错误修法方向曾被连开三轮)。frozen 语义配套:连续两轮同签名 fail →
`.frozen.json`(重写保留 overrides 换法历史);frozen≠终态=「重编必须换法」标记,
emit `override_frozen_reason` 门强制显式声明;终态=frozen∧轮次封顶。

### 19.8 V6 性能护栏在 V8 的存续表

| V6 护栏 | V8 状态 | 锚/说明 |
|---|---|---|
| run-identity 绑定(stale_log 不采信) | ✅ 沿用 | batch_tools `fetch_batch_details(min_epoch)`,早于 deliver 基线的日志判 unknown |
| 上机互斥(进程锁+跳板机残留探测) | ✅ 沿用 | dev_run_batch 双层防 |
| fail 子集复测+终验整卷 | ✅ 沿用并强化 | §16 终验幂等闸(INV-8 组成指纹) |
| fork 弹性(墙钟两层+transient 重试+max 思考放宽) | ✅ 沿用 | resilience.ForkExecutor,`IST_FORK_WALLCLOCK*` |
| briefs_path 批量载荷通道 | ⚠ 引擎主路不再需要 | V8 逐案构建 brief 单发 fork(author 节点);批量通道保留给 `compile_fanout(skill="dyn-*")` 动态子 agent 场景 |
| fresh-PASS grade 短路 | ❌ 已废 | 语义随 grade 闸删除而消失(942 配对实证 LLM 审 LLM 判别力 3pp);机械等价物=lint 凭证 mtime 新鲜性+pass 卷面锁 |
| 预检索块(IST_FOOTPRINT_PREFETCH) | ❌ 已废 | 知识路由反转为 worker 自拉(§19.2),防框定效应 |
