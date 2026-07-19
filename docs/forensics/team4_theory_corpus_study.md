# 理论语料实证研究（#43）——四批 105 卷交付语料 → K/S 公式深化候选

> 2026-07-19，Theory 主研。用户令：「做了这么多轮，理论专家需基于生成的用例和脑图，
> 提取信息和对应的 excel 函数，看看是否有可以深入理解、公式研究更新的」。
> 语料源：`docs/forensics/team4_theory_corpus_extract.jsonl`（Py-Eng 机械抽取，105 行一案一行，read-only）。
> 纪律：**数据结论逐条带语料数字/行引，零臆造**；候选=提案（公式锚+改法+证据），过 leader 审+Design 一致性再 land。
> 状态：**六轴收卷（2026-07-19，leader 裁接受轴③三粒度不可判定理）**——①②④⑤⑥ 实证入档 + ③ 满射三粒度一致机械不可判 + INV-7 闭环印证另轴；候选 **C1-C9**。

## §0 语料与方法

- **规模**：105 delivered 卷。批分布 CNAME_dongkl 9 / dongkl 29 / yzg 25 / zhaiyq 42。
- **字段**（per-case）：`autoid / batch / intent{title,step_intents,group_path} / f_sequence（F列方法序列）
  / assertion_ops[{row,op,host_E,G,H,I}] / h_registers / captured_relation{has_capture,n_capture_rows,relation_compare_used}
  / expected_hits_form / tau_hexatuple{s0,σ,e,π,R,τ,fields_present} / provenance`。
- **断言算子闭集**（Py-Eng 从 mirror `lib/check_point.py` 解析）：`{found, not_found, abs_found, found_times}`。
- **方法**：`jq` 只读统计（不 import 项目，云盘合规）；所有交叉均双向验证或列例外。
- **诚实边界**：语料 `f_sequence` 只到**方法名**（cmds_config/cmd_config/routera…），**无 cmd 文本内容**——
  凡需 cmd 内容判定的结论（如 τ 责任集精确划分、创建型 L2/L3 写识别）**当前语料不足以支撑，逐处标注**。
- **节次导览（轴序≠节序，增量成文所致）**：§1 轴① / §2 轴② / §3 轴④ / §3′ footprint 单列 / §4 轴⑤ / §4bis 轴③ / §5′ 轴⑥ / §5 候选清单 C1-C9。

---

## §1 轴①：断言形态学分布 vs FORM_BY_KIND（**核心发现：form 全机制可判**）

### 1.1 分布实证

| expected_hits_form | 案数 | op 全语料频度 | 每案 op 去重组合分布 |
|---|---|---|---|
| presence(found) | 58 | found 191 | found 45 / found+not_found 20（其 13→presence,7→capture）|
| capture_compare_relation | 36 | not_found 89 | abs_found+found+not_found 19 / … |
| literal_match(abs_found) | 9 | abs_found 79 | abs_found+found 7 / abs_found 3 / … |
| absence(not_found) | 2 | — | not_found 6（其 2→absence,4→capture）|

### 1.2 核心发现：**expected_hits_form 完全 = f(op 机制, H 寄存器)，105 案零例外**

反推判定规则并对照实际 form，**零例外**（jq select 例外集空）：
```
if  H寄存器 relation_compare_used      → capture_compare_relation   (36)
elif 有 abs_found                       → literal_match(abs_found)   (9)
elif 纯 not_found(无 found)            → absence(not_found)         (2)
else(有 found、无 abs_found)           → presence(found)            (58)
```
- **capture_compare_relation(36) ≡ H 寄存器 relation_compare_used=true(36)**，双向同集、零例外。
- op **单独不能**定 form（同 op 组合分裂：`found+not_found`→presence 13 且 capture 7；纯 `not_found`→capture 4 且 absence 2），
  **但 (op, H) 两个机制变量联合可唯一定 form**——H 寄存器是分野的关键第二变量。
- 结论：**四形态全部机制闭合（L_struct 全可判），不是只有 capture 闭合**。

### 1.3 对 FORM_BY_KIND 的关系 + 对 #44 自由度分层的精确切分

- `FORM_BY_KIND`（questions.py:157）刻画的是 **claim_kind → 形态建议**（distribution/weight_ratio→dist；
  position/rotation→member；captured_relation），是**语义决策轴**。
