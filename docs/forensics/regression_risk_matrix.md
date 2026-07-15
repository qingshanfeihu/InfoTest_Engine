# 回归风险总评矩阵(2026-07-15 yzg 真机验收 + 5流×理论/设计不变式审计)

> 输入:yzg run25 真机对照(暴露 3 症状)+ 3 线索三层取证(`regression_{1,2,3}_*.md`)+
> **5 流各派独立子审计手对抗性审计(closeout 对每条 HIGH/MEDIUM 顶级发现行级复核)**。
>
> **修订裁决(closeout 深审后,取代初稿"5流全干净"判断)**:本轮 5 流引入的**新代码无直接崩溃、
> 无引擎死循环(终止性守住,S3 errored reflow 被 `rounds_used` cap 封顶)**;**3 个观察到的症状全是
> 既有 bug**(见 §B)。**但**——初稿"5 流全干净或低"**过于乐观**:5 个独立审计手揪出 **2 条 HIGH +
> ≥5 条 MEDIUM 未在 yzg 显形的回归风险**,尤其 S1/S2 各有一条 **HIGH**(初稿判"低"):
> - **S1**:`Hit:` 设备回显 token 写进 worker prompt,**逆转 2026-07-04 checker_tool 红线**;
> - **S2**:F1"去默认"只做了内容层,渲染层 `engine_tool.py`(S2 未拥有)仍留默认首选项。
>
> 二者+S4/S5 的 MEDIUM 属同一元病(**M2 半修:成对机制留在未拥有文件里过期**)。**建议初稿 A 段结论
> 按本矩阵下修**,并交用户/协调者裁 §5 修法优先级。

---

## §0. 三条元发现(最高价值)

### M1 · 3 个"观察到的回归"全是既有 bug 被新数据条件显形,非本轮 5 流引入
| 症状 | 裁决 | 真根因(既有) | 与 5 流关系 |
|---|---|---|---|
| #1 S1 过度泛化(667986 broken) | **证伪** | worker 照 attribution「逐条验 16 combos」手写 format-错配区间正则;思维链零援引 S1 分布段 | S1 非因;但 S1 有更严隐患(S1 §2 表 R1) |
| #2 ask 面板没触发 | **非 S3** | 既有 live-gate 活锁:非收敛 broken 让 `live>0` 恒真→`_after_reconcile` 恒回 merge→gather 不可达(git 证 live-check 在 S3 前就在) | S3 只改注释+加惰性项;但其「undetermined→rerun」安全默认**喂**该活锁 |
| #3 bed_gate 干净床误报 | **非 S3**(2026-07-02 起) | dev_probe 空探针 note 泄漏进 bed_check 当床残留 | S3 碰同文件 nodes.py `_probe_fn` 但不同函数区,无撞车 |

### M2 · 「半修 / 成对机制留在未拥有文件里过期」——DESIGN §3 流所有权切分的结构性盲区
按文件所有权并行切流,导致**生产侧改了、消费侧没同步**——成对机制留在**别流不拥有的文件**里过期:
- **S1** → worker.md 补分布指引,却写死 `Hit:` token;而 `checker_tool.py`(S1 不拥有)2026-07-04 红线**专门切除**该 token。前门重注入后门清理掉的东西。
- **S2** → ask_panel.py 中性化 hypothesis「去默认」,但 `engine_tool.py:214/220`(S2 不拥有)仍渲「引擎的理解」+ 默认首选项。杀默认只到内容层。
- **S5** → precedent_tools.py 给**先例**标 provisional,但 `_writeback_one` 的 **footprint 写回**硬编 `on_device_passed=True` 不标——DESIGN §A 明说 footprint 也要标。

**这是矩阵最系统的一类风险**:非单条 bug,是切流方式的结构性盲区。修法须**跨所有权边界核对成对机制**。

### M3 · §0.5 采样敏感/flaky 写回:三道**软**护栏、零硬门(设计明示,残留面真实)
finalization §A/§0 明示 flaky 写回护栏 = 「摆事实+LLM 自查+像记忆标」、**不加机械门**。这套保护**分布**在三流:S1(构造侧摆方法)+ S2(attributor 血统自查)+ S5(检索期 sampling-note/provisional)。**三道全是 C 层软护栏**。残留面:写回侧对 flakiness **零门**(593516 型 delivery-flaky pass 写成 `provisional=False` 权威判例)→ 唯一兜底=可漏的检索启发(词表召回天花板)→ worker 可无视「用前先核」照抄。**对齐真机 yzg「疑似写回回归」方向**。硬门缺席是设计选择,但三软护栏任一弱化(S1 的 `Hit:` 反例、S5 词表漏标)即塌。

