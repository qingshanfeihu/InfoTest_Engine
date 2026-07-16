# Team2 待归档内容 — 代码注释里的工程知识(建议折入设计文档)

> 来源:#3 冗余注释治理。下列注释块承载**不在 `DESIGN_dongkl_finalization.md` 内**的工程实证/机制知识。
> 按「原文抄录 + 标源 file:line + 建议归入的设计文档§」归档,供文档 owner 折入正式设计/理论文档。
> **执行说明**:本轮**未就地缩写这些注释**——多数引用更广的 §18.x/(44)/(45)/§11.x(在 DESIGN_v8/THEORY_k),
> 逐条确认目标§是否真收录需读那两份大文档(非我写权域),未确认即缩写有丢知识风险(违证据优先 #2「别猜」)。
> 故本文件作**保全快照 + 折档暂存区**;是否就地缩写由文档 owner 逐条核对目标§后定。生成 2026-07-16。

---

## A. 富矿块(逐字归档 · 建议优先折入设计文档)

### A1 · 归因机械预判只认协议级硬事实(三张 marker 表已删的实证)
**源**:`main/ist_core/tools/device/fail_attribution.py:26-35` · **建议归入**:DESIGN §0.1(语义门禁)/§B(归因)
```
归因机械预判只认**一个协议级事实**:设备语法拒绝标记 ``^``(独行,空格对齐指向
上一行出错 token)——设备明确说"这条命令我不认",确定无疑、上下文无关。

曾经这里有三张 marker 关键字表(瞬态/E/G)做预归因,已删——那是强字典猜语义
(B/C 层伪装成 A 层),实证两类误归都发生了(2026-07-02 E2E):
- 裸 "dig" 把「context 里出现过 dig 命令」当 E 可达性失败,抢掉共存的
  "failed to execute"(994928 配置被拒却归 E);
- "timed out" 把配置错引发的 dig 超时归瞬态不回流(5 个"瞬态"下一轮 100% 复现)。
设备真实回显直接交给 LLM,它看得明白;错误的预归因反而带偏(错误预标签
会显著拉低 LLM 归因准确率)。
```
*价值*:§0.1「语义门(禁)」的奠基实证——B/C 层伪装 A 层的两类真实误归数据。

### A2 · s₀ 复跑闸 + 用户裁决覆盖机械闸的写权律
**源**:`main/ist_core/compile_engine_v8/nodes.py:755-760` · **建议归入**:DESIGN §⑥ / THEORY (36) 写权律
```
V8.5 片3 复跑闸:批级诊断判 s₀(床态残留)的案,隔离复跑不可救——
复跑=h 重采样只救 π 噪声;s₀ 的 h 冻结在脏床上(run11 668030 实证:
重排复验×3 全部再翻挂)。s₀ 案不进复跑集,走排尾/床治理/矛盾呈报。
例外(run12 实弹修复,(36) 写权律:用户裁决权威>机械闸):最新 h_s0 诊断
**之后**用户答过 retry(床已处理/不认可,复跑)→ 放行——用户对床状态的
声明覆盖机械诊断;否决它=用户复跑指令被闸静默吞(run12 实测 8 案零复跑收口)。
```
*价值*:再生毒源 + 用户 retry 覆盖机械闸的写权律(run11/run12)。

### A3 · 开工必净初始化清理门 + 排除项
**源**:`main/ist_core/compile_engine_v8/nodes.py:257-262` · **建议归入**:DESIGN §⑥ / 床治理
```
初始化清理(2026-07-10 用户裁决:开工必净):有文法清理引用的残留先清后复检;
清不掉/无引用的仍走 ask。R1 12/26 崩盘(¥96)最大嫌疑=两天床残留,此门止损。
probe_failed 项不进清理(床态未知,没有清理对象;题面单独如实呈报)
maintenance_explained(C1):维护写是合法床基线——决不能被清理引用误清
mirror_sync/bed_closure_failed 是引擎内部发现、ledger_stuck 接力已试穷——
都不是设备残留,进清理只会虚占"引擎不认识"计数(2026-07-13 题面取证)
```
*价值*:开工必净门 + 哪些**不进**清理(maintenance/mirror_sync/probe_failed)——治床治理误清。

### A4 · s₀ 共享实体减法必须在 [:4] 截断前
**源**:`main/ist_core/compile_engine_v8/nodes.py:1765-1769` · **建议归入**:DESIGN §B / s₀ 归因
```
§18.14 S1(脏态合取):共享实体减去固定基础设施 IP——两案共用后端服务 IP/
接口 IP(topology 登记的合法共用地址)不是「前写脏、后读脏」污染,是测同一
被测系统的正常共用(667986 实弹:凭常量 co-reference 172.16.32.70 误贴 s₀,
掩盖自身断言缺陷)。减法必须在 [:4] 截断**前**(否则先截到基础设施 IP 会漏
掉第 5 个真污染物)。只减 IP 不碰 vlan/port/bond 名(自建对象是真污染物)。
```
*价值*:s₀ 污染判定的截断顺序坑(减法在截断前),否则误贴 s₀ 掩盖真断言缺陷。

### A5 · 字面 \n 拒绝改纠正的 token 经济学
**源**:`main/ist_core/tools/device/emit_xlsx_tool.py:1384-1390` · **建议归入**:DESIGN §0(总原则/成本轴)
```
字面 \n 自动纠正(拒绝改纠正,2026-07-04 V轮 token 取证):worker 批量在命令载荷里
写字面反斜杠+n(LLM 在 JSON 字符串里双转义),一轮 17 卷。命令语境(init 与
APV_0/test_env 的 G 列)里字面 \n 没有任何合法用途——设备/dig/shell 语法都不用它,
只可能是"想要换行"写错了。此前按必崩形态拒绝打回重做:每卷一轮 worker+grade 重做
≈1-2M token,17 卷纯纠正一个双转义 ≈20M 白烧。无损替换,返回文本注明教 worker 下次
写对;check_point 的 G 是正则([^\n] 合法),不在纠正范围。
```
*价值*:「拒绝 vs 无损纠正」的 token 经济学量化(17 卷纯纠正≈20M)。

### A6 · probe 缓存 single-flight:为何不判命令静/动
**源**:`main/ist_core/tools/device/run_case.py:192-201` · **建议归入**:DESIGN §0.1(结构保证 vs 分类)
```
probe 缓存:run 作用域 single-flight(对抗评审定稿,替掉原关键字黑名单)
为什么不判命令"静/动":volatility 在**回显字段层**不在命令名层(`show sdns host status` 命令长得像
配置 show、回显却是探活实时态),黑名单漏判 novel 动态命令→喂 stale、白名单又会把这类收进来;
且 footprint 节点无 volatility 字段可派生——"判命令静动"本仓没可靠数据源,押不赢。
改用**结构性保证**:compile 期设备只读(dev_probe 硬白名单仅 show/get、无写命令),故**一次 run 内
同一条 show、N 个并发 draft 只真探一次、其余等结果**(single-flight)……soundness 来自"作用域内
只探一次"(可证),不靠"分类准不准"(易错)。
```
*价值*:soundness 来自作用域保证而非分类准确性——「不用静/动分类」的判据(无可靠数据源)。

### A7 · 意图侧禁令机制:词表正则→语义自主的撤退路线
**源**:`main/ist_core/compile_engine_v8/briefs.py:201-206` · **建议归入**:DESIGN §0.1 / §18.13
```
§18.13 撤退第一步:意图侧禁令机制**盖章不再进 brief**(旧 <forbidden_mechanism>
块把词表正则命中喂给 worker 当提示,违反「判断用结构化事实,别退化成关键字白名单」
红线——用户判据「不能靠正则匹配」)。worker 改靠 test-point-first prompt 语义自主
判断意图可行性+主动三元组呈报;盖章仍落 intent.json(telemetry)+ emit 门仍读它做
安全 backstop……第二步:对照轮自主呈报率达标后删词表+门。
```
*价值*:关键字白名单→语义自主判断的两步撤退法(留 telemetry + 安全 backstop)。

### A8 · 意图族聚类的族键设计(量化实证)
**源**:`main/ist_core/tools/device/compile_prep.py:169-173` · **建议归入**:DESIGN §A / 生成侧
```
意图族聚类(V4 步骤3,H_G 摊销的路由依据;定理3.10)。族键=首步(配置意图)句式的
参数化(数字→N、去空白)——2026-07-04 实证:该键在 dongkl 34 case 聚出 14 族、
25/34 被多成员族覆盖、最大族 12(rr/wrr/ga 全系共享配置基线,族内骨架重合 45-51%);
曾试 _intent_similarity(词重叠+bigram)在同数据上聚出 0 族,不可用。
纯代码零语义判断:同族=配置前置的自然语言句式相同,骨架选择仍由族首 worker(LLM)做。
```
*价值*:族键=句式参数化(非词重叠)的量化对照(14 族 vs 0 族)。

---

## B. 候补富矿(建议折档 · 见源逐字)

- `main/ist_core/tools/device/structural_gate.py:669-677` → §凭证路:xlsx 级 lint 堵 run_python 直改 case.xlsx(绕过 emit),带病卷 39 秒崩全份 pytest(连两轮)。
- `main/ist_core/tools/device/batch_tools.py:738-745` → §④/echo-grounding:(43) ok(g) exec-failure→broken echo-grounding(668030)。
- `main/case_compiler/distribution_assertion.py:188-190` → §交付可读性:fallback desc 写人话,2026-07-05 抽查 29/154 违规。
- `main/ist_core/tools/knowledge/footprint_writeback.py:61-63` → §A/§S5:device_verified 第二权威源(V6 支柱2a),v12 28/28 skip 根因。
- `main/ist_core/tools/device/fail_attribution.py:242-246` → §B/(40):F1 panel 併呈机械门(§18.11 D21 活锁防护,(40) 第七类)。

---

## C. 中/低价值 (b) 候选索引(catalogued · 未逐字抄录)

约 100 块中/低价值 (b) 注释(多带日期/案号叙事,机制多已在 DESIGN_v8/THEORY_k 更广章节)完整清单见
`docs/forensics/team2_code_align.md` §2 注释治理表(逐块 file:line + 类 + 建议§ + 动作)。此处不重复逐字抄录——
它们的机制多已在广义设计文档,折档时按 §2 表逐条对目标§核对即可。**本团队不就地缩写**(理由见文首执行说明)。
