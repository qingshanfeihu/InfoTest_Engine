# 收官审计:脑图→excel 引擎 V1→V4 遗留问题清偿与交付就绪(2026-07-05)

> 交付判据(用户定,唯一标准):**确定的事情,上机一遍做完;不确定的事情,和用户沟通明确后,一遍做完。**
> 本审计对照历代计划的"不做/风险/待查"原件(`runtime/logs/bare_experiment_issues.md`、`docs/PLAN_footprint_v2_compile.md` §七/八、`docs/PLAN_v3_closed_loop_compile.md` §五、`docs/PLAN_v4_engine.md`)与全部实证记录,逐条判:已清偿 / 机制在位待全量实证 / 未闭合。

## 一、版本递延链——每一版"留下的问题"去哪了

| 版本 | 当时明确留下的 | 归宿 |
|---|---|---|
| V1 裸写对照(2026-06-29) | 读错输入/发散翻无关库/token 失控(¥4.93 零产出);云盘 Read 瞬态 | ✅ `compile_prep` manifest 锁输入 + fork 隔离 + 编排轨道;瞬态重试 + 裸数字 marker 误判修复 |
| V2 footprint 补全 | **本轮不上机**(静态验收);手册 MinerU 截断→文法不全风险;意图相似度用词重叠(YAGNI) | 上机 → V3 又推迟 → **V4 直接把上机立为唯一 oracle**;截断→evidence 门+probe/先例双源(缓解非根治,见 §四);词重叠 → V4 调研 C 实测 **0 族证伪**,换参数化句式聚类(14 族) |
| V3 闭环 | **真上机闭环留 V3.1**(grade PASS 作临时写回门) | V4 步骤 1:942 时点配对实证 grade 判别力 3pp → **临时代理被数据废除**,换 lint+上机 oracle;写回门改认上机真 PASS |
| V4 引擎 | 调研 A-J 盲区:载荷传输容量 | ✅ 步骤 7 补齐(briefs_path/出参落盘截尾/横切原则),18+ 规模进永久回归 |

递延链的教训成立:**V2/V3 两次把"上机"推到以后,代理指标(grade)顶了两版,最后被 942 对数据证明是安慰剂**——正对应用户判词"只看数学模型/架构/最终结果"。

## 二、问题台账(错误/挂起/撞墙全类,26 条)

### A. 输入与编排失控
| # | 问题(实证原件) | 机制 | 状态 |
|---|---|---|---|
| 1 | 裸写读错脑图/翻无关培训表/1.6M token 零产出 | prep 锁输入→manifest;fork 框死单 case;编排轨道 | ✅ |
| 2 | 云盘 Read 瞬态;"429/502"裸数字误中 autoid 子串 | 重试 + 删裸数字码只认文字 marker | ✅ |
| 3 | loop_guard 软预算误伤(编译 ~14 case 停) | budget-only 温和提醒 | ✅ |

### B. 断言语义(撞墙最大户)
| # | 问题 | 机制 | 状态 |
|---|---|---|---|
| 4 | observe-then-assert / 写死单次命中 IP / 固定计数(778012 带病 PASS ×2 轮) | `compile_check_verifiability` 数学证伪 + grade_extract 确定性 suspects + lint 拒绝 + blocks/member/dist 正确形态 | ✅ |
| 5 | 恒真断言(无界数值正则) | 反恒真门 + 守恒自检 | ✅ |
| 6 | GA 被重做意见写死答案带进沟(3 case 连续 CUT) | prompt 红线:领域判断禁具体答案例;算法类型分诊 | ✅ |
| 7 | 有序语义静默降级(593516)/顺序锚被并组磨掉 | `ordering_sensitive` 台账 + ask_user 分组红线 + emit 出口机械核对顺序锚 | ✅ |
| 8 | 计数期望手算错(轮转态漂移/分段) | `compile_expected_hits`(设备回放实证包络 + 分段自动降级) | ✅ |

