# 引擎 ↔ 理论对照审计（增删改清单 + 信号机设计）

> ⚠️ **历史存档（2026-07-17 归档,team4 docs 整编）**：V6 引擎↔理论对照(2026-07-09),增删改清单已被 V8 消化;后续理论对账见 AUDIT_design_theory_gaps.md。事实存档不删,现状勿引本文。

> 2026-07-09。依据：`docs/THEORY_k_state_machine.md`（三合取 / 分层可导 / K 状态机 / 锚差监控）。
> 判定四值：✅符合保留 / ⚠符合但需改 / ❌违背或冗余需删 / ➕理论要求但缺失需增。
> 用法：每项带理论构件归属与依据；"➕/❌"项动工前过用户（用户要求 4）。

## 一、逐机制判定表

### A. 编译产出面（合取①②的生产与守护）

| 机制 | 理论归属 | 判定 | 依据 |
|---|---|---|---|
| worker fork 隔离编写（分布式解码） | D 解码的多样性冗余（§1、C2 反驳） | ✅ | 570/608 兄弟一对一错，即时写回流动其正解——冗余是自愈来源 |
| `_build_brief` 数据置顶/意图紧邻指令/归因降级为假设 | 合取①的"P⊩D"注意力工程 | ✅ | trace 019f3bc3 取证驱动；末轮全历史+max 思考=行为层实验的 brief 侧支撑 |
| preserve_constraints / rewritable_claims 分层 | D 的欠定切分（Ω⑤编译期先验排除） | ✅ | verifiability 机制；dongkl 批 7/34 欠定全部编译期拦截 |
| emit 结构门+lint+必崩门（17 门） | E 的良构性谓词 + I(a)=0 拦截 | ✅ | A 层，mirror 源码推导；325 卷反扫 |
| `intent_record_type_gap` probe 拦截 | 合取②的词面显式子集（dim_V 意图侧） | ✅ | 644/373 双机理实证；C1 已声明覆盖边界 |
| **重编/override 单调性检查** | 守恒律 ΔI_V≥0（合取②压力路径投影） | **✅ 已落**（2026-07-09） | `compile_emit` 单调门：旧卷基线，观测动词类+DNS 记录类型集合不减；`coverage_reduction_reason` 声明放行；`monotonicity_violation` 信号双路径（拦截/声明）；回归 `test_monotonicity_gate.py` 6 例 |
| worker md"换法≠删覆盖/最小拓扑"文案 | 合取①②的 C 层劝告 | ⚠ | 与理论一致但属 prompt 层——单调门落地后降为解释性文字，守护职责移交机械门 |
| probe 的 `_PROBE_NO_REWORK` fail 路径注入 | G⊔E⊔V：诊断信息在 fail 路径变现 | ✅ | 12/13 真机 PASS 同形实证（不配 rework 资格），合取式诊断 |

### B. 验证与归因面（合取③ + 分层可导）

| 机制 | 理论归属 | 判定 | 依据 |
|---|---|---|---|
| dev_run_batch_digest（互斥/run-identity/跨轮对照） | 合取③ oracle + Ω④通道层近似算子 | ✅ | stale_log/min_epoch=观测可信性对账；同签名两轮=非瞬态（判定树通道层） |
| 机械预判只认 `^`（fail_attribution） | 语法层完全可判定（§3.2） | ✅ | 关键字表已删的历史决策被理论追认（其余层不许猜） |
| **`^`→dev_help 自动接线**（本轮已落） | 语法层算子本体（? 读表） | ✅追认 | 044572 实证；digest 内同进程同连接，结果随 last_run 流动 |
| 形态检验轮（defect 候选换形态复现才坐实，两段路由） | 行为层可导性=实验二分（§3.2 推论） | ✅ | 413/453 一轮判死反例驱动；644 多形态复现正例 |
| attributor 判缺陷四道核对（先例对照/被拒手段） | 判定树的 md 侧说明 | ⚠ | 与理论一致；其中"被拒命令∉意图字面"可下沉为机械信号（谓词可判），md 保留 why |
| known_defects DC 短路 | K（known_issue 血统）消费 | ⚠ | 符合，但缺**版本区间语义**：当前 token 匹配不查 fix_version——被测 build ≥ 修复版本时应失效（用户指出的来源③） |
| 瞬态判定=复现性（换时间重跑消失） | Ω④ 与"重跑"算子 | ✅ | dongkl 5 例误归瞬态 100% 复现的取证驱动 |
| `ist-verify` 独立上机 | 合取③的独立 oracle（生成/评估分离） | ✅ | 自生成自评估教训 |
| ~~grade LLM 卷面审~~（已删） | 合取② LLM oracle | ✅已删 | 942 对判别力 3pp；理论追认：忠实性从未被正确度量（DS-2 补此洞） |
| compile_fanout 的 fresh-PASS grade 短路残留 | （grade 已删的伴生逻辑） | ✅已核清 | `SKIPPED_FRESH_PASS`/`force_regrade` 全仓零命中；`.grade_credential.json` 是**活的 lint 凭证机制**（source=lint），仅文件名带历史命名——不动 |

