# P0 幂等键修复·设计一致性评审（team4 Design，2026-07-17）

> 对象：Py-Eng P0 diff（qid 改 `nd:{aid}:{claim_kind}:{nd_seq}`，nd_seq 读事实流；P1-11 emit_tick 前移）。单文件 nodes.py，仅生成侧。
> 方法：设计四处原文（§2.1/§16.1/§11.9/§11.11）+ 代码亲核（nodes.py:356-378/470-487、report_gate.py:44-46、facts.py:96-103、views.py:89-94、判例采纳键 :575/:1310）+ 子agent qid 全消费点全景。
> **证据边界**：结论基于工作树当前 diff（生成侧 +35/−2，消费侧未动）+ 上述亲核代码点确认；未跑测试、未见 Py-Eng 后续补丁。report_gate 缺陷经我逐行亲读原文确认（非仅子agent转述）。

## 总裁决：PASS（2026-07-17 复核转正——F-1 已修、M-1 已结构性消除、锚 f/g 到位）

> 初裁 PARTIAL → 复核 PASS。Py-Eng 交付 F-1（report_gate.py:48-50 按 qid 配对，逐字段同 views.py:92-94，独立重算保双路交叉校验）+ M-1（qid 前移 `nd:{aid}:{nd_seq}:{ck}`，nd_seq 置截断安全位）+ 锚 f（test_report_gate.py:206 休眠分叉激活场景+ :220 防过修对照，用新 qid 格式）。三判据亲核全绿，清单 1产6消完整。下方初裁表保留作演进记录。

### 初裁表（PARTIAL，历史）

| 维度 | 结论 | 依据 |
|---|---|---|
| ① §2.1 幂等键条款 | **P**（条文需按实现修正——见下） | facts.py:97 decision 键=`(ev,aid,question_id[:120])`；改 qid 生成即改去重粒度，消费端不需改。含中危核对项（截断，见 M-1） |
| ② 影响面/漏改消费点 | **F** | report_gate.py:44-46（G5 重算门）漏同步——P0 新暴露的一致性缺陷（详见 F-1） |
| ③ 跨轮同 kind 再问·两层正交 | **P** | 判例采纳键 `(intent_signature,conflict_shape,version_family)`（:575/:1310）不含 qid/nd_seq；nd_seq 只进入账键。leader 分层判读在代码成立 |
| ④ emit_tick 前移 vs §11.9 | **P** | emit_tick(closing) 前移到删 manifest 之前（:2843），注释因果链正确（manifest 删后 counts 全 0→footer 恒 0/0）；tick 在清理前发、引用路径未清 |

## F-1（维度②·必修）report_gate.py:44-46 漏同步为按 qid 配对

- 现码：`if any(ev==needs_decision) and not any(ev==decision): continue`——**旧「有任意 decision 即非等待」口径**。
- 冲突：本函数 docstring:20 自述「对齐 fold 优先级语义(views.case_status)，独立实现」；而 views.py:92-94 已是 **H2（2026-07-14）按 question_id 配对**（`needs_decision.qid ∉ 已答 decision.qid` 才算未答）。两条独立重算路径口径分叉，违 G5 门"双路同口径"设计。
- **为何 P0 才暴露**：旧 qid `nd:{aid}:{rnd}`（rnd 恒 1）→ 真·二次欠定被 idem_key 去重吞掉，此分叉路径**从不触发**（案停 S_PENDING）。P0 让二次欠定首次存活 → 激活休眠分叉。
- 失败场景：aid 首轮欠定→答（产 decision）→次轮又欠定（新 qid，未答）。views 判 `S_AWAITING_USER`（对）；report_gate `not any(decision)`=False（因有首轮 decision）→ 不 continue → 若有 delivery pass 判**可交付**（错）。G5 报告门自我误告警/漏防未答案交付。
- 修法：report_gate.py:44-46 改为与 views 同口径——`_answered={d.question_id for decision}`，存在 `needs_decision.qid ∉ _answered` → continue。**同步 H2 到 G5 门。**

## M-1（维度①·中危核对项）nd_seq 在 qid 末尾 + facts.py:97 `[:120]` 截断

