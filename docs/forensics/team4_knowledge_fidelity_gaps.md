# team4 知识供应链保真缺口(#54 校准后复核 · 只读取证 + 修法规格)

- 作者：LLM-Eng（team4）；日期 2026-07-20；HEAD `1e0e0298`
- 授权：team-lead 回执（两项深挖，只读，产出=规格，实现派 Py-Eng）
- **证据边界**：全部结论基于盘上机读账与源码行级核对（footprint 节点 JSON、`runtime/logs/verified_runs.jsonl`、`runtime/logs/k_signals.jsonl`、批次 `facts.jsonl`/`engine_report.json`、`case.xlsx` openpyxl 读取）。**未上机、未跑测试、未改任何文件**。设备侧行为未复核。

---

## 缺口①：uncertain → verified 升格从未发生（与 calib 报告 (d) 节矛盾）

### 与报告的矛盾点

`docs/forensics/team4_calib_batch54.md` 称「writeback provisional=false，validity:uncertain→verified 闭环」。盘面反证：`knowledge/footprints/nodes/ssl.activate.certificate.json` 的 `importcert_auto_activates_no_manual_reactivate` 条目在 003 clean-recompile 判 `delivered_all_pass` 之后**仍为 `validity: "uncertain"`**。

**对证结论：报告的 provisional=false 部分为真，validity 升格部分为假。** 二者是两条独立的写回路，报告把它们并成了一句。
- provisional=false 属实：`knowledge/framework/mirror_precedent_provenance.json` → `verified_205400000000000003.xlsx: {"provisional": false}`；`workspace/outputs/slbssl_calib_003/facts.jsonl` 第 6 行 `{"ev":"writeback","targets":["precedent","footprint"],"provisional":false}`。
- 升格未发生，且**不是该节点特例——全域从未触发过一次**。

### 全域证据

```
runtime/logs/k_signals.jsonl:
  upgraded_verified   → 0 条
  uncertain_ingested  → 2 条
```

升格信号 `upgraded_verified`（`merger.py:370` 发射）计数为 0，即自愈环的**演化端在生产中从未闭合过**；入库端也只跑过 2 次。

### 根因（file:line 级）：三条写回路的 fact_key 命名空间互不相交

merger 的升格分支按 **同节点 + 同 section + 同 `fact_key`** 对齐：

- `main/ist_core/memory/footprint/merger.py:362` — `if existing.get("validity") == "uncertain" and validity == "verified":` → 就地升格。

而写回侧存在**三条**产键规则，各自键空间不交：

| 路径 | 代码 | fact_kind | fact_key 形态 | 落点 |
|---|---|---|---|---|
| A 机器入库（uncertain 端） | `compile_engine_v8/uncertain.py:93-103` | `behavior` | `{feature_head}:{sha1(归一化内容)[:8]}` | 节点 `behaviors` |
| B 行为晋升（verified 端） | `compile_engine_v8/uncertain.py:159-165` | `behavior` | 同 A（同源，设计上唯一能对齐 A 的路） | 节点 `behaviors` |
| C PASS 文法写回 | `memory/compile_writeback.py:80-83` | `cli_command` | **命令原文** | 节点 `cli.commands` |

`ssl.activate.certificate` 那条 uncertain 条目的 `fact_key` 是**语义短语** `importcert_auto_activates_no_manual_reactivate`，落在 `decision_rules` section —— 不属于 A/B/C 任何一条产出的键空间与 section。它是 #58 治理时由 LLM/人**手写**入库的知识条目。

**故：无论 003 跑多少次 PASS，B 路产出的 `{head}:{hash}` 键永远碰不到这条语义键；C 路产 `cli_command` 落 `cli.commands`，更不相干。升格在结构上不可达，不是概率问题。**

第二重阻断（同一案上叠加）：003 的 delivered 目录**没有 `behavior_candidates.json`**（`workspace/outputs/slbssl_calib_003/delivered/*/` 仅 `case.xlsx / case.provenance.json / intent.json / needs_decision.json`）→ `_promote_behavior_candidates` 在 `uncertain.py:127-128` `if not cands: return` 空转返回。即便键空间对得上，B 路这次也无料可升。

### 排除 07-16 同型（`sh.env_flag` 漏带）

已核，**不是**同型残余：
- `_shared.py:316-320` `env_flag(name, default="1")` 默认开；
- `uncertain.py:65`（uncertain 入库）与 `uncertain.py:123`（行为晋升）均正确带 flag 名调用；
- `environment` / `environment.example` 中 `FOOTPRINT_UNCERTAIN_WRITEBACK`、`FOOTPRINT_BEHAVIOR_WRITEBACK` **均未出现**（无人关闭）。
- 佐证：`uncertain_ingested` 有 2 条真实信号，说明入库端 flag 通路是活的。

### 修法规格（缺口①）

**须先由 Theory/Design 裁决走哪条，不建议 Py-Eng 直接选。**

- **方向 R1（键空间对齐，治本）**：手写/LLM 写入的知识条目也必须落在机器可对齐的键空间——即 uncertain 条目的准入统一收口到 A 路（`RawFact` + `route_facts` + `merge_fact`），禁止旁路直写节点 JSON。代价：#58 那类「读 mirror 源码得出的机制性判断」不是设备观察，塞进 `behaviors` 语义上不对（它本就该在 `decision_rules`）。
- **方向 R2（升格判据换轴，治标且语义更正）**：承认 `decision_rules` 类条目的升格判据不该是 fact_key 对齐，而应是**显式待确认锚**——条目写入时带 `pending_confirm: {autoid, expect: "pass"}`，closing 在该 autoid 真 PASS 时按 autoid 索引升格。代价：新增字段与索引路径。
- **机器守门（无论选哪条，必须有）**：一条断言 `upgraded_verified` 在自愈演练中必然发射的回归——现有 `tests/ist_core/memory/test_self_healing_loop.py` 显然未覆盖真实键空间（否则 0 计数早暴露），需补**跨 section 的端到端**用例，而非同 section 构造。
- **不建议**：为对齐而把语义键改写成 hash 键——会毁掉该条目对 worker 的可读性与 grep 可达性。

---

## 缺口②：PASS 文法写回把「含实参 + 框架 kwarg 的命令行」当 CLI 语法签名

### 现象（盘面原文）

`knowledge/footprints/nodes/ssl.activate.json`：

```json
"cli": {"commands": [{
  "fact_key": "ssl activate certificate vh1,prompt=YES",
  "command":  "ssl activate certificate vh1,prompt=YES",
  "evidence": {"quoted_text": "ssl activate certificate vh1,prompt=YES",
               "device_run": {"autoid": "205400000000000003",
                              "run_ts": 1784472473.53408,
                              "build": "InfosecOS_Beta_APV_HG_K_10_5_0_568"}}}]}
```

三处失真，逐条：
1. **`,prompt=YES` 不是 CLI 语法**——它是框架 xlsx 执行器的 kwarg（`domain_grammar.json` `executor_contract`，出处 mirror `lib/test_xlsx.py::get_parameter`）。写进 `cli.commands` 后，worker 检索会读成「这条 CLI 命令的语法里含 prompt 参数」。
2. **`vh1` 是本 case 实参**，被固化成语法签名的一部分。
3. **与手册签名重条目**：同族节点 `ssl.activate.certificate` 已有手册出处的正确签名 `ssl activate certificate <host_name> [certificate_index] [domain_name] [certificate_type]`。现在同一命令在知识树里有两个互相矛盾的「语法」。

**放大性**：`compile_writeback.py:82` `fact_key=cmd` 对**每个 PASS case 的每条 G 段命令**成立 → 每次成功交付都在复制这一类污染，与批量规模同增。这是建议 #55 放量前先修的理由。

### 根因（file:line）

`main/ist_core/memory/compile_writeback.py:79-83`（`_g_step_to_rawfacts`）：
```
out.append(RawFact(
    fact_kind="cli_command",
    fact_key=cmd,        # ← 命令原文直接当键
    cli_syntax=cmd,      # ← 原文直接当语法
    ...))
```
`cmd` 来自 G 段 provenance 的卷面原文，未经任何归一化。

### 修法规格（缺口②）

**S1 — kwarg 剥离（机械判定，不硬编码 `,prompt=`）**

判据从 mirror `get_parameter` 语义机械推导，与 `executor_contract` 同源：
- 对 G 段命令按**引号外逗号**切段（切法必须与 `get_parameter` 一致，实现时以 mirror 源码为准，勿另写一套）；
- 尾部形如 `^[A-Za-z_][A-Za-z0-9_]*=` 且键**无空格**的段 = 执行器 kwarg，从 `cli_syntax`/`fact_key` 剥除；
- 剥除的原文**不丢**：整条原文落 `RawFact.raw_invocation` 新字段（`schema.py:41-44`，第一单已实现），仅当它与剥净的语法位不同时才写进 evidence，供审计回溯「设备上实际发的是什么」。
  > **修正（2026-07-20，Design 回执③）**：本条初稿曾写「原文存进 `evidence.quoted_text`」，**该写法是错的** —— `quoted_text` 是证据门的针（必须在手册/卷面命中），塞进不命中手册的设备原文会让整条 fact 被 `skip`，等于**静默关掉写回**。以 `raw_invocation` 为准。
- **不要**维护 `{prompt, timeout}` 白名单做判定——键集会随框架版本增长（参考文档只写机制、数据按引用）。白名单只可用于**告警**（出现未知 kwarg 时记信号），不可用于判定。

**S2 — 实参参数化：保守，本轮不做**

主机名 `vh1` → `<host_name>` 的替换**无机械依据**（需要知道该 token 在手册签名里的位次，而 G 段命令未必能与手册签名可靠对齐；错配会造出假语法）。规格：
- 本轮**只剥 kwarg，不做实参参数化**；
- 但**须避免重条目**：写回前若同族节点 `cli.commands` 已存在可挂接的手册出处签名，则本次 PASS 只把 `device_run` 证据**挂到那条已有签名上**（`verified_count` 照常累计），不新建以实参为键的条目。
  > **挂接判据（2026-07-20，Design 回执④ 定稿）**：**剥净命令词 token 序列完全相等**（Design 条件⑴）—— 即剥掉 kwarg 与实参后的命令词序列逐 token 全等才挂接，**不用前缀匹配**。`uncertain.py:28 _behavior_feature_head` **只作节点寻址**，不参与挂接判定。本条初稿曾写「同命令词前缀 + 复用 `_behavior_feature_head` 判挂接」，前缀匹配会把 `ssl activate certificate` 与 `ssl activate` 类父子命令错挂，已按回执改为全等。
- 若无已有签名可挂：仍以剥 kwarg 后的原文建条目，但**须打 `syntax_provenance: "device_run_verbatim"`** 标记，与手册出处签名（`source_file` + `quoted_text`）在渲染层可区分——让 worker 知道这条是「跑通过的一个实例」而非「语法」。

**S3 — build 取数源（568 ≠ 585 的根因，全域失真）**

