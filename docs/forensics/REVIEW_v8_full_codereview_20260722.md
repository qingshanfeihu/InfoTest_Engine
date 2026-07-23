# V8 引擎全量 code review(2026-07-22)

> 分支:`fix/dongkl-finalization-yzg-regressions`(含工作树未提交的 de-escalate 通道改动,以盘上现状为准)。
> 范围:`main/ist_core/compile_engine_v8/` 17 文件 7665 行 + 权威文档 5 份 4780 行 + `tests/ist_core/compile_engine_v8/` 40 文件 7697 行。
> 方法:先从 THEORY(K/S/I)+ DESIGN(D/F) 提炼 90 条机械可核 rubric(`workspace/tmp/v8_review_rubric.md`),再 12 路并行评审(nodes.py 四块、questions、facts+views+report_gate、_shared+state+graph、render+remedies、bed+uncertain+mirror+persistence、briefs+engine_tool、测试域、文档一致性专项),每条发现均核实到代码证据。
> 分级:阻断=错判/丢案/死循环/谎报/安全越界;高=逻辑错误路径现实可达;中=边界条件/一致性/账目失真;低=残渣/注释漂移。
> 去重:多路独立命中同根因的合并为一条(注明双确认);与 de-escalate 盘面核验(同日上午)已登记项不重复开单,仅在「在册项」节索引。

---

## 一、阻断(3)

### B-1 run() 把陈旧 last_run.json 当本轮产出——旧 pass 可背书未上机的新卷面交付
`nodes.py:1204-1213`:`lr` 只查存在性不查新鲜度。delivery 卷跨轮同目录(`vol_name = out_name`,:1112),上轮 last_run.json 批内存活(closing 才删);digest 对非 list 结果(设备失败/ssh 错/partial dict)早退不写文件(`batch_tools.py:1197-1203`),错误串不含三个已知标记时(:1200)穿透存在性检查 → reconcile 把**上轮记录**以新 run_id 重录;且 verdict 入账的 `artifact`/`volume` 全取**当前**值(:1264)——重编过的案,旧 pass 被盖到新卷面新组成上,deliverable 三重匹配(R013)全绿,**没上机的卷面被交付**。违 R006/R028。修法:digest 失败=error 硬停(与文件存在性解耦),或校验 last_run mtime ≥ 本轮 merge 时间。

### B-2 终验幂等闸吸收复跑处方——rerun/transient 被静默吞,事实死循环
`_delivery_verify_skippable`(`nodes.py:959-976`)否决集不看组成内是否有待复跑的 S_FAILED/S_CONTRADICTED 案。可达链:attribute 落 rerun_isolated/transient → author 不重编(:461「由 merge 复跑」)→ `_after_author` 按处方路由 merge → need_verify==live 时 comp/artifact 全同 → 闸吸收 → nothing_to_merge → closing。前提「need_verify==live」在单案批/全案 transient 批/全案首 contradicted 自动回环三种现实场景成立;吸收后零状态推进,下批同路径再吸收。设计原文(§16.4:866)自证闸意是吸收**零信息重跑**,复跑处方恰恰非零信息。违 R019 设计意图、R051(处方复跑先于 ask)。修法:闸追加「comp 内每案最新 delivery 裁决皆 pass@本 volume」条件。

### B-3 closing 床恢复重 diff 无己方过滤——foreign 记入床账,下批自动删非己方配置(INV-9 越界)
`nodes.py:2967-2980`:恢复命令执行后 `restorable_diff(bed_diff(before, 重拍))` 是全量重 diff,foreign(案面未创建)物理仍在设备上必在新 diff 里;随后 `for name, d in residual.items(): bed_record(..., "created", ...)` 把 foreign 记成**本引擎产物**(对比 `elif own:` 分支有 `if k in own` 过滤,`if cmds:` 分支漏了)。下批 bed_gate 接力对无预存命令账项走 LLM 生成+entity_gate(allowed 集来自账项自身,自指恒过)→ 自动删非己方实体。触发条件极宽:本批执行过任意恢复命令且同期存在任意非己方漂移(他人同床操作即满足)。次生错:residual 恒非空 → `verified` 恒空 → bed_note 谎报「复探未清零」。违 R069/R070/R071。