### C. 结构必崩
| # | 问题 | 机制 | 状态 |
|---|---|---|---|
| 9 | found_times 崩整卷 / dig(H) 后直接断言(39s 崩 pytest ×2 轮) / literal\n(17 卷) / 截断 autoid 进终卷 / `[^` 正则 / DNS 单标签 >63(994838 三轮) | emit 崩溃门全集 + 成品卷 lint | ✅ |
| 10 | orchestrator 直改 xlsx 绕过门 | lint 挂凭证与合并**双卡点**(门挂凭证路不挂编辑路) | ✅ |
| 11 | 双转义/组合子碎裂(逐字符拆 cmds) | blocks correct-by-construction:非法形态不可表达 + 碎片检测 | ✅ |

### D. 审批循环(翻案/烧钱)
| # | 问题 | 机制 | 状态 |
|---|---|---|---|
| 12 | 同卷 PASS↔CUT 随抽样漂移翻案 5 轮(拖 ~2h) | 翻案需行级新证据(工具拒)+ 上机型疑虑进 caveats 不构成 CUT | ✅ |
| 13 | grade 判别力 3pp、重复 grade 5-10M token 零增量 | **grade 出主路**(942 配对,用户拍板)+ fresh-PASS 短路 | ✅ |
| 14 | 长上下文把 grade 从 plan 遗忘、零审批合并 | 凭证机械门(xlsx_mtime 精确签名,LLM 冒充不了) | ✅ |

### E. 上机执行
| # | 问题 | 机制 | 状态 |
|---|---|---|---|
| 15 | 同 turn 连发 digest 并发互踩(三轮报废) | 进程内互斥 + 设备残留探测 + force_clean | ✅ |
| 16 | 收割旧执行日志(0/34、1/34 假结果→无效修复轮) | run-identity:deliver epoch 基线,早于基线判 stale | ✅ |
| 17 | O(N²) 逐 case 整跑、20min 无结果 | 整卷单跑 O(N) + case 数自适应超时 | ✅ |
| 18 | 整卷反复重跑(7 轮 ≈200 次多余执行) | fail 子集复测 + 节流提示 + 交付前整卷一次 | ✅ |
| 19 | "瞬态"下轮 100% 复现(5/5 误归);同法重编三轮 | 连续两轮同签名=冻结(重编必答 override_frozen_reason)+ 瞬态复现机械点名 | ✅ |
| 20 | 跨 case 重复 ip add→RTNETLINK 成批假 fail 伪装环境阻塞 | 框架 IP 恢复契约进 emit 门 | ✅ |

### F. 通道与上下文(跨版本根因)
| # | 问题 | 机制 | 状态 |
|---|---|---|---|
| 21 | 字符串通道 73% 拖尾;18-case briefs 内联截断→并发退化串行(截断×55/分批×34 全史) | 原生+文件双通道横切原则(emit 三通道 / fanout briefs_path / 出参落盘截尾);18+ 规模进永久回归 | ✅ |
| 22 | offload 大结果读得回用不上 | digest 工具内消化 + last_run.json 落 workspace | ✅ |
| 23 | 挂流(空 chunk 死挂)/TUI async 死锁/思考多轮 400 | fork 强制非流式 + RunnableCallable 双版本 + reasoning_content 回传 | ✅ |
| 24 | 30M 上下文打转;28k 摘要配置系死代码从未生效 | 死代码修正 + deepagents 默认摘要(撤出历史可回读)+ **工具结果剪枝**(先于摘要,保头可恢复)+ gating 常驻 -61% | ◐ 机制在位,长会话实证待对照轮 |

### G. 知识复用
| # | 问题 | 机制 | 状态 |
|---|---|---|---|
| 25 | worker 重复探/示例 IP 重犯 8 次/fork 零共享 | 预检索内联 + advisory 落盘引用 + 族摊销骨架(重合 45-51%) | ✅ |
| 26 | footprint 单遍漏命令(曾误判"LLM 抽不出") | strict function-calling + 证据门命令签名兜底 | ✅ |

