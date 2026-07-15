# dongkl 遗留问题·实现定稿(2026-07-15,经真实数据 + 用户逐条裁决)

> 取代 `docs/forensics/SYNTHESIS_and_questions.md` 的问题清单与 DESIGN_v8 §18.15「设计中」诸单元。
> 取证四报告 `docs/forensics/{A_oracle,B_attribution,C_gates,F_closeout}.md` 为事实依据。
> **用户裁决把 oracle 的两处判断纠回**:①「集合相等/比例不可构造→需 D」是错的(见 §A);②机械后校验
> 应改为「摆事实 + prompt 自查」,不加机械门替判(总原则)。

## 0. 总原则(用户裁决,统辖全部修法)

**全走「摆事实 + 叫 LLM 自己核对」,不加机械门替 LLM 拍板**(守 CLAUDE.md #5/#6/#12、
`[[compile-judgment-structural-not-strongdict]]`)。判例写回**像 Claude 记忆一样**:如实标来源/条件、
标「用前先核」;读的人当**记忆**(提示,需拿一手证据核)看,不当**铁证**(照抄)。唯一保留的机械判定是
**协议级硬事实**(语法拒绝符 `^`、非设备主机提示符、设备 ping 不通)——这不是替判,是读一个物理事实。

**prompt 编写红线(用户重申)**:改 prompt 一律**陈述事实+后果+为什么**,**禁**「建议/必须/应该」这类
预设结论/指令词(违 skill 编写标准的按自由度分层)。

## 1. 逐项定稿

### A · RR/分布类断言 + 写回洗白(修正 oracle,不需要 D)

**实证**:593516(wrr 3:2:1)用小样本(10 dig)+ 精确/非零/错区间断言(`Hit:\s+3`/`[1-9]\d*`/`[4-9]\d*`),
flaky pass 后写回 precedent(`mirror/verified_…593516.xlsx` live 可检索)。归因层发「加采样刷过」
(`rerun_isolated`),把采样噪声当"样本不足"、没认出配比 40 成员 Hit:0 按 S§0.5 是缺陷候选。

**修正 oracle 的「不可构造」(用户裁决)**:
- **成员归属(⊇)可构造**:`abs_found(每个配置成员 IP)` 合取;`⊆`(无配置外成员)由 config 保证、不需断言。
- **配比可构造**:框架**既有做法**(V6)= 大样本发包 + `show statistics` 读每后端累计命中 + **区间正则**
  (如 `Hit:\s+(2[89]|3[0-3])`)。`domain_grammar.json:144-151` 已白纸黑字记此法(「分布类=发 N 次→各后端
  累计命中∈统计区间,守恒 Σ==N」)。**不需要单元 D**。
- 「加采样」本身不错——错在**用它刷 flaky**、而非用 **config 推导的确定性覆盖样本量**(Σweights×k)。

**修法(全是摆事实/给知识/改提示,零机械门)**:
1. **worker 指引**(`compile-worker.md`):把上面这套"分布类=大样本+每后端区间正则"的**既有方法摆给 worker**
   (现在只喂了 grade_extract 检测器、没喂 worker 构造侧)。陈述式,不写"必须"。
2. **写回像记忆**:`compile_writeback`/footprint 写回时**如实标**"采样敏感/机生血统/provisional";检索
   (`compile_precedent`/`kb_footprint`)把该标记**摆进结果里**(现在 provisional 不挡检索也不显)。
   **「如实标」=按通道语义标为真,非机械把三标套两通道**(2026-07-15 reconcile 定稿,见
   `docs/forensics/reconcile_S5_footprint_provisional.md`):**precedent** 是 per-case 断言链(投毒向量)→
   标 采样敏感/机生血统/provisional;**footprint** 是 per-fact 累积的命令语法(h-不变量,单节点 verified_count
   由多 case 累积背书)→ 标机生血统(source_threads,已有)、**不标 provisional**——per-case 状态不组合到累积
   事实上;子集轮语法也真上机跑过=genuinely verified;半毒事实由 `_rollback_one` 按 device_run 锚摘条兜住;
   且经 `on_device_passed=False` 标会砸 device_verified 第二权威源拉取(28/28 skip 回归)。故 S5 落地=precedent
   三标、footprint 只标机生,已有专锚 `test_writeback_threads_provisional_keeps_footprint_device_verified` 锁死。
3. **归因自查**(并入 B 的 attributor prompt):喂事实"该成员配比×样本量≫0 但实测 Hit:0",提示它下
   `rerun_isolated` 前先核这是不是缺陷。**不加机械翻转门**。

