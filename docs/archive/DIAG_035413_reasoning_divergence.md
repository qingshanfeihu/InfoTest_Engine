# 035413「本地域名命中回退池」上机失败——LLM 推理分歧点全回溯

> ⚠️ **历史存档（2026-07-17 归档,team4 docs 整编）**：035413 单案取证(DESIGN_grade_grounding 证据链,随其同归档)。事实存档不删,现状勿引本文。

> 数据源：LangSmith project `infotest_engine`，2026-07-07 CNAME 编译三轮全 trace。
> 目的：钉死**哪个 agent、哪一轮、哪一步推理**把配置带偏，区分主次。全程只读分析、不改代码。

## 用例意图（manifest 原文）

- autoid `204651759025035413`，标题「本地域名命中回退池情况」，group_path `["84938 CNAME pool支持ipo算法","本地域名"]`。
- 过程：① 配置 cname 为本地域名，cname pool 算法 ga ② 本地域名配置服务池，server 为 disable ③ 配置回退池 + fallback 服务池 ④ 客户端请求 A/AAAA → **预期：返回本地域名 fallback 服务池对应的 service ip**。

**被测功能**：主服务池 disable 时，A 查询命中回退池、**返回一个 IP**。

## 三轮链路 + 每步 LangSmith 原文

### R1-worker（08:19，trace 019f3ba9…）——★根错在此

产出配置骨架：
```
sdns host name www.a.com 60
sdns pool cname name cname
sdns pool cname member cname cname.a.com
sdns host pool www.a.com p_main        # 服务池挂 www.a.com
sdns host pool www.a.com cname         # cname 池也挂 www.a.com
sdns pool fallback p_main p_fb
```

**它建立了一个错误的数据流心智模型（reasoning 原文）**：
> *"www.a.com → cname pool (GA) → returns cname.a.com; **cname.a.com is local → re-query → host www.a.com → p_main**"*
> *"the cname.a.com re-queries to the SDNS system, and **since the host www.a.com is also bound to p1, the re-query hits p1**"*

**错误假设**：它认为 cname 池返回 `cname.a.com` 后，客户端「重新查询」`cname.a.com` 会**绕回到 host www.a.com 的服务池**（p_main→p_fb），于是返回 IP。基于这个假设，把服务池 + cname 池都挂到同一个 www.a.com 就「能通」。

**设备实际否定了这个假设**（同轮 dig 回显）：
```
dig @172.16.34.70 www.a.com A +short → cname.a.com.
```
A 查询**死在 cname.a.com**，没有绕回 www.a.com、没有命中 fallback、没有返回 IP。`cname.a.com` 没有自己的 host/pool、也不会回流到 www.a.com——worker 的「re-query → www.a.com」是虚构的。**被测功能（返回 fallback IP）从这一刻起就没生效。**

### R1-attr（08:28，trace 019f3bb1…4697）——看到症状、没抓根错

- layer=**V**，disposition=reflow。
- evidence（原文引用）：`dig … www.a.com A → cname.a.com.` ← **它确实看到了 dig 返回 cname 字符串而非 IP**。
- fix_direction 全文：
  > *"设备在 p_main 无可用服务时未按 fallback 规则使用 p_fb，而是通过 CNAME 池返回了 cname.a.com。修法：(A) 检查是否缺少 `sdns host method www.a.com ga` 导致池选择顺序异常——对照 PASS 的 608（有 host method ga，CNAME 被正确抑制），补上 host method 后重跑；(B) 若仍复现则产品缺陷、冻结。"*

**分歧点**：R1-attr 看到了正确症状（dig=cname.a.com≠IP），但**没质疑 worker 的「cname.a.com 绕回 www.a.com」心智模型**，而是把问题归成「cname 池该被抑制」，修法＝「加 host method ga 让 GA 抑制 cname 池」。它接受了 www.a.com 的错误骨架、只治表面（抑制 cname 池），没碰「域名接不上」的根。

### R2-worker（08:36）——照 fix 加 host method ga

依 R1-attr 补 `sdns host method www.a.com ga`。骨架不变（仍全挂 www.a.com、cname 池成员仍 cname.a.com、仍无 cname.a.com 的独立解析）。

