# 编译 V3：闭环自演化 + 三层 Provenance IR + 意图族摊销 + 全链四层归因 + 并发摊薄

> **本 plan 自包含**：新会话无上下文也能照做。所有文件路径、机制、红线、验证在内。
> 工作目录：`/Users/jiangyongze/Library/CloudStorage/SynologyDrive-home/Project/InfoTest_Engine`
> Python：`.venv/bin/python`（项目根）。
> 论文最终稿：`workspace/outputs/paper_v6/paper_v6.md`（§3.14 定理3.22 / §3.7 定理3.10 / §5.4 归因 是 V3 三大跃迁的理论依据）。
> 前置：V2 已落地（`docs/PLAN_footprint_v2_compile.md`）。V3 不重做 V2，**在 V2 基础上做架构跃迁**。

## 〇、为什么要 V3（V2 的结构性缺口，实测定位）

V2 实测（2026-06-17，dongkl 34 case）：单 draft 288s（v1 579s，-50%）、轮数 11.3（v1 21.4）、grep 6.3/fork（v1 25）。**提速真实，但 V2 本质是"喂得更饱的 V1 架构"**——三个论文许可的结构跃迁，V2 都没碰：

1. **fork 是无状态冷函数**：每个 draft 进 brief 出 xlsx 即死、零记忆；下一个同族 case 从头再推。footprint/先例库**只读**，灌完就冻。→ 违背定理3.22「扩大先例库推高 ρ_k 把 G/E 段错误驱向本征下限」——V2 的 ρ_k 编译期不增长。
2. **draft 与 grade 是互不通气的冷 fork**：draft 查完手册产**扁平 xlsx**（丢 provenance），grade **再 grep 同样手册一遍**（实测 4.9 次/fork）重新解构。→ 浪费，且 §5.4 四层归因无依据可挂。
3. **编排器逐 case 孤立处理**：113 case 各自走 draft，同族共享骨架的 **H_G 被重复支付 ×113**。→ 违背主定理 H=H_G+H_V' 里「G 段可共享」。

外加一个工程缺口：**并发恒为 4**，墙钟 = Σfork/4，实测 113×(draft+grade) ≈ 266min。并发是墙钟唯一非质量杠杆，V3 必须把它从"调参"变成"编排器按族数自适应分配"。

## 〇·一、成功标准（本 plan 交付）

跑同一条 `infotest -p "...3份txt脑图生成10.5版本自动化excel..."`，V3 相对 V2 基线（§六记录）须证明：
- **闭环**：编译过程中 footprint `verified_count` 单调上升；第 N 个同族 case 的 draft 轮数 < 第 1 个（ρ_k 编译期增长，定理3.22 兑现）。
- **IR 复用**：grade 的 grep 次数较 V2 的 4.9/fork 显著下降（grade 验 provenance 不重新检索）。
- **族摊销**：H_G 重复支付下降——同族 case 第 2 个起跳过骨架推导（draft 轮数族内递减）。
- **四层归因**：verify 产出 G/E/V/瞬态四分（非 V2 三分），fail 能精确路由回对应层重编译。
- **墙钟**：并发自适应后总墙钟较 V2 的 4-并发显著下降（族数×族内并发）。
- **隔离**：V1/V2 链零回归；pytest 全绿。

## 一、理论映射（每个跃迁挂一条定理，不凭感觉）

| V3 跃迁 | 论文依据 | V2 现状 | V3 兑现 |
|---|---|---|---|
| ① 闭环自演化 | §3.14 定理3.22：G/E 段错误率 ≤ β_k+(1−ρ_k)，**扩库推高 ρ_k 把错误驱向本征下限** | footprint/先例只读，ρ_k 编译期不变 | 上机 PASS 的 case 写回 footprint+先例库，ρ_k 单调升 |
| ② 三层 Provenance IR | §3.5 定义3.6/3.7：G⊔E⊔V 是**带来源**的分解 | draft 产扁平 xlsx，grade 重新 grep 解构 | draft 产带标注 IR（G←footprint节点 / E←拓扑行 / V←先例·手册出处），grade 验 provenance |
| ③ 意图族摊销 H_G | §3.7 定理3.10：H=H_G+H_V'，同族 H_G 可共享；§4.5 depth-2 前缀把骨架 41→少数 | 逐 case 付 H_G ×113 | 编排器按意图轴聚类→每族编译一次骨架→族内只做 E+V 绑定 |
| ④ 四层归因 | §5.4：fail 四分 G错/E错/V错/瞬态，各层独立（§4.7+§3.10 正交） | verify 三分（真通过/断言失败/环境失败） | verify 四分，按 IR 把 fail 路由回 G/E/V 层重编译，瞬态不回流 |
| ⑤ 并发自适应 | （工程，非论文）墙钟=Σfork/并发 | 恒 4 | 编排器按族数×端点配额自适应分配，夹紧防 429 |
| ⑥ 结构门补全 | §3.2 算子代数 + 命题3.18 correct-by-construction | emit 出口**过滤**（生成后拦） | draft 用「观测→断言」类型化积木**构造**，悬空不可表达 |

