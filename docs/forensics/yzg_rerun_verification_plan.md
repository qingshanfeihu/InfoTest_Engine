# yzg 重跑验证方案（Test-Eng，修复轮收尾期备，重跑放行即用）

> 用户令：先修复全部已发现问题→从 yzg 重跑。本方案=重跑时逐条对照缺陷单**销项**的机读判据表 + 观测点 + 分工 + 参数。基线=批4 中止态 `runtime/backups/batch4_zhaiyq_stopped_20260718/facts.jsonl`。
> 销项口径：**每缺陷类在 yzg 新批的 ask 面板/交付物上复现与否 = 修复实效判定**。复现=未修好（回退修复轮），不复现=销项。配合 User 体感验证双路。
> commit 映射：部分来自 leader 给定，标「待确认」的由修复轮 Eng 落 commit 后回填。

## 1. 修复销项对照表（D1-D11 + 关键 P × 修复 commit × 重跑可观测验证点）

| 缺陷 | 描述 | 严重 | 修复 commit | 重跑可观测机读验证点 |
|------|------|------|------------|---------------------|
| **D2** | 用户可判断性缺失（选项=引擎动作名，无人话后果） | P0 | F-LLM-1（选项后果导向化、走 description 层） | yzg ask 面板每选项含「对你的用例意味什么」人话；read-screen 选项行 + facts ask_shown.options 非纯「改过程/改预期/改描述」裸 token |
| **D1** | 英文 LLM-facing 泄漏 user-facing 面板 | P0 | F-LLM-1（源头中文，待）+ **F-Py-2=ee992976**（句 detector/渲染兜底）+ F-Py-3 | facts ask_shown.question **零英文技术长句**（扫 `\b[A-Za-z]{4,}\s+[A-Za-z]{4,}\s+[A-Za-z]{4,}`==0）；批4 该值=7，销项目标=0 |
| **D5** | 黑话/机读 token 泄漏展示 | P1 | F-TUI-2（截断族，待）+ 展示映射层 | 面板 header/题面无 `nd:/contra:/cap:/panel:/captured_relation/member/dist/s₀/h_s0/reflow` |
| **D6** | 「我给别的等价方案」静默空答→改预期 | P1 | F-Py-5（在途） | 测试：选该 option 不输文本→**拦截/提示**（非静默落改预期）；facts 无「option 选中但 answer=改预期」空答记录 |
| **D11** | ask 面板挂起态拦截 Ctrl-C，无中止通路 | P0 | F-TUI（面板族，押后） | 测试：面板态 Ctrl-C **能中止引擎轮**（或有显式中止键+footer 提示同步） |
| **D3** | 裸命令/参数清单 dump 进题面 | P1 | 待确认（渲染截取结论句） | 题面无整段方法清单 dump（如 sdns pool 全子命令列表） |
| **D4** | 选项 label 嵌截断技术串 | P1 | 待确认（label 人话模板） | 选项 label 简洁人话，无半句截断技术命令 |
| **D7** | fork 零产物显示「✓ 完成」假完成 | P1 | 待确认（卡片按产物落盘判定） | 零产物 fork 显示失败/未产出（非绿勾完成） |
| **D8** | 面板引文拼行渲染丢中段 | P1 | F-TUI（已接） | 面板引文完整可核证（无「www.local.co」直接接「0.md:」丢段） |
| **D9** | 题面截断（…）丢信息 | P2 | 待确认（展开/智能截取） | 关键障碍/等价要点不被 300 字截断丢尾 |
| **D10** | Other 输入态无提示 + footer 溢出 | P2 | 待确认 | 输入态 placeholder 提示「输入裁决答案」；长文本不污染 footer |
| **P1-6** | 折叠成员必败先问后落门 | P1 | 待确认（折叠成员尾6写Q&A日志/门认代表） | 折叠组非代表成员裁决**落盘成功**（facts 有 folded 成员 decision，无「裁决落盘失败」告警） |
| **P1-4/P1-7** | 测试写生产 outputs/台账 | P1 | **F-Py-9b=e37a9634(写侧)+2de2dffe(读侧)** 路径隔离治本 + F-Py-9 conftest 收尾锁 t_* | yzg 重跑后 `workspace/outputs/` **无 t_*/_pytest_*/R_sig 污染**；`runtime/ask_user_answers.jsonl` 无 ts=0 pytest fixture 混入 |
| **P2-10** | rr/wrr 跨案时序污染 | P2 | 待确认（整卷内隔离/已知限制） | 同类 rr/wrr 案整卷复验不再单卷pass整卷contradicted（或引擎降级保护生效） |
| **P1-3** | freeform 裁决意图解析降级 | P1 | 待确认 | 条件式 freeform 答案不被 token 化取最强信号跳主动作（G4 echo 已改进，核回显解析） |

