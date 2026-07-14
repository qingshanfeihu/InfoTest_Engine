# InfoTest Engine TUI 渲染架构（ink 单核）

> 2026-07-06 重写：旧版描述「Textual 终端 + Ink 网页」双核——与现实相反且 Textual 已退役。
> 现实是 **ink 自研终端渲染器单核**：`infotest` 终端与 `infotest --server` Web Terminal
> 跑的是**同一份 ink 代码**（Web 端经 PTY 字节流转发给 xterm.js，见 `web_server.py`）。

## 分层

```
LangGraph(qa_node) ──_MainAgentProgressHandler(graph.py)──┐
compile_pipeline/_shared.emit(工具线程)───────────────────┤ bus.emit
fork 步骤(skills/loader.py)→ 文件 fastlog ─┐              │
                                           │              ▼
                        ist_app tailer(300ms tail)   EventBus(events.py)
                                           │              │
                                           └─ emit(fork_cards) ──▶ TuiSink(sink.py)
                                                                       │
                                                              MessageReducer(reducer.py)
                                                              锁内建快照+单调 rev
                                                                       │ MessageSnapshot
                                                              IstInkApp._on_snapshot
                                                              (ink/components/ist_app.py)
                                                                       │
                                                    ink 渲染核(ink/app.py: DOM+flex+screen diff)
```

- **`main/ist_core/tui/`＝数据层**：bridge（后台线程跑 graph）、streaming（astream_events→bus）、
  sink、reducer、message_model、slash_commands。没有活跃的 Textual App。
- **`main/ist_core/ink/`＝视图层**：`ink/app.py` 渲染主循环（16ms 节流、CJK 宽字符自愈、
  DEC 2026 原子包帧），`ink/components/ist_app.py` 业务 App（Transcript/Footer/PlanPanel/
  AskUserPanel/PromptInput）。
- **工具事件不走 astream_events**：`graph.py::_MainAgentProgressHandler`（BaseCallbackHandler）
  直接 emit tool_call/tool_result/thinking/usage 到 bus（`streaming.py` 的 _KIND_MAP 刻意
  不含 on_tool_*，因 agent.invoke 同步阻塞看不到内部工具事件）。
- **快照单源与 rev 守卫**：reducer 在锁内变更状态+构建不可变 `MessageSnapshot`（带单调
  `rev`），锁外投递；UI 丢弃 rev 更小的迟到快照（多线程 dispatch 下的乱序防重复渲染）。

## 子 agent（fork）卡片显示（2026-07-06，对标 opencode Task 卡）

fork 三条派发路径（invoke_skill-fork / compile_fanout / V6 引擎）全走
`skills/loader.py::execute_fork_skill`，步骤**双写**：

- `runtime/logs/compile_evidence.<pid>.live.log` — 人读行（`tail -f` 契约不变）；
- 同 stem `.events.jsonl` — 结构化事件：`fork_start / tool / tool_result / fork_end /
  run_meta / engine_tick / progress`。每条 record **自含该卡完整可见状态**（n_calls 累计、
  engine_tick 全量 counts）→ 消费端纯覆盖、乱序/丢事件容忍。

TUI 消费（`ist_app._start_evidence_tailer`，`IST_FORK_CARDS=1` 默认）：tailer 300ms tail
events.jsonl → 批量一条 `fork_cards` bus 事件 → reducer 把三类卡 upsert 成 snapshot 内的
`BLOCK_FORK_CARD` 消息（uuid=`fork:{fork_id}` / `engine:{run}` / `progress:{key}`，同 uuid
原地替换）→ UI 按 `fork_board_rev` 对已登记卡行 `update_message_at` 原地重渲：

```
⏺ EngineRun(dongkl)
  ◆ merge[full] 32 case → dongkl/case.xlsx          ← 里程碑(bus evidence_added,一次性追加)
  ⠹ ▸ 上机 223s/1440s · 32 case · smoke_test/…/test_xlsx.py   ← 心跳单行原地走秒(progress)
  ✓ worker·681841 — 完成 · 47 calls · 8m12s · ↑1.2M ↓52k      ← fork 完成定格
  ⠼ worker·593545 — sdns 案例编写
    ↳ Emit(…593545) · 12 calls · 3m                            ← 运行中:spinner+当前工具
……
ctrl+c abort · ctrl+d exit · / commands · ↑↓ history
 编译 dongkl · r1 上机 ███████████████░░░░░ 26/34 · 产出26 编写中7 欠定0 通过0 失败1
   ↑ 引擎聚合=footer 最底部常驻行(engine_tick 驱动,进度条+文字,2026-07-06 用户定稿)
```

关键设计（踩坑教训固化）：

- **卡片活在 snapshot 里**，不是 tailer 旁路 append 行——旧平铺 `·` 行不在 snapshot，
  ctrl+o（`_replay_snapshot`=clear+只重放 snap.messages）一按全部消失；卡片消息随重放
  天然还原。
- **一张卡=一条 transcript entry（值内嵌 `\n`）**：`TextNode.wrapped_rows` 按换行计高，
  卡片 2 行↔1 行不改变其他 entry 的 idx，`update_message_at` 就地改即可。
- **传输保留文件+tailer**（fork 线程不直发 bus）：8-16 worker 高频 emit 会在 app.lock/
  render 上排队拖慢 fork；文件解耦是 fastlog 既有设计动机。
- spinner 帧由 tailer tick 就地重渲（纯显示态不进 reducer）；第 9 张起的 running 卡收紧凑
  单行；running 且长时间无事件显示 `◌ … 无事件(可能已被看门狗放弃)` 兜底（fork_end 可能
  因看门狗放弃而不来）。
- 回退：`IST_FORK_CARDS=0` 整体回旧平铺；`IST_FORK_STEP_EMIT=0` 卡片退化为 start/end 两事件。

回归：`tests/tui/test_fork_cards_render.py`（渲染/重放/偏移/rev 守卫）、
`tests/tui/test_reducer.py`（卡片 upsert/progress 收敛/rev 单调）、
`tests/ist_core/test_fork_step_emit.py`（producer 事件）、
`tests/ist_core/compile_engine/test_engine_loop_stub.py`（engine_tick）。

## Slash 指令与记忆状态行

`/memory`、`/remember`、`/footprint`、`/kms`、`/reset` 等 slash 命令映射见
`main/ist_core/tui/slash_commands.py`（user-invocable skill 同时自动注册为 `/<skill-name>`）；
footer 状态行展示 `💭 dreaming` / `✓ memory consolidated` 等记忆子系统状态。

## Web Terminal（PTY 桥）

`web_server.py`：FastAPI + xterm.js，`pty.openpty()` spawn `python -m main.ist_core.tui.cli`
子进程，master 端原始 ANSI 字节经 `/ws/terminal` WebSocket 转发。**语义全在 TUI 子进程**，
浏览器是哑终端；上传/下载走自定义 OSC 7001/7002 带外信号。任何 TUI 改进对终端与 Web 是
同一份 ink 代码、零 Web 侧改动。
