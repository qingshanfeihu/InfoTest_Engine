---
name: ist_verify
description: "把成品 case.xlsx 串行上机验证的编排链。先上机回填 draft 留空的 <RUNTIME> 断言（用设备真实输出锁死，不反复改），再采集框架真实裁决，用 compile_attribute 把每个 fail 做四层归因（G错 / E错 / V错 / 瞬态，论文 §5.4）按层定向回流——G/E/V 错带层级反馈回 ist_compile 重编对应层，瞬态不回流。上机真 PASS 的 case 把 G 段文法写回 footprint。只验已有 excel + 回填 <RUNTIME>，不重新生成 case。对已编译好的 excel 做上机验证 / 上机回填 / 四层归因 / 闭环写回时用。"
context: inline
user-invocable: true
source: hand
version: "1"
effort: medium
when_to_use: |
  用户要对已编译好的 excel / case.xlsx 做上机验证、上机复验、跑一遍看结果、确认能不能在设备上跑通；含四层归因 / 上机回填 / 闭环写回。
  例："把这个 excel 上机验证"、"上机复验编译好的用例"、"上机跑一遍看结果"、"验证并按 G/E/V/瞬态归因"、"上机 PASS 的写回 footprint"。
  触发词：上机验证, 上机复验, 上机跑, 验证excel, 验证用例, 跑一遍, 复验, 设备验证, 四层归因, 闭环写回。
  跳过：要编译/生成新用例走 ist_compile；只查一条 CLI 回显用 dev_probe；评审用例文件质量但不上机走 test-list-review。
---

# 上机验证：串行上机 + 四层归因 + 回流交接

把**已编译好的** excel 串行上机一遍，采集框架真实裁决，回填 `<RUNTIME>`，对每个 fail 四层归因、按层 reflow 交给 `ist_compile` 重编。**只验一遍 + 交接修复**——不自己改 case（改归 `ist_compile`），也不自己套"验到全过"的迭代循环（迭代由上层：用户 / goal 循环驱动；本 skill 跑一遍即返回）。

## Inputs

- excel 路径或脑图名（→ `workspace/outputs/<脑图名>/case.xlsx`）+ autoid 列表 + build/module（缺省取 compiler config）。
- 各 case 的 `case.provenance.json`（draft v3 旁挂；缺失则归因退化到只看裁决明细、不写回）。

## Principles

- **裁决以框架逐 check_point 真实明细为准，不信 verdict 字符串**——字符串可能把环境失败写成 fail、掩盖真因。
- **失败必看 `device_context`**：`dev_run_batch` 对非 pass case 返回它——含 ① 框架逐步执行 + 断言明细 + case 内异常 ② 设备配置会话原文（每条命令 + 设备真实响应，含 `^` 语法错 / `Failed to execute X because Y` → 哪条命令被拒/为什么）③ 触发端 RouterA/RouterB/clientc dig 真实输出（ANSWER SECTION / 实际解析 IP）。`unknown` 的 case 还附 `framework_traceback`（**文件级崩溃**真因：某 case 把整份 pytest 搞崩、后续全不跑 → 先修 traceback 指的那一个，别误判后续 case 本身错）。**改配置 / 填值 / 写 reflow brief 都基于它，不靠猜。**
- **拿不准框架断言行为就读框架源码**（只读，沙箱已放行这两个文件）：`knowledge/framework/mirror/lib/check_point.py`（`found`=`re.compile` 当**正则**；`abs_found`=`re.escape` 当**字面**；`found_times` 需 3 参）+ `lib/test_xlsx.py`（check_point 分派只传 2 参 → `found_times` 必崩；带 H 的步只存寄存器不更新 `result`；`getattr(env,F)` 不转小写）。断言为何匹配/不匹配/崩，**以源码为准**。
- **归因如实，不救场**：不把环境失败粉饰成通过，也不把断言失败甩锅给环境。
- 上机**串行**（框架有全局锁），只走 `dev_run_batch`，不并发。

## Steps

### 1. 定位 excel + provenance

**Execution**: Direct

确定 excel 路径、autoid 列表、build/module；记下各 case 的 `provenance.json` 路径（缺失则归因退化到只看裁决明细、不写回）。

**Success criteria**: 路径 + autoids + build 就绪
**Artifacts**: xlsx_path, autoids, build, provenance_paths

### 2. 首跑上机

**Execution**: Direct

`dev_run_batch(xlsx_path=..., autoids_json='[...]', module=..., build=...)`——整份单跑一次，回每 case verdict + causality + `device_context`（非 pass）+ `framework_traceback`（unknown）。

**Rules**: 含 `<RUNTIME>` 的 case 首跑必 fail（框架拿 G 找字面 "<RUNTIME>"）——这是预期"待回填"，**先别归因**。
**Success criteria**: 拿到逐 case 真实裁决 + 失败 case 的 device_context
**Artifacts**: first_run_results

### 3. 回填 `<RUNTIME>`（锁死，不反复改）

**Execution**: Direct

