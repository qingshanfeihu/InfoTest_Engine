# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 语言要求

所有回复必须使用中文。

## 项目目标

本项目展示名为 **InfoTest Engine**，agent 核心展示名为 **IST-Core**。当前代码路径、graph id、工具名前缀、Qdrant 集合名和环境变量仍保留历史兼容名（如 `main.qa_agent`、`qa_agent`、`qa_*`、`ultra_agent_vectors`、`ultra_agent_qa`），除非另有迁移计划，不要改这些运行时标识。

InfoTest Engine 将技术文档（网络 / IPv6 / HTTP/2 / 网关配置指南等）通过 MinerU 解析 → trunk 装箱 → LLM 特征抽取，结构化输出到 Qdrant 向量库（本地 podman 部署），并通过 IST-Core 提供只读测试分析、测试资产理解和 LangGraph RAG 能力。

## 常用命令

```bash
# 安装依赖
pip install -r requirements.txt

# 启动本地 Qdrant（一次性）
podman machine start
podman run -d --name qdrant_ultra -p 6333:6333 -p 6334:6334 \
  -v C:/SynologyDrive/Project/ultra_agent/qdrant_storage:/qdrant/storage:Z \
  --user 0:0 --restart unless-stopped \
  docker.m.daocloud.io/qdrant/qdrant:latest
curl http://localhost:6333/healthz

# 完整管线（按顺序执行）
python -m main.mineru_batch_export           # 1. orgin/ → MinerU 解析 → mineru/
python -m main.mineru_merged_pre_data        # 2. 合并 → data/preset_input_data.json
python -m main.mineru_pre_data_clean         # 3. 清洗 → data/{stem}.input_data.json
python -m main.mineru_trunk_merged           # 4. 装箱 → merged/{stem}.trunk.json（含 release_status / unit_kind_override）
python -m main.function_trunk_create         # 5. 特征抽取 → features/{feature_id}.feature.json

# 索引
python -m main.index_all                     # 6. feature + trunk + QA → Qdrant 向量库
python -m main.migrate_to_qdrant             # 一次性全量回灌（含 count 汇总）

# RAG
python -m main.mix_rag.runner "如何配置 HTTP/2 SLB？"
python -m main.mix_rag.runner --interactive
python -m main.mix_rag.runner --qa-only "如何测试DNS64功能"

# IST-Core — 服务控制（推荐用 PowerShell 管理脚本，PID 存 .langgraph_api/）
.\tests\qa_agent_backend.ps1 -Action start    # LangGraph dev server (2024，--no-reload 避免 watchfiles 死循环)
.\tests\qa_agent_ui.ps1       -Action start   # agent-chat-ui (默认 4000；3000/3100 在 Windows Hyper-V 保留范围)
.\tests\qa_agent_backend.ps1 -Action status   # 查 PID
$env:UI_PORT = "5000"; .\tests\qa_agent_ui.ps1 -Action start  # 自定义端口
# 直接 CLI 等价：.venv311/Scripts/langgraph dev --no-browser --no-reload --port 2024

# 冒烟专用 Reviewer（多轮对话 + LLM 真调，约 5 min）
.venv311\Scripts\python.exe -m scripts.debug.probe_main_agent_multiturn

# E2E 评审回归（cookie 121100 套件 → 9 项人工标准比对，约 3-6 min）
# 输出 logs/e2e_v2/<utc>__<tag>/{audit.json, events.jsonl, verdict.md, diff.json}
# baseline 锁在 tests/qa_agent/fixtures/cookie_121100_baseline.txt（当前=5）；exit 2 = 回退
.venv311\Scripts\python.exe -m scripts.debug.e2e_cookie_review_v2 --tag <fix_name>

# 一次性数据修复（仅 http2 系列）
python -m main.fix_http2_deferred --apply

# 禁用进度条（非 TTY 环境）
NO_PROGRESS=1 python -m main.function_trunk_create
```

## 关键架构决策

