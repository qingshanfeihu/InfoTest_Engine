# V6 对照轮问题根因诊断(2026-07-06,只诊断未修改)

> ⚠️ **历史存档（2026-07-17 归档,team4 docs 整编）**：V6 对照轮诊断,随 V6 归档。事实存档不删,现状勿引本文。

> 方法:langgraph-persistence/HIL 官方 skill 语义对照 + 盘上机读数据(ledger/last_run/emit_stats/fork_trace/fork_status)取证。每条根因带决定性证据。

## P1 运行时翻转(dongkl 7 例 + yzg 3 例,全部 pass→fail 模式)——根因:触发机 SSH 读窗串位

**决定性证据**:210934 fail 轮的 `dig @172.16.34.70 autotest.com AAAA +short` 回显为 **172.16.35.231(IPv4)**——AAAA 应答协议上不可能携带 A 记录值。且 10 例翻转的 fail 签名**全部是 IPv6/AAAA 断言**(172::231 / IN AAAA / 3ffd:: / 2001:db8::1),无一例外。

**机制**:框架 `ssh read_until(prompt)` 按提示符切回显窗口;前一条 `dig A` 的应答晚到时窜进下一条 `dig AAAA` 的窗口——v6 断言读到 v4 输出必 fail。round1 时序凑巧对齐→pass,后续轮卷面组成/时序变化→串位。**层:框架/触发机通道时序;非编译错、非设备缺陷。**

**修法方向(未实施)**:框架层命令间确定性同步(echo 标记/序号回显);或 emit 对连续 dig 步插入间隔;或断言窗口容错。引擎现行为(标 `runtime_underdetermined` 不重编、标注交付)是正确处置。

## P2 emit "other" 打回(127 次/14h,占残余打回主体)——根因:分类器观测缺口

`_EMIT_REASON_PATTERNS` 未命中的 error 归 "other" 且**不带原文摘要**,根因不可追溯——这是可观测性缺口本身。数据面:总打回率 48-52%(基线)→ dongkl 12.1% / yzg 20%,worker blocks 通道采纳 97%。
**修法方向**:emit_stats 对 other 类记 error 头 80 字符;对照轮后按签名分布补分类与对应构造式收口。

## P3 dongkl frozen 6 例定性——收敛出两个公共根因候选

归因链全部完整(attributor 修复后质量高),按 fix_direction 聚类:

| 公共根因候选 | 涉及 case | 证据 |
|---|---|---|
| **设备 rr 调度=每 pool 连续命中 N 次再轮转(疑似 max_rr_count=2),非每查询推进** | 778012 / 778072 / 593545(三例 fix_direction 独立指向同一行为) | 区间/位置断言按"每查询轮转"建模必 fail——**这是高价值设备行为知识,应实测证实后入 footprint behaviors(经 device_verified 门),并进 compile_expected_hits 的模型参数** |
| **触发机通道脏**(与 P1 同族) | 994928(终端转义序列 `[A/[C/[K` 污染 dig 命令原文) | 与 P1 的读窗串位同属 SSH 通道时序/回显污染族 |
| 跨 case 配置依赖 | 593516(依赖前序 484 保留的 pool 配置,被 clear) | init 自包含纪律漏;worker 层 |
| 卷面执行 IP 与 provenance 不一致 | 681811(执行 @172.16.34.70,provenance 要求另一监听) | worker/emit 一致性,单例 |

## P4 worker 600s 墙钟超时(dongkl 2 例)——根因:重型欠定 case × 端点延迟,非死循环

fork_trace:超时 fork 均为 ai_rounds 15-22、tool_results 18-35 的重算例(compile_expected_hits×5-6 + verifiability×3-5 + kb_footprint×8-9),工具序列持续有进展。deepseek 端点单轮延迟高,600s 装不下 20 轮。
**修法方向**:欠定重编族提高 wallclock(按 redispatch_reason 分级)或 brief 带上一轮已算结论减少重算。

## P5 「报欠定不落台账」(105941/593573)——根因:worker 把「疑似缺陷升级」误用欠定措辞

fork_status 证据:105941 的 worker `compile_check_verifiability 调用=0`,实际做了 dev_probe 设备取证并发现「`sdns pool cname` + `sdns host lastresort pool` 后解析为空」(疑似产品缺陷/新形态),把升级诉求写成 NEEDS_USER_DECISION 字样——但这不是数学欠定,无台账。引擎 escalate 是正确出口。
**修法方向**:worker 的升级表达分信道——数学欠定(verifiability 台账)与「设备行为异常/疑似缺陷」(escalate 带证据)各有其名;后者在报告里应带 worker 的取证正文(当前 escalated 只有一行 detail)。105941 的发现本身值得进缺陷候选流程。

## P6 LangSmith 未生效——根因:两侧都未启用

- 项目 `environment`:`LANGSMITH_TRACING=false`,`LANGSMITH_API_KEY/PROJECT/ENDPOINT` 三行**被 # 注释**(模板在,未启用)。
- Claude Code 侧:`installed_plugins.json` 中 langsmith 相关插件 **0 条**(未安装)。

**启用步骤(用户操作)**:①environment 去掉三行注释填 key、TRACING 改 true → 重启 TUI 后引擎图/qa 图/fork 全部自动上报;②Claude Code 里 `/plugin marketplace add langchain-ai/langsmith-claude-code-plugins` + `/plugin install langsmith-tracing@langsmith-claude-code-plugins`。

## 优先级建议(按数据)

1. **P3-rr 调度行为实测**(一次探针卷即可证实 max_rr_count;证实后同时解 778012/778072/593545 并修 expected_hits 模型)——单点撬动最大
2. **P1/P3-通道脏**(框架层同步;或先用双跑标注顶着)
3. P2 观测点补齐(一行改动级)
4. P5 worker 升级信道措辞 + P4 墙钟分级(prompt/参数级)
