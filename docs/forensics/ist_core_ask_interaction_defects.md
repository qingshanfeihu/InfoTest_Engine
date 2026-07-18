# ist-core ask 交互缺陷单（Test-Eng 缺陷视角）

> 缘起：用户批评「测试 mate 容忍度太高，ist-core 提问的这些早该报 bug」。任务 #2 原始要求含「审查每个 ask 面板前端交付质量」，标准是**普通用户能读懂**（非「我能读懂」）。本单按测试工程师缺陷单标准记录（复现场景+预期 vs 实际+严重级+修复建议），视同产品 bug。
> 状态：**建单中**（批 1-4 全量回溯于救赎轮期间补全；User 观察帧为素材、按缺陷单标准重写+补漏报）。审查主责在 Test-Eng。
> 严重级：P0=阻断用户正确决策/致误答；P1=用户读不懂但可绕；P2=体验瑕疵。

---

## D1【P0·英文 LLM-facing 文本泄漏到 user-facing 面板】
- **复现**：批4 矛盾面板 532519（contra）题面直接嵌英文整句「MX cross-type query verification must happen BEFORE clear sdns all — the clear destroys sdns config (including the IPv6…」；cap/escalated reason 全英文「two consecutive rounds failed with the same signature」「no output from fork (tail=none); fork may have hit the wallclock watchdog」。
- **预期**：user-facing 面板（题面/选项/reason）一律中文（CLAUDE.md 语言分层铁律：user-facing 中文）。
- **实际**：worker/引擎产的英文 fix_direction/reason/attribution 原文直灌面板，中英混杂。
- **严重级**：P0（普通用户读不懂英文技术句=无法据以判断，被迫盲答或误答）。
- **修复建议**：面板渲染层对 fix_direction/reason 等自由文本字段做中文化（LLM 产出即要求中文，或渲染前过翻译）；机读 token 归机读、展示归中文。

## D2【P0·用户可判断性缺失：选项要求引擎专家知识】
- **复现**：欠定面板「改过程/改预期/改描述」、矛盾面板「重排复验/如实降级」、cap 面板「继续再修2轮/挂起/停止」——无一句解释这些选择对普通用户意味什么、选错的后果。
- **预期**：选项应让普通测试用户（无 V8 引擎知识）能据用例本身判断；或每选项附「这对你的用例意味着什么」的人话说明。
- **实际**：选项是引擎内部处置动作名，用户须懂「改过程=加观测步」「重排复验=卷序重排」「reflow」等内部机制才能选。
- **严重级**：P0（用户无法做知情决策=ask 面板的核心目的落空）。
- **修复建议**：选项文案从「引擎动作」改为「用户意图」（如「这个用例的验证步骤不够，请引擎补足」而非「改过程」）；或每选项附一句后果人话。

## D3【P1·裸命令/参数清单 dump 进题面】
- **复现**：批4 600113 题面「dev_help 实测确认：sdns pool 子命令仅支持 cname/mx/service/name/member/ga/monitor/health/fallback/failover/preempt/resort 等方法」——把设备能力清单整段 dump。
- **预期**：题面给结论（本床不支持 TXT 池），不 dump 数据清单（数据按引用、不入用户视图）。
- **实际**：worker 探测原文（含完整方法清单）直灌题面。
- **严重级**：P1（信息过载、用户读不到重点，但不致误答）。
- **修复建议**：题面渲染截取结论句，清单类数据折叠/移除。

## D4【P1·选项 label 嵌截断技术串】
- **复现**：批4 589592/600113 采纳类选项 label=「采纳「改用单pool配置（仅产生一条会话记录），不带query_type执行 `no sdns session persist」」——label 直接截断在半句技术命令。
- **预期**：选项 label 简洁人话（如「采纳引擎给的等价验证方案」），技术细节放题面/展开。
- **实际**：等价方案原文前 N 字符塞进 label 并硬截断。
- **严重级**：P1（label 读不通，但选项语义可从上下文猜）。
- **修复建议**：label 用固定人话模板，等价原文放题面区。

## D5【P1·内部黑话/机读 token 泄漏到展示】（原 P2-7 升级）
- **复现**：面板 header「欠定·组2案」「矛盾2519」；question_id 前缀 nd:/contra:/cap:/panel:；断言形态词 captured_relation/member/dist；诊断词 s₀/h_s0/reflow/escalated 出现在 user-facing 文案。
- **预期**：user-facing 只出现中文人话，机读 token 留在 facts.jsonl。
- **实际**：机读键/内部术语直接进面板文案。
- **严重级**：P1（用户读不懂「断言形态按 member」「s₀」）。
- **修复建议**：展示层建立机读 token→中文人话映射表，渲染前替换。

## D6【P1·「我给别的等价方案」静默空答陷阱】（原 P1-5）
- **复现**：多题面板选「我给别的等价方案」option 但未按 o 进 Other 文本态→静默落 token=改预期（不带用户方案），引擎据此直接编写而非 re-ask。批4 532618 实证踩坑。
- **预期**：选中带 Other-text 语义的 option 却没输入文本时，拦截并提示「按 o 输入你的方案」，或空文本回退 re-ask。
- **实际**：静默降级为改预期，用户以为给了方案实则没有。
- **严重级**：P1（致误答/案被错误处置，但 re-ask 机制可补救）。
- **修复建议**：见 P1-5；option 选中而未进文本态时 emit 拒绝空等价并回退。

## D7【P1·fork 零产物显示「✓ 完成」假完成】（原 P1-2）
- **复现**：fork 未 emit、无尾块（零产物）仍显示「✓ 编写·xxx — 完成」；引擎判 escalated 时用户看到绿勾。批4 escalated 案同理。
- **预期**：「完成」应区分「产物落盘」与「进程结束」，零产物显示失败/未产出态。
- **实际**：进程结束即绿勾「完成」。
- **严重级**：P1（误导用户以为成功）。
- **修复建议**：卡片状态按产物落盘判定，非进程退出。

## D8【P1·面板双侧引用拼行渲染丢中段】（原 P1-1）
- **复现**：ask 面板引文拼行丢中段（「www.local.co」直接接「0.md:」，实机回显尾+手册文件名不可见）；疑含 \t 文本 wrap 相关。批1 035413 实证。
- **预期**：引文完整显示，用户可核证出处。
- **实际**：中段字符丢失。
- **严重级**：P1（用户无法核证引文）。
- **修复建议**：见 P1-1（TUI-Eng 已接）。

## D9【P2·题面截断（…）丢信息】
- **复现**：批4 gather 516576/517112/600113 等题面/选项被截断以 …（question 存 facts 时 [:300] 截断 + 展示再截）。
- **预期**：关键信息（障碍、等价方案要点）不被截断，或提供展开。
- **实际**：题面 300 字符截断，长障碍描述丢尾。
- **严重级**：P2（可从 facts 补全，但用户看不到全貌）。
- **修复建议**：展示层支持展开全文，或智能截取保留结论句。

## D10【P2·Other 输入态无提示 + 长文本溢出污染 footer】（原 P2-1/2-2）
- **复现**：Other 输入态底部框 placeholder 仍「输入消息」无「正在输入裁决答案」提示；长文本输入溢出污染 footer 行（token 计数错乱拼接）。
- **严重级**：P2（体验瑕疵）。
- **修复建议**：见 P2-1/P2-2（TUI-Eng）。

---

## D11【P0·ask 面板挂起态拦截 Ctrl-C，用户无中止通路】（停批实证，leader 令补）
- **复现**：批4 停批时引擎轮 suspended 在 ask 面板 interrupt 上，按 footer「ctrl+c abort」提示发 Ctrl-C（单+双次）均被面板 key handler 拦截无效——挂起态 interrupt 无运行操作可 abort，Ctrl-C 天然失效；esc 会让 interrupt 返空致引擎续轮（危险）；Ctrl-D 因全局框有文本不干净退。**用户在 ask 面板上没有任何安全中止通路**，最终只能进程级 SIGTERM 硬停。
- **预期**：ask 面板挂起态应放行 Ctrl-C 中止整个引擎轮，或提供显式「中止/退出」键；footer 的「ctrl+c abort」提示在面板态应真实可用。
- **实际**：footer 承诺 abort 但面板态吞掉 Ctrl-C，用户被困在面板（只能答题或硬 kill）。
- **严重级**：P0（用户无正常中止通路=交互死角，尤其长批想中途停时）。
- **修复建议**：interrupt 挂起态放行 Ctrl-C（归 F-TUI 面板族，leader 已入修复池）；或面板显式中止键 + footer 提示同步。

## D21【P2·引擎床体检 device_build 解析错位（记 585、实际 568）】（build 研判坐实）
- **复现**：两轮 engine_report（首轮 07-17 + 本轮重跑）device_build 都记 `10.5.0.585`，但跳板机全 138 个 report 目录 build 标签 ALL `10.5.0.568`（自 2026-06-11、零 585）——引擎床体检 build 解析**一致性错位**（记 585、框架/设备实际 568）。
- **根因**：引擎床体检读 build 的源/解析与框架 report-dir 命名（真跑时 build）不一致。非外部重刷（设备稳定 568）。
- **严重级**：P2（version_family=10.5 家族吸收 585/568 差、zhaiyq 检索不受影响；但引擎自报 build 不实=可观测性/审计失真）。
- **修复建议**：Py-Eng 查床体检 build 解析源（show version 实际 568 为何被记成 585）。收口批修。

## D20【P1·整卷上机大批子进度行缺失（TUI 渲染/事件流缺口）】（User observer 捕 + 跳板机只读核实）
- **复现**：yzg 续跑 #36 整卷 25 案上机 dispatch 后，TUI 无 `Ns/900s` 上机子进度行、token 冻结（对照子集 5 案/轮次6 整卷都有活跃子行）。**跳板机 103 只读探针坐实设备侧真在推进**：报告目录 `2026-07-18-23:01:46-…/ist_staging_sdns/` 逐 autoid 日志 23:01→23:07 线性落（655262/668044 等 RouterA/B+apv 回显齐），run 正常跑完非卡。故子进度行缺失=**TUI 渲染层没订到整卷上机的子进度事件流**（设备真跑但界面无反馈）。
- **严重级**：P1（长上机批用户误判卡死、可用性缺口；实证 User 就误报了「疑卡住」）。
- **修复建议**：TUI-Eng 查整卷上机路径的子进度事件订阅（对照子集路径有子行=事件流在子集路径发、整卷路径漏）。
- **观测法教训**：设备侧 run 活性判读=跳板机 ps pytest 进程+staging 日志 mtime（run-identity 判据），非只看 TUI 子行——子行缺失≠run 卡，须跳板机核实。

## D19【P2·重编重问缺变更上下文（UX 候选）+ 题面双句号】（User observer 捕，收口批）
- **复现**：655233 采纳面板（重编产生的新欠定 `nd:…:3:` 非恢复重问）——用户「怎么又问了、且问得和上次不一样」困惑。判定**非缺陷**（这轮无 reopened 载荷、本题是重编新欠定非恢复重问、语义一致；⑤重问前缀留未来真 resume 场景）；但用户困惑真实=UX 候选（重编重问题面带一句「本题是重编后新发现的欠定」变更上下文）。另：题面 `。。` **双句号**（同族渲染，多处，句末拼接多一个句号）。
- **严重级**：P2（UX 优化+渲染瑕疵，非阻断）。押收口批。
- **①②LIVE 销项成**（User observer 确认）：采纳面板**固定短语 label + 全号 aid** 已生效（对照 D16 挂起处理面板短号缺口，采纳 gather 路径已修）。

## D17【P2·TUI 收官显示「4+4=8」vs 盘上 7 数目矛盾】（User observer 捕）
- **复现**：yzg 续跑 mini 批收官，TUI 收官文案显示未完成案数「4+4=8」，但盘上一致=7（delivery_report「19+7」、unsuccessful_cases.md「共7个」、unfinished/=7）。疑收官显示分组渲染重复归类（哪案被算两次/655203 分类漂移）。
- **严重级**：P2（显示矛盾、盘上正确、不影响交付）。
- **修复建议**：Py-Eng 查收官显示分组计数逻辑（TUI 层非盘上）。押后。

## D18【P0·resume 未清算旧裁决→恢复处理 effective=false→resumed 案回不到欠定】（#36 分诊坐实，走向②）
- **复现**：yzg 续跑 mini 批，7 挂起案答「恢复处理」，facts decision answer=恢复处理 + resumed 事实落——但 **decision_outcome 全 14 条（7案×2）`effective: false`**。resumed 后 needs_decision=0/authored=0，采纳 gather 从未 setup；收官 668000 suspended 仍是旧的 `_pid:47666 user_decision:改描述`。
- **根因**：resume 未作废旧 adopted:eq 改描述 decision，旧裁决 continue 管案命运（案读「改描述=本轮不产出」→编写0次→再挂），resume 决定被判 effective=false。
- **严重级**：P0（resume 机制失效、跨批续跑挂起案回不来、阻断 D12 验证）。三铁律②「effective=false 零放过」命中。
- **修复建议**：Py-Eng——①resume 作废/删旧 adopted decision；②resumed 案强制重生成 needs_decision；③修 emit_decision 门对 resume 类型的通道（同 D12 家族路径覆盖缺口）。修后 #36 重跑。

## D16【P1·挂起处理面板渲染路径缺口（B/F-TUI-2 未覆盖）】（User observer 首捕，我快评漏）
- **复现**：yzg 续跑恢复问询面板（「批如何处理?恢复处理/保持挂起」，另一渲染构建路径）三点：①题面旧**短号 `…655248`**（无全 18 位 aid，B 全 aid 修复未覆盖此路径）②括号描述**截断** `(1.添加一个sdns listener ip为h)`（D9 族，截半句）③题面/标签**号码形态不一致**（题面 6 位 vs header `[挂起5248]` 4 位）。
- **预期**：全渲染路径号码形态统一（全 aid 或统一短号规则）、描述不截断——B（全 aid 显示）+F-TUI-2（label 短语）应覆盖此挂起处理面板路径。
- **严重级**：P1（路径覆盖面缺口，同族缺陷漏一条渲染路径）。
- **修复建议**：B/F-TUI-2 姊妹项——Py-Eng 定位恢复问询面板渲染构建点，套用同一全 aid/label 规范。押后窗口，不阻塞本批。
- **我的快评 gap（认领）**：此面板我四标准快评标 D2/D1/D5✓，**漏了短号/截断/号码形态**（题面可读性维度失查）——User observer naive 视角补到。教训：四标准「题面可读性」须细查号码形态一致性+描述完整性，非只看选项人话（D2）。

## yzg 重跑·四标准快评实录（销项验收场，先于答题）

**gather 面板（8 欠定，655/668 族床限制案）四标准快评**：
- **D2 用户可判断性 → 已修 ✓✓（最严重缺陷销项）**：选项现带「**对你的用例：…**」人话后果说明——Q1(655203)选1「你来指定用什么等价办法」/选2「这轮不出、留着等环境」；用户无引擎知识也能懂每选项后果。F-LLM-1 选项后果导向化生效，对照批4 裸「改过程/挂起」token 的可判断性缺失，**D2 销项**。
- **D1 英文泄漏 → 未复现 ✓**：Q1 题面全中文、无英文技术长句（对照批4 该类面板嵌「pyATS Errored…」「MX cross-type query…」英文句 7 处，销项目标 0）。后续问题继续验。
- **D5 黑话 → 大改善、残 1 轻微**：header「欠定·655203」非「nd:」✓；但题面残留工具名 `compile_report_underdetermined`（worker 引用意图指引时带出，轻微泄漏，非阻断）。**D5-残**：题面仍可能带 compile_* 工具名，建议渲染层再滤一层。
- **D3 裸清单 dump / D4 选项 label 截断 → 未复现 ✓**（选项 label 简洁人话，无半句技术串）。

（逐题续记；User 体感路并行验读感。）

**yzg gather 新缺陷发现（P1-6 邻近 + 可观测性）**：
- **D12【P1·折叠-eq 对 panel 广播落盘失败】**：668000(代表)+668044(folded_into 668000)、verification_path_absent + equivalent=yes + test_point=yes（三元组-eq），走 panel 路径双双「裁决落盘失败」。**非批4 599838 同因**（尾6 都在 ask_user_answers.jsonl、先问后落门过）、**非 adopted×门**（adopted noeq/eq 案全落盘成功）、**非单 eq 案**（panel-eq 非折叠 655262 落盘✓）。区分变量=**panel+折叠+eq 三条件叠加**。疑折叠广播 `_land`(nodes.py:714-715) 对代表+成员的 form门/eq 校验交互。归 Py-Eng。下轮 re-ask 恢复。
- **D13【P2·_land 落盘失败仅 TUI emit 不落日志】**：`_land` 失败经 `sh.emit`(nodes.py:554) 只显 TUI，**不写 fastlog/tui.log**，Py-Eng 排障看不到确切 error 文本=可观测性缺口。建议补 logger 落盘（含 compile_user_decision 返回的 error 原文）。
- **D14【P1·判例 body 乱码化泄漏交付报告】**：unsuccessful_cases.md 里 668000/668015/668030/668044 的「裁决要点」= 判例 ruling body 原样拼进用户报告，内含 **`## Revision @2026-07-15T04:15:09`（批3 markdown 头）+ 采纳「…write memory→」（截断）+ 挂起,如实报告 + 采纳「将forward)。（乱码截断）** 多修订版杂糅。用户报告出现内部 markdown 头/批3 时间戳/截断技术串=脏泄漏。归 Py-Eng（渲染层判例 body 应取结论句、不原样拼多修订史）。
- **D15【P1·判例 adopt 误标「你的裁决」+ 覆盖本轮采纳】**：668000/668044 交付报告写「你的裁决:改描述→挂起」，但我本轮实选 option 1 采纳（worker 新 sound 等价）——判例（`adopted:eq--forbidden-mechanism--10-5` 批3 改描述 ruling）粘性 auto-adopt 改描述**覆盖了我的采纳**，且报告把判例决定**误标成「你的裁决」**（misattribution）。双问题：①判例覆盖本轮更优新等价（旧 ruling 盖新解）②报告 provenance 误标（adopted 判例 ≠ 你的裁决）。归 Py-Eng（判例覆盖逻辑 + provenance 渲染）。

## 批 1-4 全量面板回溯（补作业，从各批 facts.jsonl 机读提取）

**面板总量 43**：批1=2 / 批2=14 / 批3=6 / 批4=21。**缺陷分布（机读特征扫描）**：

| 批 | 面板数 | 含英文长句 | 黑话 token | 我的处置分布 |
|----|-------|-----------|-----------|-------------|
| 批1(CNAME…dongkl) | 2 | 0 | 0 | 缺陷候选1(035413 条件答) |
| 批2(dongkl) | 14 | 1 | 0 | 预期以实机为准2/改过程7/改预期1/继续1/降级1 |
| 批3(yzg) | 6 | 2 | 0 | 改描述/改预期/挂起/恢复(668/655 族) |
| 批4(zhaiyq) | 21 | **7** | **3** | 预期以实机为准3/改过程5/改描述2/挂起1/停止1/重排复验2 |

**英文长句泄漏在批4 激增（7 处）**——因批4 会话保持类案的 worker fix_direction/attribution 更长更技术，直灌面板未中文化。典型（D1 实证）：
- 561213 cap 题面：`pyATS Errored (protocol-hard signal: execution-failure marker in a passing case's log…)`
- 589432 cap 题面：`Change step10 assertion polarity: ALL DOES delete A-type session…`
- 532519 contra 题面：`failures: (1) CNAME within-new-cycle persistence: step15 expects two post-timeout IPv6 CNAME requests to…` + `MX cross-type query verification must happen BEFORE clear sdns all — the clear destroys sdns config`
- 批2 778012 cap：`The no sdns host method / sdns host method rr re-init sequence…`
- 批3 668 族亦含英文 fix_direction。

**逐缺陷类型批1-4 证据汇总**（D1-D10 见上，此处补跨批实例）：
- **D1（英文泄漏）**：批2×1 / 批3×2 / 批4×7 = 至少 10 处 user-facing 面板嵌英文技术句。**系统性**：worker/引擎产的 fix_direction/reason/attribution 是英文（LLM-facing 合规），但直灌 user-facing 面板未过中文化层——违语言分层铁律。
- **D2（用户可判断性）**：**全 43 面板普遍**。选项恒为引擎内部动作名（改过程/改预期/改描述 ×多数、重排复验/如实降级、继续/挂起/停止/缺陷候选、预期以实机为准/确认产品缺陷），无一附「这对你的用例意味什么」人话，普通测试用户无 V8 引擎知识无法知情决策。**最严重系统缺陷**。
- **D5（黑话）**：批4×3（header「欠定·组2案」「矛盾2519」「裁决9592」；question_id nd:/contra:/cap:/panel:；断言形态 captured_relation/member）。批1-3 facts 存的 question 里黑话少，但展示层 header 全批都有。
- **D6（空答陷阱）**：批4 532618 实证（选「我给别的等价方案」未按 o→静默改预期）。
- **D3（裸清单 dump）**：批4 600113（sdns pool 子命令全清单）。
- **D4（选项 label 截断技术串）**：批4 589592/600113 采纳类 label。
- **D8（引文拼行丢中段）/D9（题面截断）/D7（假完成）/D10（输入态提示/footer 溢出）**：见上，跨批复现。

**系统性结论（交修复轮）**：ask 面板前端交付有**两个跨全批系统缺陷**——(1) **D2 用户可判断性**：选项是引擎动作名非用户意图，普通用户无法判断（最高优先，属 ask 面板设计层）；(2) **D1 英文泄漏**：worker 英文自由文本直灌面板无中文化层（批4 激增证明会话保持等复杂域更严重）。其余 D3-D10 为渲染/交互层瑕疵。修复优先级：D2≈D1 > D5/D6 > D3/D4/D7-D10。

**User 观察员观察帧并入**：User 抓屏所报（串框污染、假完成、假交付误读等）已按缺陷单标准并入 D6/D7 及本 run_log P1/P2；User naive 视角与本专家缺陷单互补，审查主责在 Test-Eng。

> 状态：批 1-4 机读全量回溯**已完成**（43 面板）。可随 #3 终检交付。后续若重跑产生新面板，即时按四标准快评续记。
