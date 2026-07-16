# dongkl 9 个上机失败案 —— 执行回放 + 编写者隐含逻辑 T 清单

> 目的：只用**设备原始输出**倒推每个失败案的 excel 执行过程，重建编写孔（compile-worker）当时必然持有的隐含思考逻辑，固化成编号 T 清单，交设计层分析。
> 方法：xlsx 数据区（行 29 起，A=autoid B=优先级 C=步骤号 D=描述 E=角色 F=方法 G=命令/断言 H=寄存器 I=次数）逐行 → 设备逐条命令/断言 → 实际回显 → 挂点；多轮案对 `history/case.r{N}.xlsx` 做 r1→r3 修法演化对照。
> 数据源：`workspace/outputs/dongkl/unfinished/<autoid>/{case.xlsx,history/case.r*.xlsx,attr_evidence.json}` + `runtime/backups/reverify2_pre_20260716_0205/dongkl/manifest.json` 的 step_intents。
> 基线：`dongkl_excel_quality_audit.md`（五节）+ `dongkl_yzg_langfuse_failures_review.md`。整理：2026-07-16。**只读调查，零代码改动。**

---

## 零、一句话总纲

9 个失败案的隐含逻辑错误聚成两大簇：**（甲）把"非确定分布轮转"当"确定序列"来构造断言**（7 个 rr/wrr/ga 案），**（乙）配置构造知识缺口/回归**（漏权重、错语法、丢基础配置）。设备回显不但坐实了断言写法脆，还**比断言写法更深地**推翻了两条编写者（和脑图作者）共同持有的前提：① 请求→池的落点在本设备**不可预测**（跨客户端不共享轮转、单客户端顺序也不定、GA 不恒选最高）；② pool 的 `Hit` 计数器**服务了成员却可能不 +1**，不是可靠的分布支点。

---

## 一、逐案执行回放（9 案）

> 表读法：**终版关键断言** = final case.xlsx 里决定成败的 check_point；**设备实际** = attr_evidence.device_context 的框架逐步明细 / 配置会话 / RouterA·B 真实 dig；**挂点** = 哪条断言 fail、为什么；**轮间演化** = r1→r3 修法怎么变、修对没。

### 【rr 簇】

#### 777976　sdns host 选池 rr
- **意图**：client1 发 1 次→命中 pool1；client2 发 1 次→命中 pool2。
- **终版关键断言**：req1(routera dig) `abs_found 172.16.35.213`(p1) + p1 `found Hit:\s+1`；req2(routerb dig) `abs_found 172.16.35.231`(p2) + p2 `found Hit:\s+1`。
- **设备实际**：req1→p1，p1 `show statistics` **Hit:1**、返回 213 ✓✓；req2→**p2 Hit:0、231 找不到** ✗✗（routerb 未落到 p2）。
- **挂点**：`231` + p2 `Hit:\s+1` 两条 fail。前提"第 2 个客户端命中第 2 个池"在设备上不成立。
- **轮间演化**：r1/r2 两次请求**都用 routera** → r3 才把 req2 换 **routerb** 并补 `sdns host pool autotest.com p1/p2/p3` 显式绑定。**"client2→pool2" 前提三轮从未放弃**，worker 只换了实现手段（换客户端/补绑定），落点仍不受控。**未修对。**

#### 778041　修改 pool 成员 rr（结论翻转案）
- **意图**：client1 发 1 次→pool1；改一个 pool 成员后 client2 发 1 次→按原顺序命中 pool2（不变）。
- **终版关键断言**：req1(routera) `abs_found 213`(p1)+p1 `Hit:\s+1`；改 p3 成员(`no ...p3 s3` / `...p3 s4`)后 req2(**仍 routera**) `abs_found 231`(p2)+p2 `Hit:\s+1`。
- **设备实际**：req1→p1 ✓✓；req2→**p2 Hit:0、231 找不到** ✗✗。
- **挂点**：同 777976。**关键补充**：本案两请求**同为 routera**，req2 仍未落 p2 → 证明不只是"跨客户端不共享"，**单客户端连续两次也不确定 p1→p2**。
- **轮间演化**：r1 用 `sdns service ipv6 s4 3ffd::213` → 设备 `syntax rejected (^)`（ipv6 服务语法错）；final 靠**删掉 ipv6 服务**（改预建 v4 s4）绕过。核心分布前提未动。审计另记整卷复跑"先通过后不通过"翻转（床不稳），但断言层与 777976 同病。**未修对。**

