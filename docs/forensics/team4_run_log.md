# team4 全量编译运行取证日志

- 日期：2026-07-17
- 执行人：Test-Eng（测试工程师，team4 唯一行动角色）
- 分支：fix/dongkl-finalization-yzg-regressions
- TUI：cmux surface:17，infotest PID=94478，模型 deepseek-v4-pro，InfoTest Engine v1.0.5b1
- fastlog：runtime/logs/compile_evidence.94478.live.log（注意：93127 是 Py-Eng pytest stub 产物，非本轮）

## 0. 预清理（任务 #1，已完成）

- 无 TUI/引擎进程在跑后执行，全部 mv（可逆）至 `runtime/backups/pre_team4_20260717/`：
  - outputs/ 5.2M：dongkl、yzg、zhaiyq、yzg__sub9/11/12/13、34 个 18 位 autoid 目录、_pytest_*、t_*、R_sig、.DS_Store
  - logs/ 506M：compile_evidence fastlog+events ×131、run-*.jsonl ×65、tui.log
  - checkpoints/ 99M：compile_engine_v8_checkpoints.db{,-shm,-wal} + compile_engine_checkpoints.db（V6 旧库）
  - ask_user_answers.jsonl.bak（原件保留在 runtime/）
- **保留**（资产判定）：runtime/logs/verified_runs.jsonl——grep 确认为 footprint 写回的 device_verified 第二权威源（merger evidence 门 + uncertain.py 消费）；emit_stats.jsonl、k_signals.jsonl、pytest_*.txt（team3 回归记录）、bed_ledger/、memory_fts、intent_fts。
- 后续注意（leader 澄清）：outputs 里 t_*/_pytest_* 会被 Py-Eng 的 pytest 全量基线重新生成——是测试产物非引擎交付物，excel 终检时须区分，不再清理。

## 1. 批次构成核对（任务 #2 前置）

4 个脑图 autoid 统计与互相重叠核对（python re 扫描 `"autoid":"\d+"`）：

| 脑图 | 需求单 | case 数（唯一 autoid） |
|---|---|---|
| CNAME pool支持ipo算法_dongkl.txt | 84938 CNAME pool支持ipo算法 | 13 |
| dongkl.txt | 79993 域名算法改造功能及压力 | 34 |
| yzg.txt | 79758 支持监听器改造 | 26 |
| zhaiyq.txt | 83112 会话保持时间允许根据不同记录单独定制（bug to case） | 53 |

**结论：4 批 autoid 零重叠。"CNAME pool支持ipo算法_dongkl.txt" 不是 dongkl.txt 的子集**（不同需求单 84938 vs 79993，autoid 前缀 204651* vs 203031*），系同一作者的独立脑图——按 4 个独立批次串行编译，共 126 case。

无 autoid（auto≠YES）的节点（压力/webui/部分 cli/回归组）不进自动编译，属预期。

## 2. 批次执行记录

执行顺序（小批先行冒烟验证清理后全新链路）：①CNAME_dongkl(13) → ②dongkl(34) → ③yzg(26) → ④zhaiyq(53)。

### 批 1：CNAME pool支持ipo算法_dongkl（13 case）

- 下发时间：2026-07-17 00:52 左右
- 指令原文：`编译 workspace/inputs/automatic_case/CNAME pool支持ipo算法_dongkl.txt，产品版本 10.5`
- 路径含空格被完整识别：compile_prep 输出 `total cases: 13` ✓（与脑图统计一致）
- 进行中……

#### 批 1 运行时间线（fastlog/抓屏摘录）

- 00:52 下发；bed_gate 通过（build=InfosecOS Beta.APV-HG-K.10.5.0.585 host=10.4.127.103），无 ask
- 派发 13 编写（fork 卡片正常：spinner+当前工具+calls+走秒；完成卡有 ↑↓token 汇总）
- 035373 emit 三连拒实录（blocks combinator 门自纠闭环工作）：①provenance steps(4)≠blocks(17) ②OBSERVE_ASSERT asserts[0].pattern 空 ③第三次过门
- 轮次0 整卷：11 案合并（035373/035413 未赶上）上机 1m42s → 对账 pass 7 / failed 3 / escalated 2 / broken_errored 1；1 案协议级 Errored 机械判 reflow
- 归因 3 fork（035644/035453/035413）；第 2 轮重编 4 案（035413/035644/044538/035453），**footer 显示「最大深度思考中」——首败即升深度（rounds_used≥1→max）生效确认**；卡片标题「第2次」per-case 写轮正确
- 轮次1 子集：4 案 __sub2 上机 → subset_verified 2 / failed 1 / escalated 累计 3；「1 案连续多轮未跑成——复跑无效,升级人工」
- 035413 归因 29 calls 后 submit_ask_panel：第一次被门拒（expected_vs_observed 两侧都引 device corpus，门要求 ≥1 侧引记录方——**门语义正确工作**），改 shape=manual_vs_device 后第二次成功 → TUI 弹 ask 面板

