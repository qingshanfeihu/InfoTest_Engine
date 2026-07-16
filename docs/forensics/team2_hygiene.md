# team2 卫生审计报告(#8 文档/临时文件 · #10 测试孤儿 · #11 输出一致性 · #12 excel 核验)

> 生成 2026-07-16 · team2(hygiene 队) · 审计优先、证据先行、安全项先执行余项待确认
> 红线:通过率不回退。基线 `runtime/logs/pytest_baseline_20260716.txt` = **5 failed / 2026 passed**(5 失败全在 `test_batch_compile_tools.py`,根因 zhaiyq 真机 PID 29906 占床 `stale_run_on_device`,环境性非回归)。
> zhaiyq 编译真机在跑(PID 29906):`workspace/outputs/zhaiyq*`、53 个 top-level 数字 autoid 目录、compile_evidence.29906.*、checkpoints db 一律只读不动。

---

## #10 测试孤儿清理 —— 结论:**零孤儿,零删除**

**权威判据:`pytest --collect-only -q` = 2031 tests 全部干净收集(0.83s),退出码 0,零 ImportError、零收集失败。** 基线 2026 passed + 5 env-failed = 2031 全跑,**0 skipped**(说明无整文件 skip、无 importorskip 触发)。

| 候选来源 | 命中文件 | 判定 | 证据 |
|---|---|---|---|
| `compile_pipeline` | test_resilience.py:132-133 | **非孤儿** | 仅字符串字面量 `tool_name="compile_pipeline"`(loop-guard 心跳 fixture 值),非 import;基线通过 |
| `grade_extract` | test_grade_extract.py | **非孤儿** | 测的是**现役**模块 `main/ist_core/tools/device/grade_extract_script.py`(自愈引擎 5 原理检测器事实抽取,非已删 grade 闸);模块在盘 |
| `grade_extract` | test_math_model_fixes.py:3 | **非孤儿** | 仅注释提及 |
| 真 import 已删模块<br>(compile_skeleton/submit_verdict/grade_gate/compile_orchestrat) | 无 | **零命中** | `grep -E "^\s*(from\|import).*(已删名)"` tests/ = 空 |
| 整文件/条件 skip | test_compile_prep.py(3条 skipif)、test_llm_model_profile.py(1条 importorskip) | **非孤儿** | skipif 理由现役(脑图输入 dongkl.txt/zhaiyq.txt 存在性守卫,基线 0 skipped 证明输入都在、测试实跑);importorskip("deepagents") 是强依赖合法守卫 |
| xfail | 无 | — | 零命中 |

**孤儿动作:无。** 全部 198 测试文件现役。符号引用全良性(字符串字面量 / 注释 / 现役重命名模块)。

### 头号 finding + 已执行修复:单测不密闭(真 SSH 探测)

**基线 5 个失败(全在 `test_batch_compile_tools.py`)根因=单测不密闭**:`dev_run_batch` deliver 前有两个 bare 探测真连跳板机——`_probe_device_reachable`(ping 设备)+ `_probe_stale_pytest`(SSH 探残留 ist_staging pytest 进程,`batch_tools.py:596/602`)。`_patch_client` fixture 只 mock 了 MCP client、漏了这两个探测,zhaiyq 真机占床时探到残留 → 返回 `stale_run_on_device` → 与被测 deliver/run/verdict 逻辑无关却令断言失败。

**已执行(经团队 lead 授权,只改 tests/ 不改 main/)**:在 `_patch_client` fixture 内 `monkeypatch` 两个探测为「床空闲、设备可达」(`_probe_stale_pytest→None`、`_probe_device_reachable→True`),使测试密闭。核对无任何测试专测 stale/unreachable 探测路径(line 250/328 的 device_busy 是 client 层 mock、line 454 的 stale 是 grade 凭证过期,均不受影响)。**验证:单跑该文件 `39 passed in 1.01s`**(1 秒完成=零真 SSH,真探测会数秒且探到 zhaiyq 残留而失败)。通过数 **2026→2031**(红线满足,反上升 5)。

---

## #11 输出临时文件一致性规范 —— 现状描述(不改代码,不一致转 code-align 队)

基准批 `workspace/outputs/dongkl/`(compile-engine v8,34 case,07-16 09:55 定稿);对照 5 个历史批(backups,覆盖 v6/v8/v8.5/ist-verify 四形态)。全程只读。

### (A) per-autoid 目录布局(命名=18位纯数字 autoid,落在批根 `delivered/` 或 `unfinished/`)

