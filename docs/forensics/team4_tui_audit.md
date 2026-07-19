# TUI 渲染 × V8 引擎显示审计（team4，增量于 team2 07-16 审计）

**日期**：2026-07-17　**审计人**：TUI-Eng（team4 任务 #13 / 用户任务 7）
**范围**：`main/ist_core/ink/**` + `main/ist_core/tui/**` 渲染层 vs `compile_engine_v8` 发射面
**基线**：`docs/forensics/team2_tui_audit.md`（2026-07-16）——本报告只报**增量**：team2 审计后 4 个引擎提交（d10f9f21 / 994709f2 / b3ce3b4c / 14c12163）引入或暴露的问题，及 team2 未覆盖的盲区。
**方法**：git 时间线锁定增量 → 发射面全量扫描（`_fork_emit_event`/`sh.emit`/`emit_tick`/`emit_summary`）→ 消费面逐字段核对（reducer/ist_app/footer/ask_user_view）→ **活体实跑取证**（cmux 只读抓屏 surface:17，dongkl 批 13 案编译中，`compile_evidence.94478.events.jsonl`）→ 渲染层回归 341 passed 基线确认。
**纪律**：全程只读（除本报告零文件改动）；未向 infotest surface 发送任何输入。

---

## 0. 结论摘要

- **team2 报的事件侧缺陷已闭环**：broken 三态投影已修（`_shared.py::_footer_bucket_counts` 折进 failed_active，d10f9f21），渲染层「其他N」残差桶与之协调（残差自然归 0，不冲突）✅。
- **新发现 1 项 P0**：`engine_summary` 的 `decisions` 字段（G4 用户裁决「引擎理解为」echo，坑#21 修复的核心载荷）**TUI 丢弃且无其他出口——功能全灭**。
- **新发现 7 项 P1**：①author 期 footer 相位/进度冻结（实弹 13 分钟停「准备」，events.jsonl 全程仅 1 条 tick）②引擎 3 处 LangChain 通道调用冒充主 agent 事件（`⏺ 解析脑图` 假主行实弹 + usage 灌主计数 + 主活动日志污染）③busy 行「深度思考中(+75)」相位卡死（三帧 8m/13m/19m 冻结铁证；reducer usage_only 提前 return 不清相位）④「最大深度思考中」在其主场景不可见/失真（与③同根）⑤ask 面板「数字直选」提示与实际行为矛盾（run15/17 丢答文案面残留)⑥multiSelect 题 enter 推进无未提交守卫 + 单题 multiSelect 空提交无告警⑦⑧evidence 行两处术语泄漏（「上机[delivery]」英文枚举；对账行裸 JSON 实弹）。
- **P2 若干**：见 §4。
- **正确面**（增量核对全过）：13 态→9 桶投影完整、11 节点 phase 中文映射全覆盖、**工具映射零新缺口**（994709f2 未新增 LLM 工具；`submit_answers` 是 TUI 端 API 非工具、`remember` 属裸名核心规约）、progress 事件字段与渲染完全对齐、多行题面/digest 300 字 emit 换行安全、`tests/tui/`+`tests/ink/` 341 passed。

---

## 1. 事件 × 渲染对齐矩阵（增量复核）

V8 fastlog 事件全集（发射面 grep 实证）＝7 种：`fork_start / tool / tool_result / fork_end / engine_tick / engine_summary / progress`。

| 事件 | 发射点 | 活体实测（94478，author 期 13min） | reducer 处理 | 增量结论 |
|---|---|---|---|---|
| `fork_start` | loader.py:1129 | 13 | reducer.py:588 | ✅ |
| `tool` | loader.py:964 | 360 | reducer.py:598 | ✅ |
| `tool_result` | loader.py:983 | 360 | reducer.py:606 | ✅ |
| `fork_end` | loader.py:1135 | 11（2 在跑，对账✅） | reducer.py:614 | ✅ |
| `engine_tick` | _shared.py:296（5 调用点） | **1（仅 prep）** | reducer.py:632 | ⚠ P1-1 发射粒度 |
| `engine_summary` | _shared.py:65 | 0（未到 closing） | reducer.py:642 | 🔴 P0-1 字段丢弃 |
| `progress` | batch_tools.py:681/694 | 0（未到 run） | reducer.py:654 | ✅ 字段逐一对齐（key/phase/elapsed_s/total_s/n_cases/env/case_idx/detail/status 全收） |

孤儿/死码：`run_meta` 维持 team2 记录——全仓仍无生产者，reducer.py:625 消费分支为死码；**增量**：`skills/loader.py:608` 注释与 CLAUDE.md「TUI 验证」节仍把 run_meta 列进事件清单（文档漂移，P2-1）。

---

## 2. P0 发现

### P0-1　engine_summary 的 `decisions`（G4 echo）与 `report_mismatch` 字段被 TUI 丢弃——G4 功能全灭

- **发射**（nodes.py:2886-2895，closing）：`{outcome, decisions, ok, total, labels, report, files, missing, report_mismatch}`。
  `decisions` = `_g4_decision_echoes(fs)`（nodes.py:2348-2360）：每条实答 decision → `{autoid, answer, understood}`——设计意图（(41)③ / §18.6 坑#21）：「每条用户裁决带『引擎理解为』复述，**截断/兜底误判在收口卡上可核对**」（run12 实录：『停止:…』截断被兜底成 retry，echo 上 answer 与 understood 明显相悖即可人眼抓获）。
- **消费**（reducer.py:642-653）：只收 `run/outcome/ok/total/labels/report/files/missing`——**`decisions`、`report_mismatch` 不收**；`_render_fork_card` 收口卡分支（ist_app.py:380-398）也不渲染。
- **无替代出口**（grep 实证）：`decisions` 不进 delivery_report.md（render.py 无消费）、不进 engine_report.json——**engine_summary 是唯一出口，TUI 丢弃＝坑#21 修复只做了发射半程，用户永远看不到 G4 echo**。
- **伴生**：`outcome` reducer 收了但收口卡不渲染——收口卡头部只按 `ok == total` 二分；`outcome=report_mismatch`（报告数字与视图失配，最严重）在收口卡上**零视觉痕迹**（`delivery_incomplete` 尚有 missing 行兜底可见）。
- **修法建议**（渲染层，本队可修）：reducer engine_summary 分支补收 `decisions`/`report_mismatch`；收口卡渲染追加「你的裁决 · 引擎理解为」对照行（≤4 条 + 「另有 N 条见报告」）与 `report_mismatch=True` 时的红字告警行。**引擎侧配套**（归 main 分配）：`decisions` 同步落 delivery_report.md（用户离线也能核对）。

---

## 3. P1 发现

### P1-1　engine_tick 只在节点出口发——author 期 footer 相位/进度全程冻结（实弹）

- **实弹**（两帧抓屏 + events.jsonl）：编译开跑 13m17s，画面上 12/13 编写卡已「✓ 完成」，footer 底行始终 `` 编译 CNAME pool支持ipo算法_dongkl · 轮次0 准备 ░░░░░░░░░░░░░░░░░░░░ ``——phase 停「准备」、进度条全空、counts 停 prep 快照。**同屏自相矛盾**（上方 9+ 张完成卡 vs 底行 0 进度）。
- **根因**：5 个 emit_tick 调用点全在节点**尾部**（nodes.py:156/449/1157/1629/2899）；author（worker_fanout）是最长节点（本批 11min+），fanout 全程零 tick。bed_gate/merge/run/diagnose/ask_* 六节点不发 tick（merge/run 有 ◆ 里程碑行与 progress 卡兜着；bed_gate 期同样停「准备」）。
- **修法建议**（引擎侧）：worker_fanout 内每个 fork 结算时补 `emit_tick(state, "author", fs)`（引擎一行，counts 现算本就便宜）；或渲染层用 fork 卡完成计数兜底刷进度条（不推荐——两套真相）。

### P1-2　引擎 3 处 LangChain 通道调用冒充主 agent 事件（实弹 + 代码证）

- **代码**：引擎节点内走 LangChain `.invoke` 通道（callbacks 经 contextvar 从 qa_node 工具执行传播 → `_MainAgentProgressHandler` 收到 → metadata 无 `lc_agent_name`、引擎线程非 fork 线程（`current_fork_label()` 空）→ 判成**主 agent 事件**）：
  1. `nodes.py:114` `compile_prep.invoke({...})`（prep 节点）
  2. `nodes.py:859` `compile_emit_merged.invoke({...})`（merge 节点）
  3. `nodes.py:103` `m.invoke([...])`（`_bed_llm_fn` 床态恢复轻 LLM 直调）
- **实弹**（抓屏帧1）：`⏺ 解析脑图(CNAME pool支持ipo算法_dongkl)` + `⎿ === compile_prep ===` 结果块以**主 agent 工具行**形态进主 transcript——用户视角是「main agent 自己调了解析脑图」，层级失真。merge 时会再冒一条 `⏺ EmitMerged`。
- **连带**：① graph.py:373 `record_main_activity` 把引擎内部调用记进主 agent 活动日志（取证面污染）；② `_bed_llm_fn` 的 usage 走 graph.py:279 `usage_only` **灌进主 agent token 计数**（footer ↑↓ 与 ¥ 成本虚高）；③ 若 flash 端点回 reasoning/text，会以 `∴ Thinking` / `⏺` 散文形态混入主 transcript（bed 恢复命令文本冒充主 agent 发言）。
- **修法建议**（引擎侧，与 V8「引擎直调工具 .func」既有纪律一致）：nodes.py:114/859 改 `.func(...)` 调用（同文件 :68/:503/:1172/:2375 全是 `.func` 先例——这两处是漏网）；`_bed_llm_fn` 用 `with_config(metadata={"lc_agent_name": "engine-bed"})` 或剥离 callbacks（`config={"callbacks": []}`）出主 run tree。

### P1-3　busy 行「深度思考中(+75)」相位卡死（实弹 13min 冻结）

