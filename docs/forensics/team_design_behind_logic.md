# dongkl 9 失败案：错误前提的思维链出生点 + 背后设计定位

> 方法：从 Langfuse `compile-worker` trace（158 条，07-14 后；本批 dongkl 9 案 × round1-3 全覆盖）抠出 worker **写断言前的真实 reasoning + 工具调用序列**，定位基线文档《dongkl_excel_quality_audit.md》第五节四个错误前提的**思维链出生点**（brief 注入 / 检索回来 / 模型自由脑补），再对每个前提逐条给「背后设计在哪、缺什么、file:line」。
> 证据源：`/tmp/lf_full_p{1,2}.json`（trace io）；设计定位交叉三个只读子 agent 采证 + 本人直读。
> 口径：Langfuse 只追踪主 agent 与**编写孔**；归因孔未进 Langfuse，故 fix_direction 原文从编写孔 brief 的 `<device_evidence>` 反读（它注入的是**上一轮**归因结论）。
> 整理：2026-07-16。全程只读，未改任何代码/配置。

---

## 零、先讲两条与基线文档的出入（证据优先，需团队复核）

抠 round1-3 编写孔 trace 后，发现基线第五节 **③、④** 两条的「病象定性」与编写孔实际产出/设备实况**对不上**。不是基线看走眼，更可能是基线取的是 `attr_evidence.json`（今早定稿 run 的**最终**证据），而我取的是编写孔 round1-3 的**逐轮**思维链与其 brief 内嵌的设备回显——两者若定稿 run 又换了形态就会分叉。如实标注，供团队用同一证据源对齐：

- **③ 593516「成员 IP 读错命令」**：round1-3 trace 里，worker **显式意识到** `show sdns host pool` 输出形态未知，并**猜了「p4」（池名）——猜对了**（见下 §三-③ 原文）。它没把成员 IP 225 拿去 `show sdns host pool` 找；225 断言落在 dig 输出 + `show statistics sdns pool p4`（都对）。**主失败=设备 p4 未进 WRR 轮转（defect_candidate，归因正确）**。基线③的「读错命令」在 round1-3 卷面不成立；但**根因缺口一致**（`show sdns host pool` 输出形态无判例，worker 只能猜，猜错猜对全凭运气）。
- **④ 572672/572708「wrr 缺 priority 被拒」**：round1-3 三轮用的都是 `sdns host method <域名> rr/wrr/ga`（**host 级方法命令，本就不带 priority**），trace 里**从未出现** `The priority must be an valid value…` 报错。真实设备实况=**该 build 静默接受 wrr/ga/删除但不生效（全留 rr）**，归因 `V/defect_candidate` 正确。基线④的「priority 缺参」在这两案 round1-3 卷面**无据**；「priority must be valid」字样存在于**判例层 `70b32add`（ga 变体、`sdns host pool` 绑定命令）**，与本二案的 `sdns host method` 是**两条命令**，疑似被基线并读。

下面四节仍按基线四条前提的**编号与主题**展开，逐条给出生点 + 设计定位 + 分类；③④处标明「基线定性 vs trace 定性」的分叉。

---

## 一、错误前提①：跨客户端轮转（客户端1→pool1、客户端2→pool2 共享全局计数）

### A. 思维链出生点 = **brief 的 `<intent>` 逐字注入 → worker 自建「全局确定计数」模型自证**

**出生点第一跳：脑图作者预期，引擎逐字注入。** 4 个相关案（777976 rr / 593484 wrr / 593516 wrr / 681749 ga）的 `<intent>` 全部内嵌脑图原文：

```
777976: 使用客户端1发送1次请求 → expected: 命中第一个pool
        使用客户端2发送1次请求 → expected: 命中第二个pool
593484: 客户端1发3次 → 命中3权重pool ；客户端2发2次 → 命中2权重pool
```

引擎侧：`briefs.py:175` `intent = intent_summary(aid, state)` → `briefs.py:177-178` 原样包进 `<intent>`，**无任何分布前提净化**。「客户端2→第二个pool」这个**跨客户端共享轮转**的假设是脑图作者写的，引擎机械穿透给 worker。

