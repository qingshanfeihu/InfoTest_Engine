# 取证 A — RR/分布类采样敏感断言 + flaky 写回洗白（§18.15 单元 A）

> 单元：oracle 手 A。方法：/engine-verify-loop 的实证→理论→设计三段，**只读，零代码改动**。
> 数据源：`workspace/outputs/dongkl/last_run.json` + `facts.jsonl` + `verified_runs.jsonl` +
> `<SCRATCH>/trace_dumps/`（worker LLM 思维链）+ 盘上 footprint/precedent/mirror + 断言原语源码。
> 全文三类标签：**【数据事实】**（行级/子串级铁证）/ **【设计判断】**（我的对抗性结论）/
> **【给用户】**（设计张力，附倾向+反方，不自作主张）。

---

## 0. 一句话结论

**§18.15-A 方向对、不充分。** emit 门要求的替代形态「集合相等」在框架断言原语上**不可构造**（found/not_found 是正则 search，写不出补集取反），「区间」只能落成 593516 亲历的 bug 温床数值正则——**A 门若单飞，会把分布类案从「假 pass」变成「永久欠定卡死」，除非单元 D（我方结构化断言通道）先落地提供替代形态**。且洗白的**根因在归因层**（attributor 对配比 40 的成员 Hit:0 发「加采样刷过」），A 三件套只治 emit/写回两处**症状**、不碰这条根。写回护栏还把粒度切错（会误伤合法的语法/行为写回）。

---

## 1. 实证根因（从数据，行级铁证）

### 1.1 593516 是什么：WRR 3:2:1 分布类案，断言全是 h-样本读数

**【数据事实】** `workspace/outputs/203031753781593516/case.xlsx`（与 sub3 pass 版**逐行一致**）三处 check_point：

| 行 | 观测命令 | 算子/断言 | 形态诊断 |
|---|---|---|---|
| step8 | `show statistics sdns pool p1`（仅 3 次 dig 后） | `found` `Hit:\s+3` | **精确计数**，假设 WRR 前 3 请求全落 p1——observe-then-assert |
| step44 | `show statistics sdns pool p4`（Phase2） | `found` `Hit:\s+[1-9]\d*` | **非零命中**，低配比成员小样本必 flaky |
| step46 | `show statistics sdns pool p1`（Phase2） | `found` `Hit:\s+[4-9]\d*` | 意图「≥4」但正则**漏配 10–39**（秩亏/错区间 bug） |

三种都是 h-样本（轮转指针 h 的采样读数），非 h-不变式——与 S §0.5 行170「某成员命中 N 次是 h-样本读数」逐字吻合。

### 1.2 verdict 流：fail→fail→pass→写回（同一断言，只是采样够散）

**【数据事实】** `runtime/logs/verified_runs.jsonl`（同 build `..10_5_0_568`）：

```
dongkl/case.xlsx        delivery  fail  signatures=["Hit:\s+[1-9]\d*"]   (run_ts 1784075757)
dongkl__sub2/case.xlsx  subset    fail                                   (run_ts 1784083174)
dongkl__sub3/case.xlsx  subset    PASS                                   (run_ts 1784086794) → writeback
```

pass 版与 fail 版**断言相同**。worker 的「修复」（trace `593516_r2_58c59851`）是两手：①Phase2 dig 增至 30 次（照抄 rerun_isolated 的「加采样」建议）②**丢掉 flaky 低配比 p3 检查，换成高配比 p1/p4 检查**。→ 案 pass，但脑图意图「验证 3:2:1 三池加权参与」**降级为只验 p1/p4**（p2/p3 是否参与不再覆盖），且三处 fragile 形态原样留存。**这不是把断言改robust，是把测不稳的部分删掉 + 加采样把剩下的刷绿。**

### 1.3 洗白源头：两条互斥归因，「加采样」那条驱动了重写

**【数据事实】** `facts.jsonl` 同案两条 attribution（同 round1、不同 ctx）：

```
delivery: layer=V disposition=rerun_isolated  h_position=h_lambda
  fix="增加dig发送次数(如20-30次)以提高统计覆盖率…机制本身正常(WRR权重3:2:1验证通过),属流量样本不足导致的概率性遗漏"
subset:   layer=V disposition=defect_candidate h_position=none
  fix="动态添加 sdns pool p4 到已配 RR 算法后,RR 轮转未将 p4 纳入——p4成员(226)从未被返回(Hit:0)。
       与 sibling case 778012 同根因,kb_footprint 已记 known issue。建议设备侧修复 RR 轮转状态更新逻辑"
  evidence="Hit:                       0"
```

