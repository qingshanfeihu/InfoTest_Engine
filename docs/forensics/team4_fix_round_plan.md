# team4 · 问题总清单 + 修复分工草案（修复轮，Design 牵头，2026-07-18）

> 用户裁决：批 4 停止，先修全部已发现问题再从 yzg 重跑。本清单收敛全部审计/实证来源，去重后按归属域组织，供 leader 裁分工与批次。
> **来源**：Test-Eng 缺陷单 D1-D10（`ist_core_ask_interaction_defects.md`）+ LLM-Eng #30 §5（`team4_skill_official_zh_recheck.md`）+ Design precheck 三面（`team4_design_precheck.md`）+ 六项裁决 memo（`team4_decision_memo.md`）+ User 观察全帧（`team4_user_observations.md`）+ #24 批3/4 实证。
> **去重说明**：Test-Eng D 系列与 Design 面2 大量同指同一 bug（下方"实证锚"列合并双源）；每条给唯一 **F-ID** 供 leader 引用分工。
> **计数（2026-07-18 并入 TUI-Eng §13 十三项细化 + Py-Eng R_sig）**：A 区 **21 条**（Py-Eng 9 / TUI-Eng 10〔含跨域接口〕/ LLM-Eng 3 / Design-doc 1；题面英文透传并入 F-Py-2/F-LLM-1 不重复计）；B 区 **6 项**。TUI 项按【纯渲染】（TUI 独立施工）/【跨域】（需引擎接口）标注。

---

## A 区 · 可直接修（已过评审 / 纯缺陷）

### A-Py · Py-Eng 域（引擎 + 工具 + 判定式渲染 py）

