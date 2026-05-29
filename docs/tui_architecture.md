# InfoTest Engine 终端 TUI 与 Ink 浏览器网页事件双核渲染架构

InfoTest Engine 不仅提供了高性能的核心分析内核，还自主设计并实现了一套双核人机交互系统：既包含基于 **Textual** 的极客风炫酷高保真**终端 TUI（Terminal UI）**控制台（命令行输入 `infotest` 直接唤起），也支持高精度网页渲染、底层运行在 FastAPI 上的 **Web Terminal Web 界面**（执行 `infotest --server` 访问 8080）。

这套强交互平台背后的核心驱动逻辑，是**事件驱动进程总线（EventBus）与大模型流式中继器（`_MainAgentProgressHandler`） 的完美协作。**

---

## 一、 事件驱动型 EventBus 核心

系统的所有组件均不进行互相硬编码的直接状态修改。系统中所有发生的流式 Token 响应、工具处理状态以及提示，都打包通过 `main/ist_core/events.py` 定义的 `EventBus` 总线进行全局广播与就地映射处理：

- **`IstCoreEvent`**：一个高规范的强类型数据 Dict。必须包含：
  - `run_id`（执行期唯一 UUID，做多路会话区分）
  - `kind`（事件触发类型：`on_llm_new_token`、`on_tool_start`、`on_chat_state_change` 等）
  - `payload`（承载的具体数据体）

通过订阅 `EventBus`，无论是运行在终端里的 Textual 渲染节点，还是连接着 WebSocket 端点的网页 Ink 页面，均能以最低 2ms 的时延、互不侵入地实现用户渲染层的数据即时同步刷新。

---

## 二、 _MainAgentProgressHandler 全流程进度转发机制

在主图运行节点（`build_ist_core_graph` / `qa_node`）工作时，其处于一个复杂的 LangGraph 嵌套子节点生命周期。传统的 SDK 仅回执最终大字符串，用户面对空屏或闪烁的光标，产品体验极差。

为了打破大模型思考的“黑盒状态”，系统在 `graph.py` 内部内置了定制的 **`_MainAgentProgressHandler`**（继承自 LangChain 顶层 `BaseCallbackHandler`）：

```
[IST-Core Graph 节点运行]
        │
        ├── LLM 产生新 Token ➔ 触发 ProgressHandler.on_llm_new_token()
        ├── 调用特定沙箱工具 ➔ 触发 ProgressHandler.on_tool_start()
        └── 捕获到分析缺陷库 ➔ 触发 ProgressHandler.on_tool_end()
        │
        ▼ (打包为 IstCoreEvent 广播)
   【EventBus 运行时事件总线】
        │
        ├── 广播 A: Textual 终端 TUI ➔ 即时刷新状态指示栏 💭 dreaming 与进度条
        └── 广播 B: Web FastAPI Socket ➔ Ink 网页光标追随、Selection 交互屏高亮
```

### 极高帧率的进度及工具透明
- **LLM Token 瞬间直达**：当主模型产生一词、甚至一个特殊前缀时，ProgressHandler 捕获并将其发送给 EventBus，接收端（TUI 屏）以像素级逐字流动打字回显。
- **工具名称与入参投射**：当 IST-Core 决定调用高能执行工具如 `qa_exec` 或 `qa_deepagent_grep` 时，ProgressHandler 会捕获该工具名称并前置推送。屏幕底部会实时高亮显示当前智能体启动了什么底层工作、检索了哪个目录，彻底消除用户焦虑感。
- **长 ToolMessage 优雅截断防屏爆**：如果工具返回的技术数据非常庞大（如读取一个 > 300 行的代码或返回上千行缺陷列表），前台的总线消费模块（`main/ist_core/tui/sink.py`）会自动对工具日志进行极简折叠或截断提取（Truncate），在保留关键操作证据的同时，确保前台终端 UI 不会陷入无意义的满屏错乱刷屏，实现极佳的图形人机美感。

---

## 三、 TUI 的极简炫酷组件与快捷 / Slash 指令体系

通过输入 `infotest`，用户直接拉起高度可控的终端可视化页面，在这里，所有的交互指令、后台记忆归结状态一览无余：

### 1. 常规控制组件
- **Transcript Pane (对话故事板卷轴)**：自动解析大模型的 Markdown 输出，高保真格式化渲染。对于推理过程 (`reasoning_content`），自动使用淡色微缩文本在对话气泡上方优雅展开或随心收拢。
- **Footer Pane & Dreaming 状态行**：
  - *`💭 dreaming`*：后台庄周梦蝶 DreamTask 四阶段正在高效率整合；
  - *`✓ memory consolidated`*：记忆已由提炼者合并蒸馏归位，IST-Core 大脑战力随时饱满。

### 2. 多维斜杠（Slash）交互指令映射
在输入候选框中直接敲下 `/` 即可激活高能系统内设命令，不需要通过对话触发模型猜想，开销小、运行快、命令极其纯粹、一致：

| Slash 指令 | 系统内部调用函数 / 类映射 | 底层触发的技术动作与物理职责 |
| :--- | :--- | :--- |
| `/memory` | `main/ist_core/tui/memory_command.py` | 全景盘点当前会话中的 **L1 临时工作记忆** 指针，以及后台沉淀的 **L2 长期记忆** 明细数据。 |
| `/remember [text]` | `/remember --feedback [topic] [text]` | 提供向后兼容的偏好记忆显式写入，允许用户手动注入、纠正特定的 IST-Core 偏好偏见。 |
| `/footprint show/search` | `main/ist_core/tui/footprint_command.py` | 展现或全文语义检索在 `knowledge/footprints/` 沉淀出的 **Footprint 产品知识树**，调阅精确定位。 |
| `/kms status/update` | `main/ist_core/tui/kms_command.py` | 自带进度监控。查看当前文档库分类状态。或就地触发子进程（`kms_classifier`）对新置入的文件分类。 |
| `/reset` | `main/ist_core/tui/reset_command.py` | 一键无污染擦除当前 Session。添加 `--all` 参数不仅清空 L1，还可以高精度深度物理抹去 L2 长期偏好储备。 |

---

## 四、 页面 Ink（墨水）渲染引擎及 Cursor、Selection 精准重排

当用户激活 Web Terminal 模式（即 `infotest --server`），FastAPI 在后台提供基础桥接服务，前台用精心设计的 **Ink 绘制引擎** 来动态把终端的一砖一瓦解析并同步推送到浏览器进行富文本转化：

- **Cursor Manager（墨水光标追随者）**：它在 WebSocket 信息流上，通过毫秒级帧差重排，感知正在生成的流式大模型 markdown 内容中的非闭合段落，精准模拟出一颗“极速平滑颤动的打字光标”，打破了常规网页 Web AI 信息流断档式的顿挫感。
- **Selection Engine（智能交互重排选择器）**：网页上的富文本技术用例、段落可以随时被操作员用鼠标圈选，引擎能在后台精准捕获圈选位置对应的 Markdown 相对坐标段（1-based 像素投影），并高精度激活复制或定向纠错，建立高效率的代码协同流。
