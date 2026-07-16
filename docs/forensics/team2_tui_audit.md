# TUI 渲染 × V8 引擎 显示正确性审计（team2）

**日期**：2026-07-16　**审计范围**：`main/ist_core/ink/**` + `main/ist_core/tui/**`（渲染层，独占写权限）
**活体样本**：zhaiyq 编译 PID 29906（`runtime/logs/compile_evidence.29906.{events.jsonl,live.log}`，只读）
**方法**：活体事件流统计 + 渲染层源码核对 + 子 agent 枚举 V8 发射侧 → 交叉验证

---

## 0. 结论摘要

渲染层**整体健壮**：V8 实际发射的 7 种 fastlog 事件渲染层全有处理；卡片状态入 snapshot、ctrl+o/t 重放一致；footer 聚合行阶段名对当前实发 phase 全覆盖。

发现并**已在渲染层修复** 4 项：① 7 个 V8 工具掉裸 snake_case（映射表补全）② `diagnose` phase 缺中文映射（补全）③ footer 残差桶兜底（broken 案静默消失的渲染侧防线）④ ask 面板空 Other 提交防呆（今日 532862 实弹缺陷）。

发现并**记报告交事件侧** 1 项（不归本队写权限）：`emit_tick` 投影把 V8 内部 13 态折回 V6 九键时**丢了 broken 三态**，footer 桶和 < total、案凭空消失（活体 round1 实测漏 2）。

零回归：改动均为纯增量（dict 补项 / 条件式残差 / 空文本守卫），全量 `tests/tui/`+`tests/ink/` 341 passed，新增 5 测试全绿，`pytest --collect-only` 2036 收集无 ImportError。

---

## 1. 事件 × 渲染矩阵（任务点 1）

**两套事件系统**（易混，先厘清）：`events.py`（typed EventBus）与 fastlog `.events.jsonl`（`skills/loader.py::_fork_emit_event` 写）互不相干。**V8 卡片/footer 全走 fastlog**；CLAUDE.md 列的事件名属 fastlog 这套。V8 在 typed 通道只发 `evidence_added`（承载人读进度文本）。

**活体样本 V8 实发 6 种**（+ closing 的 `engine_summary` 本轮未到）：

| 事件 | 活体次数 | 渲染层处理点 | 处理正确性 |
|---|---|---|---|
| `tool` | 1552 | `reducer.py:598` → fork 卡 current_tool | ✅ |
| `tool_result` | 1552 | `reducer.py:606` → fork 卡 recent 环 | ✅ |
| `fork_start` | 92 | `reducer.py:588` → 建 fork 卡（brief_head/effort） | ✅ |
| `fork_end` | 92 | `reducer.py:614` → 卡定格（calls/时长/↑↓token） | ✅ |
| `progress` | 75 | `reducer.py:654` → progress 卡（上机心跳） | ✅ |
| `engine_tick` | 13 | `reducer.py:632` → engine 卡 → footer 底行 | ⚠ 见 §3（broken 漏计，事件侧） |
| `engine_summary` | 0（未到 closing） | `reducer.py:642` → 收口卡 | ✅（代码在，逻辑对） |

**孤儿/兜底**：
- `run_meta`：**V8 不发**（活体 0 条，全仓无生产者）。`reducer.py:625` 有消费分支 = V6 遗留死码，无害（engine 卡由首个 `engine_tick` 惰性建，footer 底行只用 run/round/phase/counts/total，不依赖 run_meta 的 mindmap/ledger 字段）。
- 未知事件兜底：`_on_fork_cards` 逐条 `if ev==...`，未知 event 静默跳过（不建卡、不崩）；坏 JSON 行 `reducer` 侧 `continue`（`ist_app.py:690`）。**兜底安全**。

---

## 2. 工具显示名映射核对表（任务点 2）

映射表 `_TOOL_SHORT_NAMES`（`ist_app.py:42`），fork 卡 current_tool 行（`ist_app.py:427`）与主 transcript tool_use（`ist_app.py:1761`）共用；fallback = 返回裸名。

**活体样本掉裸名的工具（本队已修）**：

| 工具真名 | 活体次数 | 归属 fork | 修前显示 | 修后显示 |
|---|---|---|---|---|
| `dev_help` | 36 | worker | `dev_help(...)` | `Help(...)` |
| `kb_intent_search` | 18 | attributor | 裸名 | `IntentSearch` |
| `submit_ask_panel` | 9 | attributor | 裸名（+首参长路径） | `AskPanel(…autoid)` |
| `submit_behavior_fact` | 8 | attributor | 裸名 | `BehaviorFact(…autoid)` |
| `compile_report_underdetermined` | 1 | worker | 裸名 | `Underdet(…autoid)` |

**另补 2 个已注册但本轮未出现的设备工具**（防御性）：`dev_init_device→InitDevice`、`compile_user_decision→UserDecision`。