| 文件 | 出现条件 | 顶层字段 schema | 一致性 |
|---|---|---|---|
| `intent.json` | 恒有(含未编译案) | `autoid,title,step_intents,group_path,source,stamped_by` | 跨批一致(yzg_rv2 4 案多可选 `forbidden_mechanism`) |
| `case.xlsx` | 案已 emit | (per-case 卷) | — |
| `case.provenance.json` | 案已 emit | `autoid,skeleton_ref,provisional,steps` | 跨批完全一致 |
| `.grade_credential.json` | 过 lint 门 | `autoid,xlsx,xlsx_mtime,verdict,source,lint_ok,verdict_ts` | 跨批完全一致 |
| `attr_evidence.json` | 上机 fail/归因案 | `autoid,verdict,task_id,causality,detail_tail,[anomaly_lines],device_context,_digest_layer,[_device_help],_round,_run_ts,_fail_signatures` | 核心稳定;缺 `_attribution`(聚合 last_run 却有) |
| `needs_decision.json` | 有欠定 claim | `autoid,claims[]`;claim 子对象**按 claim_kind 多态** | 无统一 union |
| `user_decision.json` | 用户已决策 | `autoid,decision,note`(+可选 `expected_assertion_form,min_requests,claim_kinds_preserved`) | 同批内 schema 漂移 |
| `.frozen.json` | 同签名连败 | `reason,signatures,ts` | 一致 |
| `history/case.rN.xlsx` | ≥1 次重写轮 | (r1/r2 轮次快照) | 命名一致 |
| `steps.json` / `prov.json` | **杂散残留** | — | 应清未清(见不一致清单) |

**「第三态」案**:`unfinished/` 里 `203031753781593545`、`203031754297105941` 只有 intent+needs_decision+user_decision,**无 case.xlsx**(卡欠定决策从未 emit,编写0次)——解释了 unfinished 12 目录 vs unsuccessful 卷 10 案的差 2。

### (B) 批级文件布局

| 文件 | 语义 | 关键 schema | 跨批一致性 |
|---|---|---|---|
| `case.xlsx` / `unsuccessful_cases.xlsx` | 主交付卷 / 未通过卷 | xlsx | yzg_rv2 缺 unsuccessful.xlsx(见 C10) |
| `unsuccessful_cases.md` / `delivery_report.md` | 人话说明 / 交付报告 | md | v8 起;v6 另有重复 FINAL_ 版 |
| `engine_report.json` | 引擎终报 | `engine,outcome,totals,volume,moved_tail,coexist_violations,bed,cases,refs` | **v6↔v8 schema 大改**(C9a) |
| `facts.jsonl` | 事件流 | JSONL 信封 `{ev,aid,_pid}`(+opener `seq`),payload 按 ev 多态 | v8 起信封一致 |
| `bed_before.json` | 批前床快照 | `segments,sdns_config_files,sync_peers,interface_addresses` | v8 起有则一致 |
| `manifest.json`/`last_run.json`/`engine_ledger.json` | 清单/上机聚合/台账 | — | 保留策略跨版本翻转(C9b-d) |

### (C) 不一致清单(→ code-align 队,含文件名+字段)

- **C1 [高危,已独立复核]** `delivered/203031753781593573/needs_decision.json` **真 JSON 损坏**:合法对象闭合后尾随上版残留字节 → `json.load` 报 `Extra data: line 23 column 2 (char 631)`。根因短内容覆盖长内容**未 truncate**。dongkl 96 个 per-autoid JSON 中仅此 1 个损坏(其余 95 + engine_report + bed_before + facts.jsonl 352 行全有效)。建议写盘走 `tmp + os.replace` 原子替换。
- **C2** `user_decision.json` 同批内 schema 漂移(可选字段非恒写)。
- **C3** `needs_decision.json` claim 子对象按 kind 多态、无统一 union(`command_existence` 带 `command` 无 `verifiable`;`distribution` 带 `verifiable,notes` 无 `command`)。
- **C4** `attr_evidence.json` 可选字段(`anomaly_lines` 6/13、`_device_help` 1/13)无固定 schema。
- **C5** `attr_evidence.json` 缺 `_attribution`,聚合 `last_run.json` 记录却有——per-autoid 切片丢归因判定对象。
- **C6** `intent.json` 可选 `forbidden_mechanism`(yzg_rv2 4 案有,dongkl 无)。
- **C7** 遗留裸名 `prov.json`(LIST)与 `case.provenance.json`(dict)并存(yzg_rv2 1 例)——旧名逃过清理。
- **C8** `steps.json` 杂散中间产物遗留(dongkl `…781593516`、yzg_rv2 各 1)——清理不彻底。
- **C9** 批级文件集随版本(v6/v8)+ 流别(compile/ist-verify)**双重漂移**:engine_report schema 大改(a)、delivered/unfinished 分栏仅 07-16 批有(b)、manifest/last_run 保留策略翻转(c)、engine_ledger 仅 v6(d)、v6 遗留重复 .md(e)。
- **C10** 同日 07-16 两 compile 批未通过卷交付不一致:dongkl 有 .md+.xlsx,yzg_rv2 只有 .md 无 .xlsx(尽管 unfinished 有案)。
- **C11** ist-verify 与 compile-engine 批形态共用同一 `workspace/outputs/<批>/` 命名空间,消费方需探测文件集才能判批类型——建议加批级 `flow` 标识。