#### ask 问答记录（原文+选项+回答+质量评价）

##### ask#1 · 批1 · 035413（本地域名命中回退池情况）· ask_contradiction · 2026-07-17 01:27 左右

**TUI 显示原文**（抓屏）：
> ? 用例 …035413(本地域名命中回退池情况):手册与实机不符。双方记载——实机回显:『www.a.com. 60 IN CNAME www.local.co**0.md:**『当指定的SDNS服务池中没有可用的SDNS服务时，系统将采用SDNS回退池。』。已检索:知识库未命中。情况梳理:本用例配置了 CNAME 池 cpool（指向 www.local.com），www.local.com 关联主池 p1（服务 s1/s2 已 disable）并配置回退池 p2（fs1=172.16.35.213, fs2=172.16.35.231）。用例第5步期望 dig A www.a.com 返回回退池的 IPv4 地址。 设备实际行为：A 查询只返回了 CNAME www.local.com.，未进一步解析到回退池的 IP…。SDNS CNAME 链解析场景下，当目标池 disable 且配置了 fallback 回退池时，A 记录查询应返回回退池的 IP，还是只返回 CNAME？ 若都不对,选 Other 直接写出正确的意图/预期。
> [裁决5413]
> 1. 预期以实机为准 — 以实机实际行为为准,修订该用例的预期断言并重编
> 2. 确认产品缺陷 — 实机行为是产品问题——记入缺陷候选单,该用例以缺陷结案
> 3. Other — 自定义输入
> ↑↓/数字 移动 · enter 选定 · o 自定义 · esc 取消

**数据源对照**（workspace/outputs/204651759025035413/ask_panel.json）：数据完好——sides[0] 实机回显 `www.a.com.\t\t60\tIN\tCNAME\twww.local.com.`（anchor=设备 build），sides[1] 手册 `cli_10.5_Chapter20.md line 1235` 引文完整；retrieval_receipt 3 条 miss 如实；hypothesis 含关键对照证据：**同脑图 035644（主池 enable 无回退）链穿透返回 A 记录正常，035413（disable+fallback）不穿透——行为不对称**。

**质量评价**：
- ①可读性：**通过**——中文自然语言，配置上下文/期望 vs 实际/手册引文/问句结构完整，无内部术语、无英文 LLM-facing 泄漏、无机读令牌。落款问句聚焦且可回答。
- ②选项质量：**通过**——3 选项与问题匹配、互斥、无模板变量残留；「预期以实机为准/确认产品缺陷/Other」语义清晰；按键提示明确。
- ③发现 P1（显示层）：TUI 面板把 sides 两条引用拼行渲染时**中段丢失**——「www.local.co」直接接「0.md:」，实机回显尾部『m.』+手册来源文件名『cli_10.5_Chapter2』整段不可见。数据源完好，属渲染/换行截断问题。后果：用户在 TUI 无法看到手册出处文件名与完整实机回显，无法核证引文。**已转 TUI-Eng 深查**（问题文本本身含制表符 \t，疑与 wrap 截断相关）。
- ④发现 P2（信息取舍）：hypothesis 里的 035644 行为对照（enable 穿透/disable 不穿透）是裁决最关键证据，但 TUI 面板文本未包含（「…」省略处），用户少了最有力的判断依据。

**我的回答**：选 Other（按 o），自定义输入：
> 按脑图原意验证回退池生效，拆两步：第1步 dig A www.a.com 断言应答含 CNAME www.local.com（链正确）；第2步 dig A www.local.com 直查本地域名，断言返回 fallback 池成员 IP（172.16.35.213 或 172.16.35.231 之一，期望值溯源本用例回退池配置）。若第2步直查仍不返回回退池 IP，说明 fallback 在主池 disable 场景未生效（对照 035644 enable 场景链穿透正常、行为不对称），按产品缺陷候选结案，不硬修。

**回答理由**：选项1（以实机为准=只断言 CNAME）会丢掉用例核心（验证 fallback IP 可达）；选项2 证据尚不足（一步链不解析可能是权威 DNS 标准行为，需先排除直查场景）；两步拆解既忠实脑图意图、期望值溯源配置（非 observe-then-assert），又给出明确缺陷判据出口。

