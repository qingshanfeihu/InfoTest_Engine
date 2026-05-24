# IST-Core

通用测试分析 Agent —— 基于 LangGraph + Textual TUI。

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
- 通用原子工具：ls / rg-backed glob / rg-backed grep / range read_file / write_file / edit_file / python_exec / bash_exec
- 大仓库文件搜索：优先使用 ripgrep，支持按文件列表 / 命中内容 / 计数搜索，支持结果分页和大文件按行范围读取；ripgrep 不可用时自动回退到 Python 只读实现
- 3 tier 模型分级（opus / sonnet / haiku）按任务复杂度自动选模型
- Thinking block 渲染（qwen3 / Claude 系列 thinking 输出折叠展开）
- 13 个 slash 命令

## 文件搜索能力

Core 的 `qa_deepagent_glob` / `qa_deepagent_grep` / `qa_deepagent_read_file` 是只读工具，`qa_deepagent_write_file` / `qa_deepagent_edit_file` 是写入工具。所有工具限制在 agent 沙箱内（`knowledge/data/` + `workspace/`），并拒绝访问 `.git`、虚拟环境、平台代码和运行日志等目录。

- `qa_deepagent_glob` 优先使用 `rg --files --glob` 定位候选文件，支持 `max_results` 和 `offset`。
- `qa_deepagent_grep` 优先使用 ripgrep regex 搜索，支持 `output_mode="files_with_matches" | "content" | "count"`、`head_limit`、`offset`、`type` 和 `context`。
- `qa_deepagent_read_file` 对文本文件使用行范围读取；小文件走快路径，大文件流式扫描并只保留请求的行段。
- `qa_deepagent_write_file` 原子写入文件到 `workspace/outputs/`（唯一可写目录），支持 overwrite 控制。
- `qa_deepagent_edit_file` 对 `workspace/outputs/` 内已有文件执行精确字符串替换。
- 搜索超时或输出过大时会返回可用的部分结果和提示；没有部分结果时会明确报错，不把超时误报为无匹配。

## 工具元数据

`main/qa_agent/tools/_shared/metadata.py` 注册当前 runtime 默认挂载的 8 个工具：

- `qa_deepagent_ls`
- `qa_deepagent_glob`
- `qa_deepagent_grep`
- `qa_deepagent_read_file`
- `qa_deepagent_write_file`
- `qa_deepagent_edit_file`
- `qa_exec`
- `qa_bash`

旧版 `qa_search_*`、`defect_*`、`qa_invoke_reviewer*` 等业务工具名不再属于当前 runtime metadata；TUI 对历史事件的渲染兼容与 runtime 工具注册分开维护。

## 目录结构

```
project_root/
├── knowledge/data/        ← 纯只读知识库（agent 可读不可写）
│   ├── orgin/             ← 源文档（APV/NSAE 产品文档）
│   └── markdown/          ← KMS 管线产出
│       ├── product/       ← 产品文档 markdown
│       └── qa/            ← 测试策略/历史用例 markdown
├── workspace/             ← agent 工作区
│   ├── inputs/            ← 用户上传的待评审文件（TUI/web 写入，agent 只读）
│   ├── outputs/           ← agent 生成的报告/标注（agent 可写）
│   └── defects/           ← 缺陷缓存（ingest 管线写入，agent 只读）
├── runtime/               ← 运行时产物（agent 不可见）
│   ├── logs/              ← LangGraph 运行日志
│   ├── conversation_history/
│   ├── large_tool_results/
│   └── users/
├── memory/                ← 记忆系统（agent 不可见）
├── main/                  ← 平台代码
├── tests/                 ← 测试
├── scripts/               ← 脚本
└── backup/                ← 历史归档
```

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
