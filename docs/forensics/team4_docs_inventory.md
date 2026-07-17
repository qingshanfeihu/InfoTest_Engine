# team4 · docs 全量文档整编行动清单（任务 #6，2026-07-17）

> **盘点进度：55/55 份 docs 根 md + 根目录 5 散文档 + archive/forensics 全部完成——本清单为完整终版**（2026-07-17 落盘；任务 #6 已 completed；后补 §六「修订波及面自查」轻量机制建议，leader 协调指示）。
> **执行进度（2026-07-17 leader 发令后）：CLAUDE.md C1-C13 全部执行 ✓（C13=wallclock 分层记载,900 特化经 _shared.py:312 核实）；29 份归档 mv 全部执行 ✓（27 份新加标注头+2 份已标注,git rename 保历史,2 份 untracked 普通 mv）；mv 前自查 tests/main/scripts 零代码引用；mv 后修复 README×2+ARCHITECTURE×3 断链,现役面悬空引用清零（forensics/archive 内 9 份历史文件引旧路径=历史记录不改）；全量 pytest 2152 passed 基线绿。HANDOFF_20260715.md 按 §五留待收口。未 commit。**

> 范围：`docs/` 根 56 份 md + `docs/archive/` + `docs/forensics/` + 根目录 5 散文档 + CLAUDE.md。
> 每份文档给**一个动词**（保留 / 更新 / 合并入X / 归档 / 删除），带一行理由；CLAUDE.md 漂移逐条给 `file:行号 → 建议新表述`，可直接照单执行。只读产出，未动任何文件。
> 判定依据：文档头部状态标注 + 被现役文档（DESIGN_v8 / dongkl_finalization / CLAUDE.md）引用与否 + 引用的代码/skill 是否实存（grep 验证）。
> **注**：`DESIGN_v6/grade_grounding 标注头`、`THEORY §6 索引` 已由 team2 完成（`team2_docs_audit.md`）；本清单不重复其已做项，只列剩余动作。

---

## 一、CLAUDE.md 漂移修复清单（P0 级，逐条可执行）

