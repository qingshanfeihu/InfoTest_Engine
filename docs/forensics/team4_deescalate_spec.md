# de-escalate 通道修法规格（v4.1）

> 2026-07-20，用户裁 B-1 走 A（修缺口）后 leader 起草；正文经会签迭代至 **v4.1**（标题与正文版本对齐，勿再写「草案 v1」）。前置取证见 `team4_escalated_deadlock.md`。
> 状态：**Theory/Design 语义会签通过**；实现认领见 epic 在册项。

## 0. 语义裁决（Theory+Design 会签通过，2026-07-20）

**escalated 是「准终态·可恢复」，不是绝对终态。**

**硬依据（Theory，THEORY:101-103 目标函数条款）**：Ω 五类中唯一「案侧无修法」的正当终态 = **缺陷候选**；其余 fail 全是中间态、引擎必须继续。escalated ≠ 缺陷候选（工程故障/卡住，非案侧无修法）⇒ **不在正当终态集内 ⇒ 必为中间态**。判「绝对终态」= 让引擎在非缺陷候选处终止 = 违反目标函数条款。git 溯源降为佐证。
> 预挡反证：A2′:712「案终态(含 suspended/escalated/terminal)」里 suspended 明文非终态（:104）⇒ 该「终态」是**松散指代案状态标签**，非绝对终态。**条款候选（Theory）**：A2′:712 该措辞收紧为「案状态标签」，免日后误引。
> Design 精化措辞：缺的不是「解除信号」（`_is_escalated`@views.py:57-72 已有解除判据「最后 escalated 后出现 authored」），而是**没有让案重回 author 的驱动**——**信号有、驱动无**。no-output 案永不产 authored → 永远等不到解除。

**恢复出口 = A6 二分 + Ω③ 拼成的工程三出口（勿写「A6 已给三个」）**：THEORY:273 **A6 原文是二分**——有待决应然→强制呈报确认；无→escalated **工程故障呈报**（证据附上）。产品缺陷候选来自 Ω③（目标函数正当终态），**不在 A6 字面内**；会签把「实然手段 / Ω③ 缺陷候选 / A6 工程故障臂」拼成面板三出口——
| 出口 | 语义 | 适用 | 理论锚 |
|---|---|---|---|
| 实然手段（重编/换床复跑） | 还有没试尽的实然路 | no_output / not_executed / no_ledger_channel 的因① | 实然试尽前置 |
| 产品缺陷候选（Ω③，THEORY:102：产品缺陷·五查+换形态坐实） | 案侧无修法的**产品**问题 | 五查坐实后 | 目标函数 Ω③ |
| **工程故障呈报（A6 臂）** | **引擎**缺口，附证据，**不进缺陷候选卷** | no_ledger_channel 的因②（先重编试探后坐实） | A6 二分之「无应然→工程故障」 |
> **裁决更正留痕**：leader 初裁「no_ledger_channel 统一转缺陷候选」，经 Theory 依 THEORY:102 定义域（引擎缺口非产品缺陷、过不了五查、无形态可换）+ A6 既有二分驳回，Py-Eng 独立佐证（or 分类不可分、先试后判）——**leader 收回原裁**。缺陷候选卷若日后出现引擎条目可溯回此处。

## 1. escalated 三子类（Py-Eng 预研修正 v2；结构化 subclass 字段分治，非 reason 散文判定）

三个产生点（盘面核实）→ 三子类，恢复路各不同：

| 子类 | 产生点 | reason 特征 | 成因 | 卷 | 恢复路 |
|---|---|---|---|---|---|
| **no_output** | `nodes.py:512` | `"no output from fork"` | worker fork 空转/墙钟超时 | **无 xlsx** | **重编**（换并发/墙钟重派 author） |
| **not_executed** | `nodes.py:1275` | `"case did not execute for N consecutive runs"` | 有卷但上机跑不成（设备/床） | **有 xlsx** | **换床复跑**（非重编——卷是好的） |
| **no_ledger_channel** | `nodes.py:508` | `"...no needs_decision.json ledger (no landing channel **or** falsify tool not called)"` | 混两因（Theory+Py-Eng 实证）：**因①** worker 忘调 compile_check_verifiability（可自愈）/ **因②** 本类欠定无落账通道（DESIGN §19.5 引擎缺口）。代码 `or` 承认分类时分不出 | 视情 | **先试后判**：答「重编」赌因①（成本1 fork）→ 重编后同 claim 再撞=因②坐实 → **A6 工程故障呈报臂（附 worker 原文证据，记引擎缺口，绝不进产品缺陷候选卷）**；选项三套「重编/工程故障呈报/保持」 |

