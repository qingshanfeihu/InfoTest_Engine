---
name: ist_verify
description: "把已编译好的成品 case.xlsx 上机跑一遍：采集设备真实裁决、回填留空的 RUNTIME 断言、对失败做四层归因（G/E/V/瞬态）并按层交回 ist_compile 重编，真 PASS 的写回 footprint。只验已有 excel、不生成新用例。当用户说上机验证 / 上机复验 / verify 这个 case.xlsx / 上机跑一遍看结果 / 验证用例 / 跑通看看 / 按 G·E·V·瞬态归因 / 上机 PASS 写回 footprint，或想让已编译好的成品 excel 在设备上实跑确认时用本 skill。"
context: inline
user-invocable: true
source: hand
version: "1"
effort: medium
when_to_use: |
  用户要对已编译好的 excel / case.xlsx 做上机验证、上机复验、跑一遍看结果、确认能不能在设备上跑通；含四层归因 / 上机回填 / 闭环写回。
  例："把这个 excel 上机验证"、"上机复验编译好的用例"、"上机跑一遍看结果"、"验证并按 G/E/V/瞬态归因"、"上机 PASS 的写回 footprint"。
  触发词：上机验证, 上机复验, 上机跑, 验证excel, 验证用例, 跑一遍, 复验, 设备验证, 四层归因, 闭环写回。
  跳过：要编译/生成新用例走 ist_compile；只查一条 CLI 回显用 dev_probe；评审用例文件质量但不上机走 test-list-review。
---

# 上机验证：串行上机 + 四层归因 + 回流交接

## Quick Start

对一份编译好的 `case.xlsx` 上机跑一遍最小调用：

```python
# 1. 首跑：整份 xlsx 单跑一次，拿逐 case 归因摘要 + 全量明细落 last_run.json
dev_run_batch_digest(
    xlsx_path="workspace/outputs/<脑图名>/case.xlsx",
    autoids_json='["121100001","121100002"]',
    # 进程内消化大结果：返**精简摘要**(计数 + 逐 case 归因层 + found_times 崩溃点名元凶 case)，
    # 全量明细(device_context/causality/traceback)落 workspace/outputs/<脑图名>/last_run.json——
    # fs_read 分页 / fs_grep <autoid> / run_python json.load 都能读它去深挖某个 fail。
    # build/module 不传 → get_config() dataclass 默认兜底(module=sdns + 当前版本 build)，别问。
)
# 2. 若有 <RUNTIME> 待填：看槽位 → 从首跑设备真实输出抽值回填 → 复验
compile_runtime_slots("workspace/outputs/<脑图名>/case.xlsx")
compile_runtime_fill(xlsx_path=..., fills_json=..., run_meta=...)
dev_run_batch_digest(xlsx_path=..., autoids_json='[...]')  # 复验(build/module 同走默认)
# 3. 仍 fail 的 → 四层归因(基于 last_run.json 里该 case 的 device_context)；真 PASS 的 → 写回 footprint
```

整份 xlsx 单跑一次（deliver+run 合并），超时 `clamp(max(floor, N×45s), 600, 2400)`。**只验一遍即返回**，不自套"验到全过"循环。

## Quick Reference

| 阶段 | 工具 / 动作 | 关键约束 |
|---|---|---|
| 定位 | 确定 xlsx 路径 + autoids + provenance 路径（build/module 走默认、不必确定） | provenance 缺失 → 归因退化、不写回 |
| 首跑 | `dev_run_batch_digest(xlsx_path, autoids_json)` → 精简摘要 + 明细落 `last_run.json` | 含 `<RUNTIME>` 的 case 必 fail，属预期待填，先别归因；found_times 崩溃=编译缺陷(摘要已点名元凶 case) |
| 回填 RUNTIME | `compile_runtime_slots` → `compile_runtime_fill` → 复验 `dev_run_batch_digest` | 值只来自设备真实输出；填完即锁、不反复改；抽不出留空 |
| 四层归因 | `compile_attribute(verdict_detail, failing_assertion_layer)` | 必基于 `device_context`/`framework_traceback`；瞬态单列不回流 |
| 回流交接 | `invoke_skill(skill="ist_compile", brief=...)` 一次 | 修 case 唯一正路；绝不手调 `compile_*` 内部步、绝不 `fs_edit` xlsx |
| 写回 footprint | provenance 取真 PASS 的 G 段文法回写（`on_device_passed=True`） | 只写 G 段命令文法；V/E/运行时值不写 |

把**已编译好的** excel 串行上机一遍，采集框架真实裁决，回填 `<RUNTIME>`，对每个 fail 四层归因、按层 reflow 交给 `ist_compile` 重编。**只验一遍 + 交接修复**——不自己改 case（改归 `ist_compile`），也不自己套"验到全过"的迭代循环（迭代由上层：用户 / goal 循环驱动；本 skill 跑一遍即返回）。

