# MEDIUM 批修 + 张力项标注(task #22)

> regression_risk_matrix.md 的 MEDIUM 项处置。**能机械修的修+测,有设计张力的标出交裁。**
> 只碰 S4 所有权文件(structural_gate.py + 其测试)+ 追加 S3 测试锚(append,不碰 nodes.py broken 路由段)。
> 未碰:nodes.py broken 路由(#17)/ worker.md(#20)/ engine_tool.py(#21)。

---

## A. 已修 + 测(机械可修)

### A1 · S4 DNS lint 误杀收窄(矩阵 §1#5) — DONE
**问题**:旧实现 `[A-Za-z0-9-]{64,}` 挂关键字门(`dig`/`host name`)后,对 dig 行**任意** 64+ alnum 串判违例=强字典误杀金标准形态(GA-CUT 型)。dig 行合法长 token 会被误杀:`+cookie=<hex>`、TSIG `-y hmac:name:<base64>`、64-hex → emit_merged 拒合并、好卷被切、merge 处静默难诊断。

**修法**(`structural_gate.py:_check_dns_label_limit`,已落):从"关键字行任意长串"改为**域名 token 的单标签长度**——双闸:
1. 行含 DNS 名承载命令(`dig`/`host name`/`host pool`/`hostname`);
2. token 是**纯域名形态**(`_DNS_NAME_TOKEN_RE`=LDH+点+下划线;跳过 `+`/`-`/`@` 前缀的 flag/query-option/@server;跳过含 `=`/`:`/`/` 等键材料字符的 token)。
再逐点分标签量长度 >63。**这是结构信号(域名 token 形态)而非命令关键字白名单**,守准则6「结构化事实非强字典」。

### A2 · S4 DNS lint 漏扫补扫(矩阵 §1#15) — DONE
**问题**:旧关键字门 `\bdig\b|\bhost\s+name\b` 圈死两命令→`sdns host pool <超长>`(「host pool」≠「host name」,fixture 第24行真实存在)、单词 `hostname`、续行 dig 均漏扫→超长标签绿着出厂(994838 痛点平移)。

**修法**(同函数):门扩为 `\bdig\b|\bhost\s+(?:name|pool)\b|\bhostname\b`;`\`↵ 续行先合并成逻辑行(`_LINE_CONTINUATION_RE`)。

**A1+A2 回归**(`test_xlsx_lint_gates.py`,**45 passed**):
- 新增误杀-clean:`test_lint_dns_ignores_dig_flag_and_key_long_tokens`(+cookie 80hex / TSIG 冒号 base64 均不误报);
- 新增漏扫-catch:`test_lint_catches_dns_label_over_63_{host_pool,hostname_word,line_continuation}`;
- 旧 4 例(over_63/no_tld/host_name/multilabel_clean)全绿(无回归)。
- 另跑 **11 例对抗性独立验证**全过:误杀(cookie/TSIG/base64+/=)不报;真阳(裸 64hex 域名位/host pool 148/hostname/续行)全报;不误伤(下划线服务名 `_dmarc`/多标签 61+58/非 DNS 命令长标识/IPv6 @server)全不报。

### A3 · S3 errored reflow 反复失败终止链测试锚(矩阵 §1#6 / auditor R2) — DONE(并揭示 R2 已被 #17 防住)
**auditor R2 疑虑**:errored 走 author reflow(S_BROKEN_ERRORED),疑绕过 streak 两轮止损(streak 按 artifact 计、reflow 每轮换 artifact→streak 恒 1),仅靠 rounds_used cap。

**核实结论(读 nodes.py:994-1016,#17 per-case streak)**:per-case streak 计的是 `v["result"] in ("broken","not_run")`;errored 案的 `verdict="broken"`→`result="broken"`(broken_subtype 是**另一字段**)→**errored 反复失败也累计 per-case streak**。∴ **#17 的 per-case streak 已覆盖 errored,R2 实已防住**,只是原来无 errored 子类专测。

**补锚**(`test_broken_third_state.py` append,`test_errored_reflow_repeated_failure_escalates_via_streak`):同 case 连续 errored 跨 reflow(art a0→a1)→ per-case streak≥2 → escalated,不无限 churn 到 cap。与既有 `test_broken_streak_per_case_escalates_across_reflow`(测 plain not_run)**互补,专测 errored 子类**。**20 passed**(全 broken_third_state 绿)。

> 协调提示:此锚落在 `test_broken_third_state.py`(#17 也在编辑该文件),我 **append 在文件末尾**(与 #17 的 per-case streak 实现/测试不重叠,已实跑共存 20 绿)。若 #17 后续改 streak 计法,此锚断言的是「errored 反复失败→escalated」的**行为不变式**(不锚具体轮数),对 per-case/per-artifact 两实现都成立。

---

## B. 设计张力项(未自动改,交协调者/用户裁)

### B1 · S5 footprint `on_device_passed=True` 不标 provisional(矩阵 §1#7 vs oracle #12) — 张力·待裁
**两个结论有真张力,不自动改:**

- **Side A(矩阵 §1#7 / S5 auditor R2 / DESIGN §A 文字)**:`_writeback_one:1149` footprint 写回硬编 `on_device_passed=True` + `:1156` 无条件 `_promote_behavior_candidates`,均不接 provisional。DESIGN §A 明说「`compile_writeback`/**footprint** 写回时如实标 provisional」。子集 flaky pass→footprint **行为候选晋升**入库零 flaky 标→后续 worker `kb_footprint` 当 device_verified 铁证(§0.5 活违反面)。且 `test_writeback_threads_provisional_keeps_footprint_device_verified` 把「不标」**锁死为预期**。
- **Side B(oracle #12)**:footprint G 段**语法**是 h-不变量、子集轮也真上机跑过=verified;标 provisional 会砸 **device_verified 拉取**(fresh-PASS 短路依赖 `on_device_passed=True`,实证 28/28 skip 省 token)。not-provisional 有其道理。

**crux(我的判断,供裁不代裁)**:张力可能可**分层化解**——S5 auditor R2 已指出 docstring 论据「对**纯语法**成立,但**行为晋升**同路无区分」。即:
- **语法写回**(G 段命令语法):子集轮真跑过→device_verified 不降级(Side B 对)→**不标 provisional**;
- **行为候选晋升**(`_promote_behavior_candidates`,如"某配比命中某分布"):采样敏感、子集 flaky 可能不稳→**应带 flaky/provisional 标**(Side A 对)。

**给协调者的问题**:footprint 该不该标 provisional?若采分层:①`_promote_behavior_candidates` 是否接 provisional/flaky 标而 `compile_footprint_writeback`(语法)不接?②这样是否既不砸 device_verified 拉取(语法仍 True)、又堵住 §0.5(行为晋升带标)?③改锁死测试 `test_writeback_threads_provisional_keeps_footprint_device_verified` 断言(现锁「不标」)。**牵涉 fresh-PASS 短路(28/28 skip)与 kb_footprint 拉取语义,影响面超 S4,不宜我单方改。**

### B2 · S3 window-audit 检测器假阳无反例锚(矩阵 §1#4 / auditor R1) — 列风险·不改检测器
**auditor R1**:window-audit 残差检测器(`_apv_blocks` 分段 + `seen[src]` 配对)假阳现被当协议硬事实驱动 **reflow 改写**(非无害复跑);分段错位(缺/畸形 prompt 行致邻块 pattern 并入)时真 fail 判 false_fail→broken-errored→重写→cap,**真缺陷可能被埋成「未跑成·已改写·封顶」永不进缺陷候选**。

**处置(证据优先,不改检测器逻辑)**:**无实证假阳前不动检测器**(守证据优先纪律——auditor 是推演脆弱性,未抓到真机假阳实例)。**建议锚**(供实现阶段,若日后抓到实证):
1. `test_window_audit.py` 补**分段错位/echo 误配假阳反例**(构造缺失/畸形 prompt 行的回显→断言不误判 false_fail);
2. 更根治的是**处置侧纠偏环**(非检测器):errored→reflow 改写后**仍 broken 则回退归因**(改写没解决=可能检测器假阳或非改写可治),避免真缺陷被埋。此属 nodes.py broken 路由段(#17 领域),**列给协调者,不在本批改**。

**倾向**:B2 短期只补反例锚(廉价、无实证不动逻辑);中期若真机抓到假阳,再上处置侧纠偏环(交 #17/路由 owner)。

---

## C. 汇总
| 项 | 类型 | 状态 |
|---|---|---|
| S4 DNS 误杀收窄(§1#5) | 机械修 | ✅ 已修+测(45 passed + 11 对抗例) |
| S4 DNS 漏扫补扫(§1#15) | 机械修 | ✅ 已修+测(host pool/hostname/续行) |
| S3 errored 终止链锚(§1#6/R2) | 测试锚 | ✅ 已补+测(20 passed);核实 R2 已被 #17 防住 |
| S5 footprint 标 provisional(§1#7) | **设计张力** | ⏳ 标出交裁(Side A vs B + 语法/行为分层 crux) |
| S3 window-audit 假阳(§1#4/R1) | **证据优先** | ⏳ 列风险+建议锚,无实证不改检测器 |

**只读边界**:仅改 structural_gate.py(S4 所有权)+ 追加 S4/S3 测试,未碰 nodes.py 路由段 / worker.md / engine_tool.py。张力项零代码改动、纯标注。

STATUS: done