- 本轴证明的 `form=f(op,H)` 是**机制判定轴**。二者是**不同的一跳**：
  ```
  claim 语义 ──[高自由度 / L_model：选 op & 要不要起 H 捕获，FORM_BY_KIND 域]──▶ (op, H)
             ──[低自由度 / L_struct：机械判 form，105 案零例外]──▶ form
  ```
- **#44 直接结论**：断言形态决策面的**自由度边界钉在「claim→形态选择」那一跳**（L_model，信任模型），
  **form 内部判定是纯机械的（可强制单路）**。这是语料证明的精确位置，非拍脑袋。

### 1.4 纯 not_found 的语义分裂（佐证 1.2）

纯 `not_found` 6 案：4 案 →capture_compare（205271757988561072/561141/600318 + 203031753342777976，
「捕获比较的否定面」，有 H），2 案 →absence（205271757988561213/588990，真「不出现」断言，无 H）。
**同 op=not_found，H 的有无把语义劈成两类**——H 是那个决定性机制变量的又一实证。

---

## §2 轴②：τ 六元组完整度（**符合理论预期，非危机**）

### 2.1 分布

- `fields_present`：**5 字段 × 96 案 / 6 字段 × 9 案**（第六元 τ）。
- `tau_teardown_proxy`：true 9 / false 96（与 6 字段案一一对应）。
- **9 个有 τ_proxy 的案全部集中 yzg(6) + zhaiyq(3)，CNAME_dongkl/dongkl 零**。
- `R_n_config_writes` 分布：1×1, 2×7, 3×22, 4×26, 5×22, 6×9, 7×15, 8×3——**全案有配置写（最小 R=1）**。

### 2.2 诚实解读（纪律：弱 proxy 不喊危机）

- τ_proxy 命中集中 **yzg**——yzg 正是**创建型 L2/L3 写批**（run12 τ 缺元教训来源：vlan/bond/ip address 迁移），
  创建型写才需案级 τ、才有恢复步 → **命中集中创建型批 = (39)τ + G1 配对恢复门的设计正确性印证**。
- 96 案 τ_proxy=false 但全有配置写：**绝大多数是功能层写**（sdns/slb 对象增删，框架 per-case `clear` 覆盖，
  不需案级 τ）——符合 S 文档 τ 分工（框架清理=τ 的功能层子集，案级 τ 只管**复位差集**(32) 的 L2/L3 分量）。
- **∴ 96:9 印证既有设计，非翻案、非危机**。
- **诚实字段 gap**：`tau_teardown_proxy` 是弱启发式（restore/no- 命令），且语料无 cmd 内容——
  **无法从当前语料判「创建型 L2/L3 写却漏配 τ」的漏网案**。全域 τ 审计需语料补每案
  `tau_coverage._derived_tau` 输出（创建型写清单 + covered/uncovered 分量）。**当前不足以支撑全域断言**。

---

## §3 轴④：F 方法 × 断言算子共现（PASS 卷判例模式）

### 3.1 共现主路

- `f_sequence` 方法频度：cmds_config 274 / routera 235 / cmd_config 204 / found 191 / sleep 90 / not_found 89 / abs_found 79 / routerb 9。
- **主路模式**：`cmds_config/cmd_config（配置）→ routera（观测，dig）→ found（断言）` = presence 主路，占语料主体。
- `routerb`（第二客户端）仅 5 案，且**不必然跨客户端 capture**：2 案 capture（rel=true）+ 3 案纯第二观测点（presence/literal，rel=false）。

### 3.2 provenance：判例层消费极低

- provenance kinds：precedent 62 / intent 38 / unknown 33 / manual 33 / emit_auto 30 / captured_relation 12 / **footprint 2 / distribution_derived 2**。
- **footprint 仅 2/105、distribution_derived 仅 2/105**——**判例层（footprint）在断言 provenance 中消费极低**，
  编写主要靠 precedent（先例卷）驱动。印证记忆 [worker-prompt-injection-ineffective]（fork 零共享→footprint 重复探/消费低）。
- 观察（非结论）：稳定 PASS 主路模式（cmds_config→routera→found）可沉判例层默认模式（接 #40/#41 加速点，偏设计面，交 Design）。

---

## §3′ footprint 判例层消费度量（单列，leader 裁；**Design 精化·已接受**）