**出生点第二跳：worker 把该预期合理化成一个错误的确定性模型。** 777976 编写孔 reasoning 原文（round1）：

> **Test Point: With sdns host method set to rr, the round-robin algorithm rotates through 3 pools in order. The 1st query hits pool p1 and the 2nd query hits pool p2.**

round2 更进一步、并**主动排除了分布采样的顾虑**：

> when only sending 2 requests with 3 pools in round-robin, **each pool gets exactly 1 hit deterministically, so this isn't really a distribution scenario at all.**
> The round-robin counter increments for every DNS query regardless of type, so I can calculate exactly where each request lands.

即 worker 构造了「RR=一个全局计数器，每来一个 query（不分来源客户端）+1」的心智模型，据此推出「query1→p1、query2→p2」，并**明确判定「这不是分布场景」**，从而给自己用 `abs_found IP + Hit:\s+1` 精确断言开了绿灯。**777976 三轮全程未调用 `compile_check_verifiability`**（工具普查证实）——它根本没让自己的 claim 过可证伪性闸。

**设备把前提双重证伪**：593484 三轮 RouterA 3 次 dig 全 →.213、RouterB 2 次 dig 全 →.213；只有 p1 有 Hit。round3 subset 归因原文：`SDNS WRR load-balancing algorithm does not rotate pool selection… all traffic goes to pool s1`。即本 build **① 根本不做逐请求轮转（全落首池），② 两客户端无差异**——脑图「client2→pool2」在两个层面都不成立。

**更深一层（项目自审已破译，`AUDIT_engine_gaps_round2.md:65`）**：脑图作者「客户端2→第二个pool」的**真实机制很可能是地址族路由**——三池=v4池+v6池+混合池，客户端2 发 **AAAA 查询** → 应答只能携 IPv6（协议事实）→ v6 池是唯一候选 → 「命中第二个池」是**确定性行为、与 rr 起点无关**。也就是说这个前提**本不该被建模成轮转**：worker 把它读成「全局 RR 计数器 query2→p2」是**丢了「查询类型×池地址族→候选池过滤」这一维**，而 `verifiability.py` 的入参谱系同样没有这一维（见 B 表）。对纯权重案（593484/681749，无地址族区分）则连这条确定性救援都没有，是真·分布欠定。**结论不变、且更硬**：① 是 verifiability 维度模型的缺口，不是 worker 一时脑补——项目已自审但该维仍未补进 `check_verifiability` 签名。

### B. 设计定位

| 设计位点 | 该管这个判断的地方 | 现状 | 分类 |
|---|---|---|---|
| worker 提示 `compile-worker.md` | L92-96 明确「'which pool does request N land on' 是 distribution claim…reads presence, not participation-rate…falsify with `compile_check_verifiability`」；L84/L102「deterministic-mapping / no h → 固定落点合法」 | **有分布指引，但缺跨客户端维度**，且给了逃逸口：worker 把「rr 位置序列」自认成 deterministic（L84/L102 的 GA/no-h 措辞可被套用），从分布闸下溜走。**全篇无一句**「两个触发客户端不必然共享全局轮转计数」 | **设计错误（含糊 + 有逃逸口）** |
| brief 注入 `briefs.py:175-178` | 意图注入点 | 脑图预期**逐字穿透**，不做分布前提标注/净化（设计上正确——意图是需求不该被引擎改写；但意味着**错误前提必然到达 worker**，全靠 worker 自查） | **设计未强制**（注入无过滤，防线全压在下游 worker + 闸） |
| `verifiability.py` claim 谱系 | 本应表达/证伪「跨客户端共享计数」 | `check_verifiability` 入参 `verifiability.py:92-100` **无「客户端数/哪个客户端」维度**；工具壳 `verifiability_tool.py:126-128` 把 n_requests 规定为「同一候选池集合内单组聚合轮转」；8 个 claim_kind（`:35-44`）无一涉及多客户端计数器共享。项目自审 `AUDIT_engine_gaps_round2.md:65` 已认此缺口 | **未设计**（模型里根本没有这一维） |
| 判例层 `footprints/nodes/` | 本应有「双客户端轮转行为」观察 | 2401 节点**零命中**；唯一沾边 `statistics.sdns.pool.json` 的 `6b921beb` 是**单客户端**（仅 RouterA）WRR 进度观察，从未记两客户端计数是否共享 | **未设计**（判例层没种进去；worker 无论怎么查 kb_footprint 都取不到） |
| emit 门 `structural_gate.py`/`emit_xlsx_tool.py` | 本应拦「写死成员IP钉确定轮转序列」 | 无任何门校验轮转序列与周期自洽；`validate_membership`（`membership_assertion.py:68-83`）只查 ip 像 IP、present 是 bool，且**仅当 worker 声明 `F="member"` 才触发**，raw `abs_found` 直穿 | **设计未强制**（正确形态是可选声明非强制门） |