worker 的 brief（`593516_r2` INPUT）**同时携带这两条**，`rerun_isolated`（加采样）排在 delivery 首位。

**【设计判断】** delivery 那条归因**理论上是错的**：p4 配比 40/46，10 次 dig 期望 ~8.7 命中，实得 0——按 S §0.5 行156「h 边缘化后统计量仍偏离=缺陷候选」，这是缺陷候选、不是「样本不足的概率性遗漏」。引擎自己在 subset 轮已给出正确的 `defect_candidate`，却让 delivery 轮的 `rerun_isolated` 进了 worker brief 并驱动重写。**「加采样把 flaky 断言刷过」是引擎亲手递给 worker 的指令**——这是本单元的铁证。

### 1.4 写回确凿：采样噪声进了第二权威判例源，且 live 可检索

**【数据事实】**
- `facts.jsonl`：`{"ev":"writeback","aid":…593516,"targets":["precedent","footprint"],"provisional":true,"voucher_run":"run:…sub3…"}`
- 物理证据：`knowledge/framework/mirror/verified_203031753781593516.xlsx` **在库**（mirror 根下 `verified_*`=机生血统，precedent_tools.py 行99；(45) 自指风险）。
- footprint `sdns.host.json` / `sdns.service.json` 的 verified `source_threads` 含 `compile_writeback:203031753781593516`。
- **provisional 不挡检索**：`compile_precedent` 检索路径**无 provisional 过滤**（precedent_tools.py grep 零命中），且 `compile_writeback` 写盘即失效 corpus 缓存、注明「同 run 内后续 compile_precedent 立即能检索到」。→ 采样敏感断言链**现在就 live、可被后继 RR/WRR 案检索**。且 `compile_precedent` 返回**完整触发→断言链**（precedent_tools.py 行331），「先例只供配置形态不供断言极性」只是散文提醒（行386-393，C 层）——**挡不住 worker 照抄 fragile 形态本身**。

**【设计判断】** brief 担心的「若真写回=采样噪声被编码成第二权威判例源」——**证实**。且比预想更活：provisional 仅台账回滚簿记，不阻断检索。

### 1.5 778012 厘清：不是三个矛盾叙事，是同一案跨轮跨层演化

brief 列的三叙事，用数据判定：

| 叙事 | 出处 | 判定 |
|---|---|---|
| 「sdns clear all 词序错」 | HANDOFF §D | **错/陈旧**。ANALYSIS 行179 已自我更正；源于 command_existence 门误标（ANALYSIS 行29/34/66，属单元 D 盲区，非本单元） |
| 「G/reflow：`sdns service ipv6` 语法不存在」 | last_run r1 + `778012_r3` brief | **r1 delivery 真相**：worker 自造了不存在的 `sdns service ipv6` 子命令，设备 `^` 拒（anomaly_lines 实证）。这是 worker 自己的配置形态错（G 层） |
| 「RR 轮转缺陷」 | ANALYSIS + subset attribution | **subset 轮真相**（语法修好后浮现）：dig 全命中 p1、p4 完全不进轮转 → fail 签名复现 |

**【数据事实】** 778012 = r1 worker 语法错（G）→ 修好 → subset 底层 RR 轮转缺陷（V/defect_candidate）浮现。**与 593516 同族**（subset attribution 自称「与 sibling 778012 同根因」），但**severity 不同**（ANALYSIS 行201-206，我复核 verified_runs 佐证）：778012 **完全卡死**（全落 p1）→ 确定性 fail；593516 **部分轮转**（9×p1+1×p3）→ 采样够散即 pass。**正是「部分轮转」让 593516 能被 flaky 刷绿并写回，而 778012 卡死刷不绿——两案的 pass/fail 分岔本身就是「dig-命中断言对 RR 采样方差敏感」的活证明。**

---

## 2. §18.15-A 设计裁决（对抗性）

设计三件套：①emit 期机械门（断言读 h-in-λ 通道样本读数→拒，要集合相等/区间）②写回护栏（h-变量断言的 pass 不够格写 footprint/precedent）③domain_grammar 标注 h-in-λ 通道。**裁决：方向对，三处不充分。**

### Gap 1 —【最关键】emit 门要求的替代形态「集合相等」不可构造，A 与 D 强耦合

**【数据事实】** 框架断言原语（`knowledge/framework/mirror/lib/check_point.py`）：
- `found`（行22）：`re.compile(expect, re.DOTALL).search(result)`——正则 search over 命令窗口
- `abs_found`（行38）：`re.escape` 字面 search
- `not_found`（行55）：正则 search，命中即 fail（取反）
- **无数值比较、无集合算子、无计数算子**暴露给用例作者。