### C. K 面（状态机与运维）

| 机制 | 理论归属 | 判定 | 依据 |
|---|---|---|---|
| uncertain 入库 + 升级分支 + 观察组渲染 | 状态机 absent→uncertain→verified/conditional | ✅ | P1；三通道带标（拉式/推式/dream） |
| device_verified 门（pass-voucher 三重校验） | verified 锚（autoid∧run_ts∧卷面命令） | ⚠ | 符合但锚缺 build 维——见 ➕build 锚 |
| **build 锚（三源）** | stale 检测信号源（§5.1） | **⚠ 最小落地**（2026-07-09） | 已落：digest 记提交 build 进 verified_runs.jsonl → device_run_ref 透传（writeback/closing）→ 条目 `evidence.device_run.build`。未落：源①show version 自述采集、源③known_issue fix_version、stale 派生判定与渲染（随缺口 D 体检批） |
| **quarantine 字段 + 方向体检扫描器** | poisoned 发现与处置（案底+不渲染） | **➕缺口 D** | 五卷体检手动预演；审计器（含拒绝回显白名单）已验证方法，待固化 scripts/ |
| PASS 即时写回（writeback_one） | latent 消除（可达性维度） | **⚠ 补注**（yzg #10 牵连） | 兄弟流动价值实证不变；但终验后的第二次写回发生在「终验 fail 已落盘」之后——写回凭证只核 emit 新鲜度，不核最后一次整卷裁决，半毒先例（668015/030/044）入库。修法并入缺口 E（写回前置条件加 ctx_delivery pass） |
| mirror 先例 + intent 索引 | K 的 precedent 血统 | ✅ | 中心论断的主变量载体 |
| footprint 渲染配额/观察组免配额 | 信号传递（改姿势不改可见性） | ✅ | P1 |
| kb_memory_search 拉式通道 | reachability（suppressed 的补偿） | ✅ | memory/ 黑名单内推拉互补 |
| **词汇映射条目（意图词↔实现词）** | lexically-unreachable→reachable | ➕后置 | 413 实证；需检索日志基建，量小、递归一层可接受（C7） |
| dream consolidate | K 的整理（同主题合并） | ⚠ | 符合，但合并时须尊重 validity/observed_under（uncertain 带标已做）；合并逻辑未按"观察组不可合并为无条件规则"约束——pe1 判例被无条件化的教训在 dream 路径尚无防护 |

### D. 编排与护栏面

