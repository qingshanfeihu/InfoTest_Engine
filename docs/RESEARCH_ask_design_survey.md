# 调研：Ask 子系统的封装与流转——Claude 官方 × MiMo-Code(opencode) 双源对照

> 2026-07-10。目的：THEORY §2.6 十参数落地前的设计调研（用户指定两参照）。
> 源：①Anthropic 官方五篇（implement-tool-use / writing-tools-for-agents /
> skill best-practices / structured-outputs / building-effective-agents）；
> ②MiMo-Code 浅克隆 `packages/opencode/src`（Zod+Effect+AI SDK 栈，MiMo=Xiaomi 一等 provider）。
> 本文只记机制与出处；数据按引用。

## 一、两源共识（可直接定案的设计规则）

1. **json_schema 与 strict 工具的分工**（官方判据原话）："JSON outputs control what Claude
   says; strict tool use validates how Claude calls your functions"。专职孔的终产物 →
   json_schema 结构化输出；agent 循环内的动作 → strict 工具。**硬坑**：extended thinking
   下 `tool_choice: any/tool` 直接报错——思考默认开的本项目,"保证产出"只能靠结构化输出,
   不能靠强制工具调用。MiMo-Code 的等价实现：合成 StructuredOutput 工具 + `toolChoice:
   required` + 有界重试(retryCount=2)+`<system-reminder>` 修复推动(`session/prompt.ts:2416,
   3036,4007`)——作为 native response_format 不可用时的备胎模式。