- MinerU 原始数据全量保留，不直接进入下游（LLM / 向量库）
- 数据经过清洗 / 预结构化 → trunk 装箱 → LLM 结构化抽取后，才进入 Qdrant 向量库
- 管线拆分为独立步骤，每步可独立复跑（hash 缓存：`knowledge/data/.cache.json`）
- feature / trunk 共用同一 Qdrant 集合，以 `doc_type=feature_json` / `doc_type=trunk_unit` 区分；QA 单独一个集合
- Qdrant payload 无 schema 锁，新增 metadata 字段无需重建集合（这正是从 Astra 迁移的核心收益）
- CLI 命令面的幻觉抑制采用**三层闸门**（详见 ARCHITECTURE.md）：
  - L1 生成侧（`rag_graph._sanitize_cli_result` + `RAG_GENERATE_CLI_SYSTEM` allowlist）
  - L3 上游（`mineru_trunk_merged` 打 `release_status` + `function_prompts.EVIDENCE_RULES`）
  - L4 数据层（`function_evidence.verify_cli_commands` + `function_schema.validate_feature`）

## 专用 Reviewer hierarchical pipeline 架构（R0.6 最终状态）

R0.5 把 R1-R7 的"语义检索 + 流水线 + 硬编码兜底"老范式重写为 **三阶段 hierarchical pipeline**；R0.6 在框架层完成 cc-haha + langchain deepagents 范式补全（13 项 F1-F13），sub_agent 真正变成"研究员 agent"——能 read_file / grep / ls 直接读项目文件，多轮反思，coordinator 中介协作。

### 三阶段 pipeline（`main/qa_agent/agents/hierarchical/`）

```
review_node / qa_invoke_reviewer
  ↓
scope_graph.run_scope（HIL 检测 + 反向依赖追问规则引擎 + R0.6 数据 hop + CrossRefMatrix 构造）
  ↓
research_graph.run_research（asyncio.gather 并行 spawn 4 物理隔离 sub_agent）
  ├─ coverage_analyst (D1/D3/D5)：file tool + qa_search_assets
  ├─ baseline_auditor (D2/D7/D8)：file tool（自己 read baseline_context page_content）
  ├─ spec_checker (D4/D6/D10)：file tool + qa_search_product_kb
  └─ architecture_analyst (D9 + 反向架构)：file tool + qa_search_product_kb + qa_search_knowledge_ref
  ↓
write_graph.run_write（反方 LLM challenge round：找 D2/D6/D7/D10 漏洞）
  ↓ challenge.retry_research=True
coordinator.coordinator_synthesize（R0.6 F4：1 次 LLM call 综合判断 → retry_targets[{sub_agent, focus_dims, synthesized_prompt}]）
  ↓ retry_executed
research_graph.run_research(retry_target_names=..., retry_synthesized_prompts=...)（同 thread_id 续跑，仅被挑战 dim 覆盖）
  ↓
audit.json + meta._hierarchical_trace + meta._challenge_round + meta._coordinator_synthesize + meta.sub_agent_returns
```

### 关键技术栈（R0.6 升级）

- **deepagents 0.5.7** 完整范式接入：`create_deep_agent` + `FilesystemPermission` (read-only 白名单 knowledge/ + review_inputs/) + `response_format=SubAgentReturn` 强制结构化输出 + `checkpointer=InMemorySaver` 让 thread_id 续跑
- **langgraph BaseCallbackHandler** per-agent telemetry（token / tool_calls / elapsed），仿 cc-haha `<task-notification>/<usage>` 格式
- **百炼 OpenAI 兼容端点**（`QA_AGENT_FALLBACK_MODEL=openai:qwen-plus` → DashScope `compatible-mode/v1`）—— PoC 验证支持 Pydantic response_format
- **PreAnalysisInjectionMiddleware** —— D6/D7/D10 程序化预分析事实通过 system_message 注入（取代 R4-R7 事后 enforcer overlay）
- **SkillAssembler + 15 fragments** 按 sub_agent 切片（`SUB_AGENT_PROMPT_SLICES` in `prompt_slices.py`）
- **数据驱动 sub_agent 配置** —— `sub_agent_definitions/{name}.py` 各导出 `build()` 返回 deepagents.SubAgent dict + ultra_agent 扩展字段（`_owned_dims` / `_max_iters` / `_cross_ref_slices` / `_vector_tools`）
- **CrossRefMatrix** scope 阶段构造测试 ↔ 产品 ↔ 缺陷 7 子表（cli_coverage / parameter_coverage / baseline_subscene_anchored / requirements_coverage / constraints_check / dependencies_check / bug_fix_cli_coverage），按 `_cross_ref_slices` 切片注入 sub_agent
- **fixture LLM-as-judge** —— substring 命中跳 LLM 节省成本；substring miss 才调 LLM 做语义评分

