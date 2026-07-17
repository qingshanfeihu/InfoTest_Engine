# 编译 V4:实证驱动的完整引擎(零未验证假设版)

> ⚠️ **历史存档（2026-07-17 归档,team4 docs 整编）**：V4 计划,步骤 0-5 已落地并被 V6→V8 两代取代;现役设计唯一权威=DESIGN_v8_engine.md。事实存档不删,现状勿引本文。

> **本 plan 自包含**;工作目录 `~/Library/CloudStorage/SynologyDrive-macbook/Project/InfoTest_Engine`,venv `~/.venvs/infotest-engine`。
> 前置:V2/V3 计划(`docs/PLAN_footprint_v2_compile.md` / `PLAN_v3_closed_loop_compile.md`)、数学骨架(`docs/linalg_formalization.md`)。
> **写作纪律:每一步都挂 2026-07-04 实测数字;"风险"栏只允许"已实证排除"或"有实证过的 escape hatch";验收全部机器可断言。**

## 〇、为什么有 V3 还要 V4(差距审计,全部实测)

2026-07-04 两轮全量实证(dongkl 34 case 各从零编译到上机):

| 实测事故 | 量化 | 根因(对照设计文档) |
|---|---|---|
| 重做率 72% | 34 case 编写 **120 轮**(9 轮最惨);1780 次 LLM 调用输入:输出 **47:1**,平均每次背 56k 上下文 | V3 步骤3(族摊销)未实现 + linalg §11 三路由未实现:每 case 都走"大残差全力 LLM" |
| worker 重犯上一轮已验证过的全部坑 | cname 语法/触发机网段/精确计数,V 轮全部复犯 | V3 步骤4(闭环写回)未生效:ρ_k 编译期不增长 |
| grade 统计无效 | grade 全 PASS → 上机首跑 **52.9% / 55.9%**(两轮一致);同卷 PASS↔CUT 翻案 5 轮 | linalg §9(isotonic 校准)从未做;§10 Cov(T,I) 未落地 |
| Hit 计数类 fail 占上机 fail 大头 | v10 首跑 15 fail 中 8 个是 Hit 区间/计数错 | linalg §8(checker 线性状态机)半成品搁置 |
| 必崩/必假形态反复出现 | 两天新增 8 道门、literal_\n 单病种 17 卷 | V3 步骤6(命题3.18 类型化构造)被实现成反面:生成后过滤,而非构造中不可表达 |
| **V3 公共契约在主路断裂** | **主路(compile_worker)产的 34 卷 provenance.json 数量 = 0** | V3 步骤1 只落在 pipeline fallback(ist_compile_draft),main-orchestrated 主路没接——步骤 2/4/5 全部因此名存实亡 |

**判定:不缺设计、不缺理论,缺的是 V3 灵魂步骤在主路上的落地。V4 = 把已论证的设计接回主路,每步先用盘上资产实证再动工。**

## 〇·一、本次调研实证清单(2026-07-04,全部盘上数据,零 LLM 成本)