| F-ID | 问题 | 级 | 实证锚 | 依赖 | 验收 |
|---|---|---|---|---|---|
| **F-Py-1** | folding 门变体 A：折叠成员先问后落门假拒（成员尾6没进 Q&A 日志→_land error→下轮重问） | P0 | run_log P1-6；User 00:16 599838；precheck §1.4/1.6 | **规格已终审 P**（凭证路 folded_members+集合判定+知情同意链）；出 diff 后 Design 增量审 | 4 守门测试（T1 防偷塞/T2 599838 过门/T3 截断免疫/T4 展示送达）；yzg 重跑折叠案无假拒 |
| **F-Py-2** | ask 面板英文 LLM-facing 泄漏（fix_direction/reason/attribution 英文原文直灌题面） | P0 | Test-Eng D1（532519 contra 英文整句/cap escalated 英文）；precheck 面2② | **双层**：源头=LLM 产出要求中文（A-LLM-1）；渲染兜底=展示层英文字段中文化。此条=渲染兜底 | 重跑观测 ask 面板零英文句；机器门 leak_scan 扩英文句检测 |
| **F-Py-3** | 内部黑话/机读 token 泄漏展示（nd:/contra:/s₀/reflow/captured_relation/escalated 进文案） | P1 | Test-Eng D5；precheck 面2②；User 22:33/23:25 | 建 token→中文人话映射表（复用 render.py STATUS_CN/LAYER_CN 扩展） | leak_scan 门扩机读 token；重跑观测 |
| **F-Py-4** | 裸命令/参数清单 dump 进题面（设备能力清单整段灌题面） | P1 | Test-Eng D3（600113 sdns pool 方法清单）；User 21:21 诊断表 | 题面渲染截结论句、清单折叠（数据按引用红线） | 重跑观测题面无清单 dump |
| **F-Py-5** | 「我给别的等价方案」静默空答陷阱（选 option 未进 Other 文本态→静默落改预期） | P1 | Test-Eng D6（532618）；precheck 面3 | emit/落盘层：option 选中未进文本态→拒空等价+回退 re-ask | 守门测试：空等价被拒；重跑 532618 型不静默降级 |
| **F-Py-6** | fork 零产物显示「✓ 完成」假完成（进程结束即绿勾，无视产物落盘） | P1 | Test-Eng D7；User 21:36 | 卡片状态按产物落盘判定非进程退出（events.jsonl fork_end 带产物标志） | 重跑观测零产物案显失败/未产出态 |
| **F-Py-7**（终裁 A·禁手工路径 · 双做，2026-07-18 铁证闭环） | 交付物黑话根因=**LLM 手工 openpyxl 重建 unsuccessful_cases.xlsx**（非引擎产，注入 nd:/facts.jsonl/escalated 黑话）；引擎 `render_unsuccessful_md`/`_archive_unsuccessful` 本已产人话/确定性交付物 | P1 | precheck 面2①；User 21:21（黑话）/23:48（尾号）；Py-Eng `main_activity:1237-43` 铁证 openpyxl 重建 | **裁 A 双做**（禁手工路径治本；**否 B** leak_scan 扩 xlsx=治标+xlsx 设备命令假阳）：①短号 md 做全（`render_unsuccessful_md` 加尾号、xlsx autoid 保 18 位框架 canonical、尾号走 title）②A-主 prompt 禁令（**LLM-Eng**：引擎交付物唯一源+禁手工重建）③A-加固机械对账（**Py-Eng** closing：交付物 mtime 晚于产出=手工覆盖告警）；**不加文件名硬写门**（误伤合法 outputs 写）。**A 正确形态=引擎做全+禁手工，缺一→新手工冲动** | 重跑交付物无黑话（引擎唯一源）+带短号+对账捕获手工覆盖 |
| **F-Py-8**（降级审计抽查项·非硬门，2026-07-18） | 断言极性照抄先例（引 dongkl 先例语法勿照抄断言方向，F3 极性禁运） | P1 | precheck 面3.2；Py-Eng provenance 核实 | **三层（机械触发+语义 oracle+报告）非硬门**：①provenance source.kind=precedent 机械触发缩抽查面（结构化事实可机械）②极性↔意图对齐是语义→closing 报告列 precedent-sourced 断言供人核 + **上机 oracle 兜底**（极性方向错→上机 fail）③不加"极性溯源"字段（假精确、极性对齐机械判不了）。**别做成机械判语义对错的假门** | 532618（precedent-sourced 触发实例）被触发缩面 + 上机验极性方向 |
| **F-Py-9** | R_sig 测试污染（.frozen.json 硬编码路径绕过 monkeypatch，测试伪键 R_sig 写进生产 workspace/outputs/） | P1 | Py-Eng 根因（batch_tools.py:1278-1281 写 / emit_xlsx_tool.py:1215 读硬编码；run_log:413 `\b1.2.3.4\b` 占位污染）；同 #18 三写入点族 | 方案 A 根治：两处硬编码 `parents[4]/workspace/outputs` → 统一可 monkeypatch 解析器（runtime_paths.outputs_root()）；一改修全 caller | 回归断言"跑全量后 workspace/outputs/ 无新增 R_sig/t_*/_pytest_*" |
| **F-Py-10**（F-Py-3 观察逼出，并 F-Py-7 人话化族） | 报告标题露绝对本地路径（`/Users/jiangyongze/.../inputs/automatic_case/yzg.txt`）——泄漏本机 home+用户名+冗长 | P2 | Py-Eng F-Py-3 增量审观察；yzg 金标准回放 | 【渲染质量】标题只显批名/相对路径（yzg）非绝对路径；与 F-Py-7 交付物人话化同批 | 重跑观测报告标题无绝对路径/本机用户名 |

### A-TUI · TUI-Eng 域（ink 渲染 + reducer 交互；TUI-Eng §13 详表，13 项，标【纯渲染】TUI 独立 /【跨域】需引擎接口）