---

## 二、错误前提②：Hit 计数器依赖（大量断言压在 `Hit:\s+N` 上）

### A. 思维链出生点 = **worker 把「命中」操作化成 Hit 计数（先例播种）+ footprint 无输出形态知识 + 归因误注入加固**

**第一跳：意图「查看命中哪个pool」被 worker 操作化为 `show statistics … pool` 的 `Hit:N`。** 593516 编写孔 round1 reasoning 原文——出处是**检索回来的先例**：

> From the precedent: `check_point found: Hit:\s+1` / `check_point found: 1.1.1.1`. So the output has a "Hit: <count>" line and the service IP.

593516 round2 更暴露**判例层没有该命令的输出形态、worker 只能沿用先例形态**：

> The footprint for `show statistics sdns pool` is minimal: CLI commands (1): show statistics sdns pool p1. **No output format documented.** But the R1 case's assertions … suggest the output contains "Hit:" and the service IP. **I'll trust the R1 case's assertion form.**

**第二跳：设备回显 `Hit:0` 时，worker 采信了引擎注入的错误归因（甩锅步序），而非质疑计数器本身。** 777976 round2 reasoning 原文：

> The real issue is that **R1 ran `show l p2` before dig traffic, so Hit was 0. If I fix the step ordering** to send dig traffic first, then run the show command, **it should return Hit: 1.**

这条「Hit:0 是因为在打流量前 show」正是 brief 里注入的 `<fix_direction>`（reflow/V 归因）原话——引擎在 `briefs.py:78`（`[:800]` 截断）把上一轮归因当权威注入。worker 顺着它把 Hit:0 解释成时序 bug，从未怀疑「设备返回了成员却不计数」这条更根本的计数器不可靠。

### B. 设计定位

| 设计位点 | 该管的地方 | 现状 | 分类 |
|---|---|---|---|
| worker 提示 `compile-worker.md` | L79-83 教 `dist` 组合子「从 live 输出读字段名」防写死拼写；L87-88「统计命令来自 footprint/manual」 | **假设计数器可靠**：全篇无一句「Hit 计数器可能返回成员却不涨/Hit:0」；且 `dist` 只是**推荐非强制**——worker 直接 raw `Hit:\s+1 found`，绕过 | **未设计**（计数器可靠性维度缺）+ **设计未强制**（dist 不强制） |
| brief 注入 `briefs.py:78` + guardrail `:125-128` | fix_direction 注入 + 「先独立质疑归因」护栏 | 上一轮**可能错的**归因被 `[:800]` 原样注入、措辞权威（"device behavior is correct — issue is framework step sequencing"）；护栏只是 C 层软话，777976 R2 实测被 worker 直接采信 | **设计错误**（错误归因当权威注入，护栏太弱） |
| 判例层 `footprints/nodes/` | 本应有「Hit 返回IP却Hit:0」观察 | 零命中，且**现存 3 条 Hit 观察全指相反方向**（`6b921beb`「三池Hit均>0」、`68d00a54`「跨阶段累计过计Hit:8」）——判例层现有知识会让 worker 更信计数器，不会警惕它 | **未设计**（且现有判例方向相反，有误导性） |
| verifiability / emit 门 | — | 见①：分布断言可证伪性只在声明 claim_kind/F=dist 时生效；能识别 `Hit:\d+`/`Hit:\s+1` 精确 vs 区间的分类器 `grade_extract_script.py:169-183` 是**已删 grade 子系统的死代码**，未接入 v8 活路径 | **设计未强制**（有能力但死代码/可选） |