## 三、对照交付判据

**「确定的事情上机一遍做完」**——链路:prep 锁输入 → 族摊销/先例/footprint 前置 → worker 单 case(组合子+checker+provenance)→ emit 机械门全过即凭证 → merged **一次** O(N) 上机 → digest 归因(G^ 直采/其余 LLM 读原文)→ fail 子集**一轮**定向重编(device 证据原文自动注入)→ 整卷确认。每一个历史撞墙点在链上都有对应的门(§二)。

**「不确定的事情沟通明确后一遍做完」**——链路:数学证伪 → NEEDS_USER_DECISION **汇总一次** ask_user(per-case 最小可验数/preserve_constraints/顺序语义显式)→ `user_decision.json` 机读落盘 → emit 出口**机械核对**断言形态与顺序锚(用户没批的降级出不了厂)→ worker 带硬约束重做**一遍**。兜底:escalate-when-stuck 诚实上报,不硬憋。

**「不信模型能力不够」**——全史每一次疑似"模型不行"最终都定位到确定性根因,有档:minimax 全量崩=载荷通道缺失(REVIEW_payload_channel_gap);footprint 漏抽=strict fc+证据门 bug;翻案=同知识散在 N 处漂移;误归瞬态=关键字表误杀(已删)。**零例外。**

## 四、未闭合(如实)

1. **【已闭合 2026-07-05】全量对照轮实跑验收(dongkl_v12,deepseek-v4-pro,IST_TOOL_GATING_ENABLED=1)**:
   - **首跑 34 卷:22 pass(64.7%)> 55.9% 基线 ✓;Hit 类恒真 fail = 0 ✓;5 轮上机零文件级崩溃 ✓**;
   - 七波+reflow 派发全走 briefs_path 文件通道,**零截断退化**(v11 崩点)✓;
   - 终态:**28/34 真 PASS(82.4%)**,交付卷合并、先例写回 20/28、footprint 写回 evidence 门正确拒运行时命令;
   - 6 个非 PASS 全部定性:**3 条产品缺陷候选**(DC-1 forward_only 手册 CLI20:379 vs 设备 ^ 拒;DC-2 wrr 家族 3 卷,手册 415 行 vs 静默忽略,kb_bug_search 未收录;DC-3 动态建池静默失败)+ 1 待复验(778041,修法已明确);
   - **判据兑现**:确定的事=首跑一遍+修复一轮+整卷确认一遍;不确定的事=2 次汇总问询 5 题,每题一次拍板一轮落地(用户决策门实战拦截过一次擅自降级 dist);
   - 成本:¥51.4 / ↑16.4M tokens(v10 mimo 时代同任务 ≈¥320/100M——约 1/6);
   - 过程中实证并修复 4 个新缺陷:emit 空载荷连败升级缺失、provenance 无文件通道、归因证据门转义误拒、fanout 空派发静默成功(均已落码+回归,下次进程生效);另记 2 个待修:先例写回 manifest 解析失败 8 例、TUI run_error 无粘性状态条。
2. 跨脑图效度(yzg 首跑 < dongkl 44%,V4 验收 4)与闭环写回 ρ_k 增长——都要第 2 个脑图的轮次才可观察。
3. wrr 设备配比与配置权重不符——**疑似产品缺陷**(外部),checker 已降级参与性并留复核条件,缺陷单落实后恢复精确区间。
4. MinerU 手册截断(98.8%)的文法覆盖上限——evidence 门+probe/先例双源是缓解不是根治;缺的文法按"标注而非编造"处置。
5. B 待办(低优):摘要模板/专用压缩模型定制(deepagents 工厂无入口,须动 harness profile);tool gating 对照轮后翻默认;grade 保留位(fail 后语义归因辅助)的增益未单独度量。
