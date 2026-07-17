# skill references 死链修复方案（任务 #20；LLM-Eng 审计 P1-1 的修法权衡）

> 状态：**方案，零代码改动**；security-reviewer 联审结论见文末附录（齐后报 leader 批准，批准前一行代码不动）。
> 问题原文：`docs/forensics/team4_skill_audit.md` P1-1——skill 包内 reference 文件对 agent 是死链（实测 `fs_read("main/ist_core/skills/...")` → `platform-denied: main/`），`invoke_skill` 的 `<skill_references>` 注入自设计起与多根沙箱矛盾。

## 0. 实证盘点（方案的证据面）

- **受影响文件（7 个，全部无秘密）**：`device-verify/reference/ssh_template.md`、`device-verify/scripts/apv_ssh_client.py`、`ist-compile-engine/references/{contracts,theory-map,removed-rules}.md`、`config-automation/scripts/smoke_config_generator.py`、`test-list-review/scripts/sanity_check.py`。
- **秘密扫描**：skills/ 全 33 文件（18 md+14 py+1 json）凭据形态 grep 零命中（SSH 凭据全走 `APV_*` env，SKILL.md 明文禁硬编码）✓。
- **三个消费面**（任何方案必须全修）：① `invoke_skill` 注入（`tools/skills/__init__.py:93-106`，列出 `reference/` 路径让 agent「按需 fs_read」）；② SKILL.md 正文指引（device-verify:43「read directly」+ Step 4）；③ 未来 fork brief 内的同类指引。
- **既有先例**：`_agent_roots` 已含 `_FRAMEWORK_MIRROR_ROOT` 只读参考根 + `_FRAMEWORK_MIRROR_READ_ALLOW` 文件白名单（file_tools.py:24-31/274-277，「默认拒、最小暴露面，扩需同样评审」）——**方案 A 的安全范式现成**。
- **连带缺陷**（随方案同批修）：注入代码只认 `reference/` 单数（`__init__.py:93`），ist-compile-engine 的 `references/` 复数目录永不进注入（skill 审计 P2-5）。

## 1. 三方案权衡

### 方案 A（推荐）：skills 根进 `_agent_roots` 只读根 + 子目录白名单收窄

- **形态**（与 mirror 先例同构）：`_SKILLS_ROOT = main/ist_core/skills` 追加进 `_agent_roots()`（仅读根；`_resolve_writable_path` 不含它 → 零写入面）；`_resolve_inside_root` 内加同构闸——skills 根下**只放行相对路径第二段 ∈ {reference, references, scripts} 的文件**（`<skill>/<白名单子目录>/...`），SKILL.md/agents md/loader.py/state.py 等一律拒（它们经 invoke_skill/loader 注入进上下文，agent 无需也不应 fs_read 原文件）。
- **优点**：唯一同时修通三个消费面的方案；渐进披露 L3 语义保真（官方 Agent Skills 规范本意=「按需读包内 references」）；skill 包完整性保持（资产封装标准 2026-07-05 方向）；安全范式有先例（mirror 整根进+白名单限读，评审路径现成）。
- **代价**：读沙箱 +1 根。攻击面增量量化：只读、白名单三子目录、当前 7 文件、实证无秘密；**目录模式而非逐文件枚举**（references 随 skill 演进增文件，逐文件枚举必漂移——与 mirror 的 2 文件稳定闭集不同，这是两者白名单粒度差异的理由）。
- **残余风险与对策**：未来有人把敏感文件放进 `*/reference(s)/scripts/`——对策=①机器门：`test_skill_package_standard.py` 加「白名单子目录内文件不得含凭据形态」扫描断言（与 leak_scan 同型，机械纪律替代人记）；②本方案文档在 file_tools 注释中被引用，扩白名单需再评审（沿用 mirror 措辞）。

### 方案 B（不推荐）：invoke_skill 注入时内联 reference 内容

- 零沙箱改动，但：①违渐进披露本意——L3 按需层被强制 L2 化，ssh_template.md 等全文每次 invoke 进上下文（与 tool_gating 削 schema 的方向背道而驰）；②只修消费面①，SKILL.md 正文「read directly」指引（面②）仍死链，除非重写全部 skill 文案为「见上方注入」——文案面大改且 fork 面（③）无解；③reference 变大时上下文成本线性放大。**治标不治本。**

