---
name: ist_compile
description: "把人工测试用例（脑图 / txt）编译成自动化 case.xlsx 的编排主入口。你作为 orchestrator 掌全局：解析脑图拆出 case 清单 → 逐个派 compile_worker 子 agent 写对 → 验它们的产出、有问题就带反馈重派（自愈）→ 合并打包。当用户要「编译用例」「把脑图/txt 转成 case.xlsx / excel」「用例编译」「编译这批脑图」时用。"
context: inline
user-invocable: true
source: hand
version: "5"
effort: high
when_to_use: |
  Use when 用户要把人工测试用例（脑图 / txt）编译成自动化 case.xlsx。
  Examples: "把这批脑图编译成 excel"、"编译这个 txt 用例"、"用例编译"、"脑图转 case.xlsx"。
  Trigger keywords: 编译用例, 脑图转excel, txt转excel, 用例编译, 闭环编译, case.xlsx。
  SKIP when: 只查一条 CLI 回显用 dev_probe；对已编译 excel 做上机复验走 ist_verify（当前 .disabled，待 main-orchestrated 配套改造后重新启用）。
---

# 编译编排（main-orchestrated）

## Overview

把人工用例（脑图 / txt）编译成断言真覆盖目标行为的自动化 `case.xlsx`。**你是 orchestrator**——掌全局、派 worker、验产出、改计划、自愈，像你平时派 subagent 那样自己编排，**不调黑盒 `compile_pipeline`**（它保留只当 fallback）。

- **worker = `compile_worker`**：复刻你自己的自由理解逻辑、限定到单个 case。你用 `invoke_skill(skill="compile_worker", brief=…)` 派它编一个 case。它不走"先检索先例→observe"那套老序列，就像你那样：读懂行为 → 区分原始约束与可改写 claim → 判断断言属静态层还是运行时层 → `compile_emit` 落盘。
- **验收 = 独立质量门**：每个 worker 产物合并前都经过 fresh `ist_compile_grade`（或等价确定性 `compile_score` 门）审批。你负责汇总、解释、重派，不把自己的肉眼判断当最终语义放行。
- **本 skill 只产 excel，不上机。** 上机复验走独立的 `ist_verify`（当前 .disabled，待重新启用前不要引导用户调它）。

## 流程

### 0. 确认版本（ask_user，不猜）

从请求提取产品版本（如 10.5）；没写就 `ask_user` 问。版本是 worker 查哪个手册的依据，错了整批文法全错。

### 1. 解析脑图 → 拿 case 清单

```
compile_prep(mindmap_path="<脑图.txt>", out_name="<脑图名>")
```

它通读脑图、列出所有 case（autoid 主键 + 标题 + 分组 + 步骤 + 期望 + 预检索的先例/footprint），写到 `workspace/outputs/<out_name>/manifest.json`。`fs_read` 它，拿到完整 case 清单——这是你掌全局的依据：清单有几个 case，你就该派几个 worker、收几份产出，一个都不能漏。

### 2. 逐 case 派 worker

对清单里每个 case，`invoke_skill(skill="compile_worker", brief=…)`。brief 给 worker：这个 case 的被测行为（标题 + 步骤 + 期望）、产品版本、manifest 里这个 case 的先例/footprint 块。brief 保留原始 step_intents 全量文本；若你已经识别出配置形态、地址族覆盖、池数量、阶段顺序、绑定关系等必须保留的约束，把它们列成 `preserve_constraints` 一并给 worker。worker 写对、`compile_emit` 落盘到 `workspace/outputs/<autoid>/case.xlsx`、返回路径 + 一句话思路。

可并发：一条消息里发多个 `invoke_skill`，worker 们并行跑——大批量时这样不会把你自己的 token 烧光。

### 3. 验产出 + 自愈