### R0.6 13 项框架补全（F1-F13）

| F# | 内容 |
|---|---|
| F1 | SubAgent 数据驱动配置（4 个 `sub_agent_definitions/{name}.py` + REGISTRY） |
| F2 | build_sub_agent 用 `create_deep_agent` 默认挂全套 atomic file tool（read_file/grep/ls/glob/read 等），FilesystemPermission read-only 白名单 |
| F3 | recursion_limit 调到 50 + cc-haha Explore agent 风格的研究员 prompt 引导 + 收敛规则（"读过 1 个 feature.json 全文" / "12+ 工具调用强制收敛"） |
| F4 | Coordinator synthesize 层（仿 cc-haha coordinatorMode），challenge retry_research=True 触发 1 次 LLM call → retry_targets → 续跑 |
| F5 | langgraph checkpointer + thread_id 续跑（`{case_id}__{sub_agent_name}`），retry 时同 thread_id messages 自动累积 |
| F6 | scope 数据 hop（ScopePayload 加 `defect_fix_summary` / `confirmed_feature_ids` / `change_type`）+ 修 review_input 顶层 case_id 缺失（兜底 case_draft.case_id）+ 把 hop 字段注入每个 sub_agent extra_context（含 `bug_fix` 范围收敛说明） |
| F7 | DIM_OWNERS 从 REGISTRY._owned_dims 派生 + D4 加入 spec_checker + research_graph merge 后 D1-D10 全 N/A 兜底（Rule e 永远 ✓） |
| F8 | SubAgentReturn Pydantic 作 deepagents.response_format（自动结构化输出，删 `必须末尾 ```json``` 块` 强约束）；保留行为引导 + 禁令（禁 `[REF:auto_corrected:*]` / 禁 "【程序化判定】" 句式 / 禁编造 REQ/BL/CON-id） |
| F9 | per-agent telemetry —— SubAgentTraceHandler(BaseCallbackHandler) 在 on_llm_end / on_tool_end 累加；run_sub_agent 把 trace 塞 `SubAgentReturn.structured_data['_telemetry']` |
| F10 | `_collect_scope_refs` 加 case_id (顶层+case_draft 兜底) / feature_cards.feature_id / 派生 *.feature.json / REQ/BL/CON/BEH/UC ID / change_context.related_ids；新增 `_collect_subagent_refs` 抽 sub_agent.raw_sources_consulted；valid_refs 三路合并；`_SAFE_ANCHOR_PREFIXES` 加 章节路径 / case_draft.* / test_data.* / baseline_context.* 等合法引用 |
| F11 | 删 ARCHITECTURE.md L555-575 R4-R7 enforcer 表 + AGENTS.md L156 auto_corrected 描述 + pre_analysis_middleware.py 注释"程序化判定"→"程序化预分析事实" |
| F12 | CrossRefMatrix（`hierarchical/cross_ref.py`），scope 阶段 build_cross_ref_matrix，sub_agent 按 `_cross_ref_slices` 拿对应子表切片 |
| F13 | feature_cards 摘字段从 9 → 18（加 verification/observability/troubleshooting/security/version_scope/known_issues/workflows/capabilities/scope/tags）；每个 sub_agent 切 suite_summary 17 字段（observed_cli_templates / parameters / test_areas / extracted_keywords / cli_commands_found / section_categories / text_subscene_signal_global 等按责任分配；旧 subscene_global_coverage 仅兼容） |

### 生产配置

