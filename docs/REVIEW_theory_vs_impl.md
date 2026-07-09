# 代码评审：理论文档 ↔ 引擎实现对账（2026-07-09）

> 方法：亲审（本会话全部改动的语义一致性热点 8 项）+ 10 路机械扫描（旧尾块/grade/LangSmith/旧判据/
> 中文漏网/案卷号/信号接线/文档标注/v5 残留/TUI 链路）。共 17 项发现：**12 项已修**（全量门 1381 绿），
> 3 项记录不动（设计内），2 项立项（工作量级）。

## 一、已修（12 项）

| # | 级 | 发现 | 修法 |
|---|---|---|---|
| 1 | S1 | **SKIP 指向死入口**：ist-compile-engine SKILL 的 "engine disabled (fall back to ist-compile)"——`ist-compile` skill 已随 v5 删除，"引擎开关"也不存在（V6 唯一路） | 整句删除 |
| 2 | S1 | **fanout 测试 fixture 用旧尾块** `状态：produced`（6 处）——靠 `_TAIL_RE` 双格式兼容临时存活，过渡期结束删旧格式即测试失效，且它测的正是尾块链路 | fixture 迁 `STATUS:/ARTIFACT:` 新契约 |
| 3 | S1 | batch_tools 两处注释描述尾块为旧**三字段** `状态:/产物:/判定:`（新契约无独立"判定"字段） | 注释同步新契约 |
| 4 | S2 | `_build_brief` docstring 仍写"末轮增强/rounds_used>=max_rounds-1"，实现已是首败即升（>=1）——文档与实现矛盾 | docstring 重写为首败即升语义 |
| 5 | S2 | `_dispatch_one` docstring "升级重编的最后一次传 max" 同上矛盾 | 同步 |
| 6 | S2 | verify_phase/ist_app 三处"升级末轮"注释旧语义 | 同步"重编轮(首败即升)" |
| 7 | S2 | **tool_gating 三方不一致**：docstring 说默认关、实现 `or "1"` 默认开、CLAUDE.md 说默认关 | docstring 对齐实现（默认开，注明 dongkl 对照轮实测后翻默认）；CLAUDE.md 另行同步 |
| 8 | S2 | `observability.py` 引用已删除的 `langsmith_sink`；`langfuse_sink.py` 注释残留 LangSmith 命名 | 注释澄清"该 sink 已删" |
| 9 | S2 | `compile_prep.py` 描述"供 ist-compile 编译链(compile_pipeline)调度"——v5 旧编排描述 | 改"供 V6 编译引擎 prep 节点调用" |
| 10 | S2 | `batch_tools.py:6` docstring "draft / grade"（grade 判官已删） | 改 "worker/attributor fork" |
| 11 | S2 | THEORY §8 仍标"dev_help 归因未接线（缺口 A）"——实际已接线并真机首秀（`cnome` typo 案） | §8 行刷新为 ✅ |
| 12 | S2 | PROMPT_ENGINEERING_STANDARD 旧尾块示例；ist-compile-engine SKILL 的 "LangSmith-verified"（观测已换 Langfuse） | 示例迁新契约；改 "trace-verified" |

## 二、记录不动（3 项，设计内）

13. **信号闭集 17 定义 / 11 接线**：未接的 6 个中，`monotonicity_violation`/`stale_flagged`/`stale_refreshed`/`quarantined` 对应理论 ❌ 缺口 B/C/D——**forward-declared 是一致的**（机制未建，信号自然无触发点）。真漏接 2 个：`observation_group_formed`/`conflict_declared`（机制在 footprint_lookup 渲染层）——**正确接线位置在入库端**（首次形成时发一次），渲染端每次查询会重复发；随缺口 C/D 实施时一并接。
14. **`.grade_credential.json` / `no_grade` 变量名**：活的 lint 凭证机制，文件名/变量名带 grade 历史包袱——改名是 cosmetic 且涉磁盘契约（存量凭证文件），不动。
15. **`compile_pipeline.py` 文件名**：v5 包袱，但只剩 3 个自包含 helper（`_emit_progress`/`_grade_extract_facts`/`_project_root`）被引擎复用，文件头已如实声明遗留性质——迁移是纯搬家，价值低。

## 三、立项（2 项，工作量级）——已收束（2026-07-09 次日批）

16. ~~**B5 残余面——工具返回串英文化**~~ ✅ **已完成**：13 文件全量转换（device 族 7：run_case/batch_tools/fail_attribution/precedent_tools/checker_tool/engine_tool/compile_prep + knowledge 族 5：behavior/command_builder/footprint_lookup/footprint_writeback/memory_search + checkers/rr_hit 的 note 面）。@tool docstring、return 串、指引 append 段全英文化；同步消费方（loop_guard `_EMPTY_MARKERS` 空结果标记、`(no output)` 产消两侧、`.frozen.json` reason 字段）与 ~40 处测试锚。**保留面按纪律**：logger（开发者面）、模块/辅助函数 docstring 与注释（维护者面）、TUI progress 事件（用户面）、数据锚（`自动化ID` 表头、匹配中文手册的正则、footprint/memory 中文数据透传）、代码消费令牌（`[未在文档直接命中]`、ask_user 的「非交互」）。AST 级残余扫描零漏网；顺带清 compile_prep 的 compile_skeleton 死指针与日期引用。全量门 1389+279 绿。
17. **fork 工具结果预览的英文显示**：维持原判——`↳` 预览属"原文引用"性质（同设备回显英文），不加翻译映射层。

## 三·附：P3「C 类文案数据化」按理论裁定收束（2026-07-09）

原立项：emit_xlsx_tool(~100 行)/precedent_tools(两大段说教)/batch_tools 的教学中文 → 判例引用渲染。按 K 理论四层封闭性重新裁定后**不再整批数据化**：

- **A 层门违例文案 = 机制 + 一则实证例**，闭合于框架版本——新的同类坑出现时门已覆盖、文案无需编辑，自愈判据（响应新坑零代码）本就满足；数据化只添运行时间接层，零自愈增益。
- **真正随判例漂移的部分已由 P2-3 完成数据化**：grade_extract 坑叙事运行时从判例现取（`_closure_case_law_note`）、先例策展标注是数据（precedent_annotations.json）、领域枚举走 domain_grammar.json。
- 两大段先例说教（完整基线/格式逐字抄）陈述的是**稳定方法论**而非增长型判例，随本批英文化保留在代码。

结论：#48 关闭；后续若出现「门文案需要按新判例改写」的实例，再以那个实例为据重开（届时才有数据支撑间接层的成本）。

## 四、对账结论

- **理论迁移表与实现一致性**：✅ 标注项全部验证属实（uncertain 入库/升级/观察组/即时写回/形态检验门两段/首败即升）；❌ 缺口项（单调门/build 锚/quarantine/词汇映射）确未实现且文档如实标注——**无虚标**。
- **老版本不兼容残留**：死入口 1 处（已修）、旧尾块 fixture 6 处（已修）、旧判据文档漂移 5 处（已修）——**行为层无残留**（`max_rounds-1` 唯一存活处是合法的 FINAL attempt 提示语义；`rounds_used>=max_rounds` 四处是 case 状态机终态锁，非升级判据）。
- **语言分层**：prompt 层（md）案卷号/日期清零 ✅；核心反馈链英文 ✅；user-facing（emit 进度/问询/报告/D 列）中文 ✅；次级工具返回串是已知残余面（项 16）。
- **验证**：全量门 1381 绿（tui 279 前轮已验）。
