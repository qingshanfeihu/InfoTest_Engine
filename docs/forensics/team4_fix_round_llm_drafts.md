# 修复轮 LLM-Eng 线草稿 + F-LLM-1 落盘台账

## 方法论沉淀（2026-07-18，双层汇合源头层纪律，Design 9条方法清单同族归并、Py-Eng 引用）

**方法 A｜「双层汇合时源头层必须 grep 核『抽取完整性』（全分支/全条目对齐），不能凭直觉 confirm」**——机器门（如 Py-Eng leak_scan net）只守它那层（ASCII token 泄漏），守不住『源头层覆盖不全』（该中文化的没中文化）。实证：F-LLM-1 我初稿只覆盖 6/13 面板，Py-Eng confirm 请求 → 我 grep 核 questions.py = 13 分支/37 desc，catch 漏 7 面板；若假 confirm「全覆盖」双层漏一半。同族纪律：「工具成功≠落盘 grep 核」「机读账优先于记忆」——都是**用机读事实核而非凭记忆/直觉拍**。

**方法 B｜「禁令锚目标集合、别枚举通道；半枚举比不枚举更危险」**（方法#14，F-Py-7 A-主 prompt 两轮打磨实证）——堵行为禁令时,枚举工具通道**必漏**(现漏 fs_write、修 gap 又漏 run_shell——连补漏的措辞都漏);且**半枚举(列四漏一)比不列更危险**:LLM 把具体清单读成「限定这几个」、具体例示压过抽象主句,反被不全的清单框住理解。根治=**锚「目标集合」(如"这些交付物")而非工具**——"无论用什么工具/写入通道"天然闭合(cover 现有+将来新工具)。完整教学链:Design 审 F(漏 fs_write)→我补枚举(方向对修法错)→复审(措辞又漏 run_shell=枚举必漏活教材)→纯目标锚定→签 P。与 leader「只堵不疏/堵不全生绕行」同源、比「枚举要补全」深一层(**根本别枚举**)。同族入档:方法 A + 「工具成功≠落盘」+「机读账优先记忆」。

**前置检查(leader 2026-07-18 沉淀,统一 A+B)**:方法 A(完整性主张必带机读自证)与方法 B(禁令锚目标不枚举手段)其实同一根——**凡写「清单/枚举」(禁令的手段清单、覆盖的条目清单),写完即自问「这个清单我能机读证明穷尽吗?」**:能证明(如 13 面板=questions.py 全分支,grep 可穷举)→ 保留但附机读自证;**不能证明穷尽(工具通道/写入手段=开放集,新工具随时加)→ 改锚目标对象**(交付物集合),锚目标天然闭合。即:枚举完整性也要机读自证,证不了就别枚举。

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