- `QA_AGENT_FALLBACK_MODEL=openai:qwen-plus`（DashScope OpenAI 兼容端点，PoC 验证支持 Pydantic response_format）
- `DASHSCOPE_API_KEY`（必填）/ `BAILIAN_API_KEY`（兼容别名）
- 不要污染 cc switch / claude code router 本地代理（`memory/feedback_production_llm_endpoint_no_cc_switch.md`）

### 关键文件

| 模块 | 文件 |
|---|---|
| 三阶段编排 | `main/qa_agent/agents/hierarchical/{__init__, scope_graph, research_graph, write_graph, supervisor, payloads, challenge, prompt_slices, coordinator, cross_ref, telemetry}.py` |
| 4 sub_agent | `main/qa_agent/agents/hierarchical/sub_agents/{__init__, _base}.py` |
| sub_agent 配置 | `main/qa_agent/agents/hierarchical/sub_agent_definitions/{coverage_analyst,baseline_auditor,spec_checker,architecture_analyst}.py` + `__init__.py` REGISTRY |
| reviewer 入口 | `main/qa_agent/tools/reviewer/invoke.py`（含 `_resolve_feature_cards_into_meta` 18 字段提取 + `_collect_scope_refs` / `_collect_subagent_refs` valid_refs 三路合并） |
| LLM 工厂 | `main/qa_agent/agents/_llm.py`（OpenAI 兼容端点优先） |
| Fragment 装配 | `main/qa_agent/agents/_prompt_assembler.py` + `skills/Review_Checklist/manifest.yaml` + 15 fragments |
| Pre-injection middleware | `main/qa_agent/agents/pre_analysis_middleware.py` |
| LLM-as-judge | `tests/qa_agent/fixture_judge.py` + `scripts/debug/e2e_cookie_review_v2.py` |
| R0.6 PoC 单测 | `tests/qa_agent/test_r06_deepagents_poc.py`（验证 deepagents 多 SubAgent 并发性 + Pydantic response_format on DashScope） |

### R0.6 KPI 验证（cookie 121100 套件）

- elapsed=4 min（vs R0.5 ~70s）；token 约 10-20 倍涨——成本与质量已确认接受的权衡
- 4 sub_agent 累计 **45 次** read_file/grep/ls/glob 调用（cc-haha 研究员范式真落地）
- D1-D10 全 10 维度齐全（含 D4，缺失维度走 `[REF:no_owner_fallback]` 兜底）
- coordinator 触发 retry round（2 targets，retry_executed=True）
- evidence 不含 `[REF:auto_corrected:*]` 幻觉
- LLM-as-judge **6/9** > baseline=5（语义评分提升），substring 4/9（数据深度限制，符合"框架就位 ≠ 内容提升"预期）

### R0.7 知识补全实现（2026-05-14 已落地；2026-05-15 树语义修正）

R0.7 的方向从“人工写 ontology / 字典”调整为“所有产品知识走 ingest + CLI 图 + scenario/architecture sidecar”，避免把 IPv4/IPv6、HTTP 版本、multi-group 等具体规则硬写进 prompt。