## 2. 总清单 8 观测点整合（重跑时集中盯这 8 项）

1. **面板语言**（D1）：ask_shown.question 零英文技术长句。
2. **选项可判断性**（D2）：选项含人话后果，非裸引擎动作名。
3. **黑话零泄漏**（D5）：header/题面/选项无机读 token。
4. **空答拦截**（D6）：给等价方案未输文本被拦，非静默改预期。
5. **折叠落盘**（P1-6）：折叠成员裁决全落盘，无「落盘失败」。
6. **中止通路**（D11）：面板态可 Ctrl-C 中止。
7. **测试隔离**（P1-4/7）：重跑后 outputs/ 与 ask_user_answers.jsonl 无测试污染。
8. **跨案时序**（P2-10 + 会话保持互扰）：整卷复验矛盾不再假 fail 有效案，或降级保护生效。

## 3. 与 User 观察员分工（双路销项）

- **User（naive 体感路）**：抓屏审「普通用户能否读懂/判断」——面板读感、选项是否人话、有无卡顿/假完成/串框，体感复现即报。
- **Test-Eng（机读销项路）**：facts.jsonl/缺陷单逐条对照——每 D 类机读验证点是否达成，_pid 过滤当前进程，落 run_log。
- **合流**：某 D 类 User 体感未复现 ∧ 我机读验证点达成 = 销项确认；任一路复现 = 回退修复轮。审查主责在 Test-Eng。

## 4. 重跑执行参数

- **批**：yzg（26 案，autoid 前缀 2036\*），脑图 `workspace/inputs/automatic_case/yzg.txt`，产品版本 10.5。
- **checkpoint**：已清空（V8 编译 + TUI 会话），thread=v8:yzg 全新起（无断点续跑，正合「重新开始」）。
- **上机互斥**：一次一批（yzg 单批，无并行）。
- **fastlog 监控**：TUI 启动后取**真实新 PID**（`ls -t runtime/logs/compile_evidence.*.live.log | head -1` 确认对应新进程 PID，非盲取；或读 TUI 首屏 PID），`tail -f` 看过程。
- **_pid 过滤口径**（记忆铁律）：新增/复发/终态判定**必须 `_pid==当前进程`** 过滤，防混入历史 stock（46022 等旧 PID 教训）。
- **答题新纪律**（矫正令）：每 ask 面板**先四标准快评（题面可读性/选项质量/黑话英文/用户可判断性）+ 有缺陷即缺陷单记录，再答题**；答题不豁免报障。产品缺陷→缺陷候选单，非答案。
- **停批安全法**（D11 教训）：若需中途停，确认无设备 run 在途后进程级 SIGTERM（面板态 Ctrl-C 无效），非 TUI 内 Ctrl-C。
- **验证基线**：批4 中止态 `runtime/backups/batch4_zhaiyq_stopped_20260718/facts.jsonl`（对照修复前后同类面板行为）。

## 就绪状态
方案就绪。修复轮收完 + leader 放行 = yzg 重跑即启，零间隙。重跑中按本表逐条销项，新面板即时四标准快评续记缺陷单。