- **实弹**：帧1（8m34s）与帧2（13m17s）busy 行同为 `✶ Reflecting… (… · ↓ …(+75) tokens · 深度思考中)`——`(+75)` 完全冻结、「深度思考中」驻留全程。main agent 实际阻塞在 compile_engine_run 工具调用，**并不在思考**；75 token 也非活跃流。
- **机理链**（代码可证的组成）：
  1. `llm_token` 唯一来源＝astream_events `on_chat_model_stream`（streaming.py:36），fork 判定＝`metadata.lc_agent_name`（streaming.py:123-125）；
  2. 引擎线程 LLM 调用（P1-2 之 `_bed_llm_fn`）进主 run tree 且无 lc_agent_name → reasoning delta 以「主 agent token」驱动 `_llm_phase="thinking"`（reducer.py:312）；
  3. `reducer._on_llm_end` 对 `name=="usage_only"` **提前 return（reducer.py:342-343），不清相位、不清 `_output_token_count`**——若某调用的 end 只以 usage_only 形态到达（或 final_thought 因 text 空缺席），相位从此卡死到 run_end。
- 精确到哪一次调用发的 75 token 需 bus 级取证（bus 不落盘；建议修复时在 reducer 加 llm_token 来源 tag 采样日志，或交叉 Langfuse trace——LLM-Eng 任务 #8 可协查）。**「显示与事实不符」本身已实锤**。
- **修法建议**（渲染层，本队可修）：`_on_llm_end` 的 usage_only 分支在 return 前不清相位是刻意的（usage_only 与 thought 是同一次调用的两条 end）——真正的修法是**给相位加心跳过期**：`_on_token` 记 `_phase_ts`，footer/`snapshot` 侧超过 N 秒（如 90s）无新 token 增量即回落无相位显示；治卡死也治任何未来漏标源。

### P1-4　「最大深度思考中」在其主场景不可见或失真（与 P1-3 同根）

- footer.py:304：`if _state and self._max_thinking and self._llm_phase == "thinking"` → 升格「最大深度思考中」。
- 编译重编轮（fork effort=max，该功能唯一使用场景）里 main agent 阻塞在引擎工具，**合法路径下 `_llm_phase` 应为空**（fork token 被 `_is_fork_event` 挡在主相位外，reducer.py:305）→ `_state=None` → 升格条件永不成立，max 状态不可见；
- 而实弹中相位是靠 P1-3 的**泄漏+卡死**碰巧维持「thinking」——若届时有 fork 在 max，会显示「最大深度思考中」，但驱动它的相位本身是假的。即：该功能当前**依赖一个 bug 才可见**。
- team2 §3 只验证了 `_payloads_have_max_thinking` 谓词与置位链，未验证「编译期 main 无相位」下的联动可见性——本条为增量。
- **实弹证实（帧4，22m57s）**：重编轮 4 张「第2次」卡（effort=max）在跑时 busy 行确实升格 `…最大深度思考中`——但驱动它的 `_llm_phase=="thinking"` 正是 P1-3 的卡死假相位（同帧 `(+75)` 仍冻结）。「依赖 bug 才可见」不再是推断而是实测：**修 P1-3（相位过期）必须与本条成对修**，否则该功能退回永不显示。
- **修法建议**（渲染层）：max_thinking 置位时不要求 `_llm_phase=="thinking"`——fork 在 max 思考是独立于主相位的事实，可在无相位分支（footer.py:329-341 的等待形态）尾挂「· 最大深度思考中」。

### P1-5　ask 面板「数字直选」按键提示与实际行为矛盾（丢答文案面残留)

- 提示行（ask_user_view.py:131）：「↑↓ 选择 · **数字直选** · …」；实际（:165-172）：数字键**只移动高亮**（`_highlight = n-1`），不落 `_selected`——落答只有 enter（单选）/space（多选）。
- 「直选」承诺了「按数字即选定」——正是 run15/run17「数字只高亮，每题必须 enter」两次 3 题丢 2 的用户心智模型根因（`[[tui-multiquestion-panel-key-semantics]]`）。994709f2 加的 `_touched` 切题/esc 告警是**行为面缓解**，但提示文案仍在主动教用户犯错。
- **修法建议**（渲染层，一行）：「数字直选」→「数字跳行」或「数字高亮」；或者把语义改真——数字键单选场景直接落选（对齐 Claude Code AskUserQuestion 面板惯例），彻底消灭这类丢答。改语义属交互变更需用户拍板，改文案零风险。

### P1-6　multiSelect 题 enter 推进无「已选未提交」守卫；单题 multiSelect 空提交无告警

- 994709f2 防呆矩阵：←→/Tab 切题（`_guard_switch`）与 esc（`_guard_cancel`）都拦「动过高亮未落答」；**enter 也是一种离开当前题**（`_on_enter` → multi 分支不落选直接 `_advance_or_submit`，ask_user_view.py:287-290/318-332），却无同款守卫——多选题按数字高亮后直接 enter → 静默空答案推进（用户以为答了）。
- 末题兜底 `还有 N 题未答` 告警条件是 `n and len(self._questions) > 1`（:328）——**单题 multiSelect** 空提交完全无告警直通 `_submit`；工具侧返回 `"Q"=""` 空答案（`submit_answers` 的 answers dict 非空、不判 cancelled），下游空答案语义再次进入 532862 修复前的模糊地带。
- **修法建议**（渲染层）：`_advance_or_submit` 推进前对 multiSelect 复用 `_has_uncommitted_selection` 走 `_warn_once("advance", …)`；末题告警去掉 `len>1` 条件。

### P1-7　run 节点 evidence 行「上机[delivery]」英文枚举泄漏（同对词 merge 侧已翻译)

- nodes.py:886（merge）：`合并[{'整卷' if is_delivery else '子集'}]` ✅ 中文；
- nodes.py:942（run）：`上机[{state.get('run_ctx')}]:{len(comp)} 案 @ {bed_host}` ——`run_ctx ∈ {delivery, subset}`（state.py:29）**原值直出**，用户面显示「上机[delivery]:13 案」。同一对语境词一处翻一处不翻；render.py 明有现成词表 `CTX_CN = {"delivery": "整卷连跑复验", "subset": "单独验证"}`。
- **修法建议**（引擎侧一行）：`RD.CTX_CN.get(str(state.get('run_ctx')), …)` 或对齐 merge 的「整卷/子集」短词。

### P1-8　reconcile evidence 行把内部状态 JSON 原样拍进用户面（实弹）

- **实弹**（帧3，attribute 期）：`` ◆ 对账:11 裁决入流(pass 7) → {"failed": 3, "deliverable": 7, "escalated": 2, "broken_errored": 1} ``——nodes.py:1155-1156 把 counts dict 的 `json.dumps` 直接拼进 `sh.emit`。用户面出现裸 JSON 语法 + 英文状态枚举（failed/deliverable/escalated/broken_errored），是 evidence 通道上最重的一处术语泄漏（render.py 的 leak_scan 零术语纪律只挂在报告面，evidence 行无门）。
- **修法建议**（引擎侧）：复用 `RD.STATUS_CN` 渲染成人话短语（如「未通过3 · 可交付7 · 升级人工2 · 需重写1」）；或该行降为 debug 日志、evidence 只留「对账:11 裁决入流(通过 7)」。

---

## 4. P2 发现

| # | 位置 | 内容 |
|---|---|---|
| P2-1 | `skills/loader.py:608` 注释、CLAUDE.md「TUI 验证」节 | 事件清单仍列 `run_meta`（无生产者）；reducer.py:625 死码维持 team2 记录待删 |
| P2-2 | `ist_app.py:295` `_render_engine_bottom_line` docstring | 仍写「broken 三态未进任何键（事件侧缺陷，已另记报告）」——d10f9f21 已修，注释过时；「其他N」残差桶保留是对的（防将来新态漏投），但叙述该改成「防御性残差」 |
| P2-3 | `ist_app.py:203-209` `_tool_display_arg` compile_engine_run 分支 | `label = ver or _arg_stem(mm)`——ver 优先使实弹显示 `⏺ EngineRun(10.5)`；tui_architecture.md 与 CLAUDE.md 示例形态均为 `EngineRun(dongkl)`（批名才有辨识度，版本号大家都一样）。建议 `_arg_stem(mm) or ver` |
| P2-4 | `_shared.py:298` emit_tick `round=vol_seq` | `vol_seq`＝「合并卷序号」（state.py:30，merge 成功即 +1，nodes.py:855——含终验卷、不重编也递增），footer 显示「轮次N」。语义近似但非重编轮次：终验轮会显示「轮次3」而实际重编 2 轮。低危，建议 footer 文案改「卷N」或引擎侧另给真轮次 |
| P2-5 | `engine_tool.py:44` `_panel` 答案解析正则 | `(?=\. "|\.?\s*$)` lookahead——Other 自由输入含 `". "` 序列（如 `改成"x". "y"也行`）会早停截断答案。低概率；根治是 ask_user 返回结构化答案而非文本反解 |
| P2-6 | `questions.py:135-137` 三元组题面 | q_text 含 `\n`——TextNode 支持内嵌换行（dom.py:149 wrapped_rows 计入），**渲染安全**；仅排版观察：题号 `(1/2)` 拼接在末行行尾、续行无缩进对齐 |
| P2-7 | `streaming.py:9` docstring | 「on_tool_start -> tool_call（唯一 tool_call 源）」过时——`_KIND_MAP` 并无 on_tool_start（落默认 info）；实际唯一源是 graph.py handler。文档漂移 |
| P2-8 | nodes.py:1097/1099 | 「协议级 Errored/Blocked」英文码进用户面 evidence 行——均带中文解释括号，属可接受技术标识；记录不改 |
| P2-9 | 抓屏帧2 busy 行 | `…深度思考中` 右括号被终端宽度截断——`_middle_ellipsis` 不覆盖 busy 行（footer 状态行无截断保护），窄终端下形态破损。cosmetic |

---

## 5. 增量核对通过项（无发现）

