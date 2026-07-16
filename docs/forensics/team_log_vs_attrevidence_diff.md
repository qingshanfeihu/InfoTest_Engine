# 设备原始 log vs 归因提取物 attr_evidence.json —— 差异与信息损失取证

> 任务：拿设备原始 log 输出对比 `attr_evidence.json`（device_context / verdict / fail_signatures / anomaly_lines），找差异与信息损失，回答「attr_evidence 作为归因与审计的唯一留存证据源是否保真」。
> 范围：dongkl 9 个上机失败案（777976 / 778012 / 778041 / 778072 / 593484 / 593516 / 681749 / 572672 / 572708）。只读，零代码改动。
> 整理：2026-07-16。

---

## 〇、先读这段：信息损失发生在哪一层（决定本报告能对比什么）

数据链路（决定性认识）：

```
设备跳板机 staging（框架 inner.txt + apv 配置会话 + RouterA/B dig —— 唯一「完整原始 log」）
   │  ← 信息损失在此发生：fetch_device_context_under 每源只取尾部 ~2800 字符 + ≤12 行 marker
   ▼
dev_run_batch 的 rec{device_context, detail_tail, causality, anomaly_lines}
   │  ← _fail_signatures 在 merge 时算（causality+device_context 拼接，见缺陷①②）
   ▼
last_run.json（按 autoid merge）
   │  ← nodes.py:1390 逐字快照 rec（无二次截断）
   ▼
attr_evidence.json
```

**关键结论先行**：真正的「完整原始 log」只在跳板机 staging 上短暂存在（跑完即清），**离设备侧没有比 attr_evidence 更原始的副本**。`runtime/logs/run-*.jsonl` 是 LangGraph/Langfuse trace（`run_id/seq/kind/payload`，见下），其中的 `device_context` 出现 954 次，全部是**同一份已截断文本**——要么是 dev_run_batch 的 tool_result（双escaped），要么是 attributor 用 `fs_read` 读 attr_evidence.json 的带行号回显。核对：run-affdccca918b.jsonl 内 tool_result 的 device_context 与 attr_evidence 同源同形（`=== 框架逐步执行+断言明细+异常 (…txt) ===` 开头一致）。

> 所以「原始 log vs 提取物」的对比在**离设备层面无更高保真基准**。本报告据此拆成两问：
> (1) **截断损失**——per-source 2800 尾截，是否削掉了归因关键证据？（逐案实测：**没有**，见 §二）
> (2) **提取忠实度**——attr_evidence 的各字段是否忠实/干净地表达了它所截取的那份文本？（`_fail_signatures` **不忠实**，两个确认缺陷，见 §三）

生成侧代码（file:line）：
- 截断组装：`main/case_compiler/device_mcp_client.py:1083` `fetch_device_context_under`（`max_chars=14000`，5 源，`per=max(1500, 14000//5)=2800`，每源尾截 + `_KEEP` 正则 salvage ≤12 行 marker）；`:1034` `fetch_batch_details`（`max_chars_each=3500`）。
- detail_tail / anomaly_lines / device_context 装入 rec：`main/ist_core/tools/device/batch_tools.py:780-812`（`detail_tail=d[-2500:]`；`anomaly_lines=[...][:8]`）。
- `_fail_signatures`：`batch_tools.py:871-879`；被消费于 `:1163`（digest 人读表 note）、`:1199-1200`（跨轮冻结交集）、`:1225`（`.frozen.json` signatures）、`:1257-1258`（写入 rec._fail_signatures）。
- attr_evidence 落盘：`main/ist_core/compile_engine_v8/nodes.py:1387-1391`（`{**rec, ...}` 逐字 dump）。

---

## 一、逐案对照表

host 时间 = _run_ts（跳板机时钟）；设备回显时间戳 = 设备本地时钟，**比 host 快 +5h40m**（已知时差，见 §四·注）。

