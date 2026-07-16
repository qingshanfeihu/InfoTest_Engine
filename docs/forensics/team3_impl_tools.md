# team3 · 丙队实现交付(工具/文法/prompt/文档面)— A1/E10a/E10b/B1'/D8/H13/H14

> 所有权域:`batch_tools.py` / `verifiability.py` / `domain_grammar.{py,json}` / `compile-worker.md` /
> `THEORY_k_state_machine.md` / `DESIGN_dongkl_finalization.md` + 对应测试。
> 规格源:`team3_p0p1_specs.md`(六卡)+ `team3_design_challenge.md`(④迁移/E10a 模板/D9-D8)+
> `team3_theory_challenge.md`(§五 9 处修订+DS-4)。
> 回归:**`pytest tests/ -q` 2125 passed / 0 failed**(基线 2007+;含本队新增 27 例)。
> 完成:2026-07-16。zhaiyq 真机全程未触碰(零 SSH/零 dev_*/零按键)。

---

## 1. A1 · fail_signatures 结构化解析+迁移条款 ✅

**改动**(`main/ist_core/tools/device/batch_tools.py`):
- `_fail_signatures` 重写:逐行剥时戳(`_WA_TS_RE`)→ `_WA_CHECK_RE`(逐步形态)优先、
  **新增 `_WA_SUMMARY_RE`**(案末汇总形态 `… find: <pat>` 无 ` in:` 尾)兜底——实读 778072 发现
  Fail 汇总行不带 in 尾,规格「复用 _WA_CHECK_RE」单靠它会**漏掉全部汇总 Fail 行**,此为对规格的
  必要扩充;仅 `group(1)=="Fail"` 收(含 `Fail…successed to find`=not_found 断言失败,旧裸 grep
  按词面漏收的新增益),pattern 过 normalize 入集合。
- `_fail_signatures_legacy` 保留旧实现(兼容腿+开关回退);零结构化裁决行→回退+warning 留声。
- 开关 `IST_FAIL_SIG_STRUCTURED`(默认 1/开)。
- 三调用点(digest 显示/跨轮交集/落盘)拼接改 `"\n".join`(B1 分隔符)。
- **迁移条款**:导出 `normalize_fail_signature(sig)`(空白压缩+剥 ` in: <file>` 尾+重截 60,新格式
  幂等)。关键实读发现:batch_tools 内部跨轮交集(sig_now/sig_prev)**本就从原文现场重提取**、
  升级轮天然同格式——「旧∩新=∅」的真现场在引擎读**存量字段**处(`facts.py:169` verdict signatures
  交集、`nodes.py:1722-28` 跨床反驳),已广播甲队在比较前两侧过该 normalizer。盲区如实记:纯
  not_found 失败案旧格式没采到真 Fail 项,无从对齐→冻结迟一轮(fail-safe),下轮自愈。