#### 778072　删除 pool rr（全批构造最好，只差一条）
- **意图**：client1 发 1 次→pool1；删一个 pool 后 client2 发 1 次→按原顺序命中。
- **终版关键断言**：绑定顺序 p3-p1-p2；dig1 `found 224`(p3)+p3 `Hit:\s+[1-9]\d*`(**区间**)；删 p2 后 dig2 `found 172\.16\.35\.(213|224)`(**集合**，p1或p3成员)+p1 `Hit:\s+[1-9]\d*`；结构 `show sdns host pool` found p1、found p3、not_found p2。
- **设备实际**：dig1→224 ✓、dig2∈{213,224} ✓、host 绑定 p1/p3 在、p2 已删 ✓✓✓✓✓（结构断言**全过**）；唯一 **Fail 1: p1 `Hit:\s+[1-9]\d*`**——`show statistics pool p1` 实际 **Hit:0**（两次请求都落 p3，p1 未被选中）。
- **挂点**：残留的**位置化计数假设**（"删 p2 后某次请求必落 p1、p1 计数必 >0"）。落点松成集合已对，计数却仍钉 p1 必中。
- **轮间演化**：r1 精确 IP+精确 `Hit:1`、dig1→p1/dig2→p3 位置化 → r2 更多位置化(dig1→p3/dig2→p1/dig3→p3、p3 `Hit:2`) → r3 **落点松成集合 `(213|224)`、计数松成区间 `Hit≥1`**——分布断言全过。**方向修对了 90%，只剩一条 `p1 Hit≥1` 位置化残留。**

#### 778012　新增 pool rr（配置回归 + 自相矛盾模型）
- **意图**：client1 发 1 次→pool1；再新增一个 pool，client2 发 1 次→按原顺序命中、**最后才命中新增池**。
- **终版关键断言**：dig1-3 `not_found 172\.16\.35\.225`(p4 未命中)、dig4-8 `found 172\.16\.35\.225`(p4 命中)、p4 `found Hit:\s+2`。
- **设备实际**：`sdns host pool autotest.com p4` → **`The SDNS host "autotest.com" does not exist. Failed to execute`**；RouterA 四次 dig **全部 `connection timed out; no servers could be reached`** → 225 五处找不到（found 挂），not_found 因超时空返回而**假过（vacuous）**。
- **挂点**：**基础配置整段丢失**——final 的 step1 (r30) 为空，建 host/pool 的 `sdns on / sdns host name autotest.com / p1-p3...` 未下发，故绑 p4 时 host 不存在、dig 无解析目标全超时。
- **轮间演化**：r1/r2 step1 **含完整基础配置** → r3 **step1 空**（疑误当 fixture 会补）。同时分布模型逐轮变且都错：r1(仅 dig4=p4，捕获-比较判两次不同) → r2(4 次 dig 后 p4 `Hit:1`) → r3(**dig4-8 连续全 225**——与 RR 周期 p1,p2,p3,p4,p1… 自相矛盾，dig5/6/7 该回原池)。**r3 相对 r1/r2 是回归（基础配置丢失），分布模型三轮未收敛。**

### 【wrr 簇】

#### 593484　wrr 选池（错误 WRR 分布模型）
- **意图**：wrr 3:2:1；client1 发 3 次→命中权重3池；client2 发 2 次→命中权重2池。
- **终版关键断言**：`found wrr`；client1(routera)3 dig → p1 `found Hit:\s*3`；client2(routerb@172.16.32.70)2 dig → p2 `found Hit:\s*2`。
- **设备实际**：`wrr` ✓；p1 **Hit:2**(非3) ✗、p2 **Hit:0** ✗。RouterA 三次实测 = **224(p3)、213(p1)、213(p1)**——交织分配、**首发落最低权重 p3**；routerb@172.16.32.70→**213(p1)** 非 p2。
- **挂点**：`Hit:\s*3` + `Hit:\s*2` 双 fail。前提"3 次全落 p1、2 次全落 p2"（块状耗尽）被设备的交织抽样推翻。
- **轮间演化**：r1 逐 dig 写死 `found 213`×3 + `Hit:3` → r2 加 `found wrr` 算法名核对 → r3 **丢掉逐 dig 写死 IP**、加 `sdns pool method primary pX rr`，但**保留致命的精确 `Hit:3`/`Hit:2`**（= 仍信"所有请求落一个池"）。**部分修（去写死IP），核心分布模型未修。**

