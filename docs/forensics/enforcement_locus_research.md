# 执行位点(Enforcement Locus)调研 — 团队 brief 汇集

> 起因:593516 分布形态问题的根因是"低自由度、可机判的正确形态被留给了散文/模型判断"。团队 5 agent 调研理论依据+工业方案+我们文档补充+实证。本文汇集各 brief 原文,末尾团队汇总。

---

## Brief 1 — theory-basis(学术理论依据,已核验一手来源)

**核心重构(纠正了发起框架三处偏差)**:原则成立,但把两条独立轴压成了一条("机器 vs 模型")。真正的分界不是"结构 vs 语义",而是 **"闭形式系统内可机判(FORM/LOGIC)→ 机器" vs "需世界知识(DOMAIN/SEMANTIC)→ 模型"**。

### 六大基础 {引用 · 一句话 · 落到"在哪执行不变式"}

1. **Rules vs Standards** — Kaplow, *Duke LJ* 42(3), 1992, pp.557-629。"规则与标准的唯一区别,是给法律赋予内容的努力发生在人行动之前还是之后。"规则**颁布贵、适用廉**;标准反之。**行为越频繁越同质,规则越占优**(一次颁布成本摊薄、一份规格覆盖众多同类)。→ 结构门/确定oracle=规则(内容事前定、每次同样适用);逐案模型判断=标准。WRR 形态每个分布案复现、唯一正确形 → 频繁+同质 → 经济学**要求规则**。bug=在经济学要规则处选了标准。

2. **Make illegal states unrepresentable / Parse don't validate** — Minsky(Harvard CS51 2010,非CUFP)、Wlaschin(2013/2018)、Alexis King(2019)、Curry-Howard(Howard 1969/1980)。把不变式编进类型/文法,非法值**构造不出来**(编译器而非运行时/约定拒绝)。King:边界处 parse 成保留证据的精确类型,别 validate-then-discard。→ **结构门的理论 + 为何最强层**:validation 事后检测(可绕,"门挂凭证路不挂编辑路"的疤);文法只准正确形 → 坏值**不可表达**。"分布断言必须区间"若进 emit 文法,少样本计数**根本 emit 不出**。

3. **Proposer-Verifier 不对称** — Cook-Levin(1971);LLM 侧:Generative Verifiers(2408.15240)、LLMs Cannot Self-Correct Yet(ICLR2024,2310.01798)、Let's Verify Step by Step(2305.20050)、GV-Consistency(2310.01846,GPT-4 自洽仅~76%)、Self-Verification Limitations(2402.08115)、AI safety via debate(1805.00899)。检查比生成廉/可靠——**但仅当 verifier 在更强或独立可靠性类**。LLM 验自身共享失效模式、增益近零(Stechly:"自评显著崩、外部 sound 验证显著增")。→ **最承重**:确定性 oracle 与随机生成器**不同可靠性类**→不对称收益大;另一个 LLM=**同类**→collapse。你的 942对/3pp 正是此。**verifier 独立性(非存在)才授权信任**。

4. **TCB / 最小化可信基** — Saltzer-Schroeder(Proc IEEE 1975:economy of mechanism/complete mediation/fail-safe defaults/least privilege);TCB(Orange Book 1983)。安全只系于最小化的必信组件。→ 把 LLM 当**不可信组件**:别让不可信物变可信,而是**缩小可信基到小而可审计的确定性机器(门+沙箱),在边界 mediate LLM 所有产出**。你架构已全中:complete mediation=lint凭证到合并;economy=门可审LLM不可;fail-safe=毁灭命令denylist;least privilege=多根沙箱。

5. **端到端论证** — Saltzer/Reed/Clark(ACM TOCS 1984)。"该功能只有靠端点应用的知识才能完整正确实现…(中间不完整版可作性能增强)。"→ **哪一层拥有正确性保证**:有完整语义上下文的端点(你的上机 oracle)。中间结构门是**廉价早筛/性能优化(fail-fast省一次上机),不是正确性权威**。即便完美"必区间"门也只保证断言**有能力**测分布;**真机统计测量才真的测比例**。结构门抬地板(足以有能力对),端点定天花板(真的对)。

