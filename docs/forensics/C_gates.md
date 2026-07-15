# 取证单元 C — broken 第三态路由核验 + 两门盲区（gates 手）

> 循环阶段：实证→理论→设计（只读，零代码改动）。
> 数据源：`workspace/outputs/dongkl*/{last_run.json,facts.jsonl,case.xlsx,needs_decision.json,manifest.json}`、
> `runtime/logs/verified_runs.jsonl`、`<SCRATCH>/trace_dumps/`、仓库源码。
> 标注约定：**【数据事实】**=盘上可复核的铁证；**【我的判断】**=据事实的推断；**【给用户的问题】**=设计张力项，待裁决。

三块分工（对齐 team-lead 定性）：
- **块1 broken**：结论=「核验已落地」——§18.1 broken 全链已实现且有测试锚，210998 真按设计路由。
- **块3 DNS lint**：结论=「找到 lint 漏的那一行」——`_DOMAIN_TOKEN_RE` 的 TLD 白名单锚是根因，给结构化修法。
- **块2 command_existence**：trace 补证后一分为二——**B2a**=活跃卫生 bug（clean re-emit 不清 stale 台账，可直接修）；**B2b**=潜伏的单信号门红线问题（dongkl 里 worker 自纠了没爆，给用户裁决）。**团队初判「门误导用户」在 dongkl 是虚警**：引擎从未真问用户。

---

## 第一节 · 实证根因（从数据，行级铁证）

### 1.1 块1 — 210998 怎么变成 broken 的（fail→fail→broken 三轮迁移）

**【数据事实】** `verified_runs.jsonl` 中 210998 终态 = `broken`（末条，`run_ts=1784086794`，`xlsx=…/dongkl__sub3/case.xlsx`）。逐轮轨迹（`facts.jsonl` 权威事实流，主 `dongkl` 目录）：

| 轮 | 目录 | verdict | 关键命令 / 签名 | 归因 |
|---|---|---|---|---|
| r1 | dongkl | fail@delivery | `show statistics sdns query test.a.com`；sigs=`['AAAA']` | V/defect_candidate（AAAA 未在默认统计输出暴露） |
| r2 | dongkl__sub2 | fail@subset | `show statistics sdns query test.a.com all A`/`all AAAA`；anomaly=`Failed to execute the command`×4 | G/reflow（`all A` filter 命令被设备语法拒） |
| r3 | dongkl__sub3 | **broken@subset** | `show statistics sdns query "" all A`（空串 host）；sigs=`[]` | 无 attribution 事件 |

**【数据事实】** 210998 的 broken 来自 `batch_tools.py` 三条降级路径中的**第 2 条（oracle 残差门 / window-audit）**。`dongkl__sub3/last_run.json` 210998 记录：
```
broken_reason: "assertion-window distortion: the framework's check window disagrees with
                the raw device stream (re-segmented by prompt) …"
window_distortion: [
  {kind:false_fail, cmd:'show statistics sdns query "" all A',   pattern:'\nA Record Statistics:',   evidence:'A Record Statistics: 1'},
  {kind:false_fail, cmd:'show statistics sdns query "" all AAAA', pattern:'\nAAAA Record Statistics:', evidence:'AAAA Record Statistics: 1'}]
```
即：框架 `found` 判 fail（没找到 `\nA Record Statistics:`），但按提示符重分段的原始设备流里**确有** `A Record Statistics: 1` → 方向矛盾 → 降 broken（`batch_tools.py:776-779`，`if _dist and verdict in ("pass","fail"): verdict = "broken"`）。

**【我的判断】** 210998 的 broken 本质是 worker 编写问题的下游症状，不是采集面偶发失真：
- worker 把 host 改成空串 `""`（`show statistics sdns query "" all A`）——畸形入参；
- 断言 pattern 带前导 `\nA Record Statistics:`——过度锚定，设备把该行放在窗口首行（命令回显后无空行）时 `\n` 恒不命中 → 近似「假 fail」形态。

window-audit 正确识别了「值其实在」→ 降 broken 是对的判定；但真正的修法是 **reflow（重编 pattern/命令）**，而 broken 的处置是 **rerun（复跑同卷面）**。见第三节块1讨论。

### 1.2 块2 — 三个「命令不存在」案的真相（worker 造错，非版本缺失）

