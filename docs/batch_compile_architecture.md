# 批量编译架构（整脑图 → 一个 excel）

## 背景

`ist_compile_batch` 是**唯一的编译入口**（2026-06-15 合并：原单条编排器 `ist_compile_orchestrate` 已删除）。无论用户要编译**单条** case 还是把**整个脑图文件**（含几十上百条 case）/ **多个 txt** 批量转成 excel，都走本 skill。逐条从头编译既慢又重复——每条都从头解析、查证、生成；`ist_compile_batch` 通读用例一次性解析出 case 清单，再按阶段把工作铺开给子流程，能并行的并行、必须串行的串行。**单条是 N=1 特例**：prep 出 1 case 的 manifest、draft fanout 并发度 1、merged 退化成单 case+哨兵，同一流程无需特殊分支。

输入：一个脑图文件（`workspace/inputs/automatic_case/*.txt`，mind-map JSON）。
输出：一个 excel（含该脑图全部通过的 case）。多个脑图 → 多个独立 excel。

## 角色与边界

主 agent 在 `ist_compile_batch` skill 下扮演**编排器**：只做解析、调度、判定、重做、合并、上报，**不亲自生成命令/上机/评分**。所有领域工作（查手册、查先例、生成命令、判分）都在 fan-out 出去的子 agent 内部完成。

编排器步数受 `recursion_limit` 硬上限约束。批量有几十上百 case，编排器**绝不能自己逐 case grep 手册 / 探设备 / 查先例**——那会在解析阶段耗光步数。每个脑图主循环应控制在十几次主 agent 调用内，省下的步数留给重做循环。

## 四个阶段与并行性（物理边界落在工具里，不靠自律）

> **2026-06-16 编译与上机验证解耦**：编译链只产出 excel（draft 生成 → grade 断言质量审批 → 合并打包），**不上机**。上机验证是独立环节，由 `ist_verify` skill 单独对成品 excel 做。原因：上机大面积失败常是设备环境瞬态（SSH 会话中断、dig 超时、DNS 解析失败），不该阻塞编译产出；把「上机通过」当成「进 excel」的硬前置，会让环境一坏就出不了任何 excel。

| 阶段 | 工具 | 并行性 | 为什么 |
|---|---|---|---|
| 解析 | `compile_prep` | 一次 | 脑图 → manifest（只含需求，零命令） |
| 生成 draft | `compile_fanout(skill="ist_compile_draft")` | **并发** | 查手册 + 本地 emit，不碰设备态 |
| 审批 grade | `compile_fanout(skill="ist_compile_grade")` | **并发** | 纯本地判分（基于先例/手册），零设备交互，不依赖上机裁决 |
| 打包 | `compile_emit_merged` | 一次 | 同脑图 grade-PASS 的 case 合并成一个 excel + 哨兵垫底 |

上机验证（独立环节）：`ist_verify` skill 对成品 excel 用 `dev_run_batch` 串行上机（框架全局锁，多 case 并发会互相污染设备状态），采集真实裁决，区分「真实断言失败」与「环境瞬态失败」，结果可回流重编译。

## 中间表示：manifest

`compile_prep` 把脑图解析成 `workspace/outputs/<脑图名>/manifest.json`：该脑图全部 case（**autoid 为主键，标题重名不去重**）的标题/分组/步骤需求/期望，以及分组链 `groups`。

**manifest 里 case 的 `init_commands`/`steps`/`assertions_provenance` 全部为 null**——这是刻意的：命令/参数/断言全部由 draft 子 agent 现场查手册/先例后回填，prep 只产「需求 + 分组 + 先例引用」。这是零硬编码红线的落地点。

分组（`group_path`）记录 case 在脑图里的父节点链，供编排器识别「组级共享基线」：如会话保持类脑图把基线抽到组外前置节点、组内 case 不重述，派发 draft 时要把该组共享基线需求一并写进每个 case 的 brief（只传需求描述，不传命令）。

## 版本校验（编译前必做）