### R2-attr（08:43，trace 019f3bbf…）——注意力被 priority 完全劫走

host method ga 触发新拒绝：`sdns host pool www.a.com p_main` → *"The priority must be an vaild value when method 'ga'. Failed to execute."*
- layer=**G**，fix_direction **全篇只讲 priority**：*"host method ga 下 priority 必填…改成 `sdns host pool www.a.com p_main <priority>`"*。
- **它没有再回看域名/cname 接线**——响的语法拒绝（priority）盖过了哑的功能失效（dig=cname.a.com）。

### R3-worker（08:48，max 思考，trace 019f3bc3…）——补 priority，根错依旧

补 priority、绑定成功、配置能下发。但骨架心智没变（reasoning 仍在 GA/priority/suppression 里绕：*"with GA on cname pool, and p_main disabled, what happens?"*），仍无 cname.a.com 独立解析。终验 dig 仍返回 cname.a.com → **fail，升级人工**。

## 主次判定（数据锁定）

| | 主问题 | 次问题 |
|---|---|---|
| 内容 | **域名接不上**：cname 池成员 cname.a.com 不会绕回 www.a.com，A 查询死在 cname 字符串，fallback 从未触发（功能没生效） | ga 下 host pool 缺 priority |
| 性质 | 语义/功能：配置是否实现意图 | 语法：inter-parameter 依赖 |
| 设备反应 | **静默接受**，只在运行时 dig 结果暴露 | **配置期当场拒**（响） |
| 起源 | **R1-worker 的「re-query 绕回 www.a.com」错误心智模型** | R1-attr 建议加 host method ga 的**副作用** |
| 为何漏 | R1-attr 治表面（抑制 cname 池），未质疑心智；R2 起 priority 劫走注意力 | — |

**结论**：终极上机失败的主因是 **R1-worker 一个具体的 SDNS 心智错误**（cname 池返回值会绕回原 host 的服务池），导致 cname.a.com 与 www.a.com 接不成能返回 IP 的链路——功能压根没生效。priority 是次要问题、且是 R1-attr 抑制建议的副作用。**主次颠倒发生在两处**：① R1-attr 用「抑制 cname 池」的表面修法盖过了「域名接不上」的根；② R2 起「配置期语法拒绝(priority)」盖过了「运行时功能失效(dig=cname.a.com)」。

## 正确配置——设备实证（2026-07-08，serial console cu ttyS0，routera/跳板机 dig）

在真设备（Beta.APV-HG-K.10.5.0.585）上逐个构造实验，dig 验证：

**实验 A（纯 pool-level fallback，无 cname）**——`sdns pool fallback pm pf` + host 只绑 pm，disable pm 的服务：
`dig cvt.a.com A` → **No answer**（域名 status 却显示 UP）。**pool-level `sdns pool fallback` 不让 A 查询回退到次池。**

**实验 B（host 级双池 + ga + 优先级）**——`sdns host method ga` + `host pool cvt.a.com pm 10` + `host pool cvt.a.com pf 1`，disable pm 的服务：
`dig cvt.a.com A` → **172.16.35.231（次池 IP）✓**。**回退的正确机制＝host 级双池 + host method ga + 优先级**（主池服务 disable → ga 选下一优先级可用池）。

**实验 C（完整正确拓扑：cname.a.com 才是本地域名）**：
```
sdns service ip s1 172.16.35.213 / sdns service ip s2 172.16.35.231
sdns pool name pm / sdns pool service pm s1
sdns pool name pf / sdns pool service pf s2
sdns host name cname.a.com 60            ← ★cname.a.com 配成本地域名(worker 从没做这条)
sdns host method cname.a.com ga
sdns host pool cname.a.com pm 10         ← 服务/回退池挂 cname.a.com(不是 www.a.com)
sdns host pool cname.a.com pf 1
sdns pool cname name cn / sdns pool cname member cn cname.a.com / sdns pool method primary cn ga
sdns host name www.a.com 60 / sdns host pool www.a.com cn   ← www.a.com 只经 cname 池指向 cname.a.com
sdns service disable s1
```
dig 结果：
```
dig www.a.com A →
  www.a.com.    IN CNAME cname.a.com.
  cname.a.com.  IN A     172.16.35.231     ← 回退池 IP，正是意图「返回 fallback 服务池 IP」
dig cname.a.com A → 172.16.35.231
```
**完整链通了**：www.a.com →cname池→ cname.a.com（本地域名，主池 disable→ga 回退次池）→ 172.16.35.231。

