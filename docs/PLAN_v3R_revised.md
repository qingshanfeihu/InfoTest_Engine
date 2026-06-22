# 编译 V3-R（修订版）：砍族摊销，保 grounding + 信息流跃迁

> **本 plan 自包含**。工作目录 `/Users/jiangyongze/Library/CloudStorage/SynologyDrive-home/Project/InfoTest_Engine`，Python `.venv/bin/python`。
> 论文最终稿 `workspace/outputs/paper_v6/paper_v6.md`。
> 前置：V2 已落地（`docs/PLAN_footprint_v2_compile.md`）；V3 初版（`docs/PLAN_v3_closed_loop_compile.md`）**实测为负收益，本 plan 修订之**。

## 〇、为什么修订（实测 + 论文三方对照，2026-06-17）

V3 初版（族摊销 + provenance + 写回 + 四层归因 + 并发）实跑：**比 V2 更慢更差**。停机核算 + 对照论文实测，定位根因——**我把优化加在了论文证明"无稳健收益"的骨架层**。

### 实测账本（单 dongkl，V3 初版，停在 fanout 中途）
- 10 个"族骨架 fork"：平均 **18.7 轮 / 263s**，共 110 次 footprint + 186 次 grep，耗 **2634s**，**一个 case 的 draft 都没产出**。
- 对比 V2 基线（dongkl）：34 个 case draft，平均 288s/11.3 轮，**直接产 xlsx**。
- 聚类合理（threshold=0.3：34→7 族，最大族 12/11）——摊销空间真实存在，但实现把"摊销"做成了"叠加"。

### 实测结论（**我们自己跑的** N≈101/102 三集双臂对照，非论文数字）
> **出处更正**：论文成稿 §5 **只有实验设计、明说"执行列为后续工作、结果表骨架预留 §5.6"**，§1.4 重申"不提出任何成本节省的端到端数字"。下面这组数是**我们执行论文 §5 设计**得到的（数据源 `/tmp/metrics_{yzg,dongkl,zhaiyq}.json` + 合并脚本 `workspace/outputs/paper_recompute/merge_metrics.py`，见记忆 `paper-static-arms-N113-result`），**不是论文作者得出的**。早期 plan 误挂为"论文 §5.6 实测"，此处更正。
>
> "跨三集**唯一稳健的分层收益是环境 IP 可达率（L=0% vs E=69% 编造率）**，而**骨架合法率两臂打平**（L=0.942 vs E=0.964，反与 N=26 旧结论相反）、断言可溯源率差距从 N=26 的 +16.5pt 缩到 +3.9pt、grade 质量依任务族波动，印证**分层价值集中在 grounding 维度而非骨架或语义层**。"

### 三方对照（实测 / 论文 / V3初版实现）逐条

| # | 维度 | 论文怎么说 | V3初版怎么做 | 判定 |
|---|---|---|---|---|
| 1 | 族骨架 fork | 定理3.10：H_G 由**每个 case 的意图前缀**收窄（§4.5 top-1≈60%）；**从未要求"先编共享骨架 fork"** | 额外起 N 个族骨架 fork，先白烧 2634s | **虚构步骤**，论文无此设计 |
| 2 | 骨架 fork 单位成本 | §4.5 单 case 骨架推导本就轻（前缀已收窄） | 族骨架 18.7 轮 > V2 单 case 11.3 轮 | **摊销单位成本 > 被摊销成本**，数学必亏 |
| 3 | 骨架是否替代 case 的 G 段 | 推论3.11：G 段可"文法生成+查表"确定性产出 | 骨架塞 brief 当文本，case draft 照样自查 footprint | **叠加≠摊销**，G 段付两遍 |
| 4 | 优化维度 | **骨架层两臂打平、无稳健收益；收益在 E 段 grounding** | 步骤3 大量精力投在骨架层 | **优化错维度**——V2 结构门(IP可达0%编造)才命中论文实测 |
| 5 | provenance/写回/归因 | §3.5 带来源分解 / §3.14 ρ_k / §5.4 归因，均支持 | 已实现，**不增加前置 fork 开销** | 方向对，但净收益**未单独验证** |

**结论**：① 砍掉族摊销（步骤3 + 族骨架 fork + qa_cluster_intents 在编排中的使用）——负收益、论文不支持。② 保留并验证不烧钱的信息流跃迁（provenance/写回/归因）。③ 真正的收益维度是 grounding（E 段），V2 结构门已做对，V3-R 不在骨架层加戏。