**理论锚**:S §0.5(h-不变式断言形态——**补注**:membership/interval 两形态均**可构造**,修法是 worker 指引
非 reject-and-strand;分界判据实现落点在 attributor 自查);K §2.9.4 (45)(判例血统→写回像记忆)。
**测试锚**:`test_xlsx_lint_gates`/`grade_extract_equiv_sweep`(分布类卷不含小样本精确计数)、
`test_fail_attribution*`(配比×样本量矛盾→提示缺陷,非自动翻转)、写回标记检索可见性测试。

### B · env_blocked 误归 + F1 血统(摆事实 + prompt 自查,不自动降级)

**实证**:994986 标 E 但 fix_direction 自身说 V-reflow + `root@console` Linux 提示符(见 ① 是敲错门);
777976 同卷 `passed check point num:2` 自证伪"环境不通"(真层 V/RR 采样,归 A);572708 F1 面板把机生
`found` 前轮抬出、盖过 worker 写对的 manual-忠实 not_found。归因器 prompt 只教跨案一致性、不教**同案内**自查。

**修法(用户裁决:标记复核,不自动改判)**:
1. **attributor 指引**(`compile-attributor.md`):把**同案内一致性事实**摆进它输入——"本案通过的 check point
   数 N""回显主机提示符形态";提示它下 env_blocked 前自问"若本案有 check point 通过,环境即是通的,此结论
   还成立吗"。**不自动降级**;它若仍判 env_blocked,走**既有** escalate→用户面板(不覆盖用户已选 E)。
2. **F1 面板**(`ask_panel.py`):**去掉预设默认建议**(现在默认"跟旧结论"本身就错);手册说的、设备实际的、
   以及"这条前轮是机生的、没独立验过"三项**平摆为事实**,不给倾向。机生同族 verified **不是**期望极性的
   独立佐证(它只证设备当时那样、不证期望对错)——此纪律进 attributor prompt(陈述式)。

**理论锚**:K (40) 处置分类学(env_blocked 出口缺同案内一致性——由 prompt 自查补,非机械门);
§2.6.6 对称怀疑(冲突不构成判决→标记交裁);(45)/(45b)(机生血统不得盖人源→F1 平摆)。
**测试锚**:`test_prompt_structure`(attributor 含同案自查纪律句 + F1 无默认倾向);
`test_ask_panel`(面板 sides 平摆、无预设 recommendation)。

### ① framework 两界面事实(并入 A 的 worker 指引)

**实证**:APV 设备有两界面——产品 CLI(`E=APV_0`,`show sdns`/配置在此)与底层 Linux 壳
(`E=test_env,F=console`,`root@console` bash,无 `show`)。worker 配置用对 `APV_0`、验证却改用 `console`。
**非拓扑问题、非 V/E 之争,是缺一条事实。**

**修法**:`compile-worker.md` 补事实——"设备 show/配置命令走 `E=APV_0` 产品 CLI;`test_env/console` 是
Linux 壳、另一道门"(源:`case_ir.py:27-37` VALID_TEST_ENV_HOSTS vs APV_0;`conftest.py:437`
`APV(…,"console")`)。可选:emit 见"设备 CLI 命令(sdns/show)路由到 `test_env/console`"时**摆这条事实**
(不阻断)。**测试锚**:worker prompt 结构门含该事实。

### ③ command_existence:不修(用户裁决)

worker 自纠了、案子都过了(681811/778041 pass+writeback)。stale 台账只误导静态检视、未致失败。
**不动**。潜伏风险(clean re-emit 不清旧台账,`emit_xlsx_tool.py:677-678`)**记录留档,不修**。

### ④ broken 第三态:采纳 pyATS 七码分类(用户裁决:为完整交付)

**实证**:210998 broken 根因是写坏了(空串 host),原样 rerun 必再 broken→白烧设备轮。§18.1 broken 二值
全链已落地(gates 核验七款+测试+实证)。

**修法(用户裁决:有成熟做法就加)**:采纳 **pyATS 七码结果代数**给 broken 子分类,**只按协议级硬事实**:
- 语法拒绝符 `^`(已走既有 fail→G→reflow、不经 broken) / **window-audit `false_fail`·`false_pass`** +
  **exec-failure markers**(设备失败串,断言被对齐证据机械反证=写错了,原样 rerun 必再同错——210998 即此形:
  空串 host + 前导-`\n` 过锚 pattern,设备确有 `A Record Statistics: 1`)→ **Errored → reflow 重写交付**(不空跑);
  - **③ 执行主机错(apv 会话现非设备提示符 `root@…#`=命令泄漏到 Linux 机)→ broken-Errored 检测器【待实证·不加】**:
    dongkl 34 案零此形 broken;994986 的 console 误派是 **fail**、已由 S1(worker 通道事实)+ S2(归因自查读提示符)
    覆盖,不走 broken 路径。臆测检测器有误伤风险(合法 `root@` 输出误判→错误 reflow),按**证据优先**待真出现
    一例 broken-`root@…#` 再落(§22 纪律)。当前 ①`^` + ②window_distortion/exec-marker 已覆盖 dongkl 全部 broken 实况。