---

## 二、高(21)

**ask/问询族**

- **H-01 env 重问 qid 碰撞,env_blocked 再判断永不呈报,案卡死** — `_shared.py:131`:qid=`env:{aid}:{round}`,round 三处都写 `F.rounds_used`;retry 不重编→rounds_used 不推进→再判 env_blocked 时 qid 同前→判「已答」永不重问;且 decision 幂等键同 qid,强行再问答案也被静默吞。案 latest=env_blocked(非人源):author 跳过、merge 不收、不在等待集,但 `n_failed_actionable` 算它有活→每批空转进 merge 直到闸吸收,收口 failed,**跨批永远不再问**。deesc_qid 文档记载并修好的同款病,env 族没修。R045/R055。
- **H-02 blocked 子类 env 题答 retry → 复跑指令被静默吞(僵尸案)** — `_shared.py:117-134`+`nodes.py:1016-1018`:retry 落 rerun_isolated 归因,但 case_status 只看 verdict 的 broken_subtype,案仍 S_BROKEN_BLOCKED——不在 merge ready 集、不在 author 集、不计 actionable、不再 waiting。四向全关,用户复跑指令零执行零告知。R023。
- **H-03 cap_waiting 无 settled 过滤 → 终态案被反复问 cap;auto-suspend 可把 user_stop 翻转成 suspended** — `_shared.py:87-98` 不看 vw 状态(对照 panel/env/bed 均有排除);①被影子化的 cap_reached 永无 decision;②用户另题答 stop→user_stop 终态;③cap_waiting 仍命中→每批出 cap 题;④非交互 auto-suspend 只排 kind=="suspended" 不查案状态→落 suspended;⑤`case_status` 里 `_is_suspended` 先于 r99 终态判定(views.py:94)→ **failed_terminal 被翻成 suspended**,用户止损终局被安全件静默推翻。R017/R051。
- **H-04 共因合题跨 kind 折叠,挂起组员恢复答案被吞** — `nodes.py:2478-2494`:bed 与 suspended 同键合组;广播(:2502-2505)后 suspended 组员按自身路径消费,组长答 retry 时组员只落 attribution rerun_isolated、**不落 resumed**——`_is_suspended` 不解除,下批以新 qid 重问同一批案。run14/15 同因多案恰是目标场景。既有折叠测试只锁同 kind。
- **H-05 header 唯一性无保障,同批同 header 裁决跨组串线**(双确认)— `nodes.py:767` 折叠组 header 统一 `欠定·组{N}案`(同批两个同规模组恒同,非概率)+ questions.py 各分支 `aid[-4:]` 尾号可撞;`_panel` 按 header `_re.search`(engine_tool.py:44),两题同 header 都命中第一处 → B 案拿到 A 案裁决落 decision+写回判例;先问后落门拦不住(folded_members 批级并集同含两组)。R048/R046。
- **H-06 answer_token 否定盲区,一批「不/别」式自由输入被语义反转执行** — questions.py 除缺陷意图外全部裸 `in` 匹配:「不接受单跑/不降级」→downgrade(落 user_stop 丢案,:580);「确认环境没问题」→stop 落 env_blocked(:570);「不要挂起/不要停止」(≤8字)→suspend/stop(:551-554);「先别恢复」→resume(:548);「别再修了」→continue 授权+2(:564);「别复跑」→retry(:576)。G4 echo 只能让用户看见误读,decision 已落账执行。R048/R049。
- **H-07 panel confirm 残留臂与中性化设计矛盾,无决断「裁决」可跨批采信** — `questions.py:557-559`:自由输入含「确认/按此」→confirm;但 :733-736 注释记载 panel 已中性化、选项刻意去 confirm。confirm 落判例 ruling=中性 hypothesis,`_try_adopt`(nodes.py:1553)对 {confirm,correct} 跨批机械采信——无决断内容的「裁决」以 user_proxy 血统入库后自我复制,污染 K_ought。
- **H-08 ask_decision 消费链无「挂起/停止」常驻特权** — R049「任何面板可敲」;欠定通道(nodes.py:836-850)无特权词分支:forbidden_mechanism 面板答「挂起/停止」→静默落 改过程(scheme 下发 worker=错判);generic 类面板答「挂起」→不落、每轮 gather 重问(死循环形态)。
- **H-09 cap qid 碰撞:cap 题挂起→恢复后永不重问,题面承诺被打破** — `cap_waiting` qid=`cap:{aid}:{round}` 与 ask 侧一致,但答「挂起」占用该 qid 后 rounds 冻结(封顶案不再派发)→decision 已存在→永不再问;而选项文案承诺「重跑同参数时会再次询问」(questions.py:761)。案 FAILED+封顶被当「有活」直送 merge 搭终验,永失「继续再修 2 轮」机会。`_needs_decision_qid` 已换 decision-count 判别子解决同款,cap 未换。

