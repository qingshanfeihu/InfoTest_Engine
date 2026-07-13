# 机械门全景审计:已建/未建/理论数据锚/措辞校准(2026-07-14,run20 实证驱动)

> 触发:用户八问——还有哪些机械门、哪些构建、哪些门没做、有没有理论数据支持、有没有设计
> 文档、低于 90% 精度的判定有没有发硬断言、有没有摆证据讲事实、工具/prompt 是指路还是写死
> 结果。方法:双路全量清点(代码侧逐 file:line 核验 74 门;文档侧 DESIGN/S/infra/K 四文档
> 全读)+ run20 实弹交叉。本文是合成结论;两份原始清点的完整表格见文末附录指引。

## 0. 总判

- **已建机械门 74 个**,十域分布,几乎全部有测试锚、设计 § 锚、且 26 个量化可靠性数字
  钉住关键门的误差特性。
- **未建门存在四个层级**:理论已点名+实弹已演示(1 个,最高优先)、infra/S/K 三文档
  登记在案(约 25 项)、本次审计新发现(3 个)、以及"数据不支持故意不立"(1 个,纪律正面例)。
- **低精度判定的措辞校准是体系性的**(16 条条款+机械分档),本次抓到**一个活违例**
  (G6 固定归因话术)。
- **prompt/工具纪律"指路不写死"有 16 条明文条款**,代码核验 worker/attributor skill
  零写死设备命令;唯一注入通道(inverse_forms/destructive)符合"机械可推导/安全边界"
  两类允许项。

## 1. 已建门:74 个,十域分布

完整逐门表(file:line + 闭集 + 违例动作 + 测试锚)由代码清点产出,此处按域给计数与代表:

| 域 | 数量 | 代表门 |
|---|---|---|
| A. emit 崩溃门+成品 lint(structural_gate) | 19 | found_times 拒绝、锚正则必假、断言撞命令原文恒真、悬空断言、毁灭命令禁令、DNS 标签 ≤63、autoid 18 位 |
| B. τ 配对覆盖(tau_coverage) | 1 | create 型写须有同实体逆元步(inverse_forms 机械派生,缺数据降级三族词表) |
| C. emit 期门(emit_xlsx_tool) | 11 | 拓扑可达性×2、save/restore 配对 P0a-P1c、S6 命令存在性(呈报不硬拒)、frozen/override、user_decision 落卷核对、provenance 必传、lint 凭证铸造 |
| D. merge 凭证门 | 3 | 单案预检(凭证新鲜 xlsx_mtime 精确签名)、批量凭证、终卷再 lint |
| E. 上机门(batch_tools/mcp_client) | 8 | 进程内互斥、设备可达探针、残留 pytest 探测、autoid 全集校验、run-identity/stale_log(mtime≥deliver_epoch)、exec-failure ok(g)(pass→broken 降级)、跳板机全局锁、防截断保留行 |
| F. 引擎节点门(nodes/bed/facts) | 24 | bed_gate(build 锚+通道残留+**mirror 同步锚**)、基线面不自动删、G6 三连(s₀ 配对/跨床反驳/anomaly 否决)、occupancy 行级判定、common_cause、K 健康 fail-open(gate_disabled 显式入账)、终验幂等、s₀ 停车位、INV-2 残差硬停、三值 not_run≠fail、broken 连击升级、交付失败回滚半毒先例、S4 机械逆放+实体越界门、G3 污染者交付门、uncertain 入库范围门 |
| G. 裁决/brief 门 | 3 | panel token 路由、X8 载荷按引用、执行失败高亮 |
| H. 收口门(report_gate/render) | 3 | G5 独立重算(故意不复用 views,失配拒背书)、泄漏扫描、交付清单断言 |
| I/J. 回填锁+可证伪性 | 2 | `<RUNTIME>` 槽位锁(假回填拒绝)、claim 可证伪性检查(不可证伪→欠定上报) |

**文档-代码时差修正**:DESIGN §13.1 I3(mirror 同步锚)仍标"全无",实际已落
(`nodes.py:209` check_sync + `mirror_anchor.py`);§13.1 标记待更新。