| # | 位置 | 现文 | 建议新表述 |
|---|---|---|---|
| C1 | CLAUDE.md:118 | `**V6 编译唯一入口**:一句话跑整条闭环(StateGraph 引擎,断点续跑)` | `**V8 编译唯一入口**:一句话跑整条闭环(事件溯源 StateGraph 引擎,断点续跑)` |
| C2 | CLAUDE.md:120 | `V6 归因孔:上机 fail 读原文判层,submit_attribution 落盘` | `V8 归因孔:上机 fail 读原文判层(+h 位置候选/ask panel),submit_attribution 落盘` |
| C3 | CLAUDE.md:171 段首 | `**V6 引擎主路（2026-07-06 起,\`main/ist_core/compile_engine/\`）**` | `**V8 引擎主路（2026-07-10 起,\`main/ist_core/compile_engine_v8/\`）**`（V6 目录已删，整段流程描述需按 V8 重写——见 C4-C6 拆分点） |
| C4 | CLAUDE.md:171 段中 | `engine_report.json\`/\`engine_ledger.json\`` | `engine_report.json\` + \`facts.jsonl\`（事件溯源事实流）`——`engine_ledger.json` 在 compile_engine_v8/ 全目录零引用，V8 交付物见 render.py:295-298 |
| C5 | CLAUDE.md:171 段中 | `_cleanup_temp\` 清 per-autoid/子集卷/manifest/last_run、保留上述交付物` | 按 DESIGN_v8 §11.9 重写：`已通过案 per-autoid 目录挪 delivered/ 存档、未决案挪 unfinished/（跨批续跑输入）、中间件删除；closing 交付对账断言` |
| C6 | CLAUDE.md:171 段尾 | `**编译只有 V6 这一条路**（2026-07-07 起,...）` | `**编译只有 V8 这一条路**（2026-07-10 一次切换,V6 包+测试已删——见 DESIGN_v8 §9.5）` |
| C7 | CLAUDE.md:191 整条 | `**终验整卷路由**（2026-07-06 zhaiyq 实证修复）…回归：\`tests/ist_core/compile_engine/test_final_full_verify_routing.py\`` | **删除或改写**：引用的测试随 V6 目录已删（find 零命中）；V8 语义=终验幂等闸+INV-8 组成指纹（DESIGN_v8 §16.4 片3 定形④）。若保留叙事价值,改为「历史修复,V8 由终验幂等闸取代」并去掉失效测试路径 |
| C8 | CLAUDE.md「性能双护栏」节（≈:196-199） | `**fresh-PASS grade 短路**（治 token）：\`compile_fanout\` 对 grade 类派发默认跳过…返回 \`SKIPPED_FRESH_PASS\`…\`force_regrade=True\`` | **删除整条**：`SKIPPED_FRESH_PASS`/`force_regrade` 代码零命中（grade 闸 07-07 删除时机制随删）；DESIGN_v8 §19.8 明载「❌ 已废,机械等价物=lint 凭证 mtime 新鲜性+pass 卷面锁」 |
| C9 | CLAUDE.md「载荷通道一致性」节（≈:205） | `编排纪律：>6 case 派发必走 \`briefs_path\`` | 改为 `V8 引擎主路 author 节点逐案构建 brief 单发 fork,briefs_path 批量通道仅保留给 compile_fanout(skill="dyn-*") 动态子 agent 场景`（DESIGN_v8 §19.8 ⚠ 行） |
| C10 | CLAUDE.md:117-126 Skills 表 | 表缺 4 个实存 skill；`review-verification` 用旧名 | 补 4 行：`doc-authoring`/`report-gen`（git 0f856609 已入 gating 映射）/`config-answer-draft`/`config-answer-verifier`；`review-verification`→`review-verifier`（loader.py:338 有别名互通不断链，表用现名） |
| C11 | CLAUDE.md「V4 引擎计划」节 | `**V4 引擎计划**：\`docs/PLAN_v4_engine.md\`…步骤 0-5 已全部落地` | PLAN_v4 归档后改为：`历史演进见 docs/archive/PLAN_v4_engine.md（V4→V6→V8,当前引擎设计唯一权威=DESIGN_v8_engine.md）`；或整条移入「关键架构决策」历史小注 |
| C12 | CLAUDE.md「Skills」节尾（≈:130） | `全景见 \`docs/AUDIT_skill_standard_alignment.md\`` | 改指第二轮：`docs/AUDIT_skill_bestpractice_v2.md`（2026-07-09,覆盖第一轮全部条目+21 项 checklist）——或两轮合并后指合并版 |

> 其余抽查通过项（不需改）：L100 工具目录表（compile_engine_run 等在位）、自愈合知识引擎节（grade_extract_script.py 在 tools/device/，文中未写路径）、`middleware/loop_guard.py` 简写（实际 main/ist_core/middleware/，惯例简写可接受）。

---

## 二、根目录散文档（5 份）

| 文档 | 动词 | 理由与要点 |
|---|---|---|
| CLAUDE.md | **更新** | 按上表 C1-C12 逐条改；改后跑 `tests/ist_core/skills tests/ist_core/agents` 确认 prompt 结构门无涉 |
| ARCHITECTURE.md | **更新（1 处）** | 仅头部 :6 「V6 编译引擎(1.0.5-beta.1 主路)：docs/DESIGN_v6_engine.md」→「V8 编译引擎：docs/DESIGN_v8_engine.md」；全文 V6/compile_engine 仅此 1 命中（grep 验证），其余 1129 行无编译引擎叙事 |
| README.md | **更新** | :5 「当前版本:1.0.5-beta.1(V6 循环驱动编译引擎首个 beta)」→ 与下一次发布版本号同步提 V8；正文如有 V6 提法一并扫 |
| CHANGELOG.md | **更新** | 最新条目停在 [1.0.5-beta.1] 2026-07-06（V6 beta）；V8 切换（07-10）、V8.5 图语义版（07-12）、ask 子系统 A/B/C 片、broken 三态、窗口审计门等 40+ 提交无条目——补一条 V8 里程碑（可在下次发布时合并写） |
| know_issue.md | **更新（轻）** | 条目 1 以 `IST_HAIKU_MODEL` 行文——该 env 已并入 `IST_FLASH`（读取兼容保留,CLAUDE.md 模型两档收敛）；条目加一句现名映射即可,29 行小文件不动结构 |