provenance kinds 中 **footprint 仅 2/105、distribution_derived 仅 2/105**——判例层在断言 provenance 中消费极低（precedent 62 先例卷主导）。
**Design 精化(已接受)**：2/105 **只证「消费低」、不证「缺口」**——判例层消费低可能是 precedent 主路已覆盖的**正常沉默**。
真「知识治理缺口」须 **available-but-unused 判别器**：103 非 footprint 案里，**供给侧 footprint 有相关知识、而 worker 未消费**的案数（对照=precedent 正常覆盖）。
- **机械化纪律(守 C1)**：相关性匹配用 **feature_id 前缀 / 命令签名 join**，**不做语义「相关」判断**（否则误伤 precedent 主路，A2 先例）。join 规则 Theory×Design 定。
- **执行**：排 Py-Eng 队列清后采；timing 紧则本节标「**判别器待采**」先发不阻塞。
- **一数两用**：该数同时是 #44 C× 需强格的「判例层厚度」度量（Design 已对齐，不重采）。

与记忆 [worker-prompt-injection-ineffective]（fork 零共享）同族——但**「缺口」结论待判别器数**，当前仅立「**消费低**」观察，不宣称缺口。

---

## §4 轴⑤：可验性边界形式化（**欠定精确二分：采样边界 vs 表达力边界**）

语料：`team4_theory_corpus_unfinished.jsonl` 11 欠定案（带 needs_decision）。

### 4.1 min_requests 值域二分（核心）

11 个 needs_decision（verifiable=false）按 min_requests 精确二分：
- **采样边界（min_requests 有限：2×4 / 4×1 / 6×1 = 6 例）**：claim 可证伪，仅当前请求数不足 → suggested_fix=**改过程**（加请求到 min_requests）。
- **表达力边界（min_requests=null = 5 例）**：claim 本质不可证伪 → suggested_fix=**改预期**（改断言）。

**min_requests 本身即判据**：有限=采样问题（工程可补）、null=表达力边界外（claim 须改）。这形式化了「最小可验请求数」——
它不是一个阈值，是一个 **null ⇔ 不可证伪** 的二值判据 + 有限侧的采样下界。（suggested_fix 分布 改过程 6 / 改预期 5，与二分吻合。）

### 4.2 不可证伪的结构类型（claim_kinds）

claim_kinds 分布：verification_path_absent 5 / relation_diff 4 / absolute_position 4 / weight_ratio 1 / new_member_last 1 / cross_client_landing 1。
- **absolute_position（4，含组合）**：rr 轮转起点运行时随机，「第 N 次必中第 N 个」偶对偶错 → 算法随机性致不可证伪。
- **verification_path_absent（5）**：验证路径本体缺失——HA FIP 单机无法模拟浮动 IP 接管、CNAME 池会话保持无 IP 池可替代
  （IP 池返回 A/AAAA 非 CNAME）→ **对应 S §投影核外（不可观测分量）+ 目标对象本体缺失**。
- new_member_last（min_requests=4 可补）、weight_ratio、relation_diff：多为采样/观测形态问题（可补）。

### 4.3 理论含义

可验性欠定 = **两个正交边界**：①**采样边界**（∃ 足够请求数则可验，工程可补，改过程）②**表达力边界**（claim 语义/目标本体不可证伪，须改 claim，改预期）。
K `compile_check_verifiability`(§654) 已在算 min_requests，但**理论层未明确 null=表达力边界(§734) vs 有限=采样边界的二分**——候选精化点（C6）。

## §4bis 轴③：脑图→用例覆盖满射（**三粒度一致不可判定理 + INV-7 闭环印证另轴**）

Py-Eng 重抽发现**脑图节点原生 autoid 回戳字段**（JSON 节点带 `"auto":"YES"`+`"autoid"`，编译回戳源脑图）——直接 autoid↔节点锚，替代子串伪象。
**Theory jq 亲核对账**：**126 autoid = 105 delivered + 21 unfinished**（delivered 全 ⊆ 脑图＝差集空；脑图 ∖ delivered = 21 = unfinished 目录数），回戳**真实**。

