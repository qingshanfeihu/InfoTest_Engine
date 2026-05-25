# Known Issues

记录开启 `extra_body={"enable_thinking": True}` 后已知 / 待观察的问题。新问题请追加到末尾，标注首次出现日期与触发场景。

## 2026-05-20 / Qwen3.6 + enable_thinking 模式

### 1. `tool_choice="required"` 与 thinking 模式不兼容

- **现象**：阿里云百炼官方文档明说"思考模式的模型不支持强制调用某个工具"。如果 deepagents / langchain 在某个 sub-agent 链路里通过 `tool_choice` 强制选工具，请求会被 DashScope 拒。
- **当前是否触发**：未在 main_agent 主路径观测到。Reviewer hierarchical pipeline 的 4 个 sub_agent 走 `create_deep_agent` 默认 `tool_choice="auto"`，理论上不受影响。
- **应对**：首次跑长流程时盯一下日志；若出现 `tool_choice not supported in thinking mode` 类错误，定位到具体调用方后改回 `auto`，或在该链路单独 `extra_body={"enable_thinking": False}` 关闭。
- **回滚**：`main/qa_agent/agents/_llm.py` 把 `extra_body.setdefault("enable_thinking", True)` 改成 `False`。

### 2. Token 消耗显著上升

- **现象**：`reasoning_content` 不参与 prompt cache 但计入 output tokens。工具调用密集的多轮回合（reviewer 跑 4 sub_agent × 12+ 工具）单次 run 的累计 token 可能从 ~700k 涨到 ~1M+。
- **TUI 表现**：footer `tokens` 数字上升更快；之前 footer 把 `/ 128,000 tokens` 误展示成上下文窗口比例（已修复，commit 1054980），现在只显示累计值。
- **应对**：长流程结束后 `/compact` 重置 transcript + token 计数；或评审任务跑完一回合就开新 thread。
- **不应对的代价**：放任不管，单 thread 里 sub_agent 会被 deepagents 的 `summarization_middleware(max_tokens=28000)` 截断历史，模型记不住前面读过的文件。

### 3. 思考内容很长 → viewport 滚动压力

- **现象**：单条 `ThinkingMessage` 可能是几百字的中文段落。transcript 现在按真实视觉行（`\n` 拆 + 终端宽软换行）算 sticky scroll（commit 等待中），AI 流式独白也修复了被工具行覆盖的 bug。但若一次性思考超过 viewport 高度，仍只能看到末尾。
- **TUI 表现**：思考行被滚出屏幕外；按 ↑/↓（如果 transcript 实现了上下翻）或 ctrl+l 重渲染。
- **应对**：暂未实现可折叠的 `✶ Thinking (ctrl+o to expand)`，目前思考整段以 dim 灰 `✶` 前缀直接打。后续考虑把 ThinkingMessage 也接入 `_tool_output_blocks` 的折叠逻辑。

### 4. `reasoning_content` 字段名不稳定

- **现象**：抽 thinking 走 `additional_kwargs.get("reasoning_content") or additional_kwargs.get("reasoning")`。LangChain 不同小版本字段名有过摇摆（`reasoning` vs `reasoning_content` vs nested under `extra_data`）。
- **应对**：兜底已加两个 key；若升级 langchain-openai 后又看不到思考行，先打 `additional_kwargs.keys()` 排查。
