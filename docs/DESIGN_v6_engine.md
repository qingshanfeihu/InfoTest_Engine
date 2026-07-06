# V6 编译引擎设计(1.0.5-beta.1)

> 状态:已落地并经三域对照轮验收(dongkl 21/34 重灾域 / yzg 25/26 / zhaiyq 51/53,编排事故 0)。
> 代码:`main/ist_core/compile_engine/`;资产包:`main/ist_core/skills/ist-compile-engine/SKILL.md`;
> 回退:`IST_COMPILE_ENGINE=0` → v5 main-orchestrated(`ist-compile` skill)。

## 1. 目标与判据

把人工测试用例(脑图)编译成断言真覆盖目标行为的 `case.xlsx`,并在真实设备上执行到不动点。

**交付判据(用户拍板)**:除「脑图与设备实际结构有争议、需人工决定」与「产品缺陷」外,其余用例全部能上机通过。达不到即架构问题,不做缝补。

**V4/V5 的教训制度化**:每步有机器可断言的验收门;过程事实一律落盘为结构化台账(散文不算数);已发生的事故形态要在数据层写不出来,而不是靠 prompt 叮嘱。

## 2. 三层栈与数据形态判定表(总纲)

langgraph × deepagents × opencode 谱系是**层**,不是竞争:

```
定义层(opencode 谱系资产): md = YAML frontmatter + XML 分节正文   ← 人写人审,可 diff
回合层(deepagents/create_agent): LLM 自由度孔 = 一张小图          ← qa 主 agent 与每个 fork
运行时层(langgraph): StateGraph / state / checkpointer            ← 引擎图、qa 图、fork 图同一地基
```

结合方式 = **图套图,薄工具衔接**:qa 图(会话)经薄工具 `compile_engine_run` 进程内 invoke 引擎图(流程);引擎的 [llm] 孔经 `execute_fork_skill → create_agent` 又是一张小图。工具边界隔离两图的 checkpointer/中间件/递归预算(langgraph 官方 agent-calls-graph-as-tool 模式)。

| 数据 | 载体 | 判定规则 |
|---|---|---|
| 身份/指令/白名单/孔位声明 | md(YAML+XML) | 人定义的用 md |
| 确定性流程(编排) | py:StateGraph(节点=纯函数,边=条件函数) | 流程是代码不是散文 |
| 过程事实/台账 | JSON(盘上,原子写) | 机器间传的按引用流,整份不进 LLM 上下文 |
| 进出 LLM 的数据 | XML 信封 | 标签是注意力锚(字符串 JSON 通道实证 73% 序列化失败) |
| 语义判断(场景而异) | skill(fork) | — |
| 单一正确做法 | tool(py;`@tool` 只是 LLM 接口皮,引擎直调 `.func`) | — |
| LLM | 只在孔里 | **永远不当胶水**——胶水是图的条件边 |

机械闭集(合法 E/F、execute 动作、框架保留字)一律从 `knowledge/framework/mirror/` 源码解析(`structural_gate.py` 的 `_public_methods`/`_execute_returning_actions`/`_framework_reserved_names`),不手抄——框架升级重解析即准。

## 3. 图拓扑

节点三类,注册表 `state.py::NODE_TYPES`(拓扑门断言 图↔SKILL.md↔NODE_TYPES 三方一致):

| 节点 | 类 | 职责 |
|---|---|---|
| prep | mech | 脑图→manifest;幂等 + dispatched 孤儿回收 |
| worker_fanout | llm | 派 `compile-worker` fork(brief 信封含预检索块/上轮修法/用户决策);探针重做 ≤3 |
| ask_decision | user | 欠定汇总 → 官方 `interrupt(payload)` 挂起问用户 → `Command(resume)` 落 `user_decision.json` |
| merge | mech | pass 卷面锁复核 → 首轮全量 / 修复轮 fail⊕produced 子集 / 收敛后终验整卷 |
| run_digest | mech | `dev_run_batch_digest.func` 上机;`run_marker{round,xlsx_mtime}` 幂等;verdict 晋升 |
| attribute | llm | known_defects 短路 → 机械预判(协议级事实) → `compile-attributor` fork 只填 undetermined |
| writeback | mech | 真 PASS 双写回(先例 + footprint 经 device_verified 第二权威源);行为知识候选晋升 |
| report | mech | `engine_report.json` + outcome 判定 |

条件边全部是 state 机读计数的纯函数(`graph.py::_after_*`)。关键路由语义:

- `_after_run`:有 active fail → attribute;子集全过 → merge(终验);整卷全过 → writeback(不动点)。
- `_after_attribute`:有重编集 → worker_fanout(重派集 ⊆ fail 集,ledger 审计强制);仅 transient → merge 复跑;**收敛于子集轮且有 passed → merge 终验整卷**(beta.1 修复:此前直接 writeback,主交付卷停留旧版、终验从未发生);全终态/封顶 → writeback 如实报告。
- 循环终止(不动点):全 pass;或非终态集空(剩余全为 frozen/product_defect/env_blocked/awaiting_user——恰为判据豁免集);或 round>max(默认 3)→ 如实报告。

## 4. 持久化与断点续跑

- 引擎独立 `SqliteSaver`(`runtime/compile_engine_checkpoints.db`),thread_id=`engine:<out_name>`,与会话 checkpoint 分库。
- 同参数重调薄工具即从 checkpoint 续跑;interrupt 挂起期间 turn 可以结束,下次调用经 `Command(resume)` 恢复。
- 节点幂等契约保证 resume 不重复烧设备轮;`engine_ledger.json` 相位级原子落盘作审计副本。
- `langgraph.json` 注册第三张图,Studio 可视化即活文档。