逐个看 worker 回的产出（路径 + 思路，必要时 `fs_read` 那份 xlsx）。这里有两层质量门，**层次不同、不能互相替代**：`compile_grade_extract` 是确定性探针，只覆盖它已编码的几类结构信号（写死命中、恒真计数、分布缺口等）；`ist_compile_grade` 是读懂这条 case 语义、对照 need_intent 判断"断言有没有真证明声称的行为"的评审，覆盖面不限于探针已编码的那几类。探针干净只说明"已知的几类问题没命中"，不等于"语义已验证"——dongkl_5fail 实跑（2026-06-30）就是反例：5 个 case 的探针全部 `suspect_count=0`，其中一个 case 的产物却只用两段聚合计数统计证明了"新增 pool 参与了轮转"，没证明 need_intent 要的"按原有顺序最后才命中"（聚合计数对请求顺序的重排不敏感，原理上证不了顺序声称）——这类语义判断在探针的判定范围之外，只有真正读这条 case 的 `ist_compile_grade` 会注意到，但那次实跑全程零次派发它，直接拿探针的"零信号"当放行依据进了合并。

对每个产物，先看这几条（探针之外，需要你自己读 manifest 对照判断）：

- 写死了运行时**单点**落点吗？——某次请求命中的具体 IP，是运行时层，写死会偶对偶错。
- **算法选对形态了吗**（最常错）：rr/wrr 均摊/比例分布 → 发 N 次（dnsperf/iperf 等）→ 统计命令看各后端累计命中 → `dist` 声明断言各后端命中∈守恒区间（不是写恒真 `Hit:\s+\d+`、不是写死单次命中 IP、不是整体 `<RUNTIME>` 弃权）；ga（优先级）/一致性哈希/会话保持 → H 捕获比较验关系（不套分布区间）。一刀切套同一种、尤其拿轮询那套套 ga，是算法类反复 CUT 的根。
- **原始约束保真了吗**：拿产物逐项对 manifest 的 step_intents。脑图点名的地址族/服务类型组合、池数量、绑定关系、阶段顺序、新增前/新增后结构、限制数量等约束，不能因为修复某个欠定预期而消失或被简化。用户选择"改预期/改过程"只作用于欠定 claim，不等于授权把配置覆盖面改成另一个更容易写的 case。
- **有序 claim 是否被降级了吗**：原预期若说"按原有顺序/最后才命中新增 pool"，验的是有序轨迹；"新增 pool 有命中/参与分布"只是较弱 claim，不能替代——聚合计数类断言本身就证不了顺序，无论容差/区间调得多精确。发现降级，带这个反馈重派 worker。
- 被测行为真覆盖了吗，还是只验了配置回显（弱断言）？

再过两道门，**顺序固定、第二道不因第一道干净而省略**：

1. `compile_grade_extract(xlsx_path, prov_path)`：看 `suspect_count` 与 `hardcoded_hit_ip_suspect`（分布算法下写死单次命中 IP）/ `hardcoded_count_suspect`（写死固定命中计数 `Hit:\s+1`）/ `distribution_coverage_gap_suspect`（配了 rr/wrr 却无分布区间也无关系断言）/ `weak_v_coverage_suspect`。任一为真，直接带这个信号反馈重派 worker，不必等下一步。
2. **不论第 1 步结果如何**，把原始 need_intent、产物路径、provenance 路径、你观察到的 preserve_constraints 交给 `ist_compile_grade`；它判 PASS 才能进入合并。

**发现问题 → 带具体反馈重派 worker**：`invoke_skill(skill="compile_worker", brief="<上一版 + 问题反馈>")`，它针对反馈改、保留对的部分。一直到这批 case 全部达标。

### 3.5 欠定用例 → 汇总问用户（绝不替用户改、绝不让 worker 硬编）

worker 返回里若带 `NEEDS_USER_DECISION`（它调 `compile_check_verifiability` 证伪发现「用例如写根本验不出目标行为」——如「1 次请求验 rr 轮转顺序」「新增 pool 仅 1 次请求验最后才命中」「wrr 发 3 次验 3:2:1 比例」），**别重派 worker 硬编、也别自己替用户改**。先把这个标记作用域收窄到具体 rewritable_claim：哪些步骤/预期欠定，哪些 preserve_constraints 不受影响。把本批所有 NEEDS_USER_DECISION 的 case **汇总成一次 `ask_user`**（每 case 一个问题，header=autoid 尾 6 位，三选项，description 带上 worker 给的原因 + 最小可验请求数 + preserve_constraints 摘要 + 待决 claim）：