**构建(非门的承重件)**:事件溯源 facts.jsonl(append-only,merge 幂等键)、ledger 状态
迁移合法性表、床账(created/restored 配对+维护日志通道)、K 健康度三面、blocks 组合子、
needs_decision/user_decision 结构化对、engine_report+G5 双算、footprint 双写回(verified
经 device_verified 门/uncertain 带语境)、判例先例库、fork 双层墙钟+流式双守卫。

## 2. 未建门(按证据等级排序)

### 2.1 理论已点名 + 实弹已演示(最高优先)

- **合取① 闭包检查 = 意图忠实门**(K §8 明文"emit 契约已有链,闭包检查未建")。
  run20 实弹:668030 脑图意图"执行 **write all** 后重启",worker 静默换成 `write memory`
  ——执行干净、结构合法、全部 74 门无一拦截,与 668000(本就是 write mem 案)机制撞车,
  write-all 覆盖轴丢失。**若非床污染恰好挡下,本案将以 write all 之名 PASS 交付假覆盖,
  且写回成 verified 先例(标题 write all、内容 write memory)反向污染未来检索——先例
  投毒路径**。候选形态:manifest 意图机制词(save 族 write all/net/file/mem 是文法层
  闭集)与卷面命令族的机械比对,不匹配→呈报(不硬拒,同 S6 姿势)。

### 2.2 本次审计新发现(代码级,小而实)

- **interactive_confirm 编写侧序列门**:文法数据已在(`domain_grammar` 槽位),但只有
  床清理在消费(bed.py:465 诚实跳过)。编写侧无门检查"触发交互确认的命令后必须跟确认步"
  ——write 族 YES 错位 9 连败的直接机械对应(worker 已自愈,门是防回归)。
- **G6 固定归因话术三连**(nodes.py:1074-1077):①"mechanical evidence sufficient"
  对 necessity_only 档(假阳 20-26%)同样硬说——**本清单唯一的活措辞违例**;②同段固定
  话提供 "tail placement" 路线,而 `_s0_pair` 注释(run11 实证)明说持久面毒源排尾无效
  ——代码自相矛盾;③该硬话流入重编 brief。修法:fix_direction 按 echo_support 分档渲染,
  持久面毒源时删 tail placement 路线。
- **G6 免派下的自愈链饥饿**:s₀ 前筛跳过深归因 fork → 无人写 behavior_candidates.json
  → uncertain 入库零输入——占用类设备行为观察(run13 缺陷形态)进不了 footprint。
  run20 三案全走此路径,footprint 增量为零。候选:G6 命中案由引擎机械落一条最小观察
  (占用行原文+语境),或对 echo_confirmed 案仍派轻量观察 fork。

### 2.3 文档登记在案的待建(择要;完整清单见 DESIGN §13.1/§15.1/§16/§11 与 K §8)

| 项 | 登记处 | 一句话 |
|---|---|---|
| L3 床基线恢复(批前 config save+批后恢复) | DESIGN §13.1 I1 | 需真机验证 save/restore 配对语义 |
| #67 取证归属一致性门(附件执行目标 vs G 列) | I2;infra E11 8.5% | 防御侧全无,切分本体另修 |
| quarantine 态(瞬态案不入交付分母) | I4;K §5.3 | fold 全函数性随动待定义 |
| 契约测试套件 tests/framework_contracts/ | I5 | 恒真门推导散在 emit 内 |
| flake 率指标 transient_rate | I7 | engine_report 无此字段 |
| L2 命名空间机械门(持久对象名 autoid 尾缀) | I8 | 现仅 C 层倡导 |
| 片4 D:remedies 队列自动执行+选项携判例证明 | §16.2 D | 机械半已落,LLM 观察者半待 |
| (41)④ TUI 多题提交保真门 | §18.8.1 | run15/17 两次 3 题丢 2 实证,登记待建 |
| 类型图 DAG(S1)→影响面闭包(S2)→层界判据(S3 影子) | §15.1 | 签名 3572/99.64% 已备,依赖边未构建 |
| 矛盾即问第三边/poisoned 拦截门/stale 派生/研发回流弧/φ(D) 提取器/^→? 接线 | K §8/§5.2 | K 面最密集待建区 |
| 时间轴 (34) | S §10 | **数据不支持故意不立门**——纪律正面例 |

