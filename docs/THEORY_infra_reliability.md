# 基础设施可靠性理论：成熟范式的采纳、映射与边界

> 2026-07-12。缘起：yzg 十轮验收（run5-run10）约 80% 失败源于测试基础设施
>（床/框架/取证/通道），而非知识或语义——K 理论范式在该域**错配**（用户两轮质疑
> 定谳：自创认识论框架从第一性原理现推标准问题，每个解都造得糙）。本文档把该域
> 交还给已成熟 15+ 年的学科——**测试可靠性工程**（test reliability engineering），
> 按文献建立问题分类、检测器谱、环境谱系、运营模式与契约测试，并与 K 理论/行动论
> 划清接口。姊妹文档：`THEORY_k_state_machine.md`（语义域，见其 §2.8 边界声明）。

## 1. 范式定位：两个问题域，两套武器

| | 语义正确性域 | 基础设施可靠性域 |
|---|---|---|
| 核心问题 | 编译出的 excel 是否忠实验证意图 | 跑出来的信号是否可信 |
| 失效形态 | 假验证/意图漂移/知识过期/欠定 | flaky/污染/顺序依赖/取证失真 |
| 理论 | K 状态机（三合取/ask/判例/行动论）——**独创，文献无现成解** | **文献有 15 年积累的标准解，禁止现推** |
| 本项目实绩 | 达标（dongkl→yzg 迁移 23/26 首跑；成本 ¥47→17.6） | 十轮 80% 失败集中于此；补丁式响应 |

**采纳纪律**：本域任何新问题，先查本文档 §2 分类学对号——有标准解的按标准解做
（允许适配，禁止从零现推）；真正的新形态才升理论讨论。这是 engine-verify-loop
理论层的前置步骤。

## 2. 问题分类学（Luo et al. FSE'14 十类 × 本项目实证映射）