## worker 的错 vs 正确配置（设备实证对照）

| | worker 配置（上机 fail） | 正确配置（实验 C，dig 通过） |
|---|---|---|
| cname.a.com | 只是 cname 池的一个**成员字符串**（无 host、无池） | **配成本地域名**：`sdns host name cname.a.com` + 自己的服务池(disable)+回退池+ga |
| 服务/回退池 | 挂 **www.a.com** | 挂 **cname.a.com**（cname 指向的那个真本地域名） |
| www.a.com | 同时挂了服务池 + cname 池 | 只挂 cname 池 → 指向 cname.a.com |
| 回退机制 | `sdns pool fallback`（实验 A 证明**不生效**） | host 级双池 + ga + 优先级（实验 B 证明生效） |
| dig www.a.com A | `cname.a.com.`（死在此，无 IP） | `cname.a.com. → 172.16.35.231`（回退 IP）✓ |

**用户的质疑完全正确**：「你 cname 配置的是 cname.a.com，那 sdns host pool www.a.com 怎么能配置 www.a.com？」——服务/回退池必须挂在 **cname.a.com**（cname 指向的本地域名），worker 却挂在 www.a.com，且**从没 `sdns host name cname.a.com` 把它配成本地域名**。「配置 cname 为本地域名」这句意图，字面就是要 `sdns host name cname.a.com`——worker 一次都没做，这是功能没生效的根。

## worker 心智错的确切内容（设备实证后精确化）

R1-worker 的虚构假设「cname.a.com is local → re-query → **host www.a.com** → p_main」——错在把 re-query 的落点接回了 www.a.com。设备实证：re-query 的落点是 **cname.a.com 自己**（它必须是个配好的本地域名才能解析）。worker 缺的正是「把 cname.a.com 配成本地域名 + 在它上面配服务/回退池」这一整块——它以为 www.a.com 的池能替 cname.a.com 兜底，设备证明不能。

## LLM 的神秘问题——结论与原因（LangSmith + 设备实证走完后）

**结论（一句话）**：LLM 没有「不知道」，它是拿一个**自己编的、内部自洽但事实错误的产品行为模型**当成真相，且**在产出交付物之前从没拿它对设备验证过一次**。

**它手里该有的都有、却都没用**：① 意图原文（「配置 cname 为本地域名」）它读了还引用了；② footprint 决策规则明写「待查询域名关联别名池时会按 CNAME 重新查询、结果只与 CNAME 关联的策略有关」（字面就是说 cname.a.com 要有自己的配置）；③ dev_probe 能现场问设备。三样都指向正解，它一样没用，选了脑补模型。

**原因（三层）**：
1. **反直觉机制 + DNS 先验反向误导**：正常 DNS 里 CNAME 指向别处、不会把目标配成本地；SDNS 里 CNAME 目标**必须**是本地域名才解析。LLM 的 DNS 常识主动把它带偏。
2. **意图是压缩的**：「配置 cname 为本地域名」= `sdns host name cname.a.com`，LLM 读到却映射成了自己的模型、不是那条字面动作。
3. **全流程没有一步逼它「落地前先验模型」**：worker 照内部模型直接 emit，只有昂贵上机才碰它；上机 fail 后 attributor 又用同一个错模型解读、补表面症状（priority），永远绕不出错模型。

## 业界解法：grounding-before-commit（产出前一致性门）——联网调研 2026-07-08

