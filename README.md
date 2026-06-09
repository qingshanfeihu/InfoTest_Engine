# IST-Core

通用测试分析 Agent —— 基于 LangGraph + Textual TUI。

## 快速开始

```bash
# 安装
pip install -e .

# 配置（复制 environment.example 并填入 API Key）
cp environment.example environment
# 编辑 environment 填入 DASHSCOPE_API_KEY 或 DEEPSEEK_API_KEY，并选用对应 provider

# 启动 TUI（Textual 终端）
infotest

# 启动 Web Terminal（浏览器，默认 http://localhost:8080）
infotest --server

# 单次查询（print 模式）
infotest -p "项目里有哪些测试用例？"

# 清除对话历史和临时文件
infotest reset           # 默认交互确认；加 --yes 跳过；--all 含长期记忆
```

## 功能

- Textual 终端 UI，支持多轮对话
- 通用原子工具：ls / rg-backed glob / rg-backed grep / range read_file / write_file / edit_file / python_exec / bash_exec
- 大仓库文件搜索：优先使用 ripgrep，支持按文件列表 / 命中内容 / 计数搜索，支持结果分页和大文件按行范围读取；ripgrep 不可用时自动回退到 Python 只读实现
- 3 tier 模型分级（opus / sonnet / haiku）按任务复杂度自动选模型
- Thinking block 渲染（思考输出折叠展开，ctrl+t 切换）
- 16 个 slash 命令

## 文件搜索能力

Core 的 `qa_deepagent_glob` / `qa_deepagent_grep` / `qa_deepagent_read_file` 是只读工具，`qa_deepagent_write_file` / `qa_deepagent_edit_file` 是写入工具。所有工具限制在 agent 沙箱内（`knowledge/data/` + `workspace/`），并拒绝访问 `.git`、虚拟环境、平台代码和运行日志等目录。

- `qa_deepagent_glob` 优先使用 `rg --files --glob` 定位候选文件，支持 `max_results` 和 `offset`。
- `qa_deepagent_grep` 优先使用 ripgrep regex 搜索，支持 `output_mode="files_with_matches" | "content" | "count"`、`head_limit`、`offset`、`type` 和 `context`。
- `qa_deepagent_read_file` 对文本文件使用行范围读取；小文件走快路径，大文件流式扫描并只保留请求的行段。
- `qa_deepagent_write_file` 原子写入文件到 `workspace/outputs/`（唯一可写目录），支持 overwrite 控制。
- `qa_deepagent_edit_file` 对 `workspace/outputs/` 内已有文件执行精确字符串替换。
- 搜索超时或输出过大时会返回可用的部分结果和提示；没有部分结果时会明确报错，不把超时误报为无匹配。

## 工具元数据

[main/ist_core/tools/_shared/metadata.py](main/ist_core/tools/_shared/metadata.py) 注册当前 runtime 默认挂载的 8 个工具：

- `qa_deepagent_ls`
- `qa_deepagent_glob`
- `qa_deepagent_grep`
- `qa_deepagent_read_file`
- `qa_deepagent_write_file`
- `qa_deepagent_edit_file`
- `qa_exec`
- `qa_bash`

旧版 `qa_search_*`、`defect_*`、`qa_invoke_reviewer*` 等业务工具名不再属于当前 runtime metadata；TUI 对历史事件的渲染兼容与 runtime 工具注册分开维护。

## 💡 核心技术文档（全新增补）

为了帮助新开发者快速理解 InfoTest Engine / IST-Core 的软核物理边界与高位认知特性，请查阅以下位于 [docs/](docs) 的 4 篇技术实录：

- **记忆层级与 Dream 归纳**：[docs/memory_system.md](docs/memory_system.md) (详细阐释三层记忆、庄周梦蝶四阶段以及足迹 Footprint 知识树机制)
- **多根白名单防护沙箱**：[docs/file_sandbox.md](docs/file_sandbox.md) (剖析文件系统的零信任防护、三闸/四闸拦截防御纵深)
- **KMS 管线与直出 Markdown**：[docs/kms_pipeline.md](docs/kms_pipeline.md) (解答“为何去向量化 RAG”，并记录元指纹缓存与高保真 Excel 离线 Markdown 解析)
- **控制台 TUI 与 Web 墨水渲染**：[docs/tui_architecture.md](docs/tui_architecture.md) (详解 EventBus 广播流、打字光标延迟平滑渲染以及长日志限额折叠机制)

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
```

## Slash 命令

| 命令 | 说明 |
|------|------|
| `/help` | 显示帮助 |
| `/clear` | 清屏 |
| `/model` | 列出 / 切换模型 |
| `/threads` | 列出历史会话 |
| `/resume` | 恢复历史会话 |
| `/continue` | 继续上次对话 |
| `/cost` | 显示 token 用量 |
| `/compact` | 压缩上下文 |
| `/plan` | 切换 plan 模式 |
| `/init` | 初始化项目分析 |
| `/reset` | 清除对话历史 + 临时文件（`--all` 含长期记忆） |
| `/memory` | 查看 / 清理记忆系统 |
| `/remember` | 显式追加偏好 / 反馈到长期记忆 |
| `/footprint` | 查询 CLI footprint 知识树 |
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

统一走 OpenAI 兼容端点（任何 OpenAI 协议端点皆可：小米 MiMo / DeepSeek 原生口 / DashScope 兼容口 / 自建网关）。换厂商只改 `OPENAI_BASE_URL` + key + 模型名。

```bash
# environment 文件（详见 environment.example）
OPENAI_BASE_URL=https://token-plan-cn.xiaomimimo.com/v1   # 留空走默认 MiMo CN 集群
OPENAI_API_KEY=sk-...
IST_MODEL=mimo-v2.5-pro
IST_ALLOWED_MODELS=mimo-v2.5-pro,mimo-v2.5

# 3 tier 分级
IST_OPUS_MODEL=mimo-v2.5-pro     # 高复杂度
IST_SONNET_MODEL=mimo-v2.5-pro   # 中等
IST_HAIKU_MODEL=mimo-v2.5        # 简单（footprint 提取 / KMS 分类）
```

## 架构

```
TUI (Textual App)
 ↕ Bridge (async query → graph.invoke)
 ↕ EventBus (进度事件流)
 ↕ LangGraph StateGraph (normalize → qa_node → review_gate → finalize)
 ↕ main_agent (deepagents ReAct loop) + subagents (explore / review-verification)
 ↕ Tools (file_tools + exec_tools + skills + ask_user)
```

## Skills 系统

IST-Core 支持 skill 扩展机制。已有 skill：

- **test-case-review**：测试用例评审，含独立 verifier subagent + review_gate 硬闸 + 桶隔离 + finalize 工程兜底

新 skill 编写参考：
- `docs/skill_authoring_standard.md`：完整模板与编写规范
- `docs/framework_design_notes.md`：当前框架设计说明

## 文档

- `WHATS_NEW.md`：版本变更记录
- `ARCHITECTURE.md`：详细架构说明
- `CLAUDE.md`：项目级 agent 指令（agent 启动时加载）
- `todolist.md`：开发待办与历史决策
- `docs/skill_authoring_standard.md`：Skill 编写标准
- `docs/framework_design_notes.md`：框架设计说明

## License

MIT