## 一、V3-R 是什么（= V2 流程骨架 + 三个零额外fork开销的信息流增强）

V3-R 编排流程**等于 V2**（prep → draft 并发 → grade 并发 → 合并），**不加聚族/族骨架两个阶段**。只在 V2 基础上叠加三件不增加 fork 的信息流：

| 跃迁 | 论文依据 | 相对 V2 的增量 | fork 开销 |
|---|---|---|---|
| ① 三层 Provenance IR | §3.5 | draft emit 时旁挂 case.provenance.json（每步 G/E/V+来源） | 0（draft 本就知道来源，只是记下来） |
| ② grade 验 provenance | §3.5 | grade 读 provenance 验来源，不重新 grep | **负**（省 grade 的 grep） |
| ③ 闭环写回 + 四层归因 | §3.14 / §5.4 | verify 上机 PASS 的 G 段写回 footprint（ρ_k↑）；fail 四层归因按层回流 | 0（写回是 verify 后处理） |

**被砍**：步骤3 意图族摊销（族骨架 fork）。`intent_cluster.py` + `qa_cluster_intents` 工具**保留代码**（无害、有单测、将来大族场景可能用），但**编排器不再调用**——不在 ist_compile_v3 流程里编族骨架。

## 二、每个现存件的处置（V3 初版已落地的，逐一定性）

| 文件 | 处置 | 理由 |
|---|---|---|
| `provenance_ir.py` + emit 的 `provenance_json` 入参 | **保留** | 零开销信息流，①的基础 |
| `ist-draft-v3.md` / `ist_draft_v3` | **改**：删"复用族骨架"分支，回到 V2 draft 行为 + 产 provenance | 不再有族骨架可复用 |
| `ist-grade-v3.md` / `ist_grade_v3` | **保留** | 验 provenance 省 grep（净收益），②​ |
| `compile_writeback.py` | **保留** | ③，零额外 fork |
| `fail_attribution.py` + `qa_attribute_fail` | **保留** | ③，零额外 fork |
| `ist_verify_v3` | **保留** | 四层归因 + 写回挂载点 |
| `ist_compile_v3/SKILL.md` | **重写**：去掉聚族+族骨架两阶段，流程对齐 V2 + draft走v3 + grade验provenance | 这是负收益的来源 |
| `intent_cluster.py` / `qa_cluster_intents` | **保留代码、编排不调用** | 无害、有测试；大族场景留作未来 |
| `resilience.py`（心跳+重试+main_activity） | **保留** | 与 V3 正交的可观测性/韧性，已证有用 |

## 三、实施步骤

### 步骤 R1：重写 ist_compile_v3 编排器（去族摊销）
- 删除"聚族"（qa_cluster_intents）和"族骨架"两个阶段。
- 流程对齐 V2：版本校验 → prep → `qa_compile_fanout(ist_draft_v3)` 逐 case 并发（**不先编骨架**）→ `qa_compile_fanout(ist_grade_v3)` → 判定/重做 → 合并。
- draft fanout 默认 auto 并发（步骤0 已实现，保留）。

### 步骤 R2：改 ist-draft-v3 agent（去族骨架复用分支）
- 删 brief 里"若带族骨架则复用 G 段"的逻辑——回到 V2 draft 的 G→E→V 自查，**额外产 provenance_json**。
- draft 行为 = V2 draft + 旁挂 provenance。轮数应回到 V2 的 ~11，不再有 18.7 轮的族骨架。

### 步骤 R3：验证（单脑图先，再全量）
- 先单 dongkl：draft 轮数对齐 V2（~11）、产 provenance、grade grep < V2、产出完整 34-case excel。
- 对照 V2 基线确认 **V3-R 不慢于 V2**（去掉族骨架后应基本持平，grade 因验 provenance 略快）。
- 通过后每脑图独立 -p 跑（治 recursion 预算，不一次喂3个），产 3 excel 人工检查。

## 四、红线
- **不在骨架层加戏**（论文实测：骨架两臂打平）。收益维度是 grounding（E 段），V2 结构门已做对，保持。
- provenance 是**记录不是规则**，只标 draft 已做的来源决策。
- 写回只写**上机真 PASS 的 G 段**，evidence 门防幻觉，不写 V 段/不建意图→命令映射。
- V1/V2 链零回归；pytest 全绿。