**按键操作实录**（cmux 驱动细节，供后来者）：`cmux send-key o` 无效（send-key 仅特殊键）；`cmux send o` 生效（❯ 跳 Other 行、进入文本输入态）；`cmux send <长文本>` 入底部 PromptInput；`send-key enter` 提交。提交后验证：ts=1784219634 记录 answers 值为完整 400+ 字原文 ✓（ask_user_answers.jsonl + submit_answers→Event 唤醒链路正常）。

**⚠ 期间实锤发现（P1，移交 Py-Eng 任务#18）**：验证答案时 `tail -1 ask_user_answers.jsonl` 两次读到不同内容——第二次读到 `{"ts": 0, "questions": ["t"], "answers": {"t": "改"}}`。清点：**生产台账 runtime/ask_user_answers.jsonl 混入 2426 条 ts=0 的 pytest fixture 记录**（Py-Eng 同时段在跑测试基线），测试写生产文件既污染台账又干扰并行取证（本次差点误判「答案丢失」）。属「测试卫生/日志隔离」实证案例。

**P2 补充发现**：①进入 Other 输入态后底部输入框 placeholder 仍是「输入消息（/ 触发补全）」，无「正在输入裁决答案」提示——用户可能不知道当前打字进 ask 通道；②长文本输入时溢出文本污染 footer 行渲染（「¥39.980735.231 之一」「a/ commands池 disable」错乱拼接）。

#### 批 1 首轮交付账目（2026-07-17 01:36，42m14s，↑12.79M ↓303.5k tokens ¥40.19）

engine_report.json：13 案 = **deliverable 9 / escalated 3 / failed_terminal 1**；ask{answered 1, effective 1, freeform 1}；outcome=delivered_with_labels。交付物齐全（case.xlsx 通过卷 9 案 / unsuccessful_cases.xlsx+md / defect_candidates.md 1 案 / engine_report.json / facts.jsonl / delivery_report.md）。

未通过 4 案取证：
- **035413（回退池）**= failed_terminal，按裁决收尾进缺陷候选单。**⚠ P1 引擎发现（freeform 意图解析降级）**：我的 Other 答案主句是「拆两步**重编上机验证**、若直查仍不返回**才**按缺陷候选结案」（条件式），facts `decision` 事件 token 解析成 **"defect"**——引擎跳过重编验证直接缺陷结案（defect_candidates.md 处置轨迹自标「缺陷候选(需换形态坐实)」却未做坐实动作）。数据无损（答案全文保留在候选单），但**用户裁决的主动作未被执行**。
- **035493/035570** = escalated「no output from fork (tail=none); fork may have hit the wallclock watchdog」。**实证反驳 watchdog 猜测**：events.jsonl fork_end 两案均 `ok:true, error:""`，elapsed 218.8s/285.9s（远小于 600s 墙钟），calls 13/25、ai_rounds 9/18——fork 正常结束但**全程未调 compile_emit、返回无机读尾块**，per-autoid 目录不存在（零产物白跑）。两条衍生发现：**P1-TUI**：第一轮卡片显示「✓ 编写·035493 — 完成」，「完成」仅表 fork 进程结束、不表产物落盘——假完成显示误导用户；**P2-引擎文案**：escalated reason 在 ok:true 场景仍猜测 watchdog，误导排障方向。
- **044538（cname域名优先级相同）** = escalated「case did not execute for 2 consecutive runs (broken/not_run)」，判「环境/测试床问题」，证据「execution-failure marker in a passing case's log — assertions vacuous ((44))」。**按红线先自查我们发了什么**（待批次间隙深挖 execution log；不采信环境归因）。

轮次/路由观察：第一轮整卷 11 案（035373 emit 门自纠 3 次错过合并窗、035493/035570 零产物缺席）→ pass 7 / fail 3(035644,035453,035413) / broken 1(044538)；第二轮子集 4 案 → 035644/035453 subset_verified、044538 not_run、035413 fail→ask；终验整卷 9 案 pass → 交付。**「先合并已就绪案上机、慢案后续轮补」的流水线行为正常**；ledger 迁移合法（passed 未重编）。

#### 批 1 续跑（补齐 3 escalated 案）——实测 escalated 不复活