| # | 调研 | 数字结论 | 对计划的约束 |
|---|---|---|---|
| A | 输入空间 | 三脑图 113 case、301 句,参数化后 133 种句式;**跨脑图句式精确命中 0%**,62% 句式只出现一次 | 意图理解**必须 LLM**(不可查表);模板化只在同脑图内成立 |
| B | 输出空间 | 34 卷 745 条命令 **80 种模式**(Top12=73%)、149 条断言 **46 种模式** | 决策→卷面可确定化 |
| C | 聚类工具 | 现有 `_intent_similarity` 在 34 真实 case 上聚出 **0 个族**(阈值 0.4/0.5/0.6 全单例)——**不可用**;**参数化首步句式**聚出 **14 族、25/34 被多成员族覆盖、最大族 12** | V3 步骤3 的工具选型必须纠正为参数化句式(纯代码) |
| D | 族内骨架重合 | 算法 12 族共同配置行占各卷 **45-51%**;show 6 族仅 **10-17%** | 摊销只对大族做;收益按 50% 计,不按空想 |
| E | 组合子完备性 | 5 个组合子(CONFIG / OBSERVE_ASSERT / CAPTURE_COMPARE / OBSERVE_ONLY / SLEEP)无损覆盖 34 卷 **307/309=99.4%** 结构单元;唯一异形卷(681841 孤立 check_point)恰是上机 fail 卷 | correct-by-construction 文法已被数据钉死;异形=坏形态的证据 |
| F | grade 信号(初测) | overall 单变量 ρ=0.158(弱);终态凭证的 caveats_n 有分离但受幸存者偏差污染 | 需时点对齐重测(见 I) |
| G | checker 输入 | v10 15 个 fail 卷 device_context:10 含完整 dig 序列、5 含 Hit 输出(digest 14k 截断所致) | checker 原型数据够;采集面需扩(保留完整观测序列) |
| H | 数据资产 | 198 个 run-*.jsonl(495M)完整记录每次 LLM/工具调用;490 个设备侧 junitxml | 时点对齐配对、轮次归因、行为回放全部可离线重建 |
| **I** | **grade 判别力(时点对齐,决定性)** | 从 run-jsonl 重建 **942 对**时点对齐配对(60 个上机批次,7-01~7-04):**凭证 PASS→上机 56% pass,凭证 CUT→53%——判别力 3pp,统计无效**;且 CUT+重做后上机通过率(53%)不高于未重做(56%),**重做循环零质量增益** | isotonic 校准不可行(零信号无法校准);**grade 必须移出主路**——它烧 ~40% token 提供 3pp 判别 |
| **J** | **组合子 round-trip** | 34 卷反解组合子→展开重建:**33/34 字节级等价**;唯一失败卷(681841 孤立 check_point)正是上机 fail 卷 | 步骤 2 的文法与展开器可行性钉死;异形形态=缺陷的互证 |

## 一、V4 引擎全景(IST-Core 原生,LLM 永远在环内)

```
main agent(编排)
 ├─ compile_prep + 族聚类(参数化首步句式,纯代码——实证 C)
 ├─ 族首 case:compile_worker 全力推导(大残差路,唯一背大上下文的位置)
 ├─ 族内 case:worker 轻量派发,brief=族骨架+差异槽(中残差路——实证 D:大族省 ~50% G 段)
 │     遇 rr/wrr 计数期望 → checker 工具算(实证 G;LLM 不猜数)
 ├─ emit:组合子构造入口(实证 E 的 5 组合子;悬空/字面\n/寄存器错在文法下不可表达;
 │     现有 8 道门反转为展开规则,门降级为 raw-steps escape hatch 的守卫)
 ├─ 机械 lint(已有,零 LLM;实测抓住全部必崩/必假)→ 直接合并上机
 │     【grade 移出主路——实证 I:942 对配对判别力仅 3pp,重做循环零增益;
 │      仅保留:上机 fail 后语义归因辅助 + 欠定/新形态升级用户前过滤】
 └─ ist_verify:上机=唯一 oracle → 四层归因(已有)→ 真 PASS 写回 footprint+先例库
       → ρ_k 单调升(定理3.22),下一脑图/下一族更快 —— 自演化闭环
```

红线不变(V3 §一):H_G≠0 的骨架选择永远 LLM;机制只动确定性信息流。

## 二、实施步骤(依赖排序;每步:改动 → 实证依据 → 机器可断言验收 → 风险状态)

### 步骤 0:把 provenance 接回主路(修 V3 断裂的公共契约;最小改动,最先做)
- **改动**:`compile_worker` prompt 的交付契约加"emit 必传 provenance_json"(emit 的入参**已存在**);`compile_emit` 对主路调用缺 provenance 时**拒绝**(与 grade 凭证门同型的 A 层强制——实证:prompt 约束在长上下文下必被遗忘,2026-07-02 零 grade 合并事故同理)。
- **实证依据**:审计发现主路 34 卷 provenance=0(调研⑤);emit 侧 `provenance_json` 入参与落盘逻辑已在(V3 步骤1 遗产);fallback 路径(ist_compile_draft)已在产,证明 LLM 产得出。
- **验收**:重编任意 3 个 case,`workspace/outputs/<autoid>/case.provenance.json` 存在且每步含 `layer∈{G,E,V}` + `source.kind`;缺 provenance 的 emit 调用返回 error。
- **风险**:已实证排除(两条路径都有存量实现);escape hatch=`IST_PROVENANCE_OPTIONAL=1` 回退旧行为。

