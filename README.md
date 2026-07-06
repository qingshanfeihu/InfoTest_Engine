# InfoTest Engine

**IST-Core** — 面向网络设备测试的对话式 Agent 平台：把产品文档与人工用例编译成**断言真覆盖目标行为、可上机自动执行**的测试卷,并用真实设备执行结果驱动知识闭环。基于 LangGraph + deepagents + Textual TUI。

> 当前版本:**1.0.5-beta.1**(V6 循环驱动编译引擎首个 beta,见 [CHANGELOG](CHANGELOG.md))

## 它做什么

```
产品文档/人工用例(PDF·docx·xlsx 脑图)
        │  KMS 管线(LLM 分桶 + MinerU/openpyxl → markdown 直出)
        ▼
只读知识库(knowledge/data/markdown/ + footprint 已验证事实树)
        │
        ├── 测试评审(test-list-review):证据纪律 + 缺陷库检索
        │
        └── 用例编译(V6 引擎):脑图 → case.xlsx
              编写(fork worker)→ 欠定问人(interrupt)→ 机械门 → 合并
              → 上机(SSH/pytest 框架)→ 归因 → 只重编 fail 子集 → 不动点
              → 真 PASS 写回先例与 footprint(知识闭环)
```

判据:除「脑图与设备实际结构有争议需人工拍板」与「产品缺陷」外,其余用例全部一遍上机通过。三域对照轮:dongkl 21/34(重灾域)、yzg 25/26、zhaiyq 51/53,编排事故 0。

## 快速开始

```bash
pip install -e .

# 配置:复制模板并填 OpenAI 兼容端点的 key(任何 OpenAI 协议端点皆可)
cp environment.example environment
#   OPENAI_BASE_URL=…  OPENAI_API_KEY=sk-…  IST_MODEL=…

infotest              # Textual 终端 TUI(默认入口)
infotest --server     # Web Terminal(浏览器,默认 :8080)
infotest -p "…"       # 单次查询(print 模式)
langgraph dev --no-browser --port 2024   # 可选:Studio 可视化三张图
```

## 核心架构:三层栈

| 层 | 载体 | 内容 |
|---|---|---|
| 定义层 | **md**(YAML frontmatter + XML 分节正文) | skill / agent / 引擎资产包——人写人审,可 diff |
| 回合层 | **deepagents / create_agent** | LLM 自由度孔:qa 主 agent 与每个 fork 都是一张小图 |
| 运行时层 | **LangGraph StateGraph** | 会话图(qa_agent)、编译引擎图、fork 图共用同一地基 |

数据形态判定表(架构红线,详见 [CLAUDE.md](CLAUDE.md)):人定义的→md;确定性流程→py(图,节点=纯函数);机器间传的→JSON(盘上台账,按引用流);进 LLM 上下文的→XML 信封;语义判断→skill(fork);单一正确做法→tool;**LLM 永远不当胶水**——胶水是图的条件边。

## V6 编译引擎(`main/ist_core/compile_engine/`)

编译闭环 = 一张 8 节点 StateGraph,main agent 只调薄工具 `compile_engine_run(mindmap, version)` 一次:

```
prep ─► worker_fanout ─►(欠定)─► ask_decision(interrupt 问人)─► worker_fanout
          │(全过)
          ▼
        merge(pass 卷面锁复核)─► run_digest(上机)─►(fail)─► attribute(归因)
          ▲                        │(子集全过)                  │(reflow ⊆ fail 集)
          └────── 终验整卷 ◄───────┘            worker_fanout ◄─┘
                    │(全 pass)
                    ▼
        writeback(先例+footprint 双写回)─► report(engine_report.json)
```

- 节点三类:[mech] 直调工具 `.func` / [llm] 孔经 `execute_fork_skill` / [user] 孔经官方 `interrupt`+`Command(resume)`
- **断点续跑**:SqliteSaver 分库 checkpoint,同参数重调即从断点继续;`run_marker` 幂等防重烧设备轮
- **EngineLedger 迁移合法性表**:`passed→重编` 在数据层非法;pass 即锁卷面 mtime;重派集 ⊆ fail 集(代码断言)
- **质量门**:emit 必崩门(恒真/恒假断言族、崩卷形态——全部从测试框架 mirror 源码语义推导)+ 成品卷 lint 挂凭证/合并双卡点;语义终判 = 上机 oracle
- 回退:`IST_COMPILE_ENGINE=0` 走 v5 main-orchestrated 编排

设计全文:[docs/DESIGN_v6_engine.md](docs/DESIGN_v6_engine.md)

## Skills(`main/ist_core/skills/`)