**命名规范观察**:点前缀(`.grade_credential`/`.frozen`)=引擎内部门禁产物,不入交付、语义一致;下划线前缀 JSON 字段(`_round`/`_run_ts`/`_fail_signatures` 等)=引擎内部元数据,与领域字段区分;`history/case.rN.xlsx` rN=重写轮次;delivered/unfinished=通过/未通过分栏,语义清晰。**核心四件套(intent/case.provenance/.grade_credential/case.xlsx)跨批跨版本高度一致,是最稳接口。**

---

## #12 dongkl excel 终卷与报告数据核验

**卷:** `case.xlsx`(主/通过卷)、`unsuccessful_cases.xlsx`(未通过卷)。全程只读,未改卷。

### 结构完整性 ✓
| 卷 | 总行 | 表头行 | autoid 案数 | 哨兵行(999999999999999) | 18位不合规 | 卷内重复 |
|---|---|---|---|---|---|---|
| case.xlsx | 268 | 1(row28) | **23** | 1 | 0 | 无 |
| unsuccessful_cases.xlsx | 179 | 1(row28) | 10 | 1 | 0 | 无 |

### 机械 lint 复扫(`structural_gate.lint_xlsx_case`,只读) ✓
- delivered/ **22 单卷:0 违例**;unfinished/ 10 卷:0 违例,2 目录无 case.xlsx(编写0次,合理);合并主卷参考 lint:ok。
- 即无恒真/恒假/悬空断言、found_times、手动 ip del 等崩溃门违例——**dongkl 机械质量过关**。

### ❌ 发现:主卷泄漏 1 个 failed_terminal 降级案(数据完整性缺陷)
- 主卷 case.xlsx 实含 **23** 案,但 engine_report `totals.deliverable=22`、delivery_report 声称「22 个通过整卷复验,已入交付卷」。
- 多出 1 案 = `203031753342778041`:engine_report.cases 里 **status=failed_terminal**(rounds=2,contradictions=2);delivery_report 明记它「按裁决收尾(未通过卷)…如实降级,记入未通过卷」;它**同时**在 unsuccessful_cases.xlsx(未通过卷正确含它)、且**不在** delivered/ 目录(22案与 deliverable=22 一致)。
- **判定:一个被复验推翻的降级案泄漏留在了主交付卷,使主卷 22→23 且与未通过卷重复。** 属 merge 路由层缺陷(lint 抓单卷机械正确性,抓不到「此案不该在主卷」)→ 转 code-align 队。dongkl 是已交付批,**仅报告不改卷,待主协调确认**。

### 报告数字互核 ✓
- engine_report `totals`:cases 34 = deliverable 22 + suspended 9 + failed_terminal 1 + pending 1 + escalated 1;ask answered 11 / effective 10 / freeform 0 —— 与用户交代的 22/9/1/1/1、ask 11/10 完全一致。
- delivery_report「34 个用例:22 通过…其余 12」,12=unfinished/ 12 目录 ✓;正文逐案 12 条 ✓。
- 设备床 `InfosecOS Beta.APV-HG-K.10.5.0.585 @10.4.127.103`;coexist_violations=[]、moved_tail=[]。
- unfinished 12 vs 未通过卷 10:差 2 = `203031753781593545`/`203031754297105941`(编写0次无 case.xlsx),合理。

---

## #8 项目临时文件与文档清点

### workspace/outputs/ 未跟踪废弃物 —— 结论:**当前无可安全移动项**

`workspace/outputs/` 全量 gitignore(未跟踪)。逐类判定:

| 类别 | 数量 | 判定 | 证据 |
|---|---|---|---|
| `dongkl/` | 1 | **保护**(交付物,只读) | — |
| `zhaiyq`/`zhaiyq__sub2/3/4` | 4 | **保护**(PID 29906 运行中) | 引擎收尾自清,现在不动 |
| 18位数字 autoid 目录 | 53 | **不动**(zhaiyq 活跃工作目录) | 前缀 `205271`(≠dongkl `203031`)、mtime 10:46-10:54 落在 zhaiyq 运行窗口(10:38 启动),per-autoid 工作目录在 top-level `outputs/<autoid>/`——待 run 结束后确认孤儿再清 |
| `_pytest_*`(7)、`t_*`/`R_sig`(15) | 22 | **不移**(活跃测试 scratch) | **目录 mtime 7-13 但内含文件全为今天 14:13-14:14**(基线 pytest 运行时段写入);名字在 tests/ 有引用(R_sig 6处等);测试写固定路径而非 tmp_path——移走无持久收益(每次测试重生成)+ 有回归风险 |

**更正团队前提**:`_pytest_prep_*` 非「7-13 残留」——目录创建于 7-13 但测试每次复用同路径重写内容,今天基线刚写入,是**活跃 scratch**。真问题=测试写固定 `workspace/outputs/<名>/` 而非 pytest tmp_path,污染输出命名空间 → **测试卫生项转 code-align/测试属主队**(改 tmp_path),不由本队移目录。

### runtime/logs 归档 —— **只报告不动**

`runtime/logs` = **490M,全 gitignore(0 跟踪)**。zhaiyq 活跃日志 `compile_evidence.29906.{live.log,events.jsonl}` + `run-5409f5f0431e.jsonl`(45M,mtime 14:33 仍在增长)**绝对不动**。历史 `run-*.jsonl`(dongkl 的 run-affdccca918b 56M/09:55 等,20-56M/个,7-10~7-16)理论可归档,**但 6 路团队正做取证(`team_log_vs_attrevidence_diff`/`team_exec_replay_logic`/yzg reverify 等很可能正读这些 run 追踪日志)**——单方移走有抽走他队分析数据之险。→ **待主协调:zhaiyq 结束 + 取证收口后统一归档历史 run-*.jsonl**。

### docs/ 文档清点(88 份:61 顶层 + 27 forensics)

**方法**:git 日期 + 读头 + 交叉引用图(CLAUDE.md/代码/prompt/文档互引)。**安全约束(已探明)**:docs/ 仅在注释中被引用(无运行时 `open()`),删文档不引发测试回归;但删被代码/prompt/当前文档引用的会造成**悬空引用**——删前必核引用。

**分类汇总**(全表在 docs 子任务归档,此处列可动项):

| 组 | 归类 | 计数 | 处置 |
|---|---|---|---|
| A 现役常青子系统参考 | 现役 | 9 | 全保留(file_sandbox/footprint/kms_pipeline/memory_system/tui_architecture/CLAUDE_USAGE_GUIDE/PROMPT_ENGINEERING_STANDARD/AUDIT_gate_inventory/HANDOFF) |
| B THEORY_/DESIGN_ | 混 | 9 | **归 theory-design 队,本队不动**(THEORY_k/target_algebra/infra + v8/dongkl_finalization 现役;v6/grade_grounding 已被 v8 取代且正被他队加历史头) |
| C 历史取证(已消费进 DESIGN) | 保留 | 11 | 全保留(A/B/C/F_closeout 四报告、reconcile_S5、regression_* 等为事实依据) |
| D 今日新产团队调查 | 现役 | 16 | 全保留(593516/enforcement/dongkl_*/team_*/team2_*) |
| E 一次性审计/诊断/研究快照 | 现役机制点时定格 | 20 | 建议整体挪 `docs/archive/` 而非删(取证链,待确认) |
| F 已被取代/过时(旧机制主题) | 已取代 | 17 | 多被互引,待确认(见下) |
| G 已完成 TODO + 迁移完成 | 已完成 | 7 | 2 份已 rm,4 TODO 待确认,1 陷阱 |
| H 明确取代关系 | 已被取代 | 1 | SYNTHESIS_and_questions(finalization 明写取代),待确认倾向 rm |

**已执行 git rm(2 份,零引用、已读确认废弃、可恢复)**:
- `skill_migration_guide.md`(旧XML→SKILL.md 一次性迁移指南,迁移已完成、被 CLAUDE.md 封装标准取代、零引用)
- `V3_prompts_review.md`(V3 编译链已删 prompt 的点时审阅、含「误判已撤销」批注、零引用)