- **失败模式有名字**：EnvSimBench 称之「fabricating incorrect state transitions（编造错误状态转移）」——worker 编造了「www.a.com A→绕回 www.a.com→fallback IP」这个虚构转移。
- **GILP（arxiv 2606.27806）机制同构**：产出前把 LLM「想象的状态变化」与 ground truth 比对，分歧大就当场带**具体分歧**再提示让它改（真机 -80% 幻觉率）。
- **我们的处境比论文更好**：GILP 用**学出来的近似世界模型**（只因「真环境查询太贵」）；**我们的真设备 3 条 dig 就能查**（dev_probe）——直接用 oracle 本身 grounding，无近似误差。手动三实验（配→dig→对意图）就是这个 grounding。
- **两条量化结论砸中我们**：① grounding-before-commit **完胜 post-hoc 验证**（GILP 0.838/15k token vs 事后 verifier 0.684/26k token）——**量化证明 rework 环是错的层，修复属产出前**；② **选择性 grounding**（只在假设新颖/不确定/高风险时验，~22% 步、20-30% 开销、80% 收益）回答「会不会太贵」。
- **Tool Receipts（arxiv 2603.10060）**：每个行为断言要有工具凭证背书；worker 的「绕回」断言零凭证，一条 dev_probe 就证伪。
- **方向**：worker emit 前，把配置依赖的关键行为假设（「这条查询会不会按我想的解析」）拿设备验一次，否了带具体分歧重想。唯一开放设计点＝**选择性触发信号**（GILP 靠模型分歧、我们没学习模型、触发信号另设）。

## 两层结构 + 全局一致性 + 注意力劫持（2026-07-08 二次联网深挖）

**命令下发分两层，是两个本质不同的验证问题：**

| 层 | 性质 | 能被什么验证 | 状态 |
|---|---|---|---|
| **参数层**（priority） | **局部**：单命令单参数、inter-parameter 依赖（手册可选/特定命令必选） | 单命令设备反馈（`?`/错误消息）——局部检查够 | ✓ 已解 |
| **命令层**（上下文配置不一致） | **全局**：跨命令引用完整性 / 场景闭合 | **可证明无法靠逐命令/成对检查发现**（arxiv 2601.13600：pairwise 不足以保证 global coherence，需整份配置做全局一致性检查、找最小不一致子集 MUS） | ← 根因、未解 |

即：priority 那种「看单条命令」永远查不出「cname.a.com 在 cname 池被引用、却没配成 host」这种**跨命令引用不闭合**——它是整份配置作为**引用图**才暴露的属性（cname.a.com＝未定义符号、解析链死在此）。

**「小问题劫持专注力」＝命名了的失败模式 Attention Hijacking**（arxiv 2503.08216）：注意力被误导到显著但无关处、忽略本质细节。机制＝注意力是**有限、按显著性分配**的资源：
- priority 拒绝＝**响**（设备一行明说、单点）→ 赢注意力。
- 域名不自洽＝**哑**（无单条命令错、不一致分布在整份配置、只运行时显形）→ 输。
- **loud-local 结构性碾压 quiet-global**——不是偶然，是注意力机制的系统性偏置。priority 一出现就吸走全部处理量，域名不自洽连被考虑的机会都没有。

**深化结论**：
1. 两问题两套机制，**不能靠「把某步推理做好」解全局**——被劫持的恰是那步推理。
2. 全局一致性必须是**独立、隔离、抗劫持的一遍**（只干「整份配置引用图自不自洽/闭合」），否则被任何 loud-local 挤掉。形态＝配置图「链接器」（查悬空引用：cname.a.com 被引用却无 host 定义）+ 场景闭合（解析链是否真产出意图要的可观测）。
3. 这个全局检查正是 grounding 的落点：整份配置的「解析链假设」＝该在产出前拿设备验的东西（手动三实验验的就是这个全局闭合）。

## 三洞察结合进引擎（worker / grade / attributor）——2026-07-08

**当前三角色真实分工（代码确认）**：
| 角色 | 时机 | 当前干什么 | 性质 |
|------|------|-----------|------|
| worker（LLM 孔①） | 产出前 | 产出配置+断言 | 错模型在此诞生；注意力可被劫持 |
| grade（**纯机械探针** `_grade_extract_facts`，inline 在 worker_fanout；LLM grade 2026-07-07 已删） | 产出后/上机前（离线） | 查 `*_suspect`——**全是断言质量**（弱V/恒真/写死IP/层不匹配…），**从不查配置引用闭合** | 独立机械 pass，结构上抗劫持 |
| attributor（LLM 孔③） | 上机 fail 后 | 判层/fix_direction | 主次颠倒在此；post-hoc |