链路：
```
footprint 节点 device_run.build
  ← footprint_writeback.py:76-78  （读 verified_runs.jsonl 的 build 字段）
  ← batch_tools.py:1361           `_eff_build = (build or get_config().build)`
  ← config.py:83                  build: str = "InfosecOS_Beta_APV_HG_K_10_5_0_568"   ← 硬编码默认值
```
`runtime/compiler_config.json` 无 `build` 覆盖、`IST_DEVICE_BUILD` 未设 → 兜底生效，**每条台账都盖 568**（`verified_runs.jsonl` 中 003 的三条记录全是 568）。
而**设备实测值 585** 来自 bed_gate 探针：`compile_engine_v8/bed.py:518-528`（`show version` + `extract` 正则）→ `engine_report.json` `bed.device_build`。

规格：
- K 锚 build 必须取**探针实测值**（引擎已有该值在 state / bed 报告里），由 digest 调用侧显式下传给 `dev_run_batch*` 的 `build` 入参；
- `config.get_config().build` 降为**纯兜底**，且兜底生效时台账须写 `build_source: "config_fallback"`，footprint 渲染层据此不把它当已验证版本作用域；
- **不建议**保留一个会静默生效的硬编码 build 默认值 —— 它让 K 锚在无人察觉时长期失真（本例已失真至少整个 #54 校准批）。

### 建议实现顺序

S3（取数源，最小改动、最大真值收益）→ S1（kwarg 剥离）→ S2（挂载合并 + 标记）→ 缺口① 待 Theory/Design 裁决方向后再实现。

### 未核项（诚实缺位）

- 未验证 `_behavior_feature_head` 在 SSL 域命令上的取头结果是否合理（该函数动词表来自 `domain_grammar verb_classes`，SSL 域词表覆盖度未核）。

---

## 存量污染普查（2026-07-20，team-lead 授权，只读）

扫描面：`knowledge/footprints/nodes/*.json` 全库 **2410 节点 / 5055 条 `cli.commands` 条目**（其中带手册出处 `evidence.source_file` 的 3707 条）。脚本为一次性只读遍历，未落库。

### 结果表

| # | 项 | 数量 | 说明 |
|---|---|---|---|
| A | 含框架 kwarg 的 cli 条目 | **1** | 仅 `ssl.activate.json` 的 `ssl activate certificate vh1,prompt=YES` |
| B | 无占位符且无手册出处的 cli 条目（verbatim 实例） | **1348** | 其中含具体值 token 的真实参条 **1264**，无参通用命令（本项启发式假阳性）84 |
| C | B 之中带 `device_run` 锚的 | **944** | 经 PASS 写回落库的 |
| D | 与同节点已有手册签名**重条目**（同前 3 词） | **19** | 一命令两语法的真冲突面 |
| E | 带 `device_run` 的节点 / 条目 | **33 节点 / 1062 条目** | — |
| E2 | 其中 `build` = `..._10_5_0_568`（config 兜底值） | **33 节点 / 1062 条目，100%** | **零例外，无一条来自探针实测** |

`fact_key` 形态分布（各 section）：

| section | 语义短语键(手写) | 命令原文(含实参) | `head:sha1`(机器行为键) | 其他/单词 |
|---|---|---|---|---|
| `cli.commands` | 3531 | 1510 | 0 | 14 |
| `decision_rules` | 1458 | 0 | 0 | 0 |
| `behaviors` | 1543 | 0 | **86** | 0 |
| `known_issues` | 0 | 0 | 0 | 2 |

### 对缺口①的补强证据

形态分布是「键空间不相交」的**全库量化确证**：机器行为键 `head:sha1` 共 86 条、**全部集中在 `behaviors`**；而 `decision_rules` 的 1458 条**无一条**是机器键。A/B 两路（`uncertain.py`）产的键与 `decision_rules` 零重叠 —— #58 那条 uncertain 落在 `decision_rules`，升格不可达是结构性的，不是个案。

### 对缺口②的量化修正

- **S1（kwarg 剥离）污染面极小：仅 1 条。** `,prompt=` 是近期才被 worker 用上的形态（#61 后），存量未积累。但它随每次 PASS 写回复制，属增长型 —— 修在源头（`compile_writeback.py`）仍必要，存量则无需批量处理。
- **B 的 1264 条不应一概判为「污染」。** 它们是 C 路 verbatim 实例知识的常态产物，写回红线本就是「只写 G 段」。真正的缺陷是它们与手册签名**混列同一 `cli.commands` 且无形态标记** —— 这正是 S2 `syntax_provenance` 标记要治的，标记是**追加字段**、不改内容。
- **D=19 是真冲突面**，规模小，可随 S2 上线后按需订正，不构成迁移压力。
- **E2 是本次普查最重的发现：1062 条 device_run 锚的 build 值 100% 等于 `config.py:83` 的硬编码兜底值，零例外。** 这意味着**没有任何一条 footprint 设备证据的版本作用域是可信的** —— 不是「部分失真」，是取数源恒为一个配置常量。

### 需不需要迁移脚本 —— 判定

**需要，但只做一件事：批量追加标记字段，不改任何既有值。**

阈值与理由（阈值自定，说明如下）：
- 我取的分界是 **「≤ 约 50 条 且需要人判」→ 不写脚本；「> 数百条 且判据纯机械」→ 写脚本**。依据是人工订正的可靠性在几十条量级仍可控，而超过后错漏率与复核成本都超过写一个可复跑脚本的成本。
- 按此判定：**A（1 条）、D（19 条）不需要脚本**；**E2（1062 条）+ B 标记（1264 条）需要脚本**，且二者判据都是纯机械（有无 `source_file` / build 是否等于兜底常量），可**同一次遍历完成**。

脚本规格（建议，实现待派）：
1. **不猜真值。** 存量 build 的真实值**无处可回溯** —— `verified_runs.jsonl` 本身也全是兜底值，历史设备实际 build 已不可考。故迁移**禁止改写 build 值**，只追加 `build_source: "config_fallback_unverified"`，让渲染层与 worker 知道这个版本锚不可信。任何「按当前设备 585 批量回填」的做法都是造值，红线。
2. B 类条目追加 `syntax_provenance: "device_run_verbatim"`（判据：无 `evidence.source_file`）。
3. 幂等 + dry-run 双模式，先出 diff 报告供 leader 过目再落盘；节点写入走原子 tmp+replace（与 `precedent_tools` 意图索引同款，防截断损坏）。
4. **前置依赖**：脚本须在 S3 落地**之后**跑 —— 否则 S3 上线后新写回仍继续产兜底值，标记刚打完就被新污染稀释。

### 普查项的诚实边界

- B 项用「无占位符 + 无手册出处」作启发式，已量出 84 条无参通用命令属假阳性（如 `clear sdns host method`），真实参条 1264 为可信下界。
- D 项按「同节点 + 前 3 词相同」判重，跨节点（如 `ssl.activate` 与 `ssl.activate.certificate` 这对父子）**未纳入** —— 本文开头 SSL 那例正是跨节点型，故 19 是**下界**，真实冲突面更大。跨节点判重需要节点族语义，留给实现时决定是否纳入。
- 全部为静态盘面统计，未上机、未与设备实际版本核对。

---

## 终稿规格：缺口① 修法（R2 主轴 + 条件并集）

- 依据：team-lead 转达的 Theory + Design 双专家独立裁决收敛结论（2026-07-20），**R2 主轴采纳**。
- 定位：本节是缺口① 的**实现规格**，作为第二单派 Py-Eng；缺口② 的 S3→S1→S2-reduced 已作第一单在实现中（`schema.py:41-44` 的 `raw_invocation` 字段已落，本节不重复定义）。
- 下方每条裁决挂到具体改动点，行号基于 HEAD `1e0e0298`。

### 新增证据：条件甲已核实，且逮到一条更硬的旁路实证

Design 的条件甲盘面属实 —— `main/ist_core/memory/footprint/merger.py:338-349` `_append_decision_rule`：

```python
for existing in rules:
    if existing.get("fact_key") == fact.fact_key:
        return "skip"          # ← 无升格分支、无 validity 处理
```

对照四个 section 的演化端有无：

| section | 写入函数 | 同 key 命中时 | 有演化端？ |
|---|---|---|---|
| `cli.commands` | `_append_cli`（~`merger.py:300-336`） | 内容有变则 `append` | 有 |
| `behaviors` | `_append_behavior:352-387` | uncertain→verified 就地升格 + 发 `upgraded_verified` | 有 |
| `known_issues` | `_append_known_issue:390+` | 补字段后 `update` | 有 |
| **`decision_rules`** | `_append_decision_rule:338-349` | **直接 `skip`** | **无** |

**Design 的判断成立，且比「键不交」更深**：即使把 #58 那条的 fact_key 改成机器键，落在 `decision_rules` 里依然升不了 —— 该 section 根本没有演化端。

**由此逮到的更硬证据（本次新增）**：`_append_decision_rule:342-347` 写出的条目**只有** `{fact_key, condition, decision, evidence}` 四个键 —— 它**从不写** `validity` / `observed_under`。而 `ssl.activate.certificate.json` 那条 decision_rule **带着这两个字段**。

→ **该条目不可能是 merger 产出的，只能是旁路直写节点 JSON 的产物。** 这为「前提（禁旁路直写）」提供了独立于理论推演的盘面实证：旁路不是假想风险，它已经发生过，并且正是缺口① 的直接成因 —— 旁路写入的条目天然落在任何机器演化路径之外。

### 裁决 → 实现改动点对照

| # | 裁决条款 | 改动点（file:line） | 规格 |
|---|---|---|---|
| P | **前提**：fact_key 派生单点化，四条写回路过同一派生函数，禁旁路直写 | 新增 `memory/footprint/keys.py`（建议）；改 `uncertain.py:93-94`(A)、`uncertain.py:161-162`(B)、`memory/compile_writeback.py:82`(C)；手写路→**取消**，改为经 `RawFact`+`merge_fact` | 三处现有派生逐字重复 `f"{' '.join(head)}:{sha1(...)[:8]}"`，抽为单函数即消除漂移。**section 归属保持 L_model 不收口**（Theory 明示）——派生函数只统一键，不裁决落哪个 section。旁路禁令需**机器守门**：见 T2 |
| R | **R2 本体**：`pending_confirm{autoid, expect}` 显式化「升格授权者=设备 oracle」 | `memory/footprint/schema.py:17-45` 加字段；merger 各 `_append_*` 读它 | 条目写入时携带待确认锚；升格时按 **autoid** 索引，不再依赖 fact_key 对齐。索引轴复用 A2′ per-(fact, case, round) 幂等键；三元锚 `(autoid, run_ts, build)` 按 DESIGN §5.1 前向形态挂 —— **build 位依赖缺口② S3**，S3 未落地前该位写入的是兜底常量（见普查 E2），故 **R 的落地须排在 S3 之后**，否则三元锚出生即失真 |
| 甲 | **条件甲**：`decision_rules` 补升格路径 | `merger.py:338-349` | 按 `_append_behavior:357-375` 同形改造：同 key 命中且 `existing.validity == "uncertain"` ∧ 新事实满足升格判据 → 就地升格 + `emit_signal("upgraded_verified", …, source="merger._append_decision_rule")`。同时**补写** `validity`/`observed_under` 字段（现完全不写，故旁路条目才是唯一带这两字段的来源） |
| 乙 | **条件乙**：升格判据禁「跑过就真」，须 mechanism signal 因果锚 | ~~`uncertain.py:138`~~、~~`merger.py:167`~~ → **仅 R2 新增的 `decision_rules` autoid 索引升格路径** | **本行已按 Design 回执①（2026-07-20）收缩，见下方 unit-2 定稿 §乙。** 初稿点名的两处**均不改**：`merger.py:167` 是 device_verified 证据门（我已判出）；`uncertain.py:138` 的 `pass` 是**锚选择的必要条件**，且 B 路已有卷面机械因果锚（`behavior_candidates` 的 `observe_cmd` 卷面校验）＝乙已满足。乙的**唯一强制对象**是 R2 新增路径 —— 裸 `autoid`+`verdict` 无卷面绑定，正是「跑过就真」的裸露面 |
| T1 | **守门测试**：真实写回入口驱动、跨 section、断言 `upgraded_verified` 必发射 | `tests/ist_core/memory/test_self_healing_loop.py` | 禁手构 `RawFact` —— 必须从 `_writeback_one`（`nodes.py:1387`）或等价真实入口驱动；用例须**跨 section**（uncertain 落 `decision_rules`、升格事实来自另一路），这正是现有测试漏掉的形态 |
| T2 | **生产计数 canary**：`upgraded_verified` 长期 0 → 告警 | `engine_report.json` 生成处 + TUI/报告面 | Theory+Design 合议明示「合成 fixture 只能证伪实现不满足自身假设」——绿测试不构成闭环证据。canary 读 `runtime/logs/k_signals.jsonl` 计数，长期零即告警。**本缺口就是靠这个数字（0/826）才暴露的，canary 是把这次的发现方式固化** |
| C | **理论条款**（呈用户，Theory 措辞） | 理论文档，挂 (49) 或 A2′ 之后 | 「凡设计为可演化的库条目，其演化跃迁必须存在构造性可达路径，且以生产计数为准入证据；跃迁计数恒零即视同该跃迁不存在」。对 R1/R2 中立。**落笔位置与最终措辞由 Theory 定，我不代拟** |