- 设备 ping 不通 → **Blocked → env 呈报**;
- 案真没跑成、好坏未知(`not_run`/`stale_log`)→ 维持 **rerun + streak 升级**(安全默认)。
分类靠硬事实、不靠 LLM 猜——与 §2.12.3b「broken 不深归因」不冲突(细分基于**物理码/机械检测器**非语义猜测;
window-audit 是确定性检测器,false_fail 确定复现→rerun 无意义、reflow 才对)。**路由用最小改动**:新增派生态
`S_BROKEN_ERRORED`/`S_BROKEN_BLOCKED`(views)+计数;errored 经 attribute 机械短路(写 disposition=reflow 不
调 LLM)→复用现有 reflow 路(**不加图边、拓扑门不动**);blocked 写机械 env_blocked 候选→ask 呈报。

**理论锚**:K (44) §2.12.3b(broken 吸收态)+ §2.13 pyATS 七码(**从"现成锚"升为"采纳"**,补注:子分类
仅限协议级硬码 Errored/Blocked,语义不明维持单态 rerun)。**测试锚**:`test_broken_third_state` 加
Errored→reflow / Blocked→env 路由;`test_window_audit` 加 210998 形态锚(空串 host + 前导-\n pattern)。

### ⑤ F1 prompt 红线:已并入 B。

### ⑥ ask-liveness 修复(2026-07-15 yzg 真机实弹;既有 bug,非本轮改动引入)

**实证**:yzg run 17 subset_verified + 2 undetermined broken + 7 awaiting_user → 引擎恒回 merge、
7 欠定案**交互 ask 面板从未触发**(基线 run25 ask answered=9,当前=0)。git 证:live-gate 活锁在 S3 前就在。

**根因(三层)**:①**理论**——(44) broken 复跑无降秩终止(见 THEORY_k §2.12.3b 2026-07-15 补注);
②**设计**——§16「批末必有聚合点」从未是**强制不变量**:`graph.py` 有 **6 条到 closing 的边绕过
`_gather_or_close`**(reconcile/run/merge 硬错误、ask 零答、bed_blocked、ask_decision 耗尽),有 awaiting_user
时静默吞;③**加剧**——broken 子集复跑改 `current_volume`→17 pass 案卷指纹失配、从 deliverable 降级回
subset_verified→live 恒 >0。

**修法(A 理论 + B 设计 + C 实现)**:
- **A(理论,已落 THEORY_k)**:undetermined broken 复跑有界(同 case 跨 reflow ≥N 仍 broken→escalated,
  一次降秩),纳入 (40) 满射,补全 liveness 三角。
- **B(设计不变量·INV-flush)**:**任何 `return "closing"` 前必先过 `_gather_or_close`**——有欠定→先 gather
  呈报;确因硬错误无法问→**显式落「因 X 未问」事实**(禁静默吞,呼应 §18.2 式③ fail-open)。机械形态=
  新 `_flush_then_close(s)` 替换 graph.py 6 条裸 `return "closing"`。**防无限环**:flush 只在**已到 closing
  决策点**触发;ask_decision→(无 pending/authored)→closing 提供终止,硬错误经一次 flush 后必收口。
  这把 §16「批末必有聚合点」从「声称」升为「强制不变量」。
- **C(实现)**:①streak per-artifact→**per-case**(跨 reflow 累计 broken/not_run,落地 A 降秩);
  ②**卷指纹隔离**(broken 子集复跑不改 delivery `current_volume`,17 pass 沉淀 deliverable 不被反复降级);
  ③B 的 `_flush_then_close` 前置门。
**测试锚**:`test_gather_ask.py`——①`test_awaiting_user_not_starved_by_persistent_broken`(C 触发)②
`test_awaiting_user_flushed_before_error_closing`(B 系统性不变量)③`test_broken_rerun_budget_terminates_per_case`(A 终止)。
**理论锚**:THEORY_k §2.12.3b(broken 终止性补注)+ (40) §2.12.1 降秩终止 + §16 批末聚合。

## 2. 直接修(无红线,无需裁决)
- **超长域名 lint**(`structural_gate.py:1097`):`_DOMAIN_TOKEN_RE` 去 TLD 白名单锚,改**裸标签扫描**
  (`dig `/`host name ` 行内任意 `[A-Za-z0-9-]` 连续段 >63 即违例,RFC 物理常量)。锚:`test_xlsx_lint_gates`
  补 no-TLD 用例(现有用例带 `.com` 所以绿着、真 bug 出厂)。