---

## 三、docs/ 根 56 份逐一判定

### 3.1 现役保留（18 份，动词=保留）

| 文档 | 理由（被谁引用/职责） |
|---|---|
| DESIGN_v8_engine.md | 现役唯一主设计（另见 team4_design_audit.md P1 修复项） |
| DESIGN_dongkl_finalization.md | 现役定稿；§5 team3 增补仍在生长；需补单元 E 处置声明（P0-1） |
| THEORY_k_state_machine.md / THEORY_target_system_algebra.md / THEORY_infra_reliability.md | 理论三角（`[[theory-triangle-architecture]]`） |
| AUDIT_design_theory_gaps.md | DESIGN §18.7 指名「本章的事实依据」 |
| AUDIT_gate_inventory_20260714.md | DESIGN §18.11 F4 引用（interactive_confirm 不建门依据） |
| AUDIT_attribution_ask_worker_gaps.md | DESIGN §18.6 引用（run19 s₀ echo-grounding 依据） |
| AUDIT_skill_bestpractice_v2.md | skill 现行对标基准（第二轮） |
| PROMPT_ENGINEERING_STANDARD.md | 现行提示面标准（2026-07-08 定稿） |
| RESEARCH_ask_design_survey.md | DESIGN §11.11 定稿依据 |
| RESEARCH_llm_test_automation_comparison.md | DESIGN §18.15 输入①/dongkl 定稿引用 |
| RESEARCH_theory_data_checks.md | DESIGN §15 指名「持久证据锚」 |
| RESEARCH_mimocode_backfill.md / RESEARCH_opencode_backfill.md | CLAUDE.md 记忆子系统节引用/对照补齐出处 |
| REVIEW_payload_channel_gap.md | CLAUDE.md 载荷通道节指名引用 |
| RUN_yzg_langfuse_monitor.md | DESIGN §9.5 指名「第三回合」切换依据 |
| CLAUDE_USAGE_GUIDE.md | CLAUDE.md 准则节指名「全景见」 |
| ANALYSIS_dongkl_ask_review.md | DESIGN §18.15/dongkl 定稿证据源 |

### 3.2 现役子系统文档（6 份，动词=保留；下轮复核）

| 文档 | 理由 |
|---|---|
| tui_architecture.md | 2026-07-06 重写（ink 单核），现役 |
| memory_system.md / footprint.md / file_sandbox.md / kms_pipeline.md | 子系统机制文档，机制未变；footprint.md 是提取链路契约（代码改动须对照） |
| skill_authoring_standard.md | 现行 skill 模板规范——**与 PROMPT_ENGINEERING_STANDARD.md、AUDIT_skill_bestpractice_v2 三份存在职责重叠**，是否合并归任务 #7（skill 审计）裁决；本清单先保留 |

### 3.3 加⚠️标注头 + 移 docs/archive/（16 份，动词=归档）

> 统一动作：标题下加「⚠️ 历史存档（被 X 取代/机制已删,YYYY-MM-DD 标注）」一行 + `git mv docs/<f> docs/archive/`。全部经 grep 确认**不被任何现役文档以活引用依赖**（PLAN_v4 被 CLAUDE.md 引用——随 C11 改引 archive 路径）。