**测试**(新 `tests/ist_core/tools/test_fail_signatures.py`,13 例):Success not_found 排除(B2)/
节头零污染(B1)/边界无跨段假行/时戳剥离/legacy 回退/Fail-notfound 新收/汇总形态/开关回退/去重/
normalizer 幂等+对齐/**dongkl 9 案实数据重提取等值**(skipif workspace 不在盘;本机实跑通过——
新签名==原文 Fail 裁决行集合逐案相等,零节头残留)。邻域保绿:perf_gates/window_audit/
fail_attribution/exec_failure_scan 21 例。

## 2. E10a · verifiability 客户端维 ✅(单源合流 2026-07-16 追加)

**键名冻结:`cross_client_landing` + 用户拍板形态 `form="captured_relation"`**(team-lead 冻结;
captured_relation 是 `compile_user_decision` 既有 assertion_form 值域成员,两层词汇天然对齐,
claim_kind 参数描述里已交叉引用)。

`main/case_compiler/verifiability.py`:CLAIM_KINDS 增该值;`check_verifiability` 增 ①b 分支
(样板=absolute_position 双岔):分布类算法 → `Verdict(False)`,reason=「轮转计数器跨客户端共享/
独立由设备实现决定,数学推不出『客户端N→池M』」,fix=改预期,notes 给可验等价(relation 断言/
按客户端分组 distribution——worker 可改写而非必问,防 ask 泛滥);**非分布算法→`Verdict(True)`+
手册/判例支撑 note**(777976 深层真机制=地址族过滤即确定性映射,红线「非分布类不误杀」语义保持)。
不加 n_clients 参数(claim_kind 已携语义)。

**分布/非分布判定的数据源(team-lead 核对项)**:E10a 分支复用的 `DISTRIBUTION_ALGOS` 是模块
**既有**元组(absolute_position/weight_ratio 既有分支同源)非新硬编码;本轮按 lexicon 单源纪律
**合流**——三处判定点改走 `_distribution_algos()` 从 grammar `algorithm_classes.distribution.methods`
现查(新算法=加 JSON 条目零代码),元组降为 grammar 不可读时的回退快照,快照↔grammar 一致性由
`test_distribution_algos_single_source` 锁(防双源漂移)。

## 3. E10b · 序列↔周期自洽 ✅(2026-07-16 按用户通用性裁决**返工**)

**返工前后对照**(违通用性红线的初版→终版):

| 维度 | 初版(被否) | 终版 |
|---|---|---|
| 适用域判定 | `if algo != "rr": 放行`——「rr=等权轮转」这条**算法语义进了 .py** | 参数改**周期语义类** `cycle_kind`:"uniform_rotation"(判)/"weighted"(不判)/"none"(不适用)/None·未知(fail-open);.py 内零算法名分支 |
| 算法名→语义映射 | 藏在 .py 字面量里 | 放**调用方**:工具壳 `_cycle_kind_from_algo` 从 grammar `algorithm_classes.uniform_rotation.methods` **数据现查**(首发 ["rr"];wrr/gwrr 交织语义、grr 组语义未上机钉死不入——不写死未证实文法,C7 钉死后加条目零代码),或 worker 语义抽取显式传 `cycle_kind`(优先) |
| algo 参数 | 判定键 | 仅呈报文案(keyword-only,`test_sequence_periodicity_algo_only_in_prose` 锁:同参任意 algo 名判定结果一致) |
| period 无效 | `Verdict(False, FIX_DESC)`(误杀) | **fail-open 中性放行、零建议**(周期未知剩余类模型无从建立,不猜不误杀) |
| 未知语义类 | 不存在该概念 | fail-open 平凡可满足、零建议(新测试锁) |

终签名:`check_sequence_periodicity(cycle_kind, period, found_idx, notfound_idx, *, algo="") -> Verdict`。
数学不变:uniform_rotation 下单成员占且仅占一个模 period 剩余类,可满足 ⟺ `∃r: found⊆r ∧
notfound∩r=∅`,O(P) 枚举;778012 形态恒假。advisory 定位不变(硬门化=把严格轮转假设走私进 A 层)。

**测试**(`tests/case_compiler/test_verifiability.py`,E10a+E10b+单源共 12 例):cross_client 分布
欠定/非分布不误杀/778012 恒假/可满足+平移不变/weighted·none 不判/**未知语义+period=None
fail-open 零建议**/**algo 只进文案**/P=1 边界/空序列+同号冲突/单源一致性/uniform 数据源。

## 3b. verifiability_tool.py 接线 ✅(team-lead 追加归属本队)

`main/ist_core/tools/device/verifiability_tool.py`:
- `compile_check_verifiability` 增可选参 **`sequence_json`**(单一成员视角按请求序 JSON 数组,
  元素 "found"|"not_found"|null)与 **`cycle_kind`**(worker 语义抽取传入,留空按 algo 走
  `_cycle_kind_from_algo` grammar 现查);claim_kind∈{rotation_order, absolute_position,
  new_member_last} 且开关 `IST_SEQ_CONSISTENCY_CHECK`(默认 1,壳层判——纯函数不读 env)开
  时附加跑;数学恒假→覆盖为 NEEDS_USER_DECISION,台账落独立 `sequence_periodicity` 条目
  (ordering_sensitive=true);可满足→主判定照常+附序列自查说明。
- `_cycle_kind_from_algo`:uniform_rotation.methods 命中→判;distribution.methods 命中非 uniform
  →None(fail-open,该算法剩余类语义未钉死);都不中→"none"(确定性映射,grammar distribution
  provenance 背书);grammar 不可读→None。
- docstring(LLM-facing 契约):claim_kind 枚举补 cross_client_landing(含 captured_relation
  形态对齐)、sequence_json/cycle_kind 用法——parse_docstring 拆进参数 schema,测试按 LLM 实际
  可见位置(args_schema properties description)断言。

