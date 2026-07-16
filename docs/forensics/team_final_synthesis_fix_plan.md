# dongkl 六步团队调查 — 第⑥步合成：理论核对与最终修复方案

> 五路团队交付（全只读取证）：
> ① `team_log_vs_attrevidence_diff.md`（设备原始 log vs attr_evidence）
> ② `team_exec_replay_logic.md`（设备输出倒推执行 + T1..T10 前提清单）
> ③ `team_design_behind_logic.md`（langfuse 思维链 → 设计定位）
> ④ `team_mindmap_structure_defects.md`（脑图规格审计）
> ⑤ `team_design_doc_gaps.md`（设计文档缺口）
> 本篇 = 第⑥步：跨报告矛盾裁决 → 对照 `THEORY_k_state_machine.md` 核对 → 最终修复方案。
> 合成：2026-07-16。

---

## 一、跨报告矛盾裁决（两处，均为证据源轮次不同，非真矛盾）

**593516（成员 IP vs p4 未进轮转）**：终版卷（unsuccessful_cases.xlsx 实读）同一 `show sdns host pool` 下有两条断言——`found: p4`（Success，worker 承认输出形态未知后猜对）与 `found: 172\.16\.35\.225`（Fail Num 1，该命令不列成员 IP）。**「猜对 p4」与「225 配错命令」同时为真**；「p4 未进 WRR 轮转」是早期轮主败因（终版轮设备 p4 Hit:10 已进轮转）。裁决：按轮分辨，基线③与 trace-design③ 各对各轮；共同根因成立=**该命令输出形态在判例层零观察，worker 靠猜**。

**572672/572708（priority 报错有无）**：attr_evidence（定稿 run，设备钟 11:47-48）逐字含 `sdns host method autotest1.com wrr → The priority must be an vaild value...`（拒绝）；早期轮 trace 同型命令**静默接受不生效**。裁决：两者都真——**同一命令在不同设备状态下两种响应**（可能取决于绑定 pool 是否带 weight），这本身就是设备文法歧义，归入「待上机钉死」清单（§四.C7），钉死前文法层不写死。

---

## 二、对照理论文档核对（(47)/(40)/(44)/§0.1）

**成立的（本轮实证再次背书，不动）：**
- **(47) Enforcement-Locus + DESIGN §0.1 路由**：五类缺陷里 ①跨客户端②Hit计数③输出形态⑤精确/时序 都**不该加内容依赖硬门**——加了就是 GA-CUT 重演（593516 末轮"区间+大量发包"能过、GA 案精确计数是对的模型，证明这些判断内容依赖、只能 L_model/L_oracle-B）。design-review 确认 ①②③⑤ 机制在场，病灶是**触发不足**，非路由错。
- **(40) 出口分类骨架**：7 类满射成立（994957 交付报告已正确引用 (44) vacuous marker）。

**理论缺条款的（三条，需补幂等条款/推论）：**

1. **(47) 缺「自愈闭环覆盖条件」推论**：L_model 层的判断力依赖判例层可查——但观察入库腿只收 terminal/escalated（`nodes.py:2270-77`），**漏 S_SUSPENDED**；而分布案的常态归宿恰是挂起（8/9）。结果：上机反复暴露的设备行为（跨客户端不共享轮转、Hit:0、输出形态）**结构性永不入 footprint**（2401 节点对此零覆盖，现存 2 条观察还指反方向），worker 下批照旧靠猜。→ 理论应补：**观察入库必须覆盖所有非 pass 归宿态（含 parked/suspended），否则 enforcement-locus 分解在 L_model 层的前提（可查判例）不成立**。这是本次调查最重要的单点发现。