**bed/床族**

- **H-10 bed_gate 清理复检把已并入的呈报发现整体丢弃** — `nodes.py:236-264` 把 mirror_sync 失配、stuck_ledger、bed_closure_failed 并入 `rep` 置 needs_ask;`:303-307` 清理成功后 `rep = B.bed_check(...)` 整体重赋值,三类发现蒸发;复检干净则不 interrupt——用户永远看不到。ledger_stuck 的 interface 漂移按自身注释不在 bed_check 判定内,复检不会重现。违 R075/R069/R006③。
- **H-11 bedclosure 配对 qid 永不产生 → 旧收敛失败每批重复呈报** — `nodes.py:256-259` 找 `question_id=="bedclosure:{run_id}"` 的 decision;全仓无此 qid 写入方(interrupt 落账固定 `"bed_gate"`,:316),且 bed_closure_failed 事实无 run_id 字段(:3001-3003)→配对键恒 `"bedclosure:"`→每批续跑拦路重问同一陈年告警,怎么答都消不掉。R045+收敛律。
- **H-12 bed_gate Other 自由文本「继续」子串判 proceed → 意图反转** — `engine_tool.py:150`:`"proceed" if "继续" in v`;「不继续」「先别继续,我去清床」均含子串→在床态不明/有残留时照跑。INV-9 床权在用户,引擎替用户决定「接受残留照跑」。R069。
- **H-13 bed_check `if foreign and not ours` 静默门:非己方残留永不 needs_ask 的永久路径** — `bed.py:575`:接力对 snapshot_only 纯 added 历史账项「留账不动手」(R073 要求)使其永不消账→ours 恒非空→此后该 host 任何非己方残留都不再 needs_ask,INV-9 被永久关闭,findings 只落 facts 无面板。R069。
- **H-14 bed_gate 接力恢复无执行后复探** — `nodes.py:211`:ok 判据仅 echo 无错误标记,不复探确认漂移清零;R072 对 LLM 后备要求双门(entity_gate+复探,closing 侧有接力侧无)。snapshot_only 通道不在残留探针集(bed.py:536 排除),恢复错配=漂移永久无痕;且 restored 账项 payload 注释称「已验证」实际未验证,下批机械回放。R072。

**事实流/状态机族**