1. **broken 投影闭环**：`_footer_bucket_counts`（_shared.py:272-287）13 态每态恰入一桶（broken 三态→failed_active，suspended→failed_terminal），测试锚 `test_footer_projection` 在；渲染层「其他N」残差桶在投影完整时恒隐藏——两侧协调 ✅。
2. **11 节点 phase 映射**：graph.py 节点全集（prep/bed_gate/author/ask_decision/merge/run/reconcile/attribute/diagnose/ask_contradiction/closing）对 `_ENGINE_PHASE_CN` 全覆盖（team2 补 diagnose 后维持）✅。实发 tick 的 5 个 phase 全有中文。
3. **工具显示名**：注册表全量（41 工具）对照 `_TOOL_SHORT_NAMES`——零新缺口。994709f2 未新增 LLM 工具（`_submit_attribution_locked` 等为私有函数）；`submit_answers` 是 TUI 回写 API（非 @tool）；`remember` 属 CLAUDE.md「裸名核心」规约。实弹抓屏 `Read/Help/Probe/解析脑图/EngineRun` 显示正常 ✅。
4. **progress 事件**：batch_tools.py 发射字段与 reducer/`_render_fork_card` progress 分支逐一对齐；`第X/N` 诚实推进、done/error 收尾形态齐备 ✅。
5. **14c12163 digest 300 字留声**：`sh.emit("⚠ 上机未产出结果——digest 返回:{head}")` 流经 BLOCK_EVIDENCE——多行 split 逐行 `◆` + `_middle_ellipsis(ln,160)`，换行安全、超长有省略留痕 ✅（中段信息被省略可接受，完整 error 在 engine_report）。
6. **ask 面板既有防呆**（team2 修 + 994709f2 加）：空 Other 拦截、切题/esc 告警一次再放行、`(1/2)` 计数、双向导航选态保留、`_warned_op=="submit"` 二次 enter 不误入 Other 输入态——状态机自洽 ✅（缺口见 P1-5/P1-6）。
7. **回归基线**：`tests/tui/ tests/ink/` **341 passed**（2.04s）✅。
8. **fork 卡实弹形态**：13 张编写卡「第1次」写轮标、✓ 完成定格（calls/时长/↑↓token）、running spinner+当前工具+计时原地走、`编写·尾6位` 标识——与 tui_architecture.md 契约一致 ✅。

---

## 6. 实跑取证记录（surface:17，dongkl 批 13 案，只读抓屏）

- **帧1**（开跑 8m34s）：`⏺ EngineRun(10.5)`（P2-3）、`⏺ 解析脑图 + ⎿ 结果块`（P1-2 实锤）、◆ prep/床态体检/派发 里程碑行正常、9✓+4 running 编写卡正常、busy 行「深度思考中(+75)」（P1-3）、footer 底行「轮次0 准备 ░░░」（P1-1）。
- **帧2**（13m17s）：12✓+2 running；busy 行 `(+75)` 与「深度思考中」**纹丝不动**（P1-3 冻结实证）；footer 底行仍「准备/空条」（P1-1）；右括号截断（P2-9）。
- **帧3**（19m6s，已推进到 attribute）：busy 行 `(+75)`「深度思考中」**第三帧仍冻结**（8m34s→13m17s→19m6s 三点铁证链）；`◆ 对账:… → {"failed": 3, …}` 裸 JSON 进用户面（P1-8 实锤）；归因 fork 卡（`⠋ 归因·035644 ↳ Read(…) · 15 calls`）正常；协议级 Errored ◆ 行（P2-8 形态）实弹出现；footer hint 行「⚠ Langfuse 上报有失败」obs 告警正常工作 ✅。
- **帧4**（22m57s，重编轮）：4 张「第2次」编写卡（写轮标✅）并发；3 张归因卡完成态✅；busy 行 `(+75)` **第四帧仍冻结**且升格「**最大深度思考中**」——P1-4「依赖假相位才可见」实弹证实；`◆ 派发 4 个编写` 里程碑正常。
- **tick 时间线**（94478 全程）：`prep(r0, total=13) → author(r0) → reconcile(r1, failed_active=4) → attribute(r1)`——「节点出口才 tick」模式、round=vol_seq 在 merge 后翻 1（P2-4）、attribute 段 footer 投影正确（round/counts）均获机器证据；事件计数 `{engine_tick: 4, fork_start: 20, tool: 473, tool_result: 469, fork_end: 16, progress: 5}`。
- 未及阶段（ask 面板/engine_summary 收口卡实弹帧）：编译仍在跑，后续由任务 #2（Test-Eng）继续盯屏（ask 面板出现时补抓「答前/答后/ctrl+o 重放」三态，验证 6799570f 答后清除链）；本报告对应结论来自代码审计 + 单测，置信度已标注。

---

## 7. 修复归属建议（供 main 分配）

| 发现 | 层 | 建议归属 |
|---|---|---|
| P0-1 reducer/收口卡补 decisions+report_mismatch+outcome 渲染 | 渲染层 | TUI-Eng 可修（引擎侧配套落报告归引擎队） |
| P1-1 author 期补 tick | 引擎侧（nodes.py 一行/fork 结算点） | 引擎队 |
| P1-2 三处 `.invoke`→`.func`/剥 callbacks | 引擎侧 | 引擎队（改后 P1-3 的泄漏源同步消失） |
| P1-3 相位心跳过期 | 渲染层 | TUI-Eng 可修 |
| P1-4 max_thinking 摆脱主相位依赖 | 渲染层 | TUI-Eng 可修 |
| P1-5 「数字直选」文案（或语义改真——需用户拍板） | 渲染层 | TUI-Eng 可修 |
| P1-6 enter 推进守卫 + 单题末题告警 | 渲染层 | TUI-Eng 可修 |
| P1-7 上机[delivery] 翻译 | 引擎侧一行 | 引擎队 |
| P1-8 对账行 JSON→人话（STATUS_CN 复用） | 引擎侧 | 引擎队 |
| P2-1/2/7 注释与文档漂移、P2-3 参数摘要顺序、P2-9 busy 行截断 | 渲染层/文档 | TUI-Eng 可修 |
| P2-4 vol_seq 轮次语义、P2-5 答案反解 | 引擎侧 | 引擎队（低优先） |

（依纪律，审计轮**零代码改动**——修复经 main 分配任务 #21 后执行，见 §8。）

---

## 8. 修复执行记录（任务 #21，2026-07-17，TUI-Eng）

**范围**：§7 归属清单中渲染层项，全部落地；引擎侧项归 Py-Eng #18（耦合点已互验，见下）。

| 发现 | 修复 | 文件 |
|---|---|---|
| P0-1 | reducer engine_summary 补收 `decisions`/`report_mismatch`；收口卡渲染「你的裁决(引擎理解为)」对照段（≤4 条+折叠）；outcome 视觉区分——`report_mismatch`→`⚠ 交付完成(对账失配)`、`delivery_incomplete`→`⚠ 交付不完整`，头部不再谎报 | `tui/reducer.py` + `ink/components/ist_app.py` |
| P1-3 | footer 相位心跳过期：`(_llm_phase, _output_token_count)` 签名冻结超 `_PHASE_STALE_S=90s` → busy 行回落等待形态（治卡死假相位，兼防未来任何漏标源） | `ink/components/footer.py` |
| P1-4 | 成对修：max_thinking 摆脱主相位依赖——无相位等待形态尾挂「· 最大深度思考中」；thinking 相位升格逻辑保留（main 真思考+fork max 并存场景） | `ink/components/footer.py` |
| P1-5 | 提示文案对齐实际语义：「数字直选」→「↑↓/数字 移动」；单选「enter 选定」、multi 非末题「enter 下一题」/末题「enter 提交」 | `ink/components/ask_user_view.py` |
| P1-6 | multiSelect enter 推进补「已选未提交」守卫（告警一次再放行，与切题/esc 同款）；末题空提交告警去掉 `len>1` 条件（单题 multiSelect 空提交也拦一次，文案区分单/多题） | `ink/components/ask_user_view.py` |
| P2-2 | `_render_engine_bottom_line` docstring 改述「防御性残差」（broken 已修事实入注） | `ink/components/ist_app.py` |
| P2-3 | EngineRun/compile_prep 参数摘要批名优先（`_arg_stem(mm) or ver`），对齐文档契约 `EngineRun(dongkl)` | `ink/components/ist_app.py` |
| P2-9 | `_update_thinking_line` 重写为 ANSI 感知截断：CSI 序列整体透传（不再从 ESC 序列中间截断泄漏坏序列/粗体不复位），截断补 `…`+`\x1b[0m` | `ink/components/ist_app.py` |

**新增测试 10 个**（全绿）：footer 相位过期×2/max 无相位可见/max 过期共存（`tests/ink/test_footer_token_phase.py`）；收口卡 G4 echo 渲染/outcome 区分（`tests/tui/test_fork_cards_render.py`）；reducer decisions 透传（`tests/tui/test_reducer.py`）；multi enter 守卫/单题空提交告警/提示文案语义（`tests/ist_core/test_ask_user.py`）。

**回归**：`tests/tui/`+`tests/ink/` **348 passed**（341 基线+7）；全量 `tests/` **2152 passed, 1 skipped**（skip 为实数据不在盘的既有跳过）。未 commit（按纪律待 main 汇总）。

**与 Py-Eng #18 的耦合点互验**：其已在 nodes.py 堵 P1-2 泄漏源（`_bed_llm_fn` 打 `lc_agent_name: "engine-bed"` 标、compile_prep/compile_emit_merged 改出 LangChain 通道）——与本队相位心跳过期是同一症状两侧：源头堵住后主相位不再被假驱动，心跳过期作为未来漏标源的通用防线保留；max 状态经 P1-4 尾挂在两侧任意合入顺序下均可见，「深度思考」显示无回归窗口（混合工作树全量 2152 绿实证共存）。

**未修留档**：P2-1（loader.py 注释）/P2-7（streaming.py docstring）在 tui/ink 边界外（skills/ 与 ist_core 顶层），P1-1/2/7/8、P2-4/5 归引擎侧——均已在 §7 标注归属。视觉生效说明：本队改动大部分不热加载进在跑的编译进程（94478），重启后生效；**例外**见 §9（ask_user_view 经函数内延迟 import 已在批 1 现场生效并获实弹验证）。

