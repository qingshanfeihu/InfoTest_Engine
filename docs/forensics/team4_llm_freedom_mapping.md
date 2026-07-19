# LLM 自由度分层映射（任务 #44）

> 2026-07-19 · LLM-Eng · **read-only 调研提案** · #43 语料已交付(六轴齐)
> **本文状态**：**定稿**——§1 双轴框架 + §2 决策面清单 + §3 表(理论列 + 数据底列)。**#43 六轴(①②③④⑤⑥)已全喂入**(§5 台账):轴覆盖的决策面数据底(应然实证/错配/语料出处)已填(prov.,待六轴收卷转终定);**六轴未覆盖的 15 面**(worker 6 + attributor 9,attribution 侧当前无轴数据)数据底列标「无轴覆盖·理论初判」,理论列(错误代价/无人值守/ABC/→三类/官方锚)据框架 + 代码结构成立,后批语料候选。Design 已消费入 DESIGN §21(2026-07-19)。
> **消费端**：Design 条款化入 DESIGN/skill 纪律,接「门密度 ∝ 错误代价 × 无人值守时长」框架。格式遵 Design #44 消费端要求(①三类=两轴机械导出 ②现状 vs 应然 diff ③决策面为行稳定 ID ④双证据分列引出处 ⑤对齐 CLAUDE.md 不重造)。
> **红线**：官方引**原则锚**、语料引**出处路径**,均不抄内容(reference-docs-mechanism-not-data,随框架版本漂)。任何 prompt/skill 实改属后批走四关。

---

## 0. 用途

