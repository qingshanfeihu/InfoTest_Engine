# team2 · GitHub 最新提交 vs 本地 同步/整合分析

> 任务 #9:检查 github 最新提交与本地是否冲突,合并或整合功能,**冲突以本地为准**。
> 全程除 `git fetch origin` 外零改动;本报告为唯一写入文件。整合动作**只列不执行**(工作树脏,统一由主协调在树干净后执行)。
> 生成时间锚:2026-07-16。

---

## 一、结论速览(TL;DR)

1. **origin/main 已被别处推进**:`195f4124 → d8a0d05d`,共 **12 个本地没有的新提交**(作者含 wangdh 等)。主体是 **`wecom_bot_smart/` 企微智能机器人子系统(7 提交)**,外加 footprint 版本参数、streaming 修复、tui、tools、command_builder 各 1。
2. **对多队未提交脏文件零威胁**:12 个远端提交**无一碰到**本地任何脏文件(`compile-worker.md` / `DESIGN_dongkl_finalization.md` / `THEORY_k_state_machine.md` / `docs/forensics/*`)。多队在改的内容 100% 安全。
3. **内存态合并模拟(`git merge-tree`,不碰工作树)判定:真冲突只有 2 个文件**——`agents/config-answer-draft.md` 与 `tools/knowledge/footprint_lookup.py`,且**都是本地已提交内容**(非脏文件),可待树干净后解决。另外 8 个「双方都改」的核心文件全部**自动合并干净**。
4. **1 个高价值可安全带入的 bugfix**:`a7296da8`(command_builder IP 加引号 bug)——**修复本地当前就存在的真实缺陷**,自动合并干净,直接利好编译产出。建议纳入。
5. **远端落后本地的部分**:本地领先 origin/main **131** 个提交(编译引擎全部工作),待本地 push;4 个 `devin/*` 与 `refactor/naming` 远端分支已并入 main 无需处理;3 个 `fix/*` 分支判为被本地等价能力取代;`wangjuan`(auth/session)为正交独立特性。

---

## 二、分支拓扑图(文本)

```
               merge-base = 195f4124  (旧 origin/main tip)
                        │
        ┌───────────────┴───────────────────────────┐
        │                                            │
   本地侧【领先 131】                          远端侧【领先 12,别处推送】
        │                                            │
   130 commits                                  12 commits
        ↓                                            │  8c0a933a  企微流式推送
   2a03b16f  main(本地)                             │  a7296da8  command_builder bugfix ★
        ↓ +1                                         │  d4fa832e  迁官方 wecom-aibot-sdk
   dc435c93  HEAD = fix/dongkl-finalization-yzg…     │  0d8946d1  wx_send_file
        ↑ 你在这里(工作树脏)                        │  2e0c564c  streaming 去重
                                                     │  db71f020  tui 自定义监听地址
                                                     │  71af5631  SDK decrypt_file
                                                     │  707b64d4  Presentation Layer
                                                     │  775ff014  企微消息格式
                                                     │  49d87c68  footprint nodes_subdir △
                                                     │  1d48d13c  企微云文档+意图路由
                                                     ↓  d8a0d05d  origin/main(NEW)

★ = 高价值可安全带入   △ = 引发冲突(footprint_lookup.py)
本地 main 与本地 HEAD(fix)差 1 个提交(dc435c93);二者相对 origin/main 分别领先 130 / 131。
```

**关键数字(`git rev-list --left-right --count`)**
| 比较对 | 本地领先 | 远端领先 |
|--------|--------:|--------:|
| HEAD(fix) ↔ origin/main | 131 | 12 |
| 本地 main ↔ origin/main | 130 | 12 |

---

## 三、逐远端新提交分析表(12 个)