## Inputs

- excel 路径或脑图名（→ `workspace/outputs/<脑图名>/case.xlsx`）+ autoid 列表。
- **build/module 不用你确定、也别为它问用户**——`dev_run_batch` 不传时底层 `get_config()` 自带 dataclass 默认（module=`sdns`、build 为当前产品版本）兜底。只有用户**主动**给了特定 build 串时才把它传进 `dev_run_batch`；没给就直接不传，让它走默认。本地没有 `compiler_config.json` 是常态、不是缺失。
- 各 case 的 `case.provenance.json`（draft v3 旁挂；缺失则归因退化到只看裁决明细、不写回）。

## Principles

- **裁决以框架逐 check_point 真实明细为准，不信 verdict 字符串**——字符串可能把环境失败写成 fail、掩盖真因。
- **失败必看 `device_context`**：`dev_run_batch` 对非 pass case 返回它——含 ① 框架逐步执行 + 断言明细 + case 内异常 ② 设备配置会话原文（每条命令 + 设备真实响应，含 `^` 语法错 / `Failed to execute X because Y` → 哪条命令被拒/为什么）③ 触发端 RouterA/RouterB/clientc dig 真实输出（ANSWER SECTION / 实际解析 IP）。`unknown` 的 case 还附 `framework_traceback`（**文件级崩溃**真因：某 case 把整份 pytest 搞崩、后续全不跑 → 先修 traceback 指的那一个，别误判后续 case 本身错）。**改配置 / 填值 / 写 reflow brief 都基于它，不靠猜。**
- **拿不准框架断言行为就读框架源码**（只读，沙箱已放行这两个文件）：`knowledge/framework/mirror/lib/check_point.py`（`found`=`re.compile` 当**正则**；`abs_found`=`re.escape` 当**字面**；`found_times` 需 3 参）+ `lib/test_xlsx.py`（check_point 分派只传 2 参 → `found_times` 必崩；带 H 的步只存寄存器不更新 `result`；`getattr(env,F)` 不转小写）。断言为何匹配/不匹配/崩，**以源码为准**。
- **归因如实，不救场**：不把环境失败粉饰成通过，也不把断言失败甩锅给环境。
- **诊断「给事实、不给结论」**：把设备真实证据交给你判断，别用现成结论替换事实——① **主料是原始事实**：`last_run.json` 里该 case 的 `device_context`（设备会话原文 / `^`语法错 / dig ANSWER SECTION），据它下判断；② **机械预判只认协议级事实**：digest/`compile_attribute` 只在设备 `^` 语法拒绝时给 G（可直接采信，先修它——同 case 后续失败多为下游后果），其余标 undetermined **不猜**——E/V/瞬态/产品缺陷由你读原文归因；③ **只有来源比你更可靠的成品结论才直接采信**——如 `found_times` 文件级崩溃（框架必崩的确定性事实，digest 已点名元凶 case）可直接判「编译缺陷、重编」，`^` 拒绝同理；语义类判断永远是你的。
- **三层边界（这错归谁、怎么修）**：**机械崩溃**（`found_times` 必崩、`found(None)` 崩）= emit 结构门管，出现即**编译缺陷**、走重编，**不是**框架 bug；**可证伪性**（某断言对该算法类能不能被证伪，如「命中恰好 N 次」对 rr/wrr 随机起点不可验）用 `compile_check_verifiability` 工具判、欠定就改预期（重定向到命中归属 / 分布区间）；**语义充分性**（断言是否真覆盖脑图关心的行为）是你的判断。别把这三层混着一刀切。
- **单环境内串行**：框架对**一套设备床**有全局锁，同一环境同一时刻只能跑一份 `dev_run_batch`（撞了回 `device_busy`）。
- **多份 excel 跨环境并行**（启用环境池 `IST_ENV_POOL_ENABLED=1` 时）：一轮**并行发多个 `dev_run_batch`**（每个一份 excel），池会把它们**自动分到不同的空闲环境**（各自独立设备床，互不撞锁）→ N 机 N 路并行，总时长≈最慢一份而非求和。并发数超过就绪环境数时多出来的自动排队等空闲，绝不撞同一设备。**池未启用（单环境）时仍串行**：一份接一份，别并发（会 `device_busy`）。

## Steps

### 1. 定位 excel + provenance

**Execution**: Direct

确定 excel 路径、autoid 列表；记下各 case 的 `provenance.json` 路径（缺失则归因退化到只看裁决明细、不写回）。**build/module 别去翻、别问用户**——`dev_run_batch` 不传就走 `get_config()` 默认（见 Inputs）。

**Success criteria**: 路径 + autoids 就绪（build/module 走默认，不阻塞）
**Artifacts**: xlsx_path, autoids, provenance_paths