#### 593516　新增 pool wrr（修法背书案，只差一条错命令）
- **意图**：wrr 3:2:1；新增 pool p4 权重 40，client2 发 4 次→**最后命中权重40**。
- **终版关键断言**：Phase1 3 dig → p1 `Hit:\s+[1-9]\d*`+`found 213`；`show sdns host pool` → `found p4`+**`found 172\.16\.35\.225`**；Phase2 **20 dig** → p4 `Hit:\s+[1-9]\d*`+`found 225`(从 `show statistics`)、p1 `Hit:\s+[1-9]\d*`。
- **设备实际**：p4 `show statistics` **Hit:10**、p1 **Hit:6**；RouterA 20 次后 ~10 次连续 225（**权重-40 主导被真验到**）→ 6 条断言过 5。唯一 **Fail 1: `172\.16\.35\.225`**——来自 `show sdns host pool`（该命令输出只有 `sdns host pool "autotest.com" "p4" 40` 域名+池名+权重，**无成员 IP**）。
- **挂点**：**一条断言用错命令**——去 `show sdns host pool` 找成员 IP 225（成员 IP 只在 `show statistics` 的 Service IP 行，本案 r63 已正确读过一次，等于**重复了错的一条**）。
- **轮间演化**：r1 位置化(第4次→p4)+从 `show sdns host pool` 读 225 → r3 **位置化松成 20 发包+区间**（分布验对了），但**"show sdns host pool 含成员 IP"的错前提保留到末轮**。**"大量发包+区间"方向被实机背书，残留是窄的错命令 bug。**

### 【ga 簇】

#### 681749　ga 算法（GA 不恒选最高 + 计数器不计数）
- **意图（本身歧义）**：desc 写"wrr 30/20/10"，title 写"ga"，expected 两客户端都"命中30权重pool"（=GA 恒选最高）。
- **终版关键断言**：method `ga`；req1(routera)`found 213`(p1)；req2(routerb)`found 213`(p1)；p1 `found Hit:\s+[1-9]`；p2/p3 `not_found Hit:\s+[1-9]`。
- **设备实际**：RouterA→**225(p3)**、RouterB→213(p1)——**GA 未恒选最高优先级 p1，两客户端落不同池**（疑按源做亲和）。且 routera 返回 225=p3 成员，`show statistics pool p3` 却 **Hit:0**（**服务了成员却不计数**）；p1 `Hit:\s+[1-9]` fail。
- **挂点**：`found 213`(req1 落 p3 非 p1) + p1 `Hit≥1`(计数器 0) 双 fail。
- **轮间演化**：r1 ga（但断言 p1 `Hit:1`+p2 `Hit:1`，模型自相矛盾）→ r2 **翻成 wrr**（12 发包、三池 `Hit≥1`）→ r3 **翻回 ga**。**因意图算法歧义，worker 在 ga/wrr 间横跳三轮，从未上机确证本 build 真实 GA 语义。未修对。**

### 【config 簇】