---

## 三、错误前提③：成员 IP 用错 show 命令（593516）

> 基线定性：把成员 IP 225 拿去 `show sdns host pool`（只列池名）找。**trace 定性**：worker 猜「p4」（池名）猜对了；主失败是 p4 未进轮转（defect）。根因缺口相同（该命令输出形态无判例）。

### A. 思维链出生点 = **worker 在「输出形态未知」下自由猜测（承认不知道，猜了）**

593516 round1：worker 对 clean 设备 dev_probe 了 `show sdns host pool`，原文：

> The `show sdns host pool` returns **empty output (just the prompt)**. This makes sense because there's no host-pool binding configured on the clean device.

——**探针在 clean 设备上无信息**（还没绑定，命令输出空），worker 学不到真实输出形态。round2 直接承认不知道、并**掷硬币**：

> **Actually, I realize I should also check if the `show sdns host pool` command shows the pool name or the service IP.** If it shows the pool name, checking for 'p4' would work. If it shows the service IP, I should check for '172.16.35.225'. **Without knowing the exact format, I'll check for 'p4' as a safe bet.**

即出生点是**模型自由判断（承认不确定后猜测）**，不是 brief 注入也不是检索回来（检索/探针都没给出输出形态）。这次猜对了池名；换个案/换一轮就可能猜成成员 IP——基线③描述的形态正是这枚硬币的反面。

### B. 设计定位

| 设计位点 | 该管的地方 | 现状 | 分类 |
|---|---|---|---|
| worker 提示 `compile-worker.md` | L104-108「layout 用 dev_probe 确认…the command's line/column shape shows even on the clean compile-time device」（667986 反例） | **指引有洞**：前提「clean 设备就能看出形态」对 `show sdns host pool` 这类**输出依赖前置配置**的命令不成立（clean 设备输出空），worker 照做拿不到形态，被迫猜 | **设计错误**（指引的可行性前提在此类命令上失效） |
| 判例层 `footprints/nodes/` | 本应记 `show sdns host pool` 输出「只列池名不列成员IP」 | `sdns.host.pool.json`/`sdns.host.json`/`show.sdns.json` **无任何输出形态设备观察**，只有手册抄来的泛化描述；`show.sdns.json` 的 decision_rules/behaviors/known_issues **全空** | **未设计** |
| emit 门 | 本应拦「断言目标形态 ≠ 来源命令实际输出形态」 | **无命令→输出 schema 模型**；最近的 `_check_assertion_matches_command_echo`（`structural_gate.py:785-838`）方向**相反**（查 pattern 命中命令原文=恒真），225 不在命令串里→不触发；唯一输出形态门 `_check_short_mode_assertions`（`structural_gate.py:909-932`）只硬编码 `dig +short` 一对，无法推广 | **未设计**（门层对命令输出形态零建模） |
| 检索机制 `footprint_lookup.py:210-244`/`index.py:141` | 让 worker 查中输出形态 | 按点分命令前缀精确/模糊匹配，无按意图跨命令语义 join——即便有观察也散在多节点难召回；此处是**根本没有可召回的观察** | **未设计** |

---

## 四、错误前提④：wrr 缺 priority（572672/572708）

> 基线定性：wrr 漏 priority、配置被拒。**trace 定性**：用的是 host 级 `sdns host method`（不带 priority），设备静默接受 wrr/ga/删除但不生效（defect_candidate，归因正确）。基线「priority」字样疑似并读了判例层 ga 变体观察。

### A. 思维链出生点 = **intent 对参数只字未提 → worker 按先例形态编写（形态正确）；真失败是设备缺陷，worker 归因正确**

