# 编译红线评审 — 任务 #56(execute 动作名精确注册表 emit 门)

> 2026-07-19 · redline-reviewer 子 agent · 只读评审(未改任何代码)
> 评审对象:未提交工作树 — `git diff` on `main/ist_core/tools/device/structural_gate.py`(+80 行)
> + 新测试 `tests/ist_core/tools/test_execute_action_gate.py`(11 tests)+ CLAUDE.md ⑦门条目 + DESIGN §15 S6 姊妹门条款。
> 证据边界:基于 git diff 全文逐行 + 新测试文件全文 + mirror 源文件 ls 实存核对 + 我亲跑测试文件(辅助证据,权威数字待 leader 亲跑)确认以下结论;未核对本批之外的历史提交。

## 总体:PASS(四项检查全过;附 2 个范围勘误 + 3 个灰点说明,均不构成违例)

**范围勘误**:
1. 门文件实际路径是 `main/ist_core/tools/device/structural_gate.py`,**非**任务描述中的 `main/case_compiler/structural_gate.py`——请在台账纠正,防记录漂移。
2. 工作树同批还混有 #50/#52/#53 的改动(`contracts.md` / `domain_grammar.json` / forensics 4 篇),已顺带核对,见「核对过但合规的点」。

## 命中(文件:行 — 红线 — 证据 — 建议)

**无红线命中。**

## 四项检查逐项裁决

### 检查 1:门代码零写死设备/领域命令,注册表必须从 mirror 解析 — PASS

- `structural_gate.py:134-159` `_execute_action_registry()`:闭集**纯解析**——
  `re.findall(r"'([^']+)':\s*self\.func_\d+", _mirror_src(src_rel))` 抽 apv_action/client_action
  的 `command_function_mapping` 键,∪ 两 synonyms 文件按全角冒号/逗号解析(复刻框架
  `load_synonyms` 语义)。**零手抄动作名单**。
- `structural_gate.py:128-129`:新增 `_APV_SYNONYMS_SRC = "lib/apv/apv_synonyms"` /
  `_CLIENT_SYNONYMS_SRC = "lib/client_synonyms"` 是 mirror 相对路径常量,非命令字面量。
- `structural_gate.py:41-47` `_mirror_src`:读盘上 `knowledge/framework/mirror/`;四个源文件
  (apv_action.py / client_action.py / apv_synonyms / client_synonyms)经 `ls -la` 核实实存。
- 门代码内唯一硬字面量:`"execute"`(F 列框架方法名,结构闭集成员)、解析正则、违例文案。
  文案中「健检 UP↔DOWN」是现象例证,非可执行命令。
- fail-open 有防静默退化兜底:mirror 读不到 → 空 dict → 门跳过(`structural_gate.py:681-682`);
  `test_execute_action_gate.py:34-36` 断言闭集 ≥40,解析悄悄失败会被测试抓住。
- 测试 fixture 中的真实动作名(「访问」「指定Service健康检查UP」「响应内容为」「发送http请求」等,
  test:38-41/55-62)与两处命令字面量(`slb virtual service vs1` / `systemctl stop nginx`,
  test:93/95)——**测试数据(正/负例验证),可接受**(leader 预先声明),且测试文件不属红线 1
  列举的 LLM 资产范围(skill/agent/case_compiler/compile_* 定义)。

### 检查 2:无 observe-then-assert — PASS

- 门是纯 membership 判定(动作名 ∈ 解析闭集),`structural_gate.py:674-706` 全函数不内嵌任何
  期望设备输出;违例消息无期望值;本批未触及 `<RUNTIME>` 回填链路(compile_runtime_fill 无改动)。

### 检查 3:拒绝 hint 不 auto-rewrite(输入行不被变异)— PASS

- `structural_gate.py:674-706` `_check_execute_action_registry` 循环体对行 dict **只有
  `s.get("F")` / `s.get("G")` 读操作,零赋值/零 mutation**;候选 `ranked[:3]` 只进违例
  detail 文本(`result.add(...)`),不回写 steps。
