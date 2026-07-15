# [RESOLVED 2026-07-15] §18.13 用 equivalent-present re-key 溶解 claim_kind 路由。原始记录保留。


> 发现 2026-07-14 run22:写保存族(668000/015/030/044)F6 emit 门**拦住了**(编写期
> 欠定,零 s₀ 零 bed 面板——大目标达成),但 F6-ii 题面模板和 F8c 组一题折叠**没命中**,
> 用户看到 7 个标准欠定题(分 2 批 4+3),不是设计的"采纳等价方案"折叠题。

## 根因(定位到行)

三个部件的 claim_kind 不一致:
- **F6 emit 门** `_gate_forbidden_mechanism`(emit_xlsx_tool.py):读 `intent.json` 的
  `forbidden_mechanism` **盖章标记**(author `_stamp_intent` 落),**不依赖 claim_kind**
  → 生效,写保存族拒落卷。
- **worker 呈报**:走 `compile_report_underdetermined`,而 `verifiability_tool.py:152`
  **硬编** `_land_needs_decision(autoid, "verification_path_absent", …)` → needs_decision
  的 claim_kind 永远是 `verification_path_absent`,worker 报什么理由都覆盖不了。
- **下游题面/折叠**:`questions.py` 的 F6 分支 `all(k=='forbidden_mechanism')`、
  `nodes.py::_fm_meta` 的 `all(...=='forbidden_mechanism')` → claim_kind 是
  verification_path_absent 时**都不命中** → 走标准三选项题面、不折叠。

即:emit 门用盖章(权威),下游用 claim_kind(worker 填不进 forbidden_mechanism)。
`compile_report_underdetermined` 硬编 verification_path_absent 有其道理(它是通用的
"验证路径缺失"工具),不宜改它的默认。

## 修法(推荐:下游改认盖章,不改工具)

`questions.py` F6 分支 + `nodes.py::_fm_meta` + `verifiability_tool.py:239` 的
`_MECH_KINDS` 判定,从"claim_kind=='forbidden_mechanism'"改为**"读 intent.json 有
forbidden_mechanism 盖章"**——盖章是 author 侧权威标记,比 worker 填的 claim_kind
可靠(intent_save_variant/_gate_forbidden_mechanism 已是这个模式)。这样:
- 题面走 F6"采纳 worker 等价方案 / 用户另给 / 挂起"模板;
- F8c 把同(组,禁令族)的写保存族折成一题(668000/015/030/044 → 1 题);
- 同键采信/判例写回随之命中。

备选:compile_report_underdetermined 加 claim_kind 参数(worker 传),但要同步放宽
verifiability CLAIM_KINDS 闭集(评审 F6 时已标"路由勿走 compile_check_verifiability"),
改动面更大。

## 影响面(诚实)

**不影响正确性**:写保存族仍被拦、仍如实呈报、reason 里 worker 的配置面模型推理
可见(用户能据此判断);用户用 Other 输入即可采纳等价方案。**只影响题面体验**:
7 独立题 vs 4 折叠题、标准三选项 vs F6 等价模板。

## 验证锚

改后 run:写保存族欠定 → 题面含"采纳…等价实现"、gather 折成一题、facts 的
ask_shown 有 folded_into。回归:test_f8c_fold_and_adopt.py 的折叠用例改用盖章驱动。
