# 研究:LLM 驱动网络设备测试自动化 — 竞品/先例对照(2026-07-15)

> **来源**:对照检索 agent 深挖六个项目全文——NeTestLLM(arXiv:2510.13248)、
> Keysight US12505309B2、iPanda(arXiv:2507.00378)、Cisco pyATS/Genie/NAPALM、
> NetConfEval(CoNEXT'24)、AutoSpec(arXiv:2511.17977)。
> **目的**:差缺补漏我们的理论/设计文档 + 佐证引擎专利新颖性。
> **语言**:中文给结论与借鉴清单(可执行部分);英文详析保留论文原引(引文不译以免失真),
> 属"参考文档只写机制、数据按引用"——细节现查论文 URL。

---

## 一句话结论

**Oracle 轴上我们独一份**:三个 LLM 项目(NeTestLLM/iPanda/Keysight)都**没有独立行为 oracle**
——靠"与参考脚本相似度 / 代码能跑 / LLM-as-judge / 人审"判对错。但成熟的**非 LLM** 框架
(pyATS/Genie/NAPALM)**有**强 oracle,机制正是我们只用了一半的那个:**断言打在结构化解析
对象的 key-path 上,永不打 raw CLI 文本**。所以我们的差异化是真的,但成熟框架也照出我们的
oracle 层仍原始(raw-text `found/not_found` + 补丁门,而它们会解析成对象再绑字段)。

> **计数已对源码核对**(对照 agent 二次验证):归因 = **5 层**
> (`fail_attribution.py:_LAYERS`)× 7 处置 × 4 隐藏自由度位;门 = **74/10 域**
> (`AUDIT_gate_inventory_20260714`)。CLAUDE.md 的"17 文法门+5 原理检测器"是同一门集的
> **自愈组织视角**,与操作清单正交、**不相加**。

- **我们领先**:oracle 独立性、机械门、归因丰富度、只重编 fail 的不动点。
- **我们落后**:spec 解析前端、覆盖率生成、结构化对象断言、流量发生器集成、benchmark 严谨度。
- **最高价值借鉴全都是"闭合 oracle 的理论→实现 gap"**(结构化断言通道、Errored/Blocked
  第三态、MA/TA 度量、OSI 链下降),而非加新的未机械化理论。

---

## 借鉴清单(按优先级,已映射到我们的文档锚点)

### P0 — 结构化对象断言通道(oracle 残差的可操作形态)【全报告最高杠杆】
emit 契约加 `(parser/getter, key_path, operator, expected)` 通道,优先于 raw
`found/not_found`(照 Blitz `parse` > `execute`)。这是 `THEORY_target_system_algebra`
§5 投影核 π + §3 承重合取的**具体落地形态**,直接消灭 `V_layer_weak_assertion_analysis`
四型(尤其"断言未绑定对象")。**必带 fail-loud 警告**(Genie 静默断裂血教训:解析 schema
不认的输出→显式报错,不让 LLM 现编 key-path;schema 锚手册/footprint)。改的是 oracle **层**,
不是加第 75 个补丁门。

### P0 — Errored/Blocked/Aborted 第三态(印证我们自己的 #1 审计缺口)
`AUDIT_design_theory_gaps` §1 已标:verdict schema 二值,采集层却发 5 值
(pass/fail/error/busy/unknown)在 `nodes.py:586` 折叠。pyATS 7 码 + 滚动优先级
(**Errored>Failed>Aborted>Blocked>Passx>Skipped>Passed**)是成熟外部模板。映射:
Errored/Aborted→不重编(infra/瞬态);Blocked→env_blocked 处置(床污染,run13);
Failed→重编。把手搓启发式(同签名 2 轮=冻结/瞬态复现=误归)升级成有原则的结果代数,
喂 `fail_attribution.py` 机械预判。

### P1 — 机械化 benchmark + naive 基线 + 消融
建版本化 `(mindmap→期望 case.xlsx)` eval 集,分阶段配 oracle 打分(NetConfEval),带常开
naive 基线 + 门关/footprint 关消融(iPanda)。报 Pass@k + 到不动点轮数 + 每案成本×模型档。
落地 CLAUDE.md 欠实现的"eval-first" + "成本换轴"轴,直击我们最薄一环。

### P1 — 形式化测试正确性度量(NeTestLLM 自认欠缺的方向)
采 AutoSpec 分级 **MA/TA**(断言接受率/案迹接受率)替二值 pytest-pass;**canonical-flow
限制**作为形式化信息含量门,喂 5 原理层检测器(尤其零信息断言)。写黄金测试意图 spec
(τ 六元组)量断言/约束 **recall**。这是 S 代数抱负的可度量化——也正是 NeTestLLM 明说
留给未来的"formal methods for test-case evaluation"。

### P1 — OSI 链归因下降(机械化一个"只在设计叙事里"的定理)
`AUDIT_design_theory_gaps` §3 列承重链下降(§30)为 C 级未机械化。NAPALM getter / Genie
`learn` 的分层结构化状态=机械探针序列,把 L7-fail→L4-listen→L3-reach→L2-adjacency
逐层机读。

### P2(不阻断)
- **spec 解析/脑图审计前端**:RFC-2119 关键词抽取(iPanda)+ 分层建模(NeTestLLM)作
  **确定性**阶段,审计人工脑图覆盖缺口或播种——守我们的数据形态律(抽取=py/确定性,
  塑形=LLM/skill)。
- **用例键校正注册表(Keysight FIG.5)+ 派发前资源清单一致性门**:交叉核对每个被引用
  IP/ID 存在于 `network_topology.json`(廉价确定性门,系 run18 基线面教训)。
- **结构化 Ops 基线 + 对象级 diff(Genie learn/diff)+ `_mode: strict` 集合相等**:硬化
  run13(再生污染者)/run16(跨床)/run18(基线面)床污染处理。

---

## 他们 vs 我们(对照表)

| 轴 | NeTestLLM | iPanda | Keysight US12505309B2 | pyATS/Genie/NAPALM | NetConfEval/AutoSpec | **InfoTest Engine(我们)** |
|---|---|---|---|---|---|---|
| **意图源** | RFC(分层解析) | RFC(2119 关键词) | NL 测试目标 | 人工 testbed/YAML | NL 意图 / RFC | **人工脑图**(无 spec 解析前端) |
| **产物** | 测试脚本+DUT CLI 配置 | Python 一致性脚本 | TG 配置(ixNetwork) | 结构化断言(代码/YAML) | 形式 spec/配置/文法 | **case.xlsx**(断言+配置,确定性 emit) |
| **Oracle** | 相似度+LLM-judge 覆盖+人审——**无行为 oracle、无反恒真** | 执行通过+LLM-judge+人审 | **无**(只报不判) | **结构化对象 key-path 断言**(确定性,成熟答案) | 精确匹配/pytest/仿真可达(手动);AutoSpec 分级 MA/TA | **上机框架跑=语义 oracle** + 17 机械反恒真门(但打 **raw 文本**,非结构化对象) |
| **归因** | **4 非形式类**(语法/配置;DUT bug;tester 缺陷;测试设计缺陷)→自修/**人**判 DUT-vs-系统 | **无**(统一重生;人+关键词过滤) | **无** | 7 结果码(verdict,非根因) | 无 / repair-agent 定位 | **5 层(G/E/V/瞬态/产品缺陷)×7 处置×4 隐藏自由度位(λ/s₀/π/none)**,机械路由;LLM 只碰 undetermined 占位(解析进 product_defect) |
| **门(执行前)** | 无(运行时才暴露断裂) | 无 | 1 资源一致性检查 | 解析 schema=门 | schema-valid(Pydantic) | **74 确定性门/10 域**(`AUDIT_gate_inventory_20260714`:结构门 19+引擎节点 24+emit 11+上机 8+合并凭证 3+…),理论投影自框架 regex 语义+目标系统代数 |
| **循环** | 两级(小=产物,大=测试案)→人升级 | 增强 CRITIC 重生,cap~6 | 执行前 LLM 精修+跨会话 broker 调优(无 exec→config 边) | N/A(人写测试) | AutoSpec:执行制导 repair(过拟合风险) | **编译→上机→归因→只重编 fail 不动点**(冻结/隔离止损,ledger 合法性表) |

**一行读法**:我们在 **oracle 独立性、机械门、归因丰富度、只重编 fail** 上独强;在
**spec 解析前端、覆盖率生成、结构化对象断言、流量发生器集成、benchmark 严谨度**上落后。

---

## 诚实差距:他们真正领先处

1. **流量发生器集成**:NeTestLLM 端到端驱动 Xinertel DARYU/BigTao(Spirent 级)发生器。
   我们只经 CLI 测设备状态,无包注入/流量模型 tester——数据面/协议测试的真能力缺口。
2. **协议/spec 覆盖 + 覆盖率度量**:NeTestLLM 分解 RFC(包字段/FSM/时序)并**给覆盖打分**
   (breadth+depth)。我们**无覆盖概念**——编给定脑图,从不问"漏了什么"。
3. **benchmark 严谨度**:NetConfEval(版本化数据集、配套 oracle、批量精度曲线)、iPanda
   (Pass@k、干净消融)、AutoSpec(MA/TA、黄金参考、naive 基线)都远比我们轶事驱动的评估严谨。
4. **结构化对象 oracle 成熟度**:pyATS/Genie/NAPALM 在断言层领先十年——我们 raw-text
   `found/not_found`+补丁门正是它们早已越过的反模式(Blitz `execute`)。
5. **"好测试"的形式化 spec**:AutoSpec 从形式文法导断言(断言=任何合法行为迹必满足者);
   我们手调机械门。他们的文法即 spec,是我们 S 代数所追的成熟形态。
6. **生产规模证据**:NeTestLLM 生产运行数月、4632 案、41 真 bug、12 专家研究;我们是
   run-series 取证,非部署规模。

**引用他们时的注意**:iPanda(2 个 Python 库、loopback 仿真、未评审 preprint、人在环)与
AutoSpec(5 个 ASCII 协议、非设备配置)证的是**方法可行**,非无人值守可信;NeTestLLM 是唯一
生产部署、评审级的对标——而它也把 oracle 让给了相似度+人审,这恰是我们要压的差异点。

**给文档的净论点**:我们理论在 **oracle 独立性+归因+不动点**上领先每个 LLM 竞品,但只机械化
了~20%(`AUDIT_design_theory_gaps`);而成熟非 LLM 框架显示我们的 oracle **原语**落后十年
(raw text vs 结构化对象)。最高价值借鉴全部**闭合 oracle 的理论→实现 gap**(结构化断言通道、
Errored/Blocked 第三态、MA/TA 度量、OSI 链下降),而非加新的未机械化理论。

---
---

# 详细分析(英文,含论文原引 — 参考按 URL 现查)

## 1. NeTestLLM — arXiv:2510.13248 (our closest analog)

"Automated Network Protocol Testing with LLM Agents" (Yunze Wei et al.; Tsinghua + Tencent +
Xinertel/信而泰). Production-deployed. Sources: https://arxiv.org/abs/2510.13248 ,
https://arxiv.org/html/2510.13248v1

**What it does.** Four-stage multi-agent pipeline, RFC → executable tester scripts + DUT CLI configs:
- **Stage 1 — Hierarchical RFC understanding.** High-level agents: *Section Splitting* (RFC→section
  tree), *Section Summarization* (per-section summary + test-importance high/med/low, on Qwen-Max),
  *Module Formation* (partition sections into functional modules). Low-level modeling agents: *Packet
  Field*, *FSM* (states/transitions), *Message Time Sequence*, and *Protocol-Specific Function* —
  each extracts "testing points."
- **Stage 2 — Test-case generation + coverage verification.** *Test Case Generation Agent* (testing
  points → NL test cases). Then a **two-dimensional coverage oracle**: *Coverage Breadth*
  (threshold-scored `score = test_importance × w(section_class)`) and *Coverage Depth*
  (**LLM-as-judge** scoring basic-function + boundary-condition coverage), feeding a *Refinement
  Agent* that iterates until thresholds met.
- **Stage 3 — Executable artifact generation.** A *Core Generation Agent* (GLM-4.5) guided by a
  domain knowledge base (SOPs, expert heuristics), plus three sub-agents: **Fault Corrector**
  (experience pool of categorized errors), **Summarizer** (RAG hierarchical index over hundreds of
  tester APIs / CLI pages), **Orchestrator** (coarse test-case → fine-grained intent + few-shot).
  Max 10 rounds × 3 attempts.
- **Stage 4 — Two-level runtime feedback.**

**Two-level feedback loop (their headline mechanism, closest to our fixpoint).**
- **Small loop** = artifact refinement: deploy+execute → runtime logs → Fault Corrector classifies
  error (syntax / config-mismatch / unsupported-command) → retrieve similar historical case →
  candidate fix → redeploy.
- **Large loop** = test-case refinement: when the small loop exhausts, route back to test-case
  generation to "synthesize refined or alternative test cases to isolate the suspected cause"; if
  still failing → **flag for human expert review** to decide DUT-vs-systemic.

**Fault taxonomy (their attribution).** Explicitly **three root-cause classes** for unresolved
errors (verbatim): "(1) DUT implementation bugs or incomplete documentation, (2) functional
limitations or defects in the tester, or (3) logical flaws or ambiguities in the test case design
itself" — plus the small-loop error categories (syntax / config-mismatch / unsupported-command).
**Routing:** auto-fix in small loop; the DUT-vs-systemic decision is **human**.

**Oracle / verdict — the critical weakness.** There is **no unified execution oracle and no
independent behavioral verdict.** For test-case *quality* they use LLM-as-judge (coverage depth).
For artifact *quality* the metrics are **Validation Rate** (artifact runs / passes review),
**Recall** (line-by-line vs a human reference script), and **Similarity**
(`SIM = 1 − normalized-edit-distance` to a human reference). The paper contains **no mechanism
ensuring a generated assertion actually checks the intended protocol behavior** (no anti-tautology
concept), and "if an artifact passes its own checks, it is then subject to manual review for final
validation." Correctness is judged by **similarity to human reference + human sign-off**, not by an
independent behavioral oracle.

**Limitations / future work — directly relevant to us.** They explicitly name our target: *"Future
work can explore integrating protocol models and formal methods to establish a more systematic
evaluation framework"* and *"test case evaluation can be viewed as a meaningful and independent
research direction."* Validation rates 89.7% (scripts) / 93.1% (configs) mean ~10%/7% need human
correction.

**Evaluation.** Protocols OSPFv2 (RFC 2328) / RIPv2 (RFC 2453) / BGP-4 (RFC 4271). DUTs: Huawei
CE6881 switch (acceptance) + FRRouting (dev). Testers: **Xinertel DARYU / BigTao traffic generators**
(Spirent-class). 4,632 test cases; covered **41 FRRouting historical bugs vs 11 by national
standards (3.7×)**; key-section coverage 95–100% vs 44–60% industry; **8.65× efficiency**; $0.81/
script vs $52.42/hr. Ablation: all three sub-agents on vs off = 65.5%→89.7% VR. Cross-model stable
(GLM-4.5 89.7 / Qwen3-Coder 86.2 / DeepSeek-V3.1 79.3). 12 domain experts in the user study.

**What we borrow.** (a) Their **RFC hierarchical modeling** (packet-field / FSM / time-sequence
decomposition) is a spec-parsing front-end we lack. (b) **Coverage breadth+depth verification as an
explicit graded stage** — we have no coverage metric at all. (c) Their honest admission that they
lack formal test-case evaluation is our opening: **we should claim the oracle + anti-tautology gates
as our contribution to exactly the gap they name.**

---

## 2. iPanda — arXiv:2507.00378

"iPanda: An LLM-based Agent for Automated Conformance Testing of Communication Protocols"
(Tsinghua-led). Sources: https://arxiv.org/abs/2507.00378 , https://arxiv.org/html/2507.00378v1

**What it does.** Five modules for protocol conformance testing: **TCG** (regex-extract RFC-2119
MUST/SHALL paragraphs → "functional points" → few-shot → structured test cases:
name/preconditions/steps/assertion/precautions); **Code Gen & Reasoning** (test case → Python script,
aided by **codeRAG**); **Execution**; **Memory** (short-term trajectory cache window=10 + long-term
repo with successful code + debug experience); **Summarization** (distills experience + writes the
conformance report). Core loop = **"augmented CRITIC"**: generate → execute → critique → regenerate,
**retaining the full trajectory** of prior code versions, cap ~6 iterations. **codeRAG** embeds
implementation source and **re-retrieves keyed on the error message each iteration** (top-4).

**Oracle — two-tier, both weak.** Code-correctness = **execution-based only** ("does it run without
error"). Conformance verdict (the actual goal) = **LLM-as-judge + a keyword filter to strip
code-bug-tainted reports + manual review.** No independent semantic oracle.

**Failure attribution — none.** No taxonomy; **uniform regeneration** on any error; on cap, case
abandoned. It has **no mechanism to decide "persistent failure = real non-conformance finding vs
buggy test script"** — that disambiguation is deferred to human review. This is precisely what our
attributor mechanizes.

**Limitations.** No dedicated limitations section. Only 2 protocols, both Python (CoAP/aiocoap,
RSocket/rsocket-py), loopback simulation. Manual review load-bearing at 3 points. Good hygiene: they
**froze long-term memory for CoAP** to isolate framework contribution from LLM built-in knowledge.

**Evaluation.** Pass@k (mainly Pass@1). CoAP-set 231 cases / 11 RFCs; RSocket-set 62. GPT-4o
**17.32%→80.95%** (4.7×), DeepSeek-V3 9.5%→57%, Qwen2.5-Coder 3%→32% (10.8×). ~90%+ converge in
**≤6 iterations**. Ablation: remove augmented-CRITIC → collapses to ~17% baseline; codeRAG on RSocket
14.5%→38.7%.

**What we borrow.** (a) **Pass@k + iterations-to-fixpoint distribution** as first-class loop metrics
("X% converge in ≤N recompile rounds") — we reason about convergence only qualitatively. (b)
**Ablation-as-justification**: turn a component off, measure the drop — we should run gates-off /
footprint-off deltas instead of "it caught a regression once." (c) **Error-message-keyed
re-retrieval** before recompile (feed the raw device failure into footprint/`fs_grep` retrieval) —
aligns with our "首败即升深度 + feed full history" rule. (d) **RFC-2119 keyword→functional-point
extractor** as a deterministic front-end to audit/seed mindmaps.

---

## 3. Keysight US12505309B2

"Methods…for network test configuration and execution using brokered communications with a large
language model." Granted 2025-12-23. Sources: https://patents.google.com/patent/US12505309B2/en ,
https://www.freepatentsonline.com/12505309.html

**What it does.** An **LLM Communication Broker (LCB)** between tester and a chatbot LLM. Pipeline: NL
test goal → LCB prompt-engineers (augments with **test-system-resource info + SUT topology**: IPs,
ports, TG capabilities) → invoke LLM via API → LLM returns config (Python/ixNetwork scripts) → LCB
fixes up output → push to traffic generators → **conduct the test.** Claim 1 stops at "conducting the
network test." Dependent claims add: NL input (2), prompt engineering (3), configure traffic
generators to a DUT (4), domain-specific-LLM selection (5), iterative LLM refinement (7/16), and
**inconsistency-detection + update (8/17)**.

**Heuristic correction (their emphasized differentiator).** Post-LLM, the LCB detects **missing
resource IDs/IP addresses** in generated code and **substitutes real values from a stored resource
inventory + a per-use-case metadata table** (FIG. 5), with LLM re-prompt as fallback "until a stop
value or criterion is reached." Rule/inventory-driven, **all before execution**, correcting the
config artifact — never driven by a test result.

**Oracle — absent.** Results are merely "collected and reported." No verdict logic, no
re-verification, no semantic-equivalence check. The only feedback loop is **cross-session broker
tuning** from user feedback (LAM module) — no execution→config feedback edge.

**Failure attribution — none.** No taxonomy, no root-cause layering.

**Explicit absences (all confirmed):** post-execution verdict re-check, semantic-equivalence
checking, recompile-on-failure fixpoint, test-bed pollution/state-carryover, deterministic assertion
gates, verified-fact writeback. It patents the **front half** of our pipeline only.

**What we borrow.** Their missing-ID/IP fill ≈ our `config-automation` IP substitution + `<RUNTIME>`
slot fill (`compile_runtime_fill`) — **independent arrival at the same pattern = prior-art
validation.** Two concrete ideas: (a) a **use-case-keyed metadata table** (FIG. 5) binding {pre-LLM
prompt template, post-LLM correction logic, domain engine} per test type — a tidy declarative form of
our scattered skill/footprint routing; (b) an **explicit resource-inventory-consistency gate before
dispatch** — cross-check every IP/ID a compiled case references actually exists in
`network_topology.json` (cheap deterministic gate; ties to the run18 baseline-face lesson). We
already exceed them because our substitution feeds an *assertion* pipeline with gates + a real
oracle, not just traffic config.

---

## 4. Cisco pyATS + Genie + Blitz / NAPALM validate — the mature NON-LLM oracles (most important for our oracle design)

Sources: https://developer.cisco.com/docs/pyats/ ,
https://pubhub.devnetcloud.com/media/pyats/docs/results/objects.html ,
https://developer.cisco.com/docs/pyats/parsing-device-output/ ,
https://pubhub.devnetcloud.com/media/genie-docs/docs/blitz/design/actions/actions.html ,
https://napalm.readthedocs.io/en/latest/validate/ , and the Genie-fragility case study
https://vincent.bernat.ch/en/blog/2021-pyats-genie-parser

**The unanimous verdict: none of them assert on raw CLI text.** They parse device output into a
**schema'd structured object** and assert on a **key-path** in that object.

- **Genie parsers**: `device.parse('show version')` → nested dict with a stable schema; assert
  `output['version']['version'] == '17.6.3'`. Raw→parsed is "no entropy loss." A BGP session state is
  *always* at `info['vrf']['default']['neighbor'][x]['session_state']` — so the assertion binds to an
  **extracted field**, not to text that includes the command echo + prompt. This structurally
  eliminates both bugs we fight: matching the command echo (tautology) and matching the wrong window.
- **Blitz** makes the contrast explicit within one framework: the `execute` action matches a string
  "**somewhere in the output, irrelevant of the structure**" (officially a degenerate channel) vs the
  `parse` action returning structured data queried via **Dq**:
  `output.q.value_operator('in_crc_errors', '>', 100).get_values('[0]')`,
  `contains_key_value('enabled', True)`, `raw('[slot][rp][1][...][model]')`. Blitz also has **loop
  retry** (`max_time`/`check_interval`) to avoid reading a transition state.
- **NAPALM validate**: purely declarative YAML — getter name → expected structured value at a
  key-path, with operators (`'<15.0'`, `'10.0<->20.0'`, `±%`, regex) and **`_mode: strict`** (exact
  set-equality at that level → catches "an extra object that shouldn't be there"). Verdict = a
  deterministic **compliance report** (`complies: true/false`, `present`/`missing`/`extra`).

**Result taxonomy — pyATS has 7 codes with deterministic rollup.** Passed / Failed / **Errored** /
Skipped / **Blocked** / **Aborted** / Passx, rollup priority **Errored > Failed > Aborted > Blocked >
Passx > Skipped > Passed**. This is a mature template for the "broken third state" our own internal
audit flags as priority #1.

**Baseline/snapshot.** Genie `learn <feature>` → structured Ops object → `genie diff v1 v2` =
**object-level +/- diff** (timestamp/line-order jitter can't produce a false diff). Direct template
for our baseline-face / bed-pollution problem.

**The blood-lesson to import with it.** Genie parsers are line-regex + glue and can **"break
silently"** (documented: `show ipv4 vrf all interface` mis-nested `Loopback30`'s IP under
`Loopback10` because the interface-name regex didn't tolerate an extra field). **Structured parsing
converts "read the wrong window" into "is the parser schema faithful" — and a silent-break
mis-located object is *harder* to catch than raw text.** So our object-chain parse layer **must be
fail-loud** (unrecognized output → explicit error, like TextFSM/YANG), command+OS+manual-anchored —
not LLM-improvised key-paths.

**What we borrow — the biggest structural idea in this whole report:** add a **structured-assertion
channel** to our emit contract — `(parser/getter, key_path, operator, expected)` — that coexists with
but is *preferred over* raw `found/not_found`, exactly as Blitz prefers `parse` over `execute`. This
is the operable form of our object-chain / oracle-residual theory, and Genie Dq's `value_operator` +
NAPALM's key-path+operator are ready-made syntax. Plus: adopt the **Errored/Blocked/Aborted
separation** into attribution; upgrade baseline snapshots to **structured Ops + object-level diff**;
use `_mode: strict` set-equality for "exactly these members" cases (run13 regenerating-polluter,
run16 cross-bed).

---

## 5 & 6. NetConfEval + AutoSpec (benchmarking + formal-spec templates)

**NetConfEval** (KTH + Red Hat, CoNEXT'24). Sources:
https://dejankostic.com/documents/publications/netconfeval-conext24.pdf ,
https://github.com/RedHatResearch/conext24-NetConfEval ,
https://research.redhat.com/blog/article/can-llms-facilitate-network-configuration/ . A benchmark on
an **abstraction ladder** with a **matched oracle per stage**: NL→formal spec (closed JSON schema
over reachability/waypoint/loadbalancing, scored by **exact-match**, plus a **conflict-detection
sub-task** scored precision/recall/F1) → NL→API calls → routing code (scored by **pytest
execution**) → high-level→low-level FRRouting config (scored by **Kathará emulator reachability via
ping/tcpdump — but currently manual**). Findings: batch translation ~10× cheaper at 100% accuracy but
**accuracy degrades as batch size grows**; LLMs **over-interpret/false-positive on indirect
conflicts**. Versioned HuggingFace dataset.

**AutoSpec** (CISPA/Zeller group + Volkswagen, arXiv:2511.17977). Sources:
https://arxiv.org/abs/2511.17977 , https://arxiv.org/html/2511.17977v1 . Domain is
protocol-conformance of software (SMTP/IMAP/FTP…), **not device config** — but its correctness
formalization is the best template found. RFC → **executable I/O grammar** (formal FSM:
states/commands/responses + constraints, **with provenance**) → grammar-fuzzer (Fandango) generates
tests. **Two-level oracle expressed as graded metrics**: structural (schema-valid, Pydantic) +
execution (real SUT conformant response), reported as **Message Acceptance (MA)** and **Trace
Acceptance (TA)** — plus **canonical-flow-restricted variants (RtCMA/RtCTA) that discount
trivially-accepted messages.** An **independent-vs-dependent constraint taxonomy** (single-field
ranges/enums vs multi-field/temporal/ordering). A **Repair Agent** (classify→localize→minimal-diff
patch→re-synthesize) with an explicit warning that it **can overfit / drift toward an
implementation-specific spec.** Naive zero-shot baselines "all failed to produce a valid executable
grammar."

**What we borrow.** From NetConfEval: **ship a versioned held-out benchmark** of
`(mindmap → expected case.xlsx)` pairs, **scored per-stage with matched oracles** (structured-match
for τ-hexatuple/assertion fields; on-device run as our Kathará-equivalent behavioral oracle); a
**multi-axis scorecard** (accuracy × cost-per-case × model-tier — operationalizes our "成本换轴"
axis); a **conflict/ambiguity sub-benchmark** measuring whether we correctly raise
`needs_decision`/`ask_user` vs silently guess (and NetConfEval predicts the failure mode: LLMs
over-fire on conflicts); an **always-on naive baseline** (mindmap→xlsx, no gates/loop) quantifying
the engine's value-add. From AutoSpec: express our A-gates + on-device verify as **graded MA/TA-style
acceptance metrics** instead of binary pytest-pass; **canonical-flow restriction** as a formal
information-content gate against 恒真/zero-information assertions; **golden-reference test-intent
specs** to measure assertion-type/constraint **recall** — this is literally "formal methods for
test-case evaluation," the thing NeTestLLM defers; the **independent-vs-dependent constraint
taxonomy** for our `ordering_sensitive`/有序语义 concerns; and the **repair-overfitting caution** —
recompiling assertions against one bed risks overfitting to that bed's quirks (a cross-bed/golden
anchor detects drift; our recent s₀ cross-bed commit gestures at this).

---

## 附:专利素材(与检索交叉)

- **整体形态不新颖**:NeTestLLM(2510.13248)+ Keysight(US12505309B2)已占"LLM 编译网络
  测试+上机迭代"。**新颖性在机械验证栈**——F2 oracle 残差(近乎无 prior art,三个 LLM 项目
  全无独立行为 oracle)最强,F1 理论投影门次之,F6 配置面代数须窄 claim。
- **本 session 实证即专利素材**:window 失真、s₀ 假阳需机械复核、env_blocked 误判有机械反证
  ——都是机械验证栈价值的活案例(F5 归因机械复核的 motivating example)。
- **正式申请前**:查中文专利(NeTestLLM 国内团队 Tsinghua+Tencent+信而泰,极可能有对应
  中文申请)+ 核对 2026 文献优先权日。**非 FTO 结论**。