**满射残差三粒度，全指向机械不可判**（`team4_theory_corpus_td.jsonl` 已重写为叶级 + `covered_by` 祖先 autoid 链）：
1. **候选粒度（autoid 回戳锚）：126/126 残差 0 = 同义反复、假可判**。autoid **是**编译回戳，「有 autoid 的场景必已编」是**定义自洽、非覆盖证明**（回戳者必已编）。**残差 0 不可读作满射成立**——初解读「候选级机械可判」正是掉进此陷阱（对账已亲核，意义须按定义域判）。
2. **场景粒度（resource 标注锚）：266 resource 场景 vs 126 已编 = 140 未编**。但 140 **混「该编漏编」vs「不该编」**（webui/压力/部分 cli 如 ha 同步、clear、write mem 大概率非本轮自动化范围）——**该编/不该编需语义判定，机械不可判**。
3. **叶粒度：458 叶 / 覆盖 225 / 残差 233**。233 混子细节（scenario 展开的操作/预期叶，非独立测试点）——三重障碍（分母污染 / 匹配键不齐 step_desc↔leaf_text 精确交集仅 37 / delivered-unfinished-漏编 层次混叠）。

- **结论（leader 裁·三粒度一致不可判定理）**：脑图→用例覆盖满射在三个机械锚粒度上**一致不可判**——候选级=同义反复假可判、场景级=该编判定需语义、叶级=子细节混叠。**比单粒度「不可判」更强**：无论选哪个机械锚，满射残差都测不准。**∴ INV-breadth 观察级(:172)、漏编集只报告不 gate，是三粒度实证的定理级依据**（C8）。任何满射残差数（28/458、140/266、233/458）**禁作覆盖率入结论**。

- **另轴正向发现：INV-7 编译闭环完整性印证**。126 autoid 回戳**零遗漏入台账**（对账差集**双向空**：delivered⊆脑图、脑图=delivered∪unfinished）——编译回戳无一丢失、全入 delivered(105)/unfinished(21)。这是 **INV-7 事件溯源闭环**的语料印证（C9）。**硬正数，但归「闭环自洽」轴、明标勿误读为「脑图覆盖率」**（覆盖率＝满射问题＝上述三粒度不可判）。

## §5′ 轴⑥：门族触发频度（门违例分布 vs 门密度∝错误代价）

语料：`team4_theory_corpus_gates.json` 四批 all_events/gate_violation_events/attribution_dispositions。分母 = verdict（上机判定）**563 次**。
**范围限定(Py-Eng 澄清)**：gates.json 是**运行时门**（facts 事件流）——**26 个 emit-时 lint 门不在此**（过门卷不留 lint 事件）。
故本轴频度=**运行时门违例**，不含编译期 lint 拦截（那 26 门在 emit 期已挡、不进上机）——**本轴结论只覆盖运行时门族，非全门族**。

### 5′.1 门违例分布（gate_violation_events 跨批汇总）

- **拦截型门违例**：s0_dispute 8 / strong_claim_unaddressed 7 / rollback 6 / cap_reached 2 / report_mismatch 1 / evidence_suspect 1 / delivery_overwritten 1 = **26 / 563 ≈ 4.6%**。
- **流程事件**（非拦截）：attribution 69（每 fail 归因）/ needs_decision 30（欠定问询）/ escalated 12（止损上报）/ common_cause 8。
- **归因处置**：reflow 47 / expectation_suspect 8 / defect_candidate 5 / rerun_isolated 5 / frozen 3 / user_stop 1（总 69）。

### 5′.2 发现

1. **门违例稀疏（拦截型 4.6%）**：门是窄桥护栏、非常态路况——绝大多数案顺畅过，门只在少数问题案触发。
2. **高代价门确在拦截**：s0_dispute 8（床污染，run12/13 教训）、rollback 6（终验矛盾，D31 类）、report_mismatch 1（报告对账，D31/G5）、evidence_suspect 1——
   **均为教训后布的门，现在真在拦**。**定性印证门密度∝错误代价**（高代价错误上都有门且触发，集中复杂批 zhaiyq）。
3. **诚实边界**：「∝」是**定性**——无每门错误代价的独立量化，不宣称定量正比。
4. **归因处置**：**reflow 47/69=68%**（fail 多可重编修复）、**defect_candidate 仅 5/69=7%**（真产品缺陷稀少）——
   印证 Ω 分类「只有产品缺陷是案侧无修法」，绝大多数 fail 案侧可修。

---

## §5 K/S 公式更新候选清单（六轴收卷 C1-C9，**提案·待审**）

> 每条：公式锚[文档:节:行] · 改法 · 语料证据 · 类型（注记/精化/新构件）· 归属文档。
> 纪律 C13/C14：无新工程消费者不立公式；能作既有构件精化就不新增。