- **TUI ask_user 面板答后残留**(`ist_app.py:2171 _replay_snapshot` 漏重置 `_ask_user`):submit_answers 发
  `ask_user_answered` 事件 + reducer 复用 `_update_tool_use_status` 的 replace_content_block 样板标块已答 +
  replay 兜底重置。锚:`test_ist_app_replay_snapshot` 加已答块不复活。
- **Section B 三 TODO 标 RESOLVED**(closeout 已代码核实真 resolved):文档簿记,TODO3 正文旧推荐加一句
  "已被 re-key 取代"。
- **210998 回归锚**(见 ④测试锚)。

## 3. 团队分工(实现阶段,按文件所有权切,避免 nodes.py 撞车)

| 流 | 内容 | 主文件(所有权) | Owner |
|---|---|---|---|
| **S1 worker 指引** | ①两界面事实 + ②分布区间方法(陈述式) | `agents/compile-worker.md` | oracle |
| **S2 归因自查+F1** | attributor 同案自查 + F1 无默认/平摆 + 血统纪律 | `agents/compile-attributor.md`、`tools/device/ask_panel.py` | attribution |
| **S3 broken pyATS** | 协议码子分类 Errored/Blocked 路由 + 210998 锚 | `compile_engine_v8/{nodes(broken段),batch_tools,views,report_gate}.py`、`test_window_audit.py` | gates |
| **S4 clear-fixes** | DNS lint 裸标签 + TUI 面板 + 三 TODO 文档 | `structural_gate.py`、`ink/*`、`docs/TODO_*` | closeout |
| **S5 写回像记忆** | 写回如实标 + 检索摆标记(用前先核) | `tools/knowledge/precedent_tools.py`、footprint 写回段 | main(我)/oracle S1 后接力 |

**撞车规避**:S3(gates,nodes.py broken段)与 S5(nodes.py 写回段)分属不同函数区;**S5 在 S3 落定后接力**
(或 worktree 隔离由我合并),不并发改 nodes.py。S1/S2/S4 三流文件互不重叠,**并行**。

### 3.1 跨所有权核对成对机制(M2「半修」防再生纪律,2026-07-15 深审矩阵实弹补)

**按文件所有权切流有结构性盲区**:改**生产侧**(自己拥有的文件)时,与之**成对的消费侧/清理门**常在
**别流不拥有的文件**里——只改生产侧=半修,成对机制留在未拥有文件里过期。深审矩阵三处同型实弹:
- **S1** worker.md 重注入 `Hit:` token,而 `checker_tool.py`(S1 不拥有)2026-07-04 红线专门切除过它——**前门重注入后门清理的**;
- **S2** ask_panel.py 中性化 hypothesis,而 `engine_tool.py`(S2 不拥有)渲染层仍留默认首选项——**杀默认只到内容层**;
- **S5** precedent_tools 标 provisional,而 footprint 写回(同 nodes.py 别函数区)不标——**核对结论(2026-07-15
  reconcile):按通道语义正确区别、非半修**:precedent=per-case 断言链(投毒向量,标 provisional)、footprint=
  per-fact 累积 h-不变量语法(非投毒向量,不标),生产/消费语义**本就该不同**;标了反砸 device_verified 拉取
  (见 `docs/forensics/reconcile_S5_footprint_provisional.md`)。**真半修只有上两处**(S1/S2 生产改了消费没同步);
  S5 列此仅作核对点、结论=无需同步。

**纪律**:改任一 prompt/契约/门时,**必先跨所有权 grep 其成对机制**(生产↔消费、注入↔清理、内容层↔渲染层),
确认成对侧同步或显式声明不需同步。已知成对簿:`checker_tool.py`↔`worker.md`(设备字段 token)、
`ask_panel.py`↔`engine_tool.py`(面板契约↔渲染)、`precedent_tools`↔`footprint 写回`(判例标注,**核对结论=按通道语义正确区别、无需同步**)。
这与 §18.14「实现丢对象链」同病——都是**局部改动丢了远处成对不变式**。

## 4. 验收(用户要求:改完立即真机)
每流改完 → `/engine-verify-loop` 真机通道(cmux 起 infotest + 跳板机上机 + langfuse/fastlog 三通道)跑受影响案:
- S1/S2:593516(分布区间)/994986(敲对门)/777976(归因自查不误 env_blocked)/572708(F1 平摆)——抓归因/worker 思维链看有没有真自查。
- S3:210998(broken 走 Errored→reflow 交付,不空跑)。
- S4:994838/994869(超长域名 emit 期拦)。
- S5:写回标记检索可见、被后继案当"记忆"核。