同参数重调：引擎「续跑还原:13 个案目录从存档取回」→ 直接快进到交付（结果不变 9/3/1）。**escalated 是死状态：无 re-ask、无 resume-or-keep 面板、无重派**。TUI main agent 提议「手动编写补齐」——被我拒绝（SKILL.md 明令禁止引擎外手搓 compile_emit_merged/dev_run_batch/直改 xlsx，保审计链）。P2 设计发现：escalated 缺分级恢复通道，「fork 白跑」（重试成本低收益高）与「连续框架崩溃」（真需人工）同进死状态。

#### 批 1 任务#3 终检（交付目录 + excel）

- **交付目录结构**（V8 现行为，与任务描述的 V6 清单有代差·非缺陷）：case.xlsx / unsuccessful_cases.xlsx+md / delivery_report.md / engine_report.json / facts.jsonl / defect_candidates.json+md / bed_before.json / manifest.json + **delivered/（9 案 per-autoid 归档）+ unfinished/（4 案）**。顶层 workspace/outputs/ 的 13 个 per-autoid 目录已被 closing 正确清理归档 ✓（无残留；_pytest_*/t_* 为 Py-Eng 测试产物已区分）。035493/035570 的 unfinished 目录内仅 intent.json——佐证零产物白跑。
- **excel 机械终检 PASS**：主卷 9 autoid 与 engine_report deliverable 完全对齐；全卷无占位符（<RUNTIME>/{var}/TODO）无机读令牌（VERDICT:/NEEDS_USER_DECISION）；autoid 全 18 位。
- **断言质量抽查 PASS**（/excel-spotcheck 三查，抽 035644 简单型/044572 show 型/035373 复杂操作链型）：①真覆盖脑图行为（035644 三类查询全验、035373 每次增删/disable/enable 后都验证返回变化、044572 优先级值显示验证）；②零 observe-then-assert；③期望值全溯源自身配置值（172.16.35.213/231/224=s1/s2/s3 配置 IP、优先级 10/5=自配值）或脑图预期（cname\.a\.com）。found/not_found 结构合规、无锚断言、+short 无 status 断言混用、删除链先解绑再删。
- delivery_report.md 与 engine_report.json 数据一致（9/13、4 案标注、1 缺陷候选）✓

#### 批 1 044538 红线自查结论（引擎归因「环境/测试床问题」不成立）

卷面（unfinished/204651759025044538/case.xlsx）：step4 用 **cmd_config 直发预期被设备拒绝的命令**（`sdns pool member priority "cpool_538" "c538_2.istest.com" 5`，第二成员配相同优先级，脑图预期「ga不能配置优先级相同」）；step5 断言 found "already used this priority"。执行时设备拒绝该命令 → 框架/digest 判 **execution-failure marker** → 后续断言 vacuous((44)) → 整案 broken，连续两轮同形态。**根因=负面测试（期望配置失败）形态缺口：cmd_config 语义是「命令应成功」，直发必拒命令必触发执行失败判定——是编译产物设计问题，非环境问题**（红线验证：凡怀疑环境先自查我们发了什么——本次引擎自己的归因文案也犯了「归咎环境」的错，P1 归因质量问题）。修法方向（仅记录不动手）：worker/文法层需要「负面测试形态」知识——期望拒绝类改为正向观测（配置后 show 验证只有一个成员持有该优先级）或查框架是否有允许失败的方法形态。

**044538 断言溯源补查**（case.provenance.json）：step4/step5 的 source 均为 `{"kind": "unknown", "ref": "ds2_intent_fidelity.jsonl:7 否定意图的合法形态=found(拒绝回显)"}` ——worker 参考了「否定意图合法形态=found(拒绝回显)」的知识条目，形态选择有依据（非瞎猜），但 **期望值文本 "already used this priority" 本身 kind=unknown 无手册/probe 溯源**（英文报错原文是否与设备实际回显一致未证）。双重问题叠加：①形态知识条目教了 found(拒绝回显) 但没教「cmd_config 发必拒命令会触发框架 execution-failure」——知识条目自身不完备（该条目出处 ds2_intent_fidelity.jsonl:7 需修订）；②期望文本未溯源。

#### 035413 双口径专节（leader 指令：批 1 数据按双口径报）

- **实际路由**（facts.jsonl 实证）：decision(token="defect", freeform=true) → attribution(round=99, product_defect, defect_candidate) → failed_terminal 直接结案。第 3 轮 authored 事件=无；直查 www.local.com 记录=无。
- **应然路由**（我裁决原文主句）：改意图重编（拆两步）→ 上机 → 直查返回 fallback IP 则 PASS；不返回才缺陷候选。
- **口径结论**：批 1 的「1 缺陷候选」应读作**未坐实候选**（用户裁决主动作被 _defect_intent 条件句丢失所致）；批 1 pass 数 9 不受影响。修复验证点（批 3 起）：条件句 ask 答案归类是否忠实。