- **H-15 reconcile run_id 盐=len(历史 verdict 数),崩溃重放(INV-10 窗口)双写并连锁误判**(双确认)— `nodes.py:1248`:append 后 checkpoint 前崩溃→重放计数已涨→run_id 变→同批裁决以新键重复入账。已核实后果:`frozen()` 对同 aid 相邻双拷贝误判「连续两 fail 同签名」;`contradictions()` 双计→跳过首次自动回环直接 ask;writeback 判重失效双执行;streak 双计→单次 broken 重放后误升级 escalated 触发 deesc_auto_resolution(谎报)。merge 侧已用 checkpointed seq 解决同问题(:1120-1121),reconcile 未采用。R005。
- **H-16 G3 封堵案跨批复活为 deliverable,limbo 循环 + 派生视图外第 13 状态**(双确认)— `nodes.py:3032` 手改 `vw` 写 `"delivery_blocked"`,但 `case_status`/`F.deliverable` 都不消费该事实:下批续跑派生回 S_DELIVERABLE→终验闸跳过→closing 再封堵→循环;emit 承诺「重编补自清后可交付」但无路由回 author、无 ask;且每次 `view()` 重算标签即丢失,计数面自相矛盾。report_gate.py:76 反而 honor 它——两路不对称恰是 R015 所禁。R031/R053。
- **H-17 _resume_reopen_needs_decision 对 auto:{panel,cap} 挂起重开数据源错配 → F1 ought 欠定未答流入交付** — `nodes.py:419-424`:重开集含 panel/cap/contra,但只读 `needs_decision.json`;归因孔 panel 台账写在 `ask_panel.json`(ask_panel.py:266-267),cap/contra 无该文件→claims 空→return None。后果链:未获答自动挂起已落空答 decision(:2521-2524)→resume 后 panel_waiting 判「已答」→merge F1 排除(:1015-1020)失效→案进 delivery 卷连跑拿 pass 即 deliverable——**ought 欠定从未获真人裁决却可交付**。docstring 声称修的就是此缺口,但对 panel/cap 实际不生效。R056/R045。
- **H-18 author 的 needs_decision 判据只查台账存在、不查新鲜度 → 旧台账重问,no_ledger_channel 升级被旁路** — `nodes.py:502`:r1 欠定→答改过程→r2 worker 又声明欠定但没写新台账(`compile_user_decision` 落盘后不删除台账)→按 :504-514 设计应走 ESC_NO_LEDGER_CHANNEL,实际因旧文件存在走 needs_decision 分支拿**旧 claims** 重问,worker 原文被丢弃。同函数 xlsx 有 mtime 检查(:497),台账没有——判据不对称。
- **H-19 _escalated_remedy_text 把「未答自动挂起」的空 decision 渲染成用户裁决** — `render.py:219-233`:deesc_decs 不滤空 answer;未答 deesc 题落 `decision{answer:"",token:"suspend"}`(:2517-2524)→落进兜底「已按你的裁决「」处理」。非交互批里所有 escalated 案必走此路径,且同案状态行显「引擎无法继续(需人工)」自相矛盾。修法:滤 `not f.get("answer")` 或 token=="suspend" 单列。
- **H-20 修法队列 direction 英文直灌用户面,双 detector 均不覆盖该接缝** — `remedies.py:54,65,70,80`→`render.py:243-244`:direction=fix_direction(LLM-facing 英文,:2418-2419 自指「直灌用户面=D1/D9 泄漏」)或三条硬编码英文串;render 原样拼「。方向:{direction}」进 delivery_report.md/unsuccessful_cases.md。leak_scan 只抓 token 类,chinese_ratio 门只管题面——报告接缝无人把守。closing 对全部非 deliverable 案构造 queues,常态可达。R083。
- **H-21 超 `_MAX_INTERRUPT_ROUNDS=12` 后无残留分支:假报错或谎报完成** — `engine_tool.py:219-230`:while 退出后不查 `res` 是否仍含 `__interrupt__`,直接读 engine_report.json——新批无报告→返回「finished without a report」(引擎实际挂起在 interrupt);同 out_name 复跑→读到**上一批陈旧报告**返回「done: <旧 outcome>」,本批悬在问询上却向用户报告完成。大批(>16 欠定案)一次 invoke 内 >12 现实可达。R028。

---

## 三、中(24)

**账目/幂等**

