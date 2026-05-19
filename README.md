# IST-Core

通用只读测试分析 Agent —— 基于 LangGraph + Textual TUI。

## 快速开始

```bash
# 安装
pip install -e .

# 配置（复制 environment.example 并填入 DashScope API Key）
cp environment.example environment
# 编辑 environment 填入 DASHSCOPE_API_KEY

# 启动 TUI
infotest

# 单次查询（print 模式）
infotest -p "项目里有哪些测试用例？"
```

## 功能

- Textual 终端 UI，支持多轮对话
- 通用原子工具：ls / rg-backed glob / rg-backed grep / range read_file / python_exec / bash_exec
- 大仓库文件搜索：优先使用 ripgrep，支持按文件列表 / 命中内容 / 计数搜索，支持结果分页和大文件按行范围读取；ripgrep 不可用时自动回退到 Python 只读实现
- 3 tier 模型分级（opus / sonnet / haiku）按任务复杂度自动选模型
- Thinking block 渲染（qwen3 / Claude 系列 thinking 输出折叠展开）
- 13 个 slash 命令

## 文件搜索能力

Core 的 `qa_deepagent_glob` / `qa_deepagent_grep` / `qa_deepagent_read_file` 是只读工具，限制在项目根目录内，并继续拒绝访问 `.git`、虚拟环境、本地向量库和运行日志等目录。

- `qa_deepagent_glob` 优先使用 `rg --files --glob` 定位候选文件，支持 `max_results` 和 `offset`。
- `qa_deepagent_grep` 优先使用 ripgrep regex 搜索，支持 `output_mode="files_with_matches" | "content" | "count"`、`head_limit`、`offset`、`type` 和 `context`。
- `qa_deepagent_read_file` 对文本文件使用行范围读取；小文件走快路径，大文件流式扫描并只保留请求的行段。
- 搜索超时或输出过大时会返回可用的部分结果和提示；没有部分结果时会明确报错，不把超时误报为无匹配。

## Slash 命令

| 命令 | 说明 |
|------|------|
| `/help` | 显示帮助 |
| `/clear` | 清屏 |
| `/model` | 列出 / 切换模型 |
| `/tier` | 列出 / 切换模型 tier |
| `/threads` | 列出历史会话 |
| `/resume` | 恢复历史会话 |
| `/continue` | 继续上次对话 |
| `/cost` | 显示 token 用量 |
| `/compact` | 压缩上下文 |
| `/plan` | 切换 plan 模式 |
| `/init` | 初始化项目分析 |
| `/version` | 显示版本 |
| `/exit` | 退出 |

## 快捷键

| 键 | 功能 |
|----|------|
| `Ctrl+O` | 展开/折叠所有工具输出 + thinking |
| `Ctrl+L` | 重绘屏幕 |
| `Ctrl+G` | 用 $EDITOR 编辑长 prompt |
| `Shift+Tab` | 切换 plan / normal 模式 |
| `Ctrl+R` | 搜索历史 |
| `Ctrl+C` | 中断 / 退出 |
| `Ctrl+D` | 直接退出 |

## 模型配置

```bash
# environment 文件
QA_AGENT_FALLBACK_MODEL=anthropic:qwen-plus
QA_AGENT_ALLOWED_MODELS=qwen-plus,qwen-turbo,qwen-max,qwen3.6-plus

# 3 tier 分级
QA_AGENT_OPUS_MODEL=qwen3.6-plus      # 高复杂度
QA_AGENT_SONNET_MODEL=qwen-plus       # 中等
QA_AGENT_HAIKU_MODEL=qwen-turbo       # 简单
```

## 架构

```
TUI (Textual App)
 ↕ Bridge (async query → graph.invoke)
 ↕ EventBus (进度事件流)
 ↕ LangGraph StateGraph (normalize → qa_node → finalize)
 ↕ main_agent (deepagents ReAct loop)
 ↕ Tools (file_tools + exec_tools)
```

## License

MIT