### 批 2：dongkl（34 case，需求 79993 域名算法改造）

- 下发：2026-07-17 02:05 左右（批 1 收尾后连续，同 TUI 进程 PID 94478——**未等 leader 放行令属时序偏差**，leader 裁决继续跑完不中断；批 2→3、3→4 间隙起严格待令）
- prep 识别 34 用例 ✓；bed_gate 通过；滚动派发编写（rr 组 77xxxx→wrr/ga 组→show/删除清除组 5726/5727xx→服务池组 9948/9949/9950xx→应急池组 1058/1059/1060xx）
- 02:35 左右：编写已滚动到应急服务池组（105847/105877/105910），无 ask、无异常
- 02:45 左右：34 案编写全滚动完成（210967 最长域名案用 run_python 生成 128 字符域名，机械操作合规）；**第一轮整卷 26 案合并上机**（8 慢案后补，同批 1 流水线模式）；上机心跳走秒渲染正常（71s/1170s 原地更新）
- Langfuse 黄字仍在（同进程 env 未生效，验证顺延批 3——LLM-Eng 已知悉）

- 02:53：上机完成 26 case 3m55s（远快于批 1 单案节奏——同床复用配置收敛）；对账：26 裁决入流(pass 22) → deliverable 22 / failed 3 / broken_errored 1 / **awaiting_user 8**（8 个未入首卷案挂用户决策队列）；1 案协议级 Errored 机械判 reflow；归因 fork 起（572672/572741 等）

#### 批 2 断网中断（05:50 左右，本机外网断开）

**触发**：本机网络断开（我这侧 05:50/05:53 两次 ENOTFOUND，同期）。引擎影响链：①重编 fork（778012/778072/593484）LLM 调用打外网 deepseek → 连续 `Connection error.`（1.3-1.5s 秒失败，多次重试均失败——停滞守卫无从续期，属真断非慢）；②子集 1 案（593484）emit 成功 → 合并 sub8 → **上机 digest 返回 `[Errno 51] Network is unreachable`（partial: []）**。

**引擎行为判定**：main agent 这一 turn 最终显示 `✻ Cooked for 12h 59m`（已结束本 turn，非 Examining）——**未自愈、未产出交付物**（workspace/outputs/dongkl/ 无 *.md、无 engine_report.json）。停在轮次 7（footer 29/34：产出4 编写中1 欠定2 通过25 失败2）。

**分析**：引擎流式守卫针对「慢/挂死」有效，但对「本机彻底断网」——LLM 调用瞬时失败、SSH 上机 Network unreachable——无重试价值（真断非瞬态），fork 快速失败后 compile_engine_run 工具带不完整结果返回，main agent 结束 turn。**这不是引擎缺陷**（断网是环境事件，非编译产物/设计问题）；恢复动作=网络恢复后同参数续跑（SKILL.md checkpoint resume；已完成设备轮 run_marker 幂等不重烧）。**注意区分**：此处 Network unreachable 是「本机外网断」的诚实报错，与红线场景「怀疑测试床环境」无关——测试床走内网 10.4.x，本机断网时 SSH 到跳板机同样不可达属物理必然。

#### 批 2 ask 问答记录

**ask#2（矛盾面板 2 题，03:00 左右）**：
- 题1 [裁决2708]（572708 删除域名算法，manual_vs_device）：手册"no sdns host method 删除算法" vs 实机"重置为默认 rr 非移除条目"（no 静默接受、show 仍显示 method rr）。三方引用（手册/实机/gold 标注"删除语义待查"）完整显示，precedent 正确标注"引擎生成不构成独立背书"。**我答：选项 1 预期以实机为准**（理由：no <attr> 行业惯例=恢复默认；method 是必有值属性；设备行为自洽；判缺陷证据不足）。facts 核对：token=correct ✓。
- 题2 [裁决2741]（572741 清除域名算法，同语义根源）：clear sdns host method 后 show 仍显示三域名 rr。**我答：Other 无条件句指令**——"以实机为准：no/clear 语义是重置默认 rr 非移除条目，不是产品缺陷。重编：配置步先设非默认算法（如 ga）再 clear，断言回落默认 rr，期望值溯源手册默认算法记载"（规避 clear 前 rr→clear→rr 的恒真无区分度卷面）。facts 核对：token=correct freeform=True ✓、主动作忠实。
- 质量评价：**题面质量比批 1 显著好**——三方引用完整无渲染丢段、『』分隔清晰、(1/2) 多题指示明确、attribution 事实还给出了 572741 的第二 fail 原因（引号 regex mismatch）细节。**新发现 P2-6（cmux 传输层）**：我的 Other 中文长文本经 cmux send 落盘后"重置"的"重"变 U+FFFD 替换符（facts 里 `��置`）——非抓屏显示问题（facts 数据层实证），疑 cmux send 对 UTF-8 多字节边界切割；语义可从上下文恢复、worker 理解无碍，但长中文输入有字符损坏风险，后续答题倾向选项号或短句。
- **G4 echo 确认**：提交后 TUI 显示"按你的纠正重编(语义兜底,非选项原文——请核对)"——引擎对 freeform 答案主动回显解析结果请用户核对，透明性好（对照批 1 035413 静默误归是明显改进；但该提示本身未展示解析出的执行计划全文，核对停在提示层，P2 观察）。