2. **(40) 缺「前提证伪→非重编出口」的触发判据**：fail 缺省压倒性走 reflow（19:2），「脑图前提被设备证伪→期望可疑/观察入库/缺陷候选」出口存在但几乎不触发。实证触发信号其实是机械可判的：**同型对照案 PASS + 本案同断言 FAIL**（IPv4 517027 过 vs IPv6 532862 挂——zhaiyq 实弹正好复验这条；跨客户端对照同理）。→ 理论补触发判据：**对照差分 = premise-falsified 的机械证据，优先级高于同向重编**。
   附：777976/778041/593484/572672 核心前提**三轮从未修**（exec-replay 实证）——重编在错前提内打转，正是此判据缺失的代价。

3. **§0.1 advisory 路由的唯一可机判留白**：778012 的「断言序列 ↔ 轮转周期自洽性」——纯标量的 verifiability 推不出序列矛盾（前3次 not_found + 后5次全 found 与周期4的 RR 数学上不可能同时真）。这是**内容无关的数学恒假**，按 §0.1 判据够格进 L_oracle 机械判定（advisory 呈报，不硬拒）。

**理论无需动的疑点核销**：T9（778012 r3 dig 全超时后 not_found 假过）——(44) vacuous 机制在「passing case 含 execution-failure marker」时已触发（994957 实证）；778012 该案整体 fail，not_found 假过被掩蔽但无害（未污染交付卷）。列为观察项，不改理论。

---

## 三、证据链上的代码级 bug（与设计无关，直接修）

| # | Bug | 位置 | 影响 | 修法 |
|---|---|---|---|---|
| B1 | `_fail_signatures` 无分隔符拼接 causality+device_context，正则越界把日志节头+文件名抓进签名 | `batch_tools.py:1257/1199/1163` | 4/9 案签名脏；污染 `.frozen.json`、跨轮冻结 `sig_now∩sig_prev`、digest 显示（本轮侥幸未错冻结） | 改解析结构化 `#### (Fail\|Success) Num` 行（现成 `_WA_CHECK_RE@947`），两 bug 同消 |
| B2 | 同函数 grep "fail to find" 不分 Fail/Success，把**通过的 not_found 断言**收进失败签名 | 同上 | 778072 收进 4 条通过断言，签名语义反转 | 同 B1 一刀 |
| B3 | 观察入库漏 S_SUSPENDED | `nodes.py:2270-77` | 自愈闭环对分布案结构性断裂（§二.1） | 入库条件补 suspended（连同 escalated/terminal） |
| B4（低优） | anomaly_lines 无去重（RTNETLINK ×7）；detail_tail 与 device_context 段0 高度重叠 | attr 提取侧 | 噪声淹信号、冗余 | 去重+去冗 |

---

## 四、最终修复方案（分层，每条注明为什么在这层）

### A. 代码窄口（bug 修复，非新门）
- **A1**=B1+B2：fail_signatures 结构化解析。验收：9 案 attr_evidence 重提取，签名与原始 Fail Num 集合逐案相等、零节头污染。
- **A2**=B3：入库补 S_SUSPENDED。验收：自愈演练测试（`test_self_healing_loop.py`）加一例「挂起案观察入库」；dongkl 8 挂起案的观察可见于 footprint。
- **A3**=B4：去重去冗（低优）。

### B. 文法层（一次性类型 + 此后纯数据）
- **B1'**：`domain_grammar.json` 增 **co-required 参数类型**（design-review 已验 top-level 无此类键；wrr/ga 的 weight/priority 绑定关系属「同语句共需参数」非悬空引用，现有 reference_closures 装不下）。一次代码支持新类型，之后同类坑=纯加 JSON 条目，恢复「零代码」承诺。
- **注意**：572708 两轮两种设备响应（静默不生效 vs priority 报错）→ **先过 C7 上机钉死，再落文法条目**，不写死未证实文法。