不同产品版本对应不同 CLI 手册、不同命令语法。编译前必须先确定**目标产品 + 版本**（如 APV 10.5）。从用户请求原文提取；**用户没写就立即 `ask_user` 问**，不从 config 猜默认值——猜错会让整批用例查错手册、生成错命令。版本确定后推出手册 glob（`10.5` → `knowledge/data/markdown/product/10.5_cli__part*.md`），写进每条 brief 的「指路」。

## 交付判定（grade-PASS 即交付）

逐 case 按编排红线判定：
- **grade PASS（断言真覆盖目标行为）** → `status=done`，进合并打包。
- **grade CUT（弱断言/未覆盖）** → 携反馈（上一版 + grade 重做意见）重新派发 draft，回审批阶段。
- 连续 N 轮（建议 3）仍 CUT → `status=escalated`，**不拿弱产物充数**，记录卡点。

交付门槛是 **grade 断言质量**（弱断言/未覆盖仍 CUT，不救场），**不是上机 pass**。上机由 `ist_verify` 在产出后独立做——环境瞬态失败不挡 excel 产出；verify 发现的真实断言问题（非环境）可回流重编译。

## 已知约束与实证教训（2026-06-16 yzg 26 case 端到端实跑）

这些是真实上机暴露的硬约束，设计/生成时必须遵守（详见 `docs/yzg_grade_vs_run_audit.md`）：

1. **check_point 必须紧跟产生回显的命令（show/dig），不能跟在纯配置命令后**。配置命令（`cmds_config`/`cmd_config` 写操作）无输出，check_point 匹配到 `result=None` → 框架 `lib/check_point.py` 抛 `TypeError: expected string or bytes-like object`。draft 生成红线，emit 阶段宜加结构校验门拦截。
2. **框架对合并 xlsx 是「一个 case 崩溃中断整包后续」**，不跳过坏 case。实证：yzg 合并 xlsx 第 4 个 case（悬空 check_point）抛 TypeError 后，后续 22 个 case 全部 no_log（未执行）。故合并 xlsx 跑法依赖每个 case 都不崩；稳妥做法是 case 间隔离或先剔除会崩的 case。
3. **合并 xlsx 的正确跑法 = deliver 一次 + run 一次**（框架按 xlsx 顺序跑全部 case，各 case 子日志落 `ist_staging_<module>/<run的autoid>/test_xlsx/case.xlsx/<each_autoid>/`）。**不是**对每个 autoid 循环 deliver+run（那会重复跑整包 + verdict 张冠李戴）。
4. **grade（断言质量）与上机（能否跑通）正交**：grade PASS 的 case 上机仍可能 fail（如 dig 没解析到后端 IP——环境/解析链路问题，非断言错）。这印证编译/验证解耦的合理性——断言写得对 ≠ 当前环境能跑通。
5. **环境瞬态 fail 的识别**：`fail to find <IP> in:`（in 后为空 = dig 无有效响应）、`Socket is closed`、`connection timed out`、NXDOMAIN/SERVFAIL 多为设备/网络瞬态，ist_verify 应标注为环境失败、不回流重编译（重做 case 没用）。

## 相关文件

- 编译 skill：`main/ist_core/skills/ist_compile_batch/SKILL.md`（编排规范 + brief 五要素）
- 上机验证 skill：`main/ist_core/skills/ist_verify/SKILL.md`（成品 excel 上机 + 断言失败/环境失败分类 + 回流）
- 子流程：`main/ist_core/skills/ist_compile_{draft,grade,run}/SKILL.md` + `main/ist_core/agents/ist-compile-*.md`
- 解析工具：`main/ist_core/tools/device/compile_prep.py`（`compile_prep`）
- 批量工具：`main/ist_core/tools/device/batch_tools.py`（`compile_fanout` / `dev_run_batch` / `compile_emit_merged`）
- 子流程编排设计：`docs/case_compile_orchestration.md`
- 端到端实证审计：`docs/yzg_grade_vs_run_audit.md`
- 本轮重构汇总：`docs/compile_refactor_round_2026-06-16.md`