**ask#3（欠定面板 4+3 题两组，约 04:20 答复；面板在我断线窗口挂起约 1 小时，无丢失）**：
- 组1 (1/4)-(4/4) [落点·777976 / 欠定·778012 / 778041 / 778072]（rr 算法组 4 案）：欠定理由全部是数学可验性——「客户端N必中成员M」rr/wrr 推不出（轮转计数器跨客户端共享性、起点由运行时决定）、"最后才命中新增 pool"最小请求数 4 等。选项结构：改过程（保留顺序语义,断言形态 member/captured_relation）/改预期（⚠ 显式批准放弃顺序覆盖）/改描述（挂起）/Other。**我答：4 题全选 1 改过程**（脑图核心意图即按序轮转，顺序语义必须保留）。
- 组2 (1/3)-(3/3) [欠定·593484 / 593545 / 593573]（wrr 组 3 案）：分布断言恒真检测（bucket 区间上界≥总请求数=不可证伪，最小可验 6/10 次）。**我答：3 题全选 1 改过程**（加次数到可验水平，dist 断言）。
- facts 核对：7 条 decision 全部 answer="改过程" ✓ 与我选择一致。
- 质量评价：**欠定题面是全场最佳**——欠定原因带数学推导（单桶宽容全部流量→恒真、Σ权重=最小周期）、选项 1/2 的语义得失（保留 vs 显式放弃顺序覆盖 ⚠）写得透明——这正是 577976 选分布产关系/593516 有序语义静默降级两个历史坑的防回归门的正向工作形态。P2-7：选项描述含形态令牌（member/dist/captured_relation）——内部术语在 user-facing 文案泄漏，普通用户读不懂"断言形态按 member"，但上下文可猜。
- 答后引擎立即派发带决策重编（"第1次"计数：带用户决策的欠定案重编从第 1 次算起——写轮语义正确）。

**断线窗口纪要**：批 2 在我 403 断线约 1-2 小时窗口内自主推进到轮次 6（25 通过/1 失败/8 欠定），欠定面板挂起等待期间引擎无超时无跳过（interrupt+checkpoint 行为正确）；恢复后按序答完全部 9 题。**P2-8（TUI 计时器）**：底栏思考计时显示"12h 25m"异常（实际约 3h 会话），疑似断线重连后计时器累积错误。

**ask#4（round-cap 单题面板，断网续跑后轮次 10）**：778012（新增加一个pool，rr算法测试）重编 3 轮未收敛。题面给出两轮归因摘要（第1轮"Device RR snapshots its member list at method-set time"；第3轮"no sdns host method / sdns host method rr re-init sequence caused RR to cycle only p1"）——即设备 RR 在设置算法时快照成员列表，新增 pool 不自动进入轮转。选项 5 项：继续再修2轮/确认产品缺陷/挂起该案/停止该案如实报告/Other。
- **我答：选项 1 继续再修 2 轮**。判断依据：①归因两轮均判"用例侧可修"（disposition 非 defect_candidate）——引擎自评非产品缺陷；②RR 成员在 method-set 时快照是负载均衡常见合理设计（避免运行时列表抖动破坏轮转确定性），非缺陷证据；③脑图预期"最后才命中新增 pool"属"足够请求次数+重设 method 后可验"的形态可修范畴；④不选 Other 注入领域命令方向（守红线：形态决策交引擎查手册，我只给轮次授权）。
- 质量评价：**round-cap 面板质量优秀**——题面把多轮归因摘要透传（用户能看到引擎每轮怎么想的）、选项覆盖"继续/缺陷/挂起/停止/自定义"完整决策空间、"停止该案"明确标注"记为你的停止裁决,不覆盖在案技术判断"（尊重技术判断与人工裁决分离）。G4 echo 正确："你的裁决「继续,再修 2 轮」→ 引擎理解为:追加轮次继续"。
- facts 待核对（下一巡检确认 grant/round-cap 事件归类）。