### C. 判例层（零代码，数据回填 + 待仲裁清单）
- **C5**：把本轮 9 案 attr_evidence 已证实的设备行为观察回填 footprint（`validity=uncertain`+`observed_under`，走 A2 修好的腿或一次性脚本）：跨客户端各自轮转（p2 恒 Hit:0）、Hit 计数语义（服务了成员却不计数）、`show sdns host pool` 只列池名不列成员 IP、`sdns host method` 对 wrr 的两种响应、（zhaiyq 联动）IPv6 会话保持超时条目不清除（532862，IPv4 对照 517027 过）。
- **C7**：exec-replay 的 3 个「必须上机钉死」问题固化为下批开跑前 probe 清单：① pool Hit 计数器何时 +1；② 落点是否绑定源客户端；③ wrr/ga 权重必带性/层级 + host method 响应条件。钉死后转 verified 入 footprint / 文法。

### D. worker 指引（prompt 层，高自由度陈述式，零写死命令）
- **D8**：`compile-worker.md` 补分布构造事实（陈述现象+后果+why，不写死命令）：分布验证的证据面=「命中集合∈存活成员 + 大样本占比」，单一统计计数器不可作唯一支点（实证：设备返回成员但计数 0）；时序锚点必须与轮转周期自洽；**输出形态未知时 probe/先例现查而非猜**（593516 承认未知仍猜=反例）；不假设特定客户端命中特定池、不假设跨客户端共享轮转（判例证实前）。593516/778072 末轮「集合+区间+大量发包」= 实机背书的正例形态。
- **D9**：brief 注入措辞（`briefs.py:175-178/78`，属「设计错误」类）：脑图预期注入时标注为**作者预期（设备未证实）**而非事实；上轮归因标注为**假设**——止住「前提洗白」链（脑图预期→brief 事实化→worker 忠实编码→精确断言放大成必崩）。

### E. verifiability（L_oracle-B advisory，工具增强不变路由）
- **E10a**：claim_kind 增**客户端维度**——跨客户端落点类主张（"client2→pool2"）在无判例支撑时判 underdetermined→ask（trace-design 实证 777976 全程没触发该工具，工具本身也没有这个维度可判）。
- **E10b**：**序列↔周期自洽性**机械检查（§二.3）：请求序列长度、断言 found/not_found 排布与声明算法的周期做可满足性判定，矛盾即 advisory 呈报（数学恒假，内容无关，不越 §0.1 红线）。

### F. 归因/引擎分流判据（(40) 出口触发强化）
- **F11**：attributor 指引 + 引擎 disposition 增机械触发：**同型对照案 PASS ∧ 本案同断言 FAIL**（跨 IPv4/IPv6、跨客户端、跨兄弟案）→ premise-falsified，优先走「期望可疑→观察入库/缺陷候选/ask 改预期」，不再同向重编；连续 2 轮同前提 fail 且无对照支撑 → 强制换证据面（呼应既有 frozen「换法」语义，把"法"细化到证据面选择）。

### G. 脑图规格侧（给测试作者，非引擎）
- **G12**：采纳 mindmap-audit 9 条编写规范；dongkl 具体返修点：ga 族 step2 误配 wrr(30/20/10)（681749 第一因）、「show展示域名算法」分支命名错位、应急 cname 与普通 cname 复制粘贴未测应急路径、补 [check] 锚点（dongkl 0 个 vs yzg 82 个——两批规格质量的硬差距）。

### H. 文档修订
- **H13**：THEORY 补 §二.1 覆盖条件推论 + §二.2 对照差分触发判据 + §二.3 序列自洽入 L_oracle 的判定归属。
- **H14**：DESIGN_dongkl_finalization 补 co-required 类型、S_SUSPENDED 入库、fail_signatures 结构化、brief 注入措辞四节。

---

## 五、优先级与验收

**P0（先行，闭环性质）**：A1（审计链保真）、A2（自愈闭环接通）、D9（止前提洗白）。
**P1**：C5/C7（判例回填+钉死清单）、E10a/E10b、F11、D8、B1'、H13/H14。
**P2**：A3、G12（随下批规格返修）。

