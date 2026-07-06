---
name: ist-compile-engine
description: "V6 编译引擎入口:一句话把脑图跑成已上机验证的 case.xlsx 交付——确定性状态机驱动整条闭环(编写→欠定问用户→合并→上机→归因→定向重编→循环到不动点→写回→报告),断点续跑。用户要「编译」「脑图转excel」「编译并上机」时优先用它。"
context: inline
user-invocable: true
source: hand
version: "1"
effort: low
when_to_use: |
  Use when 用户要把人工测试用例(脑图/txt)编译成自动化 case.xlsx 并完成上机验证交付。
  Examples: "编译 dongkl.txt"、"把这批脑图编译并上机"、"用例编译"。
  Trigger keywords: 编译, 脑图转excel, 编译上机, 用例编译, 闭环编译。
  SKIP when: 只对已有 excel 复验(ist-verify);只查一条 CLI(dev_probe);引擎关闭时走 ist-compile。
engine:
  graph: main.ist_core.compile_engine.graph:graph
  phases: [prep, worker_fanout, ask_decision, merge, run_digest, attribute, writeback, report]
  holes:
    worker: compile-worker
    attributor: compile-attributor
  tools: [compile_engine_run]
---

# V6 编译引擎(状态机驱动,LLM 只在孔里)

调 `compile_engine_run(mindmap_path, product_version)` 一次——整条闭环由确定性状态机跑完:
逐 case 派 worker 编写(机械门+探针自检)→ 欠定用例弹面板问用户(拿到答案才落决策,先问后落
是代码强制)→ 合并(凭证门+pass 卷面锁)→ 上机 → 归因(已知缺陷短路/机械预判/LLM 只填
undetermined)→ 只重编 fail 子集 → 循环到不动点(全过/全部标注/轮次封顶)→ 真 PASS 双写回
→ 交付报告。

- 产品版本没给就先 `ask_user` 问——版本错整批文法全错。
- 引擎被打断(进程死/设备忙)后,**同参数重调一次即从断点续跑**(checkpoint),已跑的设备轮不重烧。
- 面向用户的汇报用自然中文转述报告摘要;机读全量在 `workspace/outputs/<批名>/engine_report.json`。
- 返回带「升级人工」条目时,这些 case 引擎已穷尽机械路径(轮次耗尽/归因缺失),替用户定性等于把失败藏进报告——把每条的 autoid、原因、设备回显证据呈给用户,`ask_user` 拿处置(改用例描述/标注放弃/给修法方向再试一批)。
- 复述设备行为只引用返回里的回显摘录、engine_report 各 case 的 `fail_evidence`、或 `fs_read` 该批 `last_run.json` 的 `device_context` 原文;引用不了就先读再引,读不到就写「未取到回显」。凭上下文记忆重构的"回显"是伪证——曾把「设备不支持」复述成「执行成功」,还渲染出一段从未发生的配置会话(LangSmith 实证)。
- 工具返回 `engine_disabled`(IST_COMPILE_ENGINE=0)时,按 `ist-compile` skill 的 v5 编排流程执行。