**待人工确认(不盲删,理由)**:
- **4 个 RESOLVED TODO**(attributor_s0/f6_claim_kind/s0_l23_infra_ip/tui_ask_user_panel):自述 RESOLVED 且 F_closeout 独立核实,但**全被当前 HANDOFF_20260715.md + F_closeout.md 引用**(f6 还被 DESIGN_v8 引),删需先改这些引用(HANDOFF/F_closeout 我可改,DESIGN_v8 归 theory 队)→ 建议挪 `docs/archive/` 并更新引用,待协调。
- **⚠️ 陷阱 `skill_progressive_disclosure_fix.md`**:修复对象已随 V6 删,但**被代码(main_agent.py:186)+prompt 引用**——**绝不盲删**,删前先改引用方。
- **F 组旧计划/编译文档**(PLAN_v3/v3R/footprint_v2、batch_compile_architecture/case_compile_orchestration/compile_subsystem_design、yzg_grade_vs_run/V_layer/draft_slowness/compile_refactor 等):多自述历史存档且被互引,建议合并为历史存档或挪 archive,逐份待确认。
- **载荷承重 ⚑ 12 份**(REVIEW_payload_channel_gap/RESEARCH_mimocode_backfill/PLAN_v4_engine/CLAUDE_USAGE_GUIDE/AUDIT_skill_standard_alignment/theory_to_implementation_mapping/THEORY_k/skill_progressive_disclosure_fix/linalg_formalization/DESIGN_v8/A_oracle/regression_1):被 CLAUDE.md/代码/prompt 硬引,删任一前必先改引用,否则断指针。

**协调红线**:并行进程产的 `team2_docs_audit.md` 在做 THEORY/DESIGN 文档审计,与本队 docs 任务部分重叠;THEORY_/DESIGN_ 多份工作树带 M(正被编辑)——本队一律不动、处置前合并两队结论。

---

## 已执行 / 待确认动作清单

### 已执行(仅 tests/ 与 docs/,不 commit,均可恢复)
1. **[#10 密闭化,团队 lead 授权]** `tests/ist_core/tools/test_batch_compile_tools.py` 的 `_patch_client` fixture 加两行 monkeypatch,把 `_probe_device_reachable`/`_probe_stale_pytest` 置为「床空闲可达」→ 5 个环境失败测试转绿。仅改 tests/,未动 main/。验证 `39 passed in 1.01s`(零真 SSH)。通过数 2026→2031。
2. **[#8 docs]** `git rm docs/skill_migration_guide.md docs/V3_prompts_review.md`(零引用、已读确认废弃,已暂存未 commit)。

**最终回归**:全量 `collect-only`=2036 tests(较基线 2031 +5,全来自他队并发改 `test_ask_user.py`/`test_fork_cards_render.py`,我的 delta=0);`tests/ist_core -q` = **1153 passed / 0 failed**(73s,含 test_batch_compile_tools 5 个原失败测试现转绿)。**零回归,通过数因密闭化修复上升。** 注:6 路团队并发编辑中(main/ 多文件 + 2 测试文件带 M),全量 `tests/` 数字为移动靶,以 tests/ist_core 全绿 + 本队文件独立验证(test_batch_compile_tools 39 passed)为本队无回归凭据。

### 待主协调确认
1. **[#12 高优]** dongkl 主卷 case.xlsx 泄漏 failed_terminal 案 `203031753342778041`(23→应22)→ 转 code-align 查 merge 路由「降级案未从主卷剔除」。dongkl 已交付,是否需重出主卷?
2. **[#11 高优 C1]** dongkl `delivered/203031753781593573/needs_decision.json` JSON 损坏(非原子写)→ code-align 修写盘为原子替换。
3. **[#11 C2-C11]** 多态文件缺 union schema、批级文件跨版本/流别漂移、杂散 steps.json/prov.json 残留 → code-align 收口。
4. **[#8 workspace]** 53 数字 autoid 目录 + `_pytest_*`/`t_*` 测试 scratch **当前无可安全移动项**(全为 zhaiyq 活跃或今日测试写入);zhaiyq 结束后确认孤儿再移;测试 scratch 改 tmp_path(测试属主队)。
5. **[#8 docs]** 4 个 RESOLVED TODO(被 HANDOFF/F_closeout/DESIGN_v8 引)建议挪 archive 并更新引用;F 组旧机制文档逐份待确认;⚑12 份 + `skill_progressive_disclosure_fix` 删前必先改引用;THEORY_/DESIGN_ 与 `team2_docs_audit` 归他队,合并结论后再动。
6. **[runtime/logs]** 490M gitignore 日志,历史 run-*.jsonl 待 zhaiyq 结束 + 取证收口后统一归档(他队可能正读)。