- decision 幂等键 `(ev, aid, question_id[:120])`（facts.py:97）。nd qid=`nd:{aid}:{ck}:{nd_seq}`，**差异化正确性锚 nd_seq 在末尾**。
- 风险：ck 为多 claim_kind `"+"` 拼接时 qid 可能超 120 字符 → **nd_seq 首当其冲被截** → 差异化失效 → 碰撞回归（把刚修的 bug 在长 qid 下带回）。
- 典型 qid（aid 18 位+单 kind 如 verification_path_absent）≈49 字符，安全；多 kind 拼接极端下需确认。
- 修法（择一，Py-Eng 定）：①确认 needs_decision.json 单案 claims 的 kind 去重后 qid 恒 <120；②nd_seq 前移到 aid 后（`nd:{aid}:{nd_seq}:{ck}`）使截断先切可读的 ck 不切锚；③decision 键不截断或截更长。

## 已核正交·无需改（列此防重复怀疑）

- views.py:92-94 awaiting——已按 qid，新格式自然流通 ✅
- gather 折叠（nodes.py:506-604 + questions.py）——按 (group_path, claim_kind 派生 sig) 折叠，与 qid 正交 ✅
- 答案回填 `_qid_by_aid` 快照（nodes.py:502/549）——decision 复制 needs_decision 的 qid，配对自洽 ✅
- ask_user UUID 命名空间（ask_user/__init__.py:161 + reducer.py）——与 nd: qid 无关 ✅
- compile_user_decision——按 autoid 路径键，无 question_id ✅
- 无消费方对 qid 做 `split(":")` 结构解析（仅 cap: 有 startswith，nd: 无）——加段不破解析 ✅
- INV-10 重放幂等：nd_seq=decision 数（裁决后才+1，崩溃重放不新增）而非 needs_decision 数——注释详论正确，保 INV-10 ✅

## §2.1 同步条文定稿（终格式；M-1 前移后 qid=`nd:{aid}:{nd_seq}:{ck}`）

> **幂等键（按事实族分模板，2026-07-17 批3 蒸发修）**：每条事实带确定性幂等键，fold 去重（`facts.py::idem_key`）——键模板随事实类型而变：verdict 类 `(ev,aid,run_id)`；authored 类 `(ev,aid,round)`；attribution 类 `(ev,aid,run_id)`（无 run_id 退轮键）。**问询族两键机制不同（redline 校正，勿混为一键）**：
> - **needs_decision：内容键** `(ev, aid, json(全部非 `_` 字段, sort_keys))`——**不截断**，question_id **全文**进内容 JSON；两轮 qid 全文不同→内容 JSON 不同→天然不碰撞（批3 根因即在此侧：旧 qid `nd:{aid}:{round}` 的 round 恒 1→两轮 needs_decision 内容完全相同→内容键碰撞被去重吞→案未上机即交付）。
> - **decision：截断键** `(ev, aid, question_id[:120])`——decision 复制 needs_decision 的 qid；**M-1 前移的承重在此侧**：qid=`nd:{aid}:{nd_seq}:{claim_kind}`，nd_seq 紧跟 aid、置 claim_kind 之前，使正确性锚落在 120 字窗内→两条 decision 的截断键必因 nd_seq 相异而不同（多 kind `"+"` 拼接超 120 只切末尾可读 claim_kind、不切锚）。
>
> `nd_seq`=该 aid 事实流中 **decision 事实计数+1**（读事实流现算），是差异化的**正确性锚**（裁决后才前进→崩溃重放不新增→重放稳定，保 INV-10）；`claim_kind` 段仅语义可读（best-effort 读盘，为空作 `und`，不承载正确性）。**入账层宪法**：欠定事实一旦产生必落账，两键机制共同保证同案跨轮多次欠定不被前一条去重蒸发。**入账层与采纳层正交**：nd_seq 只进入账幂等键（决定"落不落账"），**不进采纳层判例匹配键**（收敛律(20) 判例键=intent_signature×conflict_shape×version_family，决定"入账后问不问人"）；故 nd_seq 递增不绕过收敛律——跨轮同 kind 再报仍入账，但 gather 时判例同键命中且未证伪→自动采纳不问人。**双路口径一致义务**：所有独立重算 awaiting 的路径（views.case_status + report_gate.recount_deliverable）必须同按 question_id 配对（H2），不得用"有任意 decision 即非等待"旧口径（F-1 教训）。