---

## 9. ask 面板实弹追验 + 新发现 P1-9（TAB 叠影，已修）

批 1 首个 ask_contradiction 面板（035413 裁决）实弹落地，三项追验 + 一项新发现：

### 9.1 「答后不清除」残留（6799570f）——实证根治 ✅
答后抓屏：面板已消失、transcript 留 `● 已回答 · {题干} → {答案}` 摘要行、引擎流程继续（EmitMerged/合并/上机 ◆ 行接续）。`_finish_ask_user` 清面板+留摘要链工作正常。（ctrl+o 重放不复活已答面板有单测锚 `test_ist_app_replay_snapshot`，实弹重放态待 Test-Eng 驱动时补抓。）

### 9.2 P1-5 新文案意外获实弹验证 ✅（观察点②定性）
实弹提示行「↑↓/数字 移动 · enter 选定 · o 自定义 · esc 取消」与 #21 新文案逐字一致（单题：无切题段、非 multi 无 space 段）。**定性**：`ask_user_view` 全仓唯一 import 点是 `ist_app._begin_ask_user` 的**函数内 import**（ist_app.py:1984）——本进程首个 ask 面板发生在 #21 改码之后，模块首次加载读的是新代码 → P1-5/P1-6 在批 1 现场已生效。不是「新旧分支文案不一」。

### 9.3 G4 echo 流水行实弹 + 引擎侧语义兜底误译一例（记引擎队）
实弹 ◆ 行：`…035413 你的裁决「按脑图原意验证回退池生效，拆两步：第1步 dig」→ 引擎理解为:确认产品缺陷(语义兜底,非选项原文——请核对)`——G4 echo 的**流水行形态**工作正常且自带核对提示（收口卡形态经 P0-1 修复后下批可见）。**同时暴露真实误译**：用户 Other 答案是条件句（「拆两步验证…**若第2步仍不返回**才按产品缺陷候选结案」），被 `_defect_intent` 归成无条件「确认产品缺陷」——正是 G4 设计要暴露的场景（echo 并排即人眼可抓）。语义归类质量归引擎侧（questions.py `_defect_intent` 否定门不覆盖条件句），非渲染缺陷。

### 9.4 P1-9（新，P1 级，已修）：题面引文携带 `\t` → 终端叠影碎片（观察点①定性）
- **实弹**：答后摘要行显示 `实机回显:『www.a.com.域名命中回 60 情况)IN 册与 CNAMEcliwww.5_Chapter20.md:…`；leader 巡检帧另见「www.local.co0.md」尾字符被吃。
- **数据源对照**（`runtime/ask_user_answers.jsonl` 第 2663 条）：题干落盘原文**完全干净**——`实机回显:『www.a.com.\t\t60\tIN\tCNAME\twww.local.com.』；cli_10.5_Chapter20.md:…`。**引文里是 dig 回显原样的 TAB 字符**。
- **根因（渲染核级）**：`char_width('\t')` 走 `code<0x1100→1` 按 1 列布局，真实终端却把 `\t` 解释为跳至下一 8 列制表位**且不清除跳过区**——布局模型与终端背离：跳过区残留前帧字符（屏上碎片「域名命中回」「册与」正是本面板前文），后续所有字符列偏移使 screen diff 更新错位。任何来源的 `\t`（设备回显/文件内容）进 TextNode 都触发，非 ask 面板独有。
- **修复（渲染核,本队）**：`dom.py` 新增 `_sanitize_text_value`——TextNode 两个值入口（`__init__`/`set_value`）统一规格化：`\t`→单空格（确定性 1 列）、`\r` 剥除（回车拉光标回行首覆盖，同族破坏者）、`\n` 保留；无控制字符快速路径零开销。测试 `test_textnode_sanitizes_tab_and_cr`（tests/ink/test_cjk_desync_gates.py）。
- **拼装侧配套（记引擎队,双侧防御）**：questions.py 题面嵌设备回显引文处建议同步规格化（数据面干净不依赖显示层兜底；jsonl/Langfuse 里的题干也会更可读）。注：`clip_text` 已对 hypothesis 做 `" ".join(split())` 规格化,但 **sides 走 `_side_cn` 的 verbatim 契约直通**（questions.py:396「引文一字不动」）——该契约本意是 LLM 载荷纪律,用户题面展示层规格化不违契约,归引擎队定夺。
  **→ 已落地（Py-Eng,2026-07-17）**：questions.py 新增 `_display_clean` 挂 `_side_cn` quote 与 panel ask 两个展示投影点（落盘/LLM 载荷 verbatim 不动）——双侧防御闭环。端到端测试的前提自检随之由 Py-Eng 翻转（`"\t" not in question`,锁拼装侧第一侧）;dom 层第二侧的独立锁=既有 `test_textnode_sanitizes_tab_and_cr`（直接喂 dom 带 TAB 文本,不经拼装,兜任何未来漏标源）——两侧各有独立测试锚,合成效果由端到端锁,覆盖链完整（8 passed 复核）。

### 9.5 「丢显」与「粘连」同根定性（Test-Eng 移交,数据层三方对照闭环）

Test-Eng 定性「题面丢显=渲染侧（ask_panel.json 数据层完好）」——本队三方对照收口：
- **数据层**（`workspace/outputs/204651759025035413/ask_panel.json`）：`sides[0].quote` = `"www.a.com.\t\t60\tIN\tCNAME\twww.local.com."`——**5 个真实 TAB**（dig 回显原样,verbatim 契约保真）。「数据层完好」精确说法=内容完好但携带控制字符。
- **拼装层**：`build_ask_question` → `_side_cn`（verbatim,不剥 \t）→ TAB 直通题干（jsonl 落盘题干可证）。
- **渲染层（症状根源）**：同一 \t 宽度背离（char_width=1 列 vs 终端 8 列制表位）产生**两个症状面**——①跳过区不清=**粘连碎片**（leader 帧「www.local.co0.md」）；②列偏移积累+终端硬折行被下一行覆盖=**中段丢显**（Test-Eng 帧:实机回显尾+手册文件名 cli_10.5_Chapter20.md 整段不可见,用户裁决时看不到完整证据）。
- **同根同修**：§9.4 的 dom 层 TextNode 规格化对两症状一并根治。**端到端测试**（`tests/ink/test_ask_user_panel.py::test_tab_bearing_sides_quote_renders_complete_and_tab_free`）：用 035413 真实 sides 形态走 `build_ask_question → AskUserSession.render_lines → AskUserPanel.update` 全链,断言面板节点值零 TAB 且两侧证据关键子串（`www.a.com./60/IN/CNAME/www.local.com./cli_10.5_Chapter20.md/SDNS回退池`）全部可见。

**§9 后回归**：渲染层 **350 passed**（341 基线+9）、全量 **2154 passed, 1 skipped**（复跑确认;其间一次 `test_diagnose_common_cause_cluster` 全量挂/单跑绿/复跑绿=顺序敏感 flaky,疑与并行编译进程实时写 workspace 相关,非本队改动面,记测试卫生域）。

---

## 10. P1-10（Test-Eng 批 1 取证移交,已修）：fork 白跑假完成显示

**现象**：035493/035570 两个 worker fork 正常结束（`ok:true`）但零产物零尾块（白跑,引擎结算判 escalated）,TUI 卡片打「✓ 完成」绿标——用户以为案子编完。

**取证**（94478 events.jsonl）：白跑 fork 的 `fork_end` 与正常 fork **在事件层完全无差别**（ok:true、13-25 calls、12-15k tokens_out 均为"正常干活"形态）——渲染层拿现有字段判不出,必须发射侧补机械事实。

**引擎判据溯源**（nodes.py author 结算,:413-435）：`fresh = case.xlsx 存在 ∧ mtime >= t0-1` + `_TAIL_RE`（`^STATUS:\s*(produced|needs_user_decision|failed)`）——白跑=非 fresh ∧ 尾块非 needs_user_decision → escalated "no output from fork"。

**修复（发射侧纯采集 + 渲染侧合取,leader 授权跨发射侧）**：
- `skills/loader.py` 新增模块级 `_fork_end_evidence(output, autoid, t0_wall)`：fork_end 事件补两枚**零语义机械事实**——`tail_status`（STATUS 尾块值,引擎 _TAIL_RE 同款语义）+ `artifact_fresh`（案卷 mtime>=fork 开始墙钟-1s,引擎 fresh 同款容差;无 autoid/stat 失败不带字段）。语义判断不放通用 fork 执行层。
- `tui/reducer.py` fork_end 透传两字段（旧事件缺省=None,向后兼容不误判）。
- `ink/ist_app.py` `_render_fork_card` 完成态合取判：`skill=="compile-worker" ∧ artifact_fresh is False ∧ 无尾块` → 黄 `⚠ 编写·xxx — 完成·无产出(引擎按无产出处理)` 替代 ✓ 绿标。有尾块（needs_user_decision 欠定上报）=有交代不算白跑仍 ✓;attributor 等产物形态不同的 fork 不误伤;旧 events.jsonl 渲染不变。

**测试 3 层**：`test_fork_end_evidence_collects_tail_and_freshness`（loader 采集:尾块抽取/新鲜度/无 autoid 不带字段）、`test_fork_end_passes_silent_run_evidence`（reducer 透传+旧事件兼容）、`test_fork_card_silent_run_shows_warning_not_checkmark`（白跑 ⚠/正常 ✓/欠定 ✓/attributor 不误伤/旧事件 ✓ 五形态）。

**顺带确认**：Py-Eng 已按本报告 P1-1 在 author 每 fork 结算处补 `emit_tick`（nodes.py:436-438,注释引用本审计）——P1-1 引擎侧闭环 ✅。

**§10 后回归**：渲染层+loader 事件面 **363 passed**、全量 **2157 passed, 1 skipped**。

---

## 11. 后续池（批后收口批处理,不阻塞修复批 commit）