### 2. 首跑上机

**Execution**: Direct

`dev_run_batch_digest(xlsx_path=..., autoids_json='[...]')`——整份单跑一次，进程内消化大结果，回**精简摘要**（逐 case verdict + 归因层 + `found_times` 文件级崩溃点名元凶 case），全量明细（`device_context`/`causality`/`framework_traceback`）落 `workspace/outputs/<脑图名>/last_run.json`。深挖某个 fail 就 `fs_grep <autoid> last_run.json` 或 `run_python` 读它。build/module 不传走 `get_config()` 默认（见 Inputs）；别为它问用户。

**Rules**: 含 `<RUNTIME>` 的 case 首跑必 fail（框架拿 G 找字面 "<RUNTIME>"）——这是预期"待回填"，**先别归因**。摘要里出现 `found_times` 文件级崩溃（点名了元凶 case）→ 那是**编译缺陷**（框架必崩），直接进步6走重编、不当各自失败逐个查。
**Success criteria**: 拿到逐 case 真实裁决摘要 + `last_run.json` 全量明细
**Artifacts**: digest_summary, last_run.json

### 3. 回填 `<RUNTIME>`（锁死，不反复改）

**Execution**: Direct

`compile_runtime_slots(xlsx_path)` 看待填槽位 + 各自 `observe_cmd`；从首跑设备真实输出里该槽位 `observe_cmd` 的输出中抽真实值 → `compile_runtime_fill(xlsx_path, fills_json=..., run_meta=...)`。

**Rules**: 回填值**只能来自设备真实输出**，抽不出就留空、绝不猜；只动仍含 `<RUNTIME>` 的格子，填完即锁、后续不覆盖（一个槽位只填一次，填错也不被悄悄改掉）。
**Success criteria**: 能填的填上并锁死，填不出的如实记"待人工补值"
**Artifacts**: fills（已填 / 留空）

### 4. 复验 (when applicable: 步3 填过)

**Execution**: Direct

回填后再 `dev_run_batch_digest` 一次。回填的断言现应转 **pass**（设备值＝设备值）；仍 fail 的才是**真实断言失败**，进归因。仍留空的 `<RUNTIME>` 不算失败、不归因。

**Success criteria**: 区分出 真 PASS / 真实 fail / 待补值
**Artifacts**: rerun_results

### 5. 四层归因

**Execution**: Direct

对复验后仍 fail 的 check_point（排除留空 `<RUNTIME>`）：先从 `last_run.json` 读该 case 的 `device_context` / `framework_traceback` 定位真因（`fs_grep <autoid> last_run.json`），从 provenance 取该步 `layer`，`compile_attribute(verdict_detail=<报错明细>, failing_assertion_layer=<层>)` → 拿机械预判。真 PASS 不归因，进步 7。

**Rules**: 归因必基于 `last_run.json` 的 device_context/traceback，不凭印象。**机械预判只有两个确定性结论**：① `compile_attribute` 返回 **G(^)** = 设备语法拒绝标记（协议级事实，直接采信；它是上游根因——同 case 后续 dig 无解析、断言不中、超时多为下游后果，先修 G）；② `found_times` 等文件级崩溃签名 = 编译缺陷（不逐个 case 归因）。**其余一律返回 undetermined——工具不猜，你读 device_context 原文自行判**：E（可达性/环境）、V（断言期望值）、瞬态（判定标准=换时间重跑即消失；digest 摘要点名「连续两轮同签名 fail」的绝不是瞬态）、或疑似产品缺陷（逻辑对∧文档对∧环境正常仍复现 → `kb_bug_search` 比对后记缺陷候选）。
**Success criteria**: 每个真实 fail 有四层归因结论（G错 / E错 / V错 / 瞬态）
**Artifacts**: attributions

### 6. 回流交接（修复只走这一条路）

**Execution**: Direct（委派 fork）

多个 fail case 要重编时，**一次并发 fan-out、别逐个串行**：给每个 fail case 建一条 brief（autoid + target_layer + 该 case 的 `device_context` 原文 + 应改方向 + 「定向重做：针对问题改、保留正确部分」），聚成 JSON 数组，调**一次**
`compile_fanout(skill="ist_compile_draft", briefs_json='[{"key":"<autoid>","brief":"<...含device_context+应改方向...>"}, ...]')`
——N 个 case 的 draft worker **真并发**跑（各自独立 fork 上下文，互不污染、不占 main 上下文），一次返回逐 case 产物。比"逐个 invoke_skill 串行"或"main 自己把 N 个 case 分析完再批量 emit"都快（并行掉最贵的分析+检索）。fan-out 返回后各 case 的新 `case.xlsx` 已在 `outputs/<autoid>/`，回步骤 2 用 `dev_run_batch_digest` 再验（上机才是真门）。