**验收器**：
1. 既有回归全绿（`pytest tests/ -q`，含自愈演练/lint 门/prompt 结构门）；
2. 9 案 attr_evidence 重提取签名等值校验（A1）；
3. 自愈演练加挂起案入库例（A2）；
4. eval 断言（改 prompt 前先固化）：WRR 案产出不含精确 `Hit:\s*N`（GA 案豁免——确定模型）、无「特定客户端→特定池」断言（判例未证实时）、时序锚点序列过 E10b 自洽检查；
5. dongkl 失败子集对照重跑：777976/778041/593484 期望走 premise-falsified 出口（观察入库/ask 改预期）而非第 4 轮同向重编。

**一句话**：理论路由（不加内容依赖硬门）被实证背书不动；真正要修的是**闭环的三条断腿**——观察入库漏挂起态（自愈饿死）、对照差分不触发（错前提重编打转）、brief 把未证实前提当事实注入（洗白链）——外加两个证据链 bug 和一个文法层类型缺口。

---

## 六、zhaiyq 活体评审追加（2026-07-16 当日，run 进行中取证，详见 team2_zhaiyq_live_review.md）

**已知缺口活体再命中（fix plan 杠杆坐实）**：
- **(A2) 入库洞升级为自相矛盾**：532862 引擎**自判 defect_candidate 级**（且已引 IPv4 对照 517027），仍因案状态=suspended 永不入 footprint——门键挂在「案状态」而非「观察价值」。
- **(F11) 无机械触发的代价具象**：同一设备行为（IPv6 会话保持超时不清除）拿到**三种处置**——532862 defect_candidate / 517027 reflow→env_blocked / 600046 env_blocked；对照差分只活在归因散文层。
- **(B) 有改善**：手册/兄弟钩子在场时 expectation_suspect/defect_candidate 真的 firing（dongkl 为 0，zhaiyq reflow 占比降至 10/18）。

**两条新律（并入 F11 节实现）**：
- **F11-N1 处置单调律**：归因跨轮无粘性——517027 轨迹 dc→dc→reflow→env_blocked，最强出口（defect_candidate）早达却被后轮弱处置覆盖。修法：处置强度只升不降（defect_candidate/expectation_suspect 一经证据确立，后轮不得静默降回 reflow/env，除非新证据显式推翻并落台账）。
- **F11-N2 污染分歧裁决律**：533020 「fork 判 s₀ ∧ 机械配对 polluters=[]」→ 默认 rerun_isolated → 隔离 PASS 整卷又翻（run13 同型 livelock 苗头）。修法：fork 污染假设与机械无污染者相左时，不得无限隔离复跑——两轮分歧即升 ask/缺陷候选出口。

**zhaiyq 失败类型学结论（exec-replay §1）**：会话保持子系统与池分布不同域，T1-T10 命中 0；失败类型 100% 已知（设备行为差/复跑翻转/vacuous/语法拒/fork infra），**设备知识全新**——5 条新观察待入判例：①持久条目超时不清除（IPv6>IPv4，双案佐证=高置信缺陷候选）②改 service ip 不清旧条目（手册空白）③记录/查询类型语义（CNAME 持久×AAAA、clear ALL）④AAAA/MX/CNAME 不返回需族配对 service ⑤IPv6 listener 3ffc::70 无响应。正是 C5 判例回填的下一批素材。

**本轮已顺手落地的（team2，零回归）**：emit_tick broken 三态并卷（B 修法的 footer 侧）、needs/user_decision 原子写、交付卷组成对账门（方案 b：leaked/absent→事实+outcome 降级，dongkl 778041 泄漏类结构性堵死）、ask 面板空 Other 防呆（532862 实弹坑）、单测密闭化（5 转绿）。物理卷重滤（方案 a）与 P0/P1 行为修复仍待用户裁决后专项轮。