| 文档 | 取代者/失效原因 |
|---|---|
| DESIGN_v6_engine.md | 已有标注头（team2）；V6 代码已删 → 移入 archive |
| DESIGN_grade_grounding.md | 已有标注头（team2）；grade 07-07 删 → 移入 archive |
| PLAN_footprint_v2_compile.md | v2 计划；自述工作目录 `SynologyDrive-home`+`.venv`（双过时） |
| PLAN_v3_closed_loop_compile.md | v3 计划；同上双过时；v3R 自述其「实测为负收益」 |
| PLAN_v3R_revised.md | v3R 计划；被 V4 取代 |
| PLAN_v4_engine.md | 被 V6→V8 两代取代；CLAUDE.md C11 随动改引 |
| compile_subsystem_design.md | v3/v4 时代（145KB,docs 最大文件）；演进备注指向的 V6 又已过时（二级过时） |
| batch_compile_architecture.md | 头部自注「仅存历史,不代表当前代码」 |
| case_compile_orchestration.md | draft/grade 编排（v4 pipeline 时代） |
| legacy_compile_pipeline_removal.md | 2026-06-15 删除记录（记录对象已删两代） |
| compile_refactor_round_2026-06-16.md | 单轮重构记录（v3 时代） |
| draft_slowness_rootcause.md | draft fork 已删 |
| yzg_grade_vs_run_audit.md | grade 已删（942 配对结论已进 CLAUDE.md/DESIGN） |
| V_layer_weak_assertion_analysis.md | draft/grade 时代分析 |
| theory_to_implementation_mapping.md | 「论文三层分解」时代；被理论三角取代 |
| linalg_formalization.md | 论文数学骨架；被 THEORY_k 取代（仅 PLAN_v4 引用,同去 archive 互引自洽） |

### 3.4 加标注头 + 归档（一次性调研/对照，价值已被吸收；6 份，动词=归档）

| 文档 | 理由 |
|---|---|
| prompt_gap_vs_cc_haha.md / context_reuse_vs_cc_haha.md | 2026-06 早期 cc_haha 对照；结论已被 RESEARCH_mimocode/opencode_backfill 与 PROMPT_ENGINEERING_STANDARD 吸收 |
| skill_progressive_disclosure_fix.md | 引用 `ist_compile_orchestrate`（已删两代的入口）；渐进披露现状以 tool_gating.py+CLAUDE.md 为准 |
| framework_design_notes.md | 2026-06 框架差异笔记；「待补齐项」多已落地（流式/skill 系统） |
| AUDIT_delivery_readiness.md | V1→V4 收官审计（2026-07-05），对象全部清偿或过时 |
| AUDIT_engine_gaps_round2.md | 2026-07-05 审计（V4/V5 时代缺口，V6/V8 已结构性取代） |
| REVIEW_theory_vs_impl.md | 2026-07-09 一次性对账，结论已进 AUDIT_engine_vs_theory→AUDIT_design_theory_gaps 链 |

### 3.5 单次运行记录/取证（DIAG/TRAJECTORY/AUDIT-快照类；5 份，动词=归档〔leader 指导第 3 条：不合并〕）

| 文档 | 理由 |
|---|---|
| DIAG_035413_reasoning_divergence.md / TRAJECTORY_035413_worker_vs_main.md | 035413 单案取证对（grade_grounding 的证据链,随其同去向） |
| DIAG_v6_shakedown_rootcauses.md | V6 对照轮诊断（DESIGN_v6 引用,随 v6 同去向） |
| AUDIT_yzg_full_system_check.md | V6 末代 yzg 快照审计（2026-07-10） |
| AUDIT_engine_vs_theory.md | 2026-07-09/10 V6 引擎↔理论对照（增删改清单已被 V8 消化;被 RUN_yzg 引用——RUN_yzg 保留在 docs/ 根,引用加 archive/ 前缀或保持相对链接由执行时统一处理） |
| AUDIT_skill_standard_alignment.md | 第一轮 skill 对标（2026-07-04）,被 v2 取代;CLAUDE.md C12 随动 |

### 3.6 时效性交接文档（1 份，动词=归档〔时机条件〕）

| 文档 | 理由 |
|---|---|
| HANDOFF_20260715.md | compact/重启接续快照（7-16 仍在更新）——**本轮 team 任务全部收口后**移 archive；当前保留 |