### 方案 C（不推荐）：references/ 构建期镜像到 knowledge/data/

- 零沙箱改动，但：①本项目**无构建步骤**（源码即部署）——「构建期镜像」实际=手动同步（漂移温床，mirror 的 .sync_anchor 就是为治这类漂移建的锚）或启动时复制（运行时写 knowledge/data 违反「纯只读知识库」目录契约）；②双份真相，改 skill 忘改镜像=静默旧版——正是 I3/§18.3 全力在治的信任根漂移形态，不该新造一个。
- **变体 C'（物理搬家不镜像）**：单份真相、零沙箱改动，但破坏 skill 包完整性（references 语义归属是 skill 包，官方规范形态），且 invoke_skill 注入的 skill↔ref 目录耦合断裂需另造映射。编译链把 EXCEL_FUNCTIONS/domain_grammar 放 knowledge/data 是因为它们是**领域数据**；ssh_template 是 **skill 私有模板**，归属不同。若 leader 否 A，C' 是次选。

## 2. 推荐结论

**方案 A（收窄版）**。配套三件同批：
1. 注入代码兼容 `reference|references` 两种目录名（P2-5 连带）；
2. 机器门升级：`test_skill_package_standard.py` 加「SKILL.md 指引的 agent 可读路径必须过 `file_tools._resolve_inside_root`」运行时断言（skill 审计发现的门盲区：现门只验文件存在=维护者视角）+ 白名单子目录凭据形态扫描；
3. device-verify 等 SKILL.md 的路径指引原样保留（修根后即活链，零文案改动）。

## 3. 实施边界（批准后执行时的自我约束；已按评审条件 1 修正措辞）

- 触碰面：`file_tools.py`（`_SKILLS_ROOT`/`_SKILLS_READ_ALLOW_SUBDIRS` 常量 + `_agent_roots` 一行 + **豁免-收窄原子谓词 `_skills_read_allowed`（黑名单闸与白名单循环双点复用同一谓词）**）、`tools/skills/__init__.py`（单复数兼容）、`test_skill_package_standard.py`/`test_deepagent_multi_root_sandbox.py`（+门/+回归锚）；
- 不碰：`_resolve_writable_path`（一行不动，升格为回归断言）、`_PLATFORM_DENIED_*` **常量**零变化（判定逻辑新增 skills 谓词豁免——评审修正：黑名单闸按 resolved 顶段判 `main/` 且先于白名单循环，豁免不可避免，必须与收窄同一谓词原子绑定，禁写成两段分离逻辑）、任何 SKILL.md 文案；
- 回归判据：全量 pytest 0 failed + 评审「实施必带机械防护」六条全带（见附录）。

---

## 附录：security-reviewer 联审结论（2026-07-17，逐字收录）

**总体：有条件通过**（方案 A 安全架构成立——与 mirror 先例同构、只读、写侧零影响；但方案文档存在一处会导致实施走样的设计表述缺口，必须按条件修正后实施）。

### 发现（按严重度）

