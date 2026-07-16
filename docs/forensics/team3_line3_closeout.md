# team3 线3 收尾报告(2026-07-16)

> 接手线3三件窄活:①注释缩写(非热区)②object_normalizer.py 终裁 ③4 个 RESOLVED TODO 挪档。
> 红线:零回归 / git rm·git mv 可恢复 / 不 commit 不 push / 热区(compile_engine_v8/**、batch_tools.py、
> case_compiler/{verifiability,domain_grammar}.py、compile-worker.md、THEORY_*/DESIGN_*)不动。
> **回归结论先行:基线 2144 passed/0 failed → 终态 2138 passed/0 failed,全绿;差额逐项归属见 §4。**

---

## 1 · 注释缩写(team2_code_align §2.1 (a) 表 16 条,过滤热区)

**过滤结果**:16 条中 13 条在热区(`nodes.py`×2、`views.py`×2、`graph.py`×3、`engine_tool.py`×2、
`_shared.py`、`batch_tools.py`×2 属 compile_engine_v8/batch_tools 热区)——**零动作**;剩 3 条逐条验证处置:

| # | 文件:行(缩写前) | 声称§ | 验证结论 | 处置 |
|---|---|---|---|---|
| 8 | `tools/device/checker_tool.py:46-48` | DESIGN §3.1 | **覆盖**:§3.1 明文记载 checker↔worker.md 成对机制、2026-07-04 红线切除史、「前门重注入后门清理的」;工具自身返回文本(机读契约)另载「worker 从先例/手册核实自拼前缀」 | 缩 3→2 行:保留禁组装前缀的 why 一句 + §3.1 引用 |
| 10 | `tools/ask_user/__init__.py:88-91` | DESIGN §2 | **覆盖**:§2 载修法全链(ask_user_answered 事件+reducer 标已答+replay 兜底+根因指针);根因链①②③(append 无已答态/答复只 set Event/_replay_snapshot 复活)逐字在 `F_closeout.md` TODO4 | 缩 4→2 行:留机制一句 + DESIGN §2 + F_closeout TODO4 双引用 |
| 16 | `tools/device/structural_gate.py:1097-1102` | DESIGN §2/§0.1 | **未覆盖**:DESIGN §2 现措辞「任意 [A-Za-z0-9-] 连续段 >63 即违例」是规划期朴素形态,与实现的双闸设计**相悖**(实现刻意规避任意长串扫描——那是 GA-CUT 强字典误杀);双闸 why 同时承载于紧邻 `_check_dns_label_limit` docstring(行为契约,KEEP) | **先归档再缩**:原文 6 行逐字抄入 `team2_designdoc_additions.md` §D1(标 file:line+归档理由+文档 owner 回填建议),源处缩 6→3 行(RFC 63 契约首行按审计要求原样保留) |

三文件 `py_compile` OK;承重契约行(RFC 63 首行、禁组装前缀语义)均保留。

## 2 · object_normalizer.py 终裁 → 已删(零生产消费者)

**独立验证(不采信旧报告,全部重查)**:
- 模块名 grep(main/tests/scripts/docs/CLAUDE.md/knowledge/wecom_bot*,含 .py/.md/.json/.toml/.cfg):
  命中仅①自身 docstring ②`tests/case_compiler/test_object_normalizer.py`(自测)③docs 两处历史记载。
- **符号级** grep(`ObjectNameNormalizer|get_object_normalizer`,防 `from x import 符号` 漏网):模块+自测之外**零命中**。
- `main/case_compiler/__init__.py` 为**空文件**(无自动导入/再导出)。
- 背景复核成立:唯一生产消费方 corpus.py 已删(team-lead 2026-07-16 裁决);docstring 曾声称的 framework_sync 消费已被 grep 证伪。

**处置**:`git rm main/case_compiler/object_normalizer.py tests/case_compiler/test_object_normalizer.py`
(测试文件 15 个用例、无 parametrize,基线中全绿——collected 下降 15 全部由此,预授权)。
collect-only 全量 **2138 collected / 0.89s / 零 ImportError**。

**残留引用(docs 历史记载,报告不改)**:`docs/compile_subsystem_design.md:87,339-346,377,380`(F 组旧机制文档,
hygiene 已列"已被取代待确认"——其 §2.8 整节描述该模块,若该文档后续裁归档/删则自然消解);
`docs/forensics/team2_code_align.md` 多处(审计史实,应保留原貌)。

## 3 · 4 个 RESOLVED TODO 挪档 → docs/archive/(新建)

`git mv` 四份(均 git 跟踪、头部均自述 `[RESOLVED 2026-07-15]`——含 `TODO_tui_ask_user_panel_clear.md`,
其 S4 修复后已回填 RESOLVED 头):

- `docs/archive/TODO_attributor_s0_mechanical_recheck.md`
- `docs/archive/TODO_f6_claim_kind_unify.md`
- `docs/archive/TODO_s0_l23_infra_ip_exclusion.md`
- `docs/archive/TODO_tui_ask_user_panel_clear.md`

**引用处置(全仓 grep 逐一验证)**:
| 引用位 | 形态 | 处置 |
|---|---|---|
| `HANDOFF_20260715.md:71-74` | 带 `.md` 文件名(唯一路径型引用) | 4 行改 `docs/archive/…` 路径;**目标存在性已逐一验证** |
| `F_closeout.md:5,14-17,36,68,97,137` | 裸名(无路径,挪档不断链) | 头部加一行挪档注(2026-07-16),正文裸名不逐处 churn |
| `DESIGN_v8_engine.md:1518` | 裸名散文、无路径 | 挪档不断链,**无需改**(且属热区) |
| `DESIGN_dongkl_finalization.md:191` | `docs/TODO_*` glob(S4 分工表史实) | **热区不动**,报告:该 glob 今后匹配为空,交文档 owner |

## 4 · 回归对账(红线:全量 pytest 全绿)

| 时点 | collected | passed | failed |
|---|---|---|---|
| 基线(改动前实跑) | 2144 | **2144** | 0 |
| 终态(全部改动后) | 2138 | **2138** | 0 |

差额 -6 = **-15(我:删 test_object_normalizer,15 用例基线全绿,git show HEAD 核实无 parametrize)
+9(非我:队友 17:54 并发改 `tests/ist_core/test_ask_user.py`**,我基线之后、终跑之前;终跑含其全部新增且全绿)。
通过率 100%→100% 不降。零 ImportError、零收集错误;py_compile 三改动文件 OK。
本人未触碰:热区全部文件、workspace/outputs/zhaiyq*、runtime/backups;未 commit 未 push。

## 5 · 遗留交对应 owner(非本轮范围)

1. **DESIGN_dongkl_finalization.md §2 检测面措辞回填**(additions §D1 已备好文案):现文「任意连续段>63」
   若被照做即重蹈 GA-CUT 误杀,与 code_align D2 名字回填同源。
2. **DESIGN_dongkl_finalization.md:191** `docs/TODO_*` glob 已空(热区,一并回填)。
3. **compile_subsystem_design.md** §2.8 仍整节描述已删的 object_normalizer(该文档本身在 hygiene 待确认清单)。
4. **HANDOFF_20260715.md:74** 「未修,仍开」陈述已过时(S4 已修,文件头已标 RESOLVED)——本轮只改路径未改史实陈述,是否补注交 owner。