**红线（§3.7ter，最重要）**：①②③④只动**确定性机制与信息流**（写回、provenance、聚类、归因路由），**绝不替代骨架选择**（H_G≠0 的语义决策永远 LLM）。混淆 = 重蹈被删的纯代码管线（41→1）。

## 二、关键代码事实（已核实，V3 复用而非新建）

- **写回机制已存在**：`main/ist_core/memory/footprint/merger.py:298 merge_fact()` 写单条事实，`:160` 自增 `verified_count`；`reconcile.py:41 reconcile()` 重建层级；**evidence_quote 必须在源文件命中否则 skip（防幻觉的现成安全闸）**。V3 只需把"上机 PASS 的 case 事实"喂给这条链。
- **自调度引擎已存在**：`main/ist_core/memory/dream.py`（`should_run_dream`/pid_lock/`build_dream_consolidate_llm`）是进程内写回执行者。V3 的编译写回可复用或仿此。
- **意图相似度已有**：`precedent_tools.py:68 _intent_similarity()` + `:51 _intent_tokens()`（CJK bigram）。聚类直接用它，不引向量库（§五 YAGNI）。
- **分组字段已有但不够**：`compile_prep.py:74 group_path` 是**脑图拓扑父链**，不是意图族。V3 聚类要在 prep 产物上**按 _intent_similarity 二次聚类**，不能直接拿 group_path 当族。
- **先例库**：`knowledge/framework/mirror_intent_index.json`（build_intent_index 产）+ mirror xlsx。当前**只读**。
- **并发**：`batch_tools.py:31 _DEFAULT_FANOUT=4 / :32 _MAX_FANOUT=12`，env `IST_FANOUT_CONCURRENCY`，`_resolve_concurrency` 夹紧。
- **verify 现状**：`skills/ist_verify/SKILL.md` 三分（真通过/断言失败/环境失败），无 G/E/V 区分。

## 三、实施步骤（按依赖排序，每步独立可验证）

### 步骤 0：并发自适应（最低风险、最快见效，先做）
- `qa_compile_fanout` 的并发从"调用方传死值"改为**编排器按族数+端点配额算**：`min(_MAX_FANOUT, max(4, 待编译数))`，env `IST_FANOUT_CONCURRENCY` 仍可硬覆盖。
- `_MAX_FANOUT` 提到 16（端点实测 429 阈值前）；加**429 退避**：fanout 内 worker 命中 429 时指数退避重试，不直接判 fork 失败。
- 验证：dongkl 34 case 跑两次（并发 4 vs 自适应），墙钟对比；无 429 失败。
- **隔离**：纯墙钟优化，不碰任何 fork 内部逻辑，V1/V2 同样受益。

### 步骤 1：三层 Provenance IR（②，draft↔grade↔verify 的公共契约）
- 新建 `main/case_compiler/provenance_ir.py`：定义 `StepIR{E,F,G, layer:'G'|'E'|'V', source:{kind, ref}}`。
  - G 层 source = footprint feature_id / 先例 xlsx 名；E 层 source = env_facts 拓扑行；V 层 source = 先例链 / 手册行号 / 作者意图。
- `qa_emit_xlsx` 增 `provenance_json=""` 入参（默认空＝V2 行为不变）：传入则把 IR 落 `<out>/case.provenance.json` 旁挂 xlsx（xlsx 本身不变，框架照吃）。
- `ist-draft-v2` → `ist-draft-v3`：产 steps 时同时产 provenance（每步标 layer+source）。这是 G→E→V 三层生成的**自然副产物**（draft 本就知道每步来源，只是 V2 没记录）。
- 验证：draft 产物含 provenance.json，每步可溯源；emit 不传 provenance 时与 V2 字节一致。

### 步骤 2：grade 验 provenance 不重新检索（②兑现，治 grade 4.9 grep/fork）
- `ist-grade-v2` → `ist-grade-v3`：brief 带 draft 产的 provenance.json。grade 改为**验证 provenance 而非重新解构**：
  - V 层断言：核对 source 引的先例/手册行是否真支撑这个期望值（仍 LLM 判语义覆盖度，但**有锚点不盲 grep**）。
  - 只在 provenance 缺失/可疑时才回退 grep（V2 的老路作兜底）。
- 验证：grade grep 次数较 V2 的 4.9/fork 下降；判据质量不降（PASS/CUT 与 V2 抽样一致或更准）。

### 步骤 3：意图族摊销 H_G（③，编排器改造）
- `ist_compile_v2` → `ist_compile_v3` 编排器：prep 后**按 `_intent_similarity` 对 manifest 聚类**成意图族（阈值初版 0.5，可调）。
- 每族流程：**先派一个 `ist-draft-v3` 编译"族骨架"**（该族共享的 G 段：监听器/服务/池等基础前置 + 命令骨架）→ 族内每个 case 的 draft 收到**族骨架作为 G 段输入**，只做 E（IP 绑定）+ V（业务断言）。
- 族内 draft 因 G 段已定，轮数应显著低于族首。**骨架选择仍 LLM 做**（族首那次），族内是复用不是硬编码。
- 验证：同族 case 第 2 个起 draft 轮数 < 族首；H_G 重复支付下降（族数 × 1 次骨架推导，非 ×case 数）。