| Skill | 类型 | 用途 |
|-------|------|------|
| `test-list-review` | user-invocable | 测试用例/策略评审(主入口) |
| `ist-compile-engine` | user-invocable | **V6 编译主入口**:一句话跑整条闭环 |
| `ist-verify` | user-invocable | 成品 excel 上机验证 + 归因 |
| `device-verify` | user-invocable | 设备 SSH 只读/配置验证 |
| `compile-worker` / `compile-attributor` | fork | 编译编写孔 / 归因孔 |
| `ist-compile` / `ist-compile-draft` / `ist-compile-grade` | inline/fork | v5 fallback 编排与子流程 |
| `config-automation` / `config-answer` | inline | 环境 IP 替换 / 配置问答 |
| `review-verification` / `escalate-when-stuck` | fork/inline | 评审验证 / 连续失败上报 |

user-invocable skill 同时注册为 TUI slash 命令。资产标准(名称/frontmatter/XML 骨架/工具白名单)见 [docs/skill_authoring_standard.md](docs/skill_authoring_standard.md);机器门 `tests/ist_core/skills/test_skill_package_standard.py`。

## 目录结构

```
project_root/
├── knowledge/
│   ├── data/              ← 纯只读知识库(agent 可读不可写)
│   │   ├── orgin/         ← 源文档
│   │   ├── markdown/      ← KMS 管线产出(product/ + qa/)
│   │   └── auto_env/      ← 自动化拓扑(network_topology.json 唯一事实源)
│   ├── footprints/        ← 已验证 CLI 事实树(设备行为知识)
│   └── framework/mirror/  ← 测试框架源码镜像(机械门闭集的解析源)
├── workspace/             ← agent 工作区
│   ├── inputs/            ← 用户上传(agent 只读)
│   └── outputs/           ← agent 产出(唯一可写区)
├── runtime/               ← 运行时产物(agent 沙箱黑名单)
├── memory/                ← 三层记忆(L1 工作/L2 长期/L3 项目指令)
├── main/                  ← 平台代码(main.ist_core / main.case_compiler / …)
└── tests/                 ← 回归(全量 stub-LLM e2e + prompt 结构门 + skill 标准门)
```

文件沙箱:`fs_*` 工具经多根白名单 + 路径穿越三闸(读)/四闸(写)强制,详见 [docs/file_sandbox.md](docs/file_sandbox.md)。

## 模型配置

统一 OpenAI 兼容端点(小米 MiMo / DeepSeek / minimax / 自建网关),换厂商只改三行:

```bash
OPENAI_BASE_URL=…
OPENAI_API_KEY=sk-…
IST_MODEL=deepseek-v4-pro     # 主档:全局默认,深度思考默认开(effort 默认 max)
IST_FLASH=deepseek-v4-flash   # 省钱档:检索/提取/蒸馏类轻任务,同样思考+max,只为降单价
# IST_EFFORT=high             # 思考深度全局档(high|max);fork 可按点覆盖(agents md 的 effort:)
```

## 常用 TUI 命令

`/kms`(知识管线) · `/footprint`(事实树) · `/memory` `/remember`(记忆) · `/model` `/cost` `/resume` `/plan` · user-invocable skill 均为 `/<skill-name>`。快捷键:`Ctrl+O` 折叠工具输出、`Ctrl+T` 折叠 thinking、`Ctrl+R` 历史搜索、`Ctrl+G` $EDITOR 编辑长 prompt。

## 文档

- [CHANGELOG.md](CHANGELOG.md) — 版本变更
- [CLAUDE.md](CLAUDE.md) — 项目级 agent 指令与架构决策全景(单一事实源)
- [docs/DESIGN_v6_engine.md](docs/DESIGN_v6_engine.md) — V6 编译引擎设计
- [docs/memory_system.md](docs/memory_system.md) — 三层记忆 + Dream + Footprint
- [docs/file_sandbox.md](docs/file_sandbox.md) — 多根白名单沙箱
- [docs/kms_pipeline.md](docs/kms_pipeline.md) — KMS 管线与 markdown 直出
- [docs/tui_architecture.md](docs/tui_architecture.md) — TUI/Web 渲染架构
- [docs/skill_authoring_standard.md](docs/skill_authoring_standard.md) — Skill 编写标准

## 安全

- API key 只经项目根 `environment` 文件注入(已 .gitignore),禁止在代码/注释/日志打印 Token
- agent 文件访问经多根沙箱强制;`runtime/`(含验证台账)在黑名单内,工具进程写、agent 伪造不了
- 修改沙箱常量/凭据处理需过安全评审(`security-reviewer` agent)

## License

MIT
