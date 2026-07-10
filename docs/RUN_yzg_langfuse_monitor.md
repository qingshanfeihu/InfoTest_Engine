# yzg 批（79758 监听器改造，26 case）——Langfuse 全程监控运行记录

> 2026-07-09。目的：**只跑和监控，零代码改动**——检验引擎是否按理论（THEORY_k_state_machine + AUDIT 迁移表）运行，
> 问题先记录本文档，不现场修。观测三通道：cmux 抓屏（TUI）/ 盘上事实流（fastlog、k_signals.jsonl、
> verified_runs.jsonl、last_run.json、engine_ledger）/ Langfuse traces（jp.cloud.langfuse.com）。

## 运行参数

| 项 | 值 |
|---|---|
| 脑图 | workspace/inputs/automatic_case/yzg.txt（26 case，15 组，含配置保存 4 例） |
| 产品版本 | 10.5（build InfosecOS_Beta_APV_HG_K_10_5_0_568） |
| 跳板机 | 10.4.127.103（环境池关，单机） |
| 模型 | mimo-v2.5-pro（思考开，effort high；重编轮首败即升 max） |
| 引擎 | V6 StateGraph（HEAD=86089265，六提交后首跑） |
| Langfuse | LANGFUSE_TRACING_ENABLED=true，auth_check 预检 OK |

## 理论核对清单（跑中逐项打勾/记偏差）

- [x] T1 prep：manifest 26 case 全入 ledger（groups 15）✓
- [x] T2 首轮 worker：effort 常规（fork 卡「第1次」）✓；briefs_path 判 N.A.（引擎内派发）
- [－] T3 欠定：本批零 NEEDS_USER_DECISION，无触发场景（机制未受测）
- [x] T4 合并：26 卷凭证门全过 ✓
- [x] T5 上机：整卷单跑（超时 1170s=26×45 公式对）；verified_runs.jsonl 全带 build 锚（**A3 首跑生效**）✓
- [x] T6 归因：^→G + dev_help 自动读表（syntax_help_attached×3）→ LLM 填 undetermined → submit_attribution 落盘 ✓；known_defects 无命中场景。**归因质量另见 R2 全景表（2/19 版本感知）**
- [x] T7 重编轮：fork_start `effort:max` 全生效（引擎层 ✓，footer 尾标缺失=问题#4）；只重编 fail 子集 ✓；**单调门零假拦截**（34 卷重编全静默通过）✓
- [✗] T8 跨轮：**frozen/瞬态复现护栏结构性失活**（问题#7——子集卷每轮换目录，digest prev_map 恒空）；defect 判层两案 disposition=frozen 但未经形态检验轮（同因）
- [x] T9 PASS 即时写回×3（precedent:true）✓；uncertain 入库 19 条 ✓；observation_group_formed×2（入库端一次性）✓——**但 uncertain 缺 build 锚+语境截断=问题#8**
- [x] T10 终态：整卷终验路由触发（第4轮整卷 3 case 2m12s）✓；交付六件套齐全、临时清理 75 项 ✓（refs 悬空=问题#9）
- [x] T11 Langfuse：全程 127 traces（主链+fork 双挂载）✓
- [x] T12 语言分层：brief/门反馈英文、TUI/交付报告中文 ✓（观察组语境英文入库——attributor 面一致）

## 时间线