`compile_runtime_slots(xlsx_path)` 看待填槽位 + 各自 `observe_cmd`；从首跑设备真实输出里该槽位 `observe_cmd` 的输出中抽真实值 → `compile_runtime_fill(xlsx_path, fills_json=..., run_meta=...)`。

**Rules**: 回填值**只能来自设备真实输出**，抽不出就留空、绝不猜；只动仍含 `<RUNTIME>` 的格子，填完即锁、后续不覆盖（一个槽位只填一次，填错也不被悄悄改掉）。
**Success criteria**: 能填的填上并锁死，填不出的如实记"待人工补值"
**Artifacts**: fills（已填 / 留空）

### 4. 复验 (when applicable: 步3 填过)

**Execution**: Direct

回填后再 `dev_run_batch` 一次。回填的断言现应转 **pass**（设备值＝设备值）；仍 fail 的才是**真实断言失败**，进归因。仍留空的 `<RUNTIME>` 不算失败、不归因。

**Success criteria**: 区分出 真 PASS / 真实 fail / 待补值
**Artifacts**: rerun_results

### 5. 四层归因

**Execution**: Direct

对复验后仍 fail 的 check_point（排除留空 `<RUNTIME>`）：先看该 case 的 `device_context` / `framework_traceback` 定位真因，从 provenance 取该步 `layer`，`compile_attribute(verdict_detail=<报错明细>, failing_assertion_layer=<层>)` → 拿 layer / reflow / target_layer。真 PASS 不归因，进步 7。

**Rules**: 归因必基于 device_context/traceback，不凭印象；瞬态（SSH 中断 / 超时 / NXDOMAIN）单列、不回流。
**Success criteria**: 每个真实 fail 有四层归因结论（G错 / E错 / V错 / 瞬态）
**Artifacts**: attributions

### 6. 回流交接（修复只走这一条路）

**Execution**: Direct（委派 fork）

把本轮**所有** G/E/V 错聚成**一个** reflow brief（逐 autoid + target_layer + 该 case 的 `device_context` 原文 + 应改方向），调**一次** `invoke_skill(skill="ist_compile", brief="只重编这些 fail case 的对应层，基于设备真实输出：<...含 device_context...>")`。

**Rules**:
- **修 case 的唯一正路 = `invoke_skill(ist_compile)`**（它内部确定性跑 `compile_pipeline`：prep→draft→grade→merge）。**绝不**自己手调 `compile_draft` / `compile_emit` / `compile_score` / `compile_precedent` / `compile_grade` / `compile_prep` / `compile_fanout`——它们是 `compile_pipeline` 的**内部步**，ad-hoc 乱调**不收敛、会把单轮工具调用撞到 recursion 上限（300）整轮崩**（实测反例：这样 churn 4 轮、excel 零改动）。
- **绝不 `fs_edit` case.xlsx**——二进制，文本编辑改不动；改 case 一律走上面的 reflow 重编。
- **瞬态不回流**——标注"环境排查 / 换时间重跑"，它和编译质量无关。
- 非交互（`infotest -p`）：直接输出归因 + reflow brief，reflow 作为独立步骤由调用方发起。
- **本 skill 到此即返回**：是否拿重编后的 excel 再 verify 一遍，由**上层**（用户 / goal 循环）决定——verify **不自己套循环**。

**Success criteria**: G/E/V 错聚成一个 reflow brief（或已 invoke 一次 ist_compile）；瞬态单列
**Artifacts**: reflow_brief

### 7. 闭环写回 footprint

**Execution**: Direct

对每个**真 PASS**（框架 pass 且断言真覆盖目标行为）的 case，读 provenance 把 **G 段文法**写回 footprint（evidence 门防幻觉，`on_device_passed=True`）。footprint 越饱，下次同类 draft 越少啃手册。

**Rules**: 只写回 G 段命令文法；**V 段断言、E 段具体 IP、回填的 `device_verified` 运行时值不写回**（环境态，进 footprint 会污染）。
**Success criteria**: 真 PASS 的 G 段已写回，报告写回条数
**Artifacts**: footprint_writeback

### 8. 输出报告

**Execution**: Direct（输出时禁止再调工具）

按下方结构输出：

```
### 上机验证 summary
- excel：<path> | build：<build> | 总 case：N
- 真通过 P / 真实 fail F（G错 a / E错 b / V错 c）/ 瞬态 t / 待补值 r
- 回填：填了 x 个 <RUNTIME>，留空 y 个（待人工补值）

### 逐 case
| autoid | verdict | 归因层 | reflow→层 | 关键裁决明细 |
|---|---|---|---|---|
| <id> | fail | V | →V | fail to find ... |

### footprint 写回
- 写回 N 条 G 段（autoid + feature_id）

### reflow brief（如有 G/E/V 错）
<逐 autoid + target_layer + device_context 摘要 + 应改方向>
```

**Rules**: 报错如实贴出，不含糊；最终输出时禁止再调任何工具。
**Success criteria**: 报告含 summary + 逐 case 表 + footprint 写回 + reflow brief 四段，异常项有根因
