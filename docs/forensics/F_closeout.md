# 取证 F·收尾：Section B 三 TODO 核销 + TODO_tui 面板清除根因

> 单元 F（/engine-verify-loop 取证段）。**只读，零代码改动。**
> 任务：不信定稿——逐个去实现代码 + 测试里核实三 TODO 是否真 RESOLVED；
> TODO_tui_ask_user_panel_clear 根因定位（仍开）。
> 数据：dongkl（pid 30390，34 案）盘上产物 + 全量测试实跑（仓库外 venv）。
> （挪档注 2026-07-16：本文核销的 4 份 `TODO_*.md` 已移至 `docs/archive/`，正文裸名引用不再逐处改。）

---

## 结论速览

| # | TODO | 声称状态 | 代码核实结论 | 建议 |
|---|------|---------|-------------|------|
| 1 | `TODO_s0_l23_infra_ip_exclusion` | RESOLVED（§18.14 S1） | **真 RESOLVED**（代码锚 + 测试绿 + dongkl 零假阳） | 文档标 RESOLVED（已标） |
| 2 | `TODO_attributor_s0_mechanical_recheck` | RESOLVED（§18.14 补修） | **真 RESOLVED**（代码锚 + 测试绿 + 提交 58a35e71） | 文档标 RESOLVED（已标） |
| 3 | `TODO_f6_claim_kind_unify` | RESOLVED（§18.13 re-key） | **真 RESOLVED**（实现走了比原推荐更通用的 re-key；测试绿） | 文档标 RESOLVED（已标）；见下「实现与文档推荐的分歧」 |
| 4 | `TODO_tui_ask_user_panel_clear` | 仍开 | **仍开·根因确认并细化**（新增 replay 复活路径铁证） | 未修，按下方修法方向实现 |

**测试铁证**（仓库外 venv 实跑，非文档说了算）：
```
~/.venvs/infotest-engine/bin/python -m pytest \
  tests/ist_core/compile_engine_v8/test_diagnose.py::test_s0_l23_excludes_fixed_infra_ips \
  tests/ist_core/compile_engine_v8/test_diagnose.py::test_attributor_s0_not_upgraded_when_mechanical_finds_no_polluter \
  tests/ist_core/compile_engine_v8/test_f8c_fold_and_adopt.py \
  tests/ist_core/tools/test_report_underdetermined.py
→ 18 passed in 0.34s
```

**dongkl 真实数据铁证**（`workspace/outputs/dongkl/facts.jsonl`）：
- `778012` → `ev=diagnosis h_position=none polluters=[]`（**精确命中** brief 预期「h=none polluters=[]」）
- `593516` → `ev=diagnosis h_position=h_lambda polluters=[]` + `h_position=none polluters=[]`（λ 层，非 s₀）
- **全 34 案 batch 的 `ev=diagnosis h_position=h_s0` 记录数 = 0**（零 s₀ 假阳——TODO 1+2 在真实数据上确实生效，无一案被误路由到 bed 床治理）

---

## TODO 1 — `TODO_s0_l23_infra_ip_exclusion`：真 RESOLVED

**声称**：已由 §18.14 S1（`env_facts.infra_ips()` + `_fixed_infra_ips()` 减法）实现——不再把测试床固定基础设施 IP 当污染性共享实体。

### 代码核实（定位到行）

1. **料源** `main/ist_core/tools/_shared/env_facts.py:102 infra_ips()`：返回 topology 登记的全部设备接口/服务 IPv4（`_exact_ips` 的 v4 投影）。数据驱动，换床改 `network_topology.json` 即变，零硬编码。
2. **包装** `main/ist_core/compile_engine_v8/nodes.py:1554 _fixed_infra_ips()`：`lru_cache` 包 `get_env_facts().infra_ips()`，读失败 fail-open 回落 `frozenset()`（不误放真污染，退回旧的过宽行为）。
3. **减法生效点** `nodes.py:1703`（`_s0_pair` 的 L2/L3 共享实体分支）：
   ```python
   shared = sorted((p_ents & vict["entities"]) - _fixed_infra_ips())[:4]
   ```
   减法在 `[:4]` 截断**之前**——正是 TODO 修法要求的「否则先截到基础设施 IP 会漏掉第 5 个真污染物」。只减 IP，不碰 vlan/port/bond 名（自建对象仍算真污染物）。

### topology 事实核对（减法真的会命中真实数据）

