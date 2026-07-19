# 准入报告料③·ask 交互缺陷单 D1-D31 + Z1-Z8 终态汇总

> 2026-07-19 · Test-Eng · 准入报告输入。源 `ist_core_ask_interaction_defects.md`（D 主单）+ `team4_user_observations.md`（Z 子症）+ git 机读 commit 归属。
> **commit 归属铁证**：四域收口批（#42）= `81fc792b` 引擎域 / `7984867f` attributor / `cd63877d` TUI / `2c6fc37d` 纯 docs；修复轮（yzg 重跑前 #32/#35/#37）逐条见下。
> **复验分档**：✅✅=已修+实弹复验（正面复验/重渲实证）；✅=已修（commit message 明证,未逐一复验落地）；◐=部分修（核心侧已修·剩余侧待行为复验）；⚠=后批池（押后/待核/leader 裁不修）。
> **2026-07-19 Py-Eng verbatim 行证核毕修订**：D13/D14 我原漏（在 59fbc326「ask 交互五项修」内、非收口批四域）→移 A 区；D11/D15 部分修↑；D21/D30 确认未修。
> **性质声明**：D/Z 全为**我方交互/TUI/引擎缺陷**,非产品缺陷；真产品缺陷候选=545097/545249（见料② unfinished 去向表,勿混置本单）。

## A 区·已修入库（24 条 D，带 commit 哈希）

| D | 症状 | 级 | commit | 复验 |
|---|---|---|---|---|
| D1 | 英文 LLM-facing 泄漏 user 面板 | P0 | ee992976(F-Py-2 detector)+76b916e3(失败卡英中映射·D1漏口封)+601a099d/54d5d55b(F-LLM-1 源头中文) | ✅✅ zhaiyq 未复现 |
| D2 | 用户可判断性缺失（选项=引擎动作名） | P0 | 601a099d(F-LLM-1 8/13)+54d5d55b(F-LLM-1b 13/13·37/37 description 后果导向) | ✅✅ 销项（最严重系统缺陷） |
| D3 | 裸命令/参数清单 dump 进题面 | P1 | 83d9c4e6(F-Py-4 清单折叠·600113 根治) | ✅ |
| D4 | 选项 label 嵌截断技术串 | P1 | 8915a94e/采纳面板固定短语 label（D19 ①②LIVE 销项） | ✅ 部分 |
| D5 | 内部黑话/机读 token 泄漏展示 | P1 | 34d3dad8(F-Py-3 leak_scan token 类级)+9891092d(去 tail6 撞) | ✅ |
| D6 | 「我给别的等价方案」静默空答陷阱 | P1 | 83d9c4e6(F-Py-5 空答 minimal·532618 本体根治)+76b916e3(数字直选落答) | ✅ |
| D8 | 面板双侧引用拼行渲染丢中段 | P1 | c8e4c4e0(F-TUI-11 长文本滚动)+8915a94e(截断族清) | ✅ 部分 |
| D9 | 题面截断（…）丢信息 | P2 | 8915a94e(截断族一次清)+83d9c4e6(clip_text:212 硬截修) | ✅ |
| D10 | Other 输入态无提示+长文本污染 footer | P2 | 76b916e3(o 输入态可见提示)+c8e4c4e0(F-TUI-11 水平滚动+光标三位置) | ✅ |
| D12 | 折叠-eq 对 panel 广播落盘失败 | P1 | 9891092d(F-Py-1 folding 门变体A·599838 根因)+59fbc326(shape-aware 21c) | ✅✅ #36 复跑 |
| D13 | _land 落盘失败仅 TUI emit 不落日志 | P2 | 59fbc326（ask 交互五项修·可观测性排障黑洞）·行证 `logger.warning("_land 失败…不落账下轮重问")` | ✅ |
| D14 | 判例 body 乱码化泄漏交付报告 | P1 | 59fbc326（render.py:100 `_ruling_summary` MULTILINE 剥 md 头）·`git log -S "剥**每一行**行首 md 头"` 命中 | ✅ |
| D16 | 挂起处理面板渲染路径缺口（短号） | P1 | 8915a94e(短号族清)+83d9c4e6(短号 md·尾号N双报告) | ✅ |
| D17 | 收官显示「4+4=8」vs 盘上 7 | P2 | d01c2a3a(D17 总结数字纪律·照抄 report[totals]) | ✅✅ LLM 摘要正确（后 D31 反转真值 42） |
| D18 | resume 未清算旧裁决→effective=false | P0 | 3dcc3af8(resume 重开欠定+§5.5.7 作废即压盖) | ✅✅ #36 |
| D19 | 重编重问缺变更上下文+题面双句号 | P2 | 8915a94e(双句号三族清+D16/D19) | ✅ ①②LIVE 销项 |
| D22 | 题面原样嵌手册内容（Z1 文件名+Z7 md 标记） | P2 | 81fc792b(题面六件 D22/Z7)+cd63877d(D22 滞后测更新) | ✅ |
| D23 | 多题面板 hint 文案-行为分叉 | P2 | cd63877d(D23 hint 对齐) | ✅ 数字键本可用·文案修 |
| D24 | 多题面板回扫显示光标重置 | P2 | cd63877d(D24 回扫游标) | ✅ |
| D25 | diagnose 状态行 s₀ 黑话堆叠（Z3） | P3 | 81fc792b(题面六件 D25) | ✅ |
| D26 | 正文交叉引用裸 autoid（Z2） | P2 | 81fc792b(题面六件 D26) | ✅ |
| D28 | cap 面板 fail 原因英文+截断（Z5） | P1 | 81fc792b(D28 user_note 全链)+7984867f(attributor user_note 产侧) | ✅ |
| D29 | cap 面板同面板数字不一致（Z6） | P2 | 81fc792b(题面六件 D29) | ✅ |
| D31 | 对账器 checker-bug（真值 42） | P0 | 81fc792b(对账器 escalated 解除感知+宪法级同口径守门) | ✅✅ 重渲 recount==claimed==42 |