| 案(尾6) | verdict | 轮 | run_ts(host) | dc字符/段数 | 原始Fail/Success计数 | anomaly_lines | fail_sig脏? | 决定性归因证据是否存活 |
|---|---|---|---|---|---|---|---|---|
| 777976 rr | fail | 1 | 06:08 | 8273 / 4段(含触发端) | 8 / 6 | 7×`RTNETLINK…`(**全重复**) | 否 | ✓ `Hit:0`/`Hit:1`/`172.16.35.213` |
| 778012 新增pool rr | fail | 1 | 06:08 | 5974 / 3段 | 19 / 9 | 1×`Failed to execute` | **是** | ✓ RouterA `connection timed out`(dig全超时)+config`Failed to execute`(host未建) |
| 778041 改成员 rr | fail | 2 | 09:22 | 4651 / 4段 | 8 / 6 | 3×RTNETLINK+3×`^`ipv6拒绝 | 否(冻结签名干净) | ✓ `172.16.35.231`/`Hit:1`+ipv6`^`拒 |
| 778072 删pool rr | fail | 1 | 09:15 | 7275 / 4段 | 3 / 26 | 4×`RTNETLINK…`(**全重复**) | **是** | ✓ `Hit`区间/`p2`绑定 |
| 593484 wrr | fail | 1 | 06:08 | 6705 / 4段 | 7 / 3 | 0 | 否 | ✓ `Hit:0`/`Hit:2` |
| 593516 新增pool wrr | fail | 1 | 06:08 | 8250 / 3段 | 3 / 19 | 0 | 否 | ✓ `Hit:10`(p4主导)+`172.16.35.225` |
| 681749 ga | fail | 1 | 06:08 | 6113 / 4段 | 6 / 10 | 0 | **是** | ✓ `Service IP:172.16.35.225`(设备实返225≠期望213) |
| 572672 show域名算法 | fail | 1 | 06:08 | 4449 / ?段 | 12 / 6 | 2×`Failed to execute` | 否 | ✓ `priority must be…wrr`+`Failed to execute` |
| 572708 删域名算法 | fail(**layer=G**) | 1 | 06:08 | 4448 / 2段(**无触发端**) | 16 / 6 | 2×`Failed`+2×`^`拒绝 | **是** | ✓ `The priority must be an vaild value…"wrr"` |

**逐维小结**：
- **维度2（verdict 一致性）**：9/9 全 `fail`，且各案原始 `#### Fail Num` 计数均 ≥1，与设备 PASS/FAIL 记号一致——**保真**。
- **维度1（截断损失）**：9/9 案的决定性归因证据（配置拒绝行 / dig 超时 / 设备实际返回 IP / Hit 值）**全部在 device_context 存活**。原因：配置会话、触发端(RouterA)会话多在 2800 cap 下、**完整**；只有 inner 框架步骤日志（如 778012 段0=2850 命中 cap）被尾截，但其 check 裁决另存于 `causality`（末12条），`_KEEP` salvage 又兜住 `Failed to execute`/`^`/`RTNETLINK` 等失败 marker。**截断未系统性丢证据**。
- **维度3（fail_signatures）**：**不保真**，两个确认缺陷（§三）。4/9 案含脏签名。
- **维度4（anomaly_lines）**：见 §三·丙（去重缺失 + 排序风险）。
- **维度5（detail_tail vs device_context 分工）**：见 §三·丁（高度重叠冗余）。

---

## 二、维度1 实证：截断没削掉关键证据（举两案）

**778012（信息最富，8 dig / 19 Fail+9 Success）** device_context 分三段：
- 段0 inner（2850，命中 cap 被尾截）：Fail Num=6 / Success Num=3（尾部裁决）
- 段1 配置会话 apv_172.16.35.70（1911，**完整**）：含 `Failed to execute the command`
- 段2 触发端 RouterA（1213，**完整**）：`;; connection timed out; no servers could be reached`（dig 全超时→设备从未返回任何 IP）

→ 归因链「host 未建(config `Failed to execute`)→ dig 超时 → 找 225 全 fail」**证据齐全**，截断只削了 inner 前几轮 dig 的逐步回显（非决定性）。

**572708（layer=G，配置被拒）**：只有 2 段（inner+config，**无触发端**——因配置失败，dig 从未跑），config 段完整保留 `The priority must be an vaild value when the SDNS host method is "wrr"`——G 判层的决定性证据在。

其余案同样核对（§一表末列全 ✓）：681749 的 `Service IP:172.16.35.225`、593516 的 `Hit:10`、593484 的 `Hit:0/Hit:2`、777976 的 `Hit:0/Hit:1/.213` 均存活。

---

## 三、维度3/4/5 实证：提取忠实度的缺陷

### 甲、缺陷①（确认，提取 bug）——causality↔device_context 无分隔符拼接 → 段头融进签名