### 实现顺序（含与第一单的依赖）

```
第一单(在实现)  S3 ──→ S1 ──→ S2-reduced
                 │
第二单(本节)     └─→ R(三元锚 build 位依赖 S3) ─┐
                 P(派生单点化) ─────────────────┼─→ 甲 ─→ 乙 ─→ T1 ─→ T2
                                                 │
                 迁移脚本(只标记不改值) ←─────────┘  须在 S3 之后
```

- **P 可与第一单并行**（不依赖 S3）；**R 必须等 S3**（否则三元锚 build 位出生即失真）。
- 甲/乙 是 merger 侧同文件改动，建议同一 diff 出，便于 Theory/Design 一次评审。
- T2 canary 建议**最先合入**——它是唯一能证明后续改动真的闭环的生产证据通道，先有它，后面每一步才可验。

### 本节的证据边界

- 全部改动点为**静态读码定位**，未运行、未改任何文件、未跑测试。行号基于 HEAD `1e0e0298`，第一单落地后会漂移，实现时以符号名为准。
- 「`merger.py:167` 是证据门不是升格判据」这一区分基于该函数上下文阅读，**建议 Py-Eng 实现前再与 Design 确认一次** —— 若判断有误，条件乙的改动面会扩大到整条 PASS 写回链。
- `pending_confirm` 与 A2′ 幂等键的具体对齐形态，我只转述裁决、**未独立验证 A2′ 键的现有实现是否够用**。

---

## 缺口③：拓扑投影层 IPv6 地址族缺失（zhaiyq 532349/532519 救回路径）

- 来源：team-lead 小单（Test-Eng 移交），2026-07-20，只读。
- 起点：zhaiyq 批 532349 的 worker 声称「触发主机仅记录 IPv4 地址，无 IPv6 地址文档」，被 Test-Eng 以拓扑 JSON + rag md 证伪；但 `env_capabilities` 面又显示无 v6 能力。

### 对证结论：worker 措辞错，操作性结论对 —— 两边各对一半

worker 的 `needs_decision.json` 原文（`workspace/outputs/zhaiyq/unfinished/205271757988532349/needs_decision.json`）含两句，须拆开判：

| # | worker 原话 | 判定 |
|---|---|---|
| a | 「触发主机（routera/routerb）仅记录 IPv4 地址，**无 IPv6 地址文档**」 | **假**。Test-Eng 证伪成立：`network_topology.json` 中 routerA `3ffa::ac10:21ce/64`+`3ffa::ac10:22ce/64`、routerB `3ffa::ac10:20d2/64`+`3ffb::ac10:20d2/64`；rag md §四 有 IPv6 地址规划专章 |
| b | 「dig 触发配对表仅覆盖 IPv4 目标，**未记录 IPv6 目标的触发机配对**」 | **真**。见下方根因——配对表在派生层就是 IPv4-only |

→ **worker 把「投影里没有」误述成「文档里没有」**，措辞该纠；但它据以放弃的操作事实（拿不到可用的 v6 配对）是真的，**不是幻觉、不是检索偷懒**。

### ① `has_ipv6` 派生链：投影 bug，不是 stale、不是语义歧义

先澄清一个措辞：**代码与数据里都不存在 `has_ipv6` 这个字面** —— 全仓 grep 无命中，`env_capabilities.json` 内也无任何 ipv6 键。所谓「实测 has ipv6: False」是对**投影结果为空**的转述，不是一个真实字段。

真正的派生链在 `main/ist_core/tools/_shared/env_facts.py`，且**整条按地址族切断**：

| 行 | 事实 |
|---|---|
| `env_facts.py:46` | `self._subnets: list[ipaddress.IPv4Network]` —— 子网集**类型上就只有 v4** |
| `env_facts.py:50-58` | `_build()` 只对 `dev.get("ipv4", [])` 派生子网 |
| `env_facts.py:61-63` | v6 地址**只进 `_exact_ips` 精确白名单，显式不派生子网**（注释：「保持与历史 ssh.py 行为一致，不误拒 IPv6 设备」） |
| `env_facts.py:139-154` | `_types_per_subnet()` / `_lb_ips_with_subnet()` 均只遍历 `ipv4` |
| `env_facts.py:183-213` | **`listener_trigger_pairs()` —— 就是「dig 触发配对表」本体**，第 199 行 `for cidr in dev.get("ipv4", [])`，v6 结构性缺席 |

**判定：投影 bug（设计遗漏），非 stale、非语义歧义。** 拓扑 JSON（mtime 6/15）数据完整且含 v6 CIDR，是**投影层把它丢了**。也不是「无 v6 能力 ≠ 无 v6 编址」的歧义 —— 派生器压根没跑 v6，谈不上判过能力。

### ② worker 为什么没检索到 v6 章：注入面问题，不是检索面

配对表经 `env_facts.py:216-248 summary_for_agent()` 渲染，由 `precedent_tools.py:488-491` 附进 `compile_precedent` 返回文本**注入** worker。worker 看到的是：

```
=== 本测试床网络事实源(写 IP 只能用这里的真实可达值)===
★ 触发机配对(dig/curl 必须从与目标 listener 同段的触发机发起…)
    dig/curl 目标 <只有 IPv4> → 必须用 test_env 主机 …
```

这段以**权威闭集口吻**下发（"写 IP 只能用这里的真实可达值"），而内容是 v4-only。**worker 忠实读了投影，是投影骗了它** —— 它没有理由再去翻 rag md 找一张已被"权威事实源"否定的地址。

时间线（回答 lead 的 #58 前后问）：claim 写于 **07-18 18:48**，#58（`09373283`）提交于 **07-19 23:10** → **在 #58 之前**。但更重要的是：**#58 修的是 footprint 检索面**（版本子目录回退 + 载入完整性守卫），`git show --stat` 确认**未触及 `env_facts.py`**；本缺口在**派生/注入面**，因此**至今仍在 HEAD 上存活**，不是历史遗留。

### ③ 修法形状：不能纯数据零代码 —— 理由与规格

**结论：落 `env_facts.py`（代码），不落 `env_capabilities.json`、不落 `compile_ref`。约 4 处小改，零新增数据。**

为什么「自愈四层的纯数据零代码」标准在这里**不适用**：
- 该标准针对的是**判例/文法条目**——新坑=加一条 JSON 知识。而这里缺的不是一条知识，是**派生器的地址族覆盖**，属 A 层能力（机械投影），能力只能是代码。
- 若把配对结果**手抄**进 `env_capabilities.json`，等于把派生量固化成数据，直接违反既有契约「换测试床只改 `network_topology.json`」（`env_facts.py:122` 明写「换床改 JSON 即变，零硬编码」），换床即漂移、且与拓扑唯一事实源双源冲突。
- `env_capabilities.json` 的语义是「能力/已知缺陷」层（`build`/`capabilities`/`known_defects`），配对是拓扑派生量，放进去是层次错置。

规格：
1. `_subnets` 泛化为 `ip_network`（v4+v6 混装），`_build()` 同时遍历 `ipv4` 与 `ipv6` 键（`env_facts.py:46, 50-63`）。
2. `_types_per_subnet()` / `_lb_ips_with_subnet()` / `listener_trigger_pairs()` 的 `IPv4Address` 改 `ip_address`，遍历面同上（`:139-154, :183-213`）。地址族在 `ip_address in ip_network` 比较时天然隔离，**不会**把 v4 触发机错配到 v6 listener。
3. **`is_reachable()`（`:68-76`）保持不变** —— 它现有的「v6 走精确白名单」是为「不误拒 IPv6 设备」而设的保守行为，与配对派生是两件事；扩配对不必动可达性门语义，动了会扩大回归面。
4. `summary_for_agent()` 渲染面无需改结构，v6 配对会自然出现在同一张表里。建议**补一句地址族提示**（触发机与目标须同族同段），因为混列后 LLM 可能尝试跨族配对。
5. 数据侧**零改动** —— 拓扑 JSON 已完整，这正是「换床只改 JSON」契约成立的正面证据。

### 救回路径：探针该验的是 routerB → `3ffb::70`，**不是 routerA**

按拓扑 v6 CIDR 机械派生同段配对（复现即得，零推测）：

| v6 网段 | 段内设备（type） | 可用 v6 配对？ |
|---|---|---|
| `3ffa::/64` | clientC(客户端)、clientD(客户端)、routerA(路由器)、routerB(路由器) | ❌ **无任何 APV** —— 有触发机但没目标 |
| `3ffb::/64` | **routerB(路由器)**、**APV0**、**APV1** | ✅ **唯一可用配对** |
| `3ffc::/64` | APV0、APV1 | ❌ 无触发机 → v6 blind |
| `3ffd::/64` | APV0、APV1、server213/231/232(服务器) | ❌ 无触发机 → v6 blind |

由此三条结论：
1. **routerA 与任何 APV 无共享 v6 网段** —— 它只在接入层 `3ffa::`。所以「探针轮证实 routerA 能发 v6」**验了也没用**：routerA 能不能发 v6 与它够不够得着 APV 是两回事，够不着是拓扑事实，不是能力问题。**这条请务必转给 Test-Eng，避免探针轮白跑。**
2. worker 当时瞄的 `3ffc::70` **确实够不着**（该段无触发机）—— 它的放弃在那条路径上是对的。
3. **救回路径唯一**：listener/目标用 **`3ffb::70`（APV0）或 `3ffb::71`（APV1）**，触发机用 **`routerb`**（小写，`env_facts.py:205-208` 注明 F 列须小写否则 `getattr(env, F)` AttributeError）。探针轮该验的是这一对。