### P2-10　思考计时器断线重连后显示 12h25m 异常（Test-Eng 批 2 观察;已静态定位,待批 3/4 实弹复核）

- **现象**：（驱动会话）断线重连后 busy 行 `✶ Reflecting… (12h25m …)` 计时异常。
- **静态定位（根因链假设,代码可证）**：`footer._start_timer`（footer.py:243-246）的 early-return 在 `_busy_since = time.time()` **之前**——`if self._timer_running: return`。断线场景上一 run 的 `run_end/run_error` 事件丢失 → status 从未回 ready/error → `_stop_timer` 从未调用 → `_timer_running` 恒 True → 重连后新 run 的 `_start_timer` 被 early-return 挡住 → **`_busy_since` 停留在最初 run 起点** → elapsed 跨越整个断线期（12h25m=从最初 run 开始的真实墙钟,数值语义与实弹一致）。
- **修法方向（随批后收口批）**：`run_start`（新一轮开始）强制重置计时——footer.update 的 status 变化分支已有同型先例（footer.py:143-144 `_sticky_error = None`「新一轮开始,上一轮的错误驻留解除」）,重置 `_busy_since`/重启 verb 可挂同一位置（`_start_timer` 前先 `_stop_timer` 或加 `force` 参数）;修时补「timer_running 态收到新 run_start」的单测。
- **批 3/4 实弹复核点**：正常批间（无断线）busy 行计时是否随每轮 run 正确归零——若正常轮也不归零（run_end 到达 status 回 ready 才停表,连续多 turn 场景),影响面比断线更宽,修法同一处。

## 13.0 F-TUI 修复轮最终交付状态（2026-07-18,Design 全收口）

| F-TUI | 内容 | 状态 |
|---|---|---|
| 1 | 提交保真门:串框隔离+数字直选+末题过挡板补点(死锁修)+跨路径 armed 共享 | ✅ commit 76b916e3 |
| 3 | 引文丢中段(=P1-9 TAB 制表位) | ✅ commit 53c2338e |
| 5 | esc 分级守卫(空秒退/有已答二次确认)+A1 o 输入态提示+placeholder | ✅ commit 76b916e3(placeholder 待下窗口) |
| 8-B1 | 编写期计数冻结提示(治 P2-11 展示误读,不碰 counts/INV-7) | ✅ commit 76b916e3 |
| 10 | 失败卡英文黑话→中文映射(5 类)+未知兜底中文框(封 D1 泄漏漏口) | ✅ commit 76b916e3 |
| 11-PromptInput | 长文本水平滚动(CJK 感知,光标三位置;宽度算共享 string_width DRY) | ✅ Design P,待下 commit 窗口 |
| 2 | 选项 label 短语化 | ⏳ 跨域,等 questions.py label 模板(LLM/Py-Eng) |
| 8-B5 | 收敛可读(第M轮/剩N/趋势) | ⏳ 缓做/降级(footer 空间,Design 裁) |
| 8-B2 | 相位标签滞后 | ✅ prep→编写已修;余滞后跨域(引擎 tick 粒度) |
| 9 | 进度跨轮口径倒退+终验心跳 | ⏳ 跨域,等引擎 counts_update/progress |
| 11-P2-9 | busy 行 ANSI 截断 | ✅ commit 53c2338e(宽度算共享 string_width) |
| 4 | 超高面板空白行(P1-12)+题面截断(D9) | ⏸ 押后 ask 实弹(§13.1 重跑观测点在册) |
| 挂起 token | 未答题落显式 "unanswered" token(裁点2) | ⏸ **降级押后续批**(premise 自纠见下) |

本轮新增守门测试 ~28 个(数字直选/esc/串框/跨路径/失败卡/编写期/CJK 水平滚动/placeholder)。全量渲染层+事件面 408 passed。Design 评审全 P,redline 豁免(纯渲染不触编译链)。

## 13.05 裁点2 premise 自纠（2026-07-18,证据边界纪律,leader premise 重构后）

会签裁点2 时我引「静默降级 bug:未答空串→answer_token→correct(verifiability:477)」——**premise 双重错误,自纠**:
1. **引用文件误**:`answer_token` 实际在 `questions.py:429`(机读确认);`verifiability.py` **无此函数**。我 `grep -n` **两个文件**(verifiability+questions)但输出行号未标文件名,没核对就归到 verifiability——**教训:grep 多文件时行号必回查文件名,勿凭输出顺序臆断归属**。
2. **数据流未验**:空答 "" **不流到 answer_token→correct**——被 `nodes.py:710`(fold 空答 `if not a: continue`)+`nodes.py:2329`(`if not a:` 安全件自动挂起)两 guard 兜进 auto-suspend。"静默降级 bug"不成立。**教训:断言"X 导致 Y"要验数据流真的从 X 到 Y,不能只看 X 存在(answer_token return correct 存在)就推 Y(空答静默降级)——中间有 guard 拦截**。

**影响**:dismiss 显式 "unanswered" 从「修静默 bug(P1)」降级为「防御纵深+体验显式化(P2)」——独立价值保留(审计自证+显式化,即使将来 guard 变动仍有纵深),但**优先级降,押后续批**。F-TUI-1 提交保真门与此**正交**(挡板防手滑,与 token 归属独立),不受影响。真·空答陷阱=scheme 通道拒空(Py-Eng 本轮修,非本裁点)。

### 证据边界教训三条（2026-07-18 修复轮会签沉淀,同型:"找到来源≠验证结论")

会签中三次推论止步于"来源/存在"未验中间/维度,均被机读/Design 纠正,固化成动作:
1. **grep 多文件行号必回查文件名**(premise 自纠①):`grep -n` 多文件输出行号不标文件,勿凭输出顺序臆断归属(误归 answer_token 到 verifiability)。
2. **断言"X→Y"必验数据流真从 X 到 Y**(premise 自纠②):不能只看 X 存在(answer_token return correct)就推 Y(空答静默降级)——中间有 guard(nodes:710/2329)拦截则 X↛Y。
3. **核对到数据来源后必验映射维度**(labels 精度纠正):找到"labels.text=STATUS_CN.get(status)"≠验证了"render reason 分流自动带新人话"——STATUS_CN 按 **status** 映射、reason 分流不进它(同一 suspended 不同 reason 无法分流),需 render 单独覆盖 labels 来源。**核对到来源只是第一步,映射键/维度是第二步**。

三条同一根:**机读找到"来源/存在"后,不能止步——必验中间链路(数据流/映射维度/拦截)**,否则"找到证据"变"臆断结论"。

### 事前防错模板（leader 2026-07-18 基于本轮实证,把"事后自纠"前移为"事前防错")

上述三条教训是"事后发现",leader 升格为两个**事前**动作模板(写判定时就防错,不等纠正):

1. **根因判定末尾附「数据流已验」行**——断言 X→Y 时,输出模板强制附一行:
   `数据流已验：X →[中间点 file:行号]→ Y，无拦截`
   **写不出这行 = 没验完,不得下判定**。本轮三次误判(P1-12 未读 render_lines 就推堆叠 / :477 文件归属臆断 / 空答未验中间 guard)同根=中间环节靠推不靠读,此模板堵在源头。示范:P1-12 若按模板,须写"数据流已验:render_lines(ask_user_view:83 只渲 cur_question)→…"——写这行时就会发现"只渲当前题",不会误推堆叠。
2. **grep 多文件必带 `-H`**——多文件 grep 输出行号不标文件名 → 凭顺序臆断归属(误归 answer_token 到 verifiability)。`grep -H`(或 `-rn` 本就带文件名) 一 flag 堵死,个人纪律:凡 grep ≥2 文件,必 `-H`。

这两条 = 把"证据边界纪律"从"核对时警惕"升级为"输出时强制"(判定模板必含数据流验证行、grep 必标文件名),事前防错。

## 13.1 押后项登记（防漏·重跑观测点,2026-07-18 Design 提醒「押后≠遗忘」）

押后到 yzg 重跑实弹的项,**在册防漏**——重跑时按"重跑观测点"核验后定位再修:

| 项 | 押后原因 | yzg 重跑观测点 | 定位后修法 |
|---|---|---|---|
| **F-TUI-4 超高面板空白行（P1-12）** | 根因未定位（自纠:非"9题堆叠",render_lines 只渲当前题;题面漏 transcript 顶+9 空行来源需活跃 ask 面板实弹） | gather 面板答完后核:transcript 顶有无题面残留+空行 | 实弹定位残留来源（面板 collapse/滚动锚/布局）后修 |
| **F-TUI-4 题面截断丢信息（D9）** | 截断在引擎 facts[:300] 还是展示再截需实弹分层;与 F-Py-1 变体 A 展示层同源（跨域） | ask 面板核题面是否截断丢结论句（516576/517112/600113 类长题面） | 定位截断层（引擎[:300]/TUI 展示）后:引擎给全文或 TUI 展开 |

（登记教训同 F-TUI-11 拆批防漏:押后项也在册,重跑观测点核验,不变"遗忘"。）

## 13.2 多题 ask 面板导航两异常（D23 数字键切题 + D24 回扫光标重置;收口批同窗 #27 第⑦项,zhaiyq 首面板实弹,read-only 备料;team-lead 2026-07-18 拆两号对齐册面）

Test-Eng 在 zhaiyq 53 案首个多题 gather 面板实弹踩到两异常;改用箭头键路径（↓选/←→切题/enter 落）稳妥完成。leader 判「箭头键路径对,数字键路径病了」,修法方向我判,收口批同窗 #27 第⑦项,Design 审 UX 措辞。**均属 `ask_user_view.py`（我域,纯渲染/交互),红线豁免（不触编译链)**。

### D23　数字键"切题"——实为数字直选（B 语义）与 hint（A 文案）混用遗留