**三洞察映射**：① grounding 完胜 post-hoc（GILP）→ 修复该在 grade（上机前），不在 attributor（我之前想改 attributor 是错的，最贵最晚被劫持的层）；② 根因是全局配置不一致、可证逐命令查不出 → grade 查错了东西（只查断言质量、不查配置闭合）；③ 全局检查须独立抗劫持 → grade 已是独立机械 pass，位置天然对，**不靠 worker 自纠**。

**结合方案（三角色不变，grade 扩维 + 修复层前移）**：
- worker：产出不变（承认会被劫持、不指望自纠）。
- **grade（核心改动）**：机械断言质量探针之外，加 ① **配置引用图链接器**（查悬空引用：cname.a.com 被引用却无 host 定义、解析链是否闭合——红线允许侧，引用完整性=意图无关类型规则）+ ② **产出前 grounding**（关键解析假设用 dev_probe/dry-dig 对设备验一次，否了带具体分歧打回 worker；比全 case 上机便宜一个量级）。
- attributor：角色缩小——配置不闭合被 grade 上游拦掉，主次颠倒从源头消失。

**两层两个修复家**：参数层（priority）→ emit 门 + footprint 自愈（`required_when`）；命令层（配置不闭合）→ grade 扩维（引用图链接器 + 设备 grounding）。

**一句话**：三角色是一条越晚越贵的纵深防线，我们一直在最贵最晚的 attributor 层补救；正解是把「全局配置一致性 + 设备 grounding」放到 grade（产出后/上机前、独立机械、天然抗劫持），worker 照旧产出，grade 在烧设备前把「配置引用图闭不闭合、解析链是否真如 worker 所想」对设备验一次，attributor 的错模型循环断在源头。

## grade 在 035413 上的实证：跑了、但对真问题结构性失明（LangSmith 确认）

三轮 worker brief 信封铁证：R1 `redispatch_reason=None`；R2/R3 均 `redispatch_reason=**verify_fail**`（attributor 上机后路径）、定向重做分别是 R1-attr「加 host method ga」/ R2-attr「加 priority」。**每轮重做都是 verify_fail（attributor），从来不是 probe:（grade 机械探针）**；全程无 extract_facts/suspect 信号。

**grade 怎么"想"**：它不想（LLM grade 已删、纯机械）。R1 worker 产出后 `_grade_extract_facts` 确实跑了，但它查的 8 个 suspect 全是**断言质量**（弱V/恒真/写死IP/层不匹配/spec冲突/命中归属未锚定…）。035413 的**断言本身没毛病** → grade 零命中 → 沉默放行 → 上机 fail → 走 attributor。**它从头没看配置一致性一眼**——cname.a.com 被引用却无 host 定义是配置引用图的问题，grade 8 个检查没一个碰它。

**坐实结合方案**：grade 站对位置（产出后/上机前、独立机械抗劫持），却查错维度（只看断言、不看配置闭合）；三轮零 probe: 触发＝grade 对 035413 真问题**结构性失明**。若 grade 加「配置引用图链接器」，R1 就会喊「cname.a.com 被引用却无 host 定义」，上机前拦下、attributor 错模型循环根本不启动。

## 定案（2026-07-08，三角色最终分工）

**grade↔att 共享三维清单（配置期接受 / 配置闭合 / 断言质量），两个时点跑，双向反馈；attributor 结构化多维输出防劫持（priority 和闭合各占一格、互不挤）。**

### attributor：职责不多、忠实履行 + 加一个 `?` 工具
- 角色缩小，只判真正只有整批上机才显形的（并发/时序），结构化填槽（配置期拒绝 / 配置实现意图 / 断言质量），不选"单一根因"。
- **新增 `?` 召回工具**：触发关键字 **`Failed to execute the command`** + **`^` 指向位置** → 把命令**截断到 `^` 处 + 空格加 `?`** → 召回设备该位置的**实际参数/命令 prompt**（如 priority 的 "Weight or priority. value range 0-65535…"）→ 连同错误原文回传 worker。错误消息(为什么错)+`?`(该填什么)互补，worker 大概率看得懂、一次改对。走框架特权 serial 路（实测能进 config 敲 `?`）。
- priority 首次必然还漏到设备被拒——`?` 工具让它当场可解，且反馈进 footprint `required_when`、下次 grade 上机前拦。