这与 `listener_trigger_pairs()` docstring 里记的 IPv4 老坑（「routerA 只在 .34 段、routerB 只在 .32 段，用 routerA dig .32.70 必 no servers could be reached」）是**同型异族** —— v4 那次踩过并写进了注释，v6 因为派生器没覆盖，同一个坑重新挖开了一遍。

### 证据边界

- 全部为静态盘面与源码推导：拓扑 JSON、rag md、`env_facts.py` 行级、worker `needs_decision.json` 原文、`git show --stat 09373283`、mtime 对比。**未上机、未探针验证 `3ffb::` 段实际连通性**。
- 「3ffb 配对可用」是**拓扑文档层**的结论；文档与设备实况是否一致须探针轮裁决（文档源等价可错原则）。若探针证伪 `3ffb::` 连通，则 532349/532519 才真正进「验证路径缺失」，届时是环境结论而非编译缺陷。
- 532519 我**只读了 532349 的机读账**，未逐条核对 532519 的 claim 文本，假定其同因（同批同类）—— 实现/救回前请 Test-Eng 确认。

---

# unit-2 规格终稿（乙收缩已确认 · 2026-07-20）

- 状态：**定稿，可开工**。依据 = Theory+Design 双专家裁决（R2 主轴 + 条件并集）+ Design 条件乙回执（2026-07-20）+ 本文档前述行级取证。
- 本节**取代**上文「终稿规格」中与之冲突的条款；上文保留作推导过程与证据留档，冲突处一律以本节为准。
- 行号基于 HEAD `1e0e0298`，第一单（S3→S1→S2-reduced）落地后会漂移，**实现以符号名为准**。

## 合入次序（不变）

```
T2 canary  ─→  P  ─→  甲  ─→  R  ─→  乙  ─→  T1
（最先）                        ↑
                    R 依赖第一单 S3 已合入
```

T2 最先的理由不变：本缺口正是靠 `upgraded_verified` 生产计数 0/826 才暴露，canary 是唯一能证明后续每一步真闭环的生产证据通道；先有它，后面每步才可验。Py-Eng 单线程，P 不再与第一单并行，按序执行。

## 六条终稿条款

### T2 · 生产计数 canary（最先合入）

- 落点：`engine_report.json` 生成处 + TUI/报告面。
- 读 `runtime/logs/k_signals.jsonl` 的 `upgraded_verified` 计数，长期为零即告警。
- 判据是**生产计数**，不是测试通过 —— Theory+Design 合议：「合成 fixture 只能证伪实现不满足自身假设」，绿测试不构成闭环证据。

### P · fact_key 派生单点化 + 通道纪律

- 新增 `memory/footprint/keys.py`（建议名），四条写回路统一经它派生：`uncertain.py:93-94`(A)、`uncertain.py:161-162`(B)、`compile_writeback.py:82`(C)、手写路（取消旁路，改经 `RawFact`+`merge_fact`）。
- A/B 两处现为逐字重复的 `f"{' '.join(head)}:{sha1(...)[:8]}"`，抽单函数即消除漂移。
- **section 归属保持 L_model 不收口**（Theory 明示）：派生函数只统一键，不裁决落哪个 section。
- 旁路禁令需机器守门 → 见 T1。**旁路已发生过**（`ssl.activate.certificate.json` 那条带 `validity`/`observed_under`，而 `merger.py:342-347` 从不写这两个键），不是假想风险。

### 甲 · `decision_rules` 补演化端（必做）

- 落点：`merger.py:338-349` `_append_decision_rule`。
- 两件事一起做：**扩字段**（支持写 `validity` / `observed_under` —— 现完全不写，正因如此旁路条目才是唯一带这两字段的来源）+ **补升格分支**（比照 `_append_behavior:357-375` 同形，含 `emit_signal("upgraded_verified", …, source="merger._append_decision_rule")`）。
- **通道纪律**：一切写入经 `merge_fact`，禁旁路直写节点 JSON。
- 终形态 = **R2 语义轴 + R1 通道纪律各取一半**（Design 措辞）。
- 依据：四 section 中 `decision_rules` 是**唯一无演化端**的（`cli.commands` 有 changed→append、`behaviors` 有升格分支、`known_issues` 有补字段 update）。此判断比「键不交」更深：即便键对齐，落这个 section 依然升不了。

### R · R2 本体：`pending_confirm` 显式化升格授权者

- 落点：`schema.py:17-45` 加字段；merger 各 `_append_*` 读它。
- `pending_confirm{autoid, expect}` —— 升格授权者 = **设备 oracle**，显式化。
- 升格按 **autoid** 索引，不再依赖 fact_key 对齐；索引轴复用 A2′ per-(fact, case, round) 幂等键。
- 三元锚 `(autoid, run_ts, build)` 按 DESIGN §5.1 前向形态挂。
- **依赖**：`build` 位取自第一单 S3 修好的链路。S3 未合入前上 R，三元锚**出生即失真**（普查 E2：1110/1110 条现存 build 全为 config 兜底常量）。

### 乙 · 升格判据禁「跑过就真」（**唯一强制对象 = R 新增路径**）

按 Design 回执①，比我初稿的收缩**更小**：

| 位置 | 裁决 | 理由 |
|---|---|---|
| `merger.py:167` | **不动** | device_verified 证据门，管「命令是否真上过机」，与升格判据是两件事。改了会让**所有** PASS 写回失效 |
| `uncertain.py:138` | **零改动** | `verdict=="pass"` 在此是**锚选择的必要条件**；且 B 路已有卷面机械因果锚（`behavior_candidates` 的 `observe_cmd` 卷面校验）→ **乙已满足** |
| **R 新增的 `decision_rules` autoid 索引升格路径** | **唯一强制对象** | 裸 `autoid`+`verdict` 无卷面绑定，正是「跑过就真」的裸露面 |

- 规格：该路径升格须命中与该 fact **因果相关的 mechanism signal**（信号源 `runtime/logs/k_signals.jsonl`，如 `fullwidth_comma_normalized`），`verdict==pass` 单独不足以升格。
- 理论依据：PASS 证结果、不证机制。

### T1 · 守门测试

- 落点：`tests/ist_core/memory/test_self_healing_loop.py`。
- **禁手构 `RawFact`** —— 必须从 `_writeback_one`（`nodes.py:1387`）或等价真实写回入口驱动。
- 用例须**跨 section**（uncertain 落 `decision_rules`、升格事实来自另一路）—— 这正是现有测试漏掉的形态，也是 0 计数长期未被发现的原因。
- 断言 `upgraded_verified` **必发射**。
- 另需一条**通道纪律**守门：断言不存在绕过 `merge_fact` 的节点写入路径（对应 P 的旁路禁令）。

## 与第一单的规格同步（Design 回执③④）

以下两条修正已回填进上文缺口② S1/S2 原位，此处汇总备查：

- **③ S1**：设备原文落 `RawFact.raw_invocation`（`schema.py:41-44`，第一单已实现），**不落 `evidence.quoted_text`** —— 后者是证据门的针，塞不命中手册的原文会让整条 fact 被 skip、静默关掉写回。仅当原文与剥净语法位不同时才写进 evidence。
- **④ S2**：挂接判据 = **剥净命令词 token 序列完全相等**（Design 条件⑴），不用前缀匹配（前缀会把 `ssl activate certificate` 与 `ssl activate` 类父子命令错挂）；`_behavior_feature_head` **只作节点寻址**，不参与挂接判定。

## unit-3 扫描面订正（已转 Py-Eng，收录备查）

迁移脚本目标 = **任意 section 下 `evidence.device_run.build` 的递归全集**，非 `cli.commands` 单域。实测分布：

```
cli.commands[].evidence.device_run.build → 1062
behaviors[].evidence.device_run.build    →   48
值分布：{568: 1110}   ← 单一兜底常量，零例外
```

我初版按 section 收窄漏检 48 条；按 section 白名单写脚本会重演同类漏检。`syntax_provenance` 标记虽只适用 cli 域，判据（有无 `source_file`）同样应递归判、不假设 section。

## 本终稿的证据边界

- 全部条款为**静态读码 + 机读账取证**，未运行、未改任何代码、未跑测试。
- 条件乙的最终收缩形态**采自 Design 回执**，我未独立验证「B 路 `observe_cmd` 卷面校验已构成因果锚」这一判断 —— 该判断是 Design 作出的，若有误，乙的强制面需重开。
- `pending_confirm` 与 A2′ 幂等键的承载力对齐，Theory 已纳入其 review 范围，我未独立验证。

---

# R2 规格 v2（Theory 两单 + Design findings 全量约束 · 2026-07-20）

- 本节**取代** unit-2 终稿中 R 与乙的条款细节；unit-2 终稿的其余五条（T2/P/甲/T1/次序理由）继续有效。
- 新增内容 = 序锁定 + R2 本体九条硬约束 + 两项核验单结论 + 一个裁决点。

## 序锁定（Theory 定理：S3 是 build 锚前置、迁移是 R2 前置）

```
S3(已落) → unit-2a[T2 canary + P 键派生单点化 + P1-6 静默吞计数信号]
         → unit-3[存量迁移，递归扫描面]
         → unit-2b[R2 本体]
```

原 unit-2 终稿的「T2→P→甲→R→乙→T1」序被此覆盖：甲/乙/T1 归入 unit-2b 与 R2 本体同批，迁移插在 R2 之前。

## 核验单 ⓐ：extra_candidates 通道有无卷面命令门

**结论：Theory 的 ⚠ 成立 —— 该通道确实不过卷面门；但它的 `observe_cmd` 是机械派生而非 LLM 断言，强度不低。真正的裸露面在别处（见下）。**

两条通道的门，行级核实：

| 通道 | 门 | 位置 | 性质 |
|---|---|---|---|
| B 路 `submit_behavior_fact` | `observe_cmd` 必在该 case 卷面 APV 命令里（读 `case.xlsx`） | `behavior_tool.py:66` 报错分支 | **校验**（LLM 断言 → 机器核） |
| `submit_attribution` | `evidence` 必须是该 case 落盘原文的 **verbatim 子串** | `fail_attribution.py:323` 报错分支 | **校验**（绑 device_context） |
| **extra_candidates** | **无 behavior_tool 门** —— 绕开 `submit_behavior_fact`，在 `nodes.py:2651 _attribution_observations` 直接造候选 dict | — | **派生**：`observe_cmd` 由 `_load_case_rows(aid)` 从卷面机械读出（最后一个 `check_point` 之前最近的非 config 观测步 G 列末行，`nodes.py:2667-2678`），**无锚即 no-op 返回 `[]`** |