`knowledge/data/auto_env/network_topology.json` 内，TODO 点名的三个 IP 全在 `infra_ips()` 集里：
- `172.16.32.70` / `172.16.34.70` / `172.16.35.70` = APV0 三接口
- `172.16.35.231` = server231（dig 固定后端服务 IP）

∴ 667986 型（两案仅共享固定基础设施 IP）在真实数据上会被减空 → 不判 s₀。**不是纸面机制，是真会触发的减法。**

### 测试锚

`tests/ist_core/compile_engine_v8/test_diagnose.py:391 test_s0_l23_excludes_fixed_infra_ips`（实跑绿）：
- 正例：两案共享 `172.16.32.70`（基础设施 IP）→ `h == ""`（非 s₀）；
- 对照：两案共享自建 `vlan233` → `h == "h_s0"` 且 polluter 含 vlan233（真 s₀ 不被误伤）。

**结论：真 RESOLVED。** 代码/测试/真实数据三方一致。

---

## TODO 2 — `TODO_attributor_s0_mechanical_recheck`：真 RESOLVED

**声称**：已修（提交 58a35e71）——attributor(fork) 判 s₀ 时过 S1 机械复核，机械明确判无污染者则 h_s0 候选不升格。

### 代码核实（定位到行）

`main/ist_core/compile_engine_v8/nodes.py:1839-1851`（diagnose 主体，机械判无 s₀ 后回退采信 attributor 的分支）：
```python
if not h_pos:
    att = [f for f in mine if f.get("ev") == "attribution"]
    cand_h = str((att[-1] if att else {}).get("h_position") or "")
    # §18.14 缺口修(run24 655173):机械 _s0_pair 明确判无 s₀(跑了配对、非失明)时,
    # attributor 的 h_s0 候选不升格...仅机械失明(aid∈_profile_failures)时才采信 fork 的 s₀
    if cand_h.startswith("h_s0") and aid not in _profile_failures:
        sh.emit(f"…{aid[-6:]} fork 判 s₀ 但机械配对判无污染者——不升格,保留深归因")
        cand_h = ""
    h_pos = cand_h
```
即区分「机械明确判无 s₀」（跑了配对）vs「机械失明」（`aid ∈ _profile_failures`，触碰画像提取失败）——只有失明时才采信 fork 的 s₀。红线兑现：判断用结构化事实（机械配对），非 LLM 凭空造 s₀。

### 提交 + 测试锚

- 提交 `58a35e71`（2026-07-15 03:35）：`nodes.py +11 行` + `test_diagnose.py +51 行`，commit body 明确「全量 1987 绿」。
- `tests/ist_core/compile_engine_v8/test_diagnose.py:170 test_attributor_s0_not_upgraded_when_mechanical_finds_no_polluter`（实跑绿）：fork 对 AIDS[1] 判 h_s0，机械只见共享 `172.16.34.70`（S1 排除）→ 断言 ① AIDS[1] 无 h_s0 诊断 ② 不进 bed 床面板。**全图跑通，非纯单元。**

**结论：真 RESOLVED。** 注：TODO 里的 655173/667986 属 run23/run24（另批），不在 dongkl last_run；但 dongkl 全 batch 零 h_s0 假阳（见速览）反向印证机制未误伤金标准。

---

## TODO 3 — `TODO_f6_claim_kind_unify`：真 RESOLVED（实现与文档推荐分歧，方向更优）

**声称**（doc 顶注）：§18.13 用 equivalent-present re-key 溶解 claim_kind 路由。

### 实现与文档推荐的分歧（重要，供协调者对账）

- **doc 正文「修法(推荐)」**写的是：下游改认**盖章**（读 intent.json 的 `forbidden_mechanism` 标记，不认 claim_kind）。
- **实际落地**走的是 doc **顶注**的 equivalent-present re-key：不再 key on `claim_kind==forbidden_mechanism`，改按**三元组投影**（claim 带 `test_point` 字段即命中）+ `(group_path, has_equivalent)` 折叠。claim_kind 故意保持 `verification_path_absent` 不新增。

两者都能解 run22 病理，实现选的 re-key 更**通用**（覆盖所有三元组欠定案，非只 forbidden_mechanism）。**顶注准、正文推荐已被更优方案取代**——核销时以顶注 + 代码为准。

### 代码核实（三部件全部改到，定位到行）

