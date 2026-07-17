# 修复轮 LLM-Eng 线草稿（DRAFT-ONLY，待「清理完成+放行信号」才落 live 源 + 每笔四关）

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
**待译黑话词表(送 Py-Eng 对齐用)**:①"逆序 no 回放"→按相反顺序用 no 命令撤配置;②"批末床态收敛(处理)"→批次结束统一清理测试床残留;③"框架清理够不着的网络层残留"→框架自动清理管不到的网络配置残留;④"等价验证重编"→用等效验证方法重编;⑤"案尾追加恢复步"→用例末尾加一步把配置改回去;⑥"挂起"→本轮先不做(待人工/环境)。

---

**状态**:F-LLM-2 就绪(无开放项)、F-LLM-3 就绪(2 开放项待 Design)、F-LLM-1 待 Py-Eng。全部 draft-only,未动 live 源。等「清理完成+放行信号」→ 逐笔应用 + 四关。
