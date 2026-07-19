# 修复轮 LLM-Eng 线草稿 + F-LLM-1 落盘台账

## 方法论沉淀（2026-07-18，双层汇合源头层纪律，Design 9条方法清单同族归并、Py-Eng 引用）

**方法 A｜「双层汇合时源头层必须 grep 核『抽取完整性』（全分支/全条目对齐），不能凭直觉 confirm」**——机器门（如 Py-Eng leak_scan net）只守它那层（ASCII token 泄漏），守不住『源头层覆盖不全』（该中文化的没中文化）。实证：F-LLM-1 我初稿只覆盖 6/13 面板，Py-Eng confirm 请求 → 我 grep 核 questions.py = 13 分支/37 desc，catch 漏 7 面板；若假 confirm「全覆盖」双层漏一半。同族纪律：「工具成功≠落盘 grep 核」「机读账优先于记忆」——都是**用机读事实核而非凭记忆/直觉拍**。

**方法 B｜「禁令锚目标集合、别枚举通道；半枚举比不枚举更危险」**（方法#14，F-Py-7 A-主 prompt 两轮打磨实证）——堵行为禁令时,枚举工具通道**必漏**(现漏 fs_write、修 gap 又漏 run_shell——连补漏的措辞都漏);且**半枚举(列四漏一)比不列更危险**:LLM 把具体清单读成「限定这几个」、具体例示压过抽象主句,反被不全的清单框住理解。根治=**锚「目标集合」(如"这些交付物")而非工具**——"无论用什么工具/写入通道"天然闭合(cover 现有+将来新工具)。完整教学链:Design 审 F(漏 fs_write)→我补枚举(方向对修法错)→复审(措辞又漏 run_shell=枚举必漏活教材)→纯目标锚定→签 P。与 leader「只堵不疏/堵不全生绕行」同源、比「枚举要补全」深一层(**根本别枚举**)。同族入档:方法 A + 「工具成功≠落盘」+「机读账优先记忆」。

**前置检查(leader 2026-07-18 沉淀,统一 A+B)**:方法 A(完整性主张必带机读自证)与方法 B(禁令锚目标不枚举手段)其实同一根——**凡写「清单/枚举」(禁令的手段清单、覆盖的条目清单),写完即自问「这个清单我能机读证明穷尽吗?」**:能证明(如 13 面板=questions.py 全分支,grep 可穷举)→ 保留但附机读自证;**不能证明穷尽(工具通道/写入手段=开放集,新工具随时加)→ 改锚目标对象**(交付物集合),锚目标天然闭合。即:枚举完整性也要机读自证,证不了就别枚举。