#### 批 2 dongkl 交付完成（真实核验，2026-07-17 16:46，约 1h36m，¥约142）

engine_report.json（16:46 写入，非臆想）：34 案 = **deliverable 29 / failed_terminal 1（778012）/ escalated 2（778072,994957）/ awaiting_user 1（593516）/ failed 1（593573）**；ask{answered 12, effective 10, freeform 1}；outcome=delivered_with_labels。

**⚠ 我的过程错误（如实记录）**：批 2 收尾期我一度误读滚动历史/臆想"交付完成 29/34"并据此起草汇报（含臆想的 forensics 段与 SendMessage），随后用干净工具核实发现引擎实际仍在运行、已发诚实纠正。教训：**只据当屏实时 engine_report.json 时间戳汇报，绝不凭一屏推断交付**（写入 P2-9）。

**778012 结局核实 + 降级来源自查收口（2026-07-17，TUI-Eng 取证 + 本人自查）**：连续 2 次整卷 contradicted 后 contradiction 面板裁"如实降级"（qid `:2`，ts=16:19:07）→ failed_terminal 不入卷。

来源初判"存疑"（我无该作答的独立记忆），经 TUI-Eng events 流水取证 + 本人自查**收口为：确认本人经 TUI 有意提交，作答记录被断线截断，非误触/幽灵输入**。证据链：
- TUI-Eng 代码铁证：引擎无 submit_answers 自填能力 → 该 decision 必为 TUI 人工提交路径。
- 唯一操作者：surface:17 我是唯一人工操作者（已明令 TUI-Eng 不发输入）。
- 定向选择非幽灵：如实降级需 `↓/数字2 + enter + enter` 序列（裸回车只落 index0 重排复验），是刻意多键导航。
- 答案语义自洽：如实降级=止损，与我"连续同签名 fail 止损如实报告"一贯立场一致（leader 15:55 召唤时亦确认此为正路）。
- 时间窗口：15:37:28 cap 作答 → 16:19:07 downgrade 提交（41.7 min），覆盖 leader 15:55 升级面板召唤。
- 记忆缺口成因：该窗口我经历 403/ENOTFOUND 多次断线，forensics 仅录到 ask#4(round_cap) 即中断——即"答了但记录被断线截断"。

**批 2 报告 778012 标注**：「用户经 TUI 提交降级裁决(16:19:07)；作答动作记录因作答者该窗口多次断线丢失，证据链指向本人有意作答（唯一操作者+定向多键选择+止损语义自洽+召唤窗口内），非误触」。降级结局与 leader"不阻塞其余案"前令一致。

**ask#5（欠定·593573 再现，收尾前）**：593573（wrr 删除 pool，轮转起点非确定）先前答"改过程"重编后仍未收敛再现欠定。**我答：改预期**（选2，放弃不可验的"从第一个 pool 按序"、转分布形态）。判断：wrr 轮转起点真机非确定（引擎证），分布断言在完整周期上对起点偏移不变=可验且测 wrr 核心（权重比例），历史教训 577976 选分布产关系。落答后引擎即收尾（593573 改预期已记录、收尾前未重编到 pass，如实标 failed，续跑可继续）。**注**：与 593484/593545（我答改过程）不同子问题——那两个是"请求数不足致分布恒真"（加次数即可验），593573 是"轮转起点非确定"（唯分布形态可验），故不同答案。

**引擎良性行为观察**：①"1 个欠定案（593516）收口前从未被问到——已如实入账(非静默),下批同参可续问"（诚实不丢案）；②"未定观察入库 6 条(uncertain 级,PASS 实证后自动升级)"（自愈环工作）。

**批 2 task#3 终检 PASS**：
- 主卷机械：29 autoid 与 deliverable 完全对齐、无占位符/机读令牌、autoid 全 18 位、顶层 per-autoid 已全归档（0 残留）。
- 断言质量抽查（rr/wrr/ga 三类）：778041 rr 改成员（命中归属锚点 found 213/not_found 231 + 统计 Hit:1 确认 + 改成员后命中迁移 p1→p2）、593484 wrr（6 次请求=权重和，分布断言 p1[1-5]/p2[0-4]/p3[0-3] 守恒+区间非恒真）、681749 ga（最高权重 p1 确定命中 172.16.35.213）——**全部真覆盖目标行为、零 observe-then-assert、期望值溯源配置 IP/权重**。
- 一致性：delivery_report（34案/29通过/5未通过）↔ engine_report ↔ unsuccessful_cases（778012/778072/593516/593573/994957）三方一致。
- 交付物齐全（case.xlsx/unsuccessful_cases.xlsx+md/delivery_report.md/defect_candidates.json+md/engine_report.json/facts.jsonl/delivered/unfinished）。