- 违例文案明示:「最近候选仅供参考、须你有意识确认,门不自动改写」。
- 性质有机器守门固化:`test_execute_action_gate.py:72` 断言拒后 `row["G"]` 原文未变。
- 设计有理论锚(DESIGN §15 新条款):auto-correction 会把危险的 ≥0.8 模糊匹配机械化重现
  ——hint 只授权「这有个近似名」,不授权「这就是对的名」。

### 检查 4:文档写机制不内联数据表 — PASS

- **CLAUDE.md:201 ⑦门条目**:写机制(精确匹配失败 → `get_similar_function` ≥0.8 模糊回退 →
  静默派发到语义反义 func)+「从 apv_action/client_action/synonyms 机械解析」;2 个碰撞对
  (health UP⇄DOWN 0.812、AXFR⇄IXFR 0.944)为证据引用(leader 预先认可该形态),未内联注册表清单。
- **DESIGN_v8_engine.md §15 S6 姊妹门(:727 附近,+7 行)**:闭集按源码路径+数量级引用
  (`apv_action.py:11-44` ~33 + `client_action.py` ~8 ∪ synonyms),**未抄 40 名清单**;
  3 个碰撞对为证据引用;含两条关键设计事实——synonyms 必纳入精确集(binding spec,防误杀
  合法 synonym 金标准)与 hint-not-rewrite 的 §21 推导。

## 核对过但合规的点(含范围外同批改动 + 灰点)

1. **`main/ist_core/skills/ist-compile-engine/references/contracts.md` +32 行**(#50/#52,
   skill 参考文档,属红线 1 作用域):总体守规——开头自 declare「inventory 是 DATA,fs_read
   mirror,never hardcode method names」;S1-S5 静默失败面表是红线明文允许的「静默失败模式+
   源码路径」。三处灰点,均不判违例:
   - ① cert 方法名族一行枚举(csr/importKey/… 9 名)紧跟 mirror 行号引用,定位是指路概览;
     如要更严可收成纯引用(**建议级,非违例**)。
   - ② TFTP IP `172.16.35.215` 是**框架源码 ssl_comm 硬编码事实的引用**(S4 归因证据,
     且明文声明金标准 never TFTP、床不需 .215),非注入给 LLM 的可执行配置。
   - ③ `ssl activate certificate <h>` → `ssl host virtual <h>` 是占位符化形态骨架,描述
     grammar 闭包机制(指向 domain_grammar 条目)——与 suggested_teardown 反例的本质区别 =
     结构依赖说明,非行动建议。
2. **`knowledge/data/compile_ref/domain_grammar.json` +32 行**(#52 SSL):文法层数据文件是
   设计认可的零代码扩展路径(自愈四层);两 pattern(ssl_host_define / ssl_cert_activate_ref)
   为识别形态正则、逐条带 provenance(金标准卷计数取证);新闭包 advisory 非门且 caveat 声明
   fixture 误报面。非 2026-07-13 裁决所禁的「经验命令建议」(suggested_* 类)。
3. **forensics 4 篇**(team4_slb_ssl_feature_model.md 改动 + 3 新文件):docs/ 取证记录
   (给人读),红线 1 作用域外;内含命令为取证证据记录,合规。
4. **编译与上机解耦、fork 隔离**:本批改动未触及 `dev_run_*` 调用链与编排,无新增耦合;
   grade 链路 2026-07-07 已删,本批无涉。
5. **辅助证据(非权威数字)**:reviewer 亲跑
   `~/.venvs/infotest-engine/bin/python -m pytest tests/ist_core/tools/test_execute_action_gate.py -q`
   → **11 passed in 2.12s**,含两项零误杀反扫实跑(105 卷交付语料 execute 行 = 0;
   380 金标准卷 2208 个 execute 行 100% ∈ 解析闭集、0 miss)。**权威 pytest 仍待 leader 亲跑。**

## 结论

#56 四项检查全 PASS,红线零命中,可进 Theory/Design 双专家评审后续流程。