---

## 四、docs/archive/ 与 docs/forensics/ 处置

- **docs/archive/**（现 4 份 TODO_*）：保持；上述 3.3-3.6 共 28 份迁入后建议按前缀自然分组（PLAN_*/DESIGN_*/AUDIT_*），不建子目录（数量未到需要层级）。
- **docs/forensics/**（41 份）：**全部保留**——性质即取证档案区（team*/regression*/run 记录）。唯一动作：`SYNTHESIS_and_questions.md` 已被 `DESIGN_dongkl_finalization.md` 明文取代（其头部声明）→ 给 SYNTHESIS 加一行「⚠️ 已被 ../DESIGN_dongkl_finalization.md 取代」标注头（**更新**,不挪——forensics 本就是档案区）。
- **不删除任何文件**：全仓纪律「事实存档不删」；本清单最重的动词是归档（git mv 保历史）。

---

## 五、执行顺序建议（供 main 修复轮）

1. **CLAUDE.md C1-C12**（P0：日常每轮注入上下文的活文档，漂移代价最高）；
2. 根目录 4 份更新（ARCHITECTURE 1 处 / README / CHANGELOG / know_issue）；
3. 3.3-3.5 批量加标注头 + `git mv`（一次提交；PLAN_v4 与 CLAUDE.md C11 同批,AUDIT_skill_standard_alignment 与 C12 同批,避免引用悬空窗口）；
4. HANDOFF 待收口后处理；SYNTHESIS 标注头随手。

统计（docs 根实数 55 份 md，全覆盖）：**更新 6 份（CLAUDE.md 12 条 + 根目录 4 + SYNTHESIS 标注）/ 归档 30 份（其中 v6/grade 2 份已有标注头只需 mv）/ 保留 25（docs 根现役）+ 41（forensics 全部）份 / 删除 0 份**。

---

## 六、修订波及面自查（轻量机制建议；leader 指示——治「正文修订后汇总表/跨文档互指不同步」系统性病灶，防再犯不过度工程）

**病灶实证**（team4 两报告 + Theory #4 独立收敛到同一形态）：追加式修订（撤销/取代/收窄）只写新条款、不回填三类锚点——①同文档汇总表/映射表/落地序（THEORY §6 索引曾缺 (45)(46)(47)；DESIGN §1 缺 (47)；§18.11 落地序残留已撤销的 S₀ 前置裁决）；②被修订的前文条款（§6.5↔§18.12、F6↔§18.13 零互指）；③跨文档取代声明的对侧（§18.15 横幅对单元 E 落空）。CLAUDE.md 漂移（V6→V8 12 条）同病：切换发生在代码，文档锚点无人回填。

**建议（主推纪律，一条写作条款零代码）**——在 DESIGN_v8 §18.7 完成度纪律（或 CLAUDE.md 文档纪律）追加一句：

> 任何「撤销/取代/收窄」条款落笔时，同一提交内 grep 被撤对象名在 docs/ + CLAUDE.md 的全部命中处，逐处三选一：打指针（「已被 §X 修订」）/ 回填（汇总表、映射表、落地序同步）/ 如实豁免（列出不改的理由）。**取代声明必须双向**：A 宣称取代 B 的某节，B 该节必须有反向指针，且 A 必须逐单元交代去向（含「缓立/取消」——§18.15 单元 E 即缺这一句的实证）。

**可选机器门（半天级，仅当纪律再失守时上）**：`tests/` 加一个 docs 一致性小门——从 DESIGN/THEORY 抽「⚠️/已被…取代/撤销」声明行，断言其宾语（§编号或文档名）在对侧文件中存在反向标注。**不做**术语级全文扫描（假阳率高，违「别过度工程」）；对象只限显式取代声明的结对锚。

**不建议**：建修订追踪工具/引用图数据库——本仓文档修订频率高但体量可控（现役 25 份），一条 grep 纪律 + 结对锚小门足够；重工具会成为新的维护债。