- M-01 bed_gate decision 跨批幂等键碰撞(qid 固定 "bed_gate"),第二批起床态裁决静默丢账;answer 英文 "proceed" 进 echo(nodes.py:316,facts.py:96-97)。R001/R005。
- M-02 attribute 收账 `_attribution` 无新鲜度闸:超时 fork 迟到写入可被下轮收割盖章新 run_id(ask_panel 侧有 t0 检查,归因侧没有)(nodes.py:1824-1856)。
- M-03 s0_dispute 计数被幂等去重塌缩(run_id 恒 `diag:{volume}:{aid}` 无 run 序),题面「N 次判起点被污染」的 N 恒 1——#74-⑤ 在 diagnosis 上修过的同型病未修到 s0_dispute(nodes.py:2305-2307)。
- M-04 s0_dispute 在「配对命中但被否决」路径误标 `mech="no_polluter"`,题面告诉用户「未找到污染者」与事实相反(nodes.py:2284-2308)。
- M-05 escalated 事实无轮次维度→同因重复升级被幂等吞,deesc_auto_resolution 承诺的「完整轨迹」不成立;同族:6 处 round=99 归因均无 run_id,幂等键退化 `(attribution,aid,99)`(facts.py:305-307 等)。
- M-06 ask_shown 先全量入账、interrupt 只问前 32 题:>32 题「账上已问、实际未问」(双确认)(nodes.py:798-816)。
- M-07 S_PENDING(emit_invalid 打回)绕过轮次封顶:反复「过 emit 门过不了 merge 预检」的卷每圈烧一次 fork 不问人,由 recursion_limit=200 终结(nodes.py:454-467)。
- M-08 defect_candidates 写盘失败时 render 仍声称「已记入」、outcome 不降级——直违 F §5.5③「说了、没有、不降级」(nodes.py:3145-3157,render.py:443-444)。
- M-09 _archive_unsuccessful 失败只 debug:未通过卷 xlsx 缺位逃出 missing 对账,render 恒声称其在交付物里(nodes.py:2694-2707,render.py:442)。
- M-10 delivery_report.md 写盘后,卷组成/缺失对账才把 outcome 翻 delivery_incomplete——md 不重渲染,头行成谎(nodes.py:3141 vs 3210-3243)。
- M-11 closing 取 moved_tail/coexist 用 `mf[-1]` 不过滤 ctx(views/report_gate 都过滤 subset,closing 漏),交付后子集复跑合并可张冠李戴(nodes.py:3038-3040)。
- M-12 缺陷表单 last_run 回读用硬编 `mdir/"last_run.json"`(:3045),同函数他处用 `state["last_run_ref"]`;最后一次跑是子集跑时在途批兼容路径部分失效。
- M-13 G3 门调用崩溃=静默放行交付:`except Exception: continue` 零日志零 gate_disabled,fail-open 方向恰把污染案送进交付卷(nodes.py:3021-3022)。R006③。
- M-14 check_sync 承诺的 missing_local 从不计算:本地缺锚文件静默退出对账,status 照样 "match"(mirror_anchor.py:61-78)。R075。
- M-15 mirror 锚 unknown 不入 findings/事实流,「连续未验证」不可见,与模块自身契约不符(nodes.py:245-246)。R075。

**一致性/词表**

- M-16 report_gate 终局臂缺 `engineering_fault`(views 已含),D31 守门 fixture 未同步——双路等价承诺开口,下一只新增排除态照样漂(双确认)(report_gate.py:53-55 vs views.py:102-105)。
- M-17 缺陷候选单处置轨迹 `round==99 → "用户裁决"`,deesc 自动裁决(引擎)被渲染成用户裁决——同一文件与 `user_confirmed=False` 自相矛盾,N1a 归属报错(双确认)(render.py:490)。
- M-18 DISP_CN 缺 `expectation_suspect`/`transient` → fallback 英文 token 上报告;且 defect_candidates.md 不在 leak_scan 扫描面(closing 只扫 dmd+umd)(render.py:43-47,nodes.py:3164)。
- M-19 S_CONTRADICTED 用终身累计计数贴标,与「重编即重置标签」注释矛盾:art1 矛盾 1 次→reflow 出 art2→art2 fail@delivery 被贴 contradicted,render 对用户讲「单独能过、整卷复验会挂」对 art2 是假话(views.py:124,140-141)。
- M-20 观察入库 verbatim 门对机械归因行未生效:deesc 自动裁决行(run_id=None 旁路)与 s₀ 前筛行(引擎自撰 basis)以 `observe_cmd=真实锚命令` 入 uncertain 库——引擎推断冒充设备观察;且破窗排除对缺 run_id 者 fail-open(双确认)(nodes.py:2755-2773,uncertain.py:50-51)。R082。
- M-21 _evidence_suspect 只实现 dig 单形态,R076/I2「执行目标 vs 卷面 G 列」通用归属门未全覆盖,非 dig 取证错位静默通过(nodes.py:1508-1529)。
- M-22 common_causes payload 键零消费:§18.6 坑#8 修复端到端未接上(_bridge 只读 cases,render/report 也不读)(nodes.py:2498-2500,engine_tool.py:156-170)。
- M-23 「队列非空禁 ask」warning 对 cap/contra 结构性误报(self_cleanup 队头在 cap 判定前无条件入队,与 remedies docstring 自相矛盾),真异常反被噪声淹没(nodes.py:2379-2381,remedies.py:47-57)。
- M-24 三元组分支丢 ordering_sensitive 显式决策保证,且与 validate_questions :414-416 不变量自相矛盾(生成器与门互斥);FORM_BY_KIND 缺 sequence_periodicity→form 默认 dist 与「顺序语义保留」同句互斥(questions.py:201,236-266)。

