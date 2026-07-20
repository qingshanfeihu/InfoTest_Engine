# #54 首批校准编译闭环·取证报告（SLB/SSL calibration）

> 2026-07-20 · Test-Eng · #54 首批校准（SLB-first）。TUI PID 74687 载 6b3dfdba（#52 enablement）。脑图 `workspace/inputs/automatic_case/slbssl_calib.txt` 3 卷。**calibration：surfacing gaps IS the deliverable**。

## 批 setup

| 卷 | autoid | 内容 | 断言溯源 |
|---|--------|------|---------|
| SLB 纯配置存在性 | 205400…001 | slb virtual tcp+real+group+policy，断言 show slb 反映 | G1/G2 config-face |
| SLB G4 健康翻转 | 205400…002 | real 好 231:80 health on→UP / 改坏 213:666→DOWN | sdns_support_slb_3 §3.1 |
| SSL 证书导入 | 205400…003 | ssl host virtual→importKey/Cert/RootCA→activate→show ssl certificate | ssl_usage_patterns §3.1 |

## round1 verdict（delivery:0）

- **001 SLB 纯配置：PASS ✓ + writeback（targets=[precedent,footprint]，provisional=false）**——**首批 PASS 真写回先例+footprint，SLB/SSL 判例层自愈积累启动**。
- **002 SLB G4 健康翻转：fail → reflow repairing**（见 FINDING #2）。
- **003 SSL 证书导入：not_run（编写中，round1 未上机）**。

## 正面（gates validated on real SLB/SSL content，leader fastlog 确认）

- **#56 execute-action 门 FIRED on 003**（`execute_action_not_in_r…` reject）——real first-batch content 上如设计触发。
- **command-existence 门 fired**（10.5 手册命令集校验）。
- **structural 门 caught 001 comma-assertion**。
- 三卷 worker self-correct 后产出 structurally-correct xlsx。**门在新域工作**。

## ⚡ FINDING #1：mirror sandbox dead pointer（leader fastlog 捕，非阻塞·design-fix after batch）

003 worker `fs_grep knowledge/framework`（欲读 cert method signatures from `mirror/ssl_comm.py`）→ `path outside agent sandbox — only knowledge/data/ or workspace/`。**mirror 在 `knowledge/framework/mirror/`、worker 沙箱外**——`contracts.md` 的「fs_read them from the mirror」对 forked worker 是 **DEAD POINTER**（只有引擎 gate code 直读 mirror）。003 via reachable sources（contracts.md sm2 inline note + EXCEL_FUNCTIONS.md + domain_grammar.json）recover，**非阻塞但浪费 worker turns + 风险 under-informed authoring**（若某 method detail 仅存 mirror）。**design-fix（批后决策）**：project into knowledge/data / inline in contracts / extend sandbox read-only。**待核**：003 authored cert steps arg counts（importKey 2-arg）despite mirror block 是否正确（编写完补）。

## ⚡ FINDING #2：SLB health 观测透镜 gap（Test-Eng 捕·脑图造错·attribution 正确 surfaced）

002 attribution（layer V·disposition reflow）verbatim：
> `show statistics slb virtual tcp hvs` output contains no Health: line — only traffic counters and hits. Precedent cases read `Health:\s+UP / Health:\s+DOWN` from `show statistics sdns service ip` (SDNS context), not from slb virtual statistics.

**根因=我造脑图 002 观测透镜造错**：用**纯 SLB 面**（`show statistics slb virtual`）观测 health，但设备 slb virtual statistics **无 Health: 行**（只 traffic counters）——**health 维度须经 sdns service 面**（`show statistics sdns service ip "0_vs1"`）。
- **印证** slb_usage_patterns §3.1「观测透镜」警告：「即便最纯 SLB-face 卷，健康态也主要经 sdns 服务透镜看，印证 SLB 在本语料恒 embedded 于 sdns」。
- **修正 #53 item5**：pure-SLB 观测**命令独立存在**（show statistics slb global/connection 结构化 sane output）**但 health 维度不完整**——health 观测必须经 sdns service 面（slb virtual 有 traffic counters 无 Health）。
- **attribution 正确诊断**（reflow：改 sdns service 面 or 找 SLB-native health 命令）——**calibration 正确 surfaced 这个观测透镜 gap**。
- **教训**：造 SLB G4 脑图观测意图应指向 sdns service 面（或让 worker 自主择透镜），非硬指 slb virtual。002 reflow 后待看 worker 是否改对透镜。

## 最终结果（批 closing 21:58）