**分治机制（Py-Eng 建议采纳）**：在三个产生点各加结构化字段 `subclass ∈ {"no_output","not_executed","no_ledger_channel"}`（append 各加一键，改动极小），下游按字段分治——**不 grep reason 散文**（关键字白名单型脆弱，改词面全盘失灵，项目栽过多次）。存量事实无该字段时按 reason 前缀兜底一次。

> 非产生点排雷：`nodes.py:1828` `sh.signal("escalated", …, reason="env_blocked")` 是**信号不是事实**，不进 facts 流、不产生案态，实现勿误当第四产生点。
> 修正记录：B-1b 三案（588766/589503/589432）早前误归「broken 换床」，实为 escalated·not_executed 子类。

## 2. 恢复通道设计（对称 suspended/resumed）

### 2.1 引擎侧（Py-Eng 域）——会签终版

**子类判据换轴（Theory②必改）**：**不按 `reason` 串匹配**（关键字白名单，措辞一改静默误路由，违准则6/`[[compile-judgment-structural-not-strongdict]]`，且与「有无 xlsx」跨轮打架）。判据取**事实流中该案最后一次失败的阶段**——author 段崩=no_output、run 段崩=not_executed、欠定无台账=no_ledger_channel；`reason` 串与「有无 xlsx」降为人读辅证/交叉校验。**跨轮铁例**（守门测试9）：round1 产卷+round2 fork 空转→最后失败在 author 段→判 **no_output（走重编）**，不因「xlsx 在」误判 not_executed。生产点仍写结构化 `subclass` 字段固化该判定。

**恢复问询（走既有 needs_decision + `deesc:` 专属 qid 前缀，Design 精化丙）**：续跑时对 escalated 案发恢复问询，**不改 all_settled**——在 `case_status` 的 escalated 分支内先判「有未答 `deesc:` 问询→返回 `S_AWAITING_USER`」（awaiting 天然不在 settled 集，判据单源）。`deesc:` 前缀防误伤旧的未答 needs_decision（否则带陈旧欠定的 escalated 案被判 awaiting=livelock，#62 stale claim 同型坑）。选项按三子类分（v4.1 修正——原行系 v3 残文与 §1 A6 裁决抵触）：no_output「重编/确认产品缺陷/保持」、not_executed「换床复跑/确认产品缺陷/保持」、no_ledger_channel「重编（先试因①）/工程故障呈报（判因②）/保持」。「确认产品缺陷」臂沿用 07-16 cap/env 面板既有缺陷臂语义（用户主张 Ω③，走缺陷单）；no_ledger_channel **无**产品缺陷选项（引擎缺口≠产品缺陷，A6 裁决）。

**de_escalate 事实驱动（Design 精化甲乙，零硬设状态）**：选恢复→写 `de_escalated` 事实 → `_is_escalated` 解除信号集扩为 `{authored, de_escalated}`：
- no_output：本就无 authored → **自然回落 S_PENDING**（views.py:14 定义即「无 authored」）→ author 选案集自然含它。**零新状态、零硬设、零特判。**
- not_executed：有 authored/verdict，解除后不自动落「该复跑」——**复跑选案集读 `de_escalated` 事实**（非状态迁移，两子类不同构，分开写）。

**round-cap（Theory+Py-Eng：计数轴落错单位，两子类都失效）**：`rounds_used`=**authored 成功事件**数，而 no_output **与 no_ledger_channel 都不产 authored**→恒0→封顶对最需要它的案永久失效（`nodes.py:653` 自述实证：批3 668族 **7 圈空烧 fork**，auth=0 verd=0）。**同型 A2″ 推论2**（计数落错单位→在最该报警场景恒0，与 upgraded_verified=0/build 1110/1110 同族）。修法=**新增 `attempts` 轴**（该案被送进 author/live 的次数，不问是否产出），**别原地改 rounds_used 定义**（波及 :1318/:1685/:1804/:2526 多消费点）；封顶按 attempts，**阈值复用既有预算公式 `max_rounds + granted`**（同一预算哲学，不新增 env 旋钮；v4.1 裁定）。**round-cap 生效是收敛律成立的前提非并列**（Theory：闸失效→「答重编→仍no-output→再问→再重编」问-编循环，判例键挡同参重问但挡不住每轮"新情况"）。