**【设计判断】** 由此：
- **「轮转集合 = 期望成员集（集合相等）」不可构造**：能写 `found(A)∧found(B)∧found(C)`（成员都出现），但写不出「且无其它成员出现」——那是对开放文本窗口的**补集取反**，需枚举所有非成员 IP 做 not_found（无界），正则 search 表达不出。
- **「区间」只能落数值范围正则**，恰是 593516 step46 `[4-9]\d*` 漏 10–39 的 bug 温床；开区间/「≥N」对正则尤其敌意。

∴ **A 门拒了采样断言、却只能要求落「集合相等（不可构造）/区间（bug 源）」→ 分布类案没有合法替代形态 → 被推向永久欠定卡死。** 真正能落的替代形态需要**单元 D**：在我方验证侧加解析层（§18.10 oracle 残差门从「窗口对齐」扩到「结构化对象抽取」），把响应块解析成对象、抽 hit 整数与成员集、用真算子（集合相等/守恒区间）比。

**这是我对「收口优先序 A(BLOCKER) > … > D(分期)」的核心质疑：D 不是 A 之后的锦上添花，是 A 门有替代形态可落的使能前提。A 无 D，对目标案是死路。**（详见 §4 给用户问题 1。）

### Gap 2 — 根因在归因层，A 三件套只治 emit/写回两处症状

**【数据事实】** 洗白源头是 §1.3 的 attributor：对 p4（配比 40/46）Hit:0 发 `rerun_isolated`「加采样、机制正常」。而 S §0.5 行156-157 的「欠定/缺陷分界」判据机械成立且引擎已有正确标签在手（subset 的 defect_candidate）。

**【设计判断】** A 的 emit 门 + 写回护栏都在**下游**（断言进卷 / pass 写回），**挡不住 attributor 生成「加采样刷过」的 fix_direction**——它已经在 worker brief 里、已经驱动了重写。A 该补一条 **attributor 机械后校验**（与单元 B 同型；设计自己也说「A 与 B 都是 §18.14 attributor 机械复核同型的延伸」，但 A 的 bullet 没写出这条）：

> **rerun_isolated / 加采样类归因，若受影响成员的配比份额使 Hit:0 在该样本量下统计不可能（配比份额 × 样本量 ≫ 0），则内部矛盾 → 不得 rerun_isolated，转 defect_candidate。**

判据全从结构化事实机械可算：配比读 config `sdns host pool <host> <pool> <weight>`、命中读 device_context `Hit:` 字段、样本量数 dig 步——无关键字白名单、无写死命令。

### Gap 3 — 写回护栏粒度切错，会误伤合法的语法/行为写回

**【数据事实】** 593516 实际写回 footprint 的内容：
- `sdns.host.json` / `sdns.service.json`：**配置语法事实**（`sdns host pool "autotest.com" "p1" 3`、`sdns service ip s2 fc00::232`）——h-不变量，与采样无关，命令确实解析通过。
- `sdns.host.method.json` fact `2f173967`：一条**正确**的 wrr `validity=uncertain` 行为观察——「权重决定命中比例、不决定严格顺序;顺序类断言在 wrr 下不可验,应改分布区间/换 ga」。这正是本坑该沉淀的知识。

**【设计判断】** A 说「h-变量断言的 pass 不够格写 footprint/precedent」——措辞把 footprint/precedent **并列一刀切**，会连上面这些合法的语法/行为写回一起拦掉（知识增长被误伤）。正确切法=**按证据类型分流**：config-fact / behavior-fact（h-不变式）照写；但**含 h-变量断言的案不得获得案级 precedent `device_verified` 戳**，降级为 `uncertain` 判例——与 (45) 行527「未经 oracle 残差审计的历史 verified 降级 uncertain」同款出口。（详见 §4 给用户问题 2。）

### 相邻发现（不属 A，记录移交实现阶段）

**【数据事实】** `grade_extract_script.py` 已有分布门检测器：行362 `_dist_ctx`（config 含 rr/wrr 即分布上下文）、行400-401 抓「unbounded `\d+`=恒真」、行403-404 抓「fixed number（如 Hit:\s+1）= right-by-luck / observe-then-assert」。但：
1. **grade_extract 是诊断 facts 生产者、不是 emit 阻断门**（grade 闸 2026-07-07 已删）→ 593516 断言照进卷、facts.jsonl 里也没见这些 reason 触发。
2. **检测器有覆盖洞**：行400 抓 `\d+`、行403 抓 fixed，而 `Hit:\s+[1-9]\d*`（非零任意）是**第三形态**，从两个检测器之间漏网。