已完成：
- `knowledge/cli_graph/cli_keyword_graph.json` 已移植；`main/knowledge/cli_graph_store.py` 提供 `command_exists` / `resolve_label_to_nid` / `extract_subgraph` / overlay mutation。运行时不覆盖 base graph，只写 overlay / effective graph。
- `main/knowledge/cli_graph_store.py` 增加 `parse_cli_syntax()`，结构化识别 conceptual command、参数、枚举动作值和 `no/show/clear` 操作前缀；`on/off/enable/disable` 不作为树节点。
- `main/mineru_trunk_merged.py` trunk schema 升 v3，unit/trunk 写入 `tree_level` / `linked_node_ids` / `similar_nodes` / `confidence` / `root_candidate` / `graph_gap` / `candidate_leaf` / `cli_syntax`。
- `main/function_trunk_create.py` 透传 tree/anchor 元数据：unit capsule → mapping → selected trunk → context locator → feature.json → cache manifest；feature schema 升 `1.1.0`，cache manifest 升 v2。
- `main/function_trunk_create.py` 默认过滤测试知识源；`root` 只允许文档级架构源升级，普通 design/spec/bug 的 Data Flow / Function List / Data Structure 不再作为 root。
- `main/function_farm_owner.py` 支持 `graph_gap` / `candidate_leaf` 批量裁决、snapshot、overlay 写入和 `knowledge/.schema_gaps.jsonl`；兼容旧函数名但主路径不再使用 `new_leaf`。
- trunk/root cluster 仍走 11 批 feature 抽取主路径，同时额外生成 `knowledge/scenarios/` 与 `knowledge/architecture/` sidecar。
- `knowledge/architecture/*.architecture.json` schema v2 增加 `os_runtime_model` / `memory_model` / `threading_model` / `io_model` / `architecture_decisions`，只从 root 架构证据综合。
- `main/indexing_payload_fields.py` 集中维护 Qdrant payload index 字段；feature/trunk/scenario/architecture 共用 `tree_level` / `linked_node_ids` / `cli_graph_anchors`。
- `main/index_all.py` 增加 scenario/architecture 增量索引和 `knowledge/knowledge_base.json` 骨架生成。
- sub_agent 新增 5 个工具：`qa_command_exists`、`qa_search_architecture`、`qa_search_scenario`、`qa_search_by_cli_anchor`、`qa_get_sibling_features`，已完成 4 处注册。
- reviewer lint 增加 self-consistency 降级、REQ/BL/CON 引用真实性、`cmd:` CLI 图校验；`QA_REVIEW_LINT_ENABLED=0` 可关闭。
- R0.7 单测已加入：`tests/test_cli_graph_store.py` + `tests/r07/`。

产品树约束：
- 仅允许 `root | trunk | branch | leaf`；`new_leaf` 已废弃，CLI 图缺口是 `leaf + graph_gap/candidate_leaf`。
- `trunk` 是产品能力主干，可跨多个 CLI module/submodule；不要把 CLI 第一段硬当 trunk。
- `branch` 是产品能力子树，不是固定 token 位置。
- `leaf` 是最小可验证能力；`no/show/clear` 挂到对应 leaf，`on/off/enable/disable` 是参数/动作枚举。
- 测试知识库与产品知识树分离；测试策略、测试列表、用例、结果、baseline 不能进入产品树。

待运维 / 端到端验证：
- `scripts/r07/check_ingest_gaps.py --json` 当前报告 28 个源文档缺少完整 ingest 产物，需按 MinerU quota 分批处理后再跑全量质量门。
- `scripts/r07/quality_inspector.py` 已实现阻断式结构质量门；当前会因上述缺口 blocked。
- 未运行长耗时 cookie 121100 三次 E2E audit；代码层验证命令见 `tests/README.md` 的 R0.7 小节。

### 工具目录结构（按模块分组）

```
main/qa_agent/tools/
  product/search.py       — 产品 KB 检索
  defect/                 — 缺陷搜索 / 抓取
    search.py / fetch_direct.py / fetch_on_demand.py / cache.py
  asset/search.py         — 测试资产 KB
  knowledge/              — RFC / 参考资料
    ref_search.py / web_search.py / cli_command.py / architecture_search.py /
    scenario_search.py / cli_anchor_search.py / sibling_features.py
  baseline/load_rules.py  — 测试基线规则
  pipeline/               — ingest / scope / run / check_updates / summarize
  reviewer/               — invoke / invoke_async / check_status / resume / cancel / read_large_result / trace_change
  _shared/                — metadata / orchestration / shared / text_sanitizers / web_search / defect_helpers
```