#### 572672　show 展示域名算法（wrr/ga 漏权重）
- **意图**：配多个域名关联池 → `show sdns host method` 查看 → 配置正确。
- **终版关键断言**：三域名 method rr/wrr/ga；`show sdns host method` → `found ..."autotest1.com" "rr"` / `..."autotest2.com" "wrr"` / `..."autotest3.com" "ga"`。
- **设备实际**：`sdns host method autotest2.com wrr` → **`The priority must be an vaild value when the SDNS host method is "wrr". Failed to execute`**；`...autotest3.com ga` → 同款 ga 报错。`show` 三域名全显 **rr**（wrr/ga 未生效）→ wrr、ga 两条 fail。
- **挂点**：host-pool 绑定 `sdns host pool autotest2.com p2`（**不带权重**）→ 设 wrr/ga 被拒。
- **轮间演化**：r1 原子下发 → r2 拆开+`sleep 2` → r3 又原子。**三轮都在改批次/加 sleep（错误假设是时序问题），从未给绑定补权重**——而同批 593484/681749 的绑定明明写了 `...p1 3`/`...p1 30`。**知识应用不一致，未修对。**

#### 572708　删除域名算法（把能过的 rr 改回归成 wrr）
- **意图**：配多个域名 → `no sdns host method` 删除 → 删除成功。
- **终版关键断言**：两域名 method **wrr**（`sdns pool service p1 s1 weight 3`）；`found ..."wrr"`×2；`no sdns host method autotest1.com` 后 `not_found autotest1 "wrr"` + `found autotest2 "wrr"`。
- **设备实际**：`sdns pool service p1 s1 weight 3` → **`syntax rejected (^)`**（`^` 指 weight，该命令不接受 weight 后缀）；`sdns host method ... wrr` → `priority must be valid... Failed`；`show` 全显 rr → wrr 三条断言 fail。
- **挂点**：① 权重写错层级（`sdns pool service` 不带 weight，权重属 `sdns host pool <域> <池> <权重>`）；② 连带 wrr 被拒。
- **轮间演化**：**r1/r2 用 rr**（删除测试与算法无关，rr 无需权重，本可通过）→ **r3 无必要地"升级"成 wrr**，引入权重要求又放错位置。**这是把一个能过的构造改成回归。未修对，且是自造的回归。**

---

## 二、编写者隐含逻辑 T 清单

> 每条 = 前提陈述 + 命中的案 + 设备证据（为何错/对）+ **类型**（设备行为知识缺失 / 构造逻辑错误 / 脑图预期照抄）+ **多轮是否修正过**。类型取主，副类型括注。

### 甲、分布/轮转"确定性"前提簇（7 案的病根）

**T1　"第 N 次请求确定命中第 N 个 pool"——轮转落点可钉死到具体池的具体成员 IP。**
- 命中案：777976、778041、778072(r1/r2)、778012、593484、593516(r1)、681749(r1)。
- 设备证据：**778072 删 p2 后 dig2 落 p3(224) 不是预期 p1；593484 client1 首次 dig 落最低权重 p3(224)；777976/778041 req2 未落 p2**。落点在本设备不可预测。
- 类型：**构造逻辑错误**（把非确定分布钉成确定序列）（副：脑图照抄——脑图逐字写"第1次命中pool1、第2次命中pool2"）。
- 多轮修正：778072/593516 末轮把落点松成集合/区间（**修对**）；777976/778041/593484 保留精确落点到末轮（**未修**）。

**T2　"两个触发客户端共享同一条全局轮转链"——client2 接着 client1 往下轮，必落 pool2。**
- 命中案：777976(r3 拆 routerb)、593484(routerb 走第二 listener)、681749(routerb)。
- 设备证据：777976 routerb→p2 未命中(p2 Hit:0)；593484 routerb→213(p1) 非 p2。**关键反证：778041 两请求同为 routera，req2 仍未落 p2**——既非跨客户端共享、单客户端顺序也不定。
- 类型：**脑图预期照抄**（脑图"客户端2→命中第二个pool"，作者前提本身与本 build 不符）（副：设备行为知识缺失——疑源相关轮转/各客户端各自从 p1 起）。
- 多轮修正：777976 r1/r2 两请求都 routera → r3 才拆 routerb，**始终未放弃"client2→pool2"前提**，只换实现手段。**未修。**