**【设计判断】** A 的 emit 门可**直接复用并收紧**这段检测逻辑（从诊断升为 emit 阻断 + 补第三形态），不必新造——降低实现成本；但这**不改变 Gap 1 结论**（替代形态仍需 D）。

---

## 3. 修法建议（先不改代码；站得住的部分给精确落点）

按「站得住 → 精确落点」「有张力 → 转 §4 给用户」分开。

**站得住、可直接落（不触 Gap 1 的 A/D 耦合争议）：**

1. **attributor 机械后校验（Gap 2）** — 代码 `main/ist_core/tools/device/fail_attribution.py`（与单元 B 共址）。加一条：判 `rerun_isolated` 且 `h_position=h_lambda` 时，机械算「受影响成员配比份额 × 样本量」，若 ≫0 而实测 Hit:0 → 翻 `defect_candidate`。数据全结构化解析，零写死命令。回归锚见 §5。

2. **写回护栏分流（Gap 3）** — 代码 `main/ist_core/compile_engine_v8/nodes.py` `_writeback_one`（行1074）。case 含 h-变量断言时：`compile_footprint_writeback`（config/behavior 事实）照走；`compile_writeback`（precedent 案级戳）降级/跳过，引 (45) 的 uncertain 出口。判「案是否含 h-变量断言」复用 §2 相邻发现的检测器。

3. **grade_extract 检测器补第三形态 + 升为 emit 门候选** — `grade_extract_script.py` 行400-404 补 `Hit:\s+[1-9]\d*`（非零任意）分支；emit 门落地时从此处提取判据。

**h-in-λ 通道标注（设计③）——【数据事实】数据已在，勿重造：** `domain_grammar.json` 的 `algorithm_classes.distribution`（rr/wrr/grr/gwrr）+ `count_field_words`（hit/命中/计数/counter/count/statistic）+ distribution 的 provenance（「均摊/加权轮询=分布类,发 N 次→各后端累计命中∈统计区间,守恒 Σ==N;ga/topology/rtt=确定性映射」）**已经是** h-in-λ 判别式。**【设计判断】** 但 `domain_grammar.py` 加载器是**逐 key 硬编 accessor**（`distribution_methods()` 行54、`count_field_words()` 行58……）——往现有 `distribution.methods` 列表加新算法=零代码，但**立一个新类别 accessor + 消费它的门=新代码**。故「自愈四层零代码」只适用于门存在**之后**的增补，不适用于**首次立门**。h-通道标注溯源：手册（distribution provenance 已锚「手册:均摊/加权轮询」）/footprint，禁现编——已合规。

**不建议动 Gap 1**：在 D 落地前，A 门对分布类案应走 `ask_user`/`escalate-when-stuck`（如实呈报「本环境无 h-不变式断言形态可落」），**不硬拒**——否则把假 pass 变成静默卡死。硬门的开关取决于 §4 问题 1 的裁决。

---

## 4. 给用户的问题（设计张力，附倾向+理由+反方，不自作主张）

### 问题 1 —【A 与 D 的先后：D 是 A 的使能前提还是分期锦上添花？】

**背景（数据）**：§18.15-A 的 emit 门要求把采样断言换成「集合相等/区间」，但实证框架 found/not_found 原语**表达不出「集合相等」**（补集取反不可写）、**「区间」只能落 bug 温床数值正则**。单元 D（我方验证侧结构化断言通道：解析响应→抽 hit 整数/成员集→真算子比，π 忠实实现）看起来不是「A 之后分期」，而是**A 门有替代形态可落的前提**。

> **是否把优先序从「A>B>C>D 分期」改为「D-phase1（先覆盖 RR/dig/show statistics 命令族）与 A 门同批落」？**

- **我的倾向**：是，D-phase1 与 A 同批。
- **理由**：A 门无 D 会把分布类案从「假 pass」变成「永久欠定卡死」（拒了旧形态、没有新形态）——对交付率负向，等于用门把问题从质量坑挪成产能坑。
- **反方**：D 是我方加解析层（§18.10 残差门扩展）、工程量与风险都大于 A 门；若 A 门先落、对分布类案暂走 ask_user/escalate 而非硬拒，两者可解耦上线，D 从容做 P0 分期。
- **本质**：D 工程量 vs A 单飞会卡死分布类案的交付率——成本换轴权衡，请裁。