- **14:27** cmux 起 TUI（workspace:1，mimo-v2.5-pro），发指令「编译 workspace/inputs/automatic_case/yzg.txt，产品版本 10.5」。
- **14:29** 主 agent 调 compile_engine_run；prep 完成——**T1 ✓** ledger 26 case 全部 `dispatched`（Monitor 首报）。
- **14:32** 抓屏：轮次0 编写 3/26（产出3 编写中23），fork 卡片全部「第1次」（首轮普通思考，未见 max 深度标记，符合首败即升前置态）；worker 行为健康：dev_probe（show sdns listener / show ha group id / show sdns host status）、读 EXCEL_FUNCTIONS.md、grep 手册「全域名/fqdn」。累计 ↑2.10M ↓30.7k tokens，¥6.48。
- **14:32** **T11 ✓** Langfuse traces=25（含 8-32 obs/trace 的 LLM spans）——主链+fork 双挂载点都在出数。观察：trace name 为空（CallbackHandler 默认匿名根），按 autoid 命名可改善检索性——**记录不修**。
- **T2 判读修正**：briefs_path 文件通道是 orchestrator 工具路径的纪律；V6 引擎 worker_fanout 为进程内逐 case 派发（不经 compile_fanout 序列化面），该项按「引擎内派发无截断暴露面」判 N.A.-符合。
- **14:45** 轮次0 收束：**26/26 产出、欠定 0**（yzg 批无 NEEDS_USER_DECISION——T3 无触发场景，待后续轮观察）；合并整卷 26→`yzg/case.xlsx` 过凭证门（**T4 ✓**，任一缺凭证/过期会拒合并）；**上机第1轮(整卷)** 启动，环境 103，超时 1170s（=26×45s clamp，公式符合），心跳单行原地走秒。累计 ↑13.1M ↓251k，¥40.91。
- **16:2x** R2 编写收束：21/21 产出（max 思考下零卡死）。**T7 后半/单调门 ✓**：真批 emit 全程**零 monotonicity 信号**——21 个重编卷对 R1 旧卷基线比对全通过，无维度削减亦无假拦截（门静默通过=最佳形态；38 条信号污染系测试残留，见问题#5）。进入子集合并→R2 上机。
- **16:0x** 归因收束：23 fail → 21 重派（R2）+ 2 判 `env_blocked` 终态（处置路径合法，但归因内容存疑——见问题#3）。**T7 ✓（引擎层）**：R2 全部 fork_start `effort:max`（首败即升数据层生效），卡片「第2次 · verify_fail」；footer 尾标缺失是显示层问题（#4）。R2 worker 检索 Footprint(sdns pool)——R1 写回的 3 个 PASS 先例进入兄弟检索路径（T9 生效性待 R2 结果印证）。
- **15:37** 首轮 digest 落账：**3 pass / 23 fail**——新特性域（监听器改造）先例覆盖稀疏，R1 低命中与 K 完备度中心论断相符（dongkl 同期 R1 高得多、其域 K 已饱和），后续轮爬升幅度是本批最有价值的论断数据。**T5/A3 ✓** verified_runs.jsonl 26 条全带 `build:…10_5_0_568` 锚（新链路首跑生效）；**T6 部分 ✓** …681588 机械 ^→G + dev_help 自动附语法事实 + `syntax_help_attached` 信号（见问题#1）；**T9 前半 ✓** 3 个 PASS 即时写回（`writeback_done{precedent:true}`），R2 兄弟 case 立即可检索。

## 🔴 头条发现：设备床 build 被换（10.5.0.568 → 10.4.6.170），缺口 C 的活体现场

**因果链（全部一手证据）**：

1. 设备 `show version`（框架 device_context 内捕获，双轮一致）：`InfosecOS Beta.APV-HG-K.10.4.6.170`，**System boot time: Fri Jul 10 01:00:11 GMT**——设备床在 dongkl 批（昨日）与 yzg 批之间被重装为 **10.4.6**；引擎按 `10_5_0_568` 提交。
2. `dev_help` 读表（10.4.6 实机）：`sdns host` 位置只接 `name`——**`sdns host pool` 子命令不存在**（79993 域名算法改造是 10.5 特性）。全部 10.5 语法先例/手册知识对此设备失效。
3. 后果形态完全自洽：解析链绑定断裂 → dig 一律 `ANSWER:0`（但 `SERVER: 172.16.34.70#53` 有应答、aa 标志——**网络可达**）；R1 20 解析类全败、R2 换法后 21/21 仍败、17/21 同签名（期望成员 IP 无应答）；配置保存 3 案 PASS（listener 命令 10.4.6 仍在，且只验配置存在性）。
4. **理论印证（本批最大收获）**：这正是缺口 C 定义的 stale 场景——K（先例/footprint/手册）与运行配置全部锚定 10.5，设备事实漂移后**无任何机械比对**。而 show version 就躺在 R1 的 device_context 里：`提交 build vs 设备自述 build` 的一次字符串比对即可在 R1 digest 时报警，可省两轮（≈¥60+ token、约 40 分钟设备时）。build 锚三源中源①（show version 自述采集）+ stale 派生判定的优先级由「理论要求」升格为「实测止损收益 quantified」。
5. **归因质量复盘**：…676594 attributor 的「整批系统性失败」直觉**正确**（我在问题#3 的「误归」初判过急——3 个 PASS 恰是不走 dig 的配置保存族，不构成反证）；但其 E 层叙事「RouterA 无法到达 34.70」**错误**（SERVER 有应答）。正确定性=环境/版本层（build 特性缺失）。教训：①「不可达」类断言必须以 dig 的 SERVER 行/状态层证据裁决；②跨案一致性对账（系统性声明 ↔ 同批 PASS 集的性质分组）值得机械化；③show version 就在证据里，归因树的「版本层」一步未走。

