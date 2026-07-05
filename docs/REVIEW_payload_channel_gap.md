# 评审:批量编排的载荷通道断层(跨版本根因,2026-07-04)

> 触发:V4 全量对照轮(34 case)20 分钟仅产 6 卷。逐帧看 minimax run-jsonl 发现——**不是模型问题,是设计假设了"批量入参/出参可以任意大",而传输层有硬上限。** 用户判断正确:"设计没考虑过大型输入的逻辑连贯性,跨版本一直存在。"

## 一、实况回放(run-6bf0673b6172.jsonl,minimax-m3)

main agent 的编排决策**全部正确**:
- 正确识别 F01(12 成员算法族)/F02(6 成员 show 族)+ 16 小族;
- 正确规划 wave 并发、处理 F01 head 的 NEEDS_USER_DECISION;
- **主动用 run_python 构造 18-case briefs 文件**规避大数组(思考原文:"Build the wave-1 briefs file (18 cases)")。

卡点(思考原文):**"JSON 字符串被截断了。让我用更小的批次派发。"**
根因链:`compile_fanout` 只有 `briefs_json`(内联),**无 `briefs_path` 文件通道** → main 构造好的 briefs 文件传不进去 → 被迫内联 18 个大 brief → 供应商序列化截断 → 退化成每次派 1 个 → 并发变串行 → 20 分钟 6 卷。

## 二、全量数据佐证(198 个 run-jsonl,跨所有历史轮)

挣扎关键词频次:**截断 ×55、重试 ×44、分批 ×34、太大 ×25、退化 ×20、无法解析 ×11**。
决策转折句(LLM 明说"因 X 太大所以改做 Y"),去重后每条=一个设计缺口:
- "脑图内容太大,我需要分段读取"
- "大结果文件在 sandbox 外无法直接读取,换个策略——用 head 分段读"
- "无法访问 main/ 目录下的脚本,手动用 Python 做等效分析"
- "681811 grade 根因反复截断需换设计"

**这不是本轮偶发,是每一轮都在发生、每次都在下游打补丁的系统性问题。**

## 三、通道完备性审计(40 个 @tool 全扫)

| 工具 | 大载荷参数 | 原生通道 | 文件通道 | 出参截断保护 | 缺口 |
|---|---|---|---|---|---|
| compile_emit | steps/blocks/provenance | ✓原生 | ✓steps_path | — | **已补全**(样板) |
| dev_run_batch(_digest) | autoids_json | ✓原生 | ✓ | ✓digest 消化 | 完整 |
| compile_runtime_fill | fills_json | ✓原生 | ✓ | — | 完整 |
| **compile_fanout** | briefs_json | ✓原生 | **✗ 无 briefs_path** | **✗ N 个 output 全文拼返回** | **入+出双缺** |
| **compile_emit_merged** | cases_json | 部分(autoids✓) | **✗ 无 cases_path** | — | 入缺(autoids 通道缓解) |
| **build_command** | values_json | ✗字符串 | ✗ | — | 小载荷,低危 |
| **compile_check_verifiability** | weights_json | ✗字符串 | ✗ | — | 小载荷(权重数组),低危 |

**核心缺口 2 个(高危)**:compile_fanout 入参(briefs_path 缺失)+ 出参(worker output 无截断,大结果撑爆 main 上下文)。

## 四、为什么跨版本没解决(设计层面的原因)

1. **补丁只打在被当场撞的那个工具上**:emit 撞过就加 steps_path,但同源的 fanout/merged 没跟上——缺"载荷通道一致性"这个横切原则;
2. **小规模测盖不出**:3-4 case 的 briefs 内联不会撞上限,一上全量(18+ 并发)才爆——测试样本规模不匹配真实工作负载;
3. **PLAN 盲区**:V4 调研 A-J 全部聚焦语义/结构/token,**没有一条覆盖"编排层的载荷传输容量"**——它隐含假设了 fanout 能吃下任意批次。这是计划思路的遗漏,不是执行问题。

## 五、修复(2026-07-04 已落地;根因,非补丁)

1. **横切原则(升为工程不变量,已写入 CLAUDE.md 工程红线 + PLAN_v4 步骤7)**:LLM 只走控制面(决策/判断/路由),数据按**引用**流——凡"入参随 N 增长"的工具必须同时有①原生数组/对象通道 ②workspace 文件路径通道(resolve+is_relative_to 围栏,复用 emit steps_path 样板);凡"批量出参"工具必须①落盘完整结果 ②内联只留摘要/尾部(复用 dev_run_batch_digest 样板)。LLM 上下文不承载 O(N×|payload|) 数据。
2. **compile_fanout 双向修复(已落地)**:入参加 `briefs_path`(通道优先级与 emit 同款:原生数组>文件>字符串;字符串截断报错指路文件通道);出参超 2000 字符全文落 `outputs/<autoid>/fanout_<skill>.md`(非 autoid key 落 `outputs/_fanout/`),内联只留**末尾**——fork 机读尾块(状态:/产物:/判定:)在末尾,orchestrator 机读协议不变,另回 `output_path` 指针。
3. **compile_emit_merged 不加 cases_path(决策修正)**:初版评审建议补齐,细看后推翻——`autoids` 回读通道本身就是"按引用"的**更强**形态(引用=盘上成品卷,数据零经手 LLM),再加按值的文件通道反而诱导 orchestrator 去凑 steps(SKILL 明令禁止的方向)。原则是"引用通道必须存在",merged 已满足。
4. **回归(已固化,test_fanout_concurrency.py +8 测试)**:18-case briefs_path 全派发、围栏拒外、截断报错指路、原生优先、大输出落盘截尾且尾块完整、20×50k 出参总量有界(N 不变性)——"全量规模"进测试,治"小规模盖不出"。pytest 1522 全绿。
5. **编排纪律(已写入 ist_compile / ist_verify SKILL)**:>6 case 的派发必走 briefs_path,briefs 用 run_python/fs_write 从 manifest/advisory 机械拼装(brief 正文不过 orchestrator 上下文)。

## 六、认知修正(评审中发现我之前的错误)

- 我此前说 `compile_footprint_writeback` "根本不存在"——**错**。它存在(`knowledge/footprint_writeback.py`)且已注册进 main_agent(:84)。真相:它是写回 footprint G 段的工具,ist_verify SKILL 流程从没在正路叫它(写回没生效的真因是**流程没调用**,不是工具缺失);V4 步骤4 我另加了 compile_writeback 写整卷先例库。
- **已理清(2026-07-04)**:ist_verify 步骤7 改为真 PASS **双写回**——`compile_writeback`(整卷先例库 mirror+意图索引)+ `compile_footprint_writeback`(G 段命令文法进 footprint,evidence 门拒无出处)。旧文本"待 provenance 语料成熟后接"的前提已被 V4 步骤0(provenance 必传门)满足,激活有据;个别旧卷缺 provenance 时工具自动跳过不报错。