6. **纵深防御/瑞士奶酪** — Reason(1990/1997/BMJ2000)。防御层像多孔奶酪,只有孔一瞬对齐才出事;叠多层、不靠单层——**且层必须独立**,否则共模孔破整栈。→ "分层"胜"选一边"的形式理由。独立性要求正是 LLM判LLM 是**坏层**的原因(孔与被检者对齐、零增益)。你真实层(机械门→上机oracle→人升级)失效模式各异=真纵深。

### 其他中心理论
- **The Bitter Lesson**(Sutton 2019):别硬编码**领域内容**,但**结构/逻辑脚手架**Sutton明确赞成。你"prompt不写设备命令/不写强关键字典"=对齐;GA-CUT回归=违反(硬编码领域规则杀金标准);WRR bug=**反向失败**(真formal不变式留给判断)。→ **真正的轴不是"机器vs模型"是"FORMAL/LOGICAL(→机器) vs DOMAIN/SEMANTIC(→模型)"。你两条规则("禁语义门"+"低自由度正确性入门")是同一条从两侧看,分界=闭系统内可机判**。
- **不完全契约**(Grossman-Hart 1986/Hart-Moore 1990/Nobel2016)+Simon 有限理性:穷举不了所有情形→关键是配置**剩余控制权**。→ 你 ask_user/needs_decision台账=事前配置事后决策权(高代价未定项归人)。
- **机制设计**(Hurwicz/Maskin/Myerson,Nobel2007;揭示原理):设计规则使自利agent均衡实现目标,非靠善意。→ 结构门不只过滤,使正确形**唯一可emit**("让对的成为容易的")。凭证到合并=激励设计,正确路是唯一可行路。**这就是散文劝导会漂、文法不会**——劝导非激励兼容,门是。
- **能力安全/POLA**(Dennis-Van Horn 1966;Miller 2006):只授所需权限,不可信组件爆炸半径结构性受限。→ 多根沙箱+毁灭命令denylist。
- **Design by Contract**(Meyer 1988/1992):前后置+不变式=可机检契约,是类型层与运行时oracle的桥。

### SYNTHESIS — 决定任一不变式在哪执行的一条规则
对任一不变式 I,在**其本性允许的最强层**执行,再把弱层叠在后面做纵深。按序走四层:**(1)结构/文法门**——I 可表达为FORM则编码使违反不可构造(最强,消除而非检测);**(2)确定性oracle**——I 可由终止过程机判(编译器/测试/沙箱/可算统计功效检查)则路由至此(不对称仅当verifier更可靠类、且确定检查器是;权威oracle置于有完整语义的端点,中间门作fail-fast);**(3)人升级**——I 不可机判但高代价且欠定,经显式剩余控制机制归人;**(4)模型判断**——其余(高自由度、可容错、无廉oracle)才信模型。路由键是**三个独立问题、非一个"自由度"标量**:*I 在闭形式系统内可机判吗?*(形态→层1,可算→层2)、*错误代价?*(高则下压一层+加层)、*多频繁/同质?*(频繁+统一则值得建规则)。压倒性约束:**永不把检查器放在与被检者同一可靠性类**(LLM判LLM,违verifier独立+奶酪独立,加成本零纵深)。一句话:**把FORM与LOGIC编进你能审计信任的确定性机器;把易错模型留给闭形式系统判不了的DOMAIN语义;两者间保留一个真实独立的端点oracle**。