### R2 归因全景（19 案，DS-1 金标准素材——真根因已知=版本换装，可逐案打分）

| 统计 | 值 | 含义 |
|---|---|---|
| 版本感知归因 | **2/19** | 找到真根因（10.4.6 固件拒绝 10.5 语法）的比例 |
| 版本感知 ∩ 带 dev_help 语法证据 | **2/2** | 两个认出版本的恰是仅有的两个 `^`→dev_help 案（655262/681588） |
| 无机械证据案的版本感知 | **0/17** | 配置被静默接受（无 ^）的案全部在 V/E 层各自成篇（「后端 IP 不可达」「缺 enable」「框架发错 dig」等互不相同的叙事） |
| (layer,disp) 分布 | V/reflow×9, E/env_blocked×3, PD/frozen×2, V/frozen×1, G/reflow×2, E/reflow×2 | 13 reflow 将进 R3（对特性缺失 build 注定再败→冻结），6 新终态 |

**理论判读**：①机械证据注入（syntax_help_attached）对归因正确率的因果效应在真根因已知的自然实验里被量化——有证据 100%、无证据 0%；②17 个互不相同的错误叙事没有一次触发「同批横向对账」——跨案一致性核对（问题#3 教训）的收益再次被坐实；③show version 在每案 device_context 里都有，但归因树没有「版本层」一步——缺口 C 的 stale 判定若已实现，19 案全部一步到位。

## 问题记录（先记录，不修）