---

## 四、低/残渣(合并列举,28)

- prep run_start seq 崩溃重放不自幂等(nodes.py:170-171);_reclaim_late_artifacts docstring 宣称的时间锚判据未实现(:902-917);ask_decision 落账成功无 G4 即时 echo(:836+);merge 全踢路径文案「打回重编」与行为(直接收口)不符(:1089-1090);_writeback_one 行为晋升失败仅 debug(:1451-1457)。
- G6 anomaly 分支注释说谎(称「diagnosis 照落」实际 continue)+行号漂移(nodes.py:1693-1695,2287);deesc_qid/deesc_recovery_waiting 两处 docstring 把 qid 机制写反(实现是对的,复用旧 qid 才会被幂等吞)(_shared.py:223-226,双确认);prior_choices 混入空答 decision(nodes.py:2390);`sig_by_aid` 注解漂移(:2268);queue_empty 字段零消费(:2389);panel 判例写回失败仅 warning(:2651-2652)。
- closing 返回值 counts_update 在 manifest 删除后执行→计数全 0(nodes.py:3275);decision_outcome 幂等键含 effective/freeform→跨 closing 状态翻转累积矛盾对(:3109-3112);_UncertainLed.data 可变类属性残渣(:2777-2790);delivery_overwritten 受监集不含 defect_candidates.*(:2873-2874);uncertain 入库整块失败只 debug(:2916-2917)。
- render:_latest_panel_dict 死函数(render.py:171-176);死词条 STATUS_CN["delivery_blocked"]/DISP_CN["fixed"](:32,45);case_timeline 无 escalated/de_escalated 分支(:119-153);_is_no_answer_reason 白名单缺 deesc(:335-338)。
- state.py:43/44 注释漂移(n_settled_bad 实为三态、等待集缺 deesc),且 n_settled_bad/n_contradicted/n_deliverable 只写不读;view() docstring 正当性锚挂在无生产消费方的 all_settled 上(_shared.py:49-55)。
- briefs:FINAL attempt 漏算 granted_rounds(briefs.py:54,133,与 DEESC_ROUND_CAP 同族另一点位);broken_errored/no_output 重编 brief 零证据且「previous on-device runs failed」对 broken/no_output 不实(:33,132-133);out_name 零校验路径穿越(engine_tool.py:207);markup=0 回退静默撤 R063 后半句(briefs.py:211-218);工具 docstring 三处漂移(engine_tool.py:183-189);_panel 取消路径契约漂移;history 字典序 r10 排 r2 前(briefs.py:107)。
- 非自污染 bed 案答「重编」→reflow_tau 但 suggested_tau 为空(questions.py:574-575);_annotate_autoids 污染 verbatim 引文(:732);answer_token docstring「correct 不授权轮次」已被 granted 推翻(:534-535);frozen() 不过滤 ctx(代码/测试一致,文档公式过期,facts.py:172-183)。

---

## 五、测试域专项(评审员:agent-11)