2. **检索工具少而整**：官方反对一源一工具("fewer, more capable tools reduce selection
   ambiguity");MiMo-Code memory 工具单口 BM25+scope/type 过滤(`tool/memory.ts`)。
   → K_ought 四源(spec/人写先例卷/bug 裁决/决策史)收编为**一个** `kb_intent_search`,
   `source_type` + `response_format: concise|detailed` 两个 enum 参数(concise 实测省 ~2/3 token)。
3. **问前门控是图的条件边不是 LLM 自觉**：官方 workflows-vs-agents 明确("predefined code
   paths for predictability");与本项目"LLM 永不当胶水"公理同构。
4. **poka-yoke 防错参数**：证据引文机械校验"必须是源文件 verbatim 子串"(官方 SWE-bench
   绝对路径案例;本项目 submit_attribution 门同型);校验失败的错误信息=prompt 工程
   ("点名字段+期望形态+最近似匹配"),MiMo-Code 以 RecoverableError+prettified-Zod 承载
   (`tool/tool.ts:110`,`tool/recoverable.ts`)——模型自纠而非硬失败。
5. **schema 硬规则**（官方）：扁平、全 required+null 可空、additionalProperties:false、
   enum 全小写且解析大小写不敏感、schema 全局一版稳定(文法缓存按结构失效——动态 enum
   候选放数据区不进 schema)、消费端容错 refusal/截断两种 stop、strict 工具 ≤20/请求。
   MiMo-Code 实证补充：众多 provider 拒 root anyOf → discriminated union 落 provider 前
   要拍平(`provider/transform.ts:1280`)。
6. **回写 plan-validate-execute**（官方 skill 实践）：先落盘 → 验证器(verbose 错误,点名
   字段列合法值) → 才提交;高风险操作(打断人类正是)必走此型。
7. **语义 slug 键**：官方("resolving UUIDs to semantically meaningful language significantly
   improves retrieval precision")→ 判例键用可读 slug(意图签名×冲突形态×版本族),不用裸 hash。
8. **skill 封装**：frontmatter description=when-to-use;模板/格式规则放 references/ 按
   base-dir 引用不内联;MiMo-Code compose/ask SKILL.md 的问询策略值得抄:
   "一事一问;空 options=自由文本;问了就别在散文里复述"。

## 二、MiMo-Code 独有可移植件

| 模式 | 位置 | 移植落点 |
|---|---|---|
| 问询=阻塞在工具内的 Deferred + pending Map + bus 事件;teardown 终结器 fail 全部 pending(永不挂死);超时→带可行动反馈的自动拒绝 | `question/index.ts:114-193` | 我们已有同构底座(interrupt+ask_user `_PENDING`);**要补的是 teardown 终结器与超时反馈语义** |
| RejectedError vs **CorrectedError{feedback}** 二分——"硬拒"与"纠正我"分开 | `permission/index.ts:102-122` | 正是"确认/纠正/缺陷"三枝的 correct 枝:自由文本反馈=纠正,进事实流 |
| 工具返回双通道 {output 给 LLM 的散文, metadata 给程序的结构} | `tool/tool.ts:31-53` | 我们既有形态(散文+落盘 JSON)——确认并命名为标准 |
| 评审官形态:Verdict{ok, reason:"quote evidence"} generateObject 后再 parse 双验 | `session/goal.ts:33-218` | 归因结论/采信判定的输出形 |
| 内容寻址 journal + 从头重放替代续跑 | `workflow/persistence.ts`,`runtime.ts:944` | 我们已有(facts 幂等键+checkpoint+run_done)——外部印证,不需动 |
| decideAskRouting 纯函数:这次暂停由谁答(交互人/父编排/自动拒) | `agent/config.ts:15-36` | 无人值守/嵌套场景的预留位,暂不建 |

## 三、本仓已实证底座（新件必须坐其上）

- strict 工具绑定通道 `IST_TOOLS_STRICT`(`agents/_llm.py:298`);
- 结构化输出现状:仅 json_object(dream/kms)——**json_schema 严格模式是待接的增量**;
- ask_user 面板契约:questions[1-4]×{question,header≤12,options 2-4,multiSelect},
  答案 `"Q"="A"` 文本回喂,`_PENDING` 登记(TUI 消费);
- 原文子串机械门(submit_attribution evidence/device_quote);
- FTS5+BM25 检索底座(kb_memory_search:CJK bigram/相对分数地板)——kb_intent_search 复用;
- facts.jsonl 幂等键+断点续跑=journal 重放的同构物。

## 四、十参数 → 封装与流转方案（骨架,待设计评审）

**工具三件套**(命名空间化;description 必含"何时不该用"):
1. `kb_intent_search(query, source_type∈{spec,precedent_case,bug_adjudication,decision},
   version_family, response_format∈{concise,detailed})` → hits:[{slug,title,quote,
   anchor:{version,ts,lineage}}]。检索触发条件(A9)=同形判据命中或 verifiability 欠定,
   由图/verifiability 工具门控,非每案常规动作。
2. `ask_user`(既有,不新造)——面板由引擎从 AskPanel 结构渲染。
3. `kb_adjudication_write(key:{intent_signature,conflict_shape,version_family}, ruling,
   anchor:{version,ts,lineage:"user_proxy"}, evidence_refs)`——**人源专属**(A5:仅引擎在
   收到 decision 后调用;fork 工具白名单不含);先落盘过验证器(key 碰撞/引文子串/schema)
   再提交(plan-validate-execute)。

**AskPanel schema**(专职孔 json_schema 产出;全 required+null、扁平、additionalProperties:false):
```
{intent_signature, conflict_shape∈{manual_vs_device, expected_vs_observed,
 method_vs_implementation, ordering_vs_persistence, other},
 version_family,
 sides:[{source_ref, quote, anchor|null}],          ← 双源引文,quote 过 verbatim 子串门
 retrieval_receipt:[{slug, outcome∈{miss,hit_conflicting,hit_adopted_blocked}}], ← 必填:空手问在 schema 层不可能(A9/检索先行)
 hypothesis,                                        ← 引擎的理解 Z(中文,唯一自由文本)
 ask}                                               ← 一句中文问句
```
面板渲染:question=差异呈报+理解 Z;options=[确认,按此继续/纠正(经 Other 自由输入=
CorrectedError 语义)/确认产品缺陷];decision 事实存小写 token confirm|correct|defect;
挂起/停止=TUI 常驻特权不占 options。落盘 ask_panel.json→验证器→才 interrupt。

**采信判定**(A10/A11,引擎机械判非 LLM):检索命中记载间无互斥 ∧ 不与实机冲突 ∧ 填充型
(不与 D 文本/既有 E 语义相抵)→ 采用,记 adopted 事实(带 slug 引用,不写回);否则产 AskPanel。

**cap 二分**(A6):cap_reached 时存在未答 AskPanel→呈报之;无→escalated 工程故障呈报(附证据)。

**其余参数落点**:应然锚(A2)=hits/write 的 anchor 必填;判例键(A3)=write 的 key,检索失配
保守回落 ask;ε 次序(A7)=ask 排在 attribute/复跑后(既有);代理声明(A8)=lineage 固定
"user_proxy";版本族收敛(A12)=key.version_family+检索按族过滤;收敛律(20)=decision→
adjudication 写回,下批检索命中即采用——固化为 eval 断言("同键第二批零 ask")。

## 五、四决策点——run5 数据裁决（2026-07-10 当日定案）

1. **采信判定=引擎机械判,比不出保守回落 ask**。数据:同案跨轮归因漂移严重——655173 三轮
   三个层(G/reflow→V/defect_candidate→E/env_blocked)、668030 两轮换处置(defect_candidate
   →rerun_isolated);加历史 942 配对"LLM 审 LLM 判别力 3pp"——把采信门交给孔,门会漂。
   三条件机械化:命中间无互斥(slug/结论比对)、填充型(verifiability 欠定槽有记载=填充)、
   与实机不冲突(记载期望形态 vs 最新回显签名,能比则比,比不出=按未知→ask)。
2. **AskPanel 由 attributor 顺产,不设独立节点**。数据:归因 fork 均价 ↑256k tokens
   (run5 共 9 fork ↑2.30M);独立 panel 孔=同批证据重读一遍(+~256k/panel,+2-3min),
   且判断漂移数据说明第二个孔可能讲出第三个故事——同孔顺产保归因与呈报一致。
   落地形态:attributor 工具白名单加 `submit_ask_panel`(strict),判 ought-欠定时顺手提交。
3. **决策史新建 `knowledge/adjudications/`(md+frontmatter=判例键/锚,FTS5 复用
   kb_memory_search 底座),不塞 footprint**。数据:footprint 2398 节点按 CLI feature
   组织,decision_rules 105 条是 CLI 决策规则非用户裁决;冲突形态(ordering_vs_persistence
   等)跨 feature,塞单节点检索必漏;决策史存量≈零(user_decision.json 存档 0 个,decision
   事实 5 条)——绿地建正确形态零迁移。kb_intent_search 的四源 fan-in:spec/design=KMS
   product md(1720 份 53.9MB,FTS5 CJK bigram 已验)、人写先例=compile_precedent 意图索引
   (mirror 96 卷,委托)、bug 裁决=kb_bug_search(委托)、决策史=adjudications/(新)。
4. **结构化产物全走 strict 合成工具,弃 response_format**(mimo 端点实测,2026-07-10):
   - response_format json_schema strict 裸调:HTTP 200 但**不守约**(丢 enum 必填字段);
   - 同形态+思考:返回 ```json 围栏散文,schema 完全无视;
   - **strict 工具+强制 tool_choice+思考:满分**(enum/键集全对,reasoning 1k 字正常);
   - **strict 工具+auto+思考:满分**。
   官方"json_schema 管说什么/strict 管怎么调"的分工判据在 Anthropic 家族成立,mimo 实测
   只有 strict 工具一条可信通道——且 mimo 强制 tool_choice 与思考**兼容**(Anthropic 不容),
   MiMo-Code 的合成工具模式即最终形态。接入=既有 bind_tools strict 通道按工具单点开
   (strict=True per-tool),不动 IST_TOOLS_STRICT 全局开关。