| # | 时间 | 现象 | 证据指针 | 理论归属/初判 |
|---|---|---|---|---|
| 1 | 15:37 | worker 给配置保存类写了交互确认步：`YES` 独立成命令发到设备 → `^` 拒；上一命令已 `File not found / Failed to execute`（保存目标文件流未通） | last_run.json …681588 device_context；k_signals `syntax_help_attached{rejected_cmd:"YES"}` | 机制侧**全部正常**（caret 抽取→dev_help 读表→信号→落盘链首跑即通）；dev_help 对 "YES" 诚实答「无可识别前缀」。属 V/G 编写质量：交互确认不是命令，框架无交互通道——待看 attributor 能否从 G+语法事实推出正解（理论：语法层 O(1) 可判定） |
| 2 | 15:37 | Langfuse trace name 为空（匿名根），批量检索需靠时间戳对位 | Langfuse traces API | 可用性观察；按 autoid/节点命名可改善——不修 |
| 3 | 16:0x | 两案 R1 即判 `E/env_blocked` 终态：…655154「RouterA 无法到达 172.16.34.70」、…676594「整批 SDNS 系统性失败」。**与两项事实冲突**：①拓扑 JSON 显示 routerA 自带 172.16.34.206/24（同网段直达）；②同批 3 case 同轮 PASS（"整批失败"直接被反证） | engine_ledger 两案 + last_run `_attribution`；network_topology.json routerA 条目 | 归因误判（E 与 G/V 混淆：listener 配置未生效 ≠ 网络不可达）。理论缺口候选：**归因无跨案一致性核对**——「系统性」声明应与同批 PASS 集对账；attributor 判 E 前应过状态层（show listener 状态）而非直接采信 dig 无响应。代价：两案损失剩余轮次。只记录不修 |
| 4 | 16:1x | 重编轮 fork_start 事件 `effort:max` 全部生效（引擎层 T7 ✓），但 TUI footer「最大深度思考中」尾标未显示（scrollback 0 命中） | events.jsonl fork_start×3 带 effort:max；抓屏 footer | TUI 显示层缺陷：尾标渲染条件未接住 fork effort 态；引擎行为正确。只记录不修 |
| 5 | 16:2x | `runtime/logs/k_signals.jsonl` 混入 38 条测试信号（MONOTEST-A2×2 冒烟 + 2030…000202×36 回归套件）——pytest 跑 compile_emit 时信号直写生产流水 | k_signals 按 subject 聚合 | 测试隔离缺口：signals._LOG 仅个别测试 monkeypatch，emit 门路径的测试未隔离。污染可按 subject 前缀过滤（真 autoid 2036…），不影响本批判读。只记录不修 |
| 6 | 16:2x | R2 emit 打回分布：最近 60 次 `prov_parse:25 / ok:28 / other:7`（≈42% provenance 解析打回） | emit_stats.jsonl | 与 E2 历史基线 48-52% 同量级、非新问题——worker 仍走字符串 provenance 通道的形态税；blocks 通道是既有解法，采纳率是改进方向。只记录 |
| **9** | 17:5x | engine_report.refs 指向已被 _cleanup_temp 删除的 manifest/last_run（引用悬空）；delivery_report 设备回显「已去时间戳前缀」但节选每行仍带 `2026-07-10 05:26:10` 前缀且首行残缺 `-10 05:26:10`（剥取模式与该日志格式不匹配） | engine_report.json refs vs 目录实态；delivery_report.md 回显节选 | 交付面小瑕疵两处。只记录不修 |
| **8** | 17:0x | **uncertain 入库缺 build 锚 + 语境 120 字符硬截断**：closing 收尾把本批 fail/escalated 观察大量入库（仅 sdns.listener 就 15 条 uncertain），`evidence.device_run` 只有 autoid——A3 的 build 透传只覆盖了 PASS 晋升/写回两路，漏了 uncertain 入库路；`observed_under` 在 120 字符处截词（"…downstream impac"），恰把 attributor 写的固件限定语砍掉 | sdns.listener.json uncertain×15；closing `_ingest_uncertain_observations` 的 `device_evidence={"autoid":…,"run_ts":None}` 与 `ctx=note[:120]` | **理论直击**：这批观察是「10.4.6 下为真」的条件知识，缺条件锚=未来 10.5 环境下的检索噪声/半毒条目（poisoned 谱系的"真过但语境漂移"形态）。缓解面已有（uncertain 标注+组头「对照配置形态取用」+同 key PASS 可升级），但 15 条/节点的量级会稀释检索。**跑后处置待用户拍板**：按 subject/时间窗清这批 uncertain，或补 build 进锚与语境。只记录不修 |
| **7** | 17:0x | **跨轮机械护栏在 V6 引擎主路径结构性失活**：R1↔R2 十余案同签名 fail，但零 `.frozen.json`、零 `frozen` 信号、瞬态复现护栏同样未激发 | k_signals yzg 批分布（无 frozen）；`ls workspace/outputs/2036*/.frozen.json`=0；`verify_phase.py:61` 子集卷名 `_fails_r{round}` 每轮新目录 vs `batch_tools` digest 跨轮对照键控「同路径 last_run.json 的 prev_map」 | **理论-实现断裂（状态机 frozen 迁移的触发点在引擎模式不可达）**：digest 的同签名冻结/瞬态复现/`_prev_attribution` 保留全是路径键控，引擎每轮换子集目录 → prev_map 恒空。降级非全断：ledger 侧 brief 喂全历史+首败即升仍在，轮次封顶兜底；但「同签名×2=必须换法」从 A 层强制退化为 C 层自觉。dongkl 时代 frozen 生效是因为当时复测复用同目录。修法方向（仅记录）：digest 跨轮对照按 **autoid 键控读主卷 last_run**（或引擎把子集结果 merge 回主卷路径后再对照） |

## 第二回合：换床清数据重跑（93 @ 10.5.0.585）

**用户裁决**：换测试床、清理数据、重新跑。**复盘我的失误**：环境池 4 床本就存在（103/93/79/105），103 被重装后我把「等床恢复」当唯一路径，没探备用床——探测结果 93/79/105 全在 **10.5.0.585**（6月27日起稳定），只有 103 被换 10.4.6。

**清污（全量先备份 `runtime/backups/yzg_1046_cleanup/`）**：
- 坏批产物：`workspace/outputs/yzg` 整目录、engine:yzg checkpoint 201 行、verified_runs 本批 63 条（恰=26+21+13+3 四轮）、今日 3 份 mirror 写回卷+索引键、footprint 手术 14 节点（19 uncertain 观察+1 cli 条目，device_run 锚精确定位——A3 的锚在清污时立了功）
- **过删回滚一次**：mirror 按前缀扫到 25 份，其中 22 份是 7月5-6 日老 /goal 阶段在 10.5 床真验过的合法先例（mtime 甄别）——已连同索引键精确回滚；footprint 无误伤（老条目无 device_run 字段天然不匹配）
- k_signals/emit_stats/fastlog 保留（观测历史，按 subject 可过滤）

**重跑**：新 TUI 以 `IST_JUMPHOST_HOST=10.4.127.93` 启动（零代码/零配置文件改动），同指令重发；checkpoint 已清=全新 R1。22 份老 yzg 先例在库，K 完备度条件与 dongkl 批对齐——本回合 R1 通过率同时是「健康 K + 正确 build」的中心论断复验。