## B 区·后批池（7 条 D，押后/待核/裁不修）

| D | 症状 | 级 | 处置 |
|---|---|---|---|
| D7 | fork 零产物显示「✓ 完成」假完成 | P1 | ◐ **卡片层已修 P1-10**(silent_run→黄⚠不显✓,compile-worker∧artifact_fresh is False∧¬tail_status·实弹035493/035570)；**Design 终裁**：bar 维持「跑完数」零改动(#27 四判据站住·**bar 含白跑=设计正确非 bug**)、**残留 A 卡片判据窄补入后批池新四关**(artifact_fresh=None/非 worker fork 漏网,配套不变量=**白跑必卡片⚠可见**)；活体盯零产物卡片色(✓=两轴缝隙坐实/⚠=守住)回填 |
| D11 | ask 面板挂起态 Ctrl-C 中止语义 | P0→低风险 | ◐ **静态走查坐实低风险**(TUI-Eng 代码走查)：Ctrl-C **非 SIGINT**(ink raw mode 关 ISIG=字节0x03,无 SIGINT handler)、ask 挂起态被静默吞(_handle_key:998 ask 拦截先于:1021→ask_user_view:243 return True)**无副作用**(不撕 PTY/不脏 checkpoint)、中止通路=ESC(:213 _guard_cancel 已证)；全链无 SIGINT/无中断写入点→**活体搭下批自然验(别真按)** |
| D15 | 判例 adopt 误标「你的裁决」+覆盖本轮采纳 | P1 | ◐ **误标侧已修 8915a94e**(nodes.py:704「不把判例误标用户裁决·D15 反向病」+prev_adopted 血统:419)；**覆盖本轮采纳部分待行为复验** |
| D20 | 整卷上机大批子进度行缺失 | P1 | ⚠ **leader 裁降级「不复现观察项」·不修**（zhaiyq 二分两侧 OK,考古无收益） |
| D21 | 床体检 device_build 585 vs 实际 568 | P2 | ✗ **未修**·config.py:83 现值 verbatim 568、`git log -S "10_5_0_585"` 零 commit→**后批池**（version_family 10.5 吸收,不阻塞） |
| D27 | footer 数字核验后回退 | P3 | ⚠ **leader 裁留档观察·不强制修**（入账核验正确行为,过度标注反复杂） |
| D30 | 止损盲区 subset-pass∧整卷-fail 不触冻结 | 引擎 | ✗ **未修·引擎缺陷候选**·facts.py:202 检测翻转(pass@subset→fail@delivery 都计)但不触发冻结、无 commit→**后批池**（517196 livelock 本体） |

## C 区·产品缺陷候选（本单空）

**缺陷单 D1-D31 全为我方交互/TUI/引擎缺陷,无产品缺陷。** 真产品缺陷候选 2 案（545097/545249）在**料② unfinished 去向表**,进产品复核链,性质不同勿混置本单。

## Z 系列子症终态（7 个,Z4 跳号无此编号,全并入 A 区已修 D）

| Z | 症状 | 并入 | commit |
|---|---|---|---|
| Z1 | 题面来源用原始文件名（attr_evidence.json/manifest.json/手册名·系统性） | D22 | 81fc792b |
| Z2 | 正文交叉引用裸 18 位 autoid 无尾号 | D26 | 81fc792b |
| Z3 | diagnose 状态行黑话（s₀/污染者/升格/深归因） | D25 | 81fc792b |
| Z4 | —（跳号,无此编号） | — | — |
| Z5 | cap 面板各轮判断英文句+截断 | D28 | 81fc792b+7984867f |
| Z6 | cap 面板 [重编2次] vs [已重编3轮] 数字不一致 | D29 | 81fc792b |
| Z7 | 手册引文原始 markdown 标记（`**`/`_.._`）泄题面 | D22 | 81fc792b |
| Z8 | 机读 token 泄选项/等价方法（captured_relation） | D5 族 | 34d3dad8(leak_scan)+601a099d(F-LLM-1 中文化) |

## 终态口径（供准入报告缺陷覆盖节）

- **31 条 D**：A 区已修 **24**（✅✅ 实弹复验 **6**=D1/D2/D12/D17/D18/D31；余 **18** commit 明证,含 D4/D8 部分修 + D13/D14 Py-Eng 行证补入）+ B 区后批池 **7**（leader 明裁不修 2=D20/D27；确认未修 2=D21/D30；◐ 部分修·活体待下批自然验 3=D7/D11/D15——D7/D11 经 TUI-Eng 静态走查：D11 Ctrl-C 坐实低风险(非 SIGINT·被吞无副作用·ESC 是通路)、D7 卡片层已修 P1-10 + **Design 裁毕**(bar 维持跑完数零改动·含白跑非 bug；残留 A 卡片判据窄入后批池新四关·配套不变量=白跑必⚠可见)）。
- **7 个 Z 子症**（Z4 跳号）全并入 A 区已修 D，随源头 commit 落地。
- **系统性两大缺陷（D2/D1）源头修复完整达成**：F-LLM-1 全 13/13 面板 37/37 后果导向中文化（D2）+ F-Py-2/3 detector+leak_scan 双层闭环（D1/D5）——zhaiyq 收官重跑正面复验销项。
- **诚实边界**（Py-Eng verbatim 行证核毕修订）：A 区 ✅（非 ✅✅）18 条系 commit message 明证、未逐一实弹复验落地；B 区经核毕——D11/D15 ◐ 部分修（核心侧已修·剩余侧待行为复验）、D7 待 TUI 复验、D20/D27 leader 裁不修、D21/D30 确认未修（`git log -S` 零 commit 佐证）。**我原漏 D13/D14**（在 59fbc326「ask 交互五项修」内,只查收口批四域遗漏了 D12 补修轮）已据行证补入 A 区。