| 机制 | 理论归属 | 判定 | 依据 |
|---|---|---|---|
| StateGraph 引擎（LLM 不当胶水） | 判定树/流程的确定性载体 | ✅ | — |
| ledger 迁移合法性表（passed 终态锁） | 状态一致性（case 状态机） | **❌ 改判**（2026-07-10 yzg #10） | 锁按迁移边设防未按证据权威设防：δ(passed, oracle_fail) 未定义且被恒等补全——终验 3 fail 无痕吞掉、照常写回。缺 oracle-override 通道（frozen 有配对通道，passed 没有）与 pass 语境锚（∃-pass 冒充交付-pass）。见 THEORY §5.5 四公理与缺口 E |
| loop_guard / tool_result_prune / 摘要中间件 | 理论外的资源护栏 | ✅保留 | 不属三合取/K 理论管辖，工程必要；标注"理论外"防止误纳入理论叙事 |
| frozen 闸 + override 通道 | 行为层"已证伪子空间"的签名级近似 | **⚠ 改判**（2026-07-10 yzg #7） | 机制本身正确且在主卷路径实证生效；但 digest 跨轮对照按「同路径 last_run」键控，引擎子集轮每轮换目录（`_fails_r{N}`）→ prev_map 恒空——**V6 主路径下 frozen/瞬态复现护栏结构性失活**，退化为 brief 历史+轮次封顶的软兜底。修法并入缺口 E（按 autoid 全射对账） |
| escalate/ask_user 欠定问询 | Ω⑤ 与用户决策通道 | ✅ | 官方 interrupt；答案落 user_decision.json |
| 环境池（默认关） | 通道层容量 | ✅理论外 | — |

## 二、增删改总清单（按优先级）

**➕ 增（理论推导的结构缺口，全部机械/数据，零 prompt）**

1. **信号机**（见 §三——要求 2 的载体，其余增项的记录基座）
2. ~~**单调性守恒门**（缺口 B）~~ ✅ 已落（2026-07-09）：emit 对重编路径做观测维度集合（观测动词类 + DNS 记录类型）不减检查；删除须 `coverage_reduction_reason` 显式声明并记信号（genuine_v_count 计数维经论证放弃——合法修法常合并断言，按维度集合判才零误杀）
3. **build 锚三源**（缺口 C）⚠ 最小段已落（2026-07-09）：digest 写 verified_runs.jsonl 带 build + footprint/writeback/closing 透传至条目 `evidence.device_run.build`。余下：源① show version 采集、源③ known_issue fix_version、渲染 `[stale?|实证于X,当前Y]`、known_defects 版本区间失效判定
3.5 **缺口 E（2026-07-10 新增，当前最高优先）——oracle 残差公理落地包**（THEORY §5.5 四公理，#10/#7/瞬态护栏 dead code 三案同根）：
   - ①终验回灌：digest→ledger 按 **dom(V) 全射对账**（遍历本轮裁决集，非台账反查 failed_active）；「oracle 反证终态」显式迁移（passed→final_verify_failed 或等价残差）+ 信号；
   - ②pass 语境锚：passed 记录取得语境（subset/full），交付判据只认 ctx_delivery；写回前置条件同步收紧；
   - ③跨轮护栏键控修复：digest 跨轮对照/frozen/瞬态复现按 autoid 读主卷 last_run（或子集结果 merge 回主卷后对照）；
   - ④矛盾即问：oracle 反证已锁结论 → 第三条 ask_user 边（如实降级 vs 复验重排 vs 接受单跑语义，用户裁决）。
4. **方向体检扫描器固化**（缺口 D）：审计器脚本进 scripts/debug/intent_fidelity_audit.py（sweep + 报告，不动卷）；quarantine 字段与"不渲染留案底"消费契约
5. **"被拒命令∉意图字面"机械信号**：attribute 时 caret 命令与 manifest 意图文本比对，结构化事实随归因落盘（A 表 attributor ⚠ 项的下沉）

**❌ 删/查删**

6. ~~fresh-PASS grade 短路残留~~——已核清（全仓零命中；.grade_credential.json 是活的 lint 凭证机制不动）

**⚠ 改**

8. dream consolidate 加"观察组不可合并为无条件规则"约束（数据完整性，pe1 教训）
9. known_defects 匹配从纯 token 升级为 token+版本区间（并入 3）

## 三、信号机设计（要求 2：状态信号可记录、供 debug）

**现状问题**：信号散在五处（ledger audit.notes / emit fastlog 人读文本 / events.jsonl TUI 卡片 / last_run._attribution / footprint 条目字段），跨批 debug 时无法回答"这条知识何时变的、谁动的、当时锚是什么"。