572672 intent 仅：`配置多个域名关联服务池配置 / show sdns host method查看配置→配置正确`（**无 priority、无算法细节**）。worker 三轮 emit 的配置命令始终是：

```
sdns host method autotest1.com rr
sdns host method autotest2.com wrr
sdns host method autotest3.com ga
```

**无 priority 参数**（host 级 method 命令本就不带），trace 三轮也**无 "priority must be valid" 报错**。worker round3 reasoning 已**正确诊断设备缺陷**：

> **The firmware is silently accepting the method changes but not applying them.** If I switch to batching all three method commands in a single cmds_config block … and the device still shows all "rr", that would confirm the firmware defect.

这是引擎 `briefs.py:169-173` 的 defect-certify round_task（「换一种 config form 复现以证缺陷」）在起正作用，worker 照做——**④ 在 trace 里不是 worker 的错误前提，是被正确处理的设备缺陷**。基线所指「priority must be valid」出自判例层 `sdns.host.pool.json` 的 behavior `70b32add`（**ga 变体、`sdns host pool` 绑定命令**：`The priority must be an vaild value when the SDNS host method is 'ga'`），与本二案的 `sdns host method` 是两条命令。

### B. 设计定位（针对「若确有 wrr→priority 参数依赖需求」这一泛化缺口）

| 设计位点 | 该管的地方 | 现状 | 分类 |
|---|---|---|---|
| 文法层 `domain_grammar.json` | 本应有「算法↔参数依赖」条目（wrr/ga→必带 priority/weight） | 19 个顶层类**无参数依赖类目**；唯一算法相关 `algorithm_classes`（`:143-153`）只是扁平 `distribution.methods`，`wrr` 全文件仅 `:147` 一处；`priority` 出现处全是 inverse_forms 命令名，无一条是算法↔参数约束 | **未设计** |
| 加载器 `case_compiler/domain_grammar.py` | 决定新增该规则是否零代码 | 每个类目配硬编码键路径专用 accessor；零代码通道只有 reference_closures/anchoring_chains/持久通道/床探针（docstring `:10-12`）。「wrr→priority」是**带前件的条件共现约束**，无现成 schema 容纳，`dangling_references()` 的无条件名字集合可达性也表达不了——**须新 JSON 段 + 新检测器，非零代码** | **未设计**（且非零代码可补） |
| 判例层 `footprints/nodes/` | wrr priority 观察 | **有覆盖**：`sdns.host.pool.json:94-101` 手册规则（作用域含 wrr：`wrr/ga 时 weight/priority 参数可用`）+ 设备实证 `70b32add`（`:151-153`，ga 变体、标注「ga/wrr 都必填」）。worker 查中 `sdns host pool` 即可召回 | 覆盖存在，但**渲染 `rest_behaviors[:3]` 配额**有挤出风险；且**跨命令**（该规则在 `sdns host pool` 节点，本二案用 `sdns host method`，语义 join 缺位）→ **设计未强制/难召回** |
| emit 门 | 「wrr 配置必带 priority」完整性门 | 无。`_gate_command_existence`（`emit_xlsx_tool.py:648-781`）只判命令头存在、不判参数必填 | **未设计** |
| worker 提示 `compile-worker.md` | L54-57「config 每个元素溯意图或其依赖链」 | 依赖链需 worker 自己从 footprint/manual 查出「wrr→priority」；intent 没写、grammar 没有→**只能靠判例召回**，无兜底 | **设计未强制** |

---

## 五、总分类矩阵（错误前提 × 设计位点）

图例：**未**=未设计（自由判断无指引） / **错**=设计错误（指引有但错或含糊/有洞） / **弱**=设计未强制（有指引无门/无数据/可选） / — =不适用 / ✓=该处设计其实正确

