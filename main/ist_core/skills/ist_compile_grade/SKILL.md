---
name: ist_compile_grade
description: Slimmed grade subflow — judges ONLY whether V-segment assertions cover the requirement's target behavior, and VERIFIES the draft's Provenance IR (case.provenance.json) instead of re-grepping the manual from scratch. For each V-layer step it confirms the cited source actually supports the expected value; only falls back to grep when provenance is missing or suspicious. Structural validity stays the emit gate's job. Read-only. Invoked by ist_compile; takes a structured brief as $ARGUMENTS.
context: fork
agent: ist-compile-grade
user-invocable: false
---

# 语义审批（验 provenance，只判 V 段覆盖度）

评估下面这个 case.xlsx 的 V 段断言是否真覆盖需求要测的行为——靠核对 draft 记的来源，不从零 grep 手册：

- 读 `case.provenance.json`，聚焦 V 层步。逐条核对 `source.ref` 是否支撑期望值：`kind=manual` 就精确读那一处，`kind=precedent` 就 `compile_precedent` 看同类断言。只在来源缺失 / 可疑 / `kind=unknown` 时才回退满手册 grep。
- `compile_score` 判分，再对照需求核心行为做对抗性核对：断言覆盖的是动态 / 关系，还是只验了静态单点？
- 只判 V 段语义。命令合法 / 断言非悬空 / IP 可达归 emit 结构门，不归你。

## `<RUNTIME>` 占位＝诚实弃权，**不当弱断言砍**（关键）

期望值是 `<RUNTIME>`（标 `source.kind=device_runtime`）表示 draft 诚实声明"此值离线不可知，留给上机回填"。这是设计要的行为，**不是弱断言**。对这类步：
- **不要因为它没填具体值就 CUT**。它的真实值由 `ist_verify` 上机回填锁死，编译期本就不该有值。
- **要核它弃得有没有道理**：该值是否**真的**运行时才可知（dig 轮转出的具体 IP、Hit/统计计数、会话保持的具体值、哈希等）？还是 draft 偷懒——本可从手册/先例溯源的值也躲成了 `<RUNTIME>`？后者要 CUT，指出"这个值手册/先例里有，不该留空"。
- **看断言结构**：部分模式（`前缀...<RUNTIME>`）的**前缀**是否溯源可信、是否咬住了需求要测的行为？前缀空泛（如整行就一个 `<RUNTIME>`、却本可写出 grounded 结构）→ CUT，要求把结构写实、只留真正不可知的槽位。
- 整 case 全是 `<RUNTIME>` 且都弃得有理 → 仍可 PASS（上机回填后才是成品）；但要在结论里点明"本 case 待上机回填 N 个 runtime 槽位"。

结论给 PASS（真覆盖且来源可信，含"runtime 槽位弃权合理"）或 CUT（弱断言 / 未覆盖 / 来源对不上 / 该溯源的值躲成 `<RUNTIME>`，附具体到能改的重做意见）。证据引用 xlsx 行号 + `source.ref` + 需求原文。不自评、不重做、不上机。

## Brief from orchestrator

$ARGUMENTS