### 发起框架的不精确处(theory-basis 主动标注)
1. "规则vs标准"≠"机器vs模型":Kaplow轴是内容**规定时机**(事前vs事后)。确定oracle是"事前定内容、运行时适用"的规则。结构门与确定oracle**都是规则**,差在**在哪适用**(构造时vs运行时),别混。
2. NP类比是**复杂度**,你架构靠**可靠性**:NP"易验"指 sound-complete 检查器低复杂度;LLM 生成-验证差是经验准确率,LLM验证器既非sound非complete。别把NP保证借给LLM验LLM。用Cook-Levin作直觉泵,承重引用是自验证局限诸文+TCB。
3. "结构vs语义"是好的初切,但真正对象是**可机判性的阶梯**,WRR横跨其上:"是否区间形态"=纯形态(层1);"N样本有无统计功效判该比例"=可机判但非文法(层2,可算功效/可识别性oracle);"这是不是该业务的对比例"=真语义(层3/4)。**WRR修复至少三级可执行,非二元**。结构门只逼区间形态,不保证该样本量下比例**可测**——那要层2功效oracle。
4. 端到端也**警告别过信结构门**:任何中间检查(含结构门)非正确性保证,只端点是。结构门=已知不可能形态的廉价早消除+fail-fast,非"结构门=正确"。地板vs天花板。
5. "自由度"非一个标量、是三比特,且大多只track其一:低自由度但不可机判(唯一对答案但只领域专家能判)→人升级非结构门;高自由度但可容错→模型无需升级。WRR直觉对但精确触发是"**可机判的唯一正确形**"非"低自由度"。拆成{可机判? · 错误代价? · 频率?}防下次误route。
6. "把正确性推进机器"自带Bitter-Lesson陷阱(你已被咬:GA-CUT):以"机器"之名硬编码**领域**规则=祸。使原则安全的限定词:把**formal/logical**不变式(文法/类型/统计可识别性/从真源parse的闭集)入机器;别把**domain/semantic**内容入机器。"禁语义门"与"低自由度正确性入门"是**同一条**,分界=形态/逻辑(闭系统可机判)vs领域知识(需世界)。

---

## Brief 2 — industry-design(工业设计方案,一手源已 fetch)

**六层执行栈(硬→软)**,每不变式推到能表达它的最硬层:
1. **不可表达**(最硬)——约束解码:文法/schema token-mask 使错形态概率0(Outlines/XGrammar/GBNF/Guidance;OpenAI/Anthropic strict schema)。
2. **边界拒绝**——harness 按 schema/确定性句法 oracle 拒畸形(strict 工具 schema;SWE-agent edit-linter `flake8 F821...`拒不落;确定性 Guardrails validator)。
3. **能力受限**——沙箱/权限/hook 使错动作不可能(seccomp/gVisor/Seatbelt;权限规则;PreToolUse deny;工具 allowlist)。
4. **确定性 oracle 校验**——跑编译器/类型/测试/LSP 读真结果修复,程序而非模型裁决语义正确(Claude Code/OpenHands/AlphaCodium;propose→run→read-error→repair)。
5. **人升级**——结构性暂停把真欠定交人(LangGraph interrupt;ask 规则)。
6. **模型判断**(最软)——self-verify/checker-LLM/散文;低自由度正确性上经验净负(Huang 2310.01798;Kamoi 2406.01297)。

**放置律**:把每不变式推到栈上尽可能高层。**散文在 L6 之上——它连检查器都不是、只是"希望"**;WRR bug 正是把低自由度正确性规则停在最软层。修法=下移到 **L2(结构 emit 门拒错形态,你的崩溃门/必崩门正是此)** 和/或 **L4(上机 oracle)**。承重测试:*"模型在这判错,什么拦它?"* 答"只有 prompt"=放太软。

**Claude Agent SDK 博客直接背书本论点**(单条最佳一手引):"最好的反馈是给明确规则+说明违反了哪条…**代码 lint 是极佳的规则式反馈**…让另一个语言模型按模糊规则'评判'输出**通常不是很稳健的方法**"(claude.com/blog/building-agents-with-the-claude-agent-sdk)。opencode/Claude Code 官方证实 LSP diagnostics 喂回 LLM=L4 实例。

## Brief 3 — theory-supplement(我们理论文档补充:立推论 (47) 非新公理)

**裁定**:执行位阶概念在三份理论**散落 7+ 处从未统一命名**(freedom 轴 E1、机检性 E2/E6、代价/自放大 E8/E9、四出口 E3/E4/E7/E10/E11、(36) 给分类器元形式、§2.10 给构造优先+形态非推理、§0 给"读物理事实合法/语义判禁"原话)。**是既有原则的操作化推论,非新公理**——由自由度原则+§2.10+(36) 推广导出,零新本体。

