# B-1a 取证：escalated·no-output 案无 de-escalate 通道（结构性死锁）

> 2026-07-20，B-1a 存量救回驾驶中暴露。leader + TUI-Eng 两条独立证据链交叉验证。calibration 性质：surfacing gap IS the deliverable。

## 现象

B-1a 目标 = 降并发（`IST_FANOUT_CONCURRENCY=2` + `IST_FORK_WALLCLOCK_S=1200`）救回 zhaiyq 批的 517027/600113（escalated·fork no-output）。同参续跑（infotest PID 54226）后：**两案原样 escalated、rounds 仍 0**，本次续跑 `compile_evidence.54226.events.jsonl` **全文仅 3 行**（engine_tick prep → engine_tick closing → engine_summary），**零 fork_start**。降并发修法一次都没被执行到。

## 根因（三条盘面证据，机读账非推断）

1. **不动点把 escalated 算已落定** — `views.py:165` `all_settled` 的稳态集 = `{S_DELIVERABLE, S_ESCALATED, S_TERMINAL, S_SUSPENDED}`。本轮全批 ∈ 该集 → settled → prep 直接路由 closing，**author 节点不被路由**。
2. **author 不拾取 escalated** — `nodes.py:439-441` 选案判据 = `{S_PENDING, S_FAILED, S_CONTRADICTED, S_BROKEN_ERRORED}`，**S_ESCALATED 不在内**。
3. **无 de-escalate 事件** — 全引擎 grep `de_escalat|unescalat` 零命中。escalated 的解除条件（`views.py:_is_escalated` / `nodes.py:892`）是「最后一个 escalated 之后出现 authored」，而 authored 靠 author 派 fork、author 又因不动点成立不被路由 → **要 authored 才解除、要路由才 authored、要不 settled 才路由——闭环死锁**。
4. **迟到产出回收够不着** — `nodes.py:886` 只回收「xlsx 已存在」的 escalated 案；no-output 案无 xlsx，不被回收。

## 与 suspended 的对照（证明这是缺口不是设计）

`run18` 注释（`nodes.py:892`）自称 escalated「非绝对终态，与 suspended/resumed 同型」。但：

| 态 | 用户恢复通道 | 重开事件 | 回环 |
|---|---|---|---|
| **suspended** | ask 面板「恢复处理」→ `resumed` 事实（nodes.py:2550）→ `_resume_reopen`（:395）→ 案转 **S_PENDING** → 进 author | ✅ `resumed` | 闭合 |
| **escalated** | **无** | **无** | **断裂** |

注释声称的「同型」在实现里只做了 suspended 一半——escalated 升得进、出不来。

## 影响

- escalated·no-output 案在同参续跑里**永久卡「引擎无法继续(需人工)」**，任何环境/并发重调都无法触发（案进不了 author，参数设了白设）。
- Test-Eng prep55 的「降并发重调」方案**触发机制缺失**——这是 B-1a 未能验证降并发修法的真因，非操作失误。

## 修法方向（待评审链，leader 呈用户）

正解 = 给 escalated 补 de-escalate 通道，与 suspended/resumed 对称。两种形态：
- **(A) 显式恢复面板**：像 suspended 一样，续跑时对 escalated·no-output 案发「重编/放弃」问询，选重编→写 de-escalate 事实→author 拾取。语义最清晰。
- **(B) author 拾取 escalated**：author 选案集加 S_ESCALATED（限 no-output 子类、有 round-cap），不动点集同步移除 S_ESCALATED（否则仍不路由）。改动面大，需核 all_settled 的其他依赖。

评审要点（Theory/Design）：escalated 语义究竟是「准终态可恢复」（则补通道）还是「绝对终态」（则 run18 注释与 all_settled 一致、Test-Eng 方案本就不可行、B-1a 这两案应转缺陷候选而非重调）。**这个语义裁决是前提**，改代码在其后。

## B-1a 处置（driver 决定，待 leader 确认）

- 517027/600113 维持 escalated，作「引擎 de-escalate 缺口」实证归档（本文档），**不手工 hand-run worker 绕过**（违「不 hand-run 引擎产物」纪律）。
- B-1b（588766/589503/589432，broken+E 换床）与此缺口**无关**（那三案是 broken 不是 escalated·no-output，走 author 的 S_BROKEN_ERRORED 或换床复跑），可照 prep55 继续。

## git 溯源定性（2026-07-20 补，leader）

**结论：不是回归，是设计从未覆盖 no-output 子类。**

- `run18`（`157e0168` "迟到产出回收"）是 escalated「非绝对终态」注释与唯一解除路径的引入点。它处理的是**「fork 墙钟超时但 worker 其实产出了合格卷」**——回收**有 case.xlsx** 的 escalated 案（`_reclaim_late_artifact`，要求 xlsx 存在+lint 凭证匹配）。
- 针对场景 = 「有产出但被误判超时」。**「真·零产出（no-output）如何恢复」从未被实现**。
- 全 git 历史 `-S "de_escalat" --all` **零命中**——de-escalate 通道从来没存在过，不是被删。