### grade：worker 写完**必须触发**（每 case @R1、上机前），增强能力
- **不是选择性/打回2轮才 grade**——实证 7/7 R1 失败在 R1 就可拦，等＝白烧上机轮。
- **必须带 device grounding**——纯离线只拦 2/7（引用图+断言结构），5/7 是"引用闭合但行为不对"（host 恒 UP、dig 返 cname、disable 不抑制、引号格式），必须 dry-probe 设备才现形。
- 能力＝现有断言质量探针 + **① 配置引用图链接器**（悬空引用/解析链闭合）+ **② device grounding**（dry-dig/dry-show 关键观测，对不上意图带具体分歧打回 worker）。
- 成本：每 case 几条 dry-probe（13 case≈十几条）vs 本轮实烧 4 轮上机——净省。

### 7/7 R1 失败实证分类（grade 能否 @R1 拦）
| 用例 | 根因 | 拦法 |
|------|------|------|
| 035413 | cname.a.com 引用不闭合 | 离线链接器 / grounding |
| 044605 | check_point G 空、capture 未产出 | 离线现有结构门 |
| 035493 | host 挂 cname 池→恒 UP | grounding（disable+show→UP≠DOWN） |
| 035570 | 健康检查类型不符+cname 恒 UP | grounding |
| 035373 | 断言以为 disable 抑制 cname 池（错模型） | grounding（dig→cname 仍返回） |
| 044572 | 断言期望缺引号 | grounding（show 回显带引号） |
| 035453 | cname 池 GA 优先级/disable 被拒 | 配置期拒绝可拦、语义部分模糊 |

## 改 grade 前核对设计意图：V6 为什么删了 grade（考古）

**老 grade（`ist-compile-grade`，git 4c13fc69^ 定义）**：LLM 意见型「断言质量」审批——`model:flash`、**纯离线不上机**、只判 V 段断言语义覆盖够不够（靠核对 provenance）；结构有效性明确归 emit 门、不是它的活。三特征：**LLM 意见 / 离线不 grounding / 判断言质量**。

**为什么弱化删除**（它 docstring 自陈 + CLAUDE.md 942 对实证）：
- *"同一份未变卷面多轮审批 **PASS↔CUT 反复翻案 5 轮**，每轮换角度但没一条编译期可修——翻案不产生新信息、只是抽样角度漂移。"*
- 942 对配对：LLM grade 判 PASS→上机 56% / CUT→53%（**判别力 3pp、CUT 重做零增益**）→「LLM 审 LLM 不构成质量门」。
- 轨迹：强模型 → `5f0286f8` 降 flash → V6 删 LLM 层、只留机械 `_grade_extract_facts`。**V6 删得对**：LLM 对断言质量的意见本质是噪声。

**对新 grade 的意义——继承其对的部分，补上它缺的一块（不是推翻）**：

老 grade 做对且值得继承的：① 目标——盯「断言有没有真覆盖目标行为」（编译质量命门，永不过时）；② 溯源核对——按 provenance 逐条核期望值出处，不从零 grep；③ 边界划分——结构有效性归 emit 门、它只管语义覆盖（新设计沿用这条边界）；④ 成熟纪律——分清「编译期可证的」和「只有上机能答的」，别拿后者反复翻案。

它唯一的天花板：**纯离线、手里只有 xlsx+provenance、没有设备**——于是判「断言/配置到底对不对」时只能落回 LLM 意见，而离线 LLM 意见遇到「手册本身错」「行为只有跑起来才知道」就无事实可依、只能漂移（942 对量的是「**离线 LLM 意见**这个手段判别力 3pp」，不是「grade 这件事蠢」）。

**新 grade = 老 grade 的目标/溯源/边界/纪律 + 补上那缺的一块（设备 grounding）**：把它想判却判不准的「断言/配置对不对」，从「离线凭 LLM 想」升级成「拿设备验一次」。设备说 dig 返回 cname.a.com 不是 IP＝设备事实、不翻案——这正是老 grade 缺的稳定 ground truth。是接续，不是取代。

## 对「怎么修」的启示（仅方向，待与用户对齐）