`_fail_signatures` 消费的是 `(rec.get("causality") or "") + (rec.get("device_context") or "")`（`batch_tools.py:1199/1200/1257`，`:1163` digest 同）——**字符串直接相加，无换行分隔**。而：
- `causality`（`batch_tools.py:781`）= 末12条裁决行 `"\n".join(...)`，每行 `rstrip()`，**末行无尾换行**；
- `device_context` **首行**恒为 `=== 框架逐步执行+断言明细+异常 (<autoid>.txt) ===`。

当 causality 末行恰好以 `fail to find: <pattern>` 收尾（框架把 check DSL 原样打进裁决行，pattern 常落行尾），拼接产生：

```
…#### Success Num 3: fail to find: 172\.16\.35\.225=== 框架逐步执行+断言明细+异常 (203031753342778012.txt) ===
```

正则 `fail to find:?\s*([^\r\n]{1,80})` 越过本应的边界，抓进**段头 + autoid 文件名**，产出脏签名：

| 案 | 脏签名（attr_evidence._fail_signatures 内实存） |
|---|---|
| 778012 | `172\.16\.35\.225=== 框架逐步执行+断言明细+异常 (203031753342778012.txt) ` |
| 778072 | `p2=== 框架逐步执行+断言明细+异常 (203031753342778072.txt) ===` |
| 681749 | `Hit:\s+[1-9]=== 框架逐步执行+断言明细+异常 (203031754277681749.txt) ===` |
| 572708 | `sdns host method "autotest1\.com"\s+"wrr"=== 框架逐步执行+断言明细+异常 ` |

坐实（778012）：`causality[-120:]` 以 `…fail to find: 172\.16\.35\.225` 结尾无换行；`device_context[:60]` 以 `=== 框架逐步执行…(778012.txt) ===` 开头；二者相加即上式。

### 乙、缺陷②（确认）——正则不分 Fail/Success，把**通过的 not_found 断言**收进"失败签名"

框架约定：`found` 检查失败记 `#### Fail Num: fail to find X`；`not_found` 检查**通过**也记 `#### Success Num: fail to find X`（"成功地找不到 X"）。`_fail_signatures` 只 grep `fail to find` 字面、**不 gate `Fail|Success` 前缀**，于是把通过的 not_found 断言 pattern 也计入失败签名集：

| 案 | `Success Num…fail to find`(not_found**通过**) | `Fail Num…fail to find`(found失败) |
|---|---|---|
| 778012 | 6 | 13 |
| 778072 | **4** | **2** ← 签名被通过检查**主导** |
| 681749 | 5 | 4 |
| 572708 | 4 | 11 |

778072 最刺眼：其 `_fail_signatures` 里 `p2` 类信号更多来自**通过**的 not_found 检查，而非真失败。

**附带噪声**：每个真 pattern 还派生一个 ` in:` 尾巴条目（如 `172.16.35.231` + `172.16.35.231 in:`），因裁决行 `fail to find X in: <cmd>` 与 check spec 行 `fail to find X` 各出一条——签名集条数被无谓翻倍。

**缺陷①②同根**：`_fail_signatures` 是对拼接文本的粗 grep，而非解析结构化 `#### (Fail|Success) Num` 行（代码里 `_WA_CHECK_RE`@`batch_tools.py:947` 已有现成的结构化正则可用）。

**影响面**（`_fail_signatures` 四处消费）：
1. **attr_evidence `_fail_signatures`（审计留存）**——审计者读到嵌了管线管道文本 / 掺了通过检查的签名，无法据此判定真正失败的断言，也无法跨案/跨轮机械比对。
2. **跨轮冻结 `sig_now & sig_prev`（`:1201`）**——脏签名含**常量** autoid 文件名，可能制造假交集（不同失败被判"同签名 fail"→ 误冻结）；反之末行行序在两轮间漂移则真同签名漏判（该冻的没冻、该换法的重复同法）。语义混淆更可能把冻结**钉在一个通过的 not_found 断言**上。
3. **`.frozen.json` signatures（`:1225`）**——冻结证据同样被污染。
4. **digest 人读表 note（`:1163`）**——显示层同样脏。

**本轮实际后果（限定）**：4 个受害案（778012/778072/681749/572708）皆 round1，**无上一轮可交集**，故脏签名未触发错误冻结；全仓仅 2 个 `.frozen.json`（778041 等），其 signatures 恰好干净（`172.16.35.231`/`Hit:\s+1`——778041 末行未落在 pattern 上）。**即：本批脏签名污染了审计记录，但未造成错误冻结**。风险是潜在的、随轮次与日志行序触发。