**收敛律落账（Theory③必改）**：恢复问询是资源权=应然命题（§2.6:112），收敛律适用。用户答「保持」须按**判例键=(autoid, subclass, 版本族/床身份)**写回 K_ought → **同参续跑不重问**（否则违 §2.6.4 同键至多一次）；换床/换版本族=新键**可重问**（A12:279 新真意的正确代价）。

### 2.2 报告侧（Py-Eng 域）
- **每个未交付案强制「去向」行**（对称 suspended 的现有格式）——render 状态映射补 escalated 分支。
- **无通道案不许承诺「可续跑」**：只有真有恢复通道的子类才写「重跑同参会再次询问是否恢复」；封顶后的真终态写「已尽轮次，记缺陷候选」。

### 2.3 footer 桶（TUI-Eng 域）
- **escalated 移出「失败」桶**（`ist_app.py:318` `bad=failed_terminal+escalated` 去掉 escalated）。
- **独立标签「需人工N」**（Design 定：术语一致——render.py:28 已有「引擎无法继续(需人工)」，footer 取同词根短标签）；broken 的「其他N」→「**未跑成N**」（Design：broken/not_run=没执行成功非判失败，同处 P2，本轮可一起收）。

### 2.4 救回入口（TUI-Eng 域，合并 ASK-1）
- **走 ask 面板新题型**（复用 suspended 恢复面板题型，基本现成）——**不走 slash**（避免与现有 `/resume` 会话线程恢复撞名=deadlock 文档报的误导源）。
- **合并 ASK-1 重设计**（挡板 armed 后按数字提交错答，现挂 P1）：这轮动 ask 面板题型，两件事一轮做、只过一次双评审——但 **Design 边界：两件须可分别回滚**（独立 commit/不交叉改同一函数），ASK-1 出问题不得连坐拖住 de-escalate 主线（后者是 B-1 救回路径、优先级更高）。

## 3. 守门测试（宪法级——缺口三月未被测出，同 #62 验收器盲区）
1. no-output escalated 案答「重编」→ 转 S_PENDING → **进 author**（断言 author 选案集含它）；
2. not-executed escalated 案答「换床复跑」→ **进 live 复跑集**；
3. escalated 案有待答恢复问询时 **all_settled==False**（防续跑直接收尾）；
4. 恢复重编受 round-cap（第二次 no-output→封顶→缺陷候选，不无限循环）；
5. **报告去向行**：每个未交付案（含 escalated 两子类）都有「去向」行，no-output 未封顶写「可重编」、封顶写「缺陷候选」，**绝不对无通道案写可续跑**；
6. footer：escalated 不落失败桶，落独立「需人工」桶，Σ==total 守恒。
7. **收敛律**（Theory）：答「保持」→ 同参续跑不再重问同判例键；换床/换版本族→可重问。
8. **判据不依赖措辞**（Theory）：`reason` 串被改写的 escalated 案，分治仍正确（锚在事实流阶段非关键字）。
9. **跨轮混合**（Theory）：round1 产卷+round2 fork 空转→判 no_output 走重编，不因「有 xlsx」判 not_executed。
10. **解除不复燃**（Design）：de_escalate 后新一轮再 no_output→`_is_escalated` 重新成立（新 escalated 在最后），验事件顺序未被 de_escalated 永久压住。
11. **no_ledger_channel 先试后判**（Theory+Py-Eng）：答「重编」→进 author；重编后同 claim 再撞→落**工程故障呈报**（附 worker 原文），**不落产品缺陷候选卷**；答「保持」不产 de_escalated、案态仍 escalated（防空转恢复）。
12. **round-cap 对零产出案生效**（Theory）：连续 N 次 no-output→第 N+1 次**必封顶**（断言 `attempts` 轴，非 rounds_used）。
13. **范畴不串台**（Theory）：工程故障呈报条目**不出现在**缺陷候选卷/交付报告产品缺陷段。

## 4. 实施顺序（Py-Eng 单线程 + TUI-Eng 并行）
语义会签 → 引擎 de_escalate 事件+通道+不动点+round-cap（Py-Eng）→ 报告去向行（Py-Eng）→ footer 桶+词面（TUI-Eng+Design）→ 救回面板+ASK-1 合并（TUI-Eng）→ 守门测试全绿 → 合入窗口。**验收=B-1 五案在新代码下真能被救回问询触达**（no-output 走重编、not-executed 走换床），而非停在死胡同。