- 派生 > 校验：该通道的 cmd 不经 LLM 之口，比"LLM 说了再核"更强。`merger.py:~190` 注释称锚定「由 behavior_tool 入口卷面校验保证」，**对 extra 通道是失准的**（该通道根本不过那道门），但结论侥幸成立——换了个更强的机制。**建议顺手订正该注释**，否则下一个读者会以为所有 uncertain 都过了 behavior_tool 门。
- **真正的裸露面（新发现，请转 Theory/Design）**：cmd 与 content 各自有绑（cmd 绑卷面、content 绑 device_context 子串门），但**「这条 content 是这条 cmd 的观察」这一配对关系无任何机械校验** —— 配对来自 `_attribution_observations` 的启发式（取最后一个 check_point 前最近观测步）。多观测步 / 多 check_point 的 case 上，锚可能配错。
- **对乙的影响**：Design 判「B 路已有卷面机械因果锚 ⇒ 乙已满足」对 `submit_behavior_fact` 通道成立；但**若 R2 的 `decision_rules` 升格路径复用 extra_candidates 作因果锚，乙的强制要求会落空**（配对无门）。规格 v2 据此要求：R2 升格的 mechanism signal 锚**不得**取自 extra_candidates 派生的配对，须取自 `k_signals.jsonl` 的独立信号。

## 核验单 ⓑ：A2′ 表示不一致 —— 定谳与二选一提案

**定谳：Theory 实测正确，实现是 per-fact 全局，条款措辞与实现不符。**

行级证据：`uncertain.py:93-94` 与 `uncertain.py:161-162` 两处产键完全相同：

```python
key = f"{' '.join(head)}:{hashlib.sha1(_normalize_observation(content).encode()).hexdigest()[:8]}"
```

键成分 = `feature_head` + `归一化内容 hash`，**不含 `autoid`、不含 `round`**。`seen_keys`（`uncertain.py:82,95-97`）只是**单案循环内**的去重，不进键；merger 侧 `_append_behavior:356` 也仅按 `fact_key` 匹配 → 全局 per-fact。

**二选一提案（标为用户/专家裁决点，我不代决）**：

| 提案 | 做法 | 代价 / 风险 |
|---|---|---|
| **A：R2 实现真三元组** | 键改为 `head + content_hash + autoid + round` | ①判例层膨胀 —— 同一观察跨案跨轮各成一条，正是约束 ⑧（C5 计数器观察每轮新键）担心的形态；②**破坏现有自愈渲染** —— `footprint_lookup` 的「同节点多语境观察自动组头」靠同 `fact_key` 的多语境计数触发，键里塞 autoid 后每条都成孤儿，观察组永不成组 |
| **B：修条款措辞（我倾向）** | 承认实现为 per-fact 全局，条款改述为「per-fact 幂等 + (case, round) 作为语境标注（`observed_under`）而非键成分」 | R2 的 pending 索引不能直接复用该键 —— 但这正是约束 ②（C2 pending 列表化）已经要解决的问题，两者相容 |

倾向 B 的理由：键承担「观察身份」，pending 承担「授权」，两者本就该解耦；A 把授权轴塞进身份轴，会连带毁掉聚合语义。

## R2 本体九条硬约束（逐条进规格）

| # | 约束 | 落地要点 |
|---|---|---|
| ① | **P0-2 升格现场查台账，禁信 `validity` 字段** | 授权凭据 ≠ 授权事实。升格判定时现场读 `verified_runs.jsonl` / `k_signals.jsonl`，不以条目上已写的 `validity` 作输入 |
| ② | **C2 pending 必须列表化**（每案一条）或索引与条目解耦 | 现 merger 同 `fact_key` 命中即 `skip` —— 同内容跨案撞键时 B 案的 pending **永不落库**。pending 存为列表 `[{autoid, expect, build}, …]`，或整体移出条目单独索引 |
| ③ | **C1 升格后清 pending + 防重复** | 清除已兑现的 pending；同一 autoid 多次 PASS 不得重复升格、不得重复累加 `verified_count`（`_update_meta:249-256`） |
| ④ | **P1-7 pending 带 build 锚** | 依赖 S3 —— S3 前写入的 build 位是 config 兜底常量（普查 E2：1110/1110），锚下去即失真。**这是序锁定「S3 是 build 锚前置」的直接落点** |
| ⑤ | **C4 sha1 截断 `[:8]` → `[:16]`** | 键将承担授权语义，碰撞后果从「两条观察合并」升级为「A 案的 PASS 升格了 B 案的知识」。改动点：`uncertain.py:94` 与 `uncertain.py:162` 两处（P 收口后为单处） |
| ⑥ | **P1-4 别按 cli `fact_key` 索引** | 该字段是死字段——写入后从不被读；按它建索引=建在空气上 |
| ⑦ | **P1-8/C3 `observed_under` 覆盖语义** | 现 `_append_behavior:367-368` 升格时**整体覆盖** `observed_under`，丢失原语境。改为**追加**（多语境并列），与渲染层观察组语义一致 |
| ⑧ | **C5 pending 膨胀去重轴** | 计数器类观察每轮产新键 → pending 无界增长。**建议去重轴 = `(autoid, head)` 级**：同案同节点只保留最新一条 pending（语境合并进 `observed_under`）。理由：授权的粒度是「这个案在这个知识点上待确认」，不是「每个内容变体各要一次确认」 |
| ⑨ | **P2-9 剥离使 `startswith(body)` 门变松，与 S1 合并评估** | `merger.py:169-170`：`body = re.split(r"[<\[{]", cmd)[0]`，判 `c == cmd or c.startswith(body)`。S1 剥掉 kwarg 后 `cmd` 变短 → `body` 变短 → 卷面上更多命令能 `startswith` 命中，门**实际放松**。**规格：S1 落地时同步把该门改为「两侧同规则剥净后精确相等」**（卷面侧命令也过同一 kwarg 剥离），而不是继续用前缀兜底——否则 S1 修了签名保真、却顺手削弱了 device_verified 门 |

## 证据边界

- ⓐ / ⓑ 两项均为**行级源码核实**（`behavior_tool.py:66`、`fail_attribution.py:323`、`nodes.py:2651-2691`、`uncertain.py:93-97/161-162`、`merger.py:139-200/356-375`）。未运行、未改代码、未跑测试。
- ⓐ 中「多观测步 case 上锚可能配错」是**从代码逻辑推出的风险**，我**未在真实批次上找到配错实例** —— 若要定量，需扫历史 `behavior_candidates` 与卷面比对，属另一单。
- 九条约束的**必要性判断采自 Theory/Design**，我只做落地要点与冲突检查；其中 ⑨ 的「门变松」是我独立复核确认的（`merger.py:169-170` 行为推导）。
- 提案 A 的第二项代价（破坏观察组渲染）基于 `footprint_lookup` 的组头触发是「同 fact_key 多语境计数」这一理解 —— 该理解来自 CLAUDE.md 与 merger 注释，**未逐行核对 `footprint_lookup` 实现**。

---

# unit-3 迁移单（三项）+ P1-C 修法规格（2026-07-20）

依据：team-lead 转达的 Theory 正式 diff 评审采纳结论（三修全治新增、零治存量 = 缺口①三轴复刻）。

## unit-3 迁移单：三项

四条纪律不变，适用于全部三项：**禁改任何既有值（只追加字段）/ dry-run 先出 diff 给 leader 过目 / 原子写 tmp+replace / 幂等可复跑**。扫描面为**递归全集，不按 section 白名单**。

### (a) 存量污染 cli 条目（实参 / kwarg 型）

- 目标：普查 B 类 1264 条真实参条目 + A 类 1 条 kwarg 条目（`ssl.activate.json` 的 `ssl activate certificate vh1,prompt=YES`）。
- 处置：追加 `syntax_provenance: "device_run_verbatim"`（判据：`evidence` 无 `source_file`，递归判、不假设 section）。
- **kwarg 那条单独处理**：按评审 P1-F，它 `evidence` 无 `source_file` 故**不作证据门的靶**，但**仍会被 worker 读到**（渲染层不区分）→ 必须标记或清理，不能因「不作靶」就放过。建议：剥净 kwarg 后若能与 `ssl.activate.certificate` 的手册签名挂接（S2 判据：剥净命令词 token 序列全等）则挂接并删除该条；否则打标记保留。

### (b) 1110 条存量 build 锚补 `build_source: "legacy_unknown"`

- **这条是评审 P1-E 逼出来的，必须做**：若渲染层按 `== "config_fallback"` 判不可信，存量条目**因字段缺失会被当旧格式放行** —— 修了新增、存量反而静默逃逸，正是「三修全治新增零治存量」要复刻的错。
- **三值域写进规格**：

| 值 | 含义 | 何时写 |
|---|---|---|
| `probe` | 探针实测值，版本作用域可信 | S3 后的正常路径 |
| `config_fallback` | 探针缺失、走了 config 兜底 | S3 后的兜底路径 |
| `legacy_unknown` | S3 之前写入，真值不可回溯 | **本次迁移追加到全部 1110 条存量** |

- 渲染层与 worker 侧判据须是**白名单式**（只有 `probe` 当可信），不是黑名单式（`!= "config_fallback"` 当可信）—— 后者正是 P1-E 的漏法。
- 重申：**禁止回填真值**。`verified_runs.jsonl` 本身也全是兜底值，历史设备实际 build 不可考；按当前 585 批量回填是造值。

### (c) 5 处旁路 `decision_rules` 归位

- 处置：经 `merge_fact` 重写入（对应 P 的通道纪律），使其落进机器可对齐的键空间与规范键形。

- ⚠ **计数对不上，需与 Theory 互对证据面（我不采用任一数字，先对齐判据）**。我按两条独立判据扫全库 1458 条 `decision_rules`：

| 判据 | 命中 |
|---|---|
| **键形非 merger 规范形**（merger `:342-347` 只写 `{fact_key, condition, decision, evidence}`，多/少键即旁路） | **3** |
| `evidence` 缺 `source_file` | **0** |

键形分布：`1455 × {condition, decision, evidence, fact_key}`（规范形）+ `2 × …+{observed_under, validity}` + `1 × …+{observed_under}` = 1458，闭合无余。命中的 3 条：

```
ssl.host.json                 ssl_host_config_write_needs_case_tail_teardown  (+validity +observed_under)
ssl.activate.certificate.json importcert_auto_activates_no_manual_reactivate  (+validity +observed_under)
sdns.host.pool.json           sdns_host_pool_cname_pool_binding_semantics     (+observed_under)
```

### 3 vs 5 冲突：已结案（team-lead 盘面裁定，2026-07-20）

**两侧都对，单位不同** —— Theory 的 5 是**字段命中「处」**（3 × `observed_under` + 2 × `validity`），我的 3 是**条目「条」**（2 条双字段 + 1 条单字段）。分布闭合完全吻合：3 条 = 2×(validity+observed_under) + 1×(observed_under) → 字段处数 = 2+2+1 = 5。把「处」写成「条」是转发环节的措辞错，leader 已认领。

**选取器定稿：键形非规范的 3 条**，清单即上表三条（`ssl.host` / `sdns.host.pool` / `ssl.activate.certificate`）。

**盲区注记保留（不阻塞迁移）**：键形规范但内容为手写的旁路，**形态上与 merger 产物无法区分**，本判据无检出能力。git 历史溯源列为**可选深审**，不阻塞本次迁移。

## P1-C 修法规格：kwarg 判据两处不等价

- **裁定记录（team-lead 转 Theory 评审）**：`structural_gate.py:1142` `_KWARG_SEG_RE = re.compile(r"^\s*(timeout|prompt)\s*=")` 是**硬白名单**；writeback 侧走机械判据（引号外逗号切段 + `key=` 形态）。两处不等价，**writeback 对、structural_gate 偏离** —— 白名单正是 prompt 红线所禁（键集随框架版本增长，抄进代码必漂移）。
- **窗口：下窗口做**（动 emit 门行为，须 Design 评审 + 测试），本窗口只记录规格。