`submit_ask_panel/submit_behavior_fact/compile_report_underdetermined` 同时进 `_AUTOID_ARG_TOOLS`（`ist_app.py:134`），参数摘要取 `…autoid 尾6位`，避免 submit_ask_panel 把首参 `last_run_path` 长路径当摘要显示。

**任务点名工具核对**：`compile_engine_run`→EngineRun ✅、`submit_attribution`→Attribution ✅、`compile_check_verifiability`→Verifiability ✅、`submit_ask_panel`→**修前裸名、已补 AskPanel**。

**未映射但保留裸名（有意）**：`glob`/`grep`（活体 8/2 次）——非 fork 白名单工具（worker 有 `fs_glob`/`fs_grep`），是 LLM 偶发够原生名，裸小写本身可读且是弱信号，不映射以免把非常规调用伪装成正常操作。**记：worker 偶发反射原生 glob/grep，属 worker prompt 面（非本队）**。

**实证（活体 live.log）**：
```
↳ engine:516576: dev_help(sdns pool cname name)      ← 修前裸名
  ⤷ dev_help → mode: config
```

---

## 3. footer 聚合行核对（任务点 3）

`_render_engine_bottom_line`（`ist_app.py:278`）→ `footer.set_engine_line`。

**九个 ledger 状态归属**（澄清语义）：footer 屏上显 **5 个数字桶**（产出/编写中/欠定/通过/失败），"九态全归属"指 engine_tick 的 **9 个 count 键**被折进这 5 桶：

| 显示桶 | = count 键 |
|---|---|
| 产出 | produced |
| 通过 | passed |
| 编写中 | pending + dispatched + failed_active |
| 欠定 | pending_decision + awaiting_user |
| 失败 | failed_terminal + escalated |

任务转述的「挂起→失败桶（suspended 在事件侧并入 failed_terminal）、上报→失败桶（escalated）、pending→编写中桶」，**均有归属**。

### ⚠ broken 第三态漏计（事件侧缺陷，已记报告 / 渲染层已加兜底）

`emit_tick`（`compile_engine_v8/_shared.py:271-281`）把 V8 内部 13 态翻译回 V6 九键时，**`broken/broken_errored/broken_blocked` 未进任何键**。有 broken 案时 9 键之和 < total，案在 footer 凭空消失。

**活体铁证**（29906 round1）：
```
phase=reconcile round=1 total=53 桶和=51  <<< 漏计=2
phase=attribute  round=1 total=53 桶和=51  <<< 漏计=2
（其余轮 broken=0 时桶和==total,正常）
```

- **根因在事件侧**（`_shared.py::emit_tick`，非本队写权限）→ **记报告交引擎侧**：应把 broken 三态并入某桶（建议并入「失败/失败桶」或新增独立键）。
- **渲染层已加防线**（本队）：`_render_engine_bottom_line` 加条件式残差桶——`total − 5桶之和 > 0` 时显「其他N」,保证可见计数恒等于 total,案不静默消失。事件侧补全后残差自然归 0、该桶消失,不冲突。

**阶段名映射**（`_ENGINE_PHASE_CN`，`ist_app.py:266`）：`emit_tick` 实际只发 5 种 phase（`prep/author/reconcile/attribute/closing`，5 处调用点 `nodes.py:152/445/1132/1481/2554`），**全部有中文映射**，footer 当前无实际漏映射。`run`（上机）不发 tick、经独立 `progress` 卡（`phase="上机"` 硬编码）显示。补记：11 节点里 `diagnose` 此前缺映射（不发 tick 故无害）——**已补 `diagnose→诊断`**，防将来给 diagnose 加 tick 时显裸英文。

**「最大深度思考中」尾挂**：2026-07-15 已从引擎底行**移到 thinking 焦点行**（`footer.py:304`，`_state` 判 `_max_thinking ∧ _llm_phase=="thinking"`）。`ist_app.py` 侧 `_payloads_have_max_thinking`（判 running fork 卡 effort==max）→ `footer.set_max_thinking`。活体确认 `effort=max`×18 forks（首败升级在跑），逻辑正确。

---

## 4. ask 面板核对（任务点 4）

单题/多题（`(1/2)` 计数）、Other 自定义输入、echo 行（`→ text` 预览 + `result_summary` 已回答/已取消）——`ask_user_view.py` 逻辑完整，多题双向导航（←→/Tab）已选状态按题保留。

### 🔴 空 Other 提交防呆（今日 532862 实弹，已修）

**缺陷链**：高亮 Other→enter→提交**空文本** → `submit_other_text("")` 仍 `_selected={_OTHER_VALUE}`（选中空 Other）→ `_answer_text_for` 过滤空串 → 该题答案 `""` → 全空答案与 `cancel()` 的 `_deliver({})` **下游无法区分** → 引擎判「已取消」→ 案被自动挂起。

**已修**（`ask_user_view.py`，低风险交互改动）：`submit_other_text` 空文本（含纯空白 strip 后为空）时**不落选、留在输入态**，面板显黄字提示「⚠ 自定义输入不能为空——请输入内容,或按 esc 取消」；补真实内容后正常提交,esc 走 `cancel_other_input` 清提示退回选项。绝不产生空答案误判。