| # | 公式锚 | 改法（提案） | 语料证据 | 类型 | 归属 |
|---|---|---|---|---|---|
| C1 | K §18.14 恒真族 / L_struct·L_model 分层（:678-698） | 增注记：**expected_hits_form = f(op机制, H寄存器) 全 L_struct 机制闭合（105 案零例外）；断言形态自由度边界在「claim→形态选择」一跳（FORM_BY_KIND 域,L_model），非 form 判定** | §1.2 零例外判定规则；capture 36≡H true 36 | 注记（印证+精化既有分层，零新本体） | K |
| C2 | K §18.14 / 代码 FORM_BY_KIND(questions.py:157) | 明确 FORM_BY_KIND 是**语义决策轴（claim_kind→form）**，与机制判定轴 f(op,H) 正交——文档现缺「两轴正交」表述 | §1.3 两跳分离 | 精化 | K（+ #44 消费） |
| C3 | S §0.4 (39) τ / G1 配对恢复门 | **印证条**（非改式）：τ_proxy 命中集中创建型批（yzg6+zhaiyq3、功能层批零）= (39)+G1 设计正确性的语料印证 | §2 96:9 分布 | 注记（印证） | S |
| C4 | S §0.4 τ 判据 | 记录**字段 gap**：全域 τ 审计需 `_derived_tau` 创建型写清单，弱 proxy 不足——为未来「τ 语料审计工具」留消费者锚 | §2.2 诚实边界 | 注记（缺口登记） | S |
| C5 | 自愈合判例层 / footprint | **观察(判别器待采)**：footprint provenance 2/105 只证**消费低**、不证缺口——真缺口=available-but-unused（供给侧有知识而 worker 未消费，对照 precedent 正常沉默）；判别器须机械化 join（feature_id/命令签名，非语义），无此数不驱动 fix 门（误伤 precedent 主路，A2 先例）；一数两用=#44 C× 判例层厚度 | §3′ | 观察（偏设计，交 Design；判别器排 Py-Eng 队后） | 设计面 |
| C6 | K `compile_check_verifiability`(§654) / 表达力边界(§734) | 明确可验性欠定二分：**min_requests=null=表达力边界（不可证伪→改预期） vs 有限=采样边界（可补→改过程）**；verification_path_absent 对应 S 投影核外+目标本体缺失 | §4.1（6 采样 / 5 表达力）、§4.2 | 精化 | K(+S) |
| C7 | K 判定函数⟨f,c,m⟩(§667) | 门违例频度（拦截型 26/563≈4.6% 稀疏 + 高代价门 s0_dispute/rollback/report_mismatch 在拦）**定性**印证门密度∝错误代价；reflow 68% 印证 Ω「只产品缺陷案侧无修法」 | §5′ | 注记（定性印证） | K |
| C8 | K INV-breadth 观察级(:172) / 验证盲区定理 §2 | **三粒度一致不可判定理**：脑图→用例满射残差在候选粒度（同义反复假可判）/场景粒度（266 vs 126 该编判定需语义）/叶粒度（三重障碍）**三粒度一致机械不可判**——比单粒度更强，INV-breadth 观察级「只报告不 gate」是三粒度实证的定理级依据 | §4bis 三粒度 | 注记（印证升格） | K |
| C9 | K INV-7 事件溯源闭环 | **INV-7 编译闭环完整性印证**：脑图 126 autoid 回戳零遗漏入台账（105 delivered+21 unfinished，对账差集**双向空**）——回戳无一丢失全入 delivered/unfinished。**硬正数，归「闭环自洽」轴、明标勿误读为覆盖率** | §4bis 另轴；亲核 126=105+21 | 注记（印证） | K |

**说明**：**C1（form=f(op,H)）与 C6（min_requests 二分）是两个语料定位的机械化候选面，直接喂 #44**。C3/C4/C7/C8/C9 是「框架能力优先」——τ 由 (39)+G1、门由判定函数、满射由 INV-breadth、回戳闭环由 INV-7 既有构件管辖，本研究是**印证/升格/缺口登记，不翻案**（C8 三粒度一致不可判把观察级坐成定理级依据；C9 是编译闭环完整性硬正数，勿混作覆盖率）。C6 是 K 表达力边界(§734) 语料精确化。C5 偏设计交 Design（判别器待采）。**六轴收卷，候选 C1-C9 全在表。**