**最终 2/3 PASS**：
- **001 SLB 纯配置存在性：PASS ✓** + writeback（先例+footprint 自愈启动）。
- **002 SLB G4 健康翻转：reflow 后 PASS ✓**——**自愈成功**：FINDING #2 attribution 正确诊断（health 须经 sdns service 面）→ worker reflow 改观测透镜（slb virtual→sdns service 面）→ round2 pass。**证明 attribution→repair loop 在新域 end-to-end 工作**。
- **003 SSL 证书导入：escalated**（唯一未过）。

## ⚡ FINDING #3：003 SSL escalated·standalone YES interactive-confirmation（机读账定谳，纠正观察推断）

**⚠ ROOT CAUSE 纠正（2026-07-20，leader+LLM-Eng 读 003/needs_decision.json 机读账定谳，覆盖我的观察推断）**：
- **机读账（003/needs_decision.json）authoritative：唯一 claim = `command_existence` for command=`YES`（standalone）**，来自 provenance:49 `"G": "ssl activate certificate vh1, prompt=YES"` 的 `, prompt=YES` annotation **emit 了一个 standalone `YES` 命令**（interactive-confirmation 被当成独立命令）。
- **根因（正确）= worker authored interactive-confirmation `YES` 作 standalone command（错误 `, prompt=YES` 语法）+ importCert 后多余手动 re-activate（importCert 已 auto-activate）——same class as yzg 的 tftp→YES interactive-prompt bug**。
- **我原归因的 show/clear forms（`show ssl certificate vh1 simple` / `clear ssl host vh1`）是错的**：LLM-Eng tested `match()=True`（门**接受**它们）、`simple` 是 documented display_mode、且它们 downstream of breakpoint（not_run，未到）——**observation-based inference from provenance G 值 didn't match actual rejected command**。
- **教训（机读账优先于观察）**：我该读 primary source `needs_decision.json`（机读账）而非从 provenance authored forms 观察推断被拒命令。verdict/layer 不变（003 escalated、knowledge-layer fix、SLB 2/2），只 correct specific failing token（YES 而非 show/clear）。
- **#58 fix 对应**：SSL interactive-confirmation enablement（`, prompt=YES` 语法正确处理 + importCert auto-activate 知识），#58 lands 后 re-calibrate 003 validates。

**⚡converging vs looping 定性（leader 完整 fastlog+provenance 确认，zero (b) signal）**：**(a)-not-(b) 确认**——worker hit #56 execute gate **ONCE 就 DROPPED execute action、converged to show-based verification**（无 oscillation on 任何 no-match execute → execute 维度**也无 capability-gap signal**）。escalation **纯 show/clear form-precision**：`show ssl certificate vh1 simple`（`simple` mode invalid in 10.5）+ `clear ssl host vh1`（invalid teardown form）；**base `show ssl certificate vh1` IS valid**。
**根因确认细节（leader 补，我原缺）**：`kb_footprint → not found for 'ssl'`——**literally 无 SSL footprint node**，worker authoring observation form **blind**（probed dev_probe + grepped manual，只找到 ambiguous `show ssl certificate (没有必要)` cell）。**≠ capability gap**（能力/命令都在），**= knowledge gap**（无 SSL footprint 引导 worker 到 valid 形态）。
**#58 fix scoped（leader 定）**：SSL-observation footprint node with valid 10.5 forms。**#58 lands 后 Test-Eng re-calibrate 003（single case）到 PASS**。

## mirror-sandbox loop closes（FINDING #1 结论）

003 **cert-import 核心步骤 authoring SOUND**：importKey/importCert/importRootCA **全 2-arg**（#50 CC2 held up，RSA 2-arg 非 sm2 3-arg）+ cert path **local-branch `cert/epolicy_ssl/rsaca/1024rsa.*`**（CC3 held up）+ **无 inline truncation**（路径引用非 inline PEM）→ **reachable sources（contracts sm2 note + grammar + EXCEL_FUNCTIONS）SUFFICIENT，mirror dead pointer 非阻塞 cert authoring 正确性**。FINDING #1 的 design-fix（project mirror→knowledge/data / inline contracts / extend sandbox）**优先级=低**（cert 核心 authoring 未被 mirror block 伤到）。

## digest held up 评估（#50/#51 知识 vs 真机）