规格：

1. **抽共用判据函数**，两处同源调用。判据 = mirror `get_parameter` 语义的机械复刻：引号外逗号切段（`structural_gate.py:1141 _PARAM_SPLIT_RE` 已是「原样复刻 `test_xlsx.py:57`」，**直接复用它，勿另写**）+ 尾段形如 `^[A-Za-z_][A-Za-z0-9_]*\s*=` 判为 kwarg。
2. **白名单降为告警**：`(timeout|prompt)` 不再参与**判定**，改为「出现名单外 kwarg 时记信号 + 提示」。这样新增 kwarg 既不被误报为 stray 位置参数（现行为：`structural_gate.py:1166` 把它算进 `stray` → 误报 `comma_splits_parameters` 拦下合法命令），也不静默放行。
3. **与 ⑨ 合并评估**：S1 落地时 `merger.py:169-170` 的 `startswith(body)` 要改成「两侧同规则剥净后精确相等」，剥离用的正是本函数 —— 三处（structural_gate / writeback / merger 证据门）**共用同一判据函数**，是这次收口的完整边界。
4. 回归：现有 `_check_parameter_splitting` 的用例须补一条「名单外 kwarg 不误报」与一条「真 stray 位置参数仍报」的对照。
5. **纪律（leader 定稿）：先写失败用例再改。** 「白名单会误报名单外合法 kwarg」目前是从 `structural_gate.py:1166` `stray` 计算逻辑**推出**的，未实测 —— 实现时**先构造该失败用例、看它真的红**，再动判据。推论未经实测就改门，正是本文档反复在治的错误形态。

## P1-A 处置记录（降 P1，下窗口）

- `raw_invocation` 无门写入 —— leader 核实渲染层不展示（只带 verbatim tag），故降 P1。
- guard 规格入下窗口清单：**存前过 PASS 台账 `apv_cmds` 佐证**（与 `merger.py:_device_evidence_supports` 同源的卷面校验），避免该字段成为无门旁路的新入口。

## 证据边界

- (c) 的两条判据扫描为本次实跑（全库 1458 条 `decision_rules`，键形分布闭合）。**未做 git 历史溯源**，故对「键形规范但内容手写」的旁路无检出能力 —— 这正是我与 Theory 计数差异的最可能落点。
- P1-C 的「白名单会误报名单外合法 kwarg」是从 `structural_gate.py:1166` `stray` 计算逻辑**推出**的，**未构造用例实测**；下窗口实现时应先写这条失败用例再改。
- P1-E 三值域、P1-F、P1-A 的必要性判断采自 Theory 评审与 leader 核实，我只做落地要点与冲突检查。

---

# unit-3 验收标准：population 全覆盖表（2026-07-20）

依据：Theory 独立普查校正 + team-lead 裁定。目的 = **防「改完 1 条就宣告完成」**，范围必须显式枚举、逐条对账。

## 合入窗口与放行裁定（记录）

- **944 条非本 diff 回归** —— 它们是 V6 支柱2a 设计内通道（PASS 写回）的正常产物，**B-1 照常放行**。
- 迁移**严格排在 B-1 收批后的下一合入窗口**：批中 worker 正在读节点 JSON，并发改库有风险。**仍在 R2 之前**，序不变。

## 全覆盖表

| # | population | 数量 | 判据（选取器） | 处置 | 语义判断？ |
|---|---|---|---|---|---|
| 1 | S1 kwarg 条目 | **1** | 命令含引号外 `key=` 段 | 挂接手册签名后删条，挂不上则打标记 | 需（挂接判定） |
| 2 | S2 实参条目（device_run 锚） | **944** | 无 `source_file` ∧ 有 `device_run` ∧ 无占位符 | 补 `syntax_provenance: "device_run_verbatim"` | 否，纯机械 |
| 3 | build 假值 | **1110** | 递归全集 `evidence.device_run.build` | 补 `build_source: "legacy_unknown"` | 否，纯机械 |
| 4 | 旁路 `decision_rules` | **3 条**（＝5 处字段，单位不同，已结案） | 键形非 merger 规范形；清单：`ssl.host` / `sdns.host.pool` / `ssl.activate.certificate` | 经 `merge_fact` 重写入 | 需 |
| **5** | **零出处实参条目（新增，我本次扫出）** | **404** | 无 `source_file` ∧ **无 `device_run`** ∧ 无占位符 | **提案乙已采纳**：标最弱档（档名待 Design 定） | 否，纯机械 |

2 与 3 合计 2054 条为**纯机械补标、零语义判断**，一次脚本遍历完成（幂等 + dry-run）。

## ⚠ 新增 population 5：404 条「零出处」实参条目

全库 5055 条 cli 条目的完整分层（本次实跑，闭合无余）：

```
2611  手册 + 无device_run + 占位符      ← 正常手册签名
 978  手册 + 无device_run + 无占位符    ← 无参命令(show ssl host 等)，正常
 944  无手册 + device_run + 无占位符    ← Theory 的 S2 population
 404  无手册 + 无device_run + 无占位符  ← ★ 零出处：既无手册也无设备锚
 118  手册 + device_run + 无占位符      ← 挂接成功形态，正常
────
5055
```

- **问题**：Theory 的 944 口径按「有 `device_run`」选取，**这 404 条落在口径之外**。它们既无手册出处、也无设备锚，是**出处最弱的一档**；若只标 944，这 404 条在渲染层将**继续与手册签名无从区分**，worker 照读照信 —— 正是本验收表要防的「看着覆盖了、其实漏了一档」。
- 样例（集中在 SDNS，与「压倒性在 SDNS」的观察一致）：
  ```
  sdns.host.json | sdns host name autotest1.com
  sdns.host.json | sdns host lastresort pool autotest1.com p1
  sdns.host.json | sdns host pool autotest.com p3
  ```
- **两个提案（请 Theory/leader 裁决，我不代决）**：
  - **提案甲（扩口径）**：S2 选取器改为「无 `source_file` ∧ 无占位符」→ population = **1348**（944 + 404），一律补 `syntax_provenance: "device_run_verbatim"`。风险：这 404 条**无 device_run 佐证**，标成 `device_run_verbatim` 是**给了它们没有的凭据**。
  - **提案乙（分档标，我倾向）**：944 标 `device_run_verbatim`；404 另标 `syntax_provenance: "unverified_legacy"`（无任何出处，最弱档）。渲染层/worker 按档位读，白名单式只信手册签名与 `device_run_verbatim`。
  - 倾向乙的理由与 (b) 的三值域同构：**缺位要诚实缺位，不能借标记给出未经验证的凭据** —— 提案甲会把「没有锚」洗成「有设备锚」，与 build 那条「禁回填真值」是同一条红线。

## 验收对账要求

脚本 dry-run 输出须逐 population 报「计划改动数 / 实际改动数 / 跳过数 + 跳过原因」，五个 population 全部列出（包括本次裁决为「不处置」的，也要显式列出并写明理由）。**任何一档缺失即验收不通过** —— 沉默的零不等于覆盖的零。

## 证据边界

- 五分层数据为本次实跑全库 5055 条 cli 条目，分层互斥且闭合（合计 5055）。未上机、未改文件。
- population 4 的计数冲突**已结案**（单位混淆：3 条 = 5 处字段，两侧闭合吻合）；选取器按 3 条定稿，盲区注记保留、git 溯源为可选深审。
- 提案乙的档位名 `unverified_legacy` 是我拟的，若与既有字段语义冲突请 Design 改名；档位**数量**（三档：手册 / device_run_verbatim / 无出处）是实质，名称非实质。

---

# R2 规格 v2.1 修订（Theory 自纠 + pending 改形 · 2026-07-20）

本节修订 v2 的三处，其余条款不变。

## 修订 ①：撤回「A2′ 未兑现」依据

- 前文核验单 ⓑ 的「A2′ 表示不一致」**依据撤回**，改标 **Theory 自纠撤回**（Theory 自曝上单误判，leader 已验条款原文 `THEORY:714-716` 成立）。
- 更正后的事实：**per-fact 全局幂等强于 per-(fact, case, round)**，条款**未被违反**。我在 ⓑ 中所述的「实现是 per-fact 全局」的**盘面事实仍然成立**（`uncertain.py:93-94 / :161-162` 键不含 autoid/round），只是它**不构成违规** —— 是我与 Theory 当时都把「更强」误读成了「不一致」。

## 修订 ②：方案 A 从「代价大」升级为「被条款明文禁止」

- v2 中我把方案 A（键塞 autoid/round）列为「代价大、破坏观察组渲染」，属**直觉性反对**。
- 现有条款原文依据：`THEORY:715-716` 警告的正是**用细粒度键伪造多语境** —— `autoid` 是**跨案易变 token**，塞进身份键即制造「同一知识在每案各算一条观察」的假多语境。
- **故方案 A 不再是权衡选项，而是条款禁止项。** 原「二选一裁决点」随之消解（见修订 ③）。
- 记录：我在 v2 中基于「观察组靠同 fact_key 多语境计数触发」给出的反对直觉，现有条款原文背书。当时我标注了「未逐行核对 `footprint_lookup` 实现」—— 本次已核（见下），直觉与实现、条款三方一致。

## 修订 ③：R2 pending 机制改形 —— 不动键，改合并语义

**键零改动**。`_append_behavior`（`merger.py:~416-450`）的 `skip` 分支改为**合并非身份字段**：

| 字段 | 旧行为 | 新行为 |
|---|---|---|
| 身份字段（`fact_key` / `content` 主体） | 取既有 | **不变**，仍取既有 |
| `observed_under` | 升格时**整体覆盖**（`merger.py:428-429`） | **累积**（语境列表） |
| `pending_confirm` | —（新增字段） | **列表 append**，每案一条 |
| `evidence` | 覆盖 | **累积** |

**一改动解两约束**：
- **C2**（同内容跨案撞键 → 第二案 pending 永不落库）：pending 列表化后，`skip` 分支不再丢弃 B 案的 pending。
- **P1-8 / C3**（升格覆盖 `observed_under` 丢原语境）：改累积即解。

原 v2 的「裁决点」降级为**一条合并语义补款候选**（措辞由 Theory 出、用户批），不再是二选一。

## ⚠ 连带影响：`observed_under` 单值 → 累积 是**破坏性数据形态变更**

Design 正做设计面核对；我这边把**读取面**核清了，规格如下。

### 现状：6 个读点，全部假设它是字符串

| 文件:行 | 读法 | 变列表后的后果 |
|---|---|---|
| `merger.py:490` | `(e.get("observed_under") or "").strip()` | **`AttributeError`** —— list 无 `.strip()`；`_distinct_observation_contexts` 崩，**入库端迁移判定直接挂** |
| `footprint_lookup.py:172` | `.strip()` 过滤 | **`AttributeError`**，观察组渲染崩 |
| `footprint_lookup.py:174` | `{… .strip() …}` 集合 | 同上 |
| `footprint_lookup.py:155` | `ou = e.get(…, "")` 后字符串操作 | 渲染错乱 |
| `footprint_lookup.py:193` | 同上 | 渲染错乱 |
| `index.py:63-65` | `ou[:60]` 切片 | list 切片得子列表 → 推式 reminder 渲染成 `语境:[...]` 垃圾 |