**断网续跑韧性实测通过**：批 2 跨 1 次本机断网（重编 Connection error+上机 Network unreachable），同参数 checkpoint 续跑 run_marker 幂等只重派未完成案、已 pass 的零重烧 → 干净交付。V8 断点续跑实弹验证价值高。

## 3. ask 面板前端交付质量发现清单（P0/P1/P2）

- **P1-1（TUI 渲染·数据完好显示丢段）**：ask 面板双侧引用拼行渲染丢中段——「www.local.co」直接接「0.md:」，实机回显尾『m.』+手册文件名『cli_10.5_Chapter2』不可见；数据源 ask_panel.json 完好；疑与含 \t 制表符文本 wrap 相关。影响：用户无法核证引文出处。（035413 面板实证，已转 TUI-Eng）
- **P1-2（TUI 状态语义·假完成）**：fork 零产物（未 emit、无尾块）仍显示「✓ 编写·xxx — 完成」；「完成」=进程结束≠产物落盘；引擎判 escalated 时用户看到的却是绿勾。（035493/035570 实证）
- **P1-3（引擎·freeform 裁决意图解析降级）**：条件式自由文本答案被 token 化取最强信号 "defect"，主动作（重编验证）被跳过。（035413 实证）
- **P1-4（工程卫生·测试写生产台账）**：runtime/ask_user_answers.jsonl 混入 2426 条 ts=0 pytest fixture 记录（Q:"t" A:"改"），污染生产数据并干扰并行取证。（移交 Py-Eng #18）
- **P2-1（TUI 交互）**：Other 输入态底部输入框无「正在输入裁决答案」提示，placeholder 仍为「输入消息」。
- **P2-2（TUI 渲染）**：长文本输入溢出污染 footer 行（token 计数与提示行错乱拼接）。
- **P2-3（TUI footer）**：footer 阶段进度「轮次0 准备 ░░░」在整个编写期不更新，直到合并才跳「编写」——阶段滞后一拍。
- **P2-4（引擎文案）**：escalated reason 在 fork ok:true 场景笼统猜测 wallclock watchdog，与 events 事实矛盾，误导排障。
- **P2-5（cmux 驱动经验）**：`send-key` 发普通字符（如 o）无效需用 `send`；数字/字母键均同理——写入 team 操作手册。
- **P2-6（cmux 传输·中文 UTF-8 损坏）**：Other 中文长文本经 cmux send 落盘后多字节边界字符损坏（"重"→U+FFFD，572741 facts 数据层实证）；语义可上下文恢复但有保真风险，长中文答案改选项号短答或先写 workspace 文件引路径。
- **P2-7（引擎·user-facing 术语泄漏）**：欠定选项描述含形态令牌（member/dist/captured_relation），内部术语在给用户的裁决面板泄漏，普通用户读不懂"断言形态按 member"。
- **P2-8（TUI 计时器）**：断线重连后底栏思考计时显示异常累积（"12h 25m" 实际约 3h）。
- **P2-9（我的过程教训·非引擎问题）**：批 2 收尾误读滚动历史臆想"交付完成"——只据当屏实时 engine_report.json 时间戳汇报，绝不凭一屏推断交付状态。
- **P2-10（引擎·rr/wrr 跨案时序污染）**：整卷连跑时前序 rr/wrr 案改变设备共享轮转计数器，后续同类案（778012/778041/593573）单卷 pass、整卷 contradicted——设备侧共享态，非编译缺陷；引擎有 contradiction 上限自动降级保护（非无限重编）。建议：同类案考虑整卷内加 clear/隔离前置，或归为"整卷时序依赖"已知限制。
- **良性确认（非缺陷，正面记录）**：①欠定数学门（分布恒真检测、最小可验请求数推导）正向工作，防 577976/593516 历史坑回归；②contradiction/round-cap 自动降级保护存在；③断网 checkpoint 续跑幂等；④欠定案"从未问到"如实入账不静默；⑤自愈环 uncertain 观察入库；⑥G4 echo 对 freeform 答案回显解析结果请用户核对（对照批1 035413 静默误归是改进）。