1. **worker 呈报** `main/ist_core/tools/device/verifiability_tool.py:180 compile_report_underdetermined`：新增 `test_point` / `equivalent_procedure` / `no_equivalent_reason` 入参；entry 落盘带 `test_point`+`equivalent` 字段，但 `claim_kind` 保持 `verification_path_absent`（:257-259 注释明说「呈现形态由 equivalent 字段有无派生，不新增 claim_kind」）。
2. **题面** `main/ist_core/compile_engine_v8/questions.py:81`：`if all(c.get("test_point") for c in claims):` ——新三元组投影分支，**按 test_point 存在性路由，不按 claim_kind**。注释:83-84 明说「真实路径 claim_kind=verification_path_absent 但带三元组字段→走这里（旧版掉进 generic『加请求/观测次数』模板=run22 病理）」。逐字投影 worker 报告，建 采纳「proc」/我给别的等价方案/挂起 三选项 + `_token_by_label`。
3. **折叠/采信 re-key** `main/ist_core/compile_engine_v8/nodes.py:460 _fm_meta`：
   ```python
   is_triple = all(c.get("test_point") for c in claims)      # 新主路径
   is_fm = all(str(c.get("claim_kind")) == "forbidden_mechanism" for c in claims)  # 旧路径留兼容
   if not (is_triple or is_fm): return None
   ...
   if is_triple:
       has_eq = all(c.get("equivalent") for c in claims)
       return {"group": gp or (aid,), "sig": (leaf+"|"+("eq" if has_eq else "noeq")).lower()}
   ```
   折叠键 = `(group_path, has_equivalent)`，不再依赖 claim_kind。`group_path` 读 intent.json 盖章。
4. **emit 门** `emit_xlsx_tool.py:323 _gate_forbidden_mechanism`：未动，仍读 intent.json 盖章（本就独立于 claim_kind，一直有效）。

### 测试锚

`tests/ist_core/compile_engine_v8/test_f8c_fold_and_adopt.py`（9 项全绿）+ `tests/ist_core/tools/test_report_underdetermined.py`（7 项全绿）：
- `:151 test_triple_projection_zero_template_verbatim`——**直测 run22 病理修复**：断言题面无「加请求/观测次数」模板文案、procedure 逐字投影、采纳选项=具体方案、P3 label→token。
- `:164 test_triple_no_equivalent_suspend_carries_reason`——无等价时挂起项携如实理由。
- `:174 test_triple_folds_by_group_and_equivalence`——P1 re-key：同 group_path + has_equivalent → 同 sig（折叠依据）。
- 旧 forbidden_mechanism 题面/折叠/采信测试（:80/104/118/128）仍全绿（兼容路径未破）。

**结论：真 RESOLVED。** run22 病理（掉 generic 模板、7 独立题不折叠）已被三元组 re-key 溶解，且旧路径保留兼容。

---

## TODO 4 — `TODO_tui_ask_user_panel_clear`：仍开·根因确认并细化

**现象**：run22——主 agent 启动时问「产品版本」的 ask_user 面板，用户答完（10.5 落盘、引擎跑完 15 pass）后**一直挂在屏幕上**，直到 gather 阶段仍未消失；遮挡后续 ask_decision 面板。

### 根因（TODO 原诊断确认，并补出复活路径铁证）

TODO 原诊断「append 有、对应的 dismiss 无」**对**，我逐行核实并补上它没点破的复活机制：

**① 问询侧只 append，无「已答」状态**
- `main/ist_core/tools/ask_user/__init__.py:151` `ask_user` 工具 `bus.emit("ask_user_request", ...)` → reducer `_on_ask_user_request`。
- `main/ist_core/tui/reducer.py:750 _on_ask_user_request` → `:761-772` 把 `BLOCK_ASK_USER` 块（只含 `question_id`+`questions`，**无 answered 字段**）append 进 `self._messages`。
- `reducer.py:168 snapshot()` → `messages=tuple(self._messages)`——该块从此**永久驻留 snapshot**。

**② 答复侧不发任何回边事件**
- `main/ist_core/tools/ask_user/__init__.py:70 submit_answers`：只 set `_PENDING[qid]["answers"]` + 触发 `threading.Event` 唤醒阻塞的工具线程，**无 `bus.emit`**。
- `ask_user` 工具 `event.wait()`（:192）返回后也只 return 文本，不发「已答」事件。
- **全仓 `grep ask_user_answered / ask_user_resolved / ask_answered` = 0 命中**——生命周期回边根本不存在（TODO 原判成立）。

