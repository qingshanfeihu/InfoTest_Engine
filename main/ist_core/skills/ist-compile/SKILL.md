---
name: ist-compile
description: "把人工测试用例（脑图 / txt）编译成自动化 case.xlsx 的编排主入口。你作为 orchestrator 掌全局：解析脑图拆出 case 清单 → 逐个派 compile-worker 子 agent 写对（emit 过全部机械门即落结构凭证）→ 合并打包 → 上机验证（唯一质量 oracle）→ fail 按归因定向重派（自愈）。当用户要「编译用例」「把脑图/txt 转成 case.xlsx / excel」「用例编译」「编译这批脑图」时用。"
context: inline
user-invocable: true
source: hand
version: "5"
effort: high
when_to_use: |
  Use when 用户要把人工测试用例（脑图 / txt）编译成自动化 case.xlsx。
  Examples: "把这批脑图编译成 excel"、"编译这个 txt 用例"、"用例编译"、"脑图转 case.xlsx"。
  Trigger keywords: 编译用例, 脑图转excel, txt转excel, 用例编译, 闭环编译, case.xlsx。
  SKIP when: 只查一条 CLI 回显用 dev_probe；对已编译 excel 做上机复验走 ist-verify。
---

# 编译编排

## 主路:V6 引擎(2026-07-06 起)

**先调 `compile_engine_run(mindmap_path, product_version)` 一次**——整条闭环(编写→欠定问用户→合并→上机→归因→定向重编→循环到不动点→写回→报告)由确定性状态机跑完,欠定会自动弹面板问用户,被打断后同参数重调即断点续跑。产品版本没给就先 `ask_user` 问。汇报用自然中文转述返回摘要;机读全量在 `workspace/outputs/<批名>/engine_report.json`。

工具返回 `engine_disabled`(IST_COMPILE_ENGINE=0)时,才走下面的 v5 编排 fallback。

## Fallback:v5 main-orchestrated(引擎关闭时)

把人工用例（脑图 / txt）编译成断言真覆盖目标行为的自动化 `case.xlsx`。**你是 orchestrator**——掌全局、派 worker、验产出、改计划、自愈，像你平时派 subagent 那样自己编排，**不调黑盒 `compile_pipeline`**（它保留只当二级 fallback）。

- **worker = `compile-worker`**：复刻你自己的自由理解逻辑、限定到单个 case。你用 `invoke_skill(skill="compile-worker", brief=…)` 派它编一个 case。它不走"先检索先例→observe"那套老序列，就像你那样：读懂行为 → 区分原始约束与可改写 claim → 判断断言属静态层还是运行时层 → `compile_emit` 落盘。
- **验收 = 机械门 + 上机 oracle**：worker 产物过 emit 的全部机械门（崩溃门/lint/欠定台账）即获结构凭证、可合并；语义对错由上机裁决（依据见 §3——不逐 case 派 LLM 审批）。`ist-compile-grade` 保留两个位置：①上机 fail 后需要语义归因辅助时；②欠定/新形态升级用户前的过滤。
- **本 skill 只产 excel，不上机。** 上机复验走独立的 `ist-verify`（运行时启停状态由 loader/overrides 决定，不在本文件维护）。

## 流程

### 0. 确认版本（ask_user，不猜）

从请求提取产品版本（如 10.5）；没写就 `ask_user` 问。版本是 worker 查哪个手册的依据，错了整批文法全错。

### 1. 解析脑图 → 拿 case 清单

```
compile_prep(mindmap_path="<脑图.txt>", out_name="<脑图名>")
```

它通读脑图、列出所有 case（autoid 主键 + 标题 + 分组 + 步骤 + 期望 + 预检索的先例/footprint），写到 `workspace/outputs/<out_name>/manifest.json`。`fs_read` 它，拿到完整 case 清单——这是你掌全局的依据：清单有几个 case，你就该派几个 worker、收几份产出，一个都不能漏。

### 2. 按族派 worker(族摊销,H_G 只付一次)