### 步骤 1:grade 移出主路(实证 I 的直接推论;最大单刀 token 削减)
> 原设计是 isotonic 校准(linalg §9)。**942 对时点配对实测推翻了它的前提**:grade verdict 判别力 3pp(56% vs 53%)、CUT+重做零质量增益——零信号无法校准,只能移除。
- **改动**:主路改为 `组合子构造(步骤2) + 机械 lint(已有,实测抓住全部必崩/必假) → 直接合并上机(oracle,1 次 25 分钟,token≈0) → fail 按四层归因定向重做`。grade(ist_compile_grade)保留两个非主路位置:①上机 fail 后的语义归因辅助(现有归因流程的一部分);②NEEDS_USER_DECISION/新形态首现时升级用户前的过滤。凭证语义随之更新:`.grade_credential.json` 的必备字段从"grade PASS"改为"lint 通过 + (上机 pass 或 首编待验)",合并门与冻结门逻辑不变、判据换源。CLAUDE.md「交付门槛是 grade 断言质量」同步改为「交付门槛 = 机械 lint + 上机 oracle」。
- **实证依据**:调研 I(n=942,判别力 3pp;重做无增益);两轮实测 grade 开销 ≈40% token(66 次 score + 4.9 grep/fork + 翻案 5 轮);上机成本已被互斥/子集复测压到 1 次/轮。
- **验收**:①同脑图从零编译的 grade fork 派发数 ≤ 高危 case 数(欠定+新形态),而非 case 总数(基线 66 次);②上机首跑 pass 率不低于基线 55.9%(移除 grade 不劣化——实证 I 预言:无差别);③总 token < 基线 40%。
- **风险**:已实证排除"grade 拦住了更差产物"的反事实(CUT 重做后 53% vs 不重做 56%);escape hatch=`IST_GRADE_MAINPATH=1` 一键恢复旧主路。

### 步骤 2:组合子构造入口(命题3.18;治 72% 重做率的形态错误部分)
- **改动**:`compile_emit` 增 `blocks` 入参(5 组合子的 JSON 数组,调研 E 文法):
  `CONFIG{cmds[]} | OBSERVE_ASSERT{obs, asserts[]} | CAPTURE_COMPARE{capture_obs, obs, relation} | OBSERVE_ONLY{obs} | SLEEP{s}`
  代码展开为五列表(寄存器分配/换行/H-I 列/观测-断言排序全部由展开器保证);展开产物过现有 8 道门作**自检断言**(应零触发,触发=展开器 bug,直接 raise 而非返回 error)。`compile_worker` prompt 输出语言切换为组合子;`steps` 通道保留为 escape hatch(过全套门)。
- **实证依据**:调研 E(99.4% 覆盖)+ **调研 J(round-trip 原型已跑:33/34 字节级等价,唯一失败卷=上机 fail 卷)**;现有门的检查逻辑反转即展开规则(structural_gate 全部语义已实证)。
- **验收**:①round-trip 33/34 已达成(原型),工程化后全量保持;②对组合子入口做 fuzz(随机合法组合子 ×200),展开产物 lint_xlsx_case 全绿;③worker 重编 5 个 case 走 blocks 通道,emit 零打回。
- **风险**:文法覆盖不足 → escape hatch(steps 通道)已在且带门;非相邻 H 引用(681841 形态)判定:先按坏形态拒绝(该卷实测 fail),出现合法反例再扩文法。

### 步骤 3:族摊销(定理3.10;只对实证过收益的大族)
- **改动**:`compile_prep` 后加族聚类(参数化首步句式,调研 C 工具,纯代码);`ist_compile` 编排:≥4 成员的族(实证 D 中算法 12 族/show 6 族/lastresort 3 族)先派族首全力推导,族内 brief 附"族骨架(族首已验证的 CONFIG 组合子)+ 本 case 差异点(脑图 diff)";<4 成员的族走原路。
- **实证依据**:调研 C(14 族/25 覆盖)+ D(大族骨架重合 45-51%)。
- **验收**:①同族第 2 个起 worker 的输入 token < 族首的 60%(fastlog 可测);②族内 case 的 CONFIG 组合子与族骨架的重合率 ≥ 实证 D 值(45%);③总编写轮数 < 上轮基线 120 的 60%。
- **风险**:族骨架错则族内全错 → 族首必须先过 grade+校准 p≥0.9 才允许族内引用(串行依赖,墙钟代价实测 +1 族首轮,可接受);show 族实证仅 10-17% 重合 → 不做,已按 ≥4 成员且重合 ≥40% 的准入线排除。