### 步骤 4：闭环写回（①，V3 的灵魂；依赖 IR + 上机）
- **触发点**：`ist_verify` 上机 PASS 的 case → 把其 provenance IR 里**已验证为真的 G/E 段事实**喂给 `merge_fact()` 写回 footprint（evidence 门已防幻觉），并把整条 case 追加进先例库（mirror + 重建 intent_index）。
- 新建 `main/ist_core/memory/compile_writeback.py`：`writeback_verified_case(provenance, verdict_detail, footprint_dir)`——只写**上机真 PASS** 的（verdict 真裁决明细为准，不信字符串），G/E 段事实走 merge_fact，整 case 走先例追加。
- **本轮验收不上机（§〇沿用 V2）**：故步骤 4 先实现+单测写回机制，**用"结构门通过+grade PASS"作为写回门的临时代理**（标记 `provisional=true`），上机闭环留作 V3.1。这样 ρ_k 增长在验收里仍可观测（同 run 内后编译的同族 case 能检索到前面写回的先例）。
- 验证：编译过程中 footprint verified_count 上升；后编译的同族 case 能 lookup 到前面写回的先例（ρ_k 编译期增长可观测）。

### 步骤 5：verify 四层归因（④，依赖 IR）
- `ist_verify` 的 fail 分类从三分→四分：按 provenance IR 把每个 fail 的 check_point 归到 **G错**（命令骨架不全/非法）/ **E错**（IP 不可达/配错）/ **V错**（断言语义值错）/ **瞬态**（SSH/dig 超时/NXDOMAIN）。
- G/E/V 错带层级反馈回流对应层重编译（draft 收到"哪层错+为什么"定向改）；瞬态标注不回流。
- 验证：人为构造各层 fail，verify 能正确四分并路由；瞬态不触发重编译。

## 四、验证（对齐成功标准 §〇·一）

跑 `infotest -p "...3份txt脑图..."`（V3 链 on），对照 V2 基线（§六记录）：
1. **并发**：墙钟较 V2 的 4-并发下降；无 429 失败（步骤0）。
2. **IR**：draft 产 provenance.json 每步可溯源；grade grep <V2 的 4.9/fork（步骤1-2）。
3. **族摊销**：同族 case draft 轮数族内递减；总 draft 轮数 < V2（步骤3）。
4. **闭环**：footprint verified_count 编译期上升；后编译同族 case 能检索到前面写回先例（步骤4）。
5. **四层归因**：verify 四分正确、按层路由（步骤5）。
6. **隔离**：V1/V2 链零回归；pytest 全绿（含 footprint/memory/structural_gate 测试）。
7. **产物质量不劣于 V2**：完整性（autoid 无丢失）、结构合法（命令∈allowlist/断言非悬空/IP可达）、§5.6 静态指标（K/P/D）。

## 五、不做的（避免过度应用）
- **不引入信息论度量到运行时**：H_G/H_V/碰撞熵是论文**分析**工具，不在生成器实时算。运行时只用"G段共享、V段才自由"的定性原则。
- **不上向量库**：聚类/相似度用现成 `_intent_similarity`（词重叠+bigram），YAGNI。
- **本轮不做真上机闭环**：步骤4 用"结构门+grade PASS"作写回门临时代理，真上机写回留 V3.1（§〇沿用 V2 不上机验收）。
- **不替代骨架选择**：族骨架由族首 LLM 推导，族内复用不是硬编码规则；写回的是"已验证事实"不是"意图→命令映射规则"。
- **不动 V1/V2 文件**：V3 全走新文件（ist-*-v3 / provenance_ir.py / compile_writeback.py / ist_compile_v3）+ 现有工具加默认空入参（向后兼容）。

## 六、V2 基线（V3 对照用，实测填入）
- V2 单 draft：288s / 11.3 轮 / grep 6.3 / footprint 13.0（dongkl n=35，2026-06-17）。
- V2 grade：277s / 6.6 轮 / grep 4.9（n=16）。
- V2 footprint 命中(grep=0)：193s / 6.2 轮（n=6）；grep 回退：307s / 12.4 轮（n=29）。
- V2 并发=4，113 case 墙钟 ≈ 266min（估算，待验收 run 实测补全）。
- §5.6 静态指标 / 完整性：**待验收 run 跑完 check_v2_products 补全**。

## 七、执行顺序建议
1. **步骤 0（并发）**——独立、零质量风险、最快见效，先做并立即验证。
2. **步骤 1（IR）**——②③④⑤的公共契约，是后续所有步骤的依赖底座。
3. **步骤 2（grade 验 provenance）+ 步骤 5（verify 四层）**——都吃 IR，可并行开发。
4. **步骤 3（族摊销）**——编排器改造，吃 IR + 聚类。
5. **步骤 4（闭环写回）**——V3 灵魂，吃 IR + 上机（本轮用代理门）。最后做、收益最大。

> 每步做完跑 pytest + 小样（dongkl 单脑图）验证，再进下一步。全部完成后跑 3 脑图全量验收对照 §六 基线。