## 5. 防回退与防越权(数据层机器门)

- **EngineLedger 迁移合法性表**(`ledger.py::_LEGAL`):`passed → pending_compile` 非法(除 flip_evidence 豁免)——「修复轮把 pass 卷改坏」在数据层写不出来。
- **pass 即锁**:LOCKED_PASS 记录卷面 mtime;merge 前逐 passed 复核,变了拒绝合并交付(tampered 审计)。
- **派发审计**:每轮重派集合 ⊆ 本轮 fail 集合,违规抛错(引擎 bug 而非静默)。
- **先问后落**:`compile_user_decision` 要求 ask_user 台账中存在含该 autoid 的问答记录,否则拒——越权替用户拍板的机器门。

## 6. 质量门体系(交付门槛 = 机械 lint + 上机 oracle)

942 对时点配对实证:LLM 审 LLM(grade)判别力仅 3pp——不构成质量门。emit 过全部机械门即落结构凭证(source=lint)可合并;**语义终判在上机**。

- **emit 必崩门**(`structural_gate.py::check_crash_gates_mandatory`,无条件):收录标准=该形态上机保证崩整卷或恒真/恒假、**误判即真错**。含分发闭集、悬空断言、载荷完整性、寄存器引用、以及恒真/恒假断言族(行首/结尾锚、断言模式命中命令回显自身、零断言卷等——全部从 mirror 源码语义推导:`found/not_found` 为 `re.DOTALL` 无 MULTILINE,窗口=命令回显+数据+提示符)。完整门集与依据见该文件各 `_check_*` docstring(按引用,不在此抄清单)。
- **成品卷 lint**(`lint_xlsx_case`):反解成品卷复用必崩门全集+成品特有检查,挂凭证(`submit_verdict`)与合并(`compile_emit_merged`)双卡点——门只放编辑入口挡不住绕行(实证 `run_python` 直改卷面崩整卷)。
- **grade 凭证机械门**:合并校验每 autoid 在当前卷面(xlsx_mtime 精确签名)上有凭证,LLM 手写文件冒充不了。

## 7. 归因与修法生效性闭环

- 机械预判只认协议级事实(设备 `^` 语法拒、文件级崩溃签名);其余 undetermined 交 `compile-attributor` fork 读 `device_context` 原文判层(G/E/V/瞬态/产品缺陷),`submit_attribution` 落盘(evidence 必须原文子串,门校验)。
- **修法生效性**(beta.1 收口):last_run 按 autoid merge 时保留上一轮 `_attribution` 为 `_prev_attribution`;attributor 对重编后再 fail 先核对「上轮修法上卷了吗/同签名复现了吗」——方向已证伪禁同向再开(588691 实证:错误修法方向被连开三轮)。
- **frozen 语义**:连续两轮同签名 fail → `.frozen.json`(digest 落,重写保留 overrides 历史)。frozen ≠ 终态——是「重编必须换法」标记,emit 的 `override_frozen_reason` 门强制显式声明换法;终态 = frozen ∧ 轮次封顶。

## 8. 知识闭环

- **device_verified 第二权威源**:digest 每 case 落 `runtime/logs/verified_runs.jsonl`(agent 沙箱黑名单内,防篡改);footprint merger 三重校验(台账存在 ∧ verdict=pass ∧ 命令∈卷面)——解决「运行时命令不在手册 → 写回全 skip → 知识循环堵死」。
- **行为知识两段闸**:归因/编写中发现的设备行为经 `submit_behavior_fact` 落候选(observe_cmd∈卷面校验)→ 该 case 真 PASS 才晋升挂 footprint 叶节点。
- **构造式接口**:worker 用 `compile_emit(blocks=…)` 组合子 + `ref` 前缀(`footprint:`/`manual:`/`precedent:`/`config_derived`/`intent`)声明溯源,`expand_blocks` 机械组装 provenance——LLM 不拼 IR JSON。emit 打回率从 48-52% 降至 12-20%(`runtime/logs/emit_stats.jsonl` 持续量化)。

## 9. 性能护栏(实证驱动)

- run-identity 绑定:digest 对日志 stat mtime 早于本轮 deliver 基线的判 stale 不采信(旧日志假结果曾致整轮报废)。
- fresh-PASS 短路、fail 子集复测(全过后终验整卷一次)、上机互斥(进程锁+跳板机残留探测)。
- fork 弹性:`resilience.py::ForkExecutor`(AdaptiveLimiter + 900s 看门狗 + transient 重试);载荷通道(>6 case 派发走 `briefs_path` 文件通道,briefs 不流经 orchestrator 上下文)。

## 10. 与 v5 的关系

v5(main agent 当 orchestrator,`ist-compile` skill 文内编排)保留为 `IST_COMPILE_ENGINE=0` 的 fallback;`compile_pipeline` 是二级 fallback。E4 实验(pipeline 55.9% vs orchestrated 64.7%)证明提升来自 **worker 自由理解孔**,不来自「编排交给 LLM」——V6 据此保留孔、把编排收回代码。

## 11. 已知边界与后续

- 触发机 SSH 读窗串位(P1,框架层时序):双跑标注 `runtime_underdetermined` 顶着,根治需框架层命令间确定性同步。
- rr 调度行为(疑似 max_rr_count=2,P3):待一次探针卷实测后入行为知识并修 `compile_expected_hits` 模型。
- 诊断全景:`docs/DIAG_v6_shakedown_rootcauses.md`;历史演进:`docs/PLAN_v4_engine.md` → 本文。