**测试**(新 `tests/ist_core/tools/test_verifiability_tool_sequence.py`,7 例):映射数据现查
(rr→uniform/wrr→None/ga→none)/sequence 解析契约/恒假覆盖+台账/可满足不覆盖/开关+claim_kind
双门/未知 fail-open+显式 cycle_kind 优先/docstring 契约。

## 4. B1' · 文法层 co-required 类型 ✅

- `knowledge/data/compile_ref/domain_grammar.json` 增第 20 顶层键 `co_required_params`:
  `_provenance`(572708 双响应未钉死的空置理由+消费语义)+`_schema_example`(条目形态文档:
  id/trigger_statement/condition{param,values}/requires_pattern/scope/provenance{source,
  confirmed_on_device})+**`rules: []` 空置**(C7 上机钉死前不写死未证实文法)。
- `main/case_compiler/domain_grammar.py`:accessor `co_required_params()`(fail-open `.get` 链)
  +纯函数 `missing_co_required(rules, lines)`(风格同 dangling_references:trigger 语句命中∧
  condition 命名组值命中∧同行 requires_pattern 零命中→报 {rule_id, line, provenance};坏规则
  整条跳过)。condition.param=trigger 正则命名捕获组,缺省回退 `name` 组;IGNORECASE 一致。
- 消费(emit advisory 文本行)归 emit_xlsx_tool 所有队——非门、不拒绝、不进 lint 凭证判定。

**测试**(新 `tests/case_compiler/test_domain_grammar_co_required.py`,5 例):空 rules noop/缺键
fail-open/合成 rule 检出+带参不报/条件不中不报(rr 不误杀)/坏规则 fail-open+混排不干扰。
grammar 消费者(diagnose/bed_gate/lint_gates/lexicon)100 例保绿。

## 5. D8 · worker.md 分布构造事实段 ✅

`main/ist_core/agents/compile-worker.md` `<task>` 内三处增补(frontmatter/骨架不动,全部陈述式
现象+后果+why,零写死设备命令,零 `Hit:` 字面 token):
- **分布段末**:①跨客户端不必然共享全局轮转计数——「client N→pool M」在判例/手册证实前是分布类
  claim,`cross_client_landing` 证伪且 notes 携可验等价(改写通常可用,不必问);②计数器是待证
  事实(设备实证:服务成员而计数为零)——单一计数器不作唯一证据支点,证据面=「命中集合⊆存活
  成员」+「大样本累计占比」并用(593516/778072 末轮实机背书正例);③时序锚点:found/not_found
  排布须与声明周期可满足——**uniform-rotation 类 claim**(措辞类级化 2026-07-16:周期语义
  data-confirmed 于 grammar `algorithm_classes.uniform_rotation` 的类,非 rr 字面当规则)把
  per-member 序列交 `sequence_json` 做剩余类自查(778012 烧了三轮);未 confirmed 的类放行不判,
  但「未知不是跳过 grounding 的许可」。
- **探针段修洞**(原文「clean 设备也能看形态」对绑定依赖类命令不成立):两类探针路况——静态布局
  类 clean probe 可得;绑定依赖类 clean 探空,形态=先例/footprint/手册现查;**三路穷尽∧断言依赖
  该形态→欠定上报,不掷硬币**(593516「承认未知仍猜 p4」反例);**可改写为已知形态支点(如 dig 侧)
  →改写优先于上报**(防 ask 泛滥)。
- **新 bullet 会话保持残影**:保持超时后下一次落点由运行时定——验证轴=条目自身状态变化(清除/
  超时字段归位),「落到特定池」重新引入绝对位置陷阱(zhaiyq 实弹漂移)。

**门**:`test_prompt_structure.py` 新增 `test_compile_worker_distribution_construction_facts`
(8 承重锚:cross_client_landing/不共享计数/计数为零实证/命中集合/sequence_json/不掷硬币/改写
优先/运行时落点——防未来误删);既有 5 个 worker 锚测试+`Hit:` 禁令+skill 标准包门全绿(109 例)。

## 6. H13 · THEORY 修订(9 处+DS-4)✅