**落点**:K §2.9 新增 **§2.9.6 (47) 执行位阶律**。四位阶(L_struct 结构门/L_oracle 确定 oracle/L_human 人升级/L_model 模型判断)+ 判定函数(键=⟨自由度 f, 错误代价 c 含自放大子轴, 机检性 m⟩):①m=形态可判∧f=低→L_struct 且**优先构造约束、检出即路由构造、非 reject-and-strand**(§2.10+M5 fail-open);②需地面真值→L_oracle(上机);③is/ought 决策或 f高c高无廉 oracle→L_human;④f高∧m≠形态可判∧无廉 oracle→L_model(带 grade 之死红线:永不自证质量)。

**核心细化(必写,否则与用户裁决打架)**:一条不变式正解常是**分解到多位阶、非二选一**。593516 正解=L_struct 检出+构造路由 worker+L_model/L_human 残差(attributor 自查)+写回血统护栏((45))。定稿 §A 否掉纯硬门正是此复合的实弹落形——**(47) 编码了这次纠回**(分支1 明写非 reject-and-strand),非复辟被否方案。

**与既有复合**:与 h-代数正交(内容 vs 放置);在 (40) 上游(放对位阶使坏形态不 emit→更少 fail 抵达);(36) 是 (47) 写授权特例(推广非重述)。对抗表 X1-X7 全过(X1 过度门控由 m(I) 严定义排除 GA-CUT;X2 撞§0 由"只强制形态非判内容"和解;X3 不 reject-and-strand 由分支1 编码;X5 样本量由 c 自放大子轴触发写回护栏)。

## Brief 4 — design-modification(我们设计文档修改:§0 二分 + 分布最小结构门)

**冒烟枪**:§0 原文(`dongkl_finalization.md:10-13`)"唯一保留的机械判定=协议级硬事实(^/主机提示符/ping)"与 `DESIGN_v8:252`"保留 emit 全部机械门(17+单调门)"**字面互斥**。真相:§0"唯一"措辞把结构门这一整类**误收缩**成三个协议实例——这 17 门本就同类、一直在用、§0 从没想删。二分在 CLAUDE.md 自由度纲、DESIGN_v8:529/596 **早是默认**。

**§0 真禁的只是语义门**。**一句话判据**:删掉该门,若"换内容就翻案"→判内容=语义门(禁);若该形态"任何设备回显下恒真/恒假/必崩"(内容无关)→判形态=结构门(留)。

**提案**:
- **(a) §0 精炼** + 新增 §0.1 两类门定义(语义门禁/结构门留 + 上述判据)。**DESIGN-only**。
- **(b) 低/高自由度决策分类表**(现有 17 门+destructive+command_existence+τ配对全归结构门;分布形态是**全表唯一缺口行**→结构门)。DESIGN-only。
- **(c) 分布形态最小结构门**——**唯一需写代码项,逻辑现成量小**:把**死掉的** `grade_extract_script.py:357-408` 分布诊断器(现只被已删 grade 管线消费=死代码)搬进 emit 门 `_check_distribution_assertion_form`,并入 `check_crash_gates_mandatory`(:1440 挂载,与 found_times 同姿势:拒落卷+不落 lint 凭证)+ `lint_xlsx_case`(:1171 复扫)。**最小作用域**:仅当 `_detect_lb_methods` 解出算法∈{rr,wrr,grr,gwrr} 才激活,ga/hi/topology/rtt **完全不触发**(`_dist_ctx` 内建防 GA-CUT 误杀)。**拒**:①unbounded `Hit:\d+`(恒真零信息)②hardcoded 单计数∧dist③字面成员IP dig-found∧dist(=593516 presence-check 精确形态)。**放行**(一条不删):range/membership_derived(abs_found 合取)/captured_relation/device_runtime。违例文案指路正确形(`compile_expected_hits` 区间/H 捕获比较),**不写死命令数字**。**保守选项**:先只上恒真子门(零争议纯A层),写死/成员子门先呈报不硬拒(同 command_existence 姿势),观察 N 案零误伤再翻硬拒。
- **(d) env_blocked→reflow 路由**:attributor.md:63-72 **已落地**(prompt);(c) 使其修法**真正可强制**(reflow 重编若再写坏形态,emit 门拒→逼出区间)。DESIGN-only。
- **(e) 分布类 ask 走 (46) 三元组**:多数分布类**根本不该 ask**(区间是可离线推导的确定替代,worker 直接采用);仅样本量本床发不出才升 ask,题面必携区间替代。DESIGN 注记(code 已在,核对 questions.py:112 generic 分支命中)。