### 步骤 4:闭环写回激活(定理3.22;V3 灵魂,机制已在只接触发)
- **改动**:`ist_verify` 真 PASS 后调 `writeback`:①provenance 里 G/E 段已验证事实 → `merger.merge_fact()`(evidence 门已防幻觉,机制实证存在);②整卷 → 先例库追加 + `build_intent_index` 重建。校准配对同时追加(步骤 1 的数据集持续生长)。
- **实证依据**:merge_fact/verified_count/reconcile 链路存在(V3 §二核实);V 轮 worker 重犯旧坑=写回不生效的反证。
- **验收**:①一次上机 PASS 后 footprint `verified_count` 增量 >0 且新先例可被 `compile_precedent` 检索到(同 run 内可测);②**同域第二脑图断言(2026-07-05 修订)**:写回后编译**同 CLI 域**的第二份脑图,首跑 fail 率低于该域首份脑图的首跑——ρ_k 的增长是按域的。原文写的是 dongkl(sdns pool/method 域)→yzg(listener/HA 域)跨域对照,2026-07-05 实测两域先例几乎零重合、yzg 首跑 fail 80% 全是新域问题(1 个跨 case 网络污染辐射 16 + 4 sancheck),跨域首跑不反映写回效度——该对照测的是"新域冷启动",不是"写回增益"。
- **风险**:写回污染 → 只写"上机真 PASS"(verdict 明细为准,与凭证门同源的机械判定);evidence 门拒无出处事实(existing 安全闸)。

### 步骤 5:checker 状态机工具(linalg §8;治 8/15 的 Hit 类 fail)
- **改动**:`main/case_compiler/checkers/rr_hit.py`:输入(算法, 权重[], 请求序列, 起点未知), 输出 Hit 的**可验区间**(起点不确定性下的 min/max——不是点值);工具 `compile_expected_hits` 暴露给 worker;worker prompt:计数类期望值必须来自该工具,禁手算。
- **实证依据**:linalg §8(理想模型已有,复现 48% 的缺口=事件抽取);数学核对——rr_hit_range 的区间是 linalg §8 闭式 h_k[i]=⌊(k-i-1)/p⌋+1 在起点未知下的包络(k=6/7/11/18,p=3 逐一验证包络正确)。
- **实际验收方式(2026-07-04 晚,偏离 PLAN 原文并升级,如实记录)**:PLAN 原计划翻 v10 旧 fail 卷回放,但旧卷的 dig 序列/插入结构不可控、Hit 输出被 digest 14k 截断(调研 G 只 5/15 完整)。改为**主动构造探针卷直接上机**(控制变量精确):rr 3池两针——6次/3池得 2/2/2(整除精确命中)、7次/3池得 3/2/2(∈[2,3] 且恰 1 池取上界),单段 6/6 池级样本命中;并发现新设备事实——**分段(show 插入后)11次分两段实测 5/3/3 超单段理论 [3,4]**,轮转态漂移,据此加 segmented 降级(治的正是上轮那批"dig→show→dig"分段结构的精确计数 fail)。wrr 沿用两轮实测配比异常结论(带复核条件,缺陷单落实后可恢复精确)。
- **验收**:①探针回放单段 6/6 命中(≥90%达标);②分段自动降级 low;③接入后重编 Hit 类 case 上机 Hit 断言 fail=0(待全量对照轮验)。
- **风险**:设备 wrr 行为与理论不符(上轮实证过配比异常)→ checker 输出带 `model_confidence`,低置信自动降级参与性断言(上轮人工决策的机械化,零新风险)。

### 步骤 6(贯穿):每步的回归纪律
每步落地即:pytest 全绿(当前基线 1491)+ 新增该步验收断言为永久测试 + 不动 V1/V2/V3 现有文件行为(新参数默认关)。