### 丙、维度4——anomaly_lines：无去重 + 排序挤出风险

`anomaly_lines = [ln for ln in scan if any(marker in ln)][:8]`（`batch_tools.py:751`），**不去重、先到先占、8 行封顶**，caret(`^` 语法拒绝，真 G 信号)在 `_window_audit` 后**追加**（`:772`，仅当 `len<8`）。实测：
- 777976：7×完全相同的 `RTNETLINK answers: Cannot assign requested address`（IP 恢复契约噪声，见 `[[framework-ip-restore-contract]]`，**非案缺陷**，却被当 exec_failure_marker 全占额）；
- 778072：4×同一 RTNETLINK；778041：3×RTNETLINK **在前** + 3×真 `^`ipv6 拒绝在后。

→ 若某案 RTNETLINK 类重复行 ≥8，真正的 `Failed to execute`/`^` 语法拒绝会被重复噪声挤出 8 格 → 归因看不到自身执行失败（正是 CLAUDE.md 记载 668030「自身命令流错位误判成床污染」的温床）。本批未触顶（最多 7 条），是**侥幸未爆**，非机制稳。

### 丁、维度5——detail_tail 与 device_context 高度重叠（冗余兜底）

`detail_tail = d[-2500:]`（inner.txt 摘要尾），`device_context` 段0 = 同一 inner.txt 经独立 fetch 的尾部（~2800）。实测 778012：`detail_tail[-200:]` 整段出现在 device_context 段0 内——二者**同源重叠**。分工：device_context 是主证据源（多源合并），detail_tail 是 device_context 缺失时的退化兜底（`fail_attribution.py:286` 的 corpus 顺序 `device_context→causality→detail_tail`）。正常路径下 detail_tail 冗余，非缺陷，但占 attr_evidence 2500 字符恒定体积。

---

## 四、结论：attr_evidence 作为「归因与审计唯一留存证据源」的保真评估

**保真的部分（可直接采信）**：
1. **device_context 作为归因证据 substrate——保真**。9/9 案决定性证据全存活；per-source 2800 尾截只削 inner 框架步日志中段（裁决另存 causality、失败 marker 由 `_KEEP` salvage 兜住），短会话在 cap 下完整。且截断发生在 SSH fetch 边界，**离设备侧无更原始副本可恢复——attr_evidence 已是离设备最高保真记录**。
2. **verdict——保真**。9/9 与原始 `Fail Num` 标记一致。

**不保真、会系统性误导的部分**：
1. **`_fail_signatures`——不保真**（缺陷①段头融合 + 缺陷②Fail/Success 混淆）。作为审计"失败签名"字段，其内容掺入管线管道文本与通过检查的 pattern，**不能直接当作"这个案失败在哪条断言"的证据**；跨轮/跨案机械比对会失灵。这是本次取证最实的失真点。
2. **跨轮冻结判定对日志行序/语义脆弱**：靠 `sig_now & sig_prev`，脏签名的常量 autoid 文件名可致假交集，语义混淆可致冻结钉在通过的 not_found 断言上。**本批未爆（受害案皆 round1），是范围侥幸，非机制免疫**。
3. **anomaly_lines 无去重**：RTNETLINK 类重复噪声可灌满 8 格挤出真 exec-failure/`^` 信号 → 归因漏看自身执行失败（668030 类误判温床）。本批最多 7 条未触顶。

**审计对时注意（非缺陷、易误读）**：device_context 内设备回显时间戳是**设备本地时钟**（如 `2026-07-16 11:46`），比 `_run_ts`（host 时钟，06:08）快 **+5h40m**。跨源核对轮次/因果时序须先减去时差，否则会把同一轮误判成不同轮。

**修法方向（供参考，本报告不改代码）**：`_fail_signatures` 应解析结构化 `#### (Fail|Success) Num` 行（复用现成 `_WA_CHECK_RE`），只取 `Fail` 行的 `(.*?) in :` pattern 分组，天然消除缺陷①（不再拼原始文本）与缺陷②（不再混 Success 行）；anomaly_lines 收集时 `dict.fromkeys` 去重后再截 8。二者皆为消费侧提取逻辑的窄修，不动采集面。