**这不是装饰性破损** —— 前两处会抛异常，属硬失败。

### 规格：单点归一化 + 全读点改造

1. **加归一化 helper**（建议 `memory/footprint/schema.py` 或 merger 同层）：
   ```
   def observed_contexts(entry: dict) -> list[str]
   ```
   兼容三形态：缺失 → `[]`；字符串（旧条目）→ `[s]`；列表（新条目）→ 去空去重保序。
2. **上表 6 个读点全部改走 helper**，禁止任何读点再直接 `.strip()` / 切片 `observed_under`。**这是本修订的验收点**：漏改一处即运行时崩。
3. **写入端**：`merger.py:428-429`（升格覆盖）与 `:447-448`（新建）改为累积语义；写入后**统一存列表**，不再写字符串。
4. **旧单值条目零迁移**：helper 兜住读取，存量 1458+1629 条带 `observed_under` 的旧条目**不必改写**（与 unit-3「禁改值只追加」纪律一致）。新写入才用列表形态。

### ⚠ 语义连带（请 Design 明确裁定）

观察组触发是**纯计数**：`footprint_lookup.py:170-174` 取「互异语境 ≥2」成组。

- 旧形态：一个条目**只能贡献 1 个语境**，故「≥2 互异语境」必然意味着**≥2 个条目**（真·多观察）。
- 新形态：**单个条目累积 2 个语境后，自己就能触发组头**。
- 我判断**这正是想要的**（同一知识在不同案下被观察到，恰是组头该提示的「行为可能条件相关」），但它**改变了触发条件的语义**，不是无损重构 —— 须 Design 显式裁定，别让它作为副作用悄悄生效。

## 证据边界

- 6 个读点为本次**行级核实**（`merger.py:490`、`footprint_lookup.py:155/172/174/193`、`index.py:63-65`）。v2 中标注的「未逐行核对 `footprint_lookup`」缺位**已补上**。
- 「两处 `.strip()` 会抛 `AttributeError`」是**从代码形态推出**的（list 无 `.strip`），**未构造用例实测** —— 按 P1-C 同款纪律，实现时先写该失败用例。
- 修订 ①② 的条款原文（`THEORY:714-716`）我**未直接阅读**，依据为 leader 转述与验证；条款措辞以 Theory 出稿为准。

---

# 三项裁决落定 + 一处自纠（v2.1 增补 · 2026-07-20）

## 裁决 ①：第五 population（404 条零出处）—— 提案乙采纳

- **三档实质定**：手册签名 / `device_run_verbatim` / 最弱档。
- **档名由 Design 按 §24⑶ 词汇定**（会签中）—— 我在 v2 里暂拟的 `unverified_legacy` **作废，勿沿用**；档位数量（三档）是实质，名称以 Design 出稿为准。
- 渲染层与 worker 侧**白名单式只信前两档**，照 v2 规格写。
- 裁决理由即我提出的理由：提案甲会把「没有锚」洗成「有设备锚」，与 build 那条「禁回填真值」是同一条红线。
- 全覆盖表 population 5 行已同步更新（处置＝标最弱档，语义判断＝否/纯机械）。

## 裁决 ②：population 4 冲突了结

leader 盘面复扫 = **条目 3 条 / 字段命中 5 处**，与我的扫描结果一致；两侧单位不同、都对。选取器按 **3 条清单**（`ssl.host` / `sdns.host.pool` / `ssl.activate.certificate`）。表内标注已改为「已结案」。

## 裁决 ③：配对置信 —— 裁强档（Design 会签带出）

对应我在核验单 ⓐ 中发现的裸露面（cmd 绑卷面、content 绑 device_context，但**二者的配对关系无机械校验**，来自 `_attribution_observations` 的启发式取锚）：

1. **extra_candidates 派生条目打 `pairing: "heuristic"` 标记**，检索/渲染可见。
2. **该类条目不参与 R2 自动升格。** 理由（Design）：升格是**发凭据的时刻**，把可能配错的内容升为 `verified` 违反「不知道别装知道」。
3. **排除仅限自动路** —— 后续经**显式确认**仍可升格。

这比我在 v2 里写的（「R2 升格的 mechanism signal 不得取自 extra_candidates 派生配对」）更强：我只禁了它当**信号源**，裁决直接禁它当**升格对象**。以裁决为准。

## 自纠：我的组头证据被 Design 证伪

**Design 是对的，我错了。** 我在 v2 反对方案 A 时称「观察组靠**同 `fact_key`** 多语境计数触发」—— 本次自核 `footprint_lookup.py:170-175` 原文：

```python
obs_entries = [e for e in (rules + behaviors)
               if (e.get("observed_under") or "").strip()
               and e.get("fact_key") not in in_conflict]
obs_ctxs = {(e.get("observed_under") or "").strip() for e in obs_entries}
obs_group = obs_entries if len(obs_ctxs) >= 2 else []
```

- 组头触发键 = **节点内互异 `observed_under` 的计数**，跨 `rules + behaviors` 汇总；
- `fact_key` 在此**只作冲突横幅的排除过滤器**，**不参与分组**。

**故「键里塞 autoid 会让观察组永不成组」这一推论不成立** —— 分组根本不看 `fact_key`。方案 A 的否决依据已由 Design 换成：**条款明文禁止（`THEORY:715-716` 细键伪造多语境）+ `conflicts_with` 破坏 + 字段语义单一性**，结论不变、依据换新。

**过程记录**：我当时在 v2 的证据边界里明确标注了「未逐行核对 `footprint_lookup` 实现」——**该诚实边界起了作用**，让 Design 知道这条该复核而非直接采信。教训：直觉与结论碰巧对，不等于给出的依据对；给依据时若未核实，必须标，且**不应让未核依据承重**（我在 v2 里让它承担了方案 A 的主要否决理由，这一步是过头的）。

**v2.1 不受影响**：v2.1 的「语义连带」一节用的是**已核实的正确机制**（互异语境 ≥2 成组），结论仍成立 —— 单个条目累积 2 个语境后，其贡献进 `obs_ctxs` 的互异值变 2，自己即可触发组头。该处仍待 Design 显式裁定。

## 证据边界

- 组头机制为本次**行级自核**（`footprint_lookup.py:170-175` 原文引用如上），推翻我此前的表述。
- 裁决 ①③ 的理由采自 leader 转达的 Design 会签，我未参与会签、未读其原始 findings。
- §24⑶ 词汇表我**未读**，故不对档名做任何预设。

---

# R2 规格 v2.2 收束（v2.1 × Design 会签合并终形 · 2026-07-20）

B 终形定稿。本节收束前述全部条款，**以本节为最终实现依据**。

## ① 消费点：全仓权威清单（并集，本次实跑 grep）

我的 6 点 + Design 补的 2 点 + `merger` 写入点，去重后**全仓 9 个生产读写点 + 6 个测试断言点**：

| 文件:行 | 读法 | 变列表后的后果 | 分级 |
|---|---|---|---|
| `merger.py:496`（`_distinct_observation_contexts`） | `.strip()` | `AttributeError` | **硬崩** |
| `footprint_lookup.py:172` | `.strip()` 过滤 | `AttributeError` | **硬崩** |
| `footprint_lookup.py:174` | `{… .strip() …}` | `AttributeError` | **硬崩** |
| **`grade_extract_script.py:136`** | `.strip()`，**但整段包在 `try/except Exception`（`:142`）里** | 异常被吞 → **观察行整段静默消失** | ★ **静默吞（最危险）** |
| `index.py:63-65` | `ou[:60]` | 渲染 `语境:[...]` 垃圾 | 渲染错乱 |
| **`store.py:396`** | `ou[:60]` | 同上（推式通道） | 渲染错乱 |
| `footprint_lookup.py:155` | 字符串操作 | 渲染错乱 | 渲染错乱 |
| `footprint_lookup.py:193` | 字符串操作 | 渲染错乱 | 渲染错乱 |
| `merger.py:424 / :434-435 / :453-454` | 写入端（覆盖语义） | 改累积 | 写入改造 |

**两处修正 v2.1 的说法**：
1. **硬崩是 3 处不是 2 处**（v2.1 只点了 `merger` + `footprint_lookup` 一处，实为 `merger:496` + `footprint_lookup:172` + `:174`）。
2. **`grade_extract_script.py:136` 不会崩，会静默吞** —— 它的 `.strip()` 在 `try/except Exception`（`:142`）内，AttributeError 被捕获，结果是**观察行整段从 grade 提取里消失、无任何报错**。这比崩更危险：崩会被发现，静默吞不会。**与 P1-6「静默吞计数信号」是同一族病，请一并纳入 unit-2a 的静默吞治理面。**

Design 的判断成立且关键：**这两点都在 `footprint` 包外**（`memory/store.py`、`tools/device/`），正是只扫包内会漏的位置。

**规格写死**：
- 实现时**重新 grep 全仓** `observed_under`（含 `tests/`），**漏一处 = 运行时崩或静默失真**；本表是 HEAD 时点快照，不是许可清单。
- **行号已在漂移**（本次 grep 相对我上一轮读，`merger` 的 418→424、490→496 等整体位移 6 行，文件被改过）→ **一律以符号名定位，不认行号**。
- helper `observed_contexts(entry) -> list[str]` **单点归一**（缺失→`[]`、字符串→`[s]`、列表→去空去重保序）；**禁任何读点直接 `.strip()` 或切片 `observed_under`**。
- **先写失败用例再改**（P1-C 同款纪律）：上表 4 处异常/吞没后果均为**代码形态推导、未实测**，实现时先构造用例看它真的红/真的空。
- **测试端 6 个断言点同步**：`test_self_healing_loop.py:107/159/211/322`、`test_ssl_enablement.py:153/184` 现均按字符串断言，改列表形态后需同步（`:159` 的 `entry["observed_under"] == "钉死的分辨条件"` 正是「覆盖语义」的固化断言，**它会与累积语义直接冲突，必须改**）。

## ② 返回契约四态（Design）

- `MergeResult.action` 增 **`"merged"`**（语境累积，区别于 `append` / `update` / `skip`）。
- **调用点显式排除**：`uncertain.py:106` 与 `uncertain.py:168` 两处现按 `!= "skip"` 计数 → 必须显式排除 `merged`，**不计入 `promoted` / `ingested`**。
- **新信号 `observation_context_merged` 入 SIGNALS 闭集**（AST 门会强制）。
- 目的：**「新入库」与「语境累积」分计数** —— 否则 `uncertain_ingested=2` / `upgraded_verified=0` 这类定位手段会失真。**本缺口正是靠这两个数字暴露的**，保住它们的判别力等于保住下一次的发现能力。

## ③ 组头语义：显式裁定（非副作用）

- **触发判据改为「跨条目 ∪ 条目内列表」的语境并集**；**单条目累积 2 语境可自触发组头**。
- 三方一致（我 / Design / 条款意图），**leader 已批**。
- **规格标注：这是显式裁定的语义变更，不是重构副作用。**
- **与合并语义同批落，不可拆** —— Design 定为**硬阻断**：拆开落会让 #61 刚修好的自愈渲染回归。

