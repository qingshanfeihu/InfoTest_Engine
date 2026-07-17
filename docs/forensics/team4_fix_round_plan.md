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
| **F-Py-7** | 交付物 xlsx 人话化 + leak_scan 扩 xlsx + 短号映射 | P1 | precheck 面2①；User 21:21（诊断表黑话）/23:48（尾号正面） | **二案对比**（禁手工路径 vs 手工产物过门）；leak_scan 现只扫 md，扩 xlsx 单元格 | leak_scan(xlsx) 门；重跑交付物无黑话/带短号 |
| **F-Py-8** | 532618 等价方案断言极性核（引 dongkl 先例语法勿照抄断言方向，F3 极性禁运） | P1 | precheck 面3.2 | closing 核重编卷断言极性溯自本案意图/手册非照抄先例 | closing 抽查 532618 断言溯源 |
| **F-Py-9** | R_sig 测试污染（.frozen.json 硬编码路径绕过 monkeypatch，测试伪键 R_sig 写进生产 workspace/outputs/） | P1 | Py-Eng 根因（batch_tools.py:1278-1281 写 / emit_xlsx_tool.py:1215 读硬编码；run_log:413 `\b1.2.3.4\b` 占位污染）；同 #18 三写入点族 | 方案 A 根治：两处硬编码 `parents[4]/workspace/outputs` → 统一可 monkeypatch 解析器（runtime_paths.outputs_root()）；一改修全 caller | 回归断言"跑全量后 workspace/outputs/ 无新增 R_sig/t_*/_pytest_*" |

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
3. **F-Py-7 leak_scan 扩 xlsx** 是交付物人话化的机器门，与 F-Py-2/3 的 leak_scan 扩项同源，一次扩；
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