一张逐决策面表:编译链 worker / attributor / 引擎机械节点 的每个「可独立判自由度的判断点」× 列[错误代价, 无人值守?, ABC 层, →三类, 现状自由度, 应然自由度, 错配?, 官方原则锚, #43 语料出处]。Design 拿来**逐行条款化,零重塑**。粒度 = **决策面级**(比整条链细、比每行代码粗——一个可独立判自由度的判断点为一面)。

---

## 1. 理论底：双轴框架

**三类(强制单路 / 引导中间态 / 自由发挥)不是独立打的标签,是两个正交轴的机械导出。** 这是本调研对 Design 门密度框架的补全:Design 的「错误代价×无人值守」回答**该不该 gate(需 gate 性)**;本仓 A/B/C 回答**能不能 gate(可 gate 性)**。两轴正交,三类落在交集。

### 1.1 轴一 · 可 gate 性(oracle 可得性)= 本仓 A/B/C 三层

`[[compile-quality-abc-three-layer]]`。判据:**这个校验的对错,是否依赖一个「因 case 而变、可能取错」的领域事实?**

| 层 | 含义 | 可 gate 形态 | 机制锚(本仓,本会话核实存在) |
|----|------|-------------|------------------------------|
| **A 机械可判定** | 上下文无关、误判即真错(不误杀好制品) | **可机械 gate**(强制单路可行) | `structural_gate` crash-gates(emit 出口) |
| **B 条件可证伪** | 判定条件于外部事实(算法确定性等) | **可验证器 gate**(自由写 + 机械验证兜底 + 反馈环) | `compile_check_verifiability`(→反驳→回灌 LLM) |
| **C 无 oracle** | 无可判定 oracle、靠上下文语义 | **不可机械 gate**,只能靠 prompt + 值守 | prompt 给「怎么判 + why」,零写死领域命令 |

### 1.2 轴二 · 需 gate 性(后果)= 错误代价 × 无人值守（Design 门密度框架）

- **错误代价**(错了炸多大):极高(自毁命令清整机床)/ 高(emit 门 miss 崩整卷)/ 中(假 PASS 单卷)/ 低(措辞欠佳、用户体验)。
- **无人值守?**(这判断点在无人环节吗):worker fork / 自动跑批 / attributor fork = **无人值守**(错了没人当场拦);ask_user 位 / leader 在环 / emit 门即时拒 = **有值守**(错了当场被拦或问)。
- 两者之积 = **需 gate 强度**(Design:门密度 ∝ 错误代价 × 无人值守时长)。

### 1.3 三类 = 两轴导出矩阵【核心】

表头 ABC = **gate 形态**（A 写时机械门 / B 事后验证器 / C 无门·靠 prompt+值守）;单元格 = 该组合的处置形态。

|  | **A（写时机械门）** | **B（事后验证器）** | **C（无门·靠 prompt+值守）** |
|--|--|--|--|
| **需强**（高代价 × 无人值守） | **强制单路**（写时门锁死一路） | **自由发挥写 + 验证器兜底**（事后 gate + 反馈环强制） | ⚠**危险格**：无法机械锁,唯二杠杆=prompt 门密度拉满(方向+why+**安全边界禁令**窄桥护栏)+ ask_user 兜底(把无人值守转有值守) |
| **需中** | 强制单路 / 引导中间态 | 自由发挥写 + 验证器兜底 | 自由发挥 + checklist（few-shot 形态示例） |
| **需弱**（低代价 × 有值守） | 引导中间态 | 自由发挥（验证器可选） | 自由发挥（高自由度给方向、信任模型） |

**危险格洞见(C × 需强)**:无 oracle 不可机械 gate、错代价高又无人值守——门密度框架撞上 oracle 缺失。实证反例:**自毁命令**(`clear config all` 类,C 层经验知识 × 极高代价 × worker 无人值守)——引擎曾给 worker 一条它不知边界的命令建议,worker 朝「清得更干净」升级,93/105 跑死两床。**修法不是「加机械门」(C 层加不了 A 门),而是**:经验知识走**判例层**(footprint 观察,worker 检索后自主查手册)+ 安全边界禁令走**窄桥护栏**(destructive_commands 整机清配一律拒)——即 CLAUDE.md「引擎不得向 LLM 注入具体命令建议」裁决(2026-07-13)。这条裁决在本框架里的位置 = C×需强 危险格的正确处置。

### 1.3.1 核心推敲：验证器兜底(B)是正交「事后-gate 维」,非自由度谱第四点（leader 2026-07-19 点）

B 层「可证伪工具 + 修复环」**既不是自由度谱(强制单路/中间态/自由发挥)上的第四点、也不是引导中间态的子型**——它是与「写时自由度」**正交的另一维:事后 gate**。区别在 gate **何时**作用于「写」:

- **引导中间态** = **写时** prompt 引导(checklist/few-shot **塑造写的过程**,LLM 边写边被收窄);
- **验证器兜底(B)** = **事后** 机械验证器(LLM **自由写完** → 验证器查 → 反驳回灌 → 重写;**写的过程本身是自由发挥**,验证器不约束写、只验成品 + 反馈)。

两者机制不同、**可正交组合**。故一个决策面完整刻画 = **写时自由度 × 验证器兜底?**:

| 组合 | 含义 | 例(决策面) |
|------|------|-----------|
| 强制单路（A 写时门即约束） | 写时机械门锁死一路,无需事后 | `engine/emit结构门`、`attributor/quote引用` |
| **自由发挥 + 验证器兜底(B)** | **最安全的自由写**:自由写 + 事后验证器兜底反馈 | `worker/claim可验性判定`、`attributor/复现方向判断` |
| **自由发挥 + 无兜底(C)** | **最险的自由写**:无 oracle,只 prompt+值守 | `worker/命令选择`、`worker/等价方案推导`(危险格) |
| 引导中间态（写时 prompt 引导） | checklist/few-shot 塑造写的过程 | `worker/持久化清理`、`attributor/product_defect检查` |

**对门密度的意义(Design 条款化直接可用)**:对**高需-gate 的自由发挥面**,门密度的「gate」优先级 = **能上事后验证器就上(B 可证伪时,如断言形态/可验性)→ 上不了(C 无 oracle,如命令选择/等价推导)才落 prompt 护栏 + ask 兜底**。即:**验证器兜底 = 自由写面的首选 gate 形态;C×需强危险格 = 「验证器都上不了」的退化面**(门密度从机械 gate 退成 prompt 护栏 + 值守转换)。**核心可操作结论:自由发挥面别只标「自由」、要标「验证器兜底? 有/无」——有=B 层安全,无=C 层需 prompt 护栏+值守补偿。** §3 表 `→三类` 列已按此标注 B 层面。

### 1.3.2 C×需强 = 显式「防御纵深」类（Design 2026-07-19 拍板，非守成非放弃）

C×需强危险格(该 gate、但无 oracle 上不了机械门)**不并入「自由发挥」、不写「守成锁现状」(太麻痹:此格风险最高、无机械安全网)、不写「靠值守缴械」(不是不 gate、是换一种 gate)——单列一类「防御纵深强制」**。其条款 = **多层栈强制 + 观察级监测**:

1. **判例层检索**(footprint 已验证观察,worker 检索后自主查手册决策——经验知识的载体);
2. **安全边界禁令窄桥**(destructive_commands 整机清配一律拒——非知识、是护栏);
3. **ask 兜底**(把无人值守转有值守,山穷水尽批末问询);
4. **首败即升深度**(重编轮 max 思考 + 喂全历史);
5. **观察级监测**(无 oracle→漂移看不见→fail/escalated 轮行为观察以 validity=uncertain 入库,判例层积累**补** oracle——同自愈四层判例层)。

**要义**:无单一机械门,但有纵深——这是本项目 worker 面**已有的模式**(footprint/安全禁令/ask/自愈),映射把它**显式化成一类条款**、非新发明。`worker/命令选择`、`worker/等价方案推导` 正落此格(§3 表 `→三类` 标「防御纵深」)。**门密度在此 = 纵深层数**(需越强→栈越厚),非机械门条数。

### 1.3.3 「必留人工」类——不该机械化的一极（轴③ 2026-07-19,与机械化候选对称）

自由度分层不只有"该收紧/该机械化"一个方向,还有**对称的一极:强行机械化会错、必须保留人工的面**。判据:**机械判定本身测不准**(不是"暂无 oracle"、是 oracle 原理上不可靠)。

- 实证:`worker/用例覆盖判定`(脑图→用例满射残差)——三粒度(候选级同义反复 / 场景级该编判定语义 / 叶级子细节)**一致机械不可判**,强行机械满射会误判(漏编 vs 合理不编无法机械区分)。故该面**观察级、不作强制门**(INV-breadth 只报告漏编集、不 gate),**既不能强制单路、也不能机械默认**——保留人工复核。
- **理论根(Design corpus 终审 C8 三粒度定理咬合,2026-07-19 背书 P)**:非拍脑袋加的一类——与 C8 逐条对上(候选级残差 0=同义反复 / 场景级 265 vs 113 需语义 / 叶级混叠),`INV-breadth:172` 观察级不 gate = C8「升格观察级为定理级依据」的落地。**与机械化候选(form/min_requests)对称、有定理支撑**。
- **与防御纵深(§1.3.2)的区别**:防御纵深(C×需强)是"无机械 oracle 但堆纵深(判例/禁令/ask/监测)兜";必留人工是"机械判定原理上测不准,别堆 gate、观察级报告 + 人工判"。防御纵深还在**尽量收**,必留人工是**明确不收**。
- **对框架的意义(Theory 强调)**:映射表须有这一类兜底,否则"该机械化"(form/min_requests)的叙事会诱导 over-mechanize——**给测不准的面加机械默认 = 把系统性误判固化**。这与机械化候选面对称,是自由度分层的另一极。**三极收束**:①机械默认可(form 守成/min_requests 修复)②engine 强制(INV-7 闭环/emit 门)③必留人工(覆盖满射,反例)。

### 1.4 与 CLAUDE.md 既有对齐（不另起炉灶）

- **CLAUDE.md「degrees-of-freedom 分层」**(高自由度陈述+方向+why 信任模型 / 低自由度精确护栏 / 避免 ALL-CAPS 默认)= 官方 B3 + 三类的 **prompt 落地形态**(强制单路→精确护栏措辞;自由发挥→陈述+方向)。
- **CLAUDE.md「三层栈数据形态判定表」**(人定义→md / 确定性流程→py 图 / 机器间传→JSON / 进 LLM 上下文→XML / 场景而异语义判断→skill fork / 单一正确做法→tool)= 同一分层在**数据形态维的投影**。**自由度映射 ≈ 逐决策面套这张判定表**(「单一正确做法→tool」= 强制单路;「语义判断→skill fork」= 自由发挥)。
- **官方 degrees-of-freedom**(Anthropic best practices,#30 全类目对照 team4_skill_official_zh_recheck.md):**B3 自由度匹配高/中/低(主锚)**、M1 模板严格/灵活分档、W1 复杂任务 checklist、W2 验证器反馈循环、A2 默认+escape hatch、M3 条件工作流决策点。

---

## 2. 决策面清单（稳定 ID）

编译链节点/孔/step 锚为行锚(V8 拓扑:prep→bed_gate→author→merge→run→reconcile→attribute→diagnose + 3 ask 位;孔=compile-worker@author / compile-attributor@attribute)。

**worker 孔**(compile-worker@author,无人值守 fork,14 面):`worker/测试点陈述` · `worker/命令选择` · `worker/E-F通道选择` · `worker/断言op&H选择` · `worker/期望值来源` · `worker/步骤结构` · `worker/claim可验性判定` · `worker/欠定报告` · `worker/欠定修法方向` · `worker/等价方案推导` · `worker/持久化清理` · `worker/emit载荷结构` · `worker/交付语言` · `worker/用例覆盖判定`

> 注(轴①,Theory prov. + Design 咬合定稿):原「断言形态」面按语料 `form=f(op,H)` 105 零例外分**两层**——**worker 决策面 `worker/断言op&H选择`**(claim→选 op & 要不要起 H,**C 层语义**,LLM 有自由度,FORM_BY_KIND:157 域)+ **engine 机械门面 `engine/form判定`**(op,H→form,**A 层强制单路守成**,LLM 零 latitude、105 零例外)。**自由度边界钉在「claim→选 op&H」那跳;form 判定是 engine 机械门面、非 worker 决策面**(决策面=LLM 有自由度的判断点;机械导出落 engine 门侧)。

**attributor 孔**(compile-attributor@attribute,无人值守 fork,9 面):`attributor/归因判层` · `attributor/复现方向判断` · `attributor/quote引用` · `attributor/disposition选择` · `attributor/E自检` · `attributor/product_defect检查` · `attributor/ask触发` · `attributor/user_note措辞` · `attributor/h_position候选`

**引擎机械节点**(mech `.func`,引擎直调,天然强制单路,7 面):`engine/form判定`(op,H→form,A 层守成,轴①105 零例外) · `engine/INV7闭环记账`(126 autoid 回戳,轴③) · `engine/emit结构门` · `engine/lint凭证` · `engine/reconcile全射` · `engine/diagnose批级裁决` · `engine/终验幂等闸`

---

## 3. 逐决策面映射表

> **理论列**(错误代价 / 无人值守 / ABC / →三类 / 官方锚 / 现状)按 §1 框架 + 代码结构 + 已知实证填。**数据底列**(应然 / 错配 / 语料出处):**六轴覆盖的决策面已填实证**(prov.,轴①断言形态 / ②τ持久化 / ④命令·footprint / ⑤可验性边界 / ⑥门二分 / ③覆盖满射 已据以确认对应面,§5 台账);**六轴未覆盖的 15 面**(worker 6 + attributor 9,attribution 侧当前无轴)标「无轴覆盖·理论初判」,后批语料候选。

| 决策面(稳定 ID) | 错误代价 | 无人值守? | ABC | →三类 | 现状自由度 | 应然(轴实证 prov. / 无轴=理论初判) | 错配? | 官方原则锚 | 语料出处(轴/后批候选) |
|--|--|--|--|--|--|--|--|--|--|
| `worker/测试点陈述` | 高(claim/证伪观测错=整卷方向错) | 无 | C(语义) | 自由发挥 | 自由(claim+证伪观测,一两行) | 无轴覆盖·理论初判 | 无轴覆盖·理论初判 | B3 高自由度 | 无轴覆盖·理论初判 |
| `worker/命令选择` | 高(错命令崩卷/污床) | 无 | C(靠检索+手册) | **防御纵深**(C×需强) | 自由发挥(retrieval 四序,零写死)+判例+安全禁令+ask | **防御纵深**(轴④证)prov. | 守成 + ⚠观察 C5(footprint 消费 2/105 低,判例层厚度结论待判别器) | B3 高自由度给方向 / CLAUDE.md 零写死命令 | 轴④ footprint 2/105 · provenance precedent 62(prov.) |
| `worker/E-F通道选择` | 高(错门=wrong-door 假环境失败) | 无 | A(E/F 列对象闭集可核) | 强制单路(对象闭集)+自由(判走哪门) | 闭集校验(case_ir VALID_TEST_OBJECTS) | 无轴覆盖·理论初判 | 无轴覆盖·理论初判 | B3 低自由度护栏 | 无轴覆盖·理论初判 |
| `worker/断言op&H选择` | 高(选错→假PASS/崩门) | 无 | **C**(选 op&H=语义,无机械 oracle;claim可验性面另有 B 验证器邻接) | **自由发挥**(FORM_BY_KIND:157 引导) | 自由选 op&H(FORM_BY_KIND 引导);form=f(op,H) 由下游 engine emit 门机械 enforce、非本面 latitude | **高自由度**(轴①证:自由度边界钉在 claim→选 op&H 那跳、form 判定 LLM 零 latitude)prov. | **守成**(边界已正确)prov. | B3 高自由度 / M3 条件决策点 | 轴① form=f(op,H) 105 零例外(theory_corpus_study,prov.) |
| `worker/期望值来源` | 高(observe-then-assert=红线假验证) | 无 | A/C 混(溯源可核 A;语义覆盖 C) | 强制单路(禁 observe-then-assert)+自由(溯源判断) | 溯源强制(红线)+ 判断自由 | 守成(溯源红线;defer 后方向机械已拆 `worker/欠定修法方向`)prov. | 守成 | B3 低自由度护栏(红线) | 轴⑤(defer 方向部分,prov.) |
| `worker/步骤结构` | 中(结构错→门拒) | 无 | A(crash-gate 可判) | 强制单路(结构门)+中间态 | A 层(带H观测步→须不带H观测步等) | 无轴覆盖·理论初判 | 无轴覆盖·理论初判 | M1 模板严格档 | 无轴覆盖·理论初判 |
| `worker/claim可验性判定` | 高(不可验 claim=flaky假PASS) | 无 | **B** | **自由发挥+验证器兜底** | 自由判+compile_check_verifiability→NEEDS_USER 事后验 | **上游高自由度**(要不要 defer、判可验性,验证器半机械辅助)prov. | 守成 | W2 验证器反馈环 | 轴⑤ min_requests 二分 11/11(上游判定,prov.) |
| `worker/欠定报告` | 中(漏报=盲猜 landed) | 无→有(转 ask) | A(结构三元组门) | 强制单路(结构三元组固定序) | 固定序(test_point+sources+obstacle+equiv) | 强制单路(结构三元组已定)prov. | 守成 | M3 条件工作流决策点 | 轴⑤ 11 欠定案(prov.) |
| `worker/欠定修法方向` | 中(方向错→无效重编) | 无→有(转 ask) | **A 打底+C 覆盖**(min_requests→方向机械) | **机械默认+LLM 覆盖**(A2 escape hatch,**覆盖有摩擦**) | LLM 判断(现状自由发挥) | **机械默认**(min_requests: null→改预期 / 有限→改过程,11/11)**+ LLM 覆盖须声明理由**(记 exception,防 escape hatch 成 silent bypass,同 frozen override)prov. | **⚠修复**(现状 LLM 判断→应然机械默认打底) prov. | A2 默认+escape hatch | 轴⑤ min_requests→suggested_fix 11/11(**第二机械化候选**,prov.) |
| `worker/等价方案推导` | **极高**(forbidden-mechanism 误 emit=跑死床) | 无→有(强制转 user) | C(经验判断) | **防御纵深**(C×需强,极高代价:4 criteria+emit 门禁 land+**强制转 user**) | 自由推导+门禁 emit+user 裁 | 无轴覆盖·理论初判 | 无轴覆盖·理论初判 | A2 默认+escape / CLAUDE.md 引擎不注入命令 | 无轴覆盖·理论初判 |
| `worker/持久化清理` | 高(残留→全卷假fail) | 无 | **C 判定+A 逆元**(二段) | 引导中间态(上游 τ 责任判定半机械)+强制单路(下游逆元机械) | checklist(case-unique 名+head/tail) | **二段**:τ 责任判定(创建型 L2/L3 写才需案级 τ,读结构化事实,半机械)+ 逆元派生(no X=X 逆元,inverse_forms A 机械)prov. | 守成(逆元已 inverse_forms 机械) | W1 checklist | 轴② τ 责任 96:9 创建型 · inverse_forms(prov.) |
| `worker/emit载荷结构` | 中(结构错→门拒重来) | 无 | **A** | **强制单路**(blocks 契约+provenance 门) | A 层(结构门无条件) | 无轴覆盖·理论初判 | 无轴覆盖·理论初判 | M1 模板严格档 | 无轴覆盖·理论初判 |
| `worker/交付语言` | 低(desc 人话,用户读) | 无 | C(语义) | 自由发挥(格式引导) | 自由(one line/step 人话) | 无轴覆盖·理论初判 | 无轴覆盖·理论初判 | B3 高自由度 | 无轴覆盖·理论初判 |
| `worker/用例覆盖判定` | 中(漏编=覆盖缺口,观察级) | 无 | **C 机械不可判**(满射测不准) | **必留人工**(观察级,不作门) | 观察级报告(INV-breadth:172 漏编集报告不 gate) | **必留人工**(三粒度一致机械不可判,保留人工复核)prov. | 守成 | A2 不过度自动化 / B3 | 轴③ 三粒度一致机械不可判(prov.) |
| `attributor/归因判层` | 中(判层错→修法方向错) | 无 | C(读原文判) | 自由发挥(layer descent 引导) | 自由判+cheap-first 引导 | 无轴覆盖·理论初判 | 无轴覆盖·理论初判 | M3 条件决策点 | 无轴覆盖·理论初判 |
| `attributor/复现方向判断` | 高(方向已证伪再开=烧轮/frozen) | 无 | **B**(上轮修法上卷/签名复现可核) | **自由发挥+验证器兜底** | 引导(核 _prev_attribution 上卷否+同签名复现否) | 无轴覆盖·理论初判 | 无轴覆盖·理论初判 | W2 验证器反馈环 | 无轴覆盖·理论初判 |
| `attributor/quote引用` | 中(转述→误归因) | 无 | **A**(verbatim 子串门) | **强制单路**(verbatim 机械门) | A 层(gate-checked 子串) | 无轴覆盖·理论初判 | 无轴覆盖·理论初判 | B3 低自由度护栏 | 无轴覆盖·理论初判 |
| `attributor/disposition选择` | 中 | 无 | C | 自由发挥(闭集选) | 自由(闭集 reflow/frozen/...) | 无轴覆盖·理论初判 | 无轴覆盖·理论初判 | A2 默认+escape | 无轴覆盖·理论初判 |
| `attributor/E自检` | 中(误判 E→假环境阻塞) | 无 | B(same-case counter 可核) | 引导中间态(self-check) | 引导(per-case counter 核) | 无轴覆盖·理论初判 | 无轴覆盖·理论初判 | W2 反馈 | 无轴覆盖·理论初判 |
| `attributor/product_defect检查` | 高(误报缺陷/漏真缺陷) | 无 | C(第三源比对) | 引导中间态(5 checks 固定序) | 5 checks 程序性 | 无轴覆盖·理论初判 | 无轴覆盖·理论初判 | W1 checklist / M3 | 无轴覆盖·理论初判 |
| `attributor/ask触发` | 中(该问不问→盲改判) | 无→有 | A(expectation_suspect 门强制) | 强制单路(panel-mandatory 门) | A 层(tool 拒无 panel) | 无轴覆盖·理论初判 | 无轴覆盖·理论初判 | M3 条件决策点 | 无轴覆盖·理论初判 |
| `attributor/user_note措辞` | 低(D28 面板叙述) | 无 | C(语义) | 自由发挥(中文契约+趋势引导) | 自由(中文一句+趋势,契约门验中文占比) | 无轴覆盖·理论初判 | 无轴覆盖·理论初判 | B3 高自由度 | 无轴覆盖·理论初判(D28) |
| `attributor/h_position候选` | 中(误判→无效重跑) | 无 | C(证据判) | 自由发挥(候选,引擎裁决) | 自由候选(propose not sentence) | 无轴覆盖·理论初判 | 无轴覆盖·理论初判 | A2 默认(空=unknown) | 无轴覆盖·理论初判 |
| `engine/form判定` | 高(form 错=假PASS/崩门) | 无 | **A**(f(op,H) 机械闭合,emit 门 enforce) | **强制单路**(engine 门面,非 worker 决策面) | 强制单路(framework 机械展开 op,H→form,105 零例外) | **强制单路**(轴①证:LLM 零 latitude)prov. | **守成** | M1 严格模板 / S5 可验证 | 轴① f(op,H) 105 零例外(prov.) |
| `engine/INV7闭环记账` | 高(回戳遗漏=交付对账断裂) | 无 | **A**(编译回戳机械) | **强制单路**(engine 闭环记账) | 强制单路(126 autoid 回戳零遗漏自动入台账) | **强制单路**(轴③证:engine 机械)prov. | **守成** | S5 可验证 / INV-7 | 轴③ INV-7 126 autoid 零遗漏(prov.) |
| `engine/emit结构门` | 高(漏门→假卷交付) | 无 | **A** | **强制单路** | A 层机械门 | 强制单路(设计即是) | 守成 | M1 严格模板 | N.A.(机械,非语料) |
| `engine/lint凭证` | 高(伪凭证→绕门合并) | 无 | **A**(mtime 签名) | **强制单路** | A 层(source=lint,mtime) | 强制单路 | 守成 | S5 可验证中间输出 | N.A. |
| `engine/reconcile全射` | 高(吞 verdict) | 无 | **A** | **强制单路** | A 层(四值全射入账) | 强制单路 | 守成 | S5 | N.A. |
| `engine/diagnose批级裁决` | 中 | 无 | A(机械子集重编) | 强制单路 | A 层 | 强制单路 | 守成 | — | N.A. |
| `engine/终验幂等闸` | 中(livelock) | 无 | **A** | **强制单路** | A 层(组成指纹幂等) | 强制单路 | 守成 | — | N.A. |

---

## 4. #43 填充记录 + Design 对齐（六轴已喂入、Design 已消费入 §21）

**六轴已全喂入**(§5 台账);轴数据确认对应决策面数据底(应然/错配/语料出处)的用法记录:
- ~~**轴①断言形态分布**~~ **已落地(prov.,2026-07-19)**:Theory 实证 `form=f(op,H)` 105 零例外 → 分两层:**worker 决策面 `worker/断言op&H选择`**(C 层高自由度,FORM_BY_KIND 域)+ **engine 机械门面 `engine/form判定`**(A 层守成,LLM 零 latitude)。边界钉在 claim→选 op&H 跳(§2/§3/§5,Design 咬合定稿)。
- **轴④ F 方法×算子共现矩阵**(PASS 卷判例级模式)→ 确认 `worker/命令选择`、`worker/持久化清理` 应然(共现稳定=可模板化=收敛;发散=自由)。
- **轴⑤可验性边界**(最小可验请求数类)→ 确认 `worker/claim可验性判定`、`worker/期望值来源` 应然(边界可判据化=B 层验证器可强化)。

**给 Design 的对齐问询(概念框架,预备时先拍齐,免产出后口径不合)**:

1. **双轴正交是否合你的门密度框架?** 你的「错误代价×无人值守」是**需 gate 性**(该不该 gate);我加的 **A/B/C 是可 gate 性**(能不能 gate)。三类是两轴交集导出(§1.3 矩阵)。**你的门密度直接 key 需 gate 性轴;可 gate 性轴决定门的形态**(A→机械门 / B→验证器 / C→prompt+值守)。若你只需单轴(需 gate 性)、把可 gate 性并进「门密度形态」注解,我可压成单轴表 + 形态注,听你。
2. **C×需强危险格**(§1.3):无 oracle 不可机械 gate 的高代价无人值守面(如 `worker/命令选择`、`worker/等价方案推导`),门密度无处可加机械门——处置=判例层 + 安全禁令窄桥 + ask_user 兜底。**这类面你想要「守成条款」锁住现有 prompt 护栏 + 判例机制,还是单列「不可 gate、靠值守」类**?
3. **「守成 vs 修复」判据**:引擎机械节点现状=应然=强制单路→守成;worker/attributor 轴覆盖面错配已实证(§5)、无轴面理论初判。**错配终判我给「现状→应然」箭头 + 一句修法方向**(prompt 加护栏 / 转判例 / 加 ask 位),你条款化。这符合你②要求吗?

**下一步**:#43 剩余轴(②③④⑤⑥)落地 → 填各面数据底三列 + 错配终判 → 交 Design 条款化。轴口径 Design 已拍齐(见 §5)、轴① 已填(prov.)。

---

## 5. 口径与数据源台账（可溯,防臆造）

**Design 轴口径拍齐(2026-07-19)**:
- **双轴正交采纳、保两轴别压**(压单轴会藏 C×需强危险格,那是最该 surface 的);门密度 key 需 gate 性、门形态由可 gate 性(ABC)定;ABC 对齐既有 `[[compile-quality-abc-three-layer]]` 非新造。
- **C×需强 单列「防御纵深」类**(非守成非放弃)——§1.3.2 已 formalize。
- **修法判据挂轴、别另写**(现状→应然箭头 + 一句方向;"为什么应然=X" 从两轴列读出,判据单源在轴列,零双写)。

**Theory 轴① 数据注入(2026-07-19,provisional,终候选待六轴收卷)**:
- 源:Theory jq 亲跑 105 delivered 卷,`docs/forensics/team4_theory_corpus_study.md` 轴①(落地后引精确行)。
- 结论:`expected_hits_form = f(op机制, H寄存器)` 105 案零例外(capture 36 ≡ H relation_compare_used 36 双向同集;op 单独不满射 form、op+H 联合唯一定)。
- 落映射(Design 咬合定稿 2026-07-19):原「断言形态」面按 `form=f(op,H)` 105 零例外分**两层**——**worker 决策面 `worker/断言op&H选择`**(C 层语义,高自由度,FORM_BY_KIND 域)+ **engine 机械门面 `engine/form判定`**(A 层强制单路守成,LLM 零 latitude)。自由度边界钉在「claim→选 op&H」跳。**标 prov.**,六轴收卷后转终定。
- 待入:~~轴②④⑤⑥ 已注入(下)~~;轴③ 待 leader 裁。

**Theory 轴②④⑤⑥ 数据注入(2026-07-19,provisional,轴③待 leader 裁未发)**:
- **轴⑤(重点·第二机械化候选)**:11 欠定案 `min_requests` 二分 → `suggested_fix` 机械导出 **11/11**(null=表达力边界→改预期 / 有限=采样边界→改过程)。落**新面 `worker/欠定修法方向`**(机械默认+LLM 覆盖=A2 escape hatch)——**⚠首个错配/修复候选**:现状 LLM 判断 → 应然机械默认打底(与 `form=f(op,H)` 并列的第二机械化候选)。上游 `worker/claim可验性判定`=判可验性/要不要 defer(高自由度);**边界同型 form:判定上游(高自由度)、方向下游(机械)**。
- **轴④**:`worker/命令选择` routera(235)主导观测/routerb(9)少数;provenance precedent 62 主导、**footprint 仅 2/105**(判例层消费低=C5,#44 C×需强防御纵深的判例层厚度度量;**C5「缺口」结论待判别器,当前只立"消费低"**)。
- **轴②**:`worker/持久化清理` τ 责任=创建型 L2/L3 写才需案级 τ(96:9,集中 yzg 创建型批);二段=τ 责任判定(读结构化事实,半机械)+ 逆元派生(`no X`=`X` 逆元,inverse_forms A 机械)。
- **轴⑥(corroboration,印证 #44 二分)**:运行时门违例二分——engine 强制门(s0_dispute/rollback/report_mismatch=A 类机械拦=强制单路)vs worker 决策点(needs_decision/escalated=worker 触发=高自由度+门 backstop)。**限运行时门,26 emit-lint 门另计**。
- 源:`docs/forensics/team4_theory_corpus_study.md` 轴②④⑤⑥(落地后引精确行)。**两个机械化候选面**(form=f(op,H) 守成 / min_requests→suggested_fix 修复)是本轮语料给 Design 的最强条款化输入。

**Theory 轴③ 数据注入(2026-07-19,最后一轴,leader 裁定,六轴齐)**:
- **覆盖满射决策面 → 新面 `worker/用例覆盖判定`=必留人工**(§1.3.3):脑图→用例满射残差三粒度(候选级同义反复/场景级判定语义/叶级子细节)**一致机械不可判**→观察级、不作强制门(INV-breadth:172 报告漏编集不 gate),既不强制单路也不机械默认、保留人工复核。
- **INV-7 闭环 → 新面 `engine/INV7闭环记账`=A 守成**:126 autoid 回戳零遗漏入台账=engine 侧机械(编译回戳自动)、非 worker 决策面。
- **三极收束(轴③补齐,#44 核心骨架)**:自由度分层三极——①**机械默认可**(form=f(op,H) 守成 / min_requests→suggested_fix 修复)②**engine 强制**(INV-7 闭环 / emit 门)③**必留人工**(覆盖满射,反例、机械不可化)。**必留人工与机械化候选对称**,防 over-mechanize(给测不准的面加机械默认=固化系统性误判)。
- **六轴数据全喂完**:轴①断言形态 / ②τ持久化 / ③覆盖满射 / ④命令·footprint / ⑤欠定修法方向 / ⑥门二分。#44 数据底填充完成、30 决策面,余 13 面(attributor 侧无轴覆盖)守待。

---

## 6. 条款化输入台账（Design 早对齐 2026-07-19；正式 land 随 full mapping 一次入 DESIGN/skill,避分次漂移）

**条款① `form=f(op,H)` 守成**(现状=应然=强制单路):
> `engine/form判定` 锁 A 层机械门,`form=f(op,H)` 不得改为 LLM 可判/可覆盖——防 105 零例外的机械确定性退化成 C 面自由度。

**条款② `worker/欠定修法方向` 修复**(全表首个修复条款):
> 修法方向 `suggested_fix` 由 `min_requests` 二分**机械默认打底**(null=表达力边界→改预期 / 有限=采样边界→改过程,11/11 实证)+ **LLM 覆盖须声明理由**(记 exception)。**无理由不得覆盖**——防 escape hatch 退化成 silent bypass(LLM 每次都覆盖=机械打底白设),同 frozen override 需 `override_frozen_reason` 模式。判据挂 min_requests 轴(单源、条款不重写)。

**修复条款模板(Design 定,后续错配面照此)**:
> `现状→应然箭头` + `判据挂轴(单源、不重写)` + `escape hatch 有摩擦(覆盖须声明理由=exception 非 norm)`。

**设计要义**:「机械默认 + LLM 覆盖」混合面的通用护栏 = 机械打底缩小 LLM 错误面(可判性收益)+ escape hatch 防机械误伤特殊 case,但**覆盖必须有摩擦**(声明理由),否则可判性收益被稀释成纯自由发挥。

**红线自守**:所有 prov. 标记的行,数据底列出处均指向 Theory 报告(未落地则标"待落地引精确行"),不抄语料内容、不臆造未出轴的结论。

---

## 7. Design 全映射定稿（#44 交付，2026-07-19 · Design；per-face 层）

> **本节 = per-face 数据层**（三极 verdict × ⑥C `[Wn]/[An]` 规则归属 × clause 状态）。**判据框架层（双轴/三极/防御纵深/2 firm 条款/修复模板）在 `DESIGN_v8_engine.md §21`——本节不复制（零双写）、只 cross-ref。** 消费 §1-§6、**不覆盖 §3**（§3=LLM-Eng 的 ABC/官方锚/现状/prov. 应然；本节=Design 三极 verdict + 规则归属 + clause 状态，两层互补）。谱位定义见 §1.3 + DESIGN §21。
> **§21 已本批 land**（过 Theory+leader 评审，leader 2026-07-19 裁）；**prompt/skill 实改走后续四关批 with eval**。`[Wn]/[An]` 内容不抄、id 现查 `agents/compile-worker.md`/`compile-attributor.md`+`theory-map.md`。

### 7.1 全映射表（谱位 × ⑥C 规则归属 × 官方锚 × clause 状态）

clause 状态：**firm**=axis-backed 已实证（prov.）/ **理论初判**=无轴覆盖待实证。

| 决策面 | 谱位 | ⑥C 治它的规则 `[Wn]/[An]` | 官方锚 | clause |
|--|--|--|--|--|
| `worker/测试点陈述` | 自由发挥(C) | W1(claim+证伪观测=可判定性基) | B3 高自由度 | 理论初判 |
| `worker/命令选择` | **防御纵深**(C×需强) | W2(forbidden-mechanism 93/105)·W6(retrieval-order)·W21(零写死命令) | B3 给方向/零写死 | firm(轴④·判例层厚度待判别器) |
| `worker/E-F通道选择` | 强制单路(A 对象闭集)+自由(判门) | W11(E/F 列对象闭集 wrong-door) | B3 低自由度护栏 | 理论初判 |
| `worker/断言op&H选择` | **自由发挥**(C·FORM_BY_KIND 引导) | W5·W23(observe-then-assert)·W7(采样 flaky)·W8(presence-luck)·W9(persistence-abs)·W10(layout-range) | B3 高自由度/M3 | **firm**(轴①·边界钉 claim→选 op&H) |
| `worker/期望值来源` | 强制单路(禁 observe-then-assert 红线)+自由(溯源) | W5·W23 | B3 低自由度护栏 | **firm**(溯源红线守成) |
| `worker/步骤结构` | 强制单路(结构门)+中间态 | (crash-gate→engine emit 侧;worker:带 H 观测步须配不带 H) | M1 模板严格 | 理论初判 |
| `worker/claim可验性判定` | **自由发挥+验证器兜底(B)** | W12(compile_check_verifiability)·W13(verification-path-absent) | W2 验证器反馈环 | **firm**(轴⑤·上游高自由度+验证器半机械) |
| `worker/欠定报告` | 强制单路(结构三元组固定序) | W3(compile_report_underdetermined 三元组) | M3 条件决策点 | **firm**(结构三元组守成) |
| `worker/欠定修法方向` | **机械默认+LLM 覆盖有摩擦**(A2) | W12/W13 邻接(min_requests 二分) | A2 默认+escape | **firm-修复**(轴⑤ 11/11·全表首个修复=条款②) |
| `worker/等价方案推导` | **防御纵深**(C×需强·极高代价) | W2(forbidden-mechanism)·W13(4criteria+emit 禁 land+强制转 user) | A2/引擎不注入命令 | 理论初判(极高代价防御纵深) |
| `worker/持久化清理` | 引导中间态(τ 责任半机械)+强制单路(逆元机械) | W14(persistence-families 保存族) | W1 checklist | **firm**(轴②·96:9 创建型+inverse_forms A 机械) |
| `worker/emit载荷结构` | **强制单路**(blocks 契约+provenance 门) | W20(handrolled-bypass·blocks+provenance) | M1 模板严格 | 理论初判(A 层结构门) |
| `worker/交付语言` | 自由发挥(格式引导) | W15(desc 人话·regex 在 G) | B3 高自由度 | 理论初判 |
| `worker/用例覆盖判定` | **必留人工**(观察级不作门) | (INV-breadth:172·engine 观察级、无 prompt 规则) | A2 不过度自动化/B3 | **firm**(轴③·THEORY C8 三粒度定理) |
| `attributor/归因判层` | 自由发挥(C·layer descent) | A2(版本层 first)·A5(层定义)·A22(证据不足→reflow) | M3 条件决策点 | 理论初判(attributor 无轴覆盖) |
| `attributor/复现方向判断` | **自由发挥+验证器兜底(B)** | A10(unchecked-repeat·核 _prev_attribution 上卷+同签名复现) | W2 验证器反馈环 | 理论初判(B 层可强化) |
| `attributor/quote引用` | **强制单路**(verbatim 机械门) | A1(retold-echo-dropped-^)·A21(verbatim-substring 门) | B3 低自由度护栏 | **firm**(A 层 gate-checked 子串) |
| `attributor/disposition选择` | 自由发挥(闭集选) | A5·A10 | A2 默认+escape | 理论初判 |
| `attributor/E自检` | 引导中间态(self-check) | A6(env_blocked-one-member)·A7(wrong-door-shell-prompt) | W2 反馈 | 理论初判 |
| `attributor/product_defect检查` | 引导中间态(5 checks 固定序) | A9(defect-reran-historical-PASS)·A12(K-poisoning) | W1 checklist/M3 | 理论初判 |
| `attributor/ask触发` | **强制单路**(panel-mandatory 门) | A11(preset-panel·kb_intent_search first)·A13(submit_ask_panel 门)·A14(panel-when-derivable) | M3 条件决策点 | **firm**(A 层 expectation_suspect 门) |
| `attributor/user_note措辞` | 自由发挥(中文契约+趋势) | A18(english-panel-prose)·A23(attribution-language-drift 语言分层) | B3 高自由度 | **firm**(D28 语言分层·契约门验中文占比) |
| `attributor/h_position候选` | 自由发挥(候选·引擎裁决) | A15(RUNTIME-slots 邻接)·(propose not sentence) | A2 默认(空=unknown) | 理论初判 |
| `engine/form判定` | **engine 强制/强制单路**(A·f(op,H) 机械闭合) | (机械导出·无 prompt 规则;worker 侧对应 W5-W10 断言族) | M1 严格/S5 可验证 | **firm**(轴①·条款① 守成) |
| `engine/INV7闭环记账` | **engine 强制**(A·编译回戳机械) | A17(counts once filed)·A20(reads filed fields) | S5/INV-7 | **firm**(轴③·126 autoid 零遗漏) |
| `engine/emit结构门` | **engine 强制**(A) | W20(handrolled-bypass)+worker 断言族门 | M1 严格模板 | firm(N.A. 机械·设计即是) |
| `engine/lint凭证` | **engine 强制**(A·mtime 签名) | (机械·无 prompt 规则) | S5 可验证中间输出 | firm(N.A.) |
| `engine/reconcile全射` | **engine 强制**(A·四值全射) | (机械) | S5 | firm(N.A.) |
| `engine/diagnose批级裁决` | **engine 强制**(A·机械子集重编) | (机械) | — | firm(N.A.) |
| `engine/终验幂等闸` | **engine 强制**(A·组成指纹幂等·①A 缝合三条件) | (机械·①A cur_bed/cur_build/coexist) | — | firm(N.A.·①A #45 已接线) |
| **`worker/execute-form可见性`**（#48 派生新面） | **prompt-data 缺口面 = 引导中间态候选** | W6(retrieval-order 检索面须含 execute 方法族)·W21(零写死但须被展示存在) | B3/官方 progressive-disclosure | **修复候选**(#48 归因) |

### 7.2 #48 派生新面说明（G/V 分层的自由度投影）

`worker/execute-form可见性`：#48 R0 归因证「G 层 gate accept execute（40 动作从 mirror 解析）但 worker prompt/references 零指 execute dispatch」——**这本身是一个自由度决策面**：worker 该不该被展示 execute/server 方法族的存在？现状=未展示（execute 对 worker 不可见 = 事实上"强制单路"到 config+dig，**非设计意图、是引导缺口**）；应然=**引导中间态**（`contracts.md` 检索顺序加一句指 mirror `apv_action.py`/`client_action.py` 形态，让 worker 现查——非写死命令，守 W21）。成本=prompt edit（后批四关）。**注**：这不是"给 worker 更多自由"、是"把被引导缺口误锁死的自由度解开到应然引导态"（同 framework-capability-before-limitation：能力在、没引导 ≠ 设计排除）。

### 7.3 边界 + 未决

- **本批 = mapping DOC**；worker/attributor prompt/skill 实改（含 #48 派生面 `contracts.md` 补句、条款② min_requests 机械默认接线）属**后批走四关 with eval**（改时按 §7.1 谱位 + DESIGN §21 门密度对号）。
- **clause 状态诚实标**：firm（axis-backed·9 面）/ 理论初判（无轴覆盖·~14 面，多 attributor 侧 + 部分 worker）——理论初判面**不 over-claim**，待后续语料或实证升 firm。
- **可直接起草 DESIGN 条款的 firm 面**：条款①（form 守成）/②（欠定修法方向修复）已在 §21；必留人工（用例覆盖判定）、防御纵深（命令选择/等价推导）、及其余 firm 面（断言 op&H/期望值来源/claim 可验性/持久化清理/quote/ask 触发/user_note/engine 七面）现状=应然 → **守成条款**（"锁现状、不得退化"），后批随 §21 扩条款时 land。