- 根不在 attributor 的判据排序（那是次生的 miss），根在 **worker 对 SDNS cname 数据流的领域理解**——它需要在**产出配置前**验证自己的数据流假设（如「cname.a.com 会不会绕回」），而不是产出后靠上机撞。
- 设备的两类反馈要区分用：配置期拒绝（priority，响）→ 已有 `^`/错误通道；运行时功能失效（dig 结果≠意图，哑）→ 需把「dig 返回的是不是意图要的东西」作为归因第一判据。但**这些都是下游补救**——上游是 worker 的领域心智，值得先在设备上把「正确数据流」搞清、再谈怎么让 worker 一次配对。

## 最小实验：让 infotest 按"设备实验循环"思路检查配置（2026-07-08，cmux 实跑）

**方法**：全新 infotest 会话（deepseek-v4-pro，与失败的 worker 同模型），喂 worker R3 那份错配置 + 脑图意图 + 断言，指令＝「用真设备验证这份配置能不能实现意图，不凭先验，dig 对不上就分析设备实际返回、调配置再验」。文件 `workspace/inputs/exp_check_035413.md`。**不泄露答案**（不提示 cname 字符串意味什么）。

**agent 调用的工具链（按序）**：
1. `Read` 用例文件 → `Grep` 手册（sdns host pool / service disable 语法）
2. `Rest`(clear sdns all) → 凭据未配失败 → `Ssh` 直连 → 拓扑不通（**正确认出"APV 只能经跳板机"**）→ `Probe`(show，只读)
3. `Read` EXCEL_FUNCTIONS.md ×2 → `Emit`(blocks) 构造最小 case.xlsx（撞 autoid 校验错、重试）
4. `RunDigest`(exp_..._fix) 下发配置+上机 → 读回显：**`dig A → cname.a.com`（不是期望 IP）**
5. 迭代：修法→RunDigest→仍 cname.a.com→认了不完整→再 Emit+RunDigest 探内部状态……

**决定性结果——诊断对了（与设备实证结论逐字一致）**：
> *"根因：手册第 1191 行说 CNAME 命中后会「重新进行 SDNS 查询」，但 **cname.a.com 没有配置为本地域名**。SDNS 找不到 cname.a.com 就原样把 CNAME 返回给客户端，不会继续走到 p_main → p_fb 的回退链。"*

**两个关键发现**：
1. **实验循环框架有效**：同一个模型，作为 worker 时凭错模型硬写、3 轮 escalated；换成「产出后拿设备验、dig 对不上就迭代」的框架，**立刻转向 grounding、正确诊断出 cname.a.com 需配成本地域名**——而且**引用了原 worker 有却忽略的手册 requery 规则**（第1191行），被设备实际行为 grounding 后把这条沉睡知识和观测连上了。**是框架改变了结果，不是模型能力。** 且它**迭代而非 committed 错误**（修法失败→继续实验，同我手动 A→B→C）。
2. **工具是瓶颈**：agent 没有轻量「应用配置+dig」工具——Rest 凭据失败 / SSH 直连不通 / dev_probe 只读，最后只能 compile_emit 造完整 xlsx + dev_run_batch_digest（每实验 30s 全 case 跑）。¥5.6/11min 还在迭代，vs 我 serial console 每实验秒级。**「设备实验循环」设计必须配一个轻量 apply-config+dig 工具**，否则实验被 xlsx 管道拖慢烧钱。

**对设计的确认**：grade=末轮设备实验循环 这个方向**实测成立**（框架让同模型从失败变成功诊断）；但落地前置条件是**给它一个轻量设备实验工具**（应用配置块→dig→回显，不走完整 case.xlsx），否则昂贵到不实用。

### 实验最终结果（agent 自主跑完 8 个设备实验，¥7.87 / ~18min）

agent 系统做了 8 个实验（03541-03548），列出实验表 + 设备状态证据，给出**多根因最终结论**（比人工单线结论更全）：

**最终结论：原始配置不能实现意图，两个根本原因**：
1. **CNAME 目标域名没配为本地 host → CNAME 链断裂**（＝设备实证实验 C：cname.a.com 必须 `sdns host name`）。
2. **`sdns service disable` 不触发 pool-level 回退**——它从 `show sdns service status` 拿到 `s_main DOWN(SERVICE_DISABLE) DISABLE`，诊断出「disable 不把 service 移出池，设备认为池中仍有成员，『池空才回退』条件不满足，回退不触发」。**这个机制细节比人工手动实验挖得更深**（人工实验 A 只观察到 pool-fallback「No answer」，没挖出「disable≠empty pool」的因）。

