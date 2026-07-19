# 编译红线评审 — 任务 #52 (SSL+SLB enablement)

- **总体裁定:PASS**（5 项红线全过,零命中;1 处边界项已细审判定合规,列在下方供知会）
- 评审者:redline-reviewer 子 agent（只读）
- 日期:2026-07-19
- 方法:已读**全量 diff**（非仅 grep）——`domain_grammar.json` / `contracts.md` / `compile-attributor.md` / `theory-map.md` / `test_rule_attribution.py` 全 diff + 两个新 eval 全文 + 针对性 grep 取行号 + 核 API 存在性。

## 命中（文件:行 — 红线 — 证据 — 建议）

无。红线角度零命中,无需修改。

## 逐项判定（PASS/FAIL + file:line 证据）

### (1) 零写死设备/领域命令 — PASS
- grammar 6 statement + 3 closure 的 pattern 均为**识别 regex**（数据层,允许）。
- `contracts.md` SSL dispatch 段:方法名（importKey/importCert/sm2ImportKey/RootCA/InterCA/CRLCA/activeCert…）是 **mirror harness 的 Python 方法名,非设备 CLI**;以 ~9 个 stem 作 locator + 明写 "The cert-method inventory … are DATA — `fs_read` them from the mirror, never hardcode method names",指向 `ssl_comm.py:89/124/572`、`test_xlsx.py:280-336`、`dic_operation.py:57`、`env.py:66-82`。符合"named method references + mirror line-refs 作 locator 可接受、full inlined table 不可"——此处是 locator overview,非全表转录。
- `compile-attributor.md` [A24] 新增块（diff 第 55-60 行区）零设备命令。grep 命中的 `show version`(@32)/`show state`(@25)/`Fail Num` 经 `git diff` 复核确认为**既有上下文,不在本次 diff**。
- 两个 eval 文件零设备工具调用（grep `dev_run|dev_ssh|dev_rest|dev_probe|compile_engine` = none,纯离线文法逻辑,不违编译/上机解耦）。
- **边界项（细审后判合规,知会 leader）**:`contracts.md:87-88` 出现 `ssl activate certificate <h>` → `ssl host virtual <h>`。判合规三条理由:
  1. 用 `<h>` 占位,非具体实参,是命令**形态**非可跑命令;
  2. 语境是描述**已存在的文法闭包** `ssl_cert_activate_needs_host_define` 所查的结构依赖（activate 引用 host-define）,属"命名一个 grammar-checked 结构契约",非"给 LLM 一条要跑的命令",也非回答"该探/该断哪条命令"（后者才是红线本意——防 LLM 跳过查手册）;
  3. 与 2026-07-13 红线（`suggested_teardown:"clear slb all"` 可执行且作用域未知）本质不同——此处无 advice-to-run、无作用域越权风险。
  - 现状落在"占位式结构契约描述"允许面内。若 leader 要最保守,可只留闭包 id、去掉两处 CLI 形态措辞;非必须。

### (2) 无 observe-then-assert / 无写死设备期望值 — PASS
- grammar provenance 引的是金标准**频次计数**（SLB 526/167 IPv6/151/138/164;SSL 88+29+23、65+19+17）+ 金标准对象名引用（vh1/rh1 出自 golden 卷 sdns_ssl_conn_2）——是**出处证据**,非断言期望值。
- `contracts.md` 的 `172.16.35.215`（TFTP 源）/ server213-231-232 / `cert/epolicy_ssl/*.key|.crt` 是**基础设施/拓扑事实**配 source 行,归入 S1-S5 静默失败面,非"设备回显抄成断言"。
- 两 eval 的 IP（172.16.34.100 / 3ffc::75 等）是**合成的 regex 演练输入**,断言对象是捕获组行为（`.group("vip")==…`）与悬空引用检测（`dangling_references(...)==[…]`）,全程离线、无设备参与——属 eval-first 文法单测,不构成 observe-then-assert。

### (3) 无 suggested_teardown 式经验命令建议 — PASS
- 全 diff 无 `suggested_teardown` / `teardown` / 任何经验命令字段。closure 的 `skip_leading_verbs:[no,clear,show]` 是识别解析器的**跳过动词 token**（跳过 `no X`/`clear X`/`show X` 这类非定义性引用）,非命令建议。
- **两个 eval 均机器守此红线**:`assert "suggested_teardown" not in blob`（`test_ssl_enablement.py:80-87`、`test_slb_grammar.py:93-100`）。已核 `domain_grammar.py` 的 `load_grammar`/`stmt_re`/`reference_closures`/`dangling_references`（:27/:44/:119/:188）全部存在——断言非空转,是真机器门。

### (4) contracts.md = 机制+语法契约+失败模式+源路径,非漂移数据表 — PASS
- SSL dispatch 段明写方法清单为 DATA 令 `fs_read`,给出全源路径（见 (1)）。
- sm2 3 参订正 `<keyType>, <vhost>, <keyFile>`（`contracts.md:63-64`）= **语法契约** + source(`sm2ImportKey :572`) + **失败模式**（错参崩卷,对照 8 golden 行 #50 CC2）,符合先例"syntax-contract/failure-mode with source refs 允许"。
- S1-S5 表每行 = **机制 + source 行**（`ssl_comm:102-104` / `dic_operation:72,:79-80` / `ssh_server:91` / `ssl_comm *_tftp` / `test_xlsx:332-336`）,框为 silent-failure faces,符合先例允许。无随框架版本漂移的内联清单。

### (5) 每条新 statement/closure 带 provenance — PASS
- 6 statement + 3 closure **全带 provenance**（金标准计数 / manual 引用 / Theory #51-C 溯源 / scope+caveat）。
- device-pending 字段（footprint_node / silently_accepted）按 leader 令**留空不臆造**,并被 `test_slb_grammar.py:85-90` 机器守住。

## 核对过但合规的点（汇总）
- grammar pattern 属数据层识别 regex —— 允许,非写死命令。
- contracts.md 方法名 stem-list 是 locator overview + fs_read 指令,非 full inlined table。
- sm2 3 参 + S1-S5 表按 syntax-contract/failure-mode + source ref 呈现 —— 命中先例允许面。
- provenance 引金标准计数与对象名 —— 出处证据非断言期望值。
- eval 全离线、无 dev_* 调用 —— 不违编译/上机解耦。
- `suggested_teardown` 缺席且被双 eval 机器守。

## 附:一处非红线提示（供 leader 亲跑 pytest 定位）
- 任务 scope 描述写 `tests/ist_core/tools/test_slb_grammar.py`,实际落盘在 **`tests/ist_core/skills/test_slb_grammar.py`**（与 `test_ssl_enablement.py` 同目录 `tests/ist_core/skills/`）。跑权威 pytest 时按 `skills/` 路径收集。非红线问题,仅避免漏跑。

---
**结论:红线角度可放行合入。** 语义终判在上机（`ist-verify`）,不在本评审范围。