- **[高——方案缺口,非代码缺陷] file_tools.py:249-264 vs 方案 §3——「黑名单零变化」声明与闸序矛盾,豁免形态未钉死**：黑名单闸按 resolved 绝对路径相对项目根第一段判定（:257），且执行于多根白名单循环（:267-284）**之前**——skills 路径永远到不了第三闸。方案要工作必须在黑名单闸开豁免；「零变化」只对常量成立。风险：若豁免（黑名单处）与收窄（白名单循环处）写成两段分离逻辑，豁免单独就是 main/ 黑名单上的无条件洞。**条件 1（必须）**：豁免与收窄原子绑定为同一谓词函数 `_skills_read_allowed(resolved)`（基于 `.resolve()` 后路径的 `relative_to(_SKILLS_ROOT)` + `parts[1].lower() ∈ 白名单子目录`），两闸复用；symlink 指向树外时 relative_to 失败 → fail-closed。
- **[中] 方案 §0「7 文件」盘点不完整**：目录模式实际匹配 10 个（含 3 个 `scripts/__pycache__/*.pyc`——被二进制门挡读但可枚举）。**条件 3**：机器门凭据扫描须扫运行时 glob 实际匹配集（非硬编码清单），谓词排除 `__pycache__` 段。
- **[低] apv_ssh_client.py:51-52/:255-257 弱默认凭据形态**：函数默认参 `admin/admin` + 默认 IP（IP 已在既有可读面 topology.json，零增量；admin/admin 是出厂默认口令常识级，真实口令走 env agent 不可读）。不阻断；方案 §0 精确化为「无真实凭据；存在弱默认值形态，已评估接受」，扫描门对此显式豁免带理由。其余 6 文件逐个通读无秘密。scripts 的 fs_read→run_python 复述链：执行能力零增量（run_python 本就可 import main.*）。
- **[低] 方案 §1 对 C 的安全维度遗漏**：方案 C 安全面**不是更小而是更差**——knowledge/data 是无子目录收窄的全开读根，镜像=把内容搬进无闸区且漂移使已评审内容与实际暴露脱钩。方案 B 安全面确实最小，它输在消费面②③无解与上下文成本，属产品决策非安全否决。

### 逐项核查（行级）

1. **三闸完整性成立**：traversal 闸（:193-197）在原始字符串层面先于一切 resolve——`<skill>/reference/../../loader.py` 相对/绝对两形态实测 DENY；同构闸插入点与 mirror（:274-277）并列无嵌套歧义；谓词 parts[1] 判定须 `.lower()`（macOS 大小写不敏感 FS）。
2. **豁免洞不可复用（前提=条件 1）**：`..` 构造→第一闸拒；symlink→resolve 展开后谓词 fail-closed；硬链接创建需仓库写权限（agent 仅 workspace/outputs 文本可写），威胁模型与 mirror 根等同。main/ 下白名单外 27 个 skills 文件及其余源码全部保持 DENY。
3. **内容风险低**（见发现），不阻断。
4. **对称面无旁路**：fs_read（:1002）/fs_ls（:541,:549）/fs_glob（:631,:573,rg 出口 :350）/fs_grep（:845,:369/:373/:389）全部过 `_resolve_inside_root`，rg 输出逐行回灌 resolver；写侧 `_resolve_writable_path`（:890-957）独立实现不遍历 `_agent_roots()`，加读根天然零影响，**其黑名单闸（:926）严禁复制豁免**。
5. **横向对比修正**：见发现第 4 条。

### 实施必带机械防护（六条，批准时随附）

1. 豁免-收窄原子谓词（双闸复用、基于 resolved、`.lower()`、排除 `__pycache__`）；方案 §3 黑名单措辞修正（已改）。
2. `_resolve_writable_path` 一行不动，升格断言：fs_write/fs_edit 对 `main/ist_core/skills/...`（含白名单子目录）PermissionError。
3. 凭据扫描门扫运行时实际匹配集、覆盖函数默认参形态、admin/admin 显式豁免带理由。
4. 回归断言六向（样板=test_deepagent_multi_root_sandbox.py:84-110 mirror 测试）：①三白名单子目录 ALLOW；②SKILL.md/loader.py/state.py/.skill_overrides.json/modules/* DENY；③贴近豁免边界的 main/ 非 skills 路径显式 DENY；④traversal 构造 DENY；⑤tmp 构造 skills 树内 symlink 指向树外 DENY；⑥写侧 DENY。另加真实树卫生断言（白名单子目录内无 symlink、st_nlink==1）。
5. skills 根追加在硬编码根末尾（mirror 之后），最小化相对路径首命中遮蔽（:234-238）。
6. file_tools 注释沿用 mirror「扩需再评审」措辞；dyn_skills（runtime/dyn_skills）**不在**豁免范围——runtime/ 黑名单语义不变。

### 已确认安全的不变量

traversal 闸先于一切解析；写路径四闸独立、唯一可写区 workspace/outputs 不变；memory/、runtime/ 黑名单语义不变（谓词范围不可达）；凭据路径不触碰（environment/ssh_users.json 仍不可读）。