### 问题 2 —【写回护栏粒度：整案不写，还是分流只拦案级 precedent 戳？】

**背景（数据）**：593516 实际写回 footprint 的是合法的配置语法事实 + 一条正确的 wrr uncertain 行为观察（与采样无关，是该沉淀的知识）。A 措辞「h-变量断言的 pass 不够格写 footprint/precedent」一刀切会误伤这些。

> **写回护栏该「整案不写 footprint/precedent」，还是「config/behavior 事实照写、只把案级 precedent `device_verified` 戳降级为 uncertain 判例」？**

- **我的倾向**：分流——config/behavior 照写，案级 precedent 降级 uncertain（引 (45) 行527）。
- **理由**：一刀切误伤知识增长；被采样污染的只是「案级绿的可信度」，不是语法/行为事实。
- **反方**：分流逻辑更复杂（需判哪些写回目标承载断言极性）；一刀切「含 h-变量断言的案整案不写回」实现简单、更保守（宁可少长知识不可投毒）。
- **本质**：保守简单 vs 精准不误伤——请裁。

---

## 5. 理论对账

| 结论 | 理论锚 | 一致/需更新 |
|---|---|---|
| 断言须绑 h-不变式、非 h-样本；采样敏感断言不构成 oracle | **S §0.5 行168-177**（h-不变式断言形态要求，593516 实弹补） | **一致**，A 直接实现它 |
| 「加采样刷过」违反欠定/缺陷分界 | **S §0.5 行156-157**（单次观测依赖 h=欠定；h 边缘化后统计量仍偏离=缺陷候选） | **理论有、实现漏**：该判据实现归属是 **attributor 机械后校验**，A 未映射进归因层（§18.14「实现丢理论合取」同病）。**建议 S §0.5 补一句**：分界判据的实现落点在 attributor，emit 门只管断言形态 |
| 采样噪声写成第二权威源、provisional 仍可检索 | **K §2.9.4 (45) 行518/813-814**（第二权威源健全性、防自指） | **活违反被证实**。(45) 行527「未经审计的 verified 降级 uncertain」正是 Gap 3 护栏出处——**建议写回护栏显式引 (45) 的「降级 uncertain」而非「不写」** |
| 集合相等/区间需我方解析层 | **S §5 π 忠实实现 / K §5.5 oracle 残差** | **一致**，单元 D 是 π 忠实实现；与 A 是「使能/被使能」关系（Gap 1） |

**理论无需推翻**，两处**建议补注实现落点**（S §0.5 分界判据归 attributor；(45) 降级 uncertain 作写回护栏出口）——指出，不改。

---

## 6. 回归锚建议（供实现阶段固化）

| 坑 | 回归锚（文件 + 断言形态） |
|---|---|
| emit 门拒 h-样本断言（Gap 1 落地后） | `tests/ist_core/tools/test_xlsx_lint_gates.py`：构造「config 含 `sdns host method X wrr` + check_point `found Hit:\s+3`」的卷 → emit **拒**（或路由 ask_user）；反向：`found Hit:\s+[1-9]\d*`（非零任意）**同拒**（防 §2 第三形态漏网）；金标准防误杀：ga/topology 算法下的固定落点断言**放行**（GA-CUT 回归同款） |
| attributor 机械后校验（Gap 2） | `tests/ist_core/tools/test_fail_attribution*.py`：喂「config 配比 40/46 + device_context `Hit: 0` + 10 次 dig」→ 断言归因**不得** `rerun_isolated`、须 `defect_candidate`；反向：配比 1/46 成员 Hit:0 小样本→**允许** rerun_isolated（低配比真欠定，不误伤） |
| 写回护栏分流（Gap 3） | `tests/ist_core/compile_engine/`：含 h-变量断言的 pass 案 → footprint config/behavior 写回**发生**、precedent 案级戳**降级 uncertain 或跳过**；纯 h-不变式 pass 案 → 双写回照常 |
| 593516 具体形态（防回归本案） | 断言产出卷不含 `Hit:\s+[4-9]\d*`（错区间正则，漏 10-39）与「分布类算法下的精确 `Hit:\s+N`」；`grade_extract_equiv_sweep` 逐卷 diff |

**清污建议（记录，非本阶段执行）**：`knowledge/framework/mirror/verified_203031753781593516.xlsx` 是 provisional-未终验的采样敏感断言卷，当前 live 可检索——建议连同 §594516 同族（593573 common_cause 同签名）一并进 `runtime/backups/poisoned_precedents_*` 隔离复检（沿用 07-14 已有清污机制）。

---

STATUS: done