**重言式测试(生产删了也不红)——高**
- T-1 digest 可达性降级逻辑复刻自测:test_device_reachability.py:14-38 把 batch_tools.py:827-834 内联重写再断言,R059 降级产生侧无真锚。
- T-2 共因合题复刻自测**且已与生产漂移**::52-77 复刻体仍写 `kind != "bed"`(生产已改 `("bed","suspended")`)——钉住旧语义,生产改了不红。
- T-3 de-escalate 新通道在唯一被改 e2e 里只路过零断言(test_gather_ask.py:167-177):不断言 ask_shown/decision qid、不断言「保持」不产 de_escalated、不断案终局。
- 中:_s0_parked 床锚重言式(test_device_reachability.py:103-132);test_full_signature_clustering 重言式(test_multifault_and_card.py:17-27);心跳 begin case 正则无真锚(test_bed_ledger_loop.py:262-269)。

**谎报类机制无锚——中**
- T-4 R036 交付物对账降级:全树无「删一件交付物→outcome 降级」(engine_env 夹具删文件即可改造)。
- T-5 R022 报告「N 案未跑成」单列行零断言。
- T-6 R006③ gate_disabled 的 grammar/touch_profile 两面落账无节点级锚。
- T-7 R016 resume 的 decision_outcome effective 无锚。

**低**:test_f8c_fold_and_adopt.py:192-209 名不符实死测试(承诺验折叠,实际断言不折);test_footer_projection.py:22 「Σ九桶」文案过时(现 10 键)。

**§3 十三守门测试改造复用建议**(逐条映射既有 harness):RED_GREEN 事实序模式(test_resume_reopen:82)、`_after_author` 计数断言(test_ask_routing)、rec_env streak harness(test_broken_third_state)、D31 fixture 族加枝(test_report_gate:237-249)、remedy_text 参数化矩阵(test_render_closing:214)、footer 对偶(test_footer_projection)、_seed/_try_adopt 模式(test_adjudication_loop)、escalated fixtures 改写 reason 重放(test_late_artifact_reclaim)、test_gather_ask rig 两跑——完整版见评审记录,改造后每条守门成本都不高,机制侧 `escalated` 桶已在 `_shared.py:383`。

---

## 六、文档一致性专项(评审员:agent-12;rubric 文末 11 条已逐条核验全部属实)

**新增文档问题(8)**
- D-1 公式 (48) 悬空引用:被 K:605-607/1396、D:1817、forensics 多处引用 6+ 处,全仓无定义(K §6 公式表止于 (47)+(30) 补记)。
- D-2 K §2.13 pyATS 映射(Errored→不重编/Failed→重编)与本文档 §2.12.3b 及 F §④ 采纳路由(Errored→reflow)直接相反,定稿后未回填。
- D-3 D §6 行数预算残文(SKILL ≤120/worker ≤60,:225/237/238)与 §5.5 ⑥C 废除令(:214「勿再引」)同文档打架;:1337「豁免登记段」指针悬空。
- D-4 D §17.4 仍按现役描述 restore_leak_teardown(:976-981),§18.4.1 已整条删除(:1049),无回填指针——违自家 §18.7 修订波及面纪律。
- D-5 「四查 vs 五查」未回填实为 9+2 处(rubric 条目 1 只列 2 处):K :114/837/867/994/996、D :383/1303,及 **spec v4.1 :18/:20 两处**(新规格仍在传播旧口径)。
- D-6 spec 标题「草案 v1」与正文自引 v4.1/commit 史矛盾(:1)。
- D-7 spec :14「THEORY:273 A6 已给三个出口」锚失真——A6 原文是二分(:273),三出口系三处拼成。
- D-8 D §13.1 I2「全无」(:663)与 §15.3「已落 I2 防御侧」(:754)状态漂移,AUDIT_design_theory_gaps.md 未登记。

**rubric 11 条核验**:全部属实;两处注记——条目 2 的两个「18.16」前者实为 `###` 三级标题(违例实质成立);条目 4「队列 v4」在全仓无定义章节,I 即使回填 v4 也无落点。

**术语一致性**:verdict 四值/ctx 两值/decision token/conflict_shape 五值/disposition 词表与 spec v4.1 互核无漂移;escalated 语义四处一致。

---