实验里还找到能通的变体（03546 空池回退→172.16.35.231✅、03547 CNAME 链正常✅），并正确识别 AAAA 无 IPv6 service 返回不了 IPv6（非配置错）。

**验证净结论**：同一模型，作为 worker 3 轮没解出、escalated；给「设备实验循环」框架后，**8 个实验自主收敛到正确多根因诊断，且比人工更彻底**。方向（grade=末轮设备实验循环）实测坚实成立。代价：8 个实验每个都走 compile_emit 造 xlsx + dev_run_batch(30s)，¥7.87/18min——**工具瓶颈确认，落地必须先造轻量 apply-config+dig 工具**。

## 轻量设备实验工具可行性——已验证（2026-07-08，直接调 apv_ssh_execute）

问题：实验循环要"应用配置块→dig→回显"，agent 走 compile_emit 造 xlsx + dev_run_batch(30s/实验)，¥7.87/18min 太贵。是否改造 dev_probe 就能解决？

**实测 apv_ssh_execute（跳板机 FastMCP :8000，dev_probe 的底座）能力边界**：
- **① 应用配置能力已存在**：`fastmcp_call('apv_ssh_execute', {host:设备, mode:'config', command:'sdns host name grndtest.a.com 60'})` → **status success、`APV(config)#`、真配上了（show 验证到）、`no ...` 清理成功**。dev_probe 只是工具层把它白名单成 show/get，把已有的 `mode=config` 藏了。提示符 `APV#`＝已特权。
- **② dig 通路现成**：跳板机（10.4.127.93）能直接 `dig @172.16.34.70 <域名>`，配置在时返回正确 IP（前面对照实验 172.16.35.231 已验）。
- **③ apv_ssh_execute 够不到 routera**：`host=172.16.33.206` → Authentication failed（它用设备凭据，routera 是 test/test、需另给）。

**结论：改造 dev_probe（暴露 apv_ssh_execute 已有的 config 模式）+ 加一步跳板机 dig ＝ 轻量 grounding 工具，90% 能力已在框架里、低风险**。每步是快 HTTP 调用、秒级，替掉 30s 的 xlsx+批跑路径。**caveat**：ga 是 geo-aware，跳板机 dig vs routera dig 的 geo 选池可能不同；但 grounding 判的是"观测类别"（IP vs cname 字符串、链通不通），跟源无关，跳板机 dig 够用；要精确复现 ga 选池才需 routera dig（凭据/锁定问题另解）。

## 设备访问速查（compact 后续用，避免重新摸索）
- 跳板机：`10.4.127.93`，user `test`，密码 env `IST_JUMPHOST_PASS`（6 位）。93/79/105 可用，103 维护。
- 设备（APV Beta.APV-HG-K.10.5.0.585）：SSH 直连不通，只能经跳板机。serial：`cu -s 9600 -l ttyS0`（ttyS0=172.16.35.70 配置口）；登录 `admin` + conf `infosec_hgk.password`（5位）；enable **空密码**（直接回车，不是 test_pass）；enable 密码≠登录密码。conf 在跳板机 `/home/test/apv_src/conf/93.conf`，段 `infosec_hgk`（hostname APV，匹配「APV login:」）。
- routera（dig 触发机）：`172.16.33.206`，test/test（多次失败会临时锁）。
- apv_ssh_execute（推荐，秒级）：`from main.case_compiler.device_mcp_client import fastmcp_call`；`fastmcp_call('apv_ssh_execute',{'host':'172.16.35.70','command':...,'mode':'config'|'show'})`。
- 环境：SDNS 监听 172.16.34.70；后端 IP 172.16.35.213/231/232；`clear sdns all` 清场（下次测试床 init 也会 clear config all）。
- `?` context-help：serial config 模式敲 `<命令截断到^> ?` 返回该位置参数说明（已实测：`sdns host pool "h" "p" ?` → "Weight or priority. 0-65535. takes effect when method wrr/ga. default 0"）。