## 三、执行顺序与预算
0(接契约,半天)→ 1(校准,1 天,含配对提取器)→ 2(组合子,1-2 天,round-trip 是主工作量)→ 3(族摊销,1 天)→ 4(写回,半天)→ 5(checker,1 天含回放验证)。
每步完成即可独立产生收益,不存在"全部做完才见效"的悬空期。全程 LLM 成本≈0(调研已完成,开发验证全用盘上资产;唯一例外是步骤 2/3 验收里的少量真实重编,各 ≤5 case)。

## 四、不做的(带实证理由)
- 不做"句式→模板查表"引擎:跨脑图句式命中 0%(调研 A),查表只在同脑图增量场景成立(那是差异编译,已由凭证+短路覆盖)。
- 不用 `_intent_similarity` 聚类:34 case 实测 0 族(调研 C)。
- 不对 show 族做摊销:骨架重合 10-17%(调研 D),收益不抵族首串行代价。
- 不在运行时算信息论度量(V3 §五红线沿用)。
- 不让校准概率替代上机:oracle 唯一,校准只做路由。

## 五、步骤 7(2026-07-04 全量对照轮取证追加):编排数据面——载荷通道一致性

**盲区自认**:本 PLAN 的调研 A-J 全部聚焦语义/结构/token,没有一条覆盖「编排层的载荷传输容量」——隐含假设了 compile_fanout 能吃任意批次。全量对照轮(34 case,minimax)在此假设上崩:main 编排决策全对(识别族/规划 wave/主动构造 18-case briefs 文件),卡在 fanout 无文件通道,被迫内联 → 序列化截断 → 逐个派发 → 并发全失(20 分钟 6 卷)。跨版本同病:198 个历史 run-jsonl 里「截断 ×55/分批 ×34/太大 ×25」。完整评审见 `docs/REVIEW_payload_channel_gap.md`。

- **原则(横切,升为工程不变量)**:LLM 只走控制面(决策/判断/路由),数据按**引用**流(路径/autoid/凭证)——凡入参随 N 增长的工具必须有原生数组+workspace 文件双通道;凡批量出参必须落盘全文+内联只留摘要/尾部。LLM 上下文不承载 O(N×|payload|) 数据。
- **改动(已落地)**:①`compile_fanout` 加 `briefs_path`(workspace 围栏 resolve+is_relative_to,复用 emit steps_path 样板;通道优先级与 emit 同款:原生数组>文件>字符串;字符串截断报错指路文件通道);②fanout 出参超 2000 字符落 `outputs/<autoid>/fanout_<skill>.md`(非 autoid key 落 `outputs/_fanout/`),内联只留**末尾**(fork 机读尾块在末尾,协议不受影响)+`output_path` 指针;③`compile_emit_merged` **不加** cases_path——`autoids` 回读通道就是按引用的更强形态(引用=盘上成品卷),再加按值文件通道反而诱导误用;④ist_compile/ist_verify SKILL 写入引用路由纪律(>6 case 必走 briefs_path)。
- **验收(已固化为永久测试,test_fanout_concurrency.py)**:18-case briefs_path 全派发/围栏拒外/截断报错指路/原生优先/大输出落盘截尾且尾块完整/20×50k 出参总量有界(N 不变性)。

## 六、V4 验收总断言(全部机器可测)
1. 同脑图从零编译:总编写轮数 ≤ 48(基线 120 的 40%),总 token ≤ 基线 40%(grade 出主路 -40% + 族摊销 + 组合子零打回);
2. 上机首跑 pass 率 ≥ 基线 55.9%(grade 移除不劣化——实证 I 预言无差别;组合子+checker 应使其上升);
3. 上机 Hit 类断言 fail = 0(基线 8/15);
4. 跨脑图效度:yzg 首跑 fail 率 < dongkl 首跑 44%(写回生效的外部证明);
5. emit 打回次数 ≈ 0(组合子构造下门零触发;基线:literal_\n 单病种 17 卷);
6. 全量派发不退化:18+ case 单次 fanout 全派完(不因载荷截断降级成逐个);fanout 返回不撑爆 orchestrator(出参有界);
7. pytest ≥1522 全绿,V1/V2/V3 路径零回归(escape hatch:IST_GRADE_MAINPATH / steps 通道 / IST_PROVENANCE_OPTIONAL)。