**方法 C｜「亲核字段:规则说『X 从字段 Y 取』,必须亲核 Y 真含 X,不只是 Y 存在」**(方法#16,D17 per-theme 空指实证,Design 三连逮 fs_write→run_shell→per-theme)——写「数字从 engine_report 的 X 字段照抄」类规则时,只 grep「engine_report 有 totals 字段」不够,**必须亲核 totals 里真有你要的那类值**:D17 我核了 totals 存在、却没核它是否含 per-theme(listener/持久化)分类——实际 totals 全是 status 桶(n_pass/n_fail/n_broken…)、无 per-theme,规则指向不存在的 field 反而暗示 LLM「per-theme 可取」、数错根没堵。共同根(与 A/B 同族):**指向前先亲核指向物真存在/真完整**——Y 存在 ≠ Y 含 X。三连击(fs_write 漏通道/run_shell 又漏/per-theme 空指)是本条完整教学案:写规则时就亲核字段,别等评审逮。

**窗口纪律｜co-merge 执行窗 mid-save race:先重跑再查、别烧排障轮**(leader 2026-07-18 沉淀,D28 co-merge 终核实证)——收口批 co-merge 是多人同窗写盘,兄弟项声明落盘中时你的 pytest 可能撞**瞬时不一致态**(兄弟项 code 已改文案、其 test 断言未存 → 假 fail)。判据:失败在**你链外**的兄弟项文件 + git diff 证该项 test 已在工作树更新(只是你跑时还没落)。处理序=**先重跑取当前盘面**(race 常已消)→ 仍 fail 才走 git diff 溯源排障。反面=一见 fail 就开排障轮/改代码(工作准则#4:先确认是不是本次/本链引入),烧 token 且可能误改兄弟项。D28 实证:首跑 1-fail(撞 q4 `_FORM_CN` test 落盘中途)→ 重跑 101 passed,零排障轮。与「机读账优先于记忆」同族:信当前盘面重跑数、不信一次快照。

**统一原则｜「别让局部授权膨胀成它没授权的范围」(2026-07-19,#44 与 Design 互纠沉淀)**——A/B/C 亲核族 + 读评审 scope + Design 证据侧,其实同一根:**一个局部事实/指令/信号,只授权关于它自己说的那点、别外推**。三个应用面:
- **亲核(指向侧)**:规则指向 X 前,别假设 X 存在/完整(方法 A/B/C——指向物膨胀成"想当然存在");
- **读 scope(阅读侧,#44 实证)**:读评审更正,只按它实际说的改、别外推(Design 说"别拆第二个 worker 决策面"≠"删 engine 门面",我上轮把窄更正外推成宽删=27→26 over-correct,Design 澄清后回 27);
- **证据侧(Design 本场轴)**:一个信号只授权关于它自己的结论、别升级成关于世界的判决(评审时信号别僭越)。
共同反面=**膨胀**:把"这一处/这一句/这一信号"的局部真值,悄悄放大成"整体/所有/世界"的判决。收进方法清单,与「指向前先亲核指向物」同族。

**Design 复审精炼(2026-07-18)**:①**措辞精炼**——方法#16 从「规则引用数据源核存在」精炼成「**指向前先亲核指向物真含**」,更通用:覆盖**枚举/引用/条款所有「指向」**动作(不止数据源引用);②**双子型同根**——run_shell=**枚举漏**(枚举通道没亲核通道全集)、per-theme=**引用空**(规则引用字段没亲核字段真含所指),两子型共同根=指向某目标前没亲核目标真存在+真含所指;③**★前移升级(关键)**——把亲核**前移到写时**(前置检查:写枚举/引用/条款时自问「指向物真含吗/通道穷尽吗」),别等评审逮:**写时亲核=第一道防线、审出=最后防线,前移到第一道减审出轮次**,同前置检查「枚举写完自问能否机读证明穷尽」同族;④**双面坐实**——per-theme 无字段经我核 `_shared.py:206-235`(totals 全 status 桶)+ Design 核 `engine_tool.py:232` 双面确认。**双向纪律**:审方亲核字段(延伸4,最后防线)∧ 写方写时亲核(前置,第一道)——两道都亲核指向物,规则才密。

## F-LLM-1 落盘台账（2026-07-18）

- **已落 8/13 面板（27/37 desc），门全过**（语法 OK + render/questions/gather 59 passed，24 条 desc 带「对你的用例」人话后果句）:missing_teardown/forbidden_mechanism/command_existence/verification 三元组/cap/contradiction/cross_client/欠定-262。label/_tokens/_token_by_label 一字未动。
- **catch 并修承重锚**:cap 停止该案「不覆盖在案技术判断」（test_questions_ask_semantics:26 锁）——盲改断门、跑门当场抓、还原精确锚串+保人话。**欠定-262 顺序语义保留/放弃「按序命中」条件子句主动保留**（非测试锁但承载真实用户语义，不 drop）。
- **余 5 面板 → F-LLM-1b（复杂,需精细续）**:裁决(expectation_suspect)/env(env_blocked)/bed-缺清理/bed-床态/挂起(resume)——option 字典散布、与动态 q-text/self_polluter 分支/_strength 承重警告交织,需逐面板精读+跑门核锚,充足预算续（编译链精度>速度）。全 13 译文在下方 §F-LLM-1，续时照落。

---

# 修复轮 LLM-Eng 线草稿（DRAFT-ONLY 部分 → 已放行落盘，见上台账）

> 2026-07-18 · LLM-Eng。闸门(leader 开工令):清理完成+放行前**只写草稿**,每笔过四关(Theory+Design 双评审→leader redline→pytest)。本文件是草稿,**未动任何 live 源文件**。顺序 F-LLM-2 → F-LLM-3 → F-LLM-1(F-LLM-1 待 Py-Eng label=token 答复)。

## F-LLM-2（P1，独立，就绪）：config-answer when_to_use 补 SKIP when

**文件**:`main/ist_core/skills/config-answer/SKILL.md`(when_to_use 现 6-9 行,缺 SKIP=唯一 user-invocable 缺)。
**精确编辑**:在 `Trigger keywords: 怎么配置, CLI命令, 生成命令, 翻译成APV` 行后、`allowed-tools:` 前插入一行:
```
  SKIP when: the request is not about APV CLI commands — pure product-spec / concept Q&A, on-device execution (device-verify), or reviewing test cases (test-list-review).
```
**语言**:英文(LLM-facing),Trigger keywords 中文保留(裁决例外)。**验证**:标准包门 + skill 结构核 + 通用 QA「产品概念问答」不误触 config-answer。**无开放问题**。

## F-LLM-3（P1，独立，含需 Design 裁的开放项）：frontmatter 键一致化

逐文件(doc-writer 排除=DEPRECATED 待删,不给将死文件加键):

| 文件 | 现状 | 草稿改动 | 判定 |
|---|---|---|---|
| `skills/compile-attributor/SKILL.md` | 缺 user-invocable(fork) | 加 `user-invocable: false`(agent 行后) | 明确(fork 非用户直调,与 compile-worker 等 fork 一致) |
| `skills/test-list-review/SKILL.md` | 缺 user-invocable(inline 主评审入口) | 加 `user-invocable: true` | 明确(用户敲「评审」入口) |
| `skills/config-automation/SKILL.md` | 缺 user-invocable(inline) | 加 `user-invocable: true` | **✔Design 裁定 2026-07-18(leader 授权)**=true(拓扑数据 always 在盘不缺上下文/IP 替换是清晰独立用户意图/带 when_to_use+SKIP 有闸/价值>菜单噪音)。**前提护栏(落地必带)**:核并强化 SKIP 子句清楚"何时不该用"防通用配置问答误入(现 SKIP="command usage or theory…"需确认足够排除、可加"→ that's config-answer");**+ 同步 CLAUDE.md skills 表**行(现标 inline→user-invocable)**同一笔原子改**(Design 裁定 2026-07-18:CLAUDE.md skills 表节=skill 域投影**归我本轮独占**,F-Doc-1 只管 DESIGN_v8;防撞车=CLAUDE.md 按小节分域,skill 表我/非 skill Design 不撞行) |
| `agents/document-author.md` | 有 model:opus,缺 inherit-parent-prompt | 加 `inherit-parent-prompt: true` | 明确(fork agent 应继承证据纪律/忠实汇报) |
| `agents/report-generator.md` | 缺 model + inherit | 加 `inherit-parent-prompt: true` + `model: opus` | inherit 明确 true;**model ✔Design 裁定=opus**(user-invocable 报告=直接交付用户产物质量优先/skill 孔有 LLM 自由度非机械渲染/R3 裁决"花钱买质量"——轻量档留纯机械任务) |
| `agents/doc-writer.md` | 缺 model+inherit | **不改** | 排除:DEPRECATED-PENDING-RULING,删除动作归 #15,不给将死文件补键 |

**allowed-tools 不一致(4/14)——本轮不做 blanket 补**:经 #19/#30 细化,allowed-tools 是**建议性非强制**,fork skill 的工具白名单在 agent md(标准包门只强制 agent md 的 tools),inline 需限工具面时才声明。故 4/14 是**按设计(fork vs inline)非缺陷**,F-LLM-3 保持现状,已在 skill_authoring_standard §三 记明约定。若 Design 要全 inline 补 allowed-tools 另议。

**F-LLM-3 验证**:标准包门(扩键一致性断言,若 Py-Eng/Design 要加门)。**两个开放项已由 Design 裁定(2026-07-18,leader 授权)**:config-automation user-invocable=true(带 SKIP 护栏+CLAUDE.md 同步前提)、report-generator model=opus。F-LLM-3 现全部明确,无遗留开放项,放行后逐笔应用+四关。

## F-LLM-1（P0，双层，边界已锁 2026-07-18 Py-Eng 权威答·行级核）

**边界锁定**(Py-Eng nodes.py:662/660 行级核):
- **简单题**(missing_teardown/forbidden_mechanism,questions.py:110-115 等):label "改过程/改预期/改描述" **就是**引擎子串匹配 token(`nodes.py:662` `d in a`),**一字不动**;后果文案改 **description 字段**(:111/113/115,不参与匹配,零风险)。
- **三元组题**(verification_path_absent,:138-149):label 描述性、绑 `_token_by_label`(:153),**不动**;后果文案往其 description(:140/144/148)。

**关键现状(读 questions.py:105-160 实证)**:三个选项 description **已存在且半后果导向**(如 opt_process desc="案尾追加恢复步(建议:…),断言之后执行——推荐")——故 F-LLM-1 是 **refine 不是 add**:
1. 残留黑话/方法论词译人话:如"逆序 no 回放"/"批末床态收敛处理"/"等价验证重编"/"框架清理够不着的网络层残留"→ 用户能懂的后果表述。
2. 每个 description 补「**对你的用例意味什么**」一句(User 22:33 诉求)。
3. **精确目标文案对齐 User 22:33 + Test-Eng D2 的具体可判断性投诉**——执行时读取该原始观察,不臆造目标。
**labels 全程 token-locked 不动**(简单题=子串 token / 三元组=_token_by_label 绑);题面 q_text 已中文,主要动 description 层。

**验证**:重跑观测选项 description 人话后果 + redline-reviewer + **Py-Eng 核文案不误伤子串匹配**(它已 offer 帮核)。

**两层分工(Py-Eng 2026-07-18 确认,不重不漏)**:
- **我 F-LLM-1 = 源头层(primary)**:description 产干净人话,译**具体**黑话词。
- **Py-Eng F-Py-3 = 渲染安全网(net)**:leak_scan 机读 token **类级**兜底(不重复译我的具体词,兜任何残留内部 marker/token)。
- **接缝**:我把黑话词表发 Py-Eng,它 leak_scan 覆盖 token 类(比我词表宽);我清具体/它兜类级,union 无漏无重。**F-Py-3 前我给词表对齐、画线**。
**匹配安全硬约束(Py-Eng 提)**:simple 题 description **禁出现其他两个 token 整串**("改过程/改预期/改描述")——防 nodes.py:662 子串误中(匹配虽在 answer 文本非 description,保险起见 description 也不留整 token 串);放行出文案后**逐条发 Py-Eng 扫**。
**待译黑话词表(已发 Py-Eng 画线,2026-07-18)**:①"逆序 no 回放"→按相反顺序用 no 命令撤配置;②"批末床态收敛(处理)"→批次结束统一清理测试床残留;③"框架清理够不着的网络层残留"→框架自动清理管不到的网络配置残留;④"等价验证重编"→用等效验证方法重编;⑤"案尾追加恢复步"→用例末尾加一步把配置改回去;⑥"挂起"→本轮先不做(待人工/环境)。

**确认目标(读 Test-Eng D2 + User22:33 原文,不臆造)**:
- **D2(P0,全 43 面板)**:选项=引擎内部动作名(改过程/改预期/改描述、重排复验/如实降级、继续/挂起/停止),**无一句"这对你的用例意味什么"**,普通用户须懂"改过程=加观测步"等内部机制才能选。修复建议原文=选项文案改用户意图("这个用例验证步骤不够请引擎补足"而非"改过程")或每选项附一句后果人话。
- **label token-locked**→用户意图/后果文案落 **description**(label"改过程"不动),即"description 说人话意图+后果"。
- **worked example(simple teardown 面板 questions.py:110-115,草稿)**:
  - opt_process(label 改过程) desc→「让引擎在用例末尾加一步把配置改回去(按相反顺序用 no 命令撤配置),断言之后执行——推荐。**对你的用例**:被测行为不变,只是跑完把测试床恢复干净,不影响后面的用例。」
  - opt_expect(label 改预期) desc→「这条配置本身就是要测的行为、必须保留残留——按这个意图重编(残留由批次结束时统一清理测试床处理,交付报告会声明)。**对你的用例**:确认这残留是有意的、不是 bug。」
  - opt_desc(label 改描述) desc→「用例意图需人工厘清,本轮先不做(挂起)。**对你的用例**:这轮不出这个用例,留着等你确认意图。」
**全量 per-panel description 译文草稿(draft-only,label 三 token 不动、译文不含另两 token 整串)**:

**① missing_teardown(清理·,questions.py:110-115)** — 见上 worked example。

**② forbidden_mechanism(禁令·,:165-172)**:
- 改过程→「让引擎采纳它推导的等价实现来编(推荐;和原机制的差异会在交付报告声明)。若被点名的词其实不是本用例真正要用的机制(如只是计数/字段名撞名),也选这项并注明、照常编。**对你的用例**:用能跑的等价办法达到同样验证目的。」
- 改预期→「引擎给的等价方向不对——在下面自定义输入写你的等价方案,原文原样交引擎编。**对你的用例**:你来指定用什么替代办法。」
- 改描述→「确认没有效替代、必须用那个真机制——这轮先不做(挂起),等有能跑它的环境;如实写报告。**对你的用例**:这轮不出、留着等环境。」

**③ command_existence(存在性·,:185-191)**:
- 改过程→「让引擎改用本版本确实有的等价命令/写法重写 {cmds},继续编。**对你的用例**:换成本版本支持的命令达到同样目的。」
- 改预期→「保留测试过程,改用本版本能观测到的替代验证形态。**对你的用例**:测的东西不变、换个本版本看得到的方式验证。」
- 改描述→「确认本版本就没这功能、或文档相互矛盾(类似 fulldns 那次)——这轮先不做(挂起),等适用版本;文档不一致如实写报告。**对你的用例**:本版本做不了、留着等对的版本。」

**④ verification_path_absent 三元组(欠定·,:138-149)**（label 绑 _token_by_label 不动,只动 description）:
- 采纳「{proc}」→「采纳这个等价验证方法重编(引擎按它编写;和原方法的差异会在交付报告声明)。**对你的用例**:用能在这个床上跑的等价办法验证同样的行为。」
- 我给别的等价方案→「在下面自定义输入给出你的等价方案,原文原样交引擎编。**对你的用例**:你来指定用什么等价办法。」
- 挂起,如实报告→「{no_eq or obs}。这轮先不做(挂起),等能跑的环境。**对你的用例**:这轮不出、留着等环境。」
（注:label `采纳「{proc[:60]}」` 的 :60 截断致括号未闭=User23:02 报的可读性缺陷,属 Py-Eng 题面结构域已转它,非本 description 改动。）

**⑤ cap 轮次面板(轮次·,:538-544)** + **contradiction 矛盾面板(矛盾·,:632-633)**（label 绑 `_tokens` 不动,只动 description）:
- cap 继续,再修 2 轮→「授权引擎再多编两轮试试。**对你的用例**:再给它两次机会修好。」
- cap 确认产品缺陷→「实机行为是产品的问题{dc_note}——记进缺陷候选清单,这个用例按缺陷结案。**对你的用例**:判定是产品 bug、不是用例写错。」
- cap 挂起该案→「先放一放,跑完其他用例;重跑同参数时会再次询问。**对你的用例**:这轮先跳过、下次再问你。」
- cap 停止该案→「以未通过如实报告,不再花轮次(记为你的停止决定,不改变引擎在案的技术判断)。**对你的用例**:就此打住、如实记未通过。」
- 矛盾 重排复验→「把用例在卷里的顺序重排后再上机终验一轮(会把互相干扰的用例排到卷末)。**对你的用例**:换个跑批顺序再验一次,排除用例间互扰。」
- 矛盾 如实降级→「这个用例不放进交付卷,按未通过如实报告。**对你的用例**:不硬塞进成品、如实记它没过。」

**⚠ 覆盖修正(2026-07-18,grep 核发现漏 7 面板)**:questions.py 全量 = 13 面板/37 desc,上面只 6 面板。补齐余 7:

**⑥ cross_client_landing(落点·,:206-215,simple 题 token)**:
- 改过程→「改成能验证的形态:同一个客户端连发多次请求、断言它们之间的关系(而不是断言某次落到哪)。**对你的用例**:换成可稳定复现的验证方式。」
- 改预期→「你确认这里是固定映射(比如按 IPv4/IPv6 地址族分流、或固定绑定)——按确定落点重编。**对你的用例**:确认落点是定死的、不是随机轮转。」
- 改描述→「用例意图待人工厘清,本轮先不做(挂起)。**对你的用例**:这轮不出、留着等你确认。」

**⑦ 欠定·(:255-262,通用 underdetermined,simple 题 token)**:
- 改过程→「{proc_parts}(引擎按可验形态重编)。**对你的用例**:换成能稳定验证的写法。」
- 改预期→「把没法证伪的『绝对预期』改成能验证的形态(改成验关系/验归属)。**对你的用例**:期望值改成跑几次都能一致判断的。」
- 改描述→「用例描述本身有歧义/与设备行为矛盾,待人工厘清(本轮不做)。**对你的用例**:描述要测啥不清楚、留着等你厘清。」

**⑧ 裁决(:511-513,expectation_suspect,_tokens)**:
- 预期以实机为准→「以实机实际行为为准,改这个用例的预期断言后重编。**对你的用例**:承认实机对、改用例期望。」
- 确认产品缺陷→「实机行为是产品问题——记进缺陷候选清单,这个用例按缺陷结案。**对你的用例**:判定产品 bug、不改用例。」

**⑨ 环境(env_blocked·,:546-549,_tokens)**:
- 确认环境问题,停止该案→「按环境阻塞如实报告这个用例。**对你的用例**:确认是环境挡的、就此如实记。」
- 不认可,隔离复跑→「单独再跑一次验证这个判断。**对你的用例**:不信是环境问题、再单跑验证一次。」
- 确认产品缺陷→「记进缺陷候选清单、按缺陷结案。**对你的用例**:判定产品 bug。」

**⑩ 缺清理(:564-566,_tokens)**:
- 重编补自清→「重编时补上用例自己的清理步。**对你的用例**:让它跑完自己收拾干净。」
- 挂起到下批→「本批不动它,下批处理。**对你的用例**:这批先跳过、下批再弄。」
- 如实降级→「不放进交付卷、按未通过如实报告。**对你的用例**:不硬塞、如实记没过。」

**⑪ 床态(:595-597,_tokens)**:
- 挂起到下批→「把测试床整理好后下批再续跑这个用例(重跑同参数会问你要不要恢复)。**对你的用例**:等床清理好、下批再跑。」
- 床已处理,复跑验证→「你已清掉残留——引擎复跑一次验证。**对你的用例**:床清好了、再跑一次确认。」
- 如实降级→「不入交付卷、按未通过如实报告。」

**⑫ 挂起(:608-609,_tokens)**:
- 恢复处理→「回到正常流程继续修。**对你的用例**:接着修这个用例。」
- 保持挂起→「本批继续不动它。**对你的用例**:这批先一直放着。」

**★13/13 面板 description 译文全量草稿完成**(2026-07-18,含覆盖修正)。全 37 desc:label/label-token/‌_tokens 绑定 label 一字不动、simple 题(改过程/改预期/改描述、落点、欠定-262)译文不含另 token 整串、黑话译人话、每选项补后果句。动态占位 `{proc_parts}/{dc_note}/{cmds}` 保留(render 时填值)。**下一步**:全 37 条发 Py-Eng 一次性 leak_scan + 子串核 → 核签后一次落 questions.py description 笔 + F-Py-3 net(34d3dad8)已在 → 四关。

---

**状态**:F-LLM-2 就绪(无开放项)、F-LLM-3 就绪(2 开放项待 Design)、F-LLM-1 待 Py-Eng。全部 draft-only,未动 live 源。等「清理完成+放行信号」→ 逐笔应用 + 四关。

---

## D28（收口批·我的半份，2026-07-18）：compile-attributor 产用户面板中文叙述

**任务(leader,Design 裁 ⓑ 源头产中文)**:归因时除机读字段外产一句中文叙述,供 cap/env 用户面板(止损/授轮)展示——545249 实弹:用户止损判断依赖读懂各轮失败性质,英文技术散文灌面板=D28 缺陷。落笔英文(LLM-facing skill 指令)、低自由度窄桥(输出字段可精确约束)。架构依据=「源头产中文、渲染零翻译」(questions.py:38)+ F-Py-2 中文契约门同款。

### 亲核发现(前移亲核,写 prompt 前先核指向物)+ 命名裁决落定

写 prompt 前亲核代码,发现 **`user_note` 是预留休眠字段**(消费 nodes.py:1852/2329 已优先它退 fix_direction、契约 `_NARRATIVE_FIELDS`:46 已含、但 submit_attribution 从未写入),建议复用免造重复字段。**裁决结果(leader 裁 + Py-Eng 照因确认全对,2026-07-18)**:**复用 `user_note`**——引擎设计本就预留了这个位、面板早备好读它,复用=零新键+消费链零改+Py-Eng 半份缩 3 处;新增 user_summary=重复字段+死读点,劣。「前移写时亲核指向物」这次省了一个重复字段 + 两处重接(leader/Py-Eng 均确认)。Py-Eng 认了自己的 framework-capability-before-limitation 老坑(原提 user_summary 没查既有休眠布线,abs_found vs found 同型)。

### Py-Eng 结构半份(Py-Eng 域,复用 user_note)

1. `submit_attribution` 签名加 `user_note: str = ""`;2. landed `entry` 加 `entry["user_note"] = (user_note or "").strip()`(:334 附近);3. docstring Args 加 `user_note` 条。**契约门 `_NARRATIVE_FIELDS` 已含 user_note、无需改**(F-Py-2 自动保护中文);**`_claim_history_line` 无需改**(:2329 已优先读 user_note)。**evidence 设备回显归位**(env:689 + cap:669 fallback verbatim「设备回显原文:『…』」)= Py-Eng 单独做、与 user_note **正交**(user_note=中文判断叙述,evidence=raw 设备原文引用,两条独立泄漏,复用 user_note 不覆盖 evidence)。

### prompt 定稿(compile-attributor.md `## Deliver` 段,英文 LLM-facing,**已定笔 live** 2026-07-18,门 22 passed)

signature 行加 `user_note`,VERDICT 行前插一段(**含 Design 终审基准#2 趋势语义**):

```
`user_note` is a short Chinese line for the user, not the engine — what the stop-loss /
round-grant panels replay across rounds so the user can tell healthy iteration from a stuck loop
worth stopping. State this round's failure nature; once a previous round exists, also say how
this round relates to it — not an isolated single-round cause but the trend: e.g. "本轮语法拒绝,
与上轮框架异常不同因" or "断言主体已过,仅收尾段未达". Keep `fix_direction` as your English
technical record (the next round's "same approach?" check reads it); `user_note` is the
plain-language trend the user acts on (measured 545249: users read three rounds' detail to tell
healthy iteration from a livelock, and isolated English prose in the panel left them unable to).
Chinese, one or two sentences, clipped by the panel — lead with the gist; a mostly-English line
trips the narrative-field gate, so produce the Chinese at the source. Do NOT paste the device
echo into it — the panel already shows the raw device lines verbatim; `user_note` carries only
your Chinese judgement, not quoted output.
```

**设计要点**:①**趋势语义(基准#2)**——本轮性质+相对前轮变化(不孤立单轮),attributor 已读 `_prev_attribution`/repeat signature(prompt :99-106 frozen 检查用)、有前轮上下文可写趋势;**round-1 容错**「once a previous round exists」(首轮无前轮,只写本轮性质);②形态例示两条(「本轮X与上轮Y不同因」/「主体已过仅收尾未达」)是**输出形态**示例(帮 LLM 看清趋势叙述长什么样,官方鼓励),非领域答案硬规则;③与 fix_direction 分工明说(英文机读 vs 中文用户面板);④不塞设备回显(Py-Eng evidence 归位正交)、中文契约+clip+gist-first、why=545249 趋势可读;⑤always 产——面板回放全轮,早轮缺则回退英文=缺口对早轮残留。

**下一步**:Design 审措辞(基准五点)→ 与 Py-Eng ①族(写入 3 处 + evidence 归位)同窗四关合入窗口 → leader commit。

---

## 后批池(prompt 域·收口批后小笔一起,现只记档不动)

leader 裁「现在只记档不动」,收口批后作一小笔合处理。同池主题=**源头产人话/不泄内部标识符**(与 D28 user_note「源头产中文」同款理念,都是"LLM 走控制面、给用户的字段用人话、机读码/内部算子不进用户面")。

- **Z8 根治(2026-07-18,zhaiyq 实弹)**:`compile-worker` prompt 加一句——`equivalent.procedure`(给用户读的等价方法描述)**用人话,不贴框架内部算子/标识符名**。实弹:worker 写 procedure 时带 `CAPTURE_COMPARE(relation_same)`(blocks combinator + claim_kind token)泄进题面,mild 级;渲染层剥离被裁"脆"(内部名无稳定边界、剥不干净)→ **源头根治**(worker 写时就用人话)。落笔英文 LLM-facing、低自由度窄桥(输出字段形态可精确约束),形态示例给"人话长什么样"、不写死领域命令。
- **attributor source_ref 语义改良**(leader 提及、同池):待收口批后细化落点(与 Z8 同一小笔)。

**下一步**:收口批四关走完 → 后批池小笔(Z8 + source_ref)按 D28 同流程(草稿→Design 审措辞→四关)。