- **现象**（Test-Eng）：Q1 上 send `2` **跳到了 Q2**,而非"停在 Q1 选中 option 2";与底部 hint「↑↓/数字 移动」承诺矛盾（数字若是"移动",不该切题）。
- **机读真相**（非"没选中",是"选中了+同时前进"）：数字分支对**单选题**=`_highlight=n-1`(:192)→落答 `_selected`(:204-205)→`_advance_or_submit()`(:206)→`_q_idx+=1`(:369) **前进下一题**。即 Q1 send `2` = **option 2 确实落答**（`_selected[0]={option2}`)+ 前进 Q2;Test-Eng 因跳到 Q2 误以为"没选中"。多选题数字=`_toggle_current()`(:200-201) 勾选(同 space,不前进)。
- **根因链（P1-5 修复时 A/B 两分支混用)**：审计 P1-5(报告 :89-93) 记「数字只移动高亮不落 `_selected`」,给两修法——**A 文案改「移动」/ B 语义改真「数字落选」**。F-TUI-1 执行时 **Design 裁点1 走了 B**（数字直选落答+前进,现 :204-206),但 hint 文案却按 **A 改成「↑↓/数字 移动」(:142)**,注释(:138-140)也停在 A 的叙事「数字只移动不落答」。**语义(B)与文案+注释(A)互斥**——这是我 F-TUI-1 改代码行为时 hint/注释未同步 B 的遗留。
- **数据流已验**：`render_lines:142 hint「数字 移动」`(A 文案) ↔ `handle_key:178 数字分支→:192 _highlight=n-1→单选:204 落 _selected→:206 _advance_or_submit→:369 _q_idx+=1（前进）`(B 语义);两处独立生成、无交叉校验,分叉点即 :142(A) vs :204-206(B),**无拦截**。

### D24　回扫显示重置——回退已答题时 ❯ 光标跳回默认 option（选择未丢,显示层丢高亮）

- **现象**（Test-Eng）：光标导航回退到已答题时,高亮"重置到默认 option",用户会慌"答案没了"。
- **机读真相**：`_goto_question`(:388-394) `self._highlight = 0`(:392) **无条件重置**——回退已答题时 ❯ 光标停在 option 0,而该题已选项（`_selected` 保留,:390-394 全程未读它)在 render_lines 里仍以绿色标出(:113/121 `selected` 判据)但**无 ❯ 光标**。即**选择本身没丢,丢的是"高亮位置指向已选项"**。
- **数据流已验**：`handle_key:219-226 ←→/Tab→_goto_question(idx)→:392 _highlight=0(硬置)→render_lines:112 focused=(i==_highlight) → ❯ 停 option 0`;`_selected[idx]` 在 _goto_question 全程未被读取,高亮重置与已选状态无关联,**无拦截**。

### 两异常耦合（D23+D24 叠加致用户彻底懵）

D23（数字直选"选完跳走下一题"）→ 用户想回去确认 → D24（回退却看不到已选项在哪,❯ 在默认位）= **选了看不见 + 跳走找不回**。修好 D23（知道会跳+文案说清）+ D24（回去看得到已选）方成完整闭环。

### 修法方向（Design 2026-07-18 ①UX 裁定定稿 + team-lead D23-b/D24 裁;Design 亲核 ask_user_view.py 全链)

**Design 亲核地基**：代码已是 B（:200-206 单选数字直选落答+advance）;**单选 enter(:330→:339) 与数字(:206) 行为完全一致——都落答+前进**（都走 :367 _advance_or_submit）;hint(:142)+注释停 A 旧叙事、与代码方向相反。A/B 混用坐实。

- **D23-a hint/注释对齐 B 语义**（必改,纯文案,我域;Design 精确文案锁定结构、我落字可微调)：
  - hint(:142) `"↑↓/数字 移动 · "` → `"↑↓ 移动 · "`（数字移出"移动"）
  - 单选段：`("数字/enter 选定并提交 · " if last_q else "数字/enter 选定并进下题 · ")`——enter 与数字**并列**（两者都落答+前进）,"选定并进"表前进是选定一部分（强反馈"选上了"、非意外跳走）;末题 last_q(:141) 说"提交"、非末题说"进下题"。
  - 多选段：`"数字/space 勾选 · " + ("enter 提交 · " if last_q else "enter 下一题 · ")`——**保留 enter**（现状 :144 有,勾完必 enter 走,不可丢）。
  - 单题 total==1：无"进下题/下一题",单选「数字/enter 选定并提交」/多选「数字/space 勾选 · enter 提交」(按 total 适配,单题说"进下题"不准）。
  - **第二处注释债（Design 亲核加码,我原漏)**：不只 :138-140 注释 + :142 hint,还有 :253-254 `_has_uncommitted_selection` 注释（「数字/↑↓ 只动高亮，enter 才落答」）+ :284 `_guard_switch` warn 文案（「enter 落答后再切」）全停 A 叙事,一并对齐 B（B 下纯移动只剩 ↑↓、数字已落答)。:253-254 改「↑↓ 只动高亮，数字/enter(单选)/space(多选) 才落答」;:284 留 enter 但别暗示只有 enter 能落答。**纯注释/文案,不改守卫逻辑**（_touched 且 _selected 空告警在 B 下仍成立=↑↓ 动高亮没落答）。
- **D23-b 前进 UX**（team-lead+Design 同裁保留;**硬绑定 D24 同批**)：数字直选"落答+前进"**保留**（B 核心机制 :206/:339,治 run15/17 丢答=强反馈"选上了")。**配套不变量:前进（强反馈治丢答)必须配 D24 回扫（可复核治不可退回)同批上——单上前进不上 D24 = run15/17 变体复发**（落答跳走但回退看不到已选、"丢感"回归)。D24 是 D23-b 前提,两者不可拆。闭环护栏佐证:Tab 切题 _selected 按题保留(:390)+uncommitted guard(:281/:331)+D24 回扫=完整不丢答。
- **D24 回扫显已选**（纯显示层,我域自决,team-lead+Design 认收;D23-b 配套前提,同批上)：`_goto_question`(:392) **条件化**——已答题(_selected 非空)→ `_highlight`=已选项 index;**未答题→保持 0**（无已选项可显,别无脑显）。对比 :370 前进新题高亮 0 合理（新题从头),:392 切题回退才需显已选。抽 `_highlight_for(idx)` 助手（已选→其 index / Other 选中→len(options) / 未选→0）。
- **四关**：收口批同窗 #27 第⑦项（zhaiyq 批后开工令),Theory+Design 双评审（Design 随收口批终审:对齐 B 事实+多选保 enter+末题区分+第二处注释债清+D23-b 前进 D24 配套同批)→leader redline(纯渲染豁免)+pytest+commit;补守门测试(数字直选落答+前进/回退已答题 _highlight 落已选/未答题 _highlight=0)。
- **关联记忆**：`[[tui-multiquestion-panel-key-semantics]]`（run15/17 数字只高亮丢答)的 hint 对齐**收尾**——F-TUI-1(B) 治行为、D23 补 hint/注释让 B 治法完整闭环。

## 13.3 D11 Ctrl-C 语义 + D7 fork 零产物卡片态复验（2026-07-19 team-lead 派静态走查,回 Test-Eng 入表）

Py-Eng commit 归属核出两件,我做**静态代码走查**(未真按 Ctrl-C/未上机,活体项标"搭下批面板自然验")。

### D11 Ctrl-C 语义(ask 挂起态)——低风险
- **Ctrl-C 非 SIGINT**:ink raw mode(app.py:176 `set_raw_mode(True)`→termio:53 `tty.setraw` 关 ISIG)→ Ctrl-C=字节 0x03,不产生 SIGINT;仅注册 SIGWINCH(app.py:192)无 SIGINT handler。
- **ask 挂起态落点**:_handle_key(ist_app:976)顺序——:998 ask 面板拦截**在** :1021 ctrl+c 主处理**之前**。挂起态 Ctrl-C→:998 `_ask_user.handle_key`→无 ctrl+c 分支→ask_user_view:243 `return True` 吞掉→**无效果**。中止通路=ESC(ask_user_view:213,已证在)。
- **PTY/checkpoint**:挂起态 Ctrl-C 被吞无副作用→不撕不脏;退出路径 finally cancel_all_pending(ist_app:729-735)让挂起问询干净收尾(引擎无答案=自动挂起)→checkpoint 不脏。:727 KeyboardInterrupt except 兜底(raw mode 常态不触发)。
- **数据流已验**:Ctrl-C→[app.py:176 raw ISIG off]→字节→[parse_keypress ctrl+c]→[_handle_key:998 ask 拦截→ask_user_view:243 吞],全链无 SIGINT 分支/无 checkpoint 中断点。
- **活体验证点**(搭下批自然验,别真按):挂起态 Ctrl-C 应无反应;非 ask 态双击退出走干净 teardown。

