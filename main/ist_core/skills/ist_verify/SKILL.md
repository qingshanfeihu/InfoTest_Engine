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

# 上机验证：串行上机 + 四层归因 + 闭环写回

把已编译好的 excel 串行上机，采集框架真实裁决，对每个 fail 做四层归因按层回流，把上机真 PASS 的 case 写回 footprint。只验证、不生成、不改 case——生成 / 改归 `ist_compile`。

## 三个能力

0. **上机回填 `<RUNTIME>`（最先做）**：draft 对离线不可知的期望值（dig 轮转出的 IP、Hit 计数、会话值等）诚实留了 `<RUNTIME>` 占位（不猜）。verify 第一件事就是**用设备真实输出把这些占位填上并锁死**：
   - 这类槽位**首跑必 fail**（框架拿 G 去文本匹配，找字面 "<RUNTIME>" 当然找不到）——这是预期的"待回填"，**不是真实断言失败**，不要对它归因。
   - 回填值**只能来自设备真实输出**（本次上机明细 / `dev_probe`），抽不出就**如实留空、绝不猜**。
   - **锁死、不反复改**：`compile_runtime_fill` 只动仍含 `<RUNTIME>` 的格子，填完即不含占位符 → 永不被覆盖。一个槽位只填一次，填错也不会下一轮被悄悄改掉。

1. **四层归因**：v2 是三分（真通过 / 断言失败 / 环境失败）。v3 对每个 fail 用 `compile_attribute` 归到四层，按层定向回流——比"整条 case 打回重编"省得多：
   - G 错（命令非法 / 配置没生效）→ 回流重编 G 段。
   - E 错（dig 无解析 / 后端不通）→ 回流重绑 E 段（换可达 IP）。
   - V 错（有回显但断言期望值错）→ 回流重写 V 段断言。
   - 瞬态（SSH 中断 / 超时 / NXDOMAIN）→ 不回流。这类是环境抖动，和编译质量无关，回流也修不好。
2. **闭环写回**：上机真 PASS 的 case，把它 provenance 里的 G 段文法写回 footprint（evidence 门防幻觉）。footprint 越饱，下次同类 case 的 draft 越少啃手册。

## Principles

- 裁决以框架逐 check_point 的真实明细为准，不信 verdict 字符串——字符串可能把环境失败也写成 fail，掩盖真正原因。
- **失败必看「完整设备上下文」**：`dev_run_batch`/`dev_run_case` 对**非 pass** 的 case 会返回 `device_context`——里面是**设备配置会话原文**（每条 config 命令 + 设备真实响应，含 `Failed to execute X because Y` → 知道**哪条命令被拒/为什么** → 怎么改配置）+ **触发端 dig 真实输出**（ANSWER SECTION / 实际解析出的 IP → 知道**怎么填 `<RUNTIME>`**）。**改配置 / 填值 / 写回流 brief 都要基于它**，不要靠猜。
- 归因如实，不救场：不把环境失败粉饰成通过，也不把断言失败甩锅给环境。
- 只写回上机真 PASS 的 G 段。没 PASS 不写回；V 段断言、E 段具体 IP 不写回（它们依赖具体环境，进 footprint 会污染）。
- 上机串行（框架有全局锁），只走 `dev_run_batch`，不并发上机。

## 流程

### 1. 定位 excel + provenance
excel 路径或脑图名（→ `workspace/outputs/<脑图名>/case.xlsx`），确定 autoid 列表和 build。记下每个 case 的 `case.provenance.json` 路径（draft v3 旁挂；缺失则归因退化到只看裁决明细、不写回）。

### 2. 首跑（采集设备真实输出）
```
dev_run_batch(xlsx_path="...", autoids_json='[...]', module="<模块>", build="<build>")
```
返回每 case 的 verdict + 逐 check_point 真实裁决明细（含 `... fail to find <pattern> in : <设备真实输出>`）。
**含 `<RUNTIME>` 槽位的 case 首跑必有 fail**——框架找字面 "<RUNTIME>"，这是预期的"待回填"，**先别归因**。

### 3. 上机回填 `<RUNTIME>`（锁死，不反复改）
```
compile_runtime_slots(xlsx_path="...")   # 看有哪些待填槽位 + 各自前序观测命令(observe_cmd)
```
对每个槽位：从**首跑设备真实输出**里、该槽位 `observe_cmd` 那条命令的输出中，抽出真实值——
- 部分模式（`前缀...<RUNTIME>`）：只抽 `<RUNTIME>` 那一段的真实值（如前缀 `Hits:` 后的真实数字）。
- 整值 `<RUNTIME>`：抽该断言要测的那个真实落点值（如本次 dig 真实解析出的 IP）。
- **抽不出就留空**（该槽位不传、或 runtime_value 给空）——绝不猜。
```
compile_runtime_fill(xlsx_path="...", fills_json='[{"slot_id":"<autoid>#<n>","runtime_value":"<设备真实值>","evidence":"<输出片段>"}]', run_meta="build=<build>;task=<task_id>")
```
锁死写入：只动含 `<RUNTIME>` 的格子，填完即锁，后续不覆盖。

### 4. 复跑确认
回填后再 `dev_run_batch` 跑一次。回填的断言现在应 **pass**（设备值＝设备值）；
仍 fail 的才是**真实断言失败**（draft 把断言挂错了对象/前缀溯源错），进归因。
仍留空的 `<RUNTIME>` 槽位（抽不出）不算真实失败——如实记"待人工补值"，不归因不回流。

### 5. 四层归因
对**复跑后仍 fail**的 check_point（排除仍留空的 `<RUNTIME>` 槽位）：从 provenance 找该断言对应步的 `layer`，`compile_attribute(verdict_detail=<报错明细>, failing_assertion_layer=<层>)` → 拿 layer / reflow / target_layer。真 PASS 的 case 不归因，进写回。

### 6. 回流
- G/E/V 错：聚合成回流 brief（逐 autoid + target_layer + 裁决明细 + **该 case 的 `device_context` 原文**「设备对每条命令的真实响应 + dig 真实输出」+ 应改方向），`invoke_skill(skill="ist_compile", brief="只重编这些 case 的对应层，基于上一版改：<...含 device_context...>")`。**device_context 是重编的关键输入**——它告诉 draft 设备实际拒了哪条命令/为什么、dig 实际返回啥，draft 据此精准改（改配置 / 填 V 段值），不是再猜一版。
- 瞬态：标注「环境排查 / 换时间重跑」，不回流。
- 非交互（`infotest -p`）：直接输出归因 summary，回流作为独立步骤由调用方发起。

### 7. 闭环写回
对每个真 PASS（框架 pass 且断言真覆盖目标行为）的 case，读 provenance 把 G 段事实写回 footprint（`on_device_passed=True`）。报告写回了多少条（ρ_k 增长可观测）。
**注意**：上机回填的 `device_verified` 值（V 段断言里的运行时落点值）**不写回 footprint**——它是环境态、会随设备/会话变，进 footprint 会污染。只写回确定性可复用的 G 段命令文法。

### 8. 输出 summary
总数 / 真通过 / G错 / E错 / V错 / 瞬态 各几个；**回填汇总（填了几个 `<RUNTIME>` / 仍留空几个待人工补值）**；逐 case 一行（autoid | verdict | 归因层 | 是否回流 + 目标层 | 关键裁决明细）；footprint 写回汇总。报错如实贴出，不含糊。