**DESIGN-vs-CODE 切分**:纯 DESIGN=(a)(b)(d)(e);唯一 DESIGN+CODE=**(c) 把已存在、已被 GA-CUT 锤过的死检测器搬成最小作用域 emit 结构门**。

## Brief 5 — data-miner(dongkl+yzg 实证:SUPPORT,缺口锐化)

样本(诚实):dongkl 崩于 round1(34案/31emit/29跑),分布 universe=feature79993=12案(rr×4/wrr×4/ga×4),9emit/8跑;yzg 26案零分布。

- **(1) 形态清单 SUPPORT 强**:9 emit 分布案 **4 种不同形态**。**wrr 3案=3种不同形态**(484 neg-zero-Primary / 516 membership / 545 interval-Hit)——**没一个验 3:2:1**;rr 2种;**ga 一致(且恰当,GA 确定性)**。散文没能让旋转算法(rr/wrr)收敛。
- **(2) env_blocked 误归 PARTIAL(N=1 精确吻合)**:593516 是**唯一** env_blocked,passed_cp=6,fix_direction 自认"6/6 show 过";稳健的 show-statistics 形态过、脆的 few-digs 超时=**form-induced 非环境**。
- **(3) 台账 SUPPORT**:combined fail 处置=reflow **19 主导**/env_blocked 1/expectation_suspect 1/defect_candidate 2;**分布敏感 fail 6→5 reflow+1 env→0 落 method-specific 桶**(词表{reflow/frozen/env/defect/expectation/rerun}无"方法不当"桶,枚举确认)。
- **(4) 零判别力假阳 SUPPORT**:框架 `found`=re.search over concat buffer,IP 出现≥1次即过、**与轮转无关**=rr/wrr 构造性零判别力;**3 在跑实例**(778012/778072/593516 Phase-1 `found 213` 过而设备只返 213 没轮转);ga PASS 案非假阳(确定性)。
- **(5) ask 框定 SUPPORT + 关键锐化**:**欠定 needs_decision 机制已在、对 4/4 分布欠定案给 `equivalent.procedure`(relation_diff/dist 正确方法替代)**——但 **gated on worker 自声明欠定**;`ask_panel.json` 仅 1(572741,expected_vs_observed 无方法替代)。**精确缺口**:6 案静默 emit membership/other 形态**没触发欠定**→绕过方法替代机制→跑→fail 进 reflow/env;raise 欠定的 4 案恰是never-emitted(suspended)。
- **(6) 轮次**:dongkl 全 round1(崩)→0 分布案有机会收敛;yzg reflow 对 config/compile bug 收敛(round2-3→deliverable)但**从没在分布形态问题上 exercise**。

**data-miner 总判**:thesis SUPPORTED,锐化——**方法替代机制(欠定)存在且给对 fix,但 gated on worker 自声明;静默 membership emit 上游无触发、下游无 method 桶=精确 enforcement hole**。

## ⭐ data-miner 对修法的直接验证
精确缺口("静默 membership emit 绕过在场的欠定/方法替代机制")= **worker.md 通道消歧修法的靶心**:机制在场、唯一缺口是 worker 误分类不触发它。修法让 worker 认出「dig-参与轮转=分布 claim」→触发欠定/falsify→拿到 `equivalent.procedure` 正解。**零新机制、最小修法**(再证"不加新硬门"对)。**残余**(worker 仍偶误分类→静默 emit 无上游拦截):候选确定性 backstop=「配加权分布算法+断言全 presence+无 dist/区间」→advisory 呈报(非硬拒);**evidence-first:重跑验主修法,不够再加**。

---

## 团队汇总(四家收敛,待 data-miner 补实证)