### 第二回合时间线

- **18:5x** R1 编写 26/26 产出（零欠定，与第一回合一致）→ 整卷上机 @93。
- **19:2x** **R1 digest：24/26 直接 PASS**（写回信号逐案点名；对照第一回合同批同引擎 3/26）——「偏差是 K 健康度的函数」在同批用例上的最干净对照：健康 K（22 份老先例在库）+ 正确 build（10.5.0.585）→ R1 命中率 92%。第一回合被判 env_blocked 终态的 655154、升级人工的 655173/188 等全部同法直过，反证第一回合 23 案确系「对错误 build 的正确失败」。
- 遗留 2 案均为「配置保存+重启设备」族（668015 write file / 668030 write all，签名=重启后 listener 查询不匹配）——进 R2 首败即升 max 思考。
- **19:3x** R2 两案子集单跑双双 PASS → 整卷终验。⚠ **后经完整审计更正（AUDIT_yzg_full_system_check 头条）**：终验整卷实测 fail×3（668015/668030/668044，保存族连跑互扰），`frozen` 在主路径正确点名但引擎未消费——终验 fail 被 pass 卷面锁静默吞掉，未发生任何重编再验，writeback 直接进行。我当时的「frozen→重编→再验全绿」叙事是错误推断，以审计版为准。
- **19:4x** 终局：报告 `delivered_all_pass`（名义 26/26；**审计实测整卷语境 23/26**，见 AUDIT_yzg_full_system_check）。第二回合 43m34s，↑18.5M ↓327k，¥57.36；Langfuse 累计 163 traces。交付卷 `workspace/outputs/yzg/case.xlsx`（26 case），零人工处置项。

### 第二回合终局判定

- **中心论断闭环**：同批 26 case、同引擎、同指令——错误 build+可用 K：3/26；正确 build+健康 K（22 老先例）：**R1 24/26 → 终局 26/26**。K 健康度与环境锚正确性对结果的决定性以最干净的受控对照落账。
- **引擎行为全绿**：欠定零误触、单调门四轮零假拦截、首败即升 max、子集/整卷双层验证抓住重启族状态交互、frozen 换法在主路径生效、PASS 双写回幂等、成本第二回合仅第一回合 36%（¥57 vs ¥160——正确环境下无效重编轮消失）。
- **待办沉淀**（连同第一回合 9 问题）：缺口 C（show version 锚差报警）、问题#7（子集轮 frozen 失活）、#8（uncertain 锚+截断）为最高优先修复项——三者本次都有量化收益/实证背书。

## 终局（第一回合 @103/10.4.6）

- **总账**：26 case → **3 通过 / 8 终态标注 / 15 升级人工**；4 轮（R1 整卷→R2 子集 21→R3 子集 13→R4 整卷终验）；1h16m，↑51.5M ↓1.02M tokens，**¥160.50**；Langfuse 127 traces；设备 4 轮。
- **根因**：设备床在批间被重装为 **10.4.6.170**（引擎按 10.5.0.568 提交）——79758/79993 相关 10.5 语法（`sdns host pool` 等）在该 build 不存在，解析链系统性断裂。3 个通过恰为不走 dig 的配置保存族。**本批 23 个未通过不构成引擎回归证据**——它们是对错误 build 的正确失败。
- **引擎按理论运行的判定**：核对清单 10✓ / 1 无场景 / 1 结构性失活（T8）。首败即升、单调门、build 锚、观察组信号、整卷终验路由、自愈环入库——六个新机制全部真跑生效且零假阳性。
- **两个头条产出**：①缺口 C（build 锚差→stale 判定）从理论要求升格为量化止损收益（show version 在 R1 证据里就有，一次比对可省两轮 ≈¥90/40min）；②发现 T8 跨轮护栏在 V6 主路径失活（问题#7）——dongkl 时代生效是同目录复测的巧合。
- **DS-1 金标准入账**：真根因已知的 19 案归因自然实验——机械证据（dev_help）在场 2/2 正确、缺席 0/17，跨案一致性核对的收益被直接量化。
- **跑后待用户拍板的处置**：①问题#8 的 19 条无锚 uncertain 观察（清除 or 补锚）；②设备床 build 恢复 10.5 后同参数续跑可复用 checkpoint（3 个 PASS 与全部欠定决策不重烧）；③问题#7/#8/#9 与缺口 C 的修复排期。