**面板交互族**
| F-ID | 问题 | 级 | 实证锚 | 归属/接口 | 验收 |
|---|---|---|---|---|---|
| **F-TUI-1** | (41)④ 提交保真门（多题面板按键丢答：数字只高亮/Tab 不落/Enter 只提交聚焦题）；含 A6 多题提交保真强化（ask_user_view.py:390 已有未答告警，评估强化） | P0 | K (41)④ 待建；run15/run17 丢答；User 23:54/00:03 串框 | 【纯渲染】TUI；独立于 F-Py-1（599838 是引擎 fold 门非此） | 守门：Enter 未答挡板；cmux 多题逐题落答 |
| **F-TUI-2** | 选项 label 短语化（长 label+desc 撑爆行/硬截断技术串「采纳「…no sdns session persist」」） | P1 | Test-Eng D4；precheck 面2②；User 23:46/00:03 系统性；TUI A3 | **【跨域】label 短化在引擎 questions.py 侧（LLM-Eng/Py-Eng 题面生成），TUI 渲染配合** | 重跑观测 label 无半句截断 |
| **F-TUI-3** | 面板双侧引用拼行渲染丢中段（引文尾+文件名不可见，疑 \t wrap） | P1 | Test-Eng D8（035413）；precheck 面2② | 【纯渲染】TUI 已接（原 P1-1） | 重跑观测引文完整可核 |
| **F-TUI-4** | 题面截断（…）丢信息（facts [:300]+展示再截）/A4 超高面板 collapse 残留空白行 | P2 | Test-Eng D9（516576/517112/600113）；User 23:46；TUI A4/P1-12 | 【纯渲染】展开全文/限面板高度；**大 fold 组题面展示与 F-Py-1 变体 A 展示层同源**（precheck §1.6 边界2） | 重跑观测关键信息不丢、无空白残留 |
| **F-TUI-5** | Other 输入态无提示（A1）+ 长文本溢出污染 footer / A5 ask begin 未清全局框串旧文 | P2 | Test-Eng D10；User 00:03；TUI A1/A5 | 【纯渲染】placeholder「输入裁决答案」+进 other 态显提示；ask begin 清全局 PromptInput | 重跑观测输入态提示正确、无串框、footer 不污染 |
| **F-TUI-7** | esc 高危守卫（非 other 态 esc 二次 cancel 整面板，大面板误触全丢） | P1 | TUI A2；User 22:33 提示行 | **【跨域·Design 定语义】**：见下"接口裁决"——有已答内容时二次确认再丢，不破既有防呆 | cmux 误触不立即全丢 |

