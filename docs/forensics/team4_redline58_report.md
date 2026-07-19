# #58 SSL/SLB knowledge-reachability 批 — 编译红线评审报告

- 评审子 agent:redline-reviewer(只读,不改代码)
- 范围:#58 组合批未提交工作树改动的编译链红线
- 结论:**总体 PASS**(5 检查全过;读了生成器 + 投影全文 + mirror 源逐条核对,非仅 grep)
- 备注:footprints/ gitignore 的 `ssl.activate.certificate.json` 节点编辑在本 agent 范围外(Theory/Design 另审),已略过。

## 命中(违例):无

## 逐项核对(file:line 证据)

### (1) 零写死领域命令 — PASS
- 投影 `method_reference.json` 是 mirror 生成的 **DATA**,落 `knowledge/data/compile_ref/`(与 domain_grammar/command_inventory 同模式)。`_agent_roots()` 硬编码 `knowledge/data/` 为首位读根(`file_tools.py:37-39`),worker fs_read 可达。
- 提示词只**指向**投影、不内联命令:
  - `compile-worker.md [W6]` 只加一行「framework method arg-signatures + silent-failure faces (SSL/execute/server) are in `knowledge/data/compile_ref/method_reference.json` (fs_read-able projection; the mirror is outside your sandbox)」。
  - `compile-attributor.md [A24]` 指向 `silent_failure_faces` S1-S5 + 描述机制(缺 cert 文件不 import 等),**未内联** `importKey`/`ssl activate certificate` 等设备命令。
- grep 当前 worker/attributor .md 的命令字面量:命中项(`show version`/`show sdns listener`/`dig` 等)全是**先例存量的机制描述行**,均**不在 #58 diff 内**,#58 未新增任何内联设备命令。
- 投影内命令片段(`ssl activate certificate`/`ssl host virtual` @JSON:445、TFTP `172.16.35.215` @444/494)均为 provenance 锚定的**文法层事实**(带 mirror source + 已查文法门 `ssl_cert_activate_needs_host_define`),等同 domain_grammar.json 既有形态——data-by-reference,非 prompt 内联。

### (2) 无 observe-then-assert / 无写死期望值 — PASS
- grep 投影 `Hit:|found_times|\d+|锚` → **NONE**。投影零断言期望值。
- `cert_behavior_notes` 是「框架行为」(importCert 自动 activate)带 source 锚(JSON:447-459),非设备回显抄成断言。
- footprint `index.py`(Fix A/B)纯 load 可靠性 + 版本回退;`loader.py`(Fix C)加 kwargs 日志;`skills/__init__.py` 删死块——均无设备值/断言。`<RUNTIME>` 纪律(worker [W5])未被触碰。

### (3) 生成器 PARSE mirror(非手抄)— PASS
- `_parse_cert_methods()` 用 regex `_CERT_DEF_RE` 打 `_mirror_src("lib/apv/ssl_comm.py")`(gen:34-45)。核对:mirror ssl_comm.py 里该 regex 实际命中 **37** 个 def = JSON `cert_methods` 的 37 条,一一对应(importKey/importCert/sm2ImportKey/activeCert 签名逐字吻合)。
- `_execute_actions()` 复用 #56 `_execute_action_registry()`(`structural_gate.py:138-160`,regex 解析 apv_action/client_action 的 `command_function_mapping` ∪ synonyms)——**非手抄 40 名**。
- 漂移守门测 `test_cert_methods_match_mirror_no_drift`/`test_execute_actions_match_registry_no_drift` 断言 `JSON == 现场重解析`,任何手改脱离 mirror 即红。
- `_CURATED` 块确为手写,但只含语义/行为注(S1-S5/arity/dispatch,机械不可导),带 mirror source 锚——即红线许可的「策展带出处」层,非被禁的手抄签名/动作清单。

### (4) 重指向可达路径、无死指针 — PASS
- 旧 `references/contracts.md` 解析到 `main/…`(在 `_PLATFORM_DENIED` → worker 死指针);[W6]/[A24] 已改指 `knowledge/data/compile_ref/`(可达)。
- `skills/__init__.py` 删的 `<skill_references>` 块正是列 `main/…/reference/` 不可达路径的死块(且历史单复数不符从未 emit),删除合理。

### (5) CLAUDE.md 讲机制非内联数据 — PASS
- 证据优先 #12:「fs_read mirror 现查」→「worker fs_read `knowledge/data/compile_ref/` 投影现查,投影由 mirror 生成——mirror 源不在 worker 沙箱,只引擎门直读」——纯机制,纠正了旧的错误声明(mirror 本就不在 worker 沙箱)。
- 红线节:改述为「数据投影进沙箱可达的 compile_ref/(生成式)」,只举 `method_reference.json` 为例(如它处举 domain_grammar),**未内联签名/命令表**。
- 核对其引用的 `_FRAMEWORK_MIRROR_READ_ALLOW` 2 文件白名单声明属实:`file_tools.py:29-32` = `{lib/test_xlsx.py, lib/check_point.py}`,故「ssl_comm.py 不在 worker 白名单、旧提示是死指针」这一 #58 核心 FINDING 成立;`_mirror_src`(`structural_gate:41-47`)直读全 mirror 不走该白名单 → 引擎门/生成器可读 ssl_comm.py 生成投影,机制自洽。

## 核对过但合规 / 需知会(非阻塞,非 #58 引入)
- **`ist-compile-engine/SKILL.md:39`** 仍写「machine contracts are documented in `references/contracts.md`」。**不在 #58 diff、不判 FAIL**:①它是 inline 引擎 skill(非 worker fork 检索指令),②目标文件存在(`contracts.md` 5223B,7月19 20:55 更新),③loader 删块注释已把 `references/` 定性为「维护者文档」,此处属文档指路非运行时 fs_read。仅知会:该 md-path 在 `main/` 下,若哪天真让引擎主 agent fs_read 它同样会被沙箱挡——建议后续顺手改成 docstring/维护者说明措辞。
- 投影 `server_trigger_hosts.contract` 含框架用户名「test/click1」(env.py 源),**无口令**;与既有 topology/domain_grammar 同类,无新增机密进 git。知识内容正确性交 Theory/Design。
- 策展块 source 行锚(如 `ssl_comm.py:153-154`)**不被漂移守门测覆盖**(测只护 generated 部分)。当前核对 importCert 自动 activate 确在 153-154(sed 实读吻合),但 mirror 变更时锚会静态陈旧——维护性提示,非红线,归 Design 知识层。

## 放行结论
红线侧可放行,建议进 leader 权威 pytest + atomic commit。
