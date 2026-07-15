# 回归线索#1 取证 — S1 过度泛化假设(667986/668059)

> 只读调查。假设(team-lead):worker 把 S1 加的分布类「区间正则」套到非分布的容量测试(667986 满配16 listener)上,导致断言与 `show sdns listener` 对不齐→broken。
> **裁决:假设证伪。S1 未被援引;真根因在归因指令 + worker 手写 format-错配区间正则。**

---

## 0. 一句话结论

667986 的端口范围正则 **不是** S1 分布指引的产物——它是 worker **照 attribution 的「生成16个不同IP:port组合、断言逐条验证」指令**、用手写区间正则去「逐条验」`show sdns listener`,而正则假设的输出格式(`IP\s+port`)与设备实际格式对不齐。worker 思维链**零**援引分布/区间/`dist` 概念。668059 是另一回事(用 `abs_found`,无区间正则)。

**三层回归面裁决(§6 展开):理论对、设计有缝、实现(S1)留了一道门但未被本案穿过。**
- **理论**:S §0.5 正确且已 scope——interval 只绑 h-in-λ(分布类),「无 h → 出辖区」明确把容量/存在性排除在区间remedy外。**非理论缺口**。
- **实现丢理论(轻·潜伏)**:S1 文本按**算法类型轴**(分布algo vs 确定映射algo)scope,而理论按 **h-位置轴**(h-in-λ vs 无h)scope——两轴不重合,**「无 h」的容量/枚举类(既非分布也非确定映射algo)落在 S1 的 scope 声明覆盖不到的缝里**,且给了手写区间正则形态例、未指向 `dist`。
- **系统性风险实测:低**——全 outputs 仅 **8 份**用 `[d-d]` 范围正则,其中**非分布上下文仅 1 份=667986**(还是 attribution 驱动、非 S1)。未见 worker 系统性把区间正则套到其他非分布案。潜伏面在,实现面未爆。

---

## 1. 实证根因(行级铁证)

### 1.1 时间线不排除、但内容排除 S1
- 我的 S1 edit(compile-worker.md)mtime ~16:08–16:30;667986 worker r2 trace `b64c8db4…` ts **2026-07-15T08:29Z=17:29 本地**,case.xlsx mtime 17:38 → worker 跑在 S1 之后,**时间线不排除**。
- 但**内容排除**:worker 思维链(langfuse trace 234KB)里 `分布`/`区间`/`interval`/`distribution`/`Hit:\s`/`dist 声明` 在**模型推理**中**一次都没出现**;唯一出现处是 `fs_read knowledge/data/compile_ref/EXCEL_FUNCTIONS.md` 结果里的**目录行**(第8行 TOC「分布区间断言:算法类(rr/wrr)…」)被回显——worker 读了那份 blocks 帮助文档,但**没用**其分布段(`dist 声明`未出现)。

### 1.2 范围正则的真来源 = attribution 的「逐条验证16 combos」
667986 r2 brief 的 attribution(`V/reflow`)fix_direction 原文:
> 「…设备对相同IP:port去重只存储一条…修复方案:(2)如果测意图是"满配16条listener"→**config步骤应生成16个不同IP:port组合,断言逐条验证**。」

worker 照做:config 改成 **4 IP × 4 port = 16 唯一组合**(ports 54–69),断言用**端口范围正则**压缩「逐条验证」:
- `172\.16\.3[24]\.70\s+5[4-9]`(IP + 端口54-59)
- `172\.16\.34\.70\s+6[01]`、`172\.16\.3[24]\.71\s+6[2-9]`
- 默认端口:`\n172\.16\.32\.70\s*\n`

这些是**成员集合压缩**(把 16 条期望 listener 塞进几条范围正则),不是 S1 的**命中计数区间**(`Hit:\s+(2[89]|3[0-3])`)——概念与结构都不同。

### 1.3 为什么 broken:手写区间正则与 show 输出格式错配
r1 device_context 已显示实际格式:`show sdns listener` 回显 = `sdns listener 172.16.34.70`(默认端口**不带 port**、格式是 `sdns listener <IP>` 非 `<IP>\s+<port>`)。worker r2 的范围正则假设 `IP\s+port` 布局,与实际不符 → `fail to find`。**worker 没用 dev_probe 现验非默认端口的实际 show 格式**(编译期设备干净,统计/会话面空)就手写了假设格式的正则。