## 七、存疑/待 leader·设计裁定(择要)

1. deesc_auto_resolution round=99 引擎自动终判 vs R017「终态仅用户来源」——views.py:96-101 注释自辩为 B-1 既定设计,与在册项「DEESC_ROUND_CAP=2 违 v4.1 裁定」联动,建议一并裁。
2. _try_adopt 缺构件五第三条件「填充型(不与 D 文本/既有 E 语义相抵)」——文档未给机械判据,硬做可能撞 R064 语义门禁;需文档先澄清。
3. 采信成功后案仍每轮烧归因 fork(收割被 already 跳过,brief 不带 adopted 裁决)——消耗形态是否设计预期,无文档锚。
4. s₀ 配对域取 `merges[-1]`,subset 复跑后可能缩域(diagnose :2222、G6 :1664-1666)——§16.2 C 未明确卷域口径。
5. R030「无 acknowledged 翻案」以「排除最终 deliverable」代理——换形态若只绕开缺陷触发点,517027 型真缺陷主张会从候选单消失;需 acknowledged 精确定义或文档授权。
6. contra 自由输入默认 reorder(烧整轮整卷终验),与 bed/deesc 默认保守哲学不一致;未见文档明文。
7. R082 归一化口径:文档写「剥时间戳/计数器易变 token」,代码只剥时间戳(注释论证计数器是观察身份)——同期文档与代码冲突,需裁决回填一侧。
8. _gather_or_close 不 flush 第二问询族(cap/env/bed/suspended/deesc)——已登记 team3_design_challenge C6「兑现一半」;deesc 投影使该族第一次碰到这门,是否扩门需设计裁。
9. deesc 选项→decision token 映射契约文档缺位(spec 未定 token 词表);「工程故障呈报」事实载体未定(N1a 禁 attribution 形态)——spec 待补,实现期有踩线风险。
10. frozen() 不过滤 ctx、contradictions 形态②超公式字面——代码/测试一致,判文档公式过期,建议回填文档。
11. diagnose 本体 run_id 与 G6 不对称(G6 改派发条件时 #74-⑤ 同型病会在 diagnose 侧复活)——建议统一带 verdict run 序。
12. mirror_sync internal detail(框架文件名)直进用户题面——R083 泄漏 vs 处置必需信息,判不清。
13. (48) 出处:若曾以会话共识立条,问题降级为「理论正本未回填」。

---

## 八、在册项(同日上午 de-escalate 盘面核验已登记,不重复开单)

DEESC_ROUND_CAP=2 硬编码(违 v4.1 裁定 max_rounds+granted);deesc_recovery_waiting 非保持决策后永不重问+all_settled 含 S_ESCALATED 的交互;answer_token("deesc") 缺陷意图返回 "defect" 而非 "deesc_defect";build_ask_question 无 deesc 分支(落 contra 兜底);13 守门测试全缺;facts.py:230 注释 v3 残文;_user_sourced docstring 过时;de_escalated_after_last_escalation 死函数。

## 九、建议处置顺序

1. **先修阻断 3 条**(B-1 陈旧 last_run 背书、B-2 幂等闸吞处方、B-3 床账 foreign 误记)——都是错判/丢案/安全越界,且 B-1/B-2 直接影响「五案救回」验收的可信度。
2. **ask qid 族一并修**(H-01 env、H-04 折叠、H-05 header、H-09 cap、H-11 bedclosure)——同根「qid 判别子选型」病,deesc_qid 的 decision-count 判别子已是现成范式。
3. **状态机漏洞**(H-03 cap_waiting 过滤、H-16 delivery_blocked、H-17 F1 重开、H-15 run_id 盐)。
4. **否定盲区/意图反转**(H-06/H-12)——answer_token 加否定门是局部修。
5. 谎报族(H-19/H-20/M-08~M-10/M-17)与泄漏族(M-18)随渲染侧一并过。
6. 测试重言式重写(T-1/T-2)+守门 13 条按第五节复用建议落地。
7. 文档回填(D-1~D-8+rubric 11 条)走「理论/设计正文零改动纪律」的既有流程,与代码修复分开 commit。