**【数据事实】** 三案 `needs_decision.json`（`claim_kind=command_existence`）与其脑图意图（`manifest.json`）对照：

| autoid | worker 产出命令 | 门 nearest 记载 | 脑图意图（manifest） |
|---|---|---|---|
| …681811 | **`'s'`**（单字符残缺） | `无` | 「修改一个pool的成员，ga算法测试」 |
| …778012 | **`'sdns clear all'`** | `sdns、sdns cache、sdns dnssec` | 「新增加一个pool，rr算法测试」 step_intents 全是「配置service…加入pool…rr…发送请求查看命中哪个pool」，**无 clear** |
| …778041 | **`'clear statistics sdns'`** | `clear statistics sdns cache、…listener、…local` | 「修改一个pool的成员，rr算法测试」 |

**【数据事实】** 三命令均不在脑图（脑图是 ga/rr 算法配置+发查询），均是 worker 自造/截断：`s` 是单字符残片；`sdns clear all` 是编造的清理命令；`clear statistics sdns` 是真命令 `clear statistics sdns <cache|listener|local|…>` 的**截断前缀**（nearest 全是它加一个尾词）。

**【数据事实】** 门源码 `emit_xlsx_tool.py:_gate_command_existence`（648）唯一判据 = `match_command(cmd)` 的清单成员性（674-676）；未命中即写 `claim_kind=command_existence` 台账（747），reason=「命令X在…手册命令集未命中…也可能该功能不属本版本」（748-753）。`questions.py:138-155` 把它组成题面「在被测版本的 CLI 手册里查不到（可能这版没有此功能，或命令改了名）」，选项 改过程/改预期/**改描述（挂起待适用版本）**。

**【数据事实】** `command_inventory.py:match_command`（99-122）对 (a) 真版本缺失命令（`sdns fulldns on`，头族 `sdns` 存在、功能缺）与 (b) worker 垃圾（`s`/`sdns clear all`）**返回同型 `hit=False`**——无结构区分。

#### 1.2b（trace_dumps 补证，重大修正）— 三案其实是 worker **自纠中的过渡草稿**，门冻结成 stale 台账

**【数据事实】** 三案 worker LLM 思维链（`<SCRATCH>/trace_dumps/{681811_r1,778012_r1,778041_r1}`）：
- **681811 `s`**：worker 全程推理的命令都是良构的（`show statistics sdns pool p1/p2/p3`、`sdns host method autotest.com ga`）；`s`（nearest=none）与它推理过的任何命令都不对应 → **截断产物**，非有意编写。
- **778012 `sdns clear all`**：worker 自己写道「…`clear sdns host persistence`、`clear sdns host pool`，**But no `sdns clear all`. Let me use the individual clear commands or just use `clear slb all`**」——worker **本就认得**这命令不存在、正在自纠。
- **778041 `clear statistics sdns`**：worker 自己写道「**the command `clear statistics sdns` doesn't exist**. The nearest recorded commands are `clear statistics sdns cache/listener/localdns`. **Let me remove the `clear statistics sdns` command**」——同样自纠中。

**【数据事实】** 三案的 round 结局（`facts.jsonl`）证明门**没有真的挡住**它们——worker 同轮自纠后落了干净卷：
- 681811：authored r1 → **pass@delivery** → writeback（**r1 就过**）
- 778041：authored r1→fail(V/reflow)→r2 → **pass@subset** → writeback（**r2 过**）
- 778012：authored r1→…→r3（仍在 reflow，与 command_existence 无关，是 G/V 层断言问题）

**【数据事实】** `needs_decision.json` 是 **stale 残留**：mtime 比最终干净 `case.xlsx` **早 13 秒～3.3 小时**（681811: ND 早 13s；778041: 早 ~1.9h；778012: 早 ~3.3h）；且 `facts.jsonl` 中三案 **needs_decision/decision 事实数全为 0**——**引擎从未把它们呈给用户**。gate 在某次失败 emit 上写了台账并返 error，worker 自纠后干净 re-emit（无 miss）走 `emit_xlsx_tool.py:677-678` 提前 return，**没清那份旧台账**。

**【我的判断】** 团队定性「门把错误命令当版本缺失呈报、题面误导用户」在 dongkl **观测层面是虚警**：门确实写了误导性台账，但 (1) worker 同轮自纠、2/3 直接 PASS，(2) 引擎从未真的问用户。**真正落地的缺陷是 stale-台账卫生问题**（见 2.2 B2a）。原设计张力（门无法机械二分两来源）**降级为潜伏风险**（见 2.2 B2b / P-C2），非 dongkl 活跃故障。

### 1.3 块3 — 994838/994869 超长域名为何漏过 lint（TLD 白名单锚）

**【数据事实】** lint 函数 `structural_gate.py:_check_dns_label_limit`（1100）靠正则：
```python
_DOMAIN_TOKEN_RE = re.compile(r"\b([A-Za-z0-9][A-Za-z0-9.-]{10,}\.(?:com|net|org|cn|test))\b")
```
它**必须匹配到 `.` + 白名单 TLD（com/net/org/cn/test）后缀**才会往下 `dom.split(".")` 查 >63 标签，且只扫 `G` 列。

**【数据事实】** 域名逐轮形态（openpyxl 读 `history/case.r{N}.xlsx`）：

| autoid | 轮 | 域名形态 | 有 `.`/TLD？ | 结果 |
|---|---|---|---|---|
| …994869 | r1 | `dig @… 0123456789abcdef…`（单标签 **141** 字符） | **无** | 正则不匹配 → 漏 → 上机 fail |
| …994869 | r2 | `dig @… 0123…`（单标签 **128** 字符）`… AAAA +noidnin` | **无** | 漏 → 上机 fail |
| …994869 | r3 | `sdns128chars01.sdns128chars02.….com`（**多标签**，每段≤63） | 有 | lint 正确不触发；仍上机 fail（另因，见下） |
| …994838 | r1 | `sdns host name aaaa…oooo`（单标签 **147** 字符） | **无** | 漏 → 上机 fail |
| …994838 | r2 | `…gg.gggg…nnnnnnn.test`（maxlabel **77**） | 有 `.test` | 正则命中 → **emit_invalid `[dns_label_over_63]`**（唯一被抓的一轮） |
| …994838 | r3 | 修正 | — | pass |

**【数据事实】** `facts.jsonl`：994838 round2 有 `emit_invalid reason="成品卷 lint 违例:[dns_label_over_63]"`；994869 三轮全无 emit_invalid（每轮都 authored→device fail）。

**【我的判断（根因，行级）】** lint 漏的那一行就是 `_DOMAIN_TOKEN_RE` 的 `\.(?:com|net|org|cn|test)` 锚。它把「找域名 token」的策略建立在 **TLD 后缀存在**上，而这个 lint 存在的目的恰恰是抓「巨型单标签」——而巨型单标签的自然形态（`0123…def`、`aaaa…oooo` 这类裸测试串）**往往没有 TLD 甚至没有点**。994838 之所以在 r2 被抓，纯属 worker 那轮碰巧加了 `.test`；994869 三轮都是裸串，一次没抓到。`+noidnin`（r2）也救不了：单标签 128 字符超 DNS 线格式 6-bit 长度前缀上限（≤63 octet），物理上发不出，与 IDNA 无关。

---

## 第二节 · §18.15-C 核验结论 + 两门根因

### 2.1 §18.15-C 裁决：broken 全链**已正确落地**（正确，非不充分）

DESIGN §18.1 声称 broken 全链已设计（schema 三值 / fold S_BROKEN / 不计签名 / 不深归因 / 不重编 / 不写回 / 报告单列分母）。逐条核验实现 + 210998 实证 + 测试锚：

| §18.1 设计条款 | 实现位置（行级） | 210998 实证 | 测试锚 |
|---|---|---|---|
| schema 三值透传（禁 pass/else fail 折叠） | `nodes.py:967` `_RESULT_MAP={"pass","fail","broken"}`，缺省 `not_run` | r3 verdict=broken 入账 | `test_broken_third_state.py::test_reconcile_unknown_becomes_not_run` |
| fold → S_BROKEN 派生态 | `views.py:103-106` | facts.jsonl 末条 broken@subset | `test_fold_broken_and_not_run_derive_s_broken` |
| **不计 fail 签名**（防误 frozen） | `facts.py:162-163` frozen 仅看 pass/fail；`views.py:104` | broken 记录 **sigs=`[]`** | `test_frozen_ignores_broken_rounds` |
| **不进 attribute 深归因** | `nodes.py:1219` `if c["status"] not in (S_FAILED,S_CONTRADICTED): continue` | broken 后**无 attribution 事件** | （由 §18.1 短路语义覆盖） |
| **不重编（不烧轮次授权）** | `nodes.py:346` author 工作集仅 `(S_PENDING,S_FAILED,S_CONTRADICTED)`；broken→rerun | broken 走复跑不 reauthor | `test_route_broken_goes_to_merge_rerun` |
| 不写回 / 不回滚 | `nodes.py:1021`（仅 pass 写回）、`nodes.py:1042-1044`（broken 不触发回滚） | — | `test_reconcile_broken_does_not_rollback` |
| 报告**单列分母**（不进 fail 叙事） | `render.py:229-232` `n_broken` 独立行；`nodes.py:2322` totals 由 `vw["counts"]` 注入 | — | `test_reconcile_unknown_becomes_not_run` 断言 `n_broken==1`；`test_status_vocab_and_leak` |
| streak≥2 未跑成 → escalated | `nodes.py:989-1012` | r3 是首个 broken（streak=1），未升级 | `test_reconcile_broken_streak_escalates` |

broken 的**赋值来源**（`batch_tools.py`）三条路径，全有测试锚：
- 路径①（738-754）exec_failure_marker 打在 pass 案 → broken：`test_exec_failure_scan.py`
- 路径②（755-779）oracle 残差 window-audit false_fail/false_pass → broken：`test_window_audit.py`（**210998 走的这条**）
- 路径③（807-821）设备不可达 → broken：`test_device_reachability.py`

**结论**：§18.1 broken 全链**七条设计款全部在代码 + 测试 + 210998 实证三处得到印证**，判定 = **正确**。这一单元不是「补齐」而是「已落地核验通过」。

**两个诚实缺口（不影响主结论，但属 §18.7 纪律的收尾）**：
1. **【数据事实】** 本次 dongkl 运行**未跑到 closing**（`workspace/outputs/dongkl*` 无 `engine_report.json`/`engine_ledger.json`；facts.jsonl 210998 末事件是 broken verdict，其后无 escalated/merge），显系人工中断在 sub3 broken 之后。∴「broken 单列分母」在 210998 上**没有产出物级实证**，只有 render.py + 单测背书。这是「运行被中断」不是「路由错」。
2. **【数据事实】** §18.15-C 明确要「挂 210998 形态回归锚（§18.7 已落地字样挂测试锚）」。当前 `test_window_audit.py` 的 fixture 全取自 **run20 668015/030** 形态（写保存族），**没有 210998 特有形态**（`show statistics sdns query "" all A` + `\nA Record Statistics:` 前导-`\n` pattern + `A Record Statistics: 1` 块的 false_fail）。机制被测了，210998 卷面形态没被锚。

### 2.2 块2 门根因：一个卫生 bug（活跃）+ 一个单信号门潜伏风险

trace 补证（1.2b）把块2 拆成两条，严重度顺序**与初判相反**：

**B2a（活跃缺陷，可直接修）— clean re-emit 不清 stale command_existence 台账。**
`_gate_command_existence`（`emit_xlsx_tool.py:648`）在 `not misses` 时于 677-678 行**提前 return None**，不检查该 autoid 是否已有一份**前次失败 emit 写下的** `needs_decision.json`。worker 自纠后干净 re-emit（换了命令、无 miss）→ 旧台账原样留盘。铁证：三案 ND mtime 比最终 case.xlsx 早 13s～3.3h，且 facts.jsonl needs_decision 事实=0（引擎没消费）。**危害**：① 误导任何「静态检视」case 状态的人（正是本次让三案看着像被误 gate 的直接原因）；② 该案后续因**他因**进问询流时（ask 节点 `questions.py:load_ledgers` 直接读盘），会把过期题面带出——代码 692-694 行注释已知此风险（evidence-accepted 路径会清），但 **clean-emit 路径漏清**。

**B2b（潜伏风险，非 dongkl 活跃）— 单信号门无法机械二分两来源。**
门唯一判据是「命令是否在版本清单」（`match_command` 成员性）。信号在 worker 编对时够用（48 真机 PASS 卷 865 命令误报 0），但把两人群折叠：(a) 脑图要求、版本没有的**功能命令**（`sdns fulldns on`）→ 合法欠定该呈报；(b) worker 自造/截断的**错误命令**（`s`/`sdns clear all`/`clear statistics sdns`）→ 该 reflow。题面对二者都答「版本查不到（可能这版没有此功能）」+ 给「挂起待版本」错出口。**dongkl 里 worker 都自纠了所以没爆**，但若某轮 worker 不自纠、bad 命令留到该轮最终 NEEDS_USER_DECISION，误导题面就会真呈给用户（668059 fulldns 是门本为之而建的真·版本缺失对照）。

### 2.3 块3 门根因：DNS lint 的 TLD 白名单锚（`structural_gate.py:1097`）

**根因（一行）**：`_DOMAIN_TOKEN_RE` 要求 token 以 `.`+{com,net,org,cn,test} 结尾才识别为域名。裸长单标签（无点/无白名单 TLD）——正是「128 字符域名」测试夹具的自然写法——直接不进检查。lint 的目标群体（巨型单标签）恰好高比例落在它的盲区里。994838 靠 worker 碰巧加 `.test` 才被抓一次，994869 三轮全漏。

---

## 第三节 · 修法建议 / 待讨论问题（三块分清）

### 3.1 块3（DNS lint）——设计站得住，给精确修法【倾向直接修】

**【我的判断】** 这是纯 A 层机械门 bug，无红线张力，修法明确、走结构化不碰领域知识：

- **改哪行**：`structural_gate.py:1097` 的 `_DOMAIN_TOKEN_RE` 与 `_check_dns_label_limit`（1100）。
- **改成什么（两选一，倾向前者）**：
  1. **裸标签扫描**（最简、最稳）：不再靠 TLD 猜域名边界，改为在 DNS 相关命令的 `G` 文本里扫**任意极大 `[A-Za-z0-9-]` 连续段（DNS 标签字符集，不含点）**，长度 >63 即违例。任何 >63 octet 的单标签在 DNS 线格式里非法（6-bit 长度前缀），与 TLD、与 `+noidnin` 无关。这一条能抓全部形态（141 无 TLD、128 无 TLD、77.test）。
  2. **绑命令文法**（更精准、稍重）：从 `sdns host name <arg>` / `dig [@server] <arg> <type>` 按位取 `<arg>`，再 `split(".")` 查每段 ≤63。好处是只查真的 hostname 参数、不误伤别处长串；成本是要维护「哪些命令的哪个位置是 hostname」的结构（可从 command_inventory 签名推）。
- **误伤自查**：方案1 需排除已知长非域名串（如寄存器/证书文件名）——但这些通常不落在 `dig`/`sdns host name` 的 G 里；建议方案1 限定在**含 `dig ` 或 `host name ` 的行**上扫，兼顾简单与低误伤。
- **红线合规**：零硬编域名、零 TLD 清单、判据是「标签长度 >63」这个 RFC 物理常量——结构化信号，非关键字白名单。

**【数据事实（边界，勿越界修）】** 994869 r3 用**合法多标签**（每段≤63）仍上机 fail——那是**另一个问题**（设备侧对 128 字符多标签 hostname 的接受度 / 断言 `AAAA\s+fc00::[123]` 不命中），**不归 DNS-label lint 管**。lint 修法只解决 r1/r2 单标签逃逸；r3 的失败要么是产品行为（缺陷候选）要么是断言/配置问题，属别的单元。

### 3.2 块2（command_existence）——一半直接修（B2a），一半给用户的红线问题（B2b）

**B2a 卫生 bug——设计站得住，给精确修法【倾向直接修】：**
- **改哪**：`emit_xlsx_tool.py:_gate_command_existence` 的 677-678「`if not misses: return None`」提前 return 前，增一步：若本 autoid 存在 `needs_decision.json` 且含 `command_existence` 类 claim，则清掉这些 claim（无其他 claim 则删文件）——**与 682-711 行 evidence-accepted 路径已有的清理逻辑同构**，只是补到 clean-emit 出口。
- **红线合规**：纯台账卫生，零命令语义判断。
- **收益**：消除 stale 台账误导 + 堵住「他因进问询流被带出过期题面」（692-694 注释所指风险的 clean-emit 缺口）。
- 回归锚：见第五节 B2a。

**B2b 单信号门——红线张力，列为给用户的问题（P-C2）。能否只靠结构化信号区分 (a) 版本缺失 vs (b) worker 造错，而不碰领域知识？** 分三档回答：

**可机械判、无红线的信号（这些能直接加）**：
- **`nearest_heads == []`**（681811 `s` → 记载「无」）：命令与清单里任何命令头都不沾边 → 结构异类 → 极可能是垃圾。此信号**门已经算出来了**（`_gate_command_existence` 拿了 `nearest_heads(cmd)`），只是没用它分流。
- **命令是某记载头的严格 token 前缀**（778041 `clear statistics sdns` ⊂ `clear statistics sdns cache/listener/local`）：命令**不完整**（缺必需尾词）→ 截断/编写错，不是版本缺功能。可从 nearest_heads 的前缀重合度判。
- **token 数 / 长度过短**（681811 `s` = 1 token、1 字符）：结构上不成命令。

**判不了、正是红线撞点的信号**：
- **778012 `sdns clear all`** 是难点：头 `sdns` 合法、`clear all` 像模像样但 `sdns clear` 不是真子命令；nearest 非空（都含 `sdns`）、也不是任何头的前缀。要把它和「真版本缺失的 `sdns <新功能>`」区分开，只能靠**「命令动词/词根是否溯源脑图 step」**——而脑图是中文自然语言（「配置…加入pool…rr」），命令是英文 CLI token，`clear` 在 778012 脑图里确实一次没出现。但这一步：① 跨中英 token 匹配不稳；② 已经在往「读脑图判命令该不该存在」的领域推理上滑，逼近红线（门不该判命令词序对错）。

**【给用户的问题 P-C2】** command_existence 门是否引入结构化前置分流，把「明显 worker 造错」从「版本缺失」里摘出来、直接 reflow 而非 ask_user？
- **我的倾向**：加**前两档无红线信号**（`nearest_heads==[]` → 判 worker 垃圾走 reflow；`严格前缀 of 记载头` → 判截断走 reflow），保留「有头族但具体命令未记载」（如 `sdns fulldns on`）走现有 ask_user 版本缺失流。`sdns clear all` 这种**不加脑图溯源就判不了**——建议**暂不为它单独造判据**，让它继续走 ask_user（宁可多问一次，不越红线）。
- **反方**：① 把 worker 垃圾自动 reflow = 少一次用户确认，但如果 `nearest_heads==[]` 误判了一个真·孤儿新命令（版本新加、清单还没收录、又长得不像任何老命令），会被错误 reflow 掉——不过这与「清单抽取有截断上限」的现有逃生口（行级证据重 emit）叠加后风险可控。② 现状「改过程」选项本就等价 reflow 指令，改动收益主要是**题面不再误导 + 省一轮交互 + 去掉对垃圾命令荒谬的「挂起待版本」出口**，不是从 0 到 1。
- **需用户拍板的具体边界**：`sdns clear all` 类（合法头 + 编造子命令 + 不溯源脑图）——(甲) 继续 ask_user（我的倾向，守红线）；(乙) 引入「命令动词是否在脑图 step 出现」的溯源信号判 reflow（更省事，但碰领域推理红线，且中英匹配脆）。
- **优先级下调（trace 补证后）**：dongkl 里 worker 全都自纠了、门从没真呈给用户（1.2b），∴ **B2b 是潜伏风险不是活跃故障，优先级低于 B2a**。且 `s` 大概率是**载荷通道截断**（worker 推理里根本没这命令），若要治它，`token 长度<2 → 判残缺` 这条比「版本缺失」框架更贴切；但先把 B2a stale 清理做了，B2b 是否值得动可另议。

**【给用户的问题 P-C2b（次要）】** 即便判为 worker 造错走 reflow，`_gate_command_existence` 目前是 emit 期**硬拒落卷**（返回 error），reflow 由引擎 author 节点接。要确认：worker 造错的 reflow 是否要携「上一版命令未命中清单」的机读证据回 worker（防它同法再造），还是仅靠 author 的首败升深度（`rounds_used≥1` → max 思考 + 全历史 brief）就够。倾向后者（已有机制），但列出待确认。

### 3.3 块1（broken）——已落地，仅补两个收尾【非改设计，补锚 + 一个观察】

**§18.1 broken 全链无需改设计。** 两个收尾：
1. **补 210998 形态回归锚**（§18.7 纪律要求）：见第五节。
2. **【给用户的问题 P-C1（低优先，设计观察非 bug）】** broken 的处置固定是 rerun（复跑同卷面），但 210998 的 broken 根因是 **worker 编写缺陷**（空串 host + 前导-`\n` 过锚 pattern）。复跑同卷面必再产同 false_fail → 再 broken → streak=2 → escalated。即：window-distortion 检测器对**异质根因**（真采集偶发失真 vs worker 造的畸形命令/pattern）**一律路由 rerun**，对后者要烧 2 个设备轮才升级。
   - **我的倾向**：**不改**。理由：(44) 明令 broken **不深归因、不子分类**（避免假签名/误 frozen），这是理论要求的；单次复跑做消歧（也许真是偶发）+ streak≥2 升级，是有界且安全的。为「broken 来自编写缺陷就转 reflow」加判据，等于在 broken 上重新引入子分类，破坏 (44) 的短路纯粹性。
   - **反方 / 可选精化**：THEORY §2.12.3b + §2.13 已给外部锚——**pyATS 7 码结果代数**（`Errored>Failed>Aborted>Blocked`）。若将来要精化，正解是把 broken 按 pyATS 子码分（Errored=执行错→可 reflow / Aborted / Blocked=env→env_blocked），而不是临时加 if。属分期项，非本轮。
   - **列给用户裁决**：broken 处置维持「一律 rerun + streak 升级」（我的倾向），还是要为 window-distortion-from-authoring 开 reflow 快捷路。

---

## 第四节 · 理论对账

- **块1 与 THEORY_k §2.12.3b (43)(44) 完全一致**。理论：broken=⊥_err 吸收态 ≙ xUnit ERROR，「不计签名、不进深归因、不入交付分母」（THEORY 行 740-741、1184）。实现三处印证：sigs=`[]`（不计签名）、broken 后无 attribution（不深归因）、render.py `n_broken` 单列（不入分母）。THEORY 行 808-811 **已把 210998 写作「broken 第三态活实例…首次以显式 verdict 现身」**——理论已消费本实证，无冲突。
  - **可选理论补记（不改，仅指出）**：§2.13 表（行 801）已挂 pyATS 7 码作为 broken 子分类的现成锚，但 §2.12.3b 正文仍是「broken 单态」。若将来采纳 3.3 的精化，§2.12.3b 可加一句「broken 的子分类（Errored/Aborted/Blocked）沿用 pyATS 滚动优先级」——**当前不必**。

- **块3 属 A 层结构门**，无深理论，锚点就是「断言/命令结构合法性机械可判、判据来自协议物理常量（标签 ≤63 octet）」。修法是数据/正则面，**零理论变更**。

- **块2 触及 THEORY_k (40) 处置分类学 + (33) 版本参数化**。当前理论把「命令不在版本」笼统归为 version-gap 欠定，**未区分「环境缺失」与「编写缺陷」两个来源**。这与 Unit B/§18.14 「归因来源要机械可复核」同型——command_existence 也是一个「来源未被机械二分」的门。**指出（不改）**：(40) 处置分类学可增一条正交维度「欠定的来源 ∈ {环境缺失, 编写缺陷}」，编写缺陷走 reflow-不问用户、环境缺失走 ask_user——但此条落地依赖 3.2 的用户裁决（能不能机械二分）。

---

## 第五节 · 回归锚建议（供实现阶段用）

**块3（DNS lint，最确定、建议先落）**——现有 `test_xlsx_lint_gates.py:95 test_lint_catches_dns_label_over_63` 用 `www.` + `x`*120 + `.com`（**带白名单 TLD**），所以它绿着，真 bug 照样出厂。补：
```
# 文件: tests/ist_core/tools/test_xlsx_lint_gates.py
def test_lint_catches_dns_label_over_63_no_tld():
    # 994869 真实形态:裸长单标签,无点无 TLD
    G = "dig @172.16.34.70 " + "0123456789abcdef"*8 + " AAAA +noidnin"   # 128 单标签
    → 断言 lint 出 dns_label_over_63
def test_lint_catches_dns_label_over_63_host_name_no_tld():
    G = "sdns host name " + "a"*147                                        # 994838 r1 形态
    → 断言 lint 出 dns_label_over_63
```
双锚都必须在**修 `_DOMAIN_TOKEN_RE` 之前红、之后绿**（eval-first）。

**块1（broken 210998 形态锚，§18.7 纪律）**：
```
# 文件: tests/ist_core/tools/test_window_audit.py — 加 210998 形态 fixture
def test_false_fail_statistics_query_empty_host():
    # inner: show statistics sdns query "" all A → 框架判 fail(找不到 '\nA Record Statistics:')
    # apv:   对齐块含 'A Record Statistics: 1'
    → 断言 _window_audit 出 kind=false_fail, cmd 含 'show statistics sdns query'
# 可选 端到端锚(补 §18.1「报告单列分母」的产出物级空白):
# 文件: tests/ist_core/compile_engine_v8/test_broken_third_state.py
def test_report_totals_broken_separate_denominator():
    # 一批含 1 案终态 S_BROKEN → engine_report totals['broken']==1
    # 且该案不在 deliverable 分母、render 出「N 案未跑成」行
```

**块2 B2a（stale 台账清理，可直接落）**——现有 `test_command_existence_gate.py` 无此锚。补：
```
# 文件: tests/ist_core/tools/test_command_existence_gate.py
def test_clean_reemit_clears_stale_needs_decision():
    # 1) emit 含 'sdns fulldns on' → 门写 needs_decision(command_existence)
    # 2) 换成干净命令 re-emit(无 miss) → 断言该 autoid 的 needs_decision.json
    #    中 command_existence claim 被清(无其他 claim 则文件删)
```

**块2 B2b（契约锚，落地前置=用户裁决 P-C2）**——**先不写**，待用户定边界后按定稿写。预留形态（若采纳我的倾向）：
```
def test_single_char_garbage_routes_reflow_not_ask():   # 's'  → reflow,不进 needs_decision 版本缺失流
def test_truncated_prefix_routes_reflow():              # 'clear statistics sdns' (前缀 of 记载头) → reflow
def test_genuine_version_gap_still_asks():              # 'sdns fulldns on' → 维持 ask_user(版本缺失)
def test_plausible_invented_stays_ask():               # 'sdns clear all' → 维持 ask_user(守红线,不误 reflow)
```

---

## 附 · 数据事实 / 判断 / 待裁决 一览

| 项 | 类型 | 一句话 |
|---|---|---|
| 210998 fail→fail→broken 三轮迁移、broken 来自 window-audit false_fail（空串 host + 前导-\n pattern） | 数据事实 | verified_runs/facts.jsonl/sub3.last_run 三处铁证 |
| §18.1 broken 全链七款全落地 + 有测试锚 + 210998 真按设计路由 | 数据事实 | 逐条行级 + test_broken_third_state.py 等 |
| dongkl 运行被中断、无 engine_report → broken 单列分母缺产出物级实证 | 数据事实 | 目录无 engine_report.json |
| 210998 形态无专属回归锚（window_audit fixture 全是 run20） | 数据事实 | §18.7 纪律缺口 |
| 三案命令是 worker 造错/截断，非版本缺失 | 数据事实 | needs_decision × manifest 对照 |
| 三案 worker **同轮自纠**、门没真挡住（681811 r1 过 / 778041 r2 过），引擎**从未问用户**（0 ask 事实） | 数据事实 | trace_dumps + facts.jsonl + ND mtime 早于 xlsx 13s~3.3h |
| **B2a**：clean re-emit 不清 stale command_existence 台账（emit 677-678 提前 return）→ stale 残留误导 | 我的判断（活跃 bug） | mtime + facts=0 铁证；可直接修 |
| **B2b**：单信号门无法机械二分两来源（潜伏风险，非 dongkl 活跃） | 我的判断 | match_command 对垃圾/真缺失同型 hit=False |
| DNS lint 漏因 = `_DOMAIN_TOKEN_RE` 的 TLD 白名单锚 | 我的判断（行级） | structural_gate.py:1097 |
| DNS lint 修法：裸标签扫描 / 绑命令文法（结构化，不硬编） | 我的判断（修法） | 倾向裸标签扫描 |
| **P-C2**：command_existence 是否加结构化前置分流（垃圾→reflow）？`sdns clear all` 边界怎么划？ | 给用户的问题 | 倾向加前两档无红线信号，`sdns clear all` 守红线继续 ask |
| **P-C1**：broken 处置维持一律 rerun+streak，还是为 authoring-distortion 开 reflow？ | 给用户的问题 | 倾向不改（守 (44) 短路纯粹性） |

STATUS: done