按 `team3_theory_challenge.md` §五文字直接采用,**零重编号**((14) 编号位保留):
1. **§五-1a** (47)「(36) 特例/推广」→**正交复合**(两键互不可导出+两问都要过)。
2. **§五-1b** (47) 判定函数④→**残差位阶**(不论 f;f 低 c 高叠加下游分解——claim_kind 语义分诊
   落此格,Brief1 第 5 条警告兑现,内部证伪事件如实记)。
3. **§五-2** 四条增补:**A2′** 挂 (47) 末(观察级判据换轴+broken 排除+归一化去重+成立域限定);
   **N1a/N1b/N2′/F11′** 挂 (40) 末(台账本体论字段分离/claim 级证据粘性替代硬单调/污染分歧=
   分辨实验缺失+contra≥2 既有界/对照差分 advisory 形态+窗口审计前置);**E10b** 入 (47) L_oracle
   实例列表(内容无关恒假→advisory,rr-only)。
4. **§五-3** (37) 两处引用口径注(Δ6/13 取校准后口径;pe1 降定性)。
5. **§五-4** (44) 边界增补挂 §2.12.3b 末(窗口源步 ¬ok⇒断言级 Broken,不进签名/归因/对照/观察库;
   F11′ 采纳前置;778012 `_round` 误标并入 A1 验收观察)。
6. **§五-5** §4「迄今最干净」→「锚差维度的极端演示」(执行靶混杂+定义性重言如实记;非平凡证据=
   413/453/493+迁移批)。
7. **§五-6** §2 保存族锚注(主根因后判窗口失真,证据力降位;定理独立支柱不依赖此锚)。
8. **§五-7** (14) 降注记(公式表编号位保留+正文降 §2.5.3 末注记——C14「无消费者降注记」自裁)。
9. **§五-8** E1「省 ~86%(算术推算未实测)」+§2.8「零复发(两批窗口)」。
**DS-4 数据修正**:`ds4_k_performance.jsonl` selfheal2 行 r1_hit=6/13(首跑口径)+caliber 字段;
pe1 行标 unverifiable;README 计数同步(ds1 20 案/ds4 4 点);THEORY DS-4 段记「数据文件已同步」
——「口径归一」指令从名义变为可执行。

## 7. H14 · DESIGN 补五节+顺笔 ✅

新 **§5**(追加尾部,零重编号)五小节:5.1 A1 结构化签名契约(含迁移条款);5.2 A2 观察级判据
换轴(含数据源限制+C5 绑定验收);5.3 co-required 类型(C7 前置);5.4 D9 brief 注入措辞(**成对
措辞强制**:标「未证实」必带「预期仍是期望值唯一来源,矛盾走呈报不得以观察值替换」——防反向
洗白;user_adjudication 不动);5.5 缺陷候选单机制(C20 三件套:attribute 透传/closing 产
defect_candidates.md+json 入对账/render 对齐+N1a 字段分离;实现归引擎队,验收锚=zhaiyq 532862
结构化单可见)。**§0.1 表**补 E10b 行(L_oracle-B,advisory 不硬拒)。**顺笔 D1/D2**:
`_flush_then_close`→`_gather_or_close`(两处,实现定名回填)、`_DOMAIN_TOKEN_RE`→
`_check_dns_label_limit`(已落地实况回填)。

---

## 跨队接缝(2026-07-16 终版——工具壳接线已归本队完成)

| 接缝 | 我方产出 | 接线方 |
|---|---|---|
| ~~E10a/E10b 工具壳~~ | **已本队完成**(§3b):docstring 枚举+sequence_json+cycle_kind+开关+grammar 映射 | — |
| E10a 题面 | claim_kind=`cross_client_landing`,form=`captured_relation`(冻结) | `questions.py` 归乙(其任务在案):新 kind 分支/非 generic 兜底 |
| A1 迁移 | `normalize_fail_signature` 导出 | `facts.py:169`/`nodes.py:1722-28` 归甲(team-lead 已转):读存量字段交集前两侧过它 |
| B1' 消费 | `missing_co_required` 检测器 | `emit_xlsx_tool` 成功路径 advisory 文本行(rules 空=天然静默,不急) |

## 通用性自证(用户裁决要求:零机制级领域知识入 .py)

逐个盘点本队全部改动中出现的领域词(算法名/命令名/设备词面),按四类归属——**机制级判定分支里
零领域字面**:

| 领域词 | 出现位置 | 归类 | 自证 |
|---|---|---|---|
| `#### (Fail\|Success) Num` / `fail to find` / `successed to find` | batch_tools.py 正则 | **协议格式**(框架裁决行,闭合于 mirror 框架版本) | 解析对象本身,非设备命令;同 `_WA_CHECK_RE` 既有性质 |
| `rr/wrr/grr/gwrr` | verifiability.py `DISTRIBUTION_ALGOS` 元组 | **回退快照**(单源=grammar 数据) | 判定处一律 `_distribution_algos()` 现查 grammar;快照↔grammar 一致性 `test_distribution_algos_single_source` 锁,漂移即红 |
| `"uniform_rotation"/"weighted"/"none"` | verifiability.py cycle_kind 值域 | **语义类词汇**(非算法名) | 描述主张的数学形态(等权轮转/加权/无周期),与具体产品算法解耦——新算法归哪类由数据/LLM 定 |
| `rr` | domain_grammar.json `algorithm_classes.uniform_rotation.methods` | **数据条目**(带 provenance:手册「均摊轮询」) | 文法层本职(数据随手册版本演进);wrr/gwrr/grr 未钉死**不入**(不写死未证实文法);新算法=加条目零代码 |
| `ga/hi/topology/rtt` | domain_grammar.json `algorithm_classes.deterministic_mapping.methods`(2026-07-16 新增) | **数据条目**(provenance 散文知识的机读提升——原 2026-07-08 手册取证文本逐字引) | 三分判定第二臂:分布→数学/确认确定性映射→改描述(ga 既有语义保留)/**未知→fail-open**(原 weight_ratio 分支把「不在分布清单」当「非分布」FIX_DESC=封闭世界假设误杀,本轮除);`test_unknown_algo_failopen_all_consumers` 锁全消费点 |
| `rr/wrr/ga` 等散见字样 | verifiability.py reason/notes、verifiability_tool.py docstring | **呈报/契约文案**(用户与 worker 可读的解释) | 不参与判定分支;`test_sequence_periodicity_algo_only_in_prose` 锁「同参任意 algo 名判定结果一致」 |
| `Hit:\s+[1-9]\d*\b` / `show sdns host pool` / `p1/p2/p3` | test_fail_signatures.py fixture | **测试夹具**(778072 保真回显形态) | 锚定解析行为的样本数据,非机制 |
| `sdns host method … wrr` | test_domain_grammar_co_required.py / test_verifiability_tool_sequence.py | **测试夹具**(合成 rule/接线锚) | 同上 |
| `dig 超时/tftp 失败` | THEORY (44) 边界补注 | **文档叙述**(执行失败形态闭集按引用指向文法数据) | 文档写机制,数据在 grammar `exec_failure_markers` |
| uniform-rotation 类级措辞 | compile-worker.md D8 增补 | **类级指引**(标注 grammar 数据源) | 既有 "(rr / wrr / grr / gwrr; `algorithm_classes.distribution`)" 列举为标注数据源的示例形态(既有文本);本轮新增文字零算法字面当规则 |

**E10b 返工前后对照**(违红线→合规):初版 `if algo != "rr"` 把「rr=等权轮转」算法语义写进 .py
判定分支;终版该知识只存在于 grammar 数据条目(带 provenance)与 worker 语义抽取,纯函数只认
语义类——机制(剩余类数学)与知识(哪个算法是等权轮转)彻底分层,同轴于「引擎不得向 LLM 注入
具体命令建议」裁决与 CLAUDE.md #12(数据按引用)。

## 理论/设计符合性(逐项引条款)

| 交付项 | 理论条款 | 设计条款 | 符合点 |
|---|---|---|---|
| A1 签名结构化 | K (40) 冻结语义(同签名两轮=换法——签名可信是其前提);N1b 补全叙述同域;(44) 边界补注(A1 断了空真进签名的 B2 路) | DESIGN **§5.1**(本轮新立契约节);§0.1 结构门(解析框架裁决行=结构化事实非关键字白名单,[[compile-judgment-structural-not-strongdict]]) | 签名从词面 grep 升为裁决行结构化解析;迁移 normalizer 保冻结跨版本连续 |
| E10a cross_client_landing | K (47) L_oracle-B(可证伪性工具回灌非硬拒)+A/B 分界(条件于外部事实→B 层) | DESIGN §0.1 表 L_oracle 行;§5.4 关联(brief 措辞教先证伪再报) | 分布类欠定呈报/非分布不误杀(verifiability.py 顶注红线,GA-CUT 防线) |
| E10b 序列↔周期 | K (47) L_oracle 实例列表(本轮增补:内容无关数学恒假→advisory,「严格轮转」模型类=设备行为假设,硬门化=走私 A 层——theory_challenge 1.7 裁决「采纳,钉死 advisory」逐字落) | DESIGN §0.1 分布形态位阶分解表新行(L_oracle-B) | advisory 双门(开关+传参);cycle_kind 语义类=零算法知识入 .py |
| B1' co-required | K (47) A/B 分界(参数语义=内容依赖判断,**不入** L_struct 硬门) | DESIGN **§5.3**;§0.1(advisory 非门);自愈四层文法层承诺(新坑=加 JSON 条目零代码) | rules 空置=不写死未证实文法(572708 双响应,C7 前置证据闸) |
| D8 worker 事实段 | K (37) 框定保真(注入事实非结论);§2.6.6 对称怀疑(计数器观察组语境);A2′ 成立域(clean 探针不可得知识→判例层) | DESIGN §1-A worker 指引(摆事实陈述式);§3.1 成对簿(checker_tool↔worker.md:零 `Hit:` token,`test_compile_worker_no_hardcoded_device_field_token` 门在) | 全陈述式现象+后果+why;8 承重锚防误删 |
| H13 九处修订 | theory_challenge §五修订文字逐字采用((47) 正交复合/④残差类/A2′/N1a/N1b/N2′/F11′/(37)口径/(44)边界/(14)降注记/§4 校准/锚注/窗口标注) | — | 零重编号((14) 编号位保留);DS-4「口径归一」指令从名义变可执行 |
| H14 五节+顺笔 | A2′/N1a/F11′ 的设计侧投影 | DESIGN §5.1-5.5 新立;§0.1 表补行;D1/D2 实况回填 | 缺陷候选单机制条文与 design_challenge ① C20 三件套逐点一致 |
| 单源合流 | — | lexicon 单源纪律(test_lexicon_single_source 同族:消费方读同一源防双源漂移) | DISTRIBUTION_ALGOS 判定处全部改现查,一致性测试锁 |

## 观察项(不改,记录)

1. worker.md 既有文本教 "`found_times` for a count" 与 emit 的 found_times 拒绝门表面张力——实读
   该句语境是 blocks/框架计数形态,非 check_point 方法名,且属近期已提交改动,不动;留给 owner 复核。
2. 778012 attr_evidence `_round=1` 而内容属第 3 次编写运行(轮次归属误标)——已记入 THEORY (44)
   边界补注,归 A1 验收观察族。
3. tests/ 全量最终 **2142 passed / 0 failed**(甲乙队测试并行合入后口径)——规格提及的
   test_batch_compile_tools 5 个 SSH 环境依赖失败本轮未出现(全过)。
4. **既有 flaky 两轮挖掘(第一轮归因错误,如实更正)**:
   - 初判「与 test_expectation_suspect 共享 autoid 900088 交错清扫」——错开 aid 后**复现打脸**
     (改后全量再挂同一断言),该归因证伪;aid 错开作为共目录卫生保留。
   - **真根因(铁证)**:`test_fanout_produced_field_probes_disk` 的 monkeypatch 目标
     `bt._run_skill_fork` 在 batch_tools.py **git 全史从未存在**(`git log -S` 零命中)——
     `raising=False` 把死 mock 掩盖成静默无效,该测试自写下起一直**真跑 execute_fork_skill**
     (真 LLM fork,违 team2 单测密闭化纪律);多数时候侥幸绿只因 produced 探盘独立于 fork
     结果,全量偶发红+异常长跑(190s vs 常态 ~80s)=真 fork 重试退避的墙钟。
   - 修=monkeypatch 改打**真实缝合点** `main.ist_core.skills.loader.execute_fork_skill`
     (compile_fanout 函数体内 import,调用时现取 loader 属性)且**去掉 raising=False**
     (名字漂移即炸,不再静默失效)。验证:全量 2144 passed / 0 failed,时长回落 54.83s
     (真 fork 墙钟消失的独立佐证),tools 目录复跑稳定。教训同型 [[working-style-evidence-first]]:
     症状复现=第一轮根因没找到,回头挖到能解释**全部**现象(含 190s 长跑)的那一个。