**何时改用 `invoke_skill(ist_compile)`**：需要 grade 质量再审批（断言形态可疑、非单纯 IP/命令订正）时——它内部跑完整 `compile_pipeline`（prep→draft→grade→merge）带收敛环。fan-out draft **跳过 grade**、靠上机复验兜底，适合归因明确的定向订正（G(^) 命令订正、E 层换真实 IP、V 层按设备语义改期望）。

**Rules**:
- **两条 sanctioned 重编路径**：① `compile_fanout(ist_compile_draft, briefs)`（多 case 并发定向重编，快，跳 grade 靠复验）；② `invoke_skill(ist_compile)`（要 grade 再审时，带收敛环）。**除这两个外绝不**自己 ad-hoc 逐个手调 `compile_emit`/`compile_score`/`compile_precedent`/`compile_prep` 去 churn——单步 ad-hoc 循环不收敛、会把单轮 tool_call 撞 recursion 上限（300）整轮崩（实测反例：churn 4 轮 excel 零改动）。`compile_fanout` 是**批量派发器**（不是被 churn 的单步），用它一次派完、不循环。
- **绝不 `fs_edit` case.xlsx**——二进制，文本编辑改不动；改 case 一律走上面两条 reflow 路径。
- **瞬态不回流**——标注"环境排查 / 换时间重跑"，它和编译质量无关。
- **收敛止损（digest 的跨轮对照信号是硬事实）**：摘要点名「连续两轮同签名 fail」的 case → 上轮修法已被证伪，**这些 case 不进本轮 reflow brief**（第三轮同法大概率再 fail、白烧钱——实测同签名 case 连续两轮重编零转正）。改为：①先核实环境事实（dev_probe/dev_ssh 查该 IP/配置在设备上的真实状态——topology 写的和设备实况可能不符）；②环境确认正常仍复现 → 疑似**产品缺陷**：`kb_bug_search` 比对缺陷库，已知则关联、未知则在最终报告「疑似产品缺陷」区记缺陷候选（复现步骤=case 步骤、期望+文档出处、实际=device_context 证据、版本号）。摘要点名「上轮归瞬态本轮复现」→ 那不是瞬态，按同法重新归因。**无论哪种，流程都跑到终点出完整报告（真 PASS 清单 + 阻塞清单带证据），不中途停摆等人。**
- 非交互（`infotest -p`）：直接输出归因 + reflow brief，reflow 作为独立步骤由调用方发起。
- **本 skill 到此即返回**：是否拿重编后的 excel 再 verify 一遍，由**上层**（用户 / goal 循环）决定——verify **不自己套循环**。

**Success criteria**: 待重编的 G/E/V 错经**一次** `compile_fanout` 并发派完（或需 grade 再审时 invoke 一次 ist_compile）；连续两轮同签名 fail 的不进重编（走环境核实/产品缺陷出口）；瞬态单列
**Artifacts**: reflow_brief（fan-out briefs_json）

### 7. 闭环写回 footprint

**Execution**: Direct

对每个**真 PASS**（框架 pass 且断言真覆盖目标行为）的 case，调 `compile_footprint_writeback(autoid=..., provenance_path=".../case.provenance.json", on_device_passed=True)` 把 **G 段文法**写回 footprint（工具内 evidence 门防幻觉、只写 G 段）。footprint 越饱，下次同类 draft 越少啃手册。

**Rules**: 靠工具写回、别手动拼 footprint JSON；工具只写回 G 段命令文法，**V 段断言、E 段具体 IP、回填的 `device_verified` 运行时值不写回**（环境态，进 footprint 会污染）。provenance 缺失则跳过写回（归因已退化）。
**Success criteria**: 真 PASS 的 G 段已写回，报告写回条数
**Artifacts**: footprint_writeback

### 8. 输出报告

**Execution**: Direct（输出时禁止再调工具）

按下方结构输出：

```
### 上机验证 summary
- excel：<path> | build：<build> | 总 case：N
- 真通过 P / 真实 fail F（G错 a / E错 b / V错 c）/ 瞬态 t / 待补值 r
- 回填：填了 x 个 <RUNTIME>，留空 y 个（待人工补值）

### 逐 case
| autoid | verdict | 归因层 | reflow→层 | 关键裁决明细 |
|---|---|---|---|---|
| <id> | fail | V | →V | fail to find ... |

### footprint 写回
- 写回 N 条 G 段（autoid + feature_id）

### reflow brief（如有 G/E/V 错）
<逐 autoid + target_layer + device_context 摘要 + 应改方向>
```

**Rules**: 报错如实贴出，不含糊；最终输出时禁止再调任何工具。
**Success criteria**: 报告含 summary + 逐 case 表 + footprint 写回 + reflow brief 四段，异常项有根因