- **CC2（importKey 2-arg RSA）** ✓ held up（003 authored 全 2-arg）。
- **CC3（local-inline cert path）** ✓ held up（cert/epolicy_ssl 形态）。
- **FINDING #2 观测透镜**（health 须经 sdns service 面）：#5/§3.1 知识 held up，attribution 正确引用。
- **sm2 3-arg**：本批 003 是 RSA、未涉 sm2（后续 sm2 卷验）。

## 收批结论

- **SLB 达标：2/2 PASS**（001 纯配置 + 002 G4 健康翻转 reflow 自愈救回）——SLB authoring sound，attribution→repair loop 新域工作，首批 PASS 写回先例+footprint 启动自愈。
- **SSL 未达标：003 escalated**——cert-import **核心步骤 sound**（arg/path/form 全对、digest held up、mirror 非阻塞），但 **worker 把 interactive-confirmation `YES` authored 成 standalone command**（错误 `, prompt=YES` 语法）+ importCert 后多余手动 re-activate（importCert auto-activates）=escalated 根因（**机读账 needs_decision.json 定谳**，same class as yzg tftp→YES interactive-prompt bug）。**建议 SSL 补 enablement pass**：SSL interactive-confirmation 语法处理 + importCert auto-activate 知识 + SSL-observation footprint node（#58）。
- **gates 全 validated on real content**：#56 execute 门 fire（003）+ command-existence 门 fire（003 standalone YES）+ structural 门 fire（001 comma）。
- **两瑕疵**（非 digest 错）：①全角逗号"，"（worker authoring 笔误，emit 应归一化半角）②interactive-confirmation YES 被 authored 成 standalone command（worker 引导需补 #58）。

## #58 后 re-calibrate 003 结果（2026-07-19 23:24，单卷 slbssl_calib_003，TUI 22932 载 360e730c/09373283）

**结果：003 re-calibrate 又 escalated（0/1，非 PASS）**——evidence-first 读 `slbssl_calib_003/unfinished/003/needs_decision.json` 机读账（**#54 lesson 执行：读 primary source、非 provenance 推断**）。

**四 proof points 实证**：
- **(a) footprint reachable ✅ 生效**：worker `kb_footprint(ssl host)` → `ssl.host: ssl host {virtual|real} <host_name> [slb_service] (+6)`；`kb_footprint(ssl activate)` → `ssl activate certificate <host_name>...`；`kb_footprint(show ssl certificate)` → `ssl.certificate: no ssl certificate...` ——都 **RETURN node**（非 #54 "not found for 'ssl'"）。**#58 footprint retrieval fix 坐实生效**（whole-domain disconnect 修复）。
- **(b) YES/activate ✗ 部分**：needs_decision claim①=**`command_existence` command=`YES`**（"命令『YES』在 10.5 手册未命中"）——**standalone YES 仍在**，#58 SSL footprint node 的 YES/auto-activate knowledge **reach 了但没阻止 worker 把 `, prompt=YES` authored 成 standalone YES 命令**。（redundant re-activate 未再现=可能已修，但 YES 本体形态仍错。）
- **⚡新 gap（#54 未暴露）**：needs_decision claim②=**`missing_teardown`**——`ssl host virtual vh1` 是网络层配置写（框架 per-case cleanup 够不着）、无案尾恢复步，机械派生 tau=`no ssl host vh1`（paired-teardown gate；233/203 六次拆床实证的同类）。
- **(c) 003 PASS ✗**（0/1）/ **(d) node promote 未触发**（未 PASS、validity:uncertain 未升 verified）。

**结论（SSL launch-readiness）**：**#58 的 footprint retrieval fix 生效（(a)✅ whole-domain 修复坐实），但 SSL enablement 仍两处不足**——①**YES 交互确认知识**（footprint node 有 knowledge 但没让 worker 避开 `, prompt=YES`→standalone YES 的形态陷阱）②**未覆盖 missing_teardown**（ssl host virtual 需案尾 `no ssl host`）。**SSL 仍未 launch-ready，需 #58 再补一轮**：YES 语法根治（`, prompt=YES` 不 emit standalone YES）+ SSL teardown 知识（ssl host 配对 no ssl host）。**#54 lesson 复用成功**：读 needs_decision.json 机读账直接拿到权威两 claims，未再从 provenance 推断。

## ⚡ needs_decision emit-gate claims 是 two false positives（leader 完整视图纠正·教训再升级）