∴ run18 注释「escalated 非绝对终态、与 suspended/resumed 同型」是**过度声称**：只做了「有迟到产出可回收」这一半，另一半（真无产出的显式恢复）是空白。B-1 五案全部落在这个空白里（reason 均为 "no output from fork" 或 "case did not execute for N consecutive rounds"，无 xlsx 可回收）。

**对语义裁决的意义**：这不是「escalated 该不该是终态」的哲学问题，而是「**已声明为可恢复、但恢复通道只造了一半**」的未完成设计。修法 = 补齐另一半（no-output 子类的恢复通道），与 run18 的既有意图一致、非推翻。

## B-1 驾驶实录（2026-07-20，leader 单兵，团队会话额度期）

- B-1a 降并发续跑：零 fork（案不进 author，死锁证实）。
- B-1b ist-verify@93：连撞「卷在 unfinished 归档区/缺凭证」——**上机路径能通，但救不了状态**：即便 93 床跑通，无通道把 verdict 写回解除 escalated。停手（避免在缺口下游叠补丁烧 token，实录 ~¥3）。
- **正确前置 = 先修 de-escalate 缺口**（本文档修法两方案），B-1 才有意义。已停手待用户裁语义+方向。

## 用户影响（2026-07-20，TUI-Eng 只读核，痛感顶格）

**定性：不是纯内部死锁，是用户可见死胡同 + 虚假承诺。** 四件事叠加：

1. **footer 错桶**：escalated 折进「失败N」（`_shared.py` escalated→`ist_app.py:318` bad=failed_terminal+escalated）。zhaiyq 实弹「失败7」= failed_terminal 2 + **escalated 5**。FOOTER-1 修好了 suspended/broken_blocked，**escalated 是同类错桶残留**——`views.py:58` 自述「非绝对终态」却与真终态同显「失败」。
2. **三面措辞互相矛盾**：footer=「失败」；卡片=「引擎无法继续(需人工)」；delivery_report 正文=「可续跑补齐/仍在引擎流程中」；engine_report.json=`status:escalated, artifact:"", rounds:0`（机读账诚实）。11 案对账：4 suspended 全有「去向」行、5 escalated 全无去向却全含「可续跑」字样、2 真终态一致无承诺——**escalated 是唯一「承诺可续跑但无去向且结构上续不了」的类别**，把用户推去必然无效的重跑。
3. **零救回入口**：`questions.py` 中 escalated 出现 0 次（永不生成恢复面板，对照 suspended 有恢复面板）；`main/` de-escalate 语义 0 命中（与 git 侧零命中互证）。
4. **误导性命令**：TUI `/resume`+`/continue` 是**会话线程**恢复（`_cmd_resume`→`_on_thread_selected(tid)`），与案状态无关。读完「可续跑」的用户看到 `/resume` 极可能去试→切换对话线程、静默无效、不报错。**误导入口比无入口更坏**。

→ 修法优先级据此从「补引擎通道」升为**用户体验红线级**：修 de-escalate 通道时须同步修 ①footer 桶（escalated 移出失败桶）②报告措辞（no-output 案不许承诺「可续跑」除非通道真的存在）③给可见救回入口（恢复面板 or 明确命令）。

**证据边界**（TUI-Eng）：基于 zhaiyq 单批次产物+源码判据，未验其他批次报告模板一致性（render.py:28 状态映射驱动，大概率一致未跑第二批证实）。

## 修法排期预判（2026-07-20，TUI-Eng 预判 + leader 归并；走 A 方案时的实施骨架）

三个 TUI 侧修点，均依赖引擎侧 de-escalate 事件先定形：

1. **footer 桶移 escalated 出「失败」**（`ist_app.py:318` + `_shared.py` 桶名，最小改动）——**词面待 Design 定**：并进「欠定」会与真待裁案混淆；TUI-Eng 倾向**独立标签**（如「需人工N」），语义=「卡住待救」既非失败也非待答。顺带收 `broken` 现显通用「其他N」的 P2（同处代码）。
2. **报告去向行强制**（`render.py` 状态映射，**Py-Eng 域**）——每个未交付案必须有「去向」行，对齐 suspended 格式；无通道案不许承诺「可续跑」。
3. **可见救回入口**（最大，依赖引擎 de-escalate 事件形态）——ask 面板新题型（复用 suspended 恢复面板题型，基本现成）vs 新 slash。**若走 slash 务必不叫 `/resume`**（撞现有会话线程恢复=本文档报的误导源）。

**⭐ 合并省评审**：ASK-1 重设计（挡板 armed 后按数字提交错答，现挂 P1）若这轮动 ask 面板题型，**与 de-escalate 恢复面板合并一轮做、只过一次双评审**（Theory/Design）。

**实施顺序**（走 A 时）：引擎 de-escalate 事件+通道（Py-Eng，需 Theory/Design 先裁 escalated 语义=补通道非改终态，git 证据已支持）→ footer 桶+词面（TUI-Eng+Design）→ 报告去向行（Py-Eng）→ 救回入口（合并 ASK-1）。全程 no-output 子类限定+round-cap，避免 escalated 变成无限重编。