### 1.4 668059 是独立问题
668059 当前 case.xlsx 断言是 `abs_found 172.16.34.70` + `abs_found "hello test"`——**无区间/范围正则**。与 667986 非同型,更与 S1 无关(其 broken 另有根因,不在本线索)。

---

## 2. 设计裁决:S1 未过度泛化(本案),但有一处**一致性改进**值得做

**S1 无罪(本案铁证):** worker 零援引分布概念、`dist` 未用、范围正则来自 attribution 指令。若删 S1、这案照样这么写(attribution 指令不变)。

**但一处真实的一致性缝隙(precautionary,非本 bug 之因):**
- 我的 S1 文本给了**手写区间正则**形态例 `Hit:\s+(2[89]|3[0-3])`;
- 而 `EXCEL_FUNCTIONS.md:176`(pre-existing,2026-07-09,与 S1 无关)明确:「**手写区间正则…极易错。所以用 `dist` 声明**,让框架确定性展开成区间正则 + 守恒自检」。
- 即:S1 展示了手写形态,项目 canonical 做法是 `dist` 组合子。两者**不一致**——S1 可对齐到指向 `dist`,避免未来 worker 手写易错区间正则(EXCEL_FUNCTIONS 自己警告的坑)。

---

## 3. 修法建议(读-only 阶段,先不改)

**给 team-lead 分诊(本案真根因不在 S1,routing 建议):**

1. **【真根因·assertion 形态】容量/配置存在性测试的验证形态** —— 667986 类「满配 N 条 X」验证的正解是**逐条成员归属**(每条 listener 的 `abs_found`,或 `found_times` 计次),**grounded 在实际 show 格式**(worker 该 `dev_probe show sdns listener` 现验格式再写断言,而非手写假设格式)。范围正则压缩成员集**易与真实布局错配**。这是 worker 构造侧指引问题(compile-worker.md territory),可加一条陈述式事实:「`show` 表类输出的字段布局按设备实际回显,断言前用 dev_probe 现验格式;成员存在性用逐条 abs_found/found_times,不用假设布局的范围正则」。

2. **【一致性·S1 对齐 dist】** —— S1 的区间正则形态例可改为指向 `dist` 组合子(`compile_emit` 的 dist 声明,框架确定性展开 + 守恒自检),与 EXCEL_FUNCTIONS.md 统一。陈述式:「命中分布区间用 `dist` 声明让框架展开,手写区间正则易错(见 blocks 文档)」。**这不修本 bug**(本 bug 非 S1 致),是消一处未来隐患。

3. **【可选·attribution 措辞】** —— attribution 的「断言逐条验证」措辞正确但未提示「逐条验证须 grounded 实际 show 格式」,worker 据此手写了错配正则。若要更稳,attribution/worker 侧可加「逐条验证前先确认观测命令的实际回显布局」。属 S2(归因)/ worker 交叉,供 team-lead 定夺。

**均为陈述式、零写死领域命令、溯源手册/实际回显。红线守。**

---

## 4. 理论对账
- 本案是 **S §5 π 忠实实现 / oracle 残差**问题的一个实例:断言(π 的投影)未 grounded 在真实观测格式,手写正则对不齐 = oracle 与设备回显错配。与 §18.10 window-audit「窗口对齐」同源——容量测试的成员断言也该按实际回显对齐,不按假设布局。
- 与 S1 锚点(S §0.5 h-不变式)**无关**:667986 是**确定性配置存在性**(无 h),不是 h-in-λ 分布采样。恰恰印证 S1 的作用域(分布类)本就不该覆盖它——worker 也确实没往那边靠。

---

## 5. 回归锚建议
- 若采纳修法1/2:worker prompt 结构门加锚——「容量/存在性测试逐条成员断言 + dev_probe 现验格式」「分布区间用 dist 非手写正则」。
- eval 锚:667986 的 mindmap → 期望 case.xlsx 断言**不含**假设布局的 `IP\s+port` 范围正则(应为逐条 abs_found 或 dist)。

---

## 6. 三层回归面(理论 / 设计 / 系统性)——定 S1 改动完整回归面(用户裁决要求)

### 6.1 理论层:非缺口,理论已正确 scope