**T3　"pool 的 Hit 计数器每次命中必然 +1，可用精确 `Hit:N` 卡分布"——计数器是可靠分布支点。**
- 命中案：777976(Hit:1)、778041(Hit:1)、593484(Hit:3/2)、778072(r1/r2 Hit:1/2)、778012(Hit:1/2)。
- 设备证据：**681749 routera dig 返回 225（=p3 成员 s3），`show statistics pool p3` 却 Hit:0——池服务了成员却不计数**（最干净的计数器异常，绕开 routerb 打错 listener 的捕获污染）。计数器不可靠。
- 类型：**设备行为知识缺失**（Hit 计数器不可靠；机理未定——DNS 60s 缓存命中不重选池 / 计数更新竞态 / 算法特定计数，**建议设计层上机钉死**）（副：构造逻辑错误——精确计数验非确定分布）。
- 多轮修正：778072/593516/681749 迁到区间 `Hit≥1`（**修对**）；777976/778041/593484 保留精确 `Hit:N`（**未修**）。
- 注：593484 的 p1 Hit:2 其实**是对的计数**（两次 213），错在 worker 期望 Hit:3——那是 T4 的分布模型错，非计数器错。别把两者混为一谈。

**T4　"WRR 先耗尽高权重池配额、再轮到次高"——块状分配而非按权重交织抽样。**
- 命中案：593484（核心）、593516(r1 隐含)、681749(r2 曾按 wrr 想)。
- 设备证据：593484 RouterA 三次 = **224(p3)、213(p1)、213(p1)**——交织且首发落最低权重池，p1 仅 Hit:2、p2 Hit:0。WRR 是按权重**交织抽样**，不是"先把 p1 的 3 次用完"。
- 类型：**构造逻辑错误**（错误 WRR 分布模型）（副：脑图照抄——"发3次→命中3权重pool"）。
- 多轮修正：593484 末轮丢逐 dig 写死 IP 但保留"3 次全落 p1"的 `Hit:3`（**未真修**）；593516 迁到 20 发包+区间（**修对**，实机 p4 Hit:10 验到权重主导）。

**T5　"GA 算法恒选最高优先级池"——任意客户端任意请求都命中权重 30 的 p1。**
- 命中案：681749(r1/r3)。
- 设备证据：routera→**225(p3)**、routerb→213(p1)——**GA 在本 build 未恒选 p1，两客户端落不同池**（疑按源亲和）。
- 类型：**设备行为知识缺失**（本 build GA 语义未经上机确证）（副：脑图照抄——"命中30权重pool"）。
- 多轮修正：因意图 desc(wrr)/title(ga)/expected(恒选) 三者打架，worker 在 ga↔wrr 间横跳三轮（r1 ga→r2 wrr→r3 ga），**从未上机实证 GA 真实行为**。**未修。**

**T10　"新增 pool 后前 K 次走原池、其后每次都命中新池"——新池入轮后恒中。**
- 命中案：778012(r1: 仅 dig4=p4；r3: dig4-8 连续全 225)。
- 设备证据：本案配置崩无法直验；但模型**自相矛盾**——RR 加 p4 后应 p1,p2,p3,p4,p1,…，dig5/6/7 该回原池、不该连续 225。把脑图"最后才命中新增pool"误解成"到位后恒中新池"。
- 类型：**构造逻辑错误**（新池入轮模型错）（副：脑图照抄——"最后才能命中新增的pool"）。
- 多轮修正：r1 与 r3 给出**不同的、都错的**入轮模型，**未收敛**。

### 乙、配置构造知识缺口/回归簇

**T6　"`show sdns host pool` 的输出里含成员 IP，可从中找成员地址"。**
- 命中案：593516(r3 唯一挂点)。
- 设备证据：`show sdns host pool` 实测只列 `sdns host pool "autotest.com" "p3" 0`（域名+池名+权重），**无成员 IP**（778072 同命令回显同样只有池名）。成员 IP 只在 `show statistics sdns pool pX` 的 `Service IP` 行。
- 类型：**设备行为知识缺失**（命令输出字段边界）。
- 多轮修正：593516 末轮同时从 `show statistics`(对) 与 `show sdns host pool`(错) 各找一次 225，**错的那条重复断言留到末轮**。**未修。**