**leader+orchestrator 完整视图纠正**：上节我报的两 claims（YES standalone + missing_teardown）**都是 emit-gate false positives**：
- **YES claim 误报**："YES" 是 `ssl activate certificate` 的**交互确认字**、非独立命令（gate 把 `, prompt=YES` 的 YES 误当独立命令去手册匹配）。
- **teardown claim 误报**：teardown **实际已有**（案卷行 40:`clear ssl host vh1`）——gate 漏看了。
- **真 blocker=中文全角逗号"，"**（importKey 的 `vh1， cert/...` 全角逗号使参数解析错）。
- **教训再升级（比 #54 更深）**：**needs_decision.json 是「gate claim 了什么」的机读账，但 gate 本身可能误报/陈旧；device error（上机实测）才是 ground truth**。我上节读机读账（#54 lesson 对了）但**把 gate claims 误当真根因**——漏了「gate 可能错」这层。归因链正确姿势：读机读账拿 claim → 但 claim 需 device run 验证 → device error 才是终判。（#62 = ledger 卫生：清 resolved/stale claim 根治此类误导。）

## 🎉 #61 后 clean-recompile 003·SSL saga 最终 proof（四点全成立，2026-07-20 00:50）

**#61（1e0e0298，comma auto-normalize）后 CLEAN-RECOMPILE 003（非手改、非 resume、全新 thread）→ PASS via engine self-heal**。四 proof points 全成立：
- **(a) engine normalize 全角逗号 ✅ 直接实证（升级·leader 补全）**：`runtime/logs/k_signals.jsonl` 有 003 记录 `{"signal": "fullwidth_comma_normalized", "subject": "205400000000000003", "source": "compile_emit", "payload": {"count": 3}}`——**worker 照打全角逗号 → 引擎 compile_emit auto-normalize **3 处**（importKey/importCert/importRootCA）→ case.xlsx 落半角","**，机制链完整、非推断。〔证据边界补全教训：`fullwidth_comma_normalized` signal **落 `k_signals.jsonl`、不落 fastlog/facts/events**，故我原 grep 三处未命中、退而用 case.xlsx 半角逗号+PASS 作间接推断并诚实标边界——leader 核出 k_signals 记录后升级为直接实证。**signal 核查以后先看 `runtime/logs/k_signals.jsonl`**。〕
- **(b) 003 PASS via ENGINE delivery ✅**：verdict `result=pass, ctx=delivery, run:3e2d571e:delivery:0`（引擎自己的整卷复验、非 manual re-verify），build 585。
- **(c) delivery_report 1/1 PASS ✅**：`1 个通过整卷复验，已入交付卷`，engine_report deliverable=1，**无 REPORT_MISMATCH**，delivered 目录=1。
- **(d) writeback 自愈闭环 ✅**：`targets=[precedent,footprint] provisional=false`（validity:uncertain→verified，self-healing loop 闭环）。

**#54 saga 完整闭环**：003 首批 escalated（全角逗号+gate 误报）→ #58 footprint retrieval fix（footprint 通了、但逗号未治）→ re-calibrate 仍 escalated（卡全角逗号）→ #61 comma auto-normalize（scale 修）→ **clean-recompile PASS via engine self-heal（engine 自动修 CJK-artifact 全角逗号→003 无人工干预 PASS→写回先例+footprint 自愈闭环）**。

## 最终结论

**SSL TRULY launch-ready！两域全达标：SLB 2/2 PASS（001 纯配置+002 G4 reflow 自愈）+ SSL 1/1 PASS（003 clean-recompile engine self-heal）**。#54 首批校准闭环 END-TO-END 证明扩展工作：编译→上机 oracle→归因→修复轮/工程补丁→真 PASS→写回自愈。**可 proceed #55**（真实脑图放量、对齐 4 脑图准入）。gates 全 validated、digest（CC2/CC3）held up、engine self-heal 坐实。**两条 evidence-first 教训固化**：①读 needs_decision.json 机读账非 provenance 推断（#54）②gate claims 可能误报、device error 才是 ground truth（#58 re-calibrate）。

## Leader 复核注（2026-07-20，Theory 措辞审定，适用于本文档与 user_observations 台账）

- 「gate claims 可能误报、device error 才是 ground truth」的精确表述：**限于「内容相关判断被塌缩进 L_struct」的那类 claim**（#54 两误报即此类）——不得推广为 L_struct 门族整体降 advisory（那是 GA-CUT 的反向回归诱因，(47) L_struct 判据与 §0「结构门留」不动）。
- 本文档所称「engine self-heal / 引擎自愈」（#61 全角逗号）术语校正为 **「emit 期机械归一化」**（A 层门修复，含 .py 变更）；「自愈」一词保留给判例层零代码增长与 (d) writeback 闭环，防与「自愈合四层封闭」定义漂移。