| 设计位点 \ 前提 | ①跨客户端轮转 | ②Hit计数器 | ③错命令(输出形态) | ④wrr参数依赖 |
|---|---|---|---|---|
| worker 提示 compile-worker.md | 错（缺维+逃逸口 L84/L92-102） | 未+弱（L79-88 假设计数器可靠、dist 不强制） | 错（L104-108 探针前提失效） | 弱（L54-57 依赖链靠自查） |
| brief 注入 briefs.py | 弱（:175-178 意图逐字穿透无过滤） | 错（:78 错归因当权威注入；:125-128 护栏弱） | — | ✓（:169-173 defect-certify 正起作用） |
| verifiability.py 谱系 | 未（:92-100 无客户端维；:35-44 八 kind 不涉共享计数） | 弱（分布可证伪仅声明时生效） | — | — |
| domain_grammar.json 文法 | — | — | — | 未（无参数依赖类目 :143-153，补它非零代码） |
| footprints 判例层 | 未（2401 节点零命中） | 未（且现存观察方向相反，误导） | 未（输出形态无观察） | 弱（有据但跨命令难召回 :94-101/70b32add） |
| emit 门 structural_gate/emit_xlsx_tool | 弱（member 校验仅声明触发） | 弱（Hit 分类器 :169-183 为死代码） | 未（无命令→输出 schema） | 未（无参数完整性门） |

**读表要点**：
1. **①②③ 的判例层全是「未」**——2401 个 footprint 节点里，「跨客户端轮转 / Hit 漏计 / show sdns host pool 输出形态」**根本没种进去**（②现有观察还指反方向）。这不是「worker 检索机制够不着」，是**知识树里压根没有**。自愈合四层架构里「判例层是唯一无限增长层」，但这三类坑从未被写回——**上机暴露的正是它们，却没有 `_ingest_uncertain_observations` 把它们沉淀成下一批可召回的观察**。
2. **verifiability.py 对 ① 是「未设计」的硬缺口**（无客户端维度，项目自审 `AUDIT_engine_gaps_round2.md:65` 已认），对分布可证伪性是「弱」（`F=dist`/claim_kind 声明才生效，777976 全程没调）。
3. **emit 门对四类全「未/弱」**：门集设计红线明确把「配置语义/命令输出语义」这类领域判断留给 worker LLM（`structural_gate.py:8-9`、`distribution_assertion.py:13-15`、`membership_assertion.py:23-25`），门只拦与意图无关的结构崩溃。正确形态 `F=dist`/`F=member` 是**可选声明非强制门**——worker 不用就零兜底。
4. **worker 提示是唯一四类都触及的位点，但全是「错/未/弱」**：分布指引存在却①缺跨客户端维、还留了「deterministic→固定落点合法」的逃逸口让 worker 自认成非分布；③的「clean 设备就能探出形态」前提对输出依赖前置配置的命令失效。
5. **brief 注入对 ② 是「设计错误」**：上一轮**可能错的**归因（reflow 甩锅步序）被 `[:800]` 权威注入，`briefs.py:125-128` 的「先独立质疑」护栏是 C 层软话，777976 实测被 worker 直接采信、延误收敛。

---

## 六、一句话结论

四个错误前提的出生点分三类：**①=brief 逐字注入脑图预期（`briefs.py:175-178`）+ worker 自建「全局确定 RR 计数器」模型自证（777976 全程未过 `compile_check_verifiability`）**；**②=worker 把「命中」操作化成 Hit 计数（先例播种、footprint 无输出形态）+ 引擎把错归因当权威注入加固**；**③=输出形态无判例，worker 承认不知道后自由猜测（这次猜对池名，基线③是硬币反面）**；**④=intent 未提参数、文法层无算法↔参数依赖类目，但 trace 里真失败其实是被正确归因的设备静默缺陷（基线④的 priority 定性存疑）**。设计账：**判例层对 ①②③ 是彻底空白**（2401 节点零对应观察，②现存观察还指反方向），是最该补的一环——上机反复暴露却没沉淀回判例；`verifiability.py` 缺客户端维度是 ① 的硬缺口（项目已自审）；emit 门与正确形态声明对四类全是「可选非强制」，worker 一旦自认「非分布/确定性」即零兜底。