@tool 装饰器的 `name=` 字符串保持原样（如 `qa_invoke_reviewer` / `defect_search_kb`），review_inputs/*.json 历史 tool_calls 引用兼容。

## main 子包结构

旧扁平 import（`from main.xxx import ...`）与新 canonical 子包路径**并存**；新代码优先使用子包路径：

| 子包 | 职责 | canonical 模块 |
|------|------|--------------|
| `main.common`    | 通用工具与外部依赖封装 | paths / env / qwen / vector_store / utils / progress / cli_commands / release_markers |
| `main.ingest`    | MinerU → 清洗 → trunk；HTML 抓取（Bugzilla / 禅道） | batch_export / merged_pre_data / pre_data_clean / trunk_merged / defect_fetch / defect_parse / html_extractors/ |
| `main.extraction`| feature 抽取 pipeline | discover / assemble / extract / evidence / schema / prompts / llm / cli_param_repair / pipeline |
| `main.indexing`  | Qdrant 向量索引 | feature_index / trunk_index / defect_index / test_asset_index / baseline_index / requirement_index / code_change_index / index_all |
| `main.rag`       | 基础 RAG 运行时 | state / prompts / tools / graph / runner + nodes/{understand,retrieve,grade,rewrite,load,generate} |
| `main.qa_agent`  | **v1.4-v1.7 对话式评审 Agent**（对接 agent-chat-ui）| graph / runner / server_graph / state / schemas / events + agents/{main_agent, reviewer_agent, _llm} + tools/ × 13 + sinks/ |

## IST-Core 兼容子包（`main/qa_agent/`）

对话式测试评审 Agent，通过 `agent-chat-ui` + `langgraph dev` 暴露 HTTP API。

### 工具清单（15 个 LangChain `@tool`，按模块分组）

挂在 IST-Core（历史 `main_agent` 入口）上，用户在 InfoTest Chat UI 自由对话触发。物理目录见"专用 Reviewer hierarchical pipeline 架构"一节。

**产品 / 资产 / 缺陷 / 知识检索（7 个）**：
- `qa_search_product_kb`（`tools/product/search.py`）— 产品 feature + trunk，走 `ultra_agent_vectors`
- `qa_search_assets`（`tools/asset/search.py`）— `ultra_agent_qa` 的 test_case/test_spec + qa_trunk_unit；合并去重 + 同源折叠
- `defect_search_kb`（`tools/defect/search.py`）— `ultra_agent_vectors` 的 bug + plm_ticket
- `defect_fetch_on_demand`（`tools/defect/fetch_on_demand.py`）— Playwright 按需 WebVPN 抓；hybrid fallback：zentao,bugzilla；对外三态 cache | fetch | not_found
- `qa_search_knowledge_ref`（`tools/knowledge/ref_search.py`）— RFC / OSI / Linux 手册；本地 Qdrant miss 直接返回"（无召回）"；topic 22 alias → 5 基础 topic
- `qa_web_search`（`tools/knowledge/web_search.py`）— 独立联网检索；DuckDuckGo + 域名白名单（IETF/W3C/ISO/NIST/kernel/man7）；每 turn ≤ 3 次
- `qa_trace_change`（`tools/reviewer/trace_change.py`）— 跨通道 bug/req/commit 追溯

**评审编排（5 个）**：
- `qa_check_origin_updates`（`tools/pipeline/check_updates.py`）— 扫 orgin vs `.cache.json` + `qa_raw/`，返回待 MinerU / QA 管线文件
- `qa_ingest_test_list`（`tools/pipeline/ingest.py`）— xlsx → suite summary + review_input JSON 落盘
- `qa_run_pipeline`（`tools/pipeline/run.py`）— subprocess 跑 `qa_only`/`mineru_only`/`full` 管线
- `qa_invoke_reviewer`（`tools/reviewer/invoke.py`）— 三阶段 hierarchical pipeline 入口（scope → research 4 sub_agent 并行 → write + challenge round）
- `qa_load_baseline_rules`（`tools/baseline/load_rules.py`）— 按测试分类拉基线

**异步任务 + 续跑（3 个）**：
- `qa_invoke_reviewer_async` / `qa_check_review_status` / `qa_cancel_review`（`tools/reviewer/{invoke_async,check_status,cancel}.py`）— chat UI 首选，长评审后台跑
- `qa_resume_pending_review`（`tools/reviewer/resume.py`）— HIL 续跑意图识别
- `qa_read_large_tool_result`（`tools/reviewer/read_large_result.py`）— LangGraph 截断大结果的兜底读取

### IST-Core 兼容 Skill（`skills/Product_QA/`，SkillAssembler 装配）

main_agent 的意图路由 + 评审编排流程：

1. 意图识别：通用平台任务类型由 LLM 路由 / agent directive / tool description 共同决定；不要在工具或 runtime 里新增 `any(token in text)` 这类关键字硬编码。xlsx 路径、"评审" 等只能作为模型输入线索，不是程序分支事实。
2. 评审编排步骤：
   - Step 2: `qa_check_origin_updates(keyword=<主题>)`
   - 若 `recommendation=ask_user` → 回复用户选 yes/no（对话自然断点）
   - Step 3（用户同意）：`qa_run_pipeline`
   - Step 4: `qa_ingest_test_list` + Step 5: `qa_invoke_reviewer` 必须同一 turn 连续调
   - Step 6: 按固定 markdown 模板回复（**关键发现** + **建议改进** + **待产品/研发确认项**）

### 专用 Reviewer（`main/qa_agent/agents/reviewer_agent.py`）

- `create_deep_agent` 构造（deepagents 0.5.7+），挂 4 个 subagent：`qa_defect_tracer`、`qa_coverage_dedup`、`qa_baseline_auditor`、`qa_theory_advisor`
- `SkillAssembler.from_dir(skills/Review_Checklist)` 装配 fragment；payload_ctx 驱动条件渲染 + baseline_subscene_text_signal（旧 baseline_subscene_coverage 仅兼容）/ feature_cards 模板插值
- 事实模型分层规则见 `memory/feedback_generic_platform_fact_model.md`：作者声明字段、文本启发式线索、LLM 评审结论必须分层命名和使用，不能把 `Test Types=Boundary/Negative` 当成真实覆盖证据。
- 挂 `FilesystemBackend(virtual_mode=True)` 让 deepagents atomic tools（read_file/grep/ls）映射到真实磁盘
- 挂 `PreAnalysisInjectionMiddleware` 把 D6/D7/D10 程序化预分析事实注入到 system_message
- Skill 有 suite 模式分支：`case_id` 以 `SUITE-` 开头时 D1 → 章节树合理性 / D7 → 套件级基线子场景核对；文本线索未命中只是候选缺口，不能直接当覆盖缺失。

### 服务入口

- `main/qa_agent/server_graph.py` → `langgraph.json` 指的 graph_id=`qa_agent`
- `main/qa_agent/runner.py` → CLI 入口 `python -m main.qa_agent.runner --task review --input xxx.json`

## 核心模块

| 文件 | 职责 |
|------|------|
| `main/utils.py` | 共享工具：JSON I/O、原子写入、SHA256 哈希、UTC 时间戳 |
| `main/knowledge_paths.py` | 路径常量 + `source_authority()`（L5 权威度：cli_* > app_* > APV_*spec > Design_Doc） |
| `main/langchain_env.py` | 根目录 `environment` 加载（`langchain_load_dotenv_if_present`） |
| `main/langchain_qwen.py` | LangChain `ChatTongyi`（`langchain_create_chat_tongyi`） |
| `main/langchain_qdrant.py` | Qdrant VectorStore（默认百炼 embeddings；payload index 替代 Astra include 列表） |
| `main/function_llm.py` | DashScope qwen-plus 聊天客户端（3 次指数退避，处理 429） |
| `main/function_schema.py` | feature schema 校验、ID 规范化；**L3 新增** `cli.commands[]` release_status / reverse 对称 / sample_cli 回溯校验 |
| `main/function_prompts.py` | 11 批次（B01–B11）prompt 构建器；**L3 新增** EVIDENCE_RULES 的 deferred / template_placeholder 规则 |
| `main/function_evidence.py` | evidence 校验与 patch；接受阈值 0.85，自动修复阈值 0.48；**L4 新增** `verify_cli_commands`（CLI 命令 substring / reverse 对称） |
| `main/terminal_progress.py` | 单行刷新进度条（daemon 线程，线程安全，`NO_PROGRESS=1` 降级） |
| `main/cli_command_utils.py` | **新增**：CLI 命令字符串工具（L1/L3/L4/L5 共用） |
| `main/release_status_markers.py` | **新增**：trunk 文本的 deferred / template_placeholder 识别（L3） |
| `main/fix_http2_deferred.py` | **新增**：一次性数据修复脚本（清洗 5 个 http2 feature.json） |

### `mineru_pre_data_clean.py` 清洗规则（filter_schema_version: 7）

处理顺序：TOC 跳过 → 列表过滤 → 页眉页脚跳过 → 图片跳过 → 文本提取 → 图片标记剥离 → 厂商过滤（华为）→ 合并 → 分块（max 1000 chars）→ 语义去重（cosine ≥ 0.9）

质量标签：`short_fragment`（≤48 chars）、`garble_ratio`（≥0.08）、`is_quarantined`

### `mineru_trunk_merged.py`（trunk_schema_version: 2）

- 按 title 划 section，以 merged 段为原子做 min/max 贪心打包
- **L3 新增**：基于 `release_status_markers.classify_text` 标记 `release_status` / `unit_kind_override`
  - 遇到 "will not (be )?included in X release" / "deferred" / "out of scope" / "not supported in phase" / "future release" / "TBD" → `release_status=deferred`
  - 遇到 "Click here to input..." / "[This section should cover..." / "Note: ... should be provided" 等 Word 模板残留，且出现在 trunk 前 30% → `unit_kind_override=template_placeholder`

### `function_trunk_create.py` 特征提取流程

- Step 0：特征发现（unit-capsule 驱动 + LLM 关联）
- Step 0.5：特征细化（过宽拆分）
- Step 0.7：未覆盖 stem 补录
- Step 1：按特征组装上下文（`assemble_feature_context`，locator JSON 含 L3 `release_status`；template_placeholder unit 不送 LLM）
- Step 2：并发分段 LLM 抽取（11 批次，最多 5 批并发）
- Step 3：evidence 验证 + 自动修复提案（含 L4 `verify_cli_commands`）
- Step 4：ID 规范化、schema 校验（含 L3 reverse 对称 / sample_cli 回溯）、门控输出

## Token 安全

- `MINERU_TOKEN`、`DASHSCOPE_API_KEY`、`QDRANT_HOST` 通过项目根目录 `environment` 文件注入（`KEY=value`）；脚本使用 `python-dotenv` 加载（不覆盖已存在的环境变量）
- `mineru_pre_data_clean` 与 `function_trunk_create` 必须配置 `DASHSCOPE_API_KEY`；缺失则非零退出
- `environment` 已在 `.gitignore`；模板为 `environment.example`
- 禁止在代码、注释、日志中打印 Token 或 API Key

### 可选环境变量（IST-Core 行为开关）

- `QA_WEB_FALLBACK_ENABLED`（**v1.7 deprecated**，已无效果）— 历史值用于 `qa_search_knowledge_ref` 内部 DDG fallback 开关；v1.7 起 fallback 已移除，保留变量名仅为向后兼容
- `QA_WEB_FALLBACK_REGION`（默认 `wt-wt`）— DDG 区域（仍由 `qa_web_search` 内部使用）
- `QA_WEB_FALLBACK_CACHE_MAX` / `QA_WEB_FALLBACK_CACHE_TTL_S`（默认 128 / 600s）— 联网结果 LRU（`qa_web_search` 共用）
- `QA_WEB_SEARCH_REPEAT_LIMIT` / `QA_WEB_SEARCH_REPEAT_WINDOW_S`（默认 2 / 600s）— `qa_web_search` 同 query 重复调用上限
- `CAPTCHA_OCR_RETRY`（默认 10）— `defect_fetch_on_demand` 自动 refresh_login 时的验证码识别重试次数

## 技术栈

- Python 3.11+（`deepagents>=0.5.3` 强约束），`requests`，`python-dotenv`，`langchain` ≥ 1.2.15，`langgraph` ≥ 1.1
- 推荐用 `py -3.11 -m venv .venv311` 建本地虚拟环境；激活后 `pip install -r requirements.txt`
- MinerU 精准解析 API（`https://mineru.net/api/v4/`）
- DashScope OpenAI 兼容端点：embeddings（`text-embedding-v4`，1024 维，批大小 10）+ chat（`qwen-plus`）
- Qdrant（本地 podman 部署，HTTP 6333）；feature/trunk 集合 `ultra_agent_vectors` 共用，QA 集合 `ultra_agent_qa` 独立；payload 字段以 keyword index 提供过滤