THEORY_target_system_algebra §0.5 按 **h-位置**分诊(行149-152):
```
h 在 λ 内 → 欠定 → 对策=R 边缘化为 h 不变式(区间/集合)   ← interval/set 只在这
无 h      → 确定性错误 → 出本框架辖区,归 Ω 判定树
```
interval/set 是 **h-in-λ 边缘化**的 remedy,与「无 h」互斥。容量测试(满配16 listener)是**无 h 的确定性配置存在性**——理论明确把它路由到「出辖区」、**不**走区间。GA-CUT 教训(`[[compile-quality-abc-three-layer]]`)同源:确定性映射(ga)固定落点合法、不该被当分布采样судить。**∴ 理论对、已 scope,非理论缺口,也非设计误用理论(§A/§② 都正确引 §0.5 的分布 scope)。**

### 6.2 实现层:**实现丢理论(轻·潜伏)——两条 scope 轴不重合**

- **理论的 scope 轴 = h-位置**(h-in-λ vs s₀ vs π vs 无h)。
- **S1 文本 / DESIGN §② 的 scope 轴 = 算法类型**(分布algo rr/wrr vs 确定映射algo ga/topology)。S1 原文:「this sample-vs-invariant fact is **the distribution class only**…Deterministic-mapping algorithms(ga/topology/rtt/hi)…fixed landing is legal」。
- **缝在哪**:两轴不重合。**「无 h」的容量/枚举类(满配N条、N个域名、端口枚举)既不是分布algo、也不是确定映射algo——它根本没有"算法"这一维**,落在 S1「distribution class only」这句**覆盖不到的盲区**。worker 面对枚举类时,S1 没有一句话说「这类不是算法采样、区间正则不适用、用逐条成员」。
- **叠加**:S1 给的是**手写**区间正则形态例 `Hit:\s+(2[89]|3[0-3])`,而 `EXCEL_FUNCTIONS.md:176`(pre-existing)明确「手写区间正则极易错→用 `dist`」——S1 未指向 `dist`,把易错形态当范例摆出。
- **判定**:这是**实现丢理论**——理论按 h-位置划界,S1 实现按算法类型划界,没把理论的「无h→非区间」这条边界保住。**但潜伏**:本案 worker 没穿这道门(§1 铁证:零援引分布/区间/dist),661986 的范围正则来自 attribution 指令而非 S1。

### 6.3 系统性风险:实测**低**,潜伏面**存在**

**实测(全 workspace/outputs 扫 `[d-d]` 范围正则断言):**
- 8 份 case.xlsx 含范围正则;**非分布上下文仅 1 份 = 667986**(且 attribution 驱动);其余 7 份均分布类(rr/wrr,区间正则合法)。
- **结论:worker 未系统性把区间正则套到非分布案。实现面未爆。**

**潜伏面(为什么仍要收):**
- 667986 是**存在性证明**:面对「N 个 X」枚举/容量意图,worker 会伸手抓范围正则压缩(哪怕这次是 attribution 点的火)。风险向量=任何多值/计数的容量/枚举测试。
- S1 + DESIGN §② 对这类**无一句 guard**——scope 停在算法类型轴,没接上理论的 h-位置轴。潜伏面不因「这次没爆」而消失。

### 6.4 完整回归面结论 + 收紧(闭合潜伏面,precautionary)

**S1 改动的完整回归面 = 一道潜伏的「实现丢理论」缝,实测未爆(1/8 且非 S1 驱动),但值得按理论轴补严:**
1. **S1/DESIGN §② scope 轴对齐理论 h-位置轴**:补一句陈述——「区间正则绑**分布采样的命中计数**(h-in-λ);容量/配置存在性/枚举类(满配N条、N域名——**无 h 的确定性**)验**逐条成员归属**(abs_found/found_times),grounded 在实际 show 回显格式,不用范围正则」。这把 S1 边界从算法类型轴挪到理论的 h-位置轴,消 6.2 的缝。
2. **手写区间正则→`dist`**:S1 区间形态例改指向 `dist` 组合子(框架确定性展开+守恒自检),与 EXCEL_FUNCTIONS.md 统一。
3. **回归锚**:worker prompt 结构门加「枚举/容量→逐条成员」「分布区间→dist 非手写」两锚;eval 反扫「非分布案不含 `[d-d]` 范围正则」(现基线=1/8,收后应=0)。

均陈述式、零写死命令、溯源理论 §0.5 + EXCEL_FUNCTIONS.md。**修法非本 bug 必需(本 bug 非 S1 致),是按理论轴闭合 S1 留的潜伏门。**是否落、由 team-lead 定。

STATUS: done