## 3. 低于 90% 精度的判定 × 输出措辞审计(八问之六的靶心)

| 判定 | 已知精度 | 输出通道与措辞 | 校准判定 |
|---|---|---|---|
| s₀ 交换子配对 | 假阳 20-26% 理论自认(S §0.8 N2) | ①panel 题面:必要条件推断+echo_support 分档(echo_confirmed「直接佐证」/necessity_only「也可能是本案自身写法」)②行为面:不自动处置,交用户面板 | ✓(占用行级否定 2026-07-14 修) |
| 同上 | 同上 | ③attribution fix_direction:固定硬话 "mechanical evidence sufficient" | **✗ 活违例(§2.2)** |
| 难度预测器 | AUC 0.788(K §2.11.2) | 只定资源路由,明文「永不当质量门」 | ✓ |
| S6 命令存在性 | MinerU 覆盖上限 98.8%(截断静默漏边) | 呈报 needs_decision,不硬拒 | ✓(知道会漏边就不硬杀) |
| LLM grade 卷面质量 | 判别力 3pp(942 对) | **整条废除**,换 lint 凭证+上机 oracle | ✓(最彻底的校准:承认无判别力) |
| τ 覆盖 recall | 自我对抗天花板(C14) | G1 呈报+机械逆元建议,可用户裁决放行 | ✓ |
| uncertain 观察 | 未实证 | validity=uncertain+observed_under 语境,渲染标注,不冒充 verified | ✓ |
| 门数据面缺席 | — | gate_disabled 显式入账+报告 K 健康行,不静默 fail-open | ✓ |

体系性结论:**"低精度不发硬断言"是机械强制的**(verbatim 子串门/≥2 侧引文 schema/
G4 echo-back/G5 独立重算/oracle 残差公理「禁无痕吸收」),不是口号;本次唯一活违例
在 G6 固定话术,已列 §2.2 待修。

## 4. prompt/工具「指路不写死」纪律(八问之八)

明文条款 16 条(DESIGN §5.5 减法纪律「门在则 prompt 不教」、§6 自由度分层「LLM 永不当
胶水」、§18.4.1 命令注入禁令+两类允许项、§19.2 知识路由反转防框定效应、§12.6 模板库
死刑、K §2.7.2 (25)「LLM 只有触发权与组合权」、(37) 框定保真公理…)。代码核验:

- worker/attributor SKILL.md **零写死设备命令**(grep 全空,红线保持);
- 引擎注入仅两类:inverse_forms(手册签名机械配对,作用域恒等)+ destructive 禁令
  (窄桥护栏);`restore_leak_teardown` 类经验命令已按 2026-07-13 裁决整条删除;
- brief 引导全部是方向性("fault 在本案序列,检索同意图先例对齐形态"),不含具体命令;
- 遗留:blocks 组合子 prompt 形态说明不清(run19 观察,worker 系统性初漏 kind/pattern
  字段,门自纠不阻断——记录在案未改)。

## 5. 附录指引

- 代码侧 74 门逐行表:本次审计子任务产出,按域 A-J 编号,含 file:line/闭集/违例动作/
  测试锚;文法层消费面结论:domain_grammar 各键几乎全被消费,真正无人消费的只有
  `_provenance`(设计如此)、`inverse_forms.version`、`granularity`。
- 文档侧五节清点(A 门规格 38/B 量化数 26/C 校准条款 16/D 未建全量/E prompt 纪律 16):
  同批产出;两处文档-代码时差已在 §1/§2 修正标注。
- run20 实弹交叉:22/26 R1 pass;3 fail 全 s₀(占用形态,毒源=配置恢复回放案);
  668044/668059(9 连败写保存族)首版 PASS;668030 意图漂移(§2.1);三题面板挂起待答。
