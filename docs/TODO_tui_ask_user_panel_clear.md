# 待修:ask_user 面板答后不清除(渲染残留)

> 发现 2026-07-14,run22 实况:run 开头主 agent 弹的"产品版本"面板已答(10.5 落盘、
> 引擎用它跑完 15 pass),但面板一直挂在 TUI 屏幕上,直到 gather 阶段仍未消失。
> 独立于当前 s₀/编译工作,非本次改动引入。**显示层 bug,不影响引擎逻辑**。

## 现象

`ask_user` 工具(主 agent 启动时问版本走的通道)弹出的面板,用户答完后**不从屏幕
消失**,与引擎节点 `interrupt` 面板(答完 resume 即消失)行为不一致。同屏后续真正
需要拍板的 `ask_decision` 面板(欠定/禁令机制题)会被旧面板视觉遮挡。

## 根因(已定位到行)

两类面板生命周期不对称:

- **引擎 interrupt 面板**:LangGraph `interrupt` 挂起 → `Command(resume=…)` 恢复,
  面板随 graph 状态自然消失。
- **ask_user 工具面板**:`reducer.py:750 _on_ask_user_request` 把 `BLOCK_ASK_USER`
  块 **append 进 `_messages`**(`:770`),但 `tools/ask_user.py::submit_answers`
  (用户答完回调,`ask_user_view.py:272-273`)**不发任何 answered/resolved 事件**
  → reducer 那条 ask_user 块永远无"已答"标记、永不移除/折叠 → 一直渲染。

即:append 有、对应的 dismiss 无。`grep ask_user_answered/resolved` 全仓零命中,
证实缺这条生命周期回边。

## 修法方向(任一)

1. **submit_answers 发 `ask_user_answered` 事件**(question_id + answers)→ reducer
   加 handler,按 question_id 把对应 ask_user 块标 answered(折叠成一行"已答:X"
   或移除)。与引擎 decision 事实入账对称(oracle 残差纪律:问了/答了都要留痕)。
2. 或 reducer 渲染时查 `tools.ask_user` 的已答集(question_id → answer),已答的块
   降级为摘要行。

推荐 1(事件驱动,与 ctrl+o/ctrl+t 重放一致——块状态进 reducer snapshot)。

## 验证锚

TUI/cmux 抓屏:ask_user 版本面板答完后应从活动区消失(或折叠成"已答"摘要),
后续 ask_decision 面板无遮挡。回归:`tests/ist_core/tui/`(reducer ask_user 块
answered 状态转移)。