---

## 5. 卡片模式核对（任务点 5）

- **同 fork 原地更新**：`_upsert_card` 按 `fork:{fork_id}` uuid 覆盖合并，`skip_if_finished` 挡 fork_end 后迟到 tool（`reducer.py:667`）✅
- **spinner + 当前工具**：`_render_fork_card` running 态 `↳ {tool}({arg}) · N calls · 耗时`（`ist_app.py:427`），无新事件也走帧 tick ✅
- **完成摘要**：`✓ {name} — 完成 · N calls · 时长 · ↑↓token`（`ist_app.py:404`）✅
- **「第N次」写轮标记**：`brief_head` 直显（`ist_app.py:422`）；活体 `第1次×53/第2次×14/第3次×4` 正常 ✅
- **subset 轮行**：`合并[子集]/上机[subset]` 人话由**引擎 render.py** 产（`CTX_CN={subset:单独验证}`），流经 progress `detail`/summary labels，TUI 原样显示 ✅
- **IST_FORK_CARDS=0 回退**：`ist_app.py:657` `cards_mode` 判定，`=0` 走平铺 tail `.live.log` 原样 `·` 追加 transcript（`ist_app.py:715`），代码路径完整 ✅（读代码验，未重启进程）

---

## 6. 显示规范（任务点 6）

- **user-facing 全中文**：底行/卡片/ask 面板/提示均中文；新增映射的英文短名（Help/AskPanel 等）是**工具技术标识**（对齐既有 Emit/Probe/RunBatch 规约），非叙述文案，符合分层。`diagnose→诊断` 补齐后 11 节点无裸英文。
- **金额/token 格式**：`_format_token_count`（≥1k→XX.Xk）、`compute_cost_rmb`（¥N.4f）统一 ✅
- **截断规则**：长命令/路径走 `_middle_ellipsis`（路径感知,保首段+末两段）、命令 60 字符截断,一致 ✅

---

## 7. ctrl+o/ctrl+t 重放一致性（任务点 7，读代码核）

卡片状态**活在 snapshot 内**：`_snapshot_locked` 带 `fork_board_rev` + `fork_card_indices`（`reducer.py:181-182`），卡片是 `BLOCK_FORK_CARD` 系统消息进 `_messages`。`_replay_snapshot` 全量重放天然还原（每条 record 自含完整可见状态，覆盖合并，乱序/丢事件容忍）。`rev` 单调守卫丢弃迟到旧快照。**重放一致 ✅**（`tests/tui/test_ist_app_replay_snapshot.py` 覆盖，本次全绿）。

---

## 8. 修复清单

**渲染层已改（本队写权限内，纯增量）**：

| # | 文件 | 改动 | 风险 |
|---|---|---|---|
| 1 | `ink/components/ist_app.py` | `_TOOL_SHORT_NAMES` 补 7 工具（dev_help/kb_intent_search/submit_ask_panel/submit_behavior_fact/compile_report_underdetermined/dev_init_device/compile_user_decision） | 零（dict 补项） |
| 2 | `ink/components/ist_app.py` | `_ENGINE_PHASE_CN` 补 `diagnose→诊断` | 零（dict 补项） |
| 3 | `ink/components/ist_app.py` | `_AUTOID_ARG_TOOLS` 补 3 个 autoid 承载工具 | 零（frozenset 补项） |
| 4 | `ink/components/ist_app.py` | `_render_engine_bottom_line` 加条件式「其他N」残差桶 | 低（仅 residual>0 时显，正常轮不变） |
| 5 | `ink/components/ask_user_view.py` | `submit_other_text` 空文本防呆 + 面板提示行 | 低（交互，杜绝空答案误判） |

**记报告交事件侧（非本队写权限）**：

| 缺陷 | 位置 | 建议 |
|---|---|---|
| broken 三态未进 engine_tick 投影 → footer 漏计 | `compile_engine_v8/_shared.py:271-281` `emit_tick` | 把 `broken/broken_errored/broken_blocked` 并入某桶或新增独立键；渲染层「其他N」已兜底但根治在此 |
| worker 偶发反射原生 `glob`/`grep`（非 fs_ 前缀） | worker prompt / fork 白名单 | 观察项，非阻塞 |

**测试（新增 5，全绿）**：
- `test_tool_short_names_cover_v8_fork_tools`、`test_render_engine_bottom_line_residual_bucket`、`test_engine_phase_cn_covers_all_v8_nodes`（`tests/tui/test_fork_cards_render.py`）
- `test_session_other_empty_text_guard`、`test_session_other_whitespace_only_guard`（`tests/ist_core/test_ask_user.py`）

**回归验证**：`tests/tui/`+`tests/ink/` **341 passed**；`pytest --collect-only tests/` **2036 收集,无 ImportError**。

**视觉生效说明**：本队改动不热加载进在跑的 29906,视觉回归记为「重启后生效,待下次 run 验证」。