**footer 语义族**（TUI-Eng 拆分：文案纯渲染 / 数据源口径跨引擎）
| F-ID | 问题 | 级 | 实证锚 | 归属/接口 | 验收 |
|---|---|---|---|---|---|
| **F-TUI-8** | 编写期计数冻结提示（B1，数据源不动 INV-7，加文案「产出将在合并时结算」）+ 相位标签滞后（B2 已修 prep→编写，余滞后定位）+ 收敛态可读性（B5「第 M 轮/剩 N/趋势」） | P1 | precheck 面2③；User 21:32(#27)/22:13；TUI B1/B2/B5 | 【纯渲染】TUI 独立（不碰 counts 数据源，不破 INV-7） | 重跑观测编写期有文案说明、相位实时、收敛态清晰 |
| **F-TUI-9** | 进度条跨轮口径倒退（B3，重编轮 total 变致 41→28 倒退）+ 终验整卷无心跳（B4） | P1 | precheck 面2③；User 22:27（倒退）/23:17（终验无心跳）；TUI B3/B4 | **【跨域】数据源在引擎**：B3 统一跨轮 total 基准=Py-Eng counts_update；B4 终验整卷补 progress 发射=Py-Eng；TUI 渲染配合 | 重跑观测 footer 不倒退、终验有心跳走秒 |

**失败卡 + 题面英文（跨域）**
| F-ID | 问题 | 级 | 实证锚 | 归属/接口 | 验收 |
|---|---|---|---|---|---|
| **F-TUI-10** | 失败卡英文黑话→中文映射（`fork returned no text output` 等→人话+去向） | P1 | Test-Eng D1/D7；User 21:36 | 【纯渲染】TUI 建映射表（配 F-Doc-1 条款），与 F-Py-6 假完成同卡 | 重跑观测失败卡中文 |
| —（并入 F-Py-2/F-LLM-1） | ask 题面英文透传系统性（TUI ④）——Py-Eng 题面拼装层主导、TUI 渲染配合 | P0 | Test-Eng D1；precheck 面2② | **【跨域】主责 Py-Eng 题面拼装（F-Py-2）+LLM 源头产中文（F-LLM-1），TUI 渲染侧配合**，不单列 | 见 F-Py-2/F-LLM-1 |
| **F-TUI-11**（D10 拆出·**已做**） | 长文本单行渲染边界（PromptInput 溢出污染 footer + P2-9 busy 行同族）——根因 height=1 固定单行无水平滚动 | P2 | Test-Eng D10（溢出面）；User 00:03；根因 prompt_input.py:65/257 | 【纯渲染】**PromptInput 部分已做**（`_horizontal_window` CJK 感知+光标跟随，407 绿，Design P）+ **P2-9 busy 行已修**（53c2338e ANSI 感知截断）；**"统一"=共享 CJK 显示宽精神（非强行同窗口函数——两者场景不同：跟光标 vs ANSI）** | CJK 守门测试；长文本不溢出；**确认 CJK 宽度计算是否共用一函数（防漂移）** |

### A-LLM · LLM-Eng 域（skill/agent md prompt）

| F-ID | 问题 | 级 | 实证锚 | 依赖 | 验收 |
|---|---|---|---|---|---|
| **F-LLM-1** | 选项可判断性缺失（选项=引擎动作名，用户须懂内部机制才能选） | P0 | Test-Eng D2；precheck 面2②；User 22:33 | **双层**：题面/选项文案人话化（LLM-Eng questions.py 题面生成）+ 各轮理由中文摘要+方法论词翻译；与 F-Py-2/F-Py-3 渲染层配合 | 重跑观测选项带「对你的用例意味什么」人话；redline-reviewer |
| **F-LLM-2** | config-answer when_to_use 缺 SKIP when 子句（唯一 user-invocable 缺，误触风险） | P1 | LLM-Eng #30 P1-a（config-answer/SKILL.md:6-9） | 独立 | 标准包门；skill 结构核 |
| **F-LLM-3** | frontmatter 键不一致（user-invocable 键缺3/allowed-tools 4/14/agents model 缺2/inherit-parent-prompt 缺3） | P1 | LLM-Eng #30 P1-d | 独立（标准包门未强制，一致性非合规） | 标准包门扩键一致性 |

### A-Doc · Design 域（我域，收口批文档条款+设计锚回填）

| F-ID | 问题 | 级 | 实证锚 | 依赖 | 验收 |
|---|---|---|---|---|---|
| **F-Doc-1** | 收口批 §11 用户面渲染层条款正式化 + §2.1 幂等键两键终稿入 DESIGN + reference 单复数（P1-b）文档侧 | P1 | precheck 面2 四类骨架；p0_qid_review §2.1 终稿；LLM-Eng P1-b | 依赖 A 区 Eng 修法定案后回填（条款=实现的文档投影） | 文档双评审；条款↔实现一致 |

---

## B 区 · 六项裁决冻结面（用户随总清单最终确认后解冻实施）

> 全文+双签认见 `team4_decision_memo.md`；用户意向 **①A ②B ③A ④B ⑤A ⑥C**（执行前置 leader 综合调研，见 #24）。下方附 #24 批3/4 实证数据供最终确认。

| 项 | 裁决面 | 用户意向 | 归属 | #24 批3/4 实证 |
|---|---|---|---|---|
| **①** 终验断批缝合合法化条款 | 理论补 (15) 缝合等价条件 | A（采纳+补条款） | Theory+Design | 批3 zhaiyq 断批续跑实证缝合避免 7.8min 重跑（run_log；已落 commit b3ce3b4b） |
| **②** 单元 E 评测基建 | 建/缓立/取消 | B（缓立+转正条件） | Design 落文档 | 无新增实证（独立工作项不阻断主路） |
| **③** config_generator 管线退役（1200 行） | 删/修/挂牌 | A（退役删除） | Py-Eng | **牵动 A 区（leader 精确化）**：LLM-Eng P1-c 中**5 个 config-automation 脚本**（config_generator/sdns_module/slb_module/smoke/topology_parser）+P2-c 孤儿随退役消解、勿补 try/except；**memory_adapter.py 独立**（非③域）照修 try/except |
| **④** DS-1/2/3 数据集承接 | 立项/最小承接/归档 | B（最小承接） | Design 落文档 | 与②同族评测基建 |
| **⑤** worker/attributor prompt 语义小修组 | 批后启动/暂缓 | A（批后启动预授权） | LLM-Eng | **与⑥同文件**（compile-worker/attributor.md），合并实施 |
| **⑥** prompt 行数预算欠账处置 | 减法轮/改预算/换约束 | C（换约束「每行有据」） | LLM-Eng+Design | worker 206 行/attributor 167 行（precheck 实测）；theory-map.md 归属行载体已在 |

---

## 依赖关系图（批次建议供 leader 裁）

```
批 A1（引擎凭证/门，先行——重跑正确性前置）：
  F-Py-1 folding 门变体 A（规格已 P，出 diff）→ 依赖：无（可即出）
  F-Py-5 空答陷阱 + F-Py-6 假完成（引擎落盘/卡片，独立）

批 A2（渲染人话化，一批同碰 render.py/题面）：
  F-Py-2/3/4（英文/黑话/清单 渲染中文化）+ F-Py-7（交付物 xlsx+leak_scan+短号）
  F-LLM-1（选项可判断性，题面生成源头）——与 F-Py-2/3 双层配合
  ⚠ 依赖：token→中文映射表设计（Design 面2 条款先定形态）

批 A3（TUI 交互，独立域）：
  F-TUI-1 (41)④ 提交保真门（P0，独立于 F-Py-1）
  F-TUI-2/3/4/5/6（选项截断/引文/题面展开/输入态/footer）
  ⚠ F-TUI-4 大 fold 组题面展示 与 F-Py-1 变体 A 展示层边界衔接（precheck §1.6 边界2）

批 A4（skill 结构，独立）：
  F-LLM-2/3（SKIP/frontmatter 键）+ F-Doc-1（文档条款，依赖 A1-A3 定案后回填）

批 B（六项裁决，用户确认后）：
  ③config_generator 退役 先于 LLM-Eng try/except 补（退役消解 P1-c/P2-c）
  ⑤+⑥ 同文件（worker/attributor.md）合并
  ①②④ Design/Theory 文档
```

**跨面关键衔接**（避免漏改/重复）：
1. **F-Py-1 vs F-TUI-1 两条独立线**（Test-Eng 机读坐实 599838=引擎 fold 门非 TUI 落盘）——别合并；
2. **F-Py-2/3（渲染兜底）vs F-LLM-1（源头产出）双层**——英文/黑话既要 LLM 产中文、又要渲染层兜底映射，两层都做才根治；
3. **F-Py-7 终裁 A（禁手工路径）不扩 xlsx leak_scan**——根因=LLM 手工重建交付物（非引擎产），治本=禁手工+引擎做全（prompt 禁令+机械对账双保险），**B 案 xlsx 网兜已否**（xlsx 设备命令假阳+治标手工路径还在）；F-Py-2/3 的 **md** leak_scan 扩项照常；
4. **③config_generator 退役先于补 try/except（leader 精确化）**——**仅 5 个 config-automation 脚本随退役消解**（别给待删代码打补丁）；**memory_adapter.py 是独立项、照修 try/except**（不随退役，归 A 区 LLM-Eng/评审）。

---

## 分工与批次（leader 裁定，2026-07-18）：三线并行、线内串行

- **Py-Eng 线**：F-Py-1（最先，重跑正确性前置）→ F-Py-2/3/5/6（渲染兜底 + leak_scan 一次扩三：英文句/机读 token/xlsx 单元格）→ F-Py-7/8 →（F-Py-9 R_sig 独立可插）；
- **TUI-Eng 线**（文件域与引擎线不相交，即刻并行）：F-TUI-1（P0 提交保真）→ F-TUI-2/3/4/5 → F-TUI-8/9 footer 族；纯渲染项不等引擎；
- **LLM-Eng 线**：F-LLM-2/3 先行（独立小项）→ F-LLM-1（与 Py-Eng A2 协同，第一步钉死 label-token 接缝）+ memory_adapter try/except。
- **Design（我）**：F-Doc-1（**依赖各线 Eng 修法定案后回填**，条款=实现的文档投影）+ **全部 diff 的设计评审出口**（三线 diff 陆续到，逐笔双评审）。
- **四关不减**：双评审（Theory 理论 + Design 设计）→ redline-reviewer → leader 亲跑 pytest → leader commit。
- **动码闸门**：Test-Eng 清理完成 + leader 工作树放行信号后才落盘；当前仅可写 diff/测试草稿在各自 scratch。
- **B 区六项**：leader 正呈用户确认，解冻后实施。

---

## 验收总纲

- **机器门（回归护栏）**：folding 门 4 守门测试 / leak_scan 扩（英文句+机读 token+xlsx 单元格）/ (41)④ 提交保真守门 / 空答拒绝 / 全量 pytest 不降（leader 亲跑基线）。
- **重跑观测点（yzg 从头）**：User 视角逐 ask 面板核——①零英文句②零内部黑话 token③选项带人话后果④选项 label 无截断⑤短号伴随⑥引文完整⑦footer 不倒退/终验有心跳⑧多题面板逐题落答不丢。
- **红线**：不回归、通过率不降、编译链改动过 redline-reviewer + Theory×Design 双评审。
- **证据边界**：本清单 A 区 Eng 项多为"实证/机读坐实"（Test-Eng+User+机读）；F-Py-1 规格已终审 P，其余 Eng 项待出 diff 后各自双评审。B 区待用户最终确认解冻。

---

## 方法沉淀（F-Py-9 系列 + 评审可复用教训，Design 记 2026-07-18）

修复轮评审中反复出现、值得后续任何"开豁免/立过渡/扫污染面/审跨域改动"时对照：

1. **门豁免/过渡态纪律（Py-Eng 一般化）**：给门开豁免/立过渡态时**同步定"还清路径 + 本轮清零"**，否则过渡态悄悄永久化（allowlist 26 过渡债本轮内清零=正例；compile_pipeline 保留/单元 E 悬空=反例）。
2. **"保留不隔离"是 fail-open 方向**：判错"该隔离的保留了"→污染（重），判错"该保留的隔离了"→无害（轻）；故保留判定要更保守、**必须核被调函数实际读写、不能只看参数名**（emit_xlsx:1866 + runtime_fill_tools:114 两个 apply_fills 型隐藏写实证——参数名 project_root 看似读、内部 _sync_provenance 写）。
3. **1866 型隐藏写全抓法**：特征=本文件传 project_root 给被调、写在被调函数内——**grep 本文件写点抓不到，要沿调用链 trace**（第6处 runtime_fill_tools:114 连 grep 重扫都漏、redline 全量 trace 才抓）。
4. **empirical discovery 两盲区**：①skipif-masked 测试 discovery 时 skip→其污染看不见（清 skip 恒跑才现）②测试读 stale 伪键假过（清 stale 后复跑才暴露真失败）。
5. **清 stale/改隔离后跑两遍验稳定**：防"清 stale 扰动"非确定性绿（第一遍侥幸）。
6. **全库机械全扫 > 人工 scoping**：污染面/写点这类"要穷举"的靠机械全扫（grep + 调用链 trace），别信人工聚焦（9b-1 人工聚焦 3 文件漏 5+1，empirical 全扫补齐）。
7. **两笔改同文件（尤其安全门）要行级核正交不撞**：F-Py-1 门匹配（:421-430）vs F-Py-9b root 解析（:409）虽同函数但正交不同行——同文件改动最易暗撞，"逻辑零变化"声明须行级背书。
8. **完备性交叉例锁语义防未来误改**：T-compat②b（损坏行不污染有效行）/跨路径 armed（enter↔数字交叉确认）/光标三位置——为"共享状态/兜底分支"补交叉测试，防将来重构破坏语义。
9. **修订波及面/拆批/押后必登记**：撤销/取代/拆批/押后项都要在册（F-TUI-11 拆批登记、F-TUI-4 押后重跑观测点、§18.15 单元 E 落空反例），防"拆了/押后了没人管"。
10. **eval 当场坐实设计前提（前提证伪器）**：对"未证实但有架构支撑的前提"（如 F-Py-2 ②剔『』命令依赖"命令走独立通道、reason 不嵌命令"），**构造边界用例让 eval 在实现阶段证伪**（误伤即当场调），而非"等生产真出问题再调"——早一个阶段、双层兜底（eval 当场坐实 + detector 生产暴露）。eval 不只测行为，还当场验设计前提成不成立。
11. **辨析低假阳结构化判据 vs 强字典误杀**：不一刀切反对机械判据——有结构锚（F-Py-3「要求下划线」排缩略语）/剔合法内容（F-Py-2「剔命令引用」）/字段边界二分（叙述验 vs 原文引用豁免 device_quote）+ eval 守假阳的，是低假阳设计；无结构特征的宽泛匹配（GA-CUT/裸数字）才是强字典。判据看有无结构锚+假阳控制。
12. **门/判据必区分暴露 vs 掩盖**：detector（报 leak/拒背书/单列 broken 逼修源头）暴露问题；scrubber（渲染删泄漏/静默修正/折叠 broken）掩盖问题。一律选暴露（G5/broken/leak_scan detector 同族）。
13. **实现/eval/评审是设计边界的暴露器（二次设计面）**：纸面设计常漏边界，实现/eval/redline 时才撞出——本批 4 实证：F-Py-3 路径段假阳（eval 逼）、F-Py-9b apply_fills 隐藏写（redline trace）、F-Py-2 裸命令 reason（坐实器 eval）、F-Py-2 fact 顶层机读码作用域（hookup 实现）。**别只照设计做、把实现当二次设计暴露面**；实现期发现的边界要**回灌设计认知**（不只修实现）。配套：设计早审定 approach + 实现增量审核实现期暴露的边界（双阶段评审）。
14. **禁令/门锚目标集合、非工具通道枚举 + 「引擎做全+禁手工」配套**（F-Py-7 双洞察，leader 点名）：①**禁令锚目标非通道枚举**——F-Py-7 A-主 prompt 实证：禁手工重建交付物的禁令按「工具通道」枚举（run_python/openpyxl）漏 fs_write/fs_edit，而同节 bullet 2 恰认可 fs_write 落 outputs → LLM 可用 fs_write 绕过。**枚举通道必漏**（现漏 fs_write、将来漏新工具）；锚「交付物这个集合」（目标）才闭合，且天然区分合法（写新分析文件）vs 非法（改交付物）。同源「机械闭集从结构锚不枚举」（GA-CUT/裸数字强字典误杀反面）。②**引擎做全+禁手工配套（只堵不疏必生新绕行）**——禁 LLM 手工建交付物，必先让引擎交付物做全（含用户要的短号），否则用户需求没满足→新手工冲动；堵（禁令锚目标）+ 疏（引擎做全）配套才治本，缺一复发。