**T7　"wrr / ga 可直接 set，不需要 host-pool 绑定预先带权重/优先级"。**
- 命中案：572672、572708。
- 设备证据：两案 `sdns host method ... wrr/ga` 均被拒——`The priority must be an vaild value when the SDNS host method is "wrr"/"ga". Failed to execute`。对比 593484/681749 绑定写成 `sdns host pool autotest.com p1 3` / `... p1 30` 即成功——**wrr/ga 要求绑定层先带权重**。
- 类型：**构造逻辑错误 / 设备行为知识缺失**（漏必需参数，机械可查）——同一 worker 在别案会写权重，**知识应用不一致**。
- 多轮修正：572672 三轮改批次/加 sleep（错误假设是时序），从未补权重；572708 r3 试图补权重却放错层级（见 T8）。**未修。**

**T8　"权重写在 `sdns pool service pX sX weight N`"——weight 属 pool-service 层。**
- 命中案：572708(r3)。
- 设备证据：`sdns pool service p1 s1 weight 3` → **`syntax rejected (^)`**，`^` 指向 weight——该命令不接受 weight 后缀；权重属 host-pool 绑定层 `sdns host pool <域> <池> <权重>`。
- 类型：**设备行为知识缺失**（权重参数所属层级）。
- 多轮修正：仅末轮出现（r1/r2 用 rr 无此问题）——是 r3 自造的新错。
- 同族小项（未单列 T）：**778041 r1 `sdns service ipv6 s4 3ffd::213` → `syntax rejected (^)`**（ipv6 服务语法错），final 靠删 ipv6 绕过——同属"设备命令语法知识缺口"。

**T9　"per-case 空 init 步也会被 fixture 自动补全基础配置"——base config 可省。**
- 命中案：778012(r3)。
- 设备证据：`The SDNS host "autotest.com" does not exist. Failed to execute`——autotest.com 从未创建，后续 dig 全 `connection timed out`，225 五处找不到（not_found 因空返回**假过 vacuous**、found 真挂）。
- 类型：**构造逻辑错误**（基础配置缺失，r3 相对 r1/r2 的**回归**）。
- 多轮修正：r1/r2 init 完整 → r3 丢失（**反向回归**，非修正）。

---

## 三、给设计层的类型分布与三个追问

**类型分布（主类型计）**：
| 类型 | T 条目 | 案数覆盖 |
|---|---|---|
| 构造逻辑错误（把非确定当确定 / 模型错 / 配置回归） | T1、T4、T7、T9、T10 | 7 案主因 |
| 设备行为知识缺失（落点/计数/GA语义/命令字段/语法层级） | T3、T5、T6、T8 | 5 案 |
| 脑图预期照抄（作者前提本身与本 build 不符） | T2（+T1/T4/T5/T10 副） | 5 案 |

**关键观察**：多数 T 是**混合型**——脑图作者写下的确定性预期（"第2次命中pool2""发3次命中3权重pool""GA命中30权重"）本身就与本 build 设备行为不符，编写孔**忠实编码了一个错的前提**，再用确定性断言手段（精确落点/精确 Hit:N）放大成必崩形态。**分类这轮已判对"分布是采样不是成员"，但落到"发多少包、区间还是精确、落点钉不钉、计数器信不信"的构造仍系统性偏确定性。** 778072/593516 末轮证明"集合落点+区间计数+大量发包"方向能过——短板精确、可定位。

**三个必须上机钉死的追问（决定 worker.md 该怎么收紧）**：
1. **本 build 的 pool `Hit` 计数器到底何时 +1？**（T3）——681749"返回成员却 Hit:0"与 593516"20 发包 p4 Hit:10 计数正常"并存，机理未定（DNS 60s 缓存 / 竞态 / 算法特定）。若计数器不可靠，**分布验证应彻底弃用 pool `Hit`，改"命中集合 ∈ 存活池成员" + "高权重成员在大样本占比显著"**。
2. **rr/wrr/ga 的落点是否跟源（客户端）绑定？**（T1/T2/T5）——GA 两客户端落不同池、单客户端连续两次不确定 p1→p2，疑源亲和。若是，**禁止"特定客户端命中特定池"的断言**。
3. **wrr/ga 的权重必带、权重层级（host-pool 绑定层）、`show sdns host pool` 无成员 IP——这三条是否入 emit 机械门？**（T6/T7/T8）——全是机械可查、不该漏到上机的构造缺陷。