## ④ 四条守门测试（Design 版全采）

1. **累积不覆盖** —— 升格后原语境仍在。
2. **列表形态下组头仍成组** —— 含条目内并集触发。
3. **存量单值读得回** —— 旧字符串条目经 helper 正常渲染（对应「旧条目零迁移」）。
4. **`merged` 不计入 `ingested`** —— 契约四态的计数隔离。

## ⑤ 收进 v2.2 的既有裁决（交错件归并）

- **population 5（404 条零出处）＝提案乙**：三档（手册签名 / `device_run_verbatim` / 最弱档），**档名由 Design 按 §24⑶ 定**，我暂拟的 `unverified_legacy` 作废；渲染层白名单式只信前两档。
- **population 4 ＝ 3 条**（＝5 处字段，单位不同已了结），选取器清单 `ssl.host` / `sdns.host.pool` / `ssl.activate.certificate`。
- **配对置信裁强档**：extra_candidates 派生条目打 `pairing: "heuristic"`，**不参与 R2 自动升格**（仅限自动路，显式确认后可升）。
- **方案 A 否决依据**＝条款禁止（`THEORY:715-716`）+ `conflicts_with` 破坏 + 字段语义单一性；我原先的「组头」依据已自纠作废。

## 证据边界

- 消费点清单为本次**全仓实跑 grep**（`main/` + `tests/` + `scripts/`，排除日志），Design 补的 2 点已逐一读取上下文确认。
- 「`grade_extract_script` 静默吞」是**读到了包裹它的 `try/except Exception`（`:142`）后作出的判断**；其余 3 处硬崩**未逐一核对是否有外层 `try` 包裹** —— 若有，它们也会退化成静默吞（更坏），实现时需一并确认。
- 四处异常/吞没后果均**未构造用例实测**，按纪律先写失败用例。
- 条款原文 `THEORY:714-716` 我仍**未直读**，leader 已直读验证；§24⑶ 词汇表未读，不预设档名。

---

# 规格线闭合：四维命名表 + A2″ 三分映射（2026-07-20 · 终）

## 四维 provenance 命名表（Design 定稿，已批准）

命名律：**`<维度>_provenance`**。四维正交，各答一个独立问题：

| 维度字段 | 答什么问题 | 值域 | 实现状态 |
|---|---|---|---|
| `syntax_provenance` | 这条命令文本是**语法**还是**跑通的实例**？ | `device_run_verbatim` / （手册签名不打标） | **已实现**（`merger.py:~398-400`） |
| `evidence_provenance` | 这条的**出处**从哪来？ | **`unsourced_legacy`**（population 5 的 404 条）/ 手册 / 设备 | 待 unit-3 |
| `build_provenance`（既有实现名 **`build_source`**，别名保留） | 版本锚**可信吗**？ | `probe` / `config_fallback` / `legacy_unknown` | 待 S3 + unit-3 |
| `pairing_provenance`（既有实现名 **`pairing`**，别名保留） | cmd↔content 的**配对**怎么来的？ | `heuristic`（extra_candidates 派生） | 待 unit-2b |

**档名定稿说明（Design）**：population 5 用 **`evidence_provenance: unsourced_legacy`**，**不用 `unverified_*`** —— 后者会与 `validity` 轴同读法撞车。两轴**正交**：完全可以 `validity=verified` 而 `evidence_provenance=unsourced_legacy`（设备实证过、但库里这条没留出处）。

- 我在 v2 暂拟的 `unverified_legacy` **正式作废**（文中三处已标），以本表为准。
- 渲染层/worker 侧**白名单式**判定不变：只信手册签名与 `device_run_verbatim`；`build` 只信 `probe`。

## A2″ 三分条款 → 代码面映射（对齐进 unit-2b）

`_append_cli_command`（`merger.py:314-403`）现有**三个出口**，即 A2″ 三分的代码面对应：

| 分支 | 位置 | 条件 | 出口 |
|---|---|---|---|
| **① 同一语法** | `merger.py:~369-374`（含 `:371` 的 `return "skip"`） | `existing.command == cli_syntax` 逐字相等 | 有新参数则合并参数表 `append`，否则 `skip` |
| **② 挂接** | `merger.py:~380-392`（`:380` 的 `is_device_verbatim` 判定起点） | 设备实证 ∧ `command_words` 序列全等 ∧ 手册出处靶**恰好一条** | `_attach_device_run(targets[0], fact)` —— 证据挂到权威签名上，不新建 |
| **③ 新建 + 标记** | `merger.py:~393-403` | 其余（含**多条同命令词序列的手册签名**，无从判该挂哪条） | 新建条目 + `syntax_provenance: "device_run_verbatim"` |

**已核实的实现质量（超出规格要求的两点，记录备查）**：
- 分支 ② 的**「恰好一条才挂」**保守侧处理是 Design 精化：多条同命令词序列的手册签名（不同参数形态）挂错 = 把实证按到错误签名上，宁可退到分支 ③ 多一条带标记的条目。**这比我 v2 规格写的更严**，采纳实现侧。
- `command_words`（`:314-324`）**显式不剥动词**，并在 docstring 里写明与 `uncertain._behavior_feature_head` 的差别、警告勿混用 —— 正是我 v2 规格 ④ 要求的「`_behavior_feature_head` 只作节点寻址、不参与挂接判定」。**Py-Eng 实现对了，且把理由固化进了注释**（拿行为挂载键当签名匹配键会让 `show ssl certificate` 与 `ssl certificate` 判等，把观测命令的设备证据挂到配置命令上）。

## 规格线状态：全闭合

| 单元 | 内容 | 状态 |
|---|---|---|
| 第一单 | S3 → S1 → S2-reduced | **S1/S2 已落**（`merger.py` 三分 + `command_words` + `syntax_provenance`）；S3 见规格 |
| unit-2a | T2 canary + P 键派生单点化 + P1-6 静默吞计数信号（**并入 `grade_extract_script` 静默吞**） | 规格闭合 |
| unit-3 | 迁移五 population（含验收全覆盖表 + 四条纪律） | 规格闭合，排 B-1 收批后窗口 |
| unit-2b | R2 本体（九条硬约束 + 合并语义 + 组头裁定 + 四条守门测试 + A2″ 三分映射） | 规格闭合 |
| 下窗口 | P1-C 三处共用判据函数 / P1-A raw_invocation guard | 规格已出，待排 |

**缺口③（IPv6 投影）** 独立于上述线，规格已出（落 `env_facts.py`，约 4 处小改），救回路径 routerB ↔ `3ffb::70` 已转 Test-Eng 探针验证。

## 证据边界（终）

- 本节的三分映射与实现质量评价为**本次行级阅读**（`merger.py:314-403`）。行号仍在漂移（第一单正在合入），**一律以符号名定位**。
- 「S1/S2 已落」是我读到 `merger.py` 现有实现得出的**盘面观察**，**未跑测试验证其正确性** —— 权威验证以 leader 亲跑 pytest 为准。
- 四维命名表、`unsourced_legacy` 档名、A2″ 条款均**采自 Design/Theory 出稿**，我未参与会签、未直读条款原文（`THEORY:714-716`）与 §24⑶ 词汇表。
- 全文档所有「未实测」标注（四处异常/吞没后果、P1-C 白名单误报、extra_candidates 锚配错风险）**仍然有效**，实现时按「先写失败用例再改」纪律处理。

---

# v2.3 微补：观察组分两类（Theory 反向质疑裁定 · 2026-07-20 · 收口）

## 裁定

组头触发后，按**组内条目数**二分（判别机械，**触发判据＝语境并集不动**）：

| 组内条目数 | 类型 | 渲染 | 仲裁指引 |
|---|---|---|---|
| **= 1** | **印证组**（泛化证据 / generalization evidence） | 标「泛化证据」 | **不发** |
| **≥ 2** | **潜在分歧组** | 现有多语境组头 | **发** |

## 为什么必须分：这是 v2.1 语义连带的正解

v2.1 我提出「单条目累积 2 语境后自己就能触发组头」须显式裁定，Theory 的反向质疑给出了比「批准/否决」更准的第三条路：

- **单条目双语境 = 同一条知识在两个语境下都被观察到 → 这是相互印证（泛化证据），不是分歧。**
- 而现有组头文案（`footprint_lookup.py:202-207`）写的是：「the behavior is likely condition-dependent... **Where observations contradict, a device experiment can arbitrate**」——**对印证组发这段，等于把「两次都成立」误报成「可能相互矛盾、去做设备实验仲裁」**。
- 后果具体且昂贵：worker 读到仲裁指引会**去设备上做本不必要的 A/B 实验**（自愈环设计里这正是仲裁触发路径），把一条已被双语境印证的知识当成待裁分歧 —— **既烧设备轮次，又可能把稳定知识改坏**。

故分两类不是措辞优化，是**防止误导 worker 发起无谓仲裁**的实质修法。

## 规格

1. 判别：`len(obs_group) == 1` → 印证组；`>= 2` → 潜在分歧组。**只看条目数，不做语义判定。**
2. 落点：`footprint_lookup.py:201-207` 的 `if obs_group:` 分支拆两支文案。印证组文案要点＝「同一知识在 N 个语境下均被观察到（泛化证据）」，**不含 contradict / arbitrate 字样**。
3. 触发判据（跨条目 ∪ 条目内列表的语境并集，v2.2 ③）**保持不变**。
4. 与合并语义、组头裁定**同批落**（v2.2 ③ 的不可拆约束延续到本条）。

## 守门测试第 5 条（加进 v2.2 ④ 的四条）

> **单条目双语境组必须渲染为印证组，且不得携带仲裁指引。**

断言要点：构造一个 `observed_under` 含 2 个语境的**单条目**节点 → 渲染结果含泛化证据标记、**不含** `arbitrate` / `contradict` 文案。

## 我的三处修正：已获采纳记档

leader 确认全部采纳，此处归并备查：

1. **硬崩是 3 处不是 2 处** —— `merger.py:496`（`_distinct_observation_contexts`）+ `footprint_lookup.py:172` + `:174`。
2. **`grade_extract_script.py:136` 是静默吞不是崩** —— `.strip()` 包在 `try/except Exception`（`:142`）内，观察行整段无声消失；**已并入 unit-2a 的 P1-6 静默吞治理面**。
3. **6 个测试断言点同步清单** —— `test_self_healing_loop.py:107/159/211/322`、`test_ssl_enablement.py:153/184`；其中 **`:159` 的 `entry["observed_under"] == "钉死的分辨条件"` 是「覆盖语义」的固化断言，与累积语义直接冲突、必须改**，否则与守门测试①（累积不覆盖）互相矛盾。

## 证据边界

- 组头文案原文为本次行级阅读（`footprint_lookup.py:201-207`，`⚠ Multiple observations… Where observations contradict, a device experiment can arbitrate`）。
- 「worker 读到仲裁指引会发起设备 A/B 实验」是**基于自愈环设计意图的推断**（CLAUDE.md 载「worker 检索见观察组自主设备实验仲裁」，A/B 实证 035570）—— **未在日志中定位到因印证组误发仲裁而多跑的实际轮次**（该形态需累积语义上线后才可能出现，当前存量条目均为单语境）。
- 裁定采自 Theory 反向质疑，我未直读其质疑原文。