### D7 fork 零产物卡片态——卡片层已修但判据窄 + #27 计数交互
- **卡片层已有 P1-10 修**(_render_fork_card ist_app:528-534):`compile-worker ∧ artifact_fresh is False ∧ ¬tail_status`→黄⚠「完成·无产出」不显✓(实弹 035493/035570)。
- **残留漏洞 A(卡片层判据窄)**:① artifact_fresh is False 严格,`None`(无判据/旧事件)不触发→零产物仍✓;② 限 compile-worker,非 worker fork(attributor/dyn-*)零产物→显✓。
- **⚠残留漏洞 B(#27 计数交互,自曝)**:`_count_fork_cards_by_status`(ist_app:383)计 status in(ok,error)→done_n,**白跑 fork status 仍"ok"**(reducer:617,卡片只显示降级⚠、status 字段没改)→计入 #27 编写期 bar done_n。**非明确 bug 是判据选择**——done_n 定义"编写孔跑完数不管成败"(含 error 同理),白跑计入自洽;若 bar 语义要"有效产出数"则该剔。卡片层降级 vs 计数层不降级的一致性**交 Design 裁 bar 语义**。
- **依据字段**:status(reducer:617)+artifact_fresh(:626)+tail_status(:625,均 fork_end 事件字段)。
- **修法方向**:卡片层 silent_run 判据放宽(artifact_fresh None 保守/覆盖非 worker)需 Design 定 artifact_fresh 语义;计数层是否剔白跑需 Design 裁。均活体搭下批自然验。
- **Design 终裁(2026-07-19)**:**bar 维持「跑完数」零改动**——四判据:①双轴不混(bar=进度维/卡片=质量维)②单调性(剔白跑会回退)③编写期可知(有效产出需质量判定,barrier 下不可靠)④与 #27 done_n 定义一致。**残留 B 不改,#27 计数定义站住**。**但硬配套前提=残留 A 必须补**:bar 不管质量的正当性 key on「白跑在卡片⚠可见」,卡片判据窄→白跑落**两轴缝隙**(bar 说跑完、卡片没⚠)。**残留 A 卡片⚠补全入后批池新四关件**(Design 定规格:真白跑=新 fork 跑完零有效产物→补⚠;**向后兼容 None**=旧事件无 artifact_fresh 字段/#27 有意不判→**不误标**,A2 防误杀)。现零动作,待后批池派工。配套不变量入册:**白跑必在卡片⚠可见**(否则两轴缝隙),是 bar 零改动的前提。

## 13. 修复轮方案清单（2026-07-18 批 4 停后开启,Design 牵头总清单;本节=TUI 域施工图,等开工令动码）

标注：【纯渲染】我域独立可做｜【跨域】需引擎/Py-Eng 配合｜证据引用报告章节。全部走四关（Theory+Design 双评审→leader redline+pytest+commit）。

### ① 面板交互族

| # | 项 | 现状/证据 | 修法方向 | 风险 | 归属 |
|---|---|---|---|---|---|
| A1 | o 输入态可见提示 | Test-Eng 卡壳(§11.1):「o 自定义」未说清须按 o 才放行文本输入 | 提示语「o 输入自定义文本」+ 进 other 态面板显「正在输入·enter 提交·esc 取消」 | 低(文案+状态行) | 【纯渲染】ask_user_view |
| A2 | esc 高危守卫 | 非 other 态 esc 二次确认 cancel 整面板(ask_user_view.py:184),大面板误触全丢 | 强化确认(显式二次)或 esc 仅明确焦点生效——需 Design 定交互语义,勿破既有防呆 | 中(交互语义) | 【跨域】+Design |
| A3 | 选项 label 截断/短语化 | 长 label+description 撑爆行(如「我给别的等价方案」+长 desc) | label 短语化(引擎 questions.py 出短 label)+渲染 desc 折行 | 中 | 【跨域】label 在引擎侧 |
| A4 | 超高面板空白行 | P1-12:9 题 gather 面板 collapse 残留题面+9 空行(viewport 溢出) | collapse 强制 render_full/重置滚动锚,或限面板高度(内嵌滚动/分页) | 中(碰布局/滚动,需回归) | 【纯渲染】ink layout |
| A5 | 全局框串旧文 | Test-Eng 实证全局 PromptInput 残留 ongkl…旧文 | ask 面板 begin 时清全局框,或 other 态出口确保清 | 低 | 【纯渲染】ist_app |
| A6 | 多题提交保真 | 末题 enter 触发 _submit 收集全部(ask_user_view.py:390 已读确认逐题落+末题整体提交);风险=未答题空答案 | 已有 _unanswered_count 告警防呆,评估是否够/强化 | 低(已有防呆) | 【纯渲染】ask_user_view |
| A7 | 数字键语义（D23,§13.2) | hint「数字 移动」(:142)与数字直选落答+前进(:204-206)矛盾;注释债三处(:138-140/:253-254/:284)停 A 叙事（A/B 修法混用遗留) | hint 拆单/多选对齐 B(单选「数字/enter 选定并进下题/提交」·多选保 enter·末题区分·单题 total==1 适配)+第二处注释债(:253-254/:284)清,Design 定稿;保留前进(硬绑 D24 同批) | 低(纯文案) | 【纯渲染】ask_user_view |
| A8 | 回扫光标重置（D24,§13.2) | _goto_question:392 _highlight=0 回扫已答题丢已选高亮(选择在光标不指) | _highlight_for(idx) 条件化(已答→已选 index/未答→0)显已选,我域自决;D23-b 前进配套前提、同批上 | 低(显示层) | 【纯渲染】ask_user_view |

### ② footer 语义族

| # | 项 | 现状/证据 | 修法方向 | 风险 | 归属 |
|---|---|---|---|---|---|
| B1 | 编写期滞后提示 | P2-11:编写期 counts 冻 pending(Theory 判据:counts 数据源不动) | 渲染侧加提示语「编写期产出将在合并时结算」(不碰 INV-7) | 低(纯文案) | 【纯渲染】ist_app |
| B2 | 相位标签滞后 | 相位跳变依赖 tick(P1-1 已修 prep→编写),其他滞后待定位 | 具体定位后按点修 | 低 | 【纯渲染】待定位 |
| B3 | 进度条跨轮口径倒退 | 进度条 done/total 跨轮可能倒退(重编轮 total 变) | 定位口径,统一跨轮基准 | 中 | 【跨域】可能 tick 侧 |
| B4 | 终验心跳缺失 | 终验(整卷复验)阶段可能无 progress 心跳 | 补终验心跳(引擎发 progress) | 中 | 【跨域】引擎发射 |
| B5 | 收敛态可读性 | footer 只显轮次+counts,无「第 M 轮/剩 N/趋势」 | footer 增收敛信息(第几轮/剩几个/趋势箭头) | 低-中 | 【纯渲染】footer 增强 |

### ③ 失败卡英文→中文人话映射（【纯渲染】ist_app _render_fork_card error 分支）

现状:`fork returned no text output` 等英文黑话直透卡片(语言分层违例)。修法:中文人话映射表+去向一句话(如「未产出结果——引擎已安排重写」),配 Design 条款。

### ④ ask 题面拼装层英文透传系统性修（【跨域】Py-Eng 主导,我配合渲染侧）

现状:题面/error/黑话英文透传系统性。修法:配合 Py-Eng 题面拼装层改造(_display_clean 已开头),渲染侧同步。

---

## 0.1 团队纪律（leader 全队令，2026-07-17，记入本报告）

用户批评「同一问题各 mate 结论口径不一」后立的全队纪律，本报告全节遵循：

1. **结论必带证据边界声明**：任何定性=「基于 X 证据确认 Y，Z 面未核」。禁部分证据下全称结论。
2. **冲突先对证据面收敛**：与队友结论冲突,先互相对证据面收敛再统一报 leader（不各报各的）。
3. **机读账优先**：机读账（events.jsonl/facts.jsonl/ask_user_answers.jsonl）> 屏幕观察 > 记忆。
4. **本报告的正面样板**（leader 点名）：§13 P0-1 取证先声明「屏幕帧被滚过→改用 events.jsonl 数据源，屏幕帧未核」再给结论;§778012（发 leader）先声明「面板挂出时刻盘上无记录→间隔不可测」再给三选一;§12 P1-3 归因「◌ worker 非本次修复,从证据剔除」自纠。以上口径保持。

---

### P1-12（User 亲见,批 4）：ask 超高 gather 面板答后空白行残留（存量,非本窗口）

- **现象**（surface:20 两帧持续）：9 题 gather 大面板答完后,transcript 顶部残留某题完整题面（panel.render_lines 格式,非"● 已回答"摘要）+ **9 行连续空行**,才接正常 ◆ 裁决行。
- **分层排除**：①组件层正确——`_finish_ask_user`(ist_app.py:2015) `ask_user_panel.clear()`=clear_children+height=0;②渲染核正确且**本窗口零改动**——log_update.py 基于 Screen diff 忠实渲染,git 确认 log_update/screen/render 在 69f8f133..d40d2203 零改动（#21 只碰 components+dom.py）;③根因疑似——9 题面板 render_lines ~60-90 行 **>> 终端可视 43 行**,撑爆 viewport,collapse 后布局/滚动锚未回弹,Screen buffer 残留。
- **判定**：**存量缺陷,非本窗口引入**（渲染核+布局零改动）。
- **⚠ 自纠（2026-07-18,纪律教训）**：初判「9 题 gather 面板 render_lines 撑 60-90 行 >> viewport」**不成立**——机读 `ask_user_view.render_lines`(line 83 `q=self._cur_question()`) 证实**只渲当前题**，非多题堆叠。教训:**先读 render_lines 确认渲染范围再推断,勿凭"9 题"直觉推"堆叠"**。P1-12 真根因(题面漏 transcript 顶+9 空行来源)**未定位**,押后到 yzg 重跑 gather 面板实弹重现(leader 批 F-TUI-4 押后)。
- **证据边界**：确认现象两帧持续/组件 clear 正确/渲染核 diff 零改动/题面 panel 格式;**未核面**=未逐行读 compute_layout+滚动管理确认确切代码位、批 3 无同现象是推断非实测历史帧。
- **修法方向（收口批,面板交互族合并）**：超高面板 collapse 强制 render_full/重置滚动锚,或限制 gather 面板高度（内嵌滚动/分页）避免撑爆 viewport。

### 批 4 正向实弹验证点（同帧确认）

- **P1-4 max 尾挂 ✅ 首次实弹验到**：busy 行「✶ Pondering…(3h14m · … · ◌ worker 87s 无新事件 · 最大深度…)」——无相位等待形态尾挂「最大深度思考中」（行宽截断成「最大深度…」）,正是 P1-4 摆脱主相位依赖的唯一场景（此前从未验到,靠单测保证,现实弹坐实）。
- **P2-11 barrier 跳真值 ✅**：footer「轮次7 归因 40/53 · 产出3 编写中2 欠定2 通过37 失败9」——非全 pending,counts 已跳真值,坐实"编写期冻结→barrier 后跳"（P2-11 未核面闭合）。

---

## 11.1 多题 ask 面板 Other 文本输入权威按键序列（批 4 现场盲区,读源码答）

历史锚 `tui-multiquestion-panel-key-semantics`（数字只高亮/每题必 enter/Tab 不落答）的**文本输入态新盲区**（批 4 Test-Eng 实卡：4 题末题要给自定义方案文本,send 的文本进全局消息框而非面板,enter 未 commit→facts 全 ask_shown 无 decision→re-ask）。

