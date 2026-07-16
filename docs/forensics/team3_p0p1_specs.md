# team3 · P0/P1 修复可实现规格(逐项规格卡 + 依赖图 + 分工 + yzg 重跑验收清单)

> 输入:`team_final_synthesis_fix_plan.md`(P0=A1/A2/D9,P1=C5/C7/E10a/E10b/F11+N1+N2/D8/B1'/H13H14)、
> `team2_zhaiyq_live_review.md`(N1/N2 实证)、`team2_code_align.md`、`team_design_behind_logic.md`。
> 方法:**全部 file:line 锚点为 2026-07-16 当日实读钉死**(非转抄 fix plan——fix plan 的 `nodes.py:2270-77`
> 实为 awaiting_user_unasked 兜底块,真正的入库腿在 `uncertain.py:47`,已按实况更正)。
> 边界:team2 已落地 emit_tick 三态并卷 / needs·user_decision 原子写 / 交付卷组成门 / ask 空 Other 防呆 /
> 单测密闭化——本篇零重复设计,只在接缝处引用。
> 红线:本篇为规格,不改任何代码;所有行号在实现时需 re-verify(活分支仍在动)。

**公共背景(各卡引用)**:
- 事实流 append-only,`att[-1]`(最新条)生效——处置类修复动「读法/记账」不动「事实覆盖」。
- 处置消费三点:author 重编过滤(`nodes.py:364-367`,只收 reflow/frozen/defect_candidate)、
  merge 复跑集(`nodes.py:751-769`,rerun_isolated/transient)、env_blocked→escalated 信号(`nodes.py:1445-46`)。
- 用户来源归因带 `evidence:"user"`(`nodes.py:2120-2136`),权威高于一切机械律((36) 写权律)。
- 回归基线:`pytest tests/ -q` 忽略 `test_batch_compile_tools.py`(5 个 SSH 环境依赖失败非回归)后 **2007+ passed**。

---

## 一、P0 规格卡

### 卡 A1 · fail_signatures 结构化解析(B1+B2 双 bug 一刀)

**一句话**:签名抽取从「无分隔拼接 + 裸 grep "fail to find"」改为按框架裁决行 `#### (Fail|Success) Num` 结构化解析,只收 Fail。

**规格**:
- 改动点:`main/ist_core/tools/device/batch_tools.py:871-879`(`_fail_signatures` 函数体重写);
  复用同文件既有 `_WA_CHECK_RE:946-947`(`^#### (Fail|Success) Num \d+: (fail to find|successed to find):? (.*?) in ?: ?(.*)$`)
  与 `_WA_TS_RE:945`(时间戳前缀剥离)。**函数签名 `(text)->set[str]` 不变**,四个调用点不动语义:
  digest 显示 `:1163`、跨轮交集 `:1199-1200`、落盘 `:1257-58`。
- 语义:逐行处理——先 `_WA_TS_RE.sub` 剥时戳,再 `_WA_CHECK_RE.match`;**仅 group(1)=="Fail"** 的行取
  group(3)(pattern 文本)归一化空白后 `[:60]` 入集合。Success 行(通过的 not_found 断言,B2 病灶)与
  一切非裁决行(节头/文件名/RTNETLINK,B1 病灶)天然出局——锚定 `^####` 即免疫。
- 兼容腿:全文零条结构化 Fail 行且含旧式 `fail to find` 文本时回退旧正则(老日志/异构框架版本留声),
  回退时该轮签名标记不参与冻结判定?——**不**,简单化:回退结果照常参与(与今日行为等同,不新增分支语义)。
- 调用点微改(B1 分隔符):三处 `(causality or "") + (detail or "")` 拼接改为 `"\n".join((causality, detail))`
  ——行级解析下拼接边界不再产生跨段假行。

**爆炸半径**:`.frozen.json` 的 `signatures` 字段内容变化(更干净);`last_run.json` `_fail_signatures` 字段;
digest fail 行表尾显示;**跨版本一次性软化**——升级后首轮 `sig_now(新格式) ∩ sig_prev(旧格式)` 可能为空,
冻结判定迟一轮触发(下一轮双侧同格式自愈)。brief `_round_evidence` 不读签名,worker 无感。

**失败模式**:①框架裁决行格式漂移(新框架版本改 `####` 前缀)→ 签名恒空 → 冻结门失效(比误冻结安全,
但静默)——兼容腿 + 「结构化零命中但旧式文本命中」时 log warning 留声;②pattern 含正则元字符跨行截断
→ group(3) 已是单行捕获,无此问题;③同一 expect 多断言实例——集合语义本就去重,符合「同/异判定」契约(:874)。

**回归测试**(新增 `tests/ist_core/tools/test_fail_signatures.py`):
- `test_success_notfound_excluded`:含 `#### Success Num 1: fail to find: X in: Y` → 不入签名(B2)。
- `test_section_headers_not_captured`:构造 dongkl 型「日志节头+文件名紧邻 fail to find 词面」→ 零污染(B1)。
- `test_causality_context_boundary_no_merge`:causality 尾 + device_context 头拼接处无跨段假签名。
- `test_timestamp_prefix_stripped`:带 `2026-07-14 11:47:00 ` 前缀的 Fail 行照常命中。
- `test_legacy_fallback`:零结构化行的旧文本 → 旧正则结果。
- 验收器(fix plan §五.2):dongkl 9 案 attr_evidence 重提取等值校验——attr_evidence 在 workspace 不入 git,
  以脱敏 fixture 固化真实回显形态进上述测试;实卷等值扫用一次性只读脚本(scripts/debug/,不入 CI)。
- 必须保持绿:`test_perf_gates.py`、digest 邻域、全量基线。

**回退开关**:`IST_FAIL_SIG_STRUCTURED`(默认 **1/开**——旧行为即 bug,开关只为跨版本对照与紧急回退)。

**质疑**:是最小正确修复(复用现成正则、签名契约不变)。更简替代「只加分隔符」治 B1 不治 B2,不取。
证据充分(4/9 案签名脏 + 778072 语义反转,两队独立复核)。

---

### 卡 A2 · 观察入库补 S_SUSPENDED(自愈闭环接通)

**一句话**:入库腿的状态集从 {failed_terminal, escalated} 扩到含 suspended——门键从「案状态」向「观察价值」校正一步。

**规格**(fix plan 锚点更正:真腿不在 nodes.py:2270-77):
- 改动点①:`main/ist_core/compile_engine_v8/uncertain.py:47`
  `for aid in (led.in_state("failed_terminal") + led.in_state("escalated")):` → 追加 `+ led.in_state("suspended")`。
- 改动点②:`main/ist_core/compile_engine_v8/nodes.py:2287-2295` closing 的 `_Led` 适配器 `in_state`
  增映射 `"suspended" → V.S_SUSPENDED`(`views.py:33`)。
- 改动点③(语境标注):`uncertain.py:55-56` 的 ctx 兜底文案当前写死「fail/escalated 轮观察」——
  由调用侧传入或按案状态渲染为「fail/escalated/挂起轮观察」;note 非空时仍取 `note[:120]`(不变)。
- **数据形态不变**:RawFact `validity="uncertain"` + `observed_under=ctx`(:58-63);observed_under 语境
  来源=`behavior_candidates.json` 每条的 `note` 字段(attributor fork 经 `submit_behavior_fact` 落,
  见 `tools/knowledge/behavior_tool.py:69`、attributor 白名单 `compile-attributor.md:4`)。
- 水源确认(实读):挂起案凡经归因 fork(如 zhaiyq 532862 defect_candidate)通常已有 behavior_candidates;
  **从未进归因就挂起的案(欠定径直 ask→suspend)天然无候选=no-op**,这是正确语义(无观察可入),不是缺口。

**爆炸半径**:closing 节点内一个 try 块;footprint nodes/*.json 多 uncertain 条目;渲染层观察组
(footprint_lookup 纯计数组头)。merge_fact 按 fact_key(内容 sha1)幂等——挂起案下批复活再挂不重复入库。

**失败模式**:①挂起案观察质量低(编写中途挂起,行为观察或基于半成品卷)→ 污染判例?——防线即
validity=uncertain + observed_under 语境,worker 被教导「按语境自判、冲突设备实验仲裁」(worker.md L69-70),
且 PASS 实证才升 verified(`test_uncertain_upgrade_on_pass_no_downgrade` 已锁);②观察量增大挤占渲染配额
(rest_behaviors[:3] 型)——观察组机制本就为多语境并列设计,不新增风险面。

**回归测试**:
- 新增 `tests/ist_core/memory/test_self_healing_loop.py::test_suspended_case_observations_ingested`
  (挂起案 + behavior_candidates → RawFact 入库,validity=uncertain,observed_under 带语境;fix plan §五.3)。
- 必须保持绿:同文件 6 个既有测试(尤其 `test_env_kill_switch`、`test_verified_entries_stay_clean`)、
  `test_render_closing`、`test_volume_composition_gate`(closing 邻域)。

**回退开关**:细粒度 `IST_INGEST_SUSPENDED_OBS`(默认 **1/开**);总闸 `FOOTPRINT_UNCERTAIN_WRITEBACK=0`
仍在上层整体关断。默认开理由:zhaiyq 实弹丢的是 defect_candidate 级观察,损失>风险,且 uncertain 门已隔离。

**质疑**:最小正确。更彻底的「门键改挂观察价值(attribution 达 defect_candidate 即入库,无论案状态)」
是正确长期方向但要动入库触发时机(closing 之外),留 N1 报告层 floor 承接其可见性,本轮不扩。

---

### 卡 D9 · brief 注入措辞去事实化(止「前提洗白」链)

**一句话**:脑图预期标注为「作者预期(设备未证实)」、上轮归因标注为「假设」——只改信封措辞,不动数据与结构。

**规格**:
- 改动点①(意图侧):`main/ist_core/compile_engine_v8/briefs.py:177-178`
  `<intent note="this case's intent; full text at manifest_path">` 的 note 扩为(英文,LLM-facing):
  「this case's intent; the desc lines are the requirement; **each `expected:` is the author's
  anticipated outcome, not device-verified fact — ground it (manual/precedent/probe) before
  encoding it as an assertion**; full text at manifest_path」。`intent_summary`(:15-25)正文
  `→ expected:` 词面不动(测试与既有消费稳定)。
- 改动点②(归因侧):`briefs.py:76-79` 文档头与 fix_direction 包装改为
  `attribution="{sig}" status="hypothesis"` + `<fix_direction confidence="hypothesis"
  note="prior-round attribution — a hypothesis to re-verify against this round's echo, not
  established fact">…</fix_direction>`。`[:800]` 截断、响度降级布局(信封→数据→意图→指令)全部不动。
- **不动**:`:121-129` round_task 既有「Before adopting any prior attribution, answer independently…」
  (与①②形成同向三点);`:133-164` `<user_adjudication>`——用户裁决是最高权威,**严禁**被本项措辞连带弱化
  (测试锁,见下)。
- eval-first(CLAUDE.md 红线):改前先落测试锚,改后 yzg 重跑即对照轮。

**爆炸半径**:每个 retry brief 的两处 XML 属性/note 文本;worker 对 fix_direction 的采信倾向(预期行为变化:
777976 型「顺着错误归因把 Hit:0 解释成步序」被削弱)。round1 brief 无 fix_direction,仅 intent note 变化——
对一次直过的案影响≈0。

**失败模式**:①矫枉过正——worker 连**正确**的归因也不信,收敛变慢/重复自查烧 token。缓解:措辞是
「re-verify against echo」不是「distrust」;②hypothesis 标记与 user_adjudication 的「highest authority」
并存时 worker 混淆权威序——两块物理分离(document 头 vs 独立 adjudication 节)且后者措辞不动,风险低;
③下游若有人 grep `attribution="` 属性做机读(实读未发现代码消费,brief 是纯 LLM-facing)——实现时再 grep 一次确认。

**回归测试**(`tests/ist_core/compile_engine_v8/test_briefs.py` 增三例):
- `test_fix_direction_marked_hypothesis`:retry brief 含 `confidence="hypothesis"` 且 fix_direction 原文仍在。
- `test_intent_note_marks_expected_as_author_claim`:intent note 含 author/not device-verified 锚词。
- `test_user_adjudication_stays_authoritative`:裁决块仍含 highest authority 措辞(防连带弱化)。
- 必须保持绿:既有 10 例(布局门 `test_layout_envelope_first_data_top_instructions_last` 的
  `<device_evidence>→<intent→<round_task>` 顺序断言不破)。

**回退开关**:`IST_BRIEF_HYPOTHESIS_MARKUP`(默认 **1/开**;字符串条件分支,成本一处)。

**质疑**:最小正确(措辞层,零结构变化)。更强替代「fix_direction 不注入、只给 ref」——会丢掉正确归因的
定向价值(归因大多数是对的),不取。证据充分(777976 R2 逐字采信实证 + 洗白链三跳完整取证)。

---

## 二、P1 规格卡

### 卡 C5 · 判例回填(零代码,数据 + 一次性脚本)

**规格**:一次性脚本 `scripts/maintenance/backfill_footprint_observations.py`(新文件,只此一个入口),
复用 `uncertain.py` 同款 RawFact→route_facts→merge_fact 链(validity=uncertain + observed_under 带
批名/autoid/对照语境),`--dry-run` 默认、`--apply` 落库。条目清单(每条 content 必须逐字取自
`workspace/outputs/<aid>/attr_evidence.json` 原文,observed_under 引对照案):
1. 跨客户端各自轮转/p2 恒 Hit:0(777976/593484);2. Hit 计数语义——服务了成员却不计数(777976);
3. `show sdns host pool` 只列池名不列成员 IP(593516);4. `sdns host method <域名> wrr` 两种响应
——**双观察并列入库**(静默接受不生效@572672 早轮 / priority 报错@定稿 run,observed_under 各标语境,
文法条目等 C7 钉死,判例层先装);5. IPv6 会话保持超时条目不清除(532862,observed_under 引 IPv4 对照
517027);6-10. zhaiyq NEW-1~5(live review §1.2c,同法)。
**注意条目 2**:现存判例 3 条 Hit 观察指反方向(6b921beb 等)——uncertain 入库后与其自动成观察组,
worker 仲裁,这正是设计机制,**不删不改旧观察**。

**爆炸半径**:knowledge/footprints/nodes/*.json 增条目(git 可回退);检索/渲染面。
**失败模式**:content 转述失真→worker 学到二手叙事——脚本内置「content 必须是 attr_evidence 子串」断言
(同 `_substring_gate` 思路);fact_key 幂等防重跑翻倍。
**测试**:脚本自带 dry-run 输出比对;`test_self_healing_loop.py` 既有观察组测试保绿。
**开关**:无(手动脚本);尊重 `FOOTPRINT_UNCERTAIN_WRITEBACK`。
**依赖**:概念依赖 A2(同一条腿的语义),实现独立;建议 A2 合入后执行,dongkl 8 挂起案候选可顺带被 A2 覆盖。
**质疑**:证据充分(全部有 attr_evidence 原文)。唯条目 4 的响应条件未钉死——已按「双观察不裁决」处理,合规。

### 卡 C7 · 上机钉死 probe 清单(数据交付,执行待床)

**规格**:清单文件 `docs/forensics/team3_probe_checklist.md`(本队顺产)固化五问:
①pool Hit 计数器何时 +1(打流前后 show 对照);②落点是否绑定源客户端(双 Router 交替 dig 序列);
③wrr/ga weight/priority 必带性+层级(`sdns host pool` vs `sdns host method` 两级分别试)+ host method
两种响应的触发条件(绑定 pool 带/不带 weight 两态各试);④IPv6 listener 3ffc::70 连通性(zhaiyq NEW-5);
⑤记录类型↔service 族配对(AAAA 需池配 IPv6 service?——zhaiyq NEW-4)。
执行=床空闲后 `device-verify` 只读会话(**zhaiyq 真机在跑,本轮零执行**);结果落库:行为观察按
C5 脚本入 uncertain(observed_under="probe session <date> bed <host>"),**语法/参数必带性**类结论
钉死后才落 B1' 文法条目与 D8 措辞引用。
**失败模式**:probe 会话自身改床(误发 config)——清单逐条标注只读命令族,执行走 device-verify skill 的只读约束。
**质疑**:C7 是 B1' 数据与 C5 条目 4 的**前置证据闸**,本身无代码;不可降级(不钉死就写文法=写死未证实文法,fix plan 明拒)。

### 卡 E10a · verifiability 增客户端维度

**规格**:
- `main/case_compiler/verifiability.py:35-44` `CLAIM_KINDS` 增 `"cross_client_landing"`
  (「特定客户端命中特定池/跨客户端共享轮转」类主张);
- `check_verifiability` 增分支(样板=`absolute_position` 的双岔 :124-139):
  - `algo ∈ DISTRIBUTION_ALGOS` → `Verdict(False)`:reason=「轮转计数器跨客户端是共享还是各自独立由设备
    实现决定,rr/wrr 数学推不出『客户端N→池M』;该主张在无手册/判例支撑时不可证伪」,
    `suggested_fix=FIX_EXPECT`,notes=[可验等价:同客户端两次关系断言(relation_diff)/按客户端分组的
    分布区间;若手册/判例证实共享全局计数,按 rotation_order/absolute_position 重判]。
  - 非分布算法 → `Verdict(True)` 带 notes(确定性映射可能成立——地址族过滤即 777976 深层真机制,
    需手册/先例支撑,镜像 :126-131 措辞)。
- 工具壳:`verifiability_tool.py:142-146` docstring 的 claim_kind 枚举文本同步增该值(**docstring 是
  LLM-facing 契约,漏改=worker 不知道有这维**)。`_MECH_KINDS`(:358-359)不收——它是形态类 claim,
  改过程/改预期仍要 assertion_form,语义正确。
- 不加 `n_clients` 参数:判定不需要(claim_kind 已携语义),少一维少一处误传。

**爆炸半径**:纯新增枚举+分支;老调用零变化。needs_decision.json 可能出现新 claim_kind——ask 渲染按
claims 通用投影,无特判。
**失败模式**:worker 把「双客户端各发1次」这类**本可按 relation/分组分布验**的意图整案上报 → ask 虚增。
缓解:D8 措辞教「先分组证伪再报」+ notes 给出可验等价(worker 可按等价改写而非必问)。
**测试**(`tests/case_compiler/test_verifiability.py` 增):`test_cross_client_landing_underdetermined_for_distribution`、
`test_cross_client_landing_non_distribution_defers_to_manual`、枚举门(未知 kind 仍拒)保绿。
**开关**:无需(不传新 kind 即不触达)。
**质疑**:最小正确。证据硬(777976 全程未触发工具+工具无此维,项目自审 AUDIT_engine_gaps_round2 已认)。

### 卡 E10b · 序列↔周期自洽机械检查(rr-only)

**规格**:
- 新函数 `check_sequence_periodicity(period: int, found_idx: list[int], notfound_idx: list[int]) -> Verdict`
  (verifiability.py):RR 下单成员占且仅占一个模 `period` 剩余类(起点/池序未知只平移/置换剩余类,
  不改「恰一类」性质)——可满足 ⟺ `∃r∈[0,period): (∀i∈found_idx: i≡r) ∧ (∀j∈notfound_idx: j≢r)`。
  O(P) 枚举。矛盾 → `Verdict(False, reason=数学恒假说明, suggested_fix=FIX_EXPECT/FIX_PROCESS)`。
  778012 形态(前3 not_found + 后5 全 found,P=4)即恒假实证。
- **适用域收窄(GA-CUT 防线)**:仅 `algo=="rr"`(等权、单槽剩余类模型闭合于数学);wrr 成员占哪些剩余类
  取决于调度器交织实现(设备相关)→ 返回「not applicable」中性 Verdict(True + note),**不判**;
  ga/确定性映射不适用。
- 接线:`compile_check_verifiability` 增可选参 `sequence_json`(JSON 数组,元素 `"found"|"not_found"|null`
  按请求序;null=该次无该成员断言);提供且 claim_kind ∈ {rotation_order, absolute_position,
  new_member_last} 时**附加**跑本检查,矛盾则覆盖为 NEEDS_USER_DECISION(advisory 呈报,不越 §0.1——
  它是内容无关恒假,fix plan §二.3 已裁归属)。
- 触发依赖 worker 主动传序列(777976 教训:不调=不触发)→ D8 措辞补「时序锚点序列须与周期自洽,
  用 sequence_json 自查」;emit 侧 advisory 二道触发**本轮不做**(动 emit_xlsx_tool 半径大,列观察项)。

**失败模式**:①「found: 池名」与「found: 成员IP」混指同成员判定错位——检查输入是 worker 抽象后的
per-member 序列,抽象错=垃圾进出;文档写明输入语义(单一成员视角);②多成员联合约束(A found@1 ∧ B found@1)
不支持——单成员逐次调用即可,不做联合 SAT(过度设计)。
**测试**:`test_sequence_periodicity_contradiction`(778012 形态恒假)/`_satisfiable`(合法序列过)/
`_wrr_not_applicable`(fail-open)/`_period_one_edge`(P=1 全 found 可满足、任一 not_found 恒假)。
**开关**:`IST_SEQ_CONSISTENCY_CHECK`(默认 1;双门——还需调用方传 sequence_json)。
**质疑**:rr-only 是否太窄?——宁窄勿误杀(GA-CUT/(47) 双重背书);wrr 扩展待 C7-③ 钉死调度形态后作为数据升级。

### 卡 F11 · 对照差分机械触发(F11-a 证据注入形态)

**一句话**:引擎机械**采集**对照证据(同组兄弟 PASS/FAIL 分裂)注入归因孔;「同断言/同前提」的**判断**留在
L_model(attributor)——机械改 disposition 不做((47) 路由红线:对照条件的「多严」是内容依赖判断)。

**规格**:
- 改动点①(引擎侧采集):`nodes.py:1395-1402` attribute 的 fork env 已有 `batch_pass_examples`(泛批级);
  增键 `sibling_contrast`:按 manifest `group_path` 取同组兄弟(样板=briefs.py:183-200 的 F8a 兄弟块),
  分裂为 `{passed:[…], failed:[…]}`(aid 尾6+title 首行);同时落 `{"ev":"sibling_contrast","aid":…,
  "passed":[…],"failed":[…],"run_id":…}` 事实(报告/N1 消费,append-only)。
- 改动点②(attributor 指引):`compile-attributor.md` 增陈述段(高自由度,零写死):同组兄弟携同型断言
  PASS 而本案 FAIL,是「脑图前提被设备证伪」的机械证据——此时优先考虑 expectation_suspect(呈报改预期)/
  defect_candidate(带对照引文)出口,而非同向 reflow;引用对照案要引 aid 与回显原文。IPv4/IPv6、
  跨客户端对照同理(zhaiyq 517027↔532862 实证形态)。
- 改动点③(换证据面):「连续 2 轮同前提 fail 且无对照支撑→强制换证据面」**复用既有 frozen 通道**
  (同签名 2 轮→.frozen.json→emit 要求 override_frozen_reason 已在):attributor md + briefs 的
  defect-certify round_task(briefs.py:167-173 既有)措辞把「换法」显式细化到「换证据面
  (换观察对象/断言支点),不只换配置形态」。零新机制。
- **不做**:引擎按对照自动写 premise-falsified disposition——「兄弟 PASS 但环境不同/断言同型判定」
  是内容依赖判断,机械化即 GA-CUT 重演;机械只到证据装配为止。

**爆炸半径**:attribute env 一键 + 一类新事实 + attributor md 一段;fork 上下文增量 ≤ 兄弟行数(≤12 行封顶,
同 briefs 兄弟块配额)。
**失败模式**:①同组兄弟环境不同(不同 bed/轮次)造成假对照——env 里兄弟取**同一 merged 卷 composition 内**
的案(同床同轮窗),锚死对照条件;②组太大注入膨胀——沿用 [:12]+more 配额;③attributor 过度倾向
expectation_suspect → ask 虚增——措辞是「优先考虑」非「必须」,且 ask_panel 有子串门/已裁不重问护栏。
**测试**:`test_diagnose.py`(或新 `test_attribute_contrast.py`)增 `test_sibling_contrast_in_fork_env`
(rig 构造同组 1 pass 1 fail → env 含分裂 + 事实落账);attributor md 锚词入 skill 标准包门可选。
**开关**:`IST_SIBLING_CONTRAST_INJECT`(默认 1;关=env 不注入、事实不落)。
**质疑**:fix plan 原文「引擎 disposition 增机械触发」被本卡**有意降格**为「机械证据+模型判断」——
理由即 (47) 本身(fix plan §二亦承认这些判断内容依赖只能 L_model);全机械触发列为证据不足项(见 §五)。

### 卡 N1 · 处置单调律(记账+报告层,不动路由)

**一句话**:强出口(defect_candidate/expectation_suspect)一经引擎证据确立,后轮弱处置不得**静默**覆盖——
降档必须显式记账,报告层保底可见;路由照旧读最新条(defect-certify 环与用户权威不破)。

**规格**:
- 强度二分(不发明全序):强出口={defect_candidate, expectation_suspect};弱处置={reflow, rerun_isolated,
  transient, env_blocked, frozen}。
- 改动点①(降档记账):归因事实落账的引擎源三点——attribute 收账 `nodes.py:1438-1444`、G6 前筛
  `:1352-1358`、reconcile 机械归因 `:1055-1069`——落账前查该 aid 归因史:若「曾达强出口(evidence≠user)
  ∧ 本条为弱处置 ∧ 本条 evidence≠user」→ **照常落本条**(事实不篡改),同时追加
  `{"ev":"disposition_downgrade","aid":…,"from":…,"to":…,"round":…,"prior_evidence":…}` + `sh.emit` 警示。
  用户源(`evidence:"user"`,:2120-2136 五种)与 PASS 清零(案过了自然无归因)**全豁免**。
- 改动点②(fork 显式翻案通道):`submit_attribution` 增可选参 `supersedes_reason`(翻案理由,非空时
  downgrade 事实带 `acknowledged:true`)——attributor md 同步一句:降档必须显式说明推翻了什么证据。
- 改动点③(报告层 floor):closing/render(`render.py` 报告生成 + `engine_report.json`)增
  「缺陷候选(含历史达成)」节:任意轮达 defect_candidate 且无 acknowledged 翻案的案,无论终态
  (含 env_blocked/failed_terminal)都列入,带处置轨迹一行(`dc@r1→reflow@r3→env@r99` 型)。
  517027 型「最强出口早达被弱化覆盖」从此在交付物可见。
- **不动**:author 过滤(:364-367)、merge 复跑集(:751-769)、escalated 信号——路由语义零变化。

**爆炸半径**:三个落账点各一段前查;facts 流一类新事实;报告一节。视图(views.py)不读 downgrade 事实,九态投影不变。
**失败模式**:①早轮 dc 是误判 → floor 把假缺陷列进报告——轨迹行如实展示后轮改判,且「候选」本就非终判
(§11.7 缺陷确认权在人);逃生=fork 带 supersedes_reason 即 acknowledged,floor 剔除。误判代价=报告一行,
路由零代价——这是选记账不选硬粘性的核心理由。②downgrade 事实刷屏(反复 churn)——同 (aid,from,to) 幂等去重。
**测试**(新 `tests/ist_core/compile_engine_v8/test_disposition_monotone.py`):
`test_downgrade_appends_downgrade_fact`、`test_user_sourced_exempt`、`test_supersedes_acknowledges`、
`test_report_floor_lists_historical_defect_candidate`、`test_author_routing_unchanged`(dc 案照常可重编)。
既有:`test_facts_invariants`、`test_render_closing`、`test_diagnose` 全绿。
**开关**:`IST_DISPOSITION_MONOTONE`(默认 1;记账层零路由风险)。
**质疑**:证据硬(517027/600046 轨迹机读实证)。「硬粘性(拒绝降档落账)」被否——破坏 defect-certify
环(dc→换形态重试→再 fail 时 fork 需按新证据自由改判)与事实流 append-only 公理。

### 卡 N2 · 污染分歧裁决律(轻量记账变体默认,全量 ask 变体开关关)

**一句话**:「fork 判 s₀ ∧ 机械配对判无污染者」的分歧从只 emit 升级为落账;两轮分歧后**默认仍靠既有
contra≥2 兜底问询**,新增专用 ask kind 以开关关闭交付(证据未钉死,见质疑)。

**规格**:
- 改动点①(分歧记账,默认开):`nodes.py:1914-1917`(不升格分支)追加
  `{"ev":"s0_dispute","aid":…,"run_id":_g6_diag_key(...),"fork_h":"h_s0","mech":"no_polluter"}`
  (幂等键=run_id,同一 fail 裁决只记一次)。
- 改动点②(既有面板增语境,默认开):contra/cap 题面(questions.py)渲染时若该案有 ≥2 条不同 run_id 的
  s0_dispute → 题面附一行「fork 两轮判自污染而机械配对均无污染者——隔离复跑通过不代表整卷会过」
  (给用户裁决依据,不新增题)。
- 改动点③(全量变体,`IST_S0_DISPUTE_ASK=1` 才启):s0_dispute ≥2(不同 fail 裁决)后,该案最新
  rerun_isolated 处方不再入复跑集(`_rerun_disposed` :751-769 增一查),转 ask_contradiction 目标集新 kind
  `"s0_dispute"`,选项=床已治理复跑(→retry 既有 token)/转缺陷候选(→defect)/挂起(→suspend)——全部复用
  :2116-2158 既有 token 语义,零新 token。
- 消费护栏:`test_diagnose.py:170 test_attributor_s0_not_upgraded_when_mechanical_finds_no_polluter`
  锁住的「不升格」语义**不变**(N2 在其后追加记账,不改判定)。

**爆炸半径**:diagnose 一段、questions 一行(①②);merge 复跑闸+ask targets(③,开关后)。
**失败模式**:③开启后若 fork 的 s₀ 判定习惯性保守(高频 h_s0 候选),两轮即问=ask 虚增——这正是默认关的理由;
①②零此风险。
**测试**:`test_diagnose.py` 增 `test_s0_dispute_fact_appended`(幂等)、`test_s0_dispute_context_in_panel`;
③变体 `test_s0_dispute_two_rounds_blocks_rerun_and_asks`(开关开时)。既有 13 例全绿。
**开关**:①② `IST_S0_DISPUTE_LEDGER`(默认 1);③ `IST_S0_DISPUTE_ASK`(默认 **0/关**)。
**质疑(本队建议降级)**:实读 `facts.py:186-202`——subset-pass→delivery-fail 每次翻转 contra+1,
contra≥2 已有 ask 边(author:362 + reconcile 路由),**振荡今日已有界(≤2 次交付回滚)**;zhaiyq 533020
终态 failed 是否因用户停批而非兜底失效,facts 时序未查证。N2 的真增量=省 1-2 次设备轮 + 题面语境,
不是堵活锁。→ 建议:①②本轮交付,③连开关一起交付但**默认关**,待下一批 facts 复盘 contra 兜底触发率再翻默认。

### 卡 D8 · worker.md 补分布构造事实(高自由度陈述式)

**规格**(`main/ist_core/agents/compile-worker.md`,全部落 `<task>` 既有小节内,frontmatter/骨架不动):
- **分布段(L73-88)增两句**:①两个触发客户端不必然共享同一全局轮转计数——「客户端N→池M」类主张在
  判例/手册证实前按分布类对待,先用 `compile_check_verifiability`(cross_client_landing)证伪(接 E10a);
  ②统计计数器本身是待证事实:设备可返回成员却不计数(实机观察:成员在服务、Hit:0)——单一计数器
  不作唯一证据支点,证据面=命中集合∈存活成员 + 大样本占比(593516/778072 末轮「集合+区间+大量发包」
  是实机背书的正例形态)。
- **时序锚点句(同段)**:found/not_found 的位置序列必须与声明算法的周期可同时为真——rr 案用
  `sequence_json` 让工具做可满足性自查(接 E10b)。
- **探针段修洞(L104-108)**:现文「the command's line/column shape shows even on the clean compile-time
  device」对**输出依赖前置配置**的命令不成立(clean 设备输出空)——改为陈述两类:静态布局类命令
  clean 探针可得形态;绑定依赖类命令 clean 探针无信息,此时形态=先例/footprint/手册现查,
  **三路都取不到且断言依赖该形态时,这是欠定事实——上报,不掷硬币**(593516「承认未知仍猜 p4」反例);
  若断言可改写为不依赖未知形态的支点(如 dig 侧),优先改写而非上报(防 ask 泛滥)。
- **会话保持残影句(zhaiyq §2.3)**:保持超时后的下一次落点由运行时定,不假设落到特定池;验证轴是
  「条目状态变化」(清除/Timeout 归零)而非「落到某具体池」。
- 零写死命令红线自查:以上全部为现象+后果+why,无一条设备命令。

**爆炸半径**:worker 全部编写行为;≈+20 行 prompt。
**失败模式**:「未知就报」写强了→ask 泛滥(上文已内置限定与改写优先);token 增量挤占(可控,+20 行)。
**测试**:`test_skill_package_standard.py` + `test_prompt_structure.py` 保绿;建议增承重锚测试
(cross-client 句/掷硬币禁令句锚词在文——防未来误删,同「承重锚点保真」既例)。eval(fix plan §五.4):
对照轮产卷断言「WRR 案无精确 `Hit:\s*N`(GA 豁免)、无特定客户端→特定池断言」——落
`scripts/debug/eval_worker_redlines.py`(只读扫产出 xlsx,不入 CI,对照轮后手跑)。
**开关**:无运行时开关(md 文本;回退=git revert 单文件。双文案开关的漂移成本>价值)。
**质疑**:与 E10a/E10b 同 PR 交付(措辞引用工具新能力,先后错开=worker 被指到不存在的能力)。

### 卡 B1' · 文法层 co-required 参数类型(类型+空数据)

**规格**:
- 数据:`knowledge/data/compile_ref/domain_grammar.json` 增顶层键 `co_required_params`
  (现 19 键无它,实测):`{"_provenance":…, "rules":[{"id":"wrr-weight","trigger_statement":<stmt id>,
  "condition":{"param":"method","values":["wrr","ga"]},"requires_pattern":"…","scope":"…",
  "provenance":{"source":"manual §… / footprint 70b32add","confirmed_on_device":false}}]}`。
  **首发 rules=[] 空数组**——572708 两种响应未钉死(C7 前置),不写死未证实文法(fix plan §B 明文)。
- 加载器:`main/case_compiler/domain_grammar.py` 增 accessor `co_required_params() -> list[dict]`
  (样板 :103-108 fail-open `.get`)+ 纯函数检测器 `missing_co_required(rules, lines) -> list[dict]`
  (风格同 `dangling_references:124-159`:trigger 语句命中 ∧ condition 参数值命中 ∧ 同语句行
  requires_pattern 零命中 → 报 {rule_id, line, provenance})。
- 消费:`emit_xlsx_tool` 的 emit 成功路径追加 **advisory 文本行**(非门、不拒绝):
  「advisory: 行 X 配置 wrr 未见 weight/priority——手册/判例标注同语句共需(provenance…),请核对或说明」。
  worker 看 tool result 自查。**不进 lint 凭证判定**(违 (47) 的内容依赖硬门红线;命令头存在门
  `_gate_command_existence` 是签名闭集,本类是参数语义,不同类)。
- 承诺兑现:此后同类坑(如 zhaiyq NEW-4 记录类型↔service 族,若 C7-⑤ 钉死为硬约束)=纯加 JSON 条目零代码。

**爆炸半径**:load_grammar 加一键(additive);emit 返回文本尾部。rules 空=行为零变化。
**失败模式**:数据落地后误报(条件写宽)→ advisory 噪声训练 worker 忽略——条目必带 provenance +
confirmed_on_device 字段,C7 未证实的不落;detector 单测锁行为。
**测试**:新 `tests/case_compiler/test_domain_grammar_co_required.py`:`test_detector_flags_missing_param`
(合成 rule)、`test_empty_rules_noop`、`test_missing_key_failopen`。既有 grammar 消费者
(`test_s0_classes_data_driven`、`test_persistence_channels`)保绿。
**开关**:`IST_CO_REQUIRED_ADVISORY`(默认 1;rules 空天然静默)。
**质疑**:「一次代码支持新类型」本卡兑现;真正价值兑现依赖 C7 数据——若团队要压本轮范围,本卡可与
C7 一起顺延(纯 additive,晚落无债)。

### 卡 H13/H14 · 文档修订

**H13**(`docs/THEORY_k_state_machine.md`):三条款——(47) 补「自愈闭环覆盖条件」推论(观察入库必须覆盖
全部非 pass 归宿态,含 suspended,否则 L_model 前提不成立);(40) 补「对照差分=premise-falsified 机械证据,
优先级高于同向重编」触发判据;§0.1 补「序列↔周期自洽是内容无关数学恒假,归 L_oracle advisory」。
**H14**(`docs/DESIGN_dongkl_finalization.md`):四节——co-required 类型(B1' 形态与 C7 前置)、
S_SUSPENDED 入库(A2 语义:门键向观察价值校正)、fail_signatures 结构化(A1 契约)、brief 注入措辞(D9 三点)。
另按 team2_code_align D1/D2 顺笔:`_flush_then_close`→`_gather_or_close`、`_DOMAIN_TOKEN_RE`→
`_check_dns_label_limit` 措辞回填(同文档同轮,零成本)。
**顺序**:实现合入后写(文档跟代码,不预写);测试:无(文档);开关:无。

---

## 三、依赖图与实现顺序

```
A1 ──────────────────────────────┐(签名可信是后续一切跨轮取证的地基)
A2 ──► C5(同腿语义,脚本独立)      │
D9 ──┐                            │
E10a ─┼─► D8(措辞引用 E10 能力,同 PR)│
E10b ─┘                            │
F11-a ─► N1(共用归因史读法) ─► N2①②│
C7(待床) ─► B1' 数据 ─► (D8 补引用)  │
全部 ─────────────────────────► H13/H14(文档收尾)
```

**建议顺序**:①A1(独立,先行);②A2+C5;③E10a+E10b+D9+D8(一个 PR:worker 面一次换血,yzg 重跑
只吃一次 prompt 变量);④F11-a+N1+N2①②(归因面一个 PR);⑤B1'(类型+空数据,随时);⑥H13/H14;
⑦C7 待床空闲,回填 B1' 数据与 C5 条目 4。

## 四、分工切分(两实现者互斥文件所有权)

| 所有者 | 文件域 | 承担项 |
|---|---|---|
| **甲(引擎侧)** | `compile_engine_v8/{nodes,briefs,questions,render}.py`、`facts.py`(如需)、`uncertain.py`、`tests/ist_core/compile_engine_v8/**`、`tests/ist_core/memory/test_self_healing_loop.py` | A2、D9、F11-a(env+事实)、N1、N2①②③ |
| **乙(工具/文法/prompt 侧)** | `tools/device/{batch_tools,verifiability_tool,emit_xlsx_tool}.py`、`case_compiler/{verifiability,domain_grammar}.py`、`agents/{compile-worker,compile-attributor}.md`、`knowledge/data/compile_ref/domain_grammar.json`、`scripts/maintenance/backfill_*.py`、对应 tests | A1、E10a、E10b、D8、F11-a(attributor md 段)、B1'、C5 脚本 |

唯一跨界接缝:F11-a 的 env 键名 `sibling_contrast`(甲产乙耗)——先行冻结键名与结构
`{passed:[{aid_tail,title}], failed:[…]}`,两侧各自可测。docs(H13/H14/C7 清单)归本队或文档 owner,零冲突。

## 五、质疑汇总与降级建议

| 项 | 裁决 | 理由 |
|---|---|---|
| F11 全机械 disposition | **降格为证据注入(F11-a)** | 「同前提/同断言」判定内容依赖,机械化=GA-CUT 重演;(47) 与 fix plan §二自证 |
| N2③ 新 ask kind | **交付但默认关(IST_S0_DISPUTE_ASK=0)** | contra≥2 既有兜底已使振荡有界(facts.py:186-202 实读);533020 终态是否兜底失效未钉死——先记账①②,下批复盘再翻默认 |
| E10b wrr 扩展 | **不做(rr-only)** | wrr 剩余类占位依赖调度器实现,非数学闭合;待 C7-③ |
| B1' 数据条目 | **推迟至 C7 后** | 572708 双响应未钉死;先落类型+空数据 |
| C5 条目 4(host method 响应) | **双观察 uncertain 并列,不裁决** | 观察组机制本职 |
| A2 门键改挂观察价值 | **不扩(保留状态门+N1 报告 floor)** | 动入库触发时机半径大;floor 已保证 dc 级观察可见性 |
| D8「未知即报」 | **限定措辞**(三路检索穷尽∧断言依赖该形态∧不可改写支点) | 防 ask 泛滥反噬 yzg 验收 |

**证据仍不足、列观察项**:①zhaiyq 533020 的 contra 兜底是否真未触发(需 facts.jsonl 时序复盘,只读可做);
②E10b 的 emit 侧二道触发(等 worker 主动调用率数据);③`attribution="…"` XML 属性是否存在隐性机读方
(实现时 grep 终验)。

## 六、yzg 重跑影响逐项分析(用户验收轴)

基线:yzg 25/26 deliverable + 1 suspended(655233 VLAN)。逐项回答四问:成功率会不会降 / ask 数量与内容
变不变 / 655233 重问时发生什么 / 「除设备缺陷外全部输出」如何被保证。

| 项 | 成功率 | ask 数量/内容 | 655233 | 备注 |
|---|---|---|---|---|
| A1 | 不降(冻结判定更准;跨版本首轮冻结迟一轮=多给一次重编机会) | 不变 | 无涉 | 签名显示更干净 |
| A2 | 不变(closing 后置,零编译路径) | 不变 | 再挂起时其观察**这次入库**(改善) | — |
| D9 | 风险最低的行为变化:25 个 round1 直过案只见 intent note 措辞;retry 案 worker 对错误归因的盲从被削弱→收敛应更快 | 数量≈不变;内容更准(不再基于洗白前提) | resume 后重编 brief 带 hypothesis 标注 | 本项是 P0 里唯一碰 worker 输入的,重跑即其对照轮 |
| D8 | 不降(yzg 域非池分布,分布段休眠;「形态未知不猜」通用正向) | 可能 +0~1(仅当某案真踩「三路穷尽仍未知形态」)且是真问题非虚假 | 无特殊 | 措辞限定已防泛滥 |
| E10a/E10b | 零(yzg 无跨客户端/rr 序列 claim 即零触达) | 同左 | 无涉 | 纯新增能力 |
| F11-a | 不降(归因证据更全) | ask_panel 可能 +N,每个都携对照引文=真差异呈报 | 无涉(suspended 不进归因) | 期望效应:premise-falsified 案早出正确出口,少烧重编轮 |
| N1 | 不变(零路由变化) | 不变 | 无涉 | 报告缺陷候选节可能多列历史达成项=更如实 |
| N2①② | 不变 | 不变(仅既有题面加语境行) | 无涉 | ③默认关 |
| B1' | 零(rules 空) | 不变 | 无涉 | — |
| C5 | 不降(检索面更富;Hit 观察组促仲裁=多一次设备实验的正确成本) | 不变 | 无涉 | yzg 域与 sdns 池分布不同,多为休眠知识 |

**655233 重问机制**(同参续跑事实流续读):suspended 案进 `ask_targets` 的 suspended kind
(`nodes.py:1965-68` 优先序最末)→ ask_contradiction 呈报「挂起案新批恢复」→ 用户 resume(→resumed 事实
→复活→author/merge,composition 锚强制整卷重终验)或 keep(→继续挂起,报告如实)。本轮修复不改这条链的
任何 token/路由;变化仅:恢复重编时 brief 带 D9 标注、若其有 behavior_candidates 则 A2 已把挂起期观察入库。

**「除设备缺陷外全部输出」的代码保证链**(新旧合成):①九态全归属 footer/台账
(`test_footer_projection` Σ九桶==状态数,team2);②交付卷组成门(`_volume_composition_check`
nodes.py:2238-2252,leaked/absent 即降级如实,team2);③未答欠定显式入账
(awaiting_user_unasked,nodes.py:2262-2280);④N1 floor:达过 defect_candidate 的案必现于报告缺陷候选节
——四链合起来:每个案要么在主卷,要么在未通过卷+报告有名有姓有理由,设备缺陷候选单独立成节。

## 七、yzg 重跑验收清单(可勾选)

### A. ask 质量四条
- [ ] **A1 自然语言可懂**:逐题核 `workspace/outputs/<aid>/{needs_decision,ask_panel}.json` 的
  test_point/obstacle/equivalent/hypothesis 为完整中文句(无英文占位、无裸 JSON、无 raw 正则当句子);
  TUI 面板 cmux read-screen 抓屏人读一遍(团队只读,零按键)。
- [ ] **A2 不前后矛盾**:同案多题间 hypothesis 与 sides 引文一致;题面所述轮次/处置与
  `facts.jsonl` 该案 attribution 序列一致(fs_grep autoid 对账);已裁决(decision/adopted 事实在案)
  的同 question_id/同键差异未被重复呈报。
- [ ] **A3 选项真实有效**:每题选项 token ∈ 引擎已实现语义集(confirm/correct/defect/retry/suspend/
  resume/keep/stop/改过程/改预期/改描述);答后 footer echo-back「你的裁决→引擎理解为」与所选一致
  (G4,nodes.py:2113-15);统计 decision 事实 `freeform` 字段——`freeform:true` 占比高=选项不适配的
  机械信号(R5①),记录呈报。**注意 TUI 既知坑**:多题面板数字只高亮、每题必须 enter
  ([[tui-multiquestion-panel-key-semantics]])——验收时按此操作,勿把操作失误记成引擎丢答。
- [ ] **A4 无虚假问题**:每题溯源一条真实事实(needs_decision.json 的 claim / ask_panel.json 非陈旧 ts /
  contra≥2 / cap_reached / suspended);抽 2 题反查底层证据原文(attr_evidence/device_context)确认
  问题描述与设备实况相符;空 Other 防呆在位(team2 已修,答空不落假 decision)。

### B. excel 成功率 ≥25/26 对账法
- [ ] `manifest.json` cases N=26;`engine_report.json` 九态计数总和=26(零凭空消失)。
- [ ] deliverable ≥25;`case.xlsx` 实际 autoid 集(openpyxl 只读)== deliverable 集
  (且 facts 无 `volume_composition_mismatch`、报告无 delivery_incomplete 降级)。
- [ ] `case.xlsx` ∪ `unsuccessful_cases.xlsx` = 全集 ∧ 交集 = ∅。
- [ ] 与基线逐案 diff:上轮 25 个 deliverable 本轮仍 deliverable(允许换更优卷面,不允许无新证据转 fail);
  任何回退案必须在 facts 里有可指认的新证据(新 fail 裁决/用户裁决),否则记回归。

### C. 「选项处理后如实输出终卷」核验
- [ ] 每条 decision 事实向下游追链:改过程/改预期 → user_decision.json 在案 + 该案新 authored + emit 门
  按 expected_assertion_form 核对通过 + 终卷含该案;suspend/keep → 报告挂起节列名;defect →
  报告缺陷候选节列名;retry → 新 verdict 事实在案。**无任何 decision 之后零下游事实的「吞答案」案**。
- [ ] 655233:重问面板出现且题面带上批语境;用户任一选择后按上行追链闭环。

### D. 「除设备缺陷外全部输出」核验
- [ ] 非交付案逐案有名有姓:unsuccessful_cases.xlsx + delivery_report 未通过节,每案给层×处置×证据引文;
  唯一合法非 excel 结局=产品缺陷候选(§11.7),缺陷候选节含设备回显原文引用。
- [ ] N1 floor 生效:任意轮达过 defect_candidate 的案(含后轮被弱处置覆盖的)在缺陷候选节可见,带处置轨迹。
- [ ] awaiting_user_unasked=0(交互跑全程在场时);若非零,逐案核对是否真非交互窗口所致并记录。
- [ ] 回归全绿:`~/.venvs/infotest-engine/bin/python -m pytest tests/ -q`(忽略 test_batch_compile_tools 的
  5 个环境依赖)≥ 基线 2007 passed + 本轮新增测试全绿。

---

*team3 · 2026-07-16 · 全程只读(唯一写=本文件);行号为当日工作树实读,实现前请 re-verify。*