**根因一句话**:分布形态验证(低自由度×高自放大代价×形态可机判)这条不变式被停在执行栈最软层(散文,连检查器都不是),worker 遂漂移写少样本 presence-check,零判别力假阳(RouterA 零轮转却 PASS)→ 投毒判例→ 归因误退 env_blocked→ ask 框定错。

**修法(三级阶梯,复合非单选)**:
1. **理论**:立推论 (47) 执行位阶律(K §2.9.6),四位阶+判定函数+"分解到多位阶非二选一"+对抗表。
2. **设计**:§0 二分(语义门禁/结构门留+判据)+ 决策分类表。
3. **实现**:见下 ⚠ 关键纠正——**不搬检测器进硬门**。
4. **端点**:上机统计 oracle 仍是最终裁决(结构门只抬地板)。

---

## ⚠ 关键纠正(用户"为什么它死你要想明白"挑战驱动,2026-07-16)

**design-modification 的"把死检测器 grade_extract:357-408 搬进 emit 硬门"方向错了。上面 §Brief4/§团队汇总的"分布结构门(c)"作废。** 证据链:

1. **检测器不是无辜孤儿,"诊断非门"是 ABC 框架的刻意设计**。读全 suspect 判据:
   - `count_tautology_suspect`(unbounded `Hit:\d+`)= **内容无关恒真**(不 gated on _dist_ctx)= **A 层**,唯一可硬门。
   - `count_hardcoded_suspect`(`Hit:固定数`∧dist)= reason 自陈"命中随**运行时轮转/健康检查变化**"= **经验性设备行为判断** = **B 层**。
   - `asserts_literal_hit_ip`(dig字面成员IP∧dist)= 代码自带**大段排除逻辑+警告**"membership 归属断言结构同、语义不同,漏排误杀合法断言",且 worker 主路不传 provenance 只能靠脆弱 shape 正则 = **B 层**。
2. **ABC 记忆 `[[compile-quality-abc-three-layer]]` 原文一锤定音**:"命中恰好 N 次对 rr/wrr 不可证伪"= **B(可证伪性工具+修复环 LLM 调,落 compile_check_verifiability)**;"**把 B 层判断误当 A 层硬门 = GA 连续 CUT 回归**(grade 写死'算法类补 show statistics')、**和我这次差点做的**"。`verifiability.py` 顶注红线"非分布类返回 verifiable=True 不误杀"。
3. **`compile_check_verifiability` 早在场**:定义 `verifiability.py`(分布可证伪性:算法+n_requests+n_pools→verifiable/underdetermined+最小请求数+建议),在 `compile-worker.md:4` 工具白名单、:116 明令 worker 调。**593516 worker 没调——因把"p4参与轮转"误归 membership**(claim_kind 灰区)。claim_kind 按红线归 LLM,引擎不能确定性代判。

**纠正后的正解(分解到多位阶,全贴 §0/ABC,零 GA-CUT)**:
| 分解 | 修法 | 位阶 |
|---|---|---|
| worker 没认出分布→没调 falsify | **worker.md 解 membership-vs-distribution 灰区**(参与加权轮转/验配比=分布claim→必走 compile_check_verifiability;少样本presence=反模式)| L_model(claim_kind 归 LLM=正确位阶,非"退回散文") |
| `Hit:\d+` 恒真 | 补 A 层恒真门(若 structural_gate 崩溃门未覆盖) | L_struct(A,唯一安全硬门) |
| 配分布算法却全 presence 断言 | 可选 advisory 呈报(给事实不结论、不阻断) | L_oracle-tool(B) |
| env_blocked→reflow | 已落地 prompt | — |

**元教训**:bug 不是"§0 禁了该有的门",是 **B 层 advisory 机制(compile_check_verifiability+worker 构造指引)在场却因分类灰区没触发**。**这印证 §0 对(B 保持 advisory)**,推翻了本文前半"§0 张力消解=可加分布硬门"的过度收敛。(47) 理论仍成立且**预言此分解**(theory-supplement 的"分解到多位阶、非 reject-and-strand"对,design-modification 塌缩成一道硬门错)。