manifest 的 `families` 字段已按配置意图句式聚好族(纯代码,prep 产)。**≥4 成员的族分两波**:先派族首(`head`)一个 worker 全力编写;族首 emit 过门后,调 `compile_skeleton(族首autoid)` 取其配置骨架,把骨架文本嵌进族内其余 case 的 brief(自由正文里加「## 族骨架(族首已过门的配置基线,按本 case 差异增删,差异之外不重新推导)」段)再并发派——同族配置基线实测重合 45-51%,族内逐个从头查手册推导是重复支付,族首一次推导族内共享。**<4 成员的族**不等骨架,直接并发派(小族串行代价大于收益)。族首失败(needs_user_decision/failed)则该族全员按无骨架路径派,不阻塞。

对每个 case,`invoke_skill(skill="compile-worker", brief=…)`。**brief 开头是一个固定 JSON 信封**（机读骨架，worker 与你都靠它防漂移），其后接自由正文：

```json
{"autoid": "203031753342777976", "manifest_path": "workspace/outputs/<批名>/manifest.json",
 "product_version": "10.5", "round": 1, "redispatch_reason": null,
 "advisory_path": "workspace/outputs/<批名>/advisory.md"}
```

- **step_intents 不手抄进 brief**——worker 凭 `manifest_path`+`autoid` 自己 `fs_read` manifest 原文（手抄是有损转录；长线程下重派 brief 曾退化到 129 字符丢光约束）。正文里只写你识别出的 `preserve_constraints`（配置形态、地址族覆盖、池数量、阶段顺序、绑定关系）与观察建议（advisory 语气，worker 可反驳——曾实证 worker 查手册否决了 orchestrator 对 ga 的错误理解）。
- **通用 advisory 落盘一份**：批开工时把「测试域名/断言纪律/环境事实」等对全批生效的守则 `fs_write` 到 `workspace/outputs/<批名>/advisory.md`，brief 信封引用路径——别在 46 份 brief 里各手抄一遍（实证 3+ 种措辞漂移）。advisory 里环境类断言（自动配置/测试机工具）只写有出处的（网络事实源/先例/footprint 里出现过的）；没出处的别写，直接写「每个 case 的 init 自包含完整基线，不假设自动配置」即可——这句零成本且永远安全。
- `redispatch_reason` 重派时填：`grade_cut`（带 grade 重做意见）/ `emit_failed`（带报错原文）/ `user_decision`（带决策，见 3.5）——worker 按原因分流理解，你也不会把两个 case 的失败原因张冠李戴。

worker 写对、`compile_emit` 落盘到 `workspace/outputs/<autoid>/case.xlsx`、返回路径 + 一句话思路。

**派发通道按批量选**（载荷通道一致性,2026-07-04 全量轮取证）：
- 少量（≤6 个）：一条消息里发多个 `invoke_skill`，worker 们并行跑。
- 大批量（>6 个）：**走 `compile_fanout(skill="compile-worker", briefs_path=…)` 文件通道**——先用 `run_python`/`fs_write` 把 briefs 数组（每项 `{key: autoid, brief: 信封+正文}`）从 manifest/advisory 机械拼装、落到 `workspace/outputs/<批名>/briefs_wave<N>.json`，再把**文件路径**传给 fanout。brief 正文既不流经你的上下文、也不内联进工具参数——18-case briefs 内联曾被序列化截断，被迫逐个派发、并发全失（20 分钟仅 6 卷）。fanout 返回里超长 output 已自动落盘、内联只保留末尾（机读尾块仍在末尾），深挖用 `fs_read` 该项的 `output_path`。

**收 worker 返回，两条铁律**：① 状态看返回末尾的机读尾块（`状态：produced|needs_user_decision|failed`），别通读散文猜——历史实证 46 份返回里 40 份含 NEEDS_USER_DECISION 字样、真欠定只有 6 份；② **「产没产出」以落盘为准**：fanout 返回每项自带 `produced` 机读字段（工具直接探盘）；逐个 invoke_skill 派发时自己对 `outputs/<autoid>/case.xlsx` 探一把。盘上没有=按 failed 重派,盘上有而返回是残句=按 produced 继续。

### 3. 产物核验（机械探针 + 抽查,不逐 case 派 LLM 审批）

worker 的 emit 走到「已产出」= 已过全部机械门（崩溃门 / 成品 lint / 欠定台账 / 冻结闸）并自动落**结构凭证**（source=lint,xlsx_mtime 精确签名）——这就是合并的通行证。**不再逐 case 派 `ist-compile-grade`**：942 对时点配对实测（2026-07-04）grade 判 PASS 的卷上机通过率 56%、判 CUT 的 53%,判别力 3 个百分点、CUT 重做后通过率不升——语义对错只有上机能裁决,逐 case 审批只烧 token 和制造翻案循环。

你对每个产物做的是**零 token 的机械核验 + 快速抽查**：

1. `compile_grade_extract(xlsx_path, prov_path)`：确定性探针,返回若干 `*_suspect` 信号(写死命中/写死计数/分布覆盖缺口等,含义在返回里)——任一为真 → 带信号原文重派 worker。
2. 对照 manifest 快速抽查（你自己读,不派 fork）：原始约束保真吗（脑图点名的地址族/池数量/绑定关系/阶段顺序没有因修欠定而消失）；有序 claim 没被降级成参与统计吗（"按原有顺序/最后才命中"是有序轨迹,聚合计数证不了顺序——发现降级带反馈重派）。
3. 探针与抽查都干净 → 进合并。**语义层面的残余不确定性交给上机**：fail 会带 device_context 回来,那时如需深度语义评审再派 `ist-compile-grade` 做归因辅助——它的意见挂在真实上机证据上,比编译期空审有效。

**发现问题 → 带具体反馈重派 worker**：`invoke_skill(skill="compile-worker", brief="<上一版 + 问题反馈>")`,它针对反馈改、保留对的部分。

### 3.5 欠定用例 → 汇总问用户（绝不替用户改、绝不让 worker 硬编）

worker 返回里若带 `NEEDS_USER_DECISION`（`compile_check_verifiability` 数学证伪「用例如写验不出目标行为」），**别重派 worker 硬编、也别自己替用户改**。把本批所有欠定 case **汇总成一次 `ask_user`**：每题的原因/最小可验请求数/待决 claim 从 `outputs/<autoid>/needs_decision.json` 台账读（别凭记忆均一化）；case 多时可按同型分组但问题文本列全组内 autoid。**分组红线**：组内任一 claim 台账标了 `ordering_sensitive`，选项文本必须显式写明顺序语义是保留还是放弃——曾实证并组时顺序锚被磨掉、用户以为选了保全实际批了降级：

- **改预期**：只把不可证伪的绝对预期改成可验的关系/分布；配置形态、服务类型组合、池数量、阶段顺序等 preserve_constraints 原样保留。
- **改过程**：只把请求数/观测次数加到最小可验数（worker 给的 `min_requests`，如新增 pool 类加到 4 次）；原始配置和场景结构不改。
- **改描述**：用例描述本身有歧义 / 与设备真实行为矛盾，需人工厘清。

拿到用户选择后，对每个 case 调 **`compile_user_decision(autoid, decision, assertion_form=…)`**——形态按用户答案如实传（工具不代判），台账锚（min_requests、ordering_sensitive 的 claim）由工具机械复制，落成 `user_decision.json`。**别自己 `fs_write` 这份文件**（手写曾把 min_requests 凭记忆均一化、把顺序锚磨掉）。用户在选项里**显式批准放弃顺序语义**的才传 `drop_ordering=True`。emit 出口会按这份文件机械核对产物——形态不符或丢顺序锚直接拒绝落盘。

然后**带决定重派 worker**：brief 写 `preserve_constraints`（原样保留）+ user_decision.json 的路径（worker 读文件,你不复述内容——777976 实测转述后 worker 挑省事形态跑偏）。用户没答/取消的 case，如实标「待用户决定」进汇报，不强行产出。

### 4. 合并打包

全部 case 探针+抽查干净后，用 `compile_emit_merged(autoids=[…清单里全部 case 的 autoid], out_name="<脑图名>")` 合并打包。合并工具带**凭证机械门**：每个 autoid 必须持有对应**当前** case.xlsx 的新鲜凭证（emit 过全部机械门自动落的结构凭证,或归因辅助场景 grade 落的审批凭证）,缺凭证、重编后过期、或判定是 CUT 都会被拒——确定性代码强制,直改绕行也会在合并前的逐卷 lint 被拦。**只传 autoid 列表**——worker 已把每个 case 落成 `outputs/<autoid>/case.xlsx`，工具自己从这些成品回读 steps 合并。**别去凑 steps/init**：那些数据 worker 已写进 xlsx，你手里没有、凑也凑不全（凑残会出空步骤/空命令）。

### 5. 汇报

excel 路径 + case 数（凭证齐备 / 仍有问题逐条带 autoid + 原因）。**上机是唯一质量 oracle**：合并完成后直接走 `ist-verify` 上机验证,fail 按四层归因定向重派 worker（修复轮只跑 fail 子集）,全过后整卷确认。

## 红线

- **掌全局别漏**：manifest 列了几个 case，就派几个 worker、收几份产出、核几份凭证。token 紧就分批派 worker、续派，但清单不能丢——别像单 agent 硬写到耗尽、做一半就停。
- **worker 复刻你、不是另一套约束**：worker 用你的自由理解逻辑（`agents/compile-worker.md`），不走先例驱动 + observe-then-assert。
- **验收不放水**：worker 自己不自评；机械探针有信号、抽查发现降级/失真,如实重派,不拿弱产物充数。语义终判在上机,不在任何 LLM 的意见里。
- **上机解耦**：只产 excel，不调 `dev_run_batch` / run。上机走 `ist-verify`。
- **欠定不硬编**：worker 上报 `NEEDS_USER_DECISION` = 用例如写验不出目标行为（数学证伪），汇总 `ask_user`（改描述/改过程/改预期），绝不替用户决定、绝不让 worker 死抠断言形态乱写。
- **改写不改题**：数学证伪只改欠定 claim；manifest 原始约束是验收基线。把 v4/v6/混合、多阶段、新增顺序、数量边界等覆盖点简化掉，即使断言本身可运行，也按漏覆盖处理。
- **面向用户说人话**：plan 条目、ask_user 面板、进度说明、最终汇报是给使用产品的人读的——他们不了解编译器内部机制。用自然语言说动作和结果（「机械检查每个用例，有问题的重写；最终对错以上机验证为准」而非「跑 compile_grade_extract 探针 + 结构凭证门」；「有 7 个用例按原始写法验证不出来，需要你选改法」而非「汇总 7 个 NEEDS_USER_DECISION」）。内部枚举值、工具名、正则不上屏；需要精确指代时用括注补在人话后面。汇报里的统计数字与分组从 manifest/凭证机读得出，不凭记忆汇总。