学界十类根因（[实证研究](https://mir.cs.illinois.edu/lamyaa/publications/fse14.pdf)，
Apache 项目 201 修复提交；跨语言分布：[Async Wait ~45%、Concurrency ~20%、Order
Dependency ~12%](https://arxiv.org/pdf/2101.09077)，Python 生态 Order Dependency 居首；
[SAP HANA 工业研究 2026](https://arxiv.org/html/2602.03556) 印证工业分布相近）：

| # | 类别 | 定义 | 本项目实证 | 已有对应物（评估） | 差距 |
|---|---|---|---|---|---|
| T1 | **Test Order Dependency** | 结果依赖执行序（污染者 polluter 改共享态未复位，受害者 victim 读到脏态） | 233 vlan 迁移→9 案超时（run7/9/10 三轮）；644 保存族单跑过连跑挂 | 矛盾谓词（∃pass@subset∧fail@delivery）=OD 的**结果侧**检测；床账快照 diff=污染的**状态侧**检测（PolDet 形态）；rerun_isolated=隔离验证 | 无污染者-受害者**配对**（谁污染了谁——iFixFlakies 的核心输入）；无主动重排检测（iDFlakies 形态：改变卷序探测 OD 案） |
| T2 | **Async Wait** | 用 sleep 赌异步完成 | 卷面大量 `time sleep 3`（配置生效/同步完成全靠赌） | 无 | 文献第一大根因（45%）；正解=轮询显式条件（配置生效的探针式等待）替代固定 sleep——emit 层可产「等待-验证」对 |
| T3 | **Infrastructure/Network** | 环境抖动、连接瞬态 | 探针单次 % Invalid（run8 床检误报源）；LLM 端点抖动 | probe_failed 判定；is_transient_error（传输契约层）；瞬态归因（复现即非瞬态） | 瞬态案缺 **quarantine 运营**（§5） |
| T4 | **Resource Leak** | 资源创建未释放累积 | segment `.conf.tmp` 尸体；SDNS 配置文件残留 | bed_check 残留探针+cleanup_refs | 已覆盖较好；增长机制待行动判例化（序③） |
| T5 | **Time** | 依赖真实时钟 | 框架 `system date` 写死；跳板机时差（run-identity 用同机时钟规避——已正确处理） | min_epoch/stale_log 门 | 基本覆盖 |
| T6-T10 | Concurrency/IO/Randomness/Float/Unordered | —— | 上机互斥锁已根治并发互踩;RR 轮询的随机性属**被测语义**（K 域的 claim_kind 处理,不是 flakiness） | 互斥锁/verifiability 工具 | 注意界线:被测系统的随机行为归 K 域,测试自身的随机性才归本域 |

**本项目特有的第十一类（文献框架的扩展）**：**取证失真**（evidence misattribution）——
per-case 采证切分错位（248 拿到 233 的 RouterA 输出，#67）。文献近邻是 test artifact
attribution；[Google 2026 已有 LLM 诊断集成失败的工业实践](https://arxiv.org/pdf/2604.12108)，
其前提同样是 artifacts 归属正确。见 §7。

## 3. 检测器谱（对标文献工具的形态，适配到床/卷面）

- **状态污染检测**（[PolDet 2015](https://experts.illinois.edu/en/publications/reliable-testing-detecting-state-polluting-tests-to-prevent-test-)
  形态：执行前后共享状态快照对比，26 项目抓出 324 污染者）→ 本项目床账快照 diff
  即其床版；**升级方向：粒度从批级到案级**（per-case 前后快照过重——上机时长×26；
  折中=可疑案定向快照：矛盾案/保存族案才做案级 diff）。
- **OD 检测**（[iDFlakies 2019](https://philmcminn.com/publications/parry2021.pdf) 形态：
  重排执行序对比结果）→ 我们的矛盾谓词是被动版（撞到才知道）；主动版=对交付卷做
  一次**逆序/随机序子集复跑**作为交付前烟测（一次上机换 OD 提前显形——成本与收益
  待评估，不默认开）。
- **自动修复**（[iFixFlakies 2019](https://www.researchgate.net/publication/335091960_iFixFlakies_a_framework_for_automatically_fixing_order-dependent_flaky_tests)
  思想：从既有 cleaner 测试提取复位代码）→ 我们的对应=归因反馈驱动 233 长出案尾
  自清（已走通）；判例化后同形态自动建议清理步（序③）。
- **污染者-受害者配对**：diff 实体 × 受害案触碰实体的交集（机械可算）——diagnose
  位（X3）的输入结构化，比自由聚类更强。

## 4. 环境谱系（hermetic 阶梯——治本方向）

[Google 的教科书结论](https://abseil.io/resources/swe-book/html/ch14.html)：共享可变
环境是 flakiness 温床，[hermetic ephemeral SUT](https://carloarg02.medium.com/how-we-use-hermetic-ephemeral-test-environments-at-google-to-reduce-flakiness-a87be42b37aa)
（每次跑起一次性隔离环境）是治本。本项目的阶梯与现状：

| 级 | 形态 | 本项目 | 升级代价/收益 |
|---|---|---|---|
| L0 | 共享可变物理床+顺序执行 | **现状**（文献反模式；十轮问题的物理温床） | —— |
| L1 | +状态守恒（快照/账/批后收敛） | 床账已落地（X11）——L0.5 | 已付 |
| L2 | +per-run 命名空间（案/批专属对象名前缀,冲突面收窄） | worker md 已倡导 case-unique artifact names（C 层） | 机械门化=emit 检查对象名唯一性,低成本 |
| L3 | +床快照/恢复（设备配置整体 save/restore per batch） | 未评估——**关键调研项**：APV 有无全量配置 save/restore 原语（手册查证,若有=穷人版 ephemeral,一条命令回到基线） | 中成本高收益 |
| L4 | ephemeral SUT（vAPV 虚拟设备,每批新起） | 未评估（产品是否有虚拟形态/license/资源） | 高成本,根治 |

**裁决待做**（工程评估,非理论）：L3 可行性查证是下一个最高杠杆动作——若设备支持
配置基线一键恢复，床账的角色从「恢复机制」退化为「审计机制」，T1/T4 全谱一次性
根治。

## 5. 运营模式（flaky 不清零，管理它）

文献共识：flaky 无法归零（[基准报告](https://testdino.com/blog/flaky-test-benchmark)、
Google ~16%），成熟做法是**运营**：

- **Quarantine（隔离区）**：判为瞬态/基础设施类失败的案，进隔离区状态——不占重编
  轮次、不污染交付信号、不反复烧归因；隔离区案单独小批复跑仲裁，恢复即出区。对应
  我们：suspended 态已具雏形，缺「瞬态自动进区+定期仲裁」的机械化。
- **Flake 率指标**：per-批 flaky 占比（瞬态归因数/总 fail）进 DS-4 型监测——趋势
  恶化=床/框架健康度报警，早于崩盘。
- **重跑预算**：瞬态仲裁复跑有全批预算上限（资源规则），防瞬态案吃光上机额度。

## 6. 契约测试：黑盒框架的行为钉住（替代「K_infra 判例」的正确形态）

框架是祖传黑盒，其暗行为（0.8 相似度模糊匹配吞命令、per-case 采证切分、IP 记账
恢复、清理只复位 slb/sdns 对象）此前散落在 CLAUDE.md/记忆/代码注释——**人和 Claude
可读，引擎不可执行**。成熟形态是 [Michael Feathers 的特征化测试](https://blog.nimblepros.com/blogs/characterization-tests-with-snapshot-testing/)
（characterization tests：钉住遗留系统的**实际**行为而非应然行为）+
[消费者驱动契约](https://microsoft.github.io/code-with-engineering-playbook/automated-testing/cdc-testing/)
（CDCT：以消费方的期望为契约）：

- **对 mirror 可离线跑的行为**（get_similar_function 的 0.8 吞命令、found/not_found
  的 DOTALL 语义、切分标记形态）：写成 pytest 特征化测试直接跑 mirror 源码——框架
  升级换 mirror 时**契约测试先行报警**，暗行为漂移不再靠撞。已有雏形：恒真断言门
  从 mirror 语义推导即此思想，但未组织成「框架契约测试套件」。
- **对必须上机的行为**（HA FIP 与静态同址、清理范围的真实边界）：契约=explore 级
  小实验卷（一次性上机验证一个行为断言）+footprint device_verified 记载——已有通道，
  纳入本框架命名管理。
- **主动考古纪律**：撞坑后修复必须回答「这个暗行为能否特征化测试钉住」——能而不钉
  =下次换个形态再撞（engine-verify-loop 实现层新增检查项）。

## 7. 证据完整性（取证链的可信性——(27) 的域内展开）

判断质量的上限是证据质量。取证链（设备回显→框架日志→staging 文件→digest 切分→
brief）每一跳都可能失真（#67 实证：切分错一格，归因 fork 拿邻案证据讲出灵异故事）。

- **归属一致性门**（机械）：采证文件中的执行目标（如 dig @IP）与卷面 G 列机械比对，
  不一致 → 「证据可疑」事实 + brief 如实声明「触发端取证疑似错位，勿采信该附件」
  ——引擎自己发现自己的证据坏了（#67 的修复形态）。
- **多源交叉**：同一事实的框架日志面与会话录面（smoke log vs RouterA.txt）互证，
  单源孤证降权。
- 原则：**取证器与审计器同样要被审计**（公式 (18) 的补全——审计器权威成立的前提
  是其输入可信）。

## 8. 与 K 理论/行动论的接口

- **床账**：既是 (25) 通路一的实现（行动论），也是 PolDet 形态的污染检测（本文档
  §3）——同一构件，两个理论视角，无冲突。
- **瞬态归因**：判定（复现即非瞬态）属本域；判定后的处置走 K 域的归因/重编流。
- **界线判据**：失效可被「换一个完美无缺的卷面」消除 → 语义域（K）；不能 → 本域。
  233 案两面都有：它的卷面该自清（K 域反馈可修），但「共享床上任何案都可能被前驱
  污染」是本域结构问题（hermetic 阶梯治）。
- **随机性界线**（§2 T6 注）：被测系统的随机行为（RR 分布）是 K 域的可验证性问题；
  测试自身的不确定性才是 flakiness。

## 9. 差距清单与优先级（按文献效果×本项目实证频次排序）

1. **#67 归属一致性门**（§7）——归因地基，影响所有批；
2. **L3 可行性查证**（§4）——一条手册查证可能改变整个治理策略的杠杆点；
3. **框架契约测试套件**（§6）——把已知暗行为（0.8 匹配/切分/清理范围/IP 记账）
   钉成可跑测试，存量知识一次性工程化；
4. **quarantine 机械化**（§5）——瞬态案自动进区+仲裁，省轮次省归因；
5. **Async Wait 治理**（§2 T2）——文献第一大根因，我们的 sleep 面还没系统清点；
6. OD 主动检测/污染配对（§3）——diagnose 位（序②）的结构化输入。

## 10. 证据索引（本项目实证 → 文献概念）

| 实证 | 文献概念 |
|---|---|
| 233 vlan→9 案超时（三轮） | state-polluting test（PolDet）+ order dependency（T1） |
| 644 保存族单跑过连跑挂 | order-dependent flaky（iDFlakies 检测对象） |
| run8 探针单次 % Invalid | infrastructure flakiness（T3） |
| 248 采证拿到 233 的 dig 输出 | evidence misattribution（§7，文献框架扩展） |
| 框架 0.8 模糊匹配吞命令 | 未钉契约的遗留系统暗行为（Feathers 特征化测试的对象） |
| 卷面 sleep 3 依赖 | async wait（T2，文献第一大根因） |
| segment .conf.tmp 尸体 | resource leak（T4） |
| 共享床+顺序执行 | 非 hermetic 反模式（Google ch14） |