| # | 提交 | 子系统 | 摘要 | 碰核心共享文件? | 合并判定 |
|---|------|--------|------|----------------|---------|
| 1 | `8c0a933a` | wecom_bot_smart | IST-Core 流式调用+stream delta 逐帧推送(替换 5min 轮询) | gateway/main 等新子系统 | 干净 |
| 2 | `a7296da8` | **command_builder** | 修参数格式化对 `-`/`.` 错误加引号(IP 被误引号) | command_builder.py(本地也改,**不同区**) | **自动合并干净·★高价值** |
| 3 | `d4fa832e` | wecom_bot_smart | 迁移官方 wecom-aibot-sdk + ask_user 企微双向通道 | ask_user/__init__.py(自动合) | 干净 |
| 4 | `0d8946d1` | tools | 新增企微发送文件工具 `wx_send_file` | wx_send_file.py(纯新增) | 干净 |
| 5 | `2e0c564c` | **streaming** | skip on_chat_model_end 去重 llm_end | streaming.py(**本地未碰**) | 干净(仅远端) |
| 6 | `db71f020` | tui | Web Terminal 自定义监听地址 | tui/cli.py(仅远端) | 干净 |
| 7 | `71af5631` | wecom_bot_smart | 用 SDK decrypt_file 替换手写 AES | wecom_bot_smart/* | 干净 |
| 8 | `707b64d4` | wecom_bot_smart | 引入 Presentation Layer+网关流式/进程退出 | presentation.py 等 | 干净 |
| 9 | `775ff014` | wecom_bot_smart | 优化企微消息格式渲染一致性 | wecom_bot_smart/* | 干净 |
| 10 | `49d87c68` | **footprint** | 支持按 nodes_subdir 独立缓存索引(kb_footprint 加 version 参数) | **footprint_lookup.py + index.py**(本地大改) | **index.py 自动合;footprint_lookup.py 冲突 △** |
| 11 | `1d48d13c` | wecom_bot_smart | 企微云文档+智能意图路由系统(新 intent_* 中间件) | main_agent.py/graph.py(自动合)、config-answer-draft.md | **config-answer-draft.md 冲突 △**;其余干净 |
| 12 | `d8a0d05d` | wecom_bot_smart | 防活跃任务期间误触会话切分与清理 | wecom_bot_smart/* | 干净 |

> 说明:第 11 号提交同时改了 `config-answer-draft.md`(在 iRule/epolicy 行加"必须生成 epolicy import/attach/class 三条命令"的语义要求),与本地整体英化冲突(见 §五)。

---

## 四、可安全整合清单(零冲突,**待树干净后由主协调执行**)

### 4.1 仅远端改、本地未碰 —— 34 个文件可干净带入
- **整个 `wecom_bot_smart/` 子系统(13 文件)**:`artifact_registry/artifact_schema/config/doc_tool/files/gateway/main/presentation/registry/report_schema/report_tool/tools` + `tests/wecom_bot_smart/__init__.py`。本地零参与,纯功能新增,**建议整体带入**(需 `pip install wecom-aibot-sdk` 等新依赖,合入前核对 requirements)。
- **意图路由新中间件**:`middleware/intent_gating.py` / `intent_router.py` / `intent_routing.py` / `runtime_permission.py`(commit 1d48d13c)。**注意**:它们经自动合并后的 `main_agent.py`/`graph.py` 挂载——合入后需**人工核对注册接线**与本地对这两文件的改动是否协调(文本无冲突≠语义无碍)。
- **文档/报告 agent**:`doc-writer.md` / `document-author.md` / `report-generator.md` + `skills/doc-authoring/SKILL.md` / `skills/report-gen/SKILL.md`。
- **footprint 其余**:`footprint/__init__.py` / `reconcile.py` / `router.py`(注:`index.py` 属"双方都改但自动合干净")。
- **其它**:`streaming.py`(2e0c564c 去重修复,本地未碰)、`tui/cli.py`+`tui/footprint_command.py`、`tools/_shared/metadata.py`、`tools/wx_send_file.py`、`knowledge_paths.py`、`scripts/maintenance/footprint_backfill.py`、`scripts/MCP/.env.example`、`tests/ist_core/memory/test_footprint_index_scan_root.py`。

### 4.2 ★ 强烈建议的定向 cherry-pick:`a7296da8`(command_builder IP 引号 bugfix)
- **实证**:本地 HEAD `command_builder.py:134` 的 `_format_value` **仍是带 bug 版**——触发字符集含 `-`、`.`,会把 IP(如 `10.0.0.100`)、负数、含短横线的值错误加引号,生成非法 CLI 命令。本地对该文件的改动(+30/-19)在**其它区域**,该 bug 行未修。
- **远端修法**:移除 `-`/`.` 触发字符 + 新增 IPv6 识别(`_IPV6_RE`)避免对 `:` 误引号。
- **为何安全**:`git merge-tree` 判定 command_builder.py **自动合并干净**(区域不重叠),本地为准原则下这是纯增益、无覆盖。
- **为何高价值**:`build_command` 是编译链/config-answer 生成 APV 命令的核心;此 bug 直接污染带 IP 参数的产出命令。**建议随 origin/main 合并一并带入,或单独 cherry-pick `a7296da8`。**

### 4.3 8 个"双方都改但自动合并干净"的核心文件
`_prompt.py` / `main_agent.py` / `graph.py` / `footprint/index.py` / `skills/loader.py` / `ask_user/__init__.py` / `command_builder.py` / `tests/…/test_footprint_lookup_fuzzy.py` —— git 三方合并可自动完成。**合入后建议跑一次全量回归**(`~/.venvs/infotest-engine/bin/python -m pytest tests/ -q`)确认语义无碍。

---

## 五、冲突处置方案(以本地为准)

`git merge-tree --write-tree`(纯内存,零工作树改动)判定真冲突仅 **2 文件**,均为本地**已提交**内容(非脏文件),不影响多队进行中的未提交修改。

### 冲突 1 · `main/ist_core/agents/config-answer-draft.md`
| 侧 | 改了什么 |
|----|---------|
| 远端(1d48d13c) | 仅 iRule/epolicy **1 行**增语义:"不准只保存文件,必须 `build_command` 生成 epolicy `import script` / `attach script` / (用 Class 时)`class` 三条命令"(保持中文) |
| 本地(HEAD) | 遵循 CLAUDE.md 语言分层(LLM-facing agent md → 英文),**将整份文件从中文翻译为英文**,恰好覆盖同一行 |

- **本地保留理由**:语言分层是 2026-07-09 用户全仓裁决,英化必须保留。
- **处置(本地为准 + 嫁接语义)**:以本地英文版为基座;把远端新增的 **epolicy 三命令生成要求**译成英文补进对应行——**语言取本地、语义取远端**,两者不矛盾,勿因英化而丢失该功能要求。

### 冲突 2 · `main/ist_core/tools/knowledge/footprint_lookup.py`
| 侧 | 改了什么 | 规模 |
|----|---------|------|
| 远端(49d87c68) | `kb_footprint` 加 `version` 参数 → `_version_to_nodes_subdir` 走 `nodes_{v}` 子目录,cache_key 与 `_kb_footprint_compute` 全程带 `nodes_subdir` | +19/-8 |
| 本地(HEAD) | 自愈合模糊查询大改写(改 `kb_footprint`/`_kb_footprint_compute` 签名与计算逻辑) | +97/-36 |

- **本地保留理由**:自愈合模糊查询是本地编译引擎在跑的核心能力,改写量 97 行,为主线。
- **处置(本地为准)**:以本地改写版为基座**照单保留**;远端 `version`/`nodes_subdir` 是**可选的加法特性**,若团队需要按版本索引 footprint,需人工在本地改写后的 `_kb_footprint_compute` 计算路径上**重新嫁接 version 参数穿透**(非自动可合)。若暂不需要,可先不带入,后续按需补。

---

## 六、其余远端分支盘点(gh 未安装,用 ahead/behind 推断)

| 分支 | vs origin/main(main领先/该分支领先) | 判定 |
|------|:---:|------|
| `devin/*` ×4(error-handling / security-audit / dedup-utils / add-unit-tests) | 62-63 / **0** | 已并入 main,无需处理 |
| `refactor/naming-tool-governance`(远端) | 87 / **0** | 已并入 main,无需处理 |
| `fix/download-list-skip-dotfiles` | 107 / 1 | 单提交未合;本地已有下载/隐藏文件处理等价能力,判**被取代**,低优先 |
| `fix/download-notify-trigger` | 108 / 1 | 同上(下载提醒挂 snapshot done),判**被取代** |
| `fix/loop-guard-and-upload-download-signals` | 109 / 1 | 本地 CLAUDE.md 已落地死循环护栏+上传下载信号,判**被取代** |
| `wangjuan`(本次 fetch 刚更新 `1e0e1628..ef7dce5a`) | 22 / **9** | auth/session 新包,**正交独立特性**,非本次整合范围,后续自行 rebase |

> 3 个 `fix/*` 若确认为历史 PR,建议主协调逐一 `git show` 核对是否真被本地取代后再关闭,避免误判丢功能。

---

## 七、执行边界与交接

- 本报告**未执行任何 cherry-pick / merge / checkout**——工作树脏(多队进行中),任何整合动作可能触发冲突中断并危及未提交修改。
- 交接主协调(树干净后):
  1. `a7296da8` command_builder bugfix——优先带入(修本地现存缺陷)。
  2. `wecom_bot_smart/` 子系统 + intent 中间件——整体带入,核对新依赖与 main_agent/graph 接线。
  3. origin/main 整体并入本地时,只需人工解 §五 2 个冲突(本地为准),其余自动合;合后跑全量 pytest。
  4. 本地领先 131 提交待 push。
- 所用命令全为只读:`git fetch/log/show/diff/rev-list/merge-base/merge-tree/ls-remote`;`merge-tree` 为内存态模拟,证实"仅 2 冲突"且零工作树副作用。