**③ 复活机制（TODO 未点破的关键——为什么『一直』挂着）**
ink 增量路径其实**有**清面板：`ist_app.py:1937 _finish_ask_user` 会 `self._ask_user = None` + `self._ask_user_panel.clear()`。且该函数 2026-06-09（4abf32d7）就在，**早于** run22 观测（2026-07-14，6799570f）——所以面板残留发生在「清面板已存在」之后，纯增量流里答完确实清掉了。

真凶是**全量重渲染路径** `main/ist_core/ink/components/ist_app.py:2171 _replay_snapshot`：
```python
self._transcript.clear()
... 重置 _subagent_* / _tool_* / _thinking_* 一堆增量态 ...   # 但没重置 _ask_user / _ask_user_panel
for msg in snap.messages:
    for block in ...:
        self._render_content_block(block, msg)   # 把每个块重走一遍
```
`_render_content_block`（:1908 `block.type == "ask_user"`）→ `_begin_ask_user`（:1915）→ `self._ask_user = AskUserSession(...)` **重新建会话、重渲面板**。因为那条 BLOCK_ASK_USER 块永远在 snapshot 里、且无 answered 标记，`_begin_ask_user` 又无「已答就跳过」的守卫，**答完的面板每次全量重渲都复活**。

`_replay_snapshot` 触发点密集：`ctrl+t`（:914 `_force_full_render`）、`ctrl+l`、**终端 resize / SIGWINCH**（`ink/app.py:192,349 _on_resize`）、:2169。长 run 里这些事件反复发生 → 观感就是「一直挂着」。

**与设计意图对账**：CLAUDE.md「TUI 验证」节明写「卡片状态在 reducer snapshot 内（ctrl+o/ctrl+t 重放一致）」。ask_user 块**没把 answered 态放进 snapshot**，于是 replay「一致地」复活了未答形态——正是该纪律的漏项。

### 修法方向（不改代码，定位到文件/函数/行；红线11：优先复用既有机制）

推荐 **事件驱动**（与 snapshot 重放一致，TODO 方案①的精化）：

1. **发回边事件**：`tools/ask_user/__init__.py` 的 `submit_answers`（:70）或 `ask_user` 工具 `event.wait()` 之后（:192），`bus.emit("ask_user_answered", payload={question_id, answers})`。
2. **reducer 入账 answered 态**：`tui/reducer.py:270` 派发表加 `elif kind == "ask_user_answered": self._on_ask_user_answered(event)`；handler **直接复用既有 `_update_tool_use_status`（reducer.py:500-524）的样板**——倒序扫 `_messages`、按 question_id 命中 BLOCK_ASK_USER、`replace_content_block` 换成带 `answered=True`（或折成「已答:X」摘要块）。这样 answered 态进 snapshot。
3. **ink 渲染认 answered**：`ist_app.py:1908` 的 ask_user 分支——块 payload 带 `answered` 时渲一行摘要（或直接跳过 `_begin_ask_user`），使 `_replay_snapshot` 重放出折叠形态而非复活面板。
4. **兜底（belt-and-suspenders）**：`_replay_snapshot`（:2181 那批重置里）加 `self._ask_user = None; self._ask_user_panel.clear()`——与它已重置 `_subagent_*/_tool_*` 对齐，防未答态面板重放叠影。

### 回归锚建议

- `tests/tui/test_ist_app_replay_snapshot.py`（**已存在**，ist_app.py:2174 引用）：加一条——snapshot 含**已答** ask_user 块时，`_replay_snapshot` 后 `self._ask_user is None` 且面板不复活。
- `tests/ist_core/tui/`（目录已存在）：加 reducer 单测——`ask_user_answered` 事件后，对应 BLOCK_ASK_USER 块 answered 态转移（块被 `replace_content_block` 折叠/标记）。

---

## 理论对账

本单元四项均为**工程收口/UI 生命周期**核实，无理论层冲突：
- TODO 1/2 落 THEORY_k (40) 处置分类学 §2.12.1 + §18.14 s₀ 机械复核；实证支持「s₀ 是床状态属性、判断用结构化事实非 LLM 造」——理论锚成立，无需更新。
- TODO 3 落 §18.13 问询三元组律；实现的 re-key 比理论文档正文的「盖章」推荐更贴 (46) 问询三元组律本身（按 test_point 三元组投影），理论无需更新，**只需把 doc 正文的旧推荐标注为已被 re-key 取代**（doc 顶注已对）。
- TODO 4 落 CLAUDE.md「卡片状态进 reducer snapshot、重放一致」纪律——是该纪律的一处漏项（ask_user 未把 answered 态入 snapshot），非理论冲突；修法即补齐该纪律。

STATUS: done