**根因（机制）**：ask 面板活跃且**非** Other 输入态时,面板 `handle_key` **吞掉所有非导航按键**（`ask_user_view.py:214` `return True`,含文本字符+ctrl+u）；**唯一放行文本到 PromptInput 的开关是按 `o`**（line 153 `if self._other_input: return False`）。没按 o → 文本被吞/卡全局框 → enter 走全局消息 submit（发 agent）而非面板 `submit_other_text`（`ist_app.py:909-914`）。

**option vs Other 澄清**：选项「我给别的等价方案」是**普通 label**（选它落 token,不带文本）;要给具体方案**文本**必须用 **Other 输入**（按 o）——questions.py description「在自定义输入里给出」即指此。

**权威序列**：
- **给文本**：导航到该题 → `o`（进 Other 态,`ask_user_view.py:198`）→（有残留则 `ctrl+u` 清,`prompt_input.py:151`,须先按 o 才生效）→ 打字 → `enter`（`submit_other_text` 落该题→前进/提交）。
- **清全局框残留**：`o`→`ctrl+u`（非 other 态直接 ctrl+u 被面板吞,无效）。
- **⚠ 禁忌**：非 other 态按 `esc` → `_guard_cancel`（`ask_user_view.py:184`）一次告警、**二次 esc cancel 整个面板**（全丢）；只有 other 态内 esc 安全（`cancel_other_input`,仅退回选项,`ist_app.py:915-918`）。

一句话：**给文本 = 先 `o` 再打字再 `enter`；清残留 = `o`+`ctrl+u`；选项态永远别按 esc**。（收口批评估:「o 自定义」提示语是否应改「o 输入自定义文本」+ option「我给别的等价方案」是否该并入 Other 提示,减歧义——记后续池。）

---

## 12. 批 3 实弹验收记录（PID 83994，yzg 批，已确认含全部 TUI 修复代码）

**代码版本铁证**：批 3 的 `fork_end` 事件含 P1-10 新增的 `tail_status`/`artifact_fresh` 字段 → 批 3 跑的是含本报告全部改动的实弹环境（此前批 1/2 为旧代码）。以下为有效实弹验证：

| 项 | 结果 | 证据 |
|---|---|---|
| P1-1 相位不卡「准备」 | ✅ | footer 相位 prep→编写正确跳变（批 1/2 曾整个编写期卡「准备」）；Test-Eng 独立确认 |
| P1-3/P1-2 深度思考卡死 | ✅ 未复现 | busy 行 18m57s/21m29s 两帧均等待形态（↑↓双向、无「深度思考中」）；对比批 1/2 的「深度思考中(+75)」四帧冻结。**机制归因**：卡死消失更可能是 Py-Eng P1-2 堵泄漏源（主相位根本不进 thinking）主导，本报告 P1-3 相位心跳过期是**兜底防线**（泄漏源堵干净则不触发，正确性靠单测 `test_footer_stale_phase_falls_back_to_waiting` 保证）。注:Test-Eng 观察到的「◌ worker Ns 无新事件」是 footer **既有**静默指示器（`_fork_wait`），非 P1-3，不计入本项证据 |
| P2-11 counts 延迟更新 | ✅ 闭环 | 亲见跳变：编写期「产出0 编写中26」→ barrier 后「产出21 编写中0 欠定5」（21+5=26）；跳变值 21≠18 磁盘数符合预测（needs_decision 不计 produced） |
| P1-10 白跑判据零误伤 | ✅ | 本批 25 fork 全 ✓ 无误报 ⚠（0 白跑形态） |
| counts 九桶投影 | ✅ | 21+0+5+0+0=26=total，无残差桶泄漏 |
| progress 卡（上机心跳） | ✅ | `⠴ ▸ 上机 102s/945s · 环境 10.4.127.103 · 21 case · …/test_xlsx.py`——spinner/阶段/计时/环境/case数/当前case中段省略全对 |

**收尾阶段补验**（events.jsonl，屏幕帧被上机日志滚过）：
- **P0-1 G4 echo 数据源 ✅**：engine_summary 事件发射，`decisions` 携 4+ 条 G4 echo（668000/668044/668015/668030「改过程」→「改过程」）、outcome=delivered_with_labels 21/26、labels 5、report_mismatch=False——reducer 透传+卡片渲染链有数据可显（P0-1 修复数据链验证通过；这批 understood=answer 因无截断/兜底误判，属正常）。
- **P1-11 新发现（见下）**：closing engine_tick counts 全 0/total 0 → footer 收尾行显「已收尾 0/0 产出0 通过0」。

**待编译推进的验证项**（顺延批 4）：max 尾挂（需重编轮 effort=max）、ask 新文案+守卫+TAB 题面+三态（欠定案 gather 呈报时抓）。

---

### P1-11　收尾态 footer 底行显「已收尾 0/0 产出0 通过0」（每批收尾必现,根因引擎侧,实弹）

- **现象**（批 3 yzg 收尾帧）：主 transcript 收口报告明示「21 通过入交付卷」，但同屏 footer 底行 `编译 yzg · 轮次3 已收尾 ░░░ 0/0 · 产出0 编写中0 欠定0 通过0 失败0`——显示与事实矛盾，用户易读成「白干了」。
- **根因（引擎侧删除顺序,代码级坐实）**：closing 节点（nodes.py）——line 2841-2843 `_cleanup_temp` 先 `(mdir/"manifest.json").unlink()`；line 2889 `emit_summary` 用清理**前**缓存的 `vw`（line 2548 算的 26 cases）→ 显 21/26 **正常**；line 2902 `emit_tick(state,"closing",fs)` 内部 `view(state,fs)→batch_view(fs, manifest(state))`，而 `batch_view` 的 cases 全集来自 manifest（views.py:140 `aids=[c.autoid for c in manifest.cases]`）——**manifest 已被删** → `manifest(state)` 兜底返回 `{}` → aids=[] → cases={} → counts 全 0、total 0。
- **渲染层无错**：`_render_engine_bottom_line` 忠实显示 counts（全 0）——数据源错，非渲染错。
- **每批必现**：删 manifest + emit_tick 在其后是 closing 固定序,非 yzg 特有（批 1/2 收尾帧未抓到但代码路径同一）。
- **修法方向（引擎侧,归引擎队）**：①最简=`emit_tick(closing)` 移到 `_cleanup_temp` 删 manifest **之前**（line 2902 提到 2841 前）;或②closing 收尾 tick 复用 emit_summary 同源数值（ok/total→passed/total,收尾语义就是终值）而非重新 view。渲染域无需改。
- **严重度 P1**：显示与事实矛盾且每批必现,但有替代信息源（主 transcript 收口报告 21 通过 + engine_summary 收口卡终值）——非致命,用户可从收口报告得真值。

---

### P2-11　footer counts 编写期冻结 produced=0（Test-Eng 批 3 实弹;定性=延迟更新非回归,改进归引擎队）

- **现象**（Test-Eng 批 3 PID 83994）：footer 相位已正确跳「编写」（P1-1 修复生效✅），但 counts 持续「产出0 编写中26 通过0」——同时 22 fork 卡已 ✓ 完成、18 case.xlsx 已落盘。
- **实证**（83994.events.jsonl）：engine_tick 序列 #0 prep(produced=0) → #1-#25 author **25 条全部 produced=0/编写中26**（barrier 前无一条真值）。
- **根因（V8 架构,非回归）**：author 节点（nodes.py:411-460）——fork 逐个结算只写内存 `results[aid]`,**authored 事实在全部 fork 跑完后批量 append（line 457）**;编写期每 fork 的 `emit_tick(state,"author",fs)`（line 438,P1-1 补的）用**节点开始的 fs 快照**（不含未 append 的 authored）→ counts 现算 produced 恒 0。barrier 后 `fs2=load_facts`（line 458）→ `emit_tick(fs2)`（line 459）→ counts 跳真值。**延迟更新,非丢失非回归**（barrier 后必跳变）。
- **卡片 vs footer 不一致的本质**：V8 账实分离（INV-7）——fork 写 case.xlsx（磁盘）与引擎 append authored（事实流）是两个时刻;卡片走 fork_end 事件（实时）、footer counts 走 facts 视图（滞后）,两层不同数据源。
- **P1-1 边界（如实）**：P1-1 目标=编写期相位不卡「准备」（达成✅）;counts 实时化**不在其范围**。
- **裁决 v1（leader 2026-07-17 上午）：维持现状,标「已知行为」**。理由:①P1-1 已修卡「准备」;②fork 卡片是实时进度源;③视图领先事实流触 INV-7。

- **批 4 精确化（PID 13032，53 案，机读揭示完整形态）**:此前只看 produced,批 4 实证**整个 counts 冻结**——14 条 author tick 完整 counts 全是 `{pending:N}`（produced/failed/欠定/passed 全 0、pending 恒 N）。根因更彻底:引擎**无 dispatched 事实**（grep nodes.py/views.py 零 append,案生命周期 pending→(authored/escalated/needs_decision) 无中间态）+ author 编写期零 append（barrier 后 nodes.py:457 一次性）→ 每条 tick 的 fs 快照都是 prep 初始态「N 全 pending」→ 显示恒定。**机读排除「tick 断流/reducer 未消费」**（14 tick 在发 21:27-21:35、reducer engine_tick 消费分支本窗口 diff 零改动）——是数据源恒定非通道故障。**自纠**:批 3 报「编写中=dispatched」表述不准,机读实为 pending（引擎无 dispatched 事实）,批 3/4 皆 pending。

- **裁决 v2（leader 2026-07-17 傍晚）：重开评估,押收口批**。新证据=User 体感实证（两帧不动+完成卡矛盾会让真实用户以为卡死),构成 v1「维持现状」时没有的证据。**收口批 TUI+Design 联合出体验方案选项,走双评审**。leader 给三方向不预设:①tick 快照并入 fork_end 结算数;②进度条按 fork 完成数填充;③仅加「编写期产出计数将在合并时结算」提示语。#27 待 Py-Eng 收敛确认后结案。