- **改预期**：只把不可证伪的绝对预期改成可验的关系/分布；配置形态、服务类型组合、池数量、阶段顺序等 preserve_constraints 原样保留。
- **改过程**：只把请求数/观测次数加到最小可验数（worker 给的 `min_requests`，如新增 pool 类加到 4 次）；原始配置和场景结构不改。
- **改描述**：用例描述本身有歧义 / 与设备真实行为矛盾，需人工厘清。

拿到用户选择后**带决定重派 worker**。brief 写清三块：`preserve_constraints`（原始约束，保留）、`allowed_rewrite_scope`（只允许改哪些 claim 的请求/断言）、`user_decision`（用户选了什么）。**user_decision 要落成 worker 可直接执行的断言形态硬约束，不是泛泛一句"改了"**（worker 会挑省事的形态写、把用户的选择跑偏——777976 实测：用户选了分布断言，worker 却产出关系断言）：

- 选**改过程（分布断言）** → worker 必须：发 N 次（dnsperf/iperf 等一条命令发起）+ 统计命令看各后端累计命中 + `dist` 声明区间断言。**不许**降级成关系断言、不许写死单次命中 IP/计数。
- 选**改预期（关系断言）** → worker 必须用 H 捕获比较（`captured_relation`，验两次同/异）。**不许**写死单次命中 IP/计数。
- 原预期是"新增 pool 最后才命中"的，无论改过程/改预期都保持有序轨迹语义（请求数覆盖原 pool 一轮 + 新增后再发，证明新增 pool 出现在原 pool 之后），不降级成"新增 pool 有命中"。

无论选哪项，原 case 的服务类型 / 地址族（v4/v6/混合）/ 阶段顺序 / 池数量 / 绑定关系等 preserve_constraints 都原样保留。用户没答/取消的 case，如实标「待用户决定」进汇报，不强行产出。

### 4. 合并打包

全部 case 达标后，用 `compile_emit_merged(autoids=[…清单里全部 case 的 autoid], out_name="<脑图名>")` 合并打包。**只传 autoid 列表**——worker 已把每个 case 落成 `outputs/<autoid>/case.xlsx`，工具自己从这些成品回读 steps 合并。**别去凑 steps/init**：那些数据 worker 已写进 xlsx，你手里没有、凑也凑不全（凑残会出空步骤/空命令）。

### 5. 汇报

excel 路径 + case 数（达标 / 仍有问题逐条带 autoid + 原因）。`ist_verify` 当前 .disabled，暂不提示用户上机复验。

## 红线

- **掌全局别漏**：manifest 列了几个 case，就派几个、收几个、验几个。token 紧就分批派 worker、续派，但清单不能丢——别像单 agent 硬写到耗尽、做一半就停。
- **worker 复刻你、不是另一套约束**：worker 用你的自由理解逻辑（`agents/compile-worker.md`），不走先例驱动 + observe-then-assert。
- **验收不放水**：worker 自己不自评，合并前由独立 grade/score 门验；发现写死/漏覆盖如实重派，不拿弱产物充数。
- **grade 隔离，且不可被探针替代**：合并前每个 case 都要有这次实跑出来的 `ist_compile_grade`/`compile_score` 结果。`compile_grade_extract` 没信号、orchestrator 自己觉得达标，都不构成跳过 `ist_compile_grade` 的理由——前者只覆盖确定性可判的几类问题，后者才管语义覆盖这件开放问题。
- **上机解耦**：只产 excel，不调 `dev_run_batch` / run。上机走 `ist_verify`（当前 .disabled）。
- **欠定不硬编**：worker 上报 `NEEDS_USER_DECISION` = 用例如写验不出目标行为（数学证伪），汇总 `ask_user`（改描述/改过程/改预期），绝不替用户决定、绝不让 worker 死抠断言形态乱写。
- **改写不改题**：数学证伪只改欠定 claim；manifest 原始约束是验收基线。把 v4/v6/混合、多阶段、新增顺序、数量边界等覆盖点简化掉，即使断言本身可运行，也按漏覆盖处理。