**设计**：单一 append-only 信号流 `runtime/logs/k_signals.jsonl`（runtime/ 在 agent 沙箱黑名单内=锚可信性 C5 的同一信任根）。

```jsonc
{"ts": 1783520000.0,               // 时间
 "signal": "uncertain_ingested",   // 信号名(闭集,见下表)
 "subject": "sdns.host.status:ab12"|"204651759025035644",  // fact_key 或 autoid
 "batch": "dongkl_79993_full",
 "source": "closing._ingest",      // 触发点(代码位置级)
 "payload": {...}}                  // 信号专属:锚差/证据ref/新旧状态
```

**信号闭集 v1**（从状态机迁移表+三合取violation直接推导，一迁移一信号）：

| 信号 | 触发点 | payload 要点 |
|---|---|---|
| `uncertain_ingested` | closing._ingest | fact_key, observed_under, autoid |
| `upgraded_verified` | merger 升级分支 | fact_key, 旧/新 evidence |
| `observation_group_formed` | 入库端 merge_fact 互异语境首跨 2（✅ 2026-07-09 接线；渲染端不发防刷屏） | node, fact_key, contexts[] |
| `conflict_declared` | conflicts_with 追加 | pair |
| `writeback_done` | writeback_one | autoid, build(锚三源之②), files |
| `frozen` / `override_frozen` | digest 跨轮 / emit | autoid, signature / reason |
| `defect_claim_deferred` | verify_phase 形态检验门 | autoid, round（已有 audit.note，迁移至此） |
| `syntax_help_attached` | digest `^`→dev_help | autoid, rejected_cmd |
| `monotonicity_violation` | 单调门（✅ 2026-07-09 随门落地；拦截/声明双路径） | autoid, removed_kinds[], removed_types[], declared? |
| `intent_gap_flagged` | probe | autoid, gap[] |
| `stale_flagged` / `stale_refreshed` | build 变更派生 / 复验（➕3） | fact_key, anchor_build, current_build |
| `quarantined` | 体检/人工（➕4） | fact_key, reason, 案底 ref |
| `escalated` / `awaiting_user` / `user_decided` | 引擎节点 | autoid, question/answer 摘要 |
| `final_verify_failed`（缺口 E 新增候选） | 终验对账：passed 案整卷 fail | autoid, ctx, signatures |
| `verdict_unconsumed`（缺口 E 新增候选，兜底） | 对账收尾：dom(V) 中未被消费的裁决 | autoid, verdict, ledger_state |

**实现形态**：`main/ist_core/memory/footprint/signals.py` 单函数 `emit_signal(signal, subject, batch="", source="", **payload)`——append 一行 jsonl，失败静默（信号不阻断主流程）；各触发点一行接线。查询：`fs_grep <fact_key|autoid> runtime/logs/k_signals.jsonl` 即得该主体全生命周期轨迹——debug 的"这条知识/这个 case 经历了什么"一问一答。

**与现有设施的关系**：audit.notes 保留（ledger 内 case 级细节）；fastlog/events.jsonl 保留（人读/TUI）；k_signals 是**跨批、主体索引、机器可查**的第三视角，不替代前两者。DS-1/DS-4 数据集的自动追加可由信号流驱动（escalated/user_decided → ds1 候选；批交付 → ds4 行）。

## 四、执行顺序建议（待用户裁决）

1. ~~信号机~~✅ → 2. ~~单调门~~✅ → **2.5 缺口 E 落地包（终验回灌/语境锚/键控修复/矛盾即问——yzg 双回合实证后升为最高优先）** → 3. build 锚源①（show version 自述采集+锚差报警——yzg 两例实证：省两轮 ≈¥90、源②错值 568vs585）→ 3.5 uncertain 入库 build 锚+语境截断修复（问题#8）→ 4. 体检扫描器+quarantine → 5. 被拒命令∉意图信号 → 6. 死代码清理 → 7. dream 约束。
每步跑门（pytest + 相关反扫）；与理论冲突处停下讨论（用户要求 4）。