---

## §1. 排序风险登记册(跨流 Top)

| # | 流 | 风险 | 等级 | 测试防护 |
|---|---|---|---|---|
| 1 | **S1** | `Hit:\s+…` 写进 worker prompt(:76,80),逆转 2026-07-04 checker_tool 红线;本 build 计数字段不叫 `Hit` 则 found 恒 fail / not_found 恒真假 PASS | **高** | 否 |
| 2 | **S2** | F1「去默认」只到内容层;`engine_tool.py:214/220`(未拥有)仍给默认首选项「确认按此继续」,中性 hypothesis 后失所指→方向欠定 brief 或逼全 Other | **高** | 否 |
| 3 | **S5** | provisional 只编码 subset/delivery、**不编码 flakiness**;delivery-flaky pass 写成 `provisional=False` 权威判例,唯一兜底=可漏采样启发 | **中高** | 部分 |
| 4 | **S3** | window-audit 残差检测器假阳,现驱动 **reflow 改写**(非无害复跑);分段错位把真 fail 判 false_fail→broken-errored→重写→cap,**真缺陷被埋成「未跑成·已改写·封顶」永不作缺陷候选** | **中** | 部分(无分段错位假阳反例) |
| 5 | **S4** | DNS lint 裸长度 `[A-Za-z0-9-]{64,}` 挂关键字门后=强字典;dig 行合法长 token(`+cookie=`/TSIG/64-hex)→误杀好卷、merge 处静默拦 | **中** | 部分 |
| 6 | **S3** | errored 绕过 streak 两轮自动止损:streak 按 artifact 计、reflow 每轮换 artifact→streak 恒 1→永不自动升级,仅靠 rounds_used cap;丢 2 轮安全网、多烧 1 设备轮 | **中** | 部分(无 reflow 反复失败终止链测试) |
| 7 | **S5** | footprint 写回 + 行为晋升硬编 `on_device_passed=True` 不标 provisional,背离 DESIGN §A;测试反把「不标」锁死为预期 | **中** | 部分(测试锁死现状) |
| 8 | **S3** | 瞬态 device_unreachable 把批内真 fail 全转 blocked→写持久 env_blocked 归因→塞 env 面板,该深归因的真缺陷被当环境止损 | **中** | 否 |
| 9 | **S2** | 同案自查「过一个 CP⇒环境可达⇒非 env_blocked」把可达性当案内恒定;时变可达(CP1 过→设备中途宕→CP2 fail)证伪→劝退真环境中断成 V 误归 | **中** | 部分(仅字符串锚) |
| 10 | **S1** | Σweights×k 手算+手写区间正则诱导 worker 旁路 `compile_expected_hits`;grr/gwrr 工具不覆盖、结构性逼手算 | **中** | 部分 |
| 11 | **S5** | 采样启发覆盖=domain_grammar 词表召回天花板(仅 rr/wrr/grr/gwrr + hit/count/counter/statistic/命中/计数);词表外静默漏标 | **中** | 部分(仅负例) |
| 12 | **S2** | hypothesis 去默认后题面须仍够判((46) 三元组);schema 不强制阻碍+最优替代→写太简、run22 同型复发 | **中** | 部分 |
| 13 | **S1** | 只补 distribution 侧构造形态,membership(⊇=abs_found 合取)对称形态缺→偏置套计数/区间(regression#1 形态) | **中** | 否 |
| 14 | **S3** | undetermined broken「rerun 安全默认」喂既有 live-gate 活锁(regression#2)——饿死欠定案 gather | **中(既有)** | 否 |
| 15 | **S4** | DNS lint 漏扫:`sdns host pool <超长>`(fixture 第24行真实存在,「host pool」≠「host name」不扫)、单词 `hostname`、续行 dig | **中/低** | 否 |
| 16 | **S3** | errored 机械归因 `layer="E"`(环境)但本质=worker 写坏(authoring),报告叙事「环境问题」自相矛盾(不影响路由) | **低** | 否 |
| — | S3/S4/S5 若干 | 见 §2 逐流表 LOW 行(footer ledger 漏 broken 三态、ist-verify 不清 provisional、teardown cancel 非对称、ANSI 注入等) | 低 | 部分/否 |

---

## §2. 逐流矩阵

> 列:`改动点 | 理论/设计锚 | 触碰的不变式 | 触发场景 | 等级 | 测试锚 | 已防住?`
> 全部为独立子审计手结论 + closeout 行级复核。

### S1 · worker 指引(`agents/compile-worker.md`)
| 改动点 | 锚 | 不变式 | 触发场景 | 等级 | 测试锚 | 已防住? |
|---|---|---|---|---|---|---|
| :76,80 `Hit:\s+3`/`[1-9]\d*`/`(2[89]\|3[0-3])` 三处设备回显 token | 红线「零写死领域命令」列 `Hit:N` 为禁;checker_tool.py:46-48/55-57(2026-07-04 移除、「never assume one spelling」) | LLM-facing prompt 不得写死设备回显 token(计数字段名=随 build 漂移的 DATA) | 任意分布案:prompt 常驻 `Hit:` salience 高于工具输出→锚它作前缀;本 build 若字段叫 `Hits:`/表格列→found 恒 fail/not_found 恒真假 PASS | **高** | test_compile_worker_distribution_interval_fact(不锚 `Hit:`、无反向禁门) | **否**——工具侧清理被前门抵消 |
| :77-80 Σweights×k 手算+手写正则未指向工具 | worker.md:67「never hand math」;checker_tool.py:12/38-45(grr/gwrr 走 else 返 error) | 计数/区间期望必过 compile_expected_hits | 诱导手推区间边界旁路工具;grr/gwrr 无工具覆盖→逼手算 | 中 | test_expected_hits_checker.py(测工具不测 worker 旁路) | **部分** |
| :73-85 只补 distribution 侧 | DESIGN §A(两形态并列);GA-CUT | membership(⊇)应 abs_found 合取、非区间 | rr 池 membership 案:偏置套计数/区间(regression#1 形态) | 中 | NONE | **部分**——确定性向 GA-CUT 护栏挡住;membership 向缺对称 |
| :87-97 两界面「no show/tests nothing」绝对化 | DESIGN §①;framework-ip-restore-contract | 事实 scope 到「配置打错门」,不否定 console 本身 | 需 test_env 观测 Linux 层态时过度回避 console | 低/中 | NONE | **部分** |
| 新增段无机械门守 §15 预设词 | §15/§0 | 陈述事实+后果+why | 本轮合规;无测试门守,后续可退化祈使 | 低 | NONE | **部分** |

### S2 · 归因自查+F1(`agents/compile-attributor.md`、`tools/device/ask_panel.py`)
| 改动点 | 锚 | 不变式 | 触发场景 | 等级 | 测试锚 | 已防住? |
|---|---|---|---|---|---|---|
| 中性化 hypothesis,但 `engine_tool.py:206-223`(未拥有)仍渲「引擎的理解」+默认首选项「确认按此继续→按引擎的理解重编」 | DESIGN §B(去默认);(46) | confirm 选项可操作性依赖 hypothesis 命名一侧(成对机制) | 任一 expectation_suspect 面板:三项平摆后「确认按此继续」无「此」可确认→方向欠定 brief/逼全 Other | **高** | NONE | **否**——§3 分工把 S2 限在两文件,渲染层未纳入 |
| attributor.md:63-68 「passing CP⇒environment reachable⇒env_blocked does not hold」 | K (40)env_blocked 出口;§2.6.6 | 把可达性当案内恒定;时变可达性证伪 | 多 CP 案前段过、设备中途真宕致后段 fail→自查劝退真环境中断成 V 误归 | 中 | test_compile_attributor_same_case_selfcheck_anchor(仅字符串锚,未覆盖 mid-case env-drop) | **部分**——逃生话术在但类别式措辞偏强 |
| :74-77「no auto-downgrade」散文 | DESIGN §B、§0 | 不得存在基于 CP 计数的机械翻转门 | diff 仅散文;env_blocked→signal→env ask,用户 override | 低 | test_eval3_cap_*;diff 零机械门 | **是**——未引入机械翻转门 |
| ask_panel:71-81 hypothesis 契约去默认 | DESIGN §B;(46) | 去默认后须仍够判——(46)⟨R,阻碍,最优替代⟩完整 | 三项写太简→用户信息不足、三问无解(run22 同型) | 中 | test_hypothesis_field_no_preset_default(仅查措辞) | **部分**——不强制(46) 三元组 |
| :119-126 血统纪律「manual...does not outweigh it」 | K (45)(人源不自动赢) | 只否定机生独立佐证,不得升「人源自动赢」 | 误读为「手册赢」→少数极性争议偏手册 | 低 | test_compile_attributor_bloodline_anchor | **部分**——净语义对齐,单句表面张力靠下文化解 |

### S3 · broken pyATS 七码(`compile_engine_v8/{nodes,graph,views,state,_shared,render}.py`、`batch_tools.py`)
| 改动点 | 锚 | 不变式 | 触发场景 | 等级 | 测试锚 | 已防住? |
|---|---|---|---|---|---|---|
| **R1** batch_tools:806-807 `_dist∨_anom→errored`→views→author reflow | DESIGN §④;§2.12.3b(物理码非语义) | 检测器**假阳**现被当协议硬事实驱动**改写**(非公理);`_apv_blocks`(953)分段/`seen[src]`(1015)配对对畸形回显脆弱 | 分段错位(缺/畸形 prompt 行致邻块 pattern 并入)→真 fail 判 false_fail→broken-errored→重写→反复→cap;**真缺陷被埋成「未跑成·已改写·封顶」永不进缺陷候选** | **中** | test_false_fail_statistics_empty_host_210998(仅真阳,无分段错位/echo 误配假阳反例) | **部分**——`_apv_blocks` 剥了 echo 误配;分段错位/多块配对假阳无门,且「判定即改写」无回退纠偏 |
| **R2** author:345-358 S_BROKEN_ERRORED 入 reflow 闸;streak(1001-1005)按 artifact 计、被 reflow 换 artifact 击穿 | THEORY (44) broken 连击护栏;§④ | errored 走 reflow 不得丢自动止损 | worker 反复写坏同 case→每轮换 artifact→streak 恒 1→永不自动升级→烧满 3 轮→cap 问询;pre-S3 plain broken 2 轮即 escalated | **中** | test_errored_broken_not_counted_by_frozen(未测 reflow 反复失败 streak/cap 终止链) | **部分**——rounds_used cap 保证有界(非死循环),但丢 2 轮止损、多烧 1 轮 |
| **R3** reconcile:1044-1057 errored 写 `layer="E"` | DESIGN §④;render LAYER_CN["E"]="环境问题" | errored=worker 写坏(authoring),layer=E(环境)叙事与处置(reflow)自相矛盾 | 210998 型在 delivery_report 显「环境/测试床问题」,用户误判为环境非编写缺陷 | 低 | NONE | **否**——layer 不参与路由(靠 disposition=reflow),仅报告措辞错 |
| **R4** 两派生态在 live 不在 merge.ready(737-747) | §④;终验整卷路由(zhaiyq §18.1) | `set(need_verify)==set(live)` delivery 触发在这类案存活期恒不成立→终验推迟;`_after_author` 因兄弟 subset_verified 短路 merge 先于 cap/env 检查 | 批内多数 pass+1 capped-errored/blocked→额外 merge/delivery 轮,cap/env 问询浮现被推迟(churn 非死循环) | 中 | test_reconcile_blocked_writes_env_and_surfaces(未测混合批 live/ready 错配推迟) | **部分**——最终收敛浮出,churn/延迟无测试 |
| **R5** batch_tools:819-828 device_unreachable→所有非 pass 案 `blocked` 覆盖 errored + reconcile 写持久 env_blocked 归因 | DESIGN §④;THEORY (30) 承载链第零层 | probe 仅有 fail 时触发,瞬态丢包→真 case 缺陷 fail 也全转 blocked | 瞬态丢包恰落 probe 窗→真 fail 与真受害者一起标 blocked→全进 env 面板;pre-S3→rerun 下轮恢复,S3 新增持久 env_blocked fact 更黏 | 中 | NONE | **部分**——env_blocked 经 ask 用户可 retry 推翻,但机械归因 fact 跨轮留存+批级全转粗粒度 |
| **R6** failopen:未识别码→S_BROKEN plain→rerun+streak(806/828/115-120/1030) | §④;§2.12.3b | 未打/未识别 subtype→安全默认复跑,不误入 reflow/env | N.A.(安全默认正确) | 低 | test_fold_broken_no_subtype_stays_plain_broken | **是**——digest/views/reconcile 三处全 fail-closed 到 plain broken |
| **R7** broken 不计签名+不污染 common_cause(facts.py:154-170 filter broken@163;attribute/diagnose 仍限 S_FAILED) | THEORY (44) | frozen 过滤 broken-errored→不误 frozen;s₀/common_cause 仅 S_FAILED→不进聚类 | N.A.(正反向都守) | 低 | test_errored_broken_not_counted_by_frozen | **是**——**closeout 开放问已解**:facts.py:163 filter broken,errored 不 frozen-loop |
| **R8** 报告分母三子态求和(render:234-235;Counter 自动含新键) | §④;report_gate 一致性门 | 三子态 disjoint 不重计;total 含之、ok 不含之 | N.A. | 低 | fold 测试保 status 计数 + report_gate 现有门覆盖新键 | **是**——求和正确,一致性门自动覆盖 |
| **R9** TUI footer ledger 漏 broken 三态桶(`_shared.py:emit_tick:270-281` 未改) | CLAUDE「九个 ledger 状态全归属」 | footer 子计数之和<total when broken 存在 | capped-errored/blocked 持久存活时进度条子计数和≠total | 低 | NONE | **否**——pre-existing gap(plain broken 本缺映射),S3 延伸 2 态未修 |

> **S3 终止性总结论(auditor + closeout)**:**无引擎死循环**。errored reflow 环严格被 `rounds_used ≥ max_rounds+granted_rounds` 封顶;blocked/capped 经 env/cap 问询浮出,未答→`_after_ask_contradiction` 收 closing。`all_settled`(views.py:155)定义但**全仓无消费者**,故两派生态不在 settled 集不构成死锁。errored/blocked 归因 `mechanical=True`+`round≠99`→`_user_sourced`(仅 round==99)正确判非用户来源、不误升 S_TERMINAL。
> **测试锚勘误**:`test_failopen_semantics.py(+40)` 实锚 **S5**(provisional 写回 + footprint device_verified),非 S3;`test_facts_invariants.py`/`test_graph_scenarios.py` 的 +2 是 `_writeback_one` 签名跟随。S3 failopen 真锚=`test_fold_broken_no_subtype_stays_plain_broken`。

### S4 · clear-fixes(`structural_gate.py`、`events.py`、`ask_user/__init__.py`、`reducer.py`、`ink/ist_app.py`)【独立审 closeout 自己的工作】
| 改动点 | 锚 | 不变式 | 触发场景 | 等级 | 测试锚 | 已防住? |
|---|---|---|---|---|---|---|
| `_check_dns_label_limit` 裸长度 `[A-Za-z0-9-]{64,}` 挂关键字门后,无标签语义校验 | 准则6「结构化事实非强字典」;GA-CUT | 「dig 行任意 64+ alnum 串=超长标签」是强模式,误判非标签长 token | dig 行含 `+cookie=<80hex>`/`-y hmac-sha256:k:<base64>`/64-hex(DKIM/长TXT)→误报→emit_merged 拒合并、好卷被切、merge 处静默 | **中** | test_lint_dns_normal_multilabel_domain_clean(仅守多标签,不守长非标签 token) | **部分** |
| 漏扫:扫描行被 `\bdig\b\|\bhost\s+name\b` 圈死 | DESIGN §2 | DNS 63 应对所有承载 DNS 名的命令生效 | `sdns host pool <148字符>`(fixture 第24行真实存在,「host pool」≠「host name」不扫)→超长标签绿着出厂(994838 痛点平移);单词 `hostname`/续行 dig 同漏 | 中/低 | NONE | **部分**——定义站点 host name 被扫有缓解;纯 host pool 漏 |
| 门挂点仅 `lint_xlsx_case:1164`,不在 `check_crash_gates_mandatory` | 「门挂凭证路不挂编辑路」 | DNS 检查须覆盖凭证路 | compile_emit 落 `.grade_credential.json` `lint_ok:True` 时**未跑** DNS;合并时 lint_xlsx_case 补拦 | 低 | test_emit_merged_rejects_lint_violation | **部分**——成品经合并门补拦(受保护);「emit 凭证门也覆盖 DNS」前提**不成立**=merge-gate 非双卡点 |
| events +ask_user_answered;submit_answers emit;reducer in-place replace_content_block | TUI 事件契约(无穷举 match 崩);重放一致 | 新 EventKind 不崩别 sink;in-place 不破 keyed reconciliation | 全仓无 `match/case _:raise`;reducer if/elif 无 else(未知 no-op);TuiSink try/except;replace 保 uuid+消息数;live 位置切片 append-only 故改既有块 live 不重渲 | 低 | test_ask_user_answered_{marks_block,unknown_qid_noop} | **是**——事件契约干净 |
| answered 分支渲摘要 vs live `_finish_ask_user` result_summary | 不双摘要 | 增量+replay 各来一条 | replay 先 clear() 再补 answered 摘要;live 摘要是 raw append 非 snapshot、replay 被清→不可叠 | 低 | test_replay_answered_ask_user_does_not_resurrect_panel | **是** |
| `_replay_snapshot` 兜底 `_ask_user=None`+清面板 | 未答态重放不误清在途 | 答题中触发 replay 清活跃会话 | **不可达**:handle_key 末行 `return True` 吞 ctrl+o/t;resize→render() 只重绘;`_replay_snapshot` 仅 toggle 调、均在 `_ask_user is None` 才触达→兜底是防御冗余 | 低 | test_replay_unanswered_ask_user_still_shows_panel | **是**(误清不可达);附:未答块 replay 重建 fresh session 丢在途多题选择是**既有**隐患、S4 未引入未修 |
| `cancel_all_pending`(teardown)只 evt.set() 不 emit answered | 问/答/取消都进 snapshot | 取消须标 answered 否则 replay 复活 | 面板 cancel 对称;teardown cancel 非对称→该块永不标→teardown 后 replay 复活(罕见) | 低 | NONE | **部分** |
| `_ask_user_answered_summary` 插答案原文进带 ANSI 单行 | user-facing 完整性 | 答案含控制序列破坏渲染 | Other 文本含 `\x1b`/`\n`→破单行/注入(与既有 result_summary 同源) | 低 | NONE | **否**——既有问题沿用未处理 |

> S4 关键锚:DNS 检查**仅** `structural_gate.py:1164`(不在 `check_crash_gates_mandatory`);实际卡点=`emit_xlsx_tool.py:1760`(emit_merged)+`:1640`(precheck)。旧 `_DOMAIN_TOKEN_RE` 全删无悬空引用。`infotest`→IstInkApp,BLOCK_ASK_USER **仅** ink/ 渲染,**无第二个 Textual 未修渲染器**——S4 覆盖默认路径,无「只修一半」前端缺口。

### S5 · 写回像记忆(`tools/device/precedent_tools.py`、`nodes.py` 写回段)
| 改动点 | 锚 | 不变式 | 触发场景 | 等级 | 测试锚 | 已防住? |
|---|---|---|---|---|---|---|
| compile_writeback +provisional;nodes:1079 `provisional=(ctx!=CTX_DELIVERY)` | S §0.5;DESIGN §A;K (45) | 采样敏感 flaky pass 不得写成非 provisional 权威源;provisional 与 flakiness 正交 | 593516(wrr)`Hit:\s+3` **delivery 轮** flaky-pass→verdict=pass 过门→`provisional=False` 写权威 mirror+index,仅结构 note 兜底 | **中高** | test_sampling_note_shown_for_distribution_hitcount(无 flakiness×delivery 用例) | **部分**——设计明示零机械门,写回侧零 flakiness 门 |
| nodes:1149 footprint 硬编 `on_device_passed=True`+:1156 无条件 `_promote_behavior_candidates`,均不接 provisional | DESIGN §A(footprint 也标);K (45) | footprint(device_verified 第二权威)也应标 provisional | 子集 flaky pass→footprint G 段语法+**行为候选晋升**入库零 flaky 标→后续 worker kb_footprint 当铁证 | 中 | test_writeback_threads_provisional_keeps_footprint_device_verified(断言 odp 恒 True——把「不标」**锁死为预期**) | **部分**——纯语法论据成立,**行为晋升**同路无区分;背离 §A 文字且测试锁死 |
| _format_precedent_hits:456 provisional/sampling note=append 一行、`is True` 显、非 filter | DESIGN §A(不挡检索也要显) | provisional 不得过滤先例出结果 | provisional 案被排除 | 低 | test_provisional_roundtrip_and_surface + test_provisional_absent_when_not_recorded | **是**——append 非 filter |
| _precedent_sampling_note:353 覆盖依赖 domain_grammar 词表 | S §0.5;DESIGN §A | 采样敏感断言须随结果摆出——词表外漏标 | 分布/计数用词表未收录词(新别名/英文变体)→note 不触发→flaky 判例静默入库无警示 | 中 | test_sampling_note_absent_without_distribution(仅负例,未测召回广度) | **部分**——词表可扩展(架构对),当前覆盖=召回天花板 |
| 检索文案「verify first / not an authority」prompt 级、无机械阻断照抄 | K (45)/(45b) 防自指;§0 | 自产判例无独立审计不得成后续主导输入 | worker 无视「用前先核」照抄判例断言链当金标准 | 中 | test_engine_lineage_shown_in_text / test_polarity_ban_wording_present(只测「文案在」不测真核) | **部分**——文案=C 层软护栏;唯一结构护栏=(45b)配额保底(本轮未动仍在) |
| ist-verify SKILL.md:112 compile_writeback 不传 provisional(→None→不记录) | DESIGN §A | 独立 ist-verify 整卷过后应能清引擎先写的 provisional=True | 引擎子集过写 True→改用 ist-verify 整卷过→provenance 永久残留 True→先例长期误显「用前先核」 | 低 | NONE | **部分**——引擎内 delivery 轮重写 False 覆盖成立;跨 ist-verify 不覆盖 |
| compile_writeback:684 provisional 记录在门①②之后 | CLAUDE 机械门;§0 | verdict==pass+凭证新鲜两门不得被绕 | 尝试用 provisional 绕 pass 门 | 低 | test_compile_writeback.py | **是**——provisional 是记录非门,门顺序零改 |
| `_rollback_one`(delivery fail 删 mirror)不清 provenance json | DESIGN §A(半毒回滚撤旁挂) | 回滚撤先例后 provisional 旁挂应一并撤 | delivery fail→删 mirror,provenance 留 stale entry | 低 | NONE | **部分**——无害残留(无 mirror 则无命中挂靠;同 aid 重写覆盖),orphan 累积 |

---

## §3. 跨流交互风险
| 交互 | 结论 |
|---|---|
| **nodes.py 撞车(S3 broken 段 × S5 写回段)** | **干净**。分属不同函数区(reconcile:1016-1065 vs 1076+/`_writeback_one`);errored/blocked 走 reflow/env 不入 pass 写回集。`_writeback_one` 签名变更全部调用点已核(生产 1+测试 13)。共享 `fs2` reload 顺序正确。 |
| **S3 undetermined broken × 既有 live-gate(regression#2)** | S3「undetermined→rerun」安全默认**喂**既有 live-gate 活锁。S3 对 errored/blocked **改善**(移出 n_broken),undetermined 面未解。修需 liveness 守卫(per-case streak / broken 复跑轮次封顶),根因既有(见 §B #2)。 |
| **S3 blocked-env × S2 env_blocked 自查** | 不同路径。机械 blocked(ping loss 协议硬)应权威于 S2 LLM 自查启发;风险仅在 broken_subtype=blocked 误标(瞬态,S3-R5)。 |
| **§0.5 三流软护栏(S1 构造+S2 自查+S5 标记)** | 三流**同向**(均「机生=结构/先核、非期望权威」),检索三标叠加。但全 C 层软护栏零硬门,任一弱化即塌向 §0.5 活违反(M3)。 |
| **M2 半修盲区(S1→checker_tool / S2→engine_tool / S5→footprint)** | 三处同型:生产侧改了、成对消费/写回点在别处未同步。**切流方式的结构性风险。** |

---

## §B. yzg 暴露的 3 个既有 bug(非本轮引入,但卡死"完整交付")— 保留初稿理论分析

### #2 ask 面板没触发 —— **理论缺口(最重)**
- **实证**:reconcile 恒回 merge(live=17 subset_verified+2 broken>0),gather→ask 永不可达→7 欠定永不被问。加剧:broken 子集复跑换 current_volume→17 pass 卷指纹失配降级回 subset_verified→live 两头卡死。git 证 live-gate 在 S3 之前就在(S3 只改注释),非 S3。
- **理论层根因**:(40)§2.12.1 fail 七类处置有**降秩终止证明**(→live 必归零→gather 必触发);但 (44)§2.12.3b broken 吸收态(07-13 晚补)**只给局部语义、无降秩终止证明**(复跑 not_run 还是 not_run,秩没降)。**(40)↔(44)↔"欠定必问" liveness 三角不完整**(C14 型:自推 (44) 没回头延伸 (40) 终止性)。
- **设计层**:DESIGN §14-R4「不可接受=整批停中间态」+§16「批末必有聚合点」——yzg 踩 R4;但"批末必有聚合点"**从来不是强制不变量**。
- **系统性**:graph.py 到 closing 有 **6 条边绕过 `_gather_or_close`**(reconcile error/run 非 ok/merge else/ask_contradiction 零答/bed_blocked/ask_decision 耗尽)。broken 只是一个触发器,n_failed 不收敛/设备 busy/last_run 断裂同样吞欠定。**洞比 broken 宽。**
- **修法(A+B+C)**:A 理论=给 undetermined broken 补降秩终止(复跑预算耗尽→escalated,未决−1)纳入 (40);B 设计=「flush awaiting_user before closing」立真不变量(所有 `return "closing"` 前置 `_gather_or_close` 门,有欠定→先 gather 或落"因硬错误未问"事实禁静默吞);C 实现=streak 改 per-case+卷指纹隔离。

### #3 bed_gate 干净床误报"分区配置残留" —— **实现丢对象链(§18.14 同病)**
- **实证**:bed_before 装的是 dev_probe 空探针的兜底 note 文字(`_annotate_if_empty_probe`),被 bed body 过滤器当"外来配置对象"。git 证既有(2026-07-02,probe 段零改动),非我们。
- **根因**:理论要求谓词"床上存在非己方脏配置**对象**",实现退化成"探针 body**文本非空**"(bed.py:562 自白)。与 §18.14 s₀ 排固定 IP、[[bed-baseline-face-no-autorestore]] 同型(床态谓词吞非对象 artifact)。
- **定级**:MAJOR-可用性、**非 BLOCKER-安全**(note 零身份 token→派生不出删除命令,不会毁床)。但每批误报→告警疲劳掩盖真 T4 残留。
- **修法**:A 分离关注点(`_do_probe(annotate=False)` 给 bed 路,零关键字匹配)。

### #1 worker 假设格式不 grounded —— **π 忠实/oracle 残差 gap(既有 worker 型)**
- **实证**:667986 worker 手写端口范围正则、假设 `IP\s+port` 布局、**没 dev_probe 现验实际 show 格式**就写→对不齐 broken。langfuse 证 worker 没用 S1 分布段(S1 无罪)。归因 fix_direction"逐条验证"驱动。
- **根因**:worker 构造侧未把断言 grounded 真实回显(observe-then-assert 的反面:assume-then-assert)。
- **修法**:worker 指引补"容量/存在性/枚举类先 dev_probe 现验 show 格式再写、用逐条成员 abs_found 不用假设布局范围正则"(与 S1 §2 表 R1/R3 收紧同处落)。

---

## §C. 元观察
3 个既有 bug 全是**"实现/理论丢了不变式"**——bed(文本代理丢对象谓词)、ask(丢 broken 终止性)、worker(丢 π 忠实 grounding)。**与本轮 dongkl 遗留工作修的 §18.14"实现丢对象链"是同一类病。** yzg 验收挖出更多同型实例,尤其 #2 是真理论缺口(该走理论层修,非打补丁)。

**5 流审计追加的元观察**:本轮 5 流的**未观察风险**也高度同型——M2「半修:成对机制留未拥有文件」(S1→checker_tool / S2→engine_tool / S5→footprint)与 M3「§0.5 三软护栏零硬门」都是"改了一处、成对/兜底机制在别处过期或缺失"。**与 §18.14 同病、与上述 3 既有 bug 同病。** 即:切流方式(§3 文件所有权)本身复制了这个病。

---

## §D. 待用户/协调者决策
1. **初稿"5流全干净"下修**:S1/S2 各有 HIGH(§1 #1/#2),建议按本矩阵定级。
2. **3 既有 bug**(既有、超 dongkl 范围,但卡死"完整交付"),#2 尤其要理论+设计+实现三层(A+B+C)。
3. **§5 修法优先级**(下)修不修、修哪几个、按什么节奏——待定。
4. **元病(M2/M3)是否系统治理**:若只逐条补 §1 各风险而不改切流"跨所有权核对成对机制"的纪律,同型半修会再生。

## §5. 修法建议(只读阶段;陈述式/结构信号/摆事实,零写死领域命令)
1. **S1-R1(高,先修)**:worker.md 去 `Hit:` 前缀→`<count-field>\s+(lo…hi)` 骨架或叙述「前缀从 compile_expected_hits + 先例/手册核实拼装」;补反向禁 `Hit:` 门;跨文件对齐 checker_tool.py:55-57。
2. **S2 F1(高)**:把"去默认"推到 `engine_tool.py:214/220`——confirm 选项改不预设方向(或按平摆三项让用户选侧);补 confirm↔中性 hypothesis 一致性测试。
3. **S5 footprint(中)**:`_writeback_one` 把 provisional thread 给 footprint/行为晋升(至少行为晋升要标);改锁死测试。
4. **S4 DNS(中)**:裸长度加**标签语义校验**(只量点分域名 token 的单标签)+ 扫描面用**结构信号**(域名 token 形态)非命令关键字白名单(治误伤+漏扫);补长非标签 token clean + host pool 违例用例。
5. **S3-R1/R2(中)**:window-audit false_fail→errored 加「改写后仍 broken 则回退归因」纠偏环(避真缺陷被埋);errored streak 改 per-case(跨 reflow 累计)恢复 2 轮止损。
6. **S3-R5(中)**:device_unreachable 批级全转 blocked 加"复探确认非瞬态"或按案区分(真 fail vs 真受害者)。
7. **S3×live-gate(中,既有,=§B #2 的 C)**:liveness 守卫(per-case broken 复跑封顶→escalated 移出 live);落 `test_awaiting_user_not_starved_by_persistent_broken`。
8. **S5 flakiness(中高)**:sampling-note 也纳入 delivery-flaky(不只 subset),或 provisional 增第三态"sampling-sensitive"。
9. **S2 同案自查(中)**:"过 CP⇒环境可达"加时变限定,避免劝退 mid-case env-drop。

STATUS: done
