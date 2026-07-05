# ist-compile-grade — 审批工作流（严格流程）

> 这是 grade fork 判 V 段断言覆盖度的**确定性流程**。SKILL.md 给硬规则与例外，本文件给逐步落点。

## 硬关卡（先探明，不许抢跑判定）

**第一步必须先调 `compile_grade_extract` 工具探明 suspect 信号，再下判定。**
在拿到它的确定性事实（layer / observe_kind / is_genuine_v_assertion / layer_mismatch /
weak_v_coverage_suspect / distribution_coverage_gap_suspect / count_tautology /
count_hardcoded / hardcoded_hit_ip）之前，**不许**凭印象给 PASS/CUT。

```
compile_grade_extract(xlsx_path="<case.xlsx>", prov_path="<case.provenance.json 或 ->")
```

工具在主进程内按绝对路径加载探针、返回结构化 JSON——**别再用 `run_python` 跑
`scripts/grade_extract.py`**：fork 里 cwd/路径不稳、会找不到脚本而 fallback 肉眼放水，
这正是写死命中 IP / 写死固定命中计数的算法类 case 带病 PASS 的根因。
（脚本仍保留供人工命令行复核：`python main/ist_core/skills/ist-compile-grade/scripts/grade_extract.py <xlsx> <prov|->`。）

工具只产**确定性信号**，**不下终判**——终判由你（grade LLM）据真实证据现场判。

## 数据契约（extract 每个 check_point 的字段）

| 字段 | 含义 |
|------|------|
| `idx` / `row_line` | check_point 序号 / 数据区行序（与 provenance.steps 同序，引用时报 row_line） |
| `mode` / `expect` / `cp_h` | found/not_found / 期望值字面量 / 寄存器引用名（关系断言非空） |
| `layer` | draft 标的 G/E/V（核其名实——`layer_mismatch` 就是名实核对） |
| `query_object` / `query_object_tokens` | 断言查询对象（期望值）/ 其字母 token |
| `observe_command` / `observe_kind` | 产生本断言回显的观测步 / 其性质：`behavior`(dig/统计/session=验业务行为,V 性质) 或 `config_query`(show 配置=看配置在不在,G 性质) |
| `matched_config_command` | expect 命中的前序配置命令（非空=该断言只是 found 一条配过的配置=配置存在性检查） |
| `is_config_existence_check` | 观测是配置查询 show 且 expect 命中前序配置命令（G 段配置存在性，不算覆盖） |
| `is_genuine_v_assertion` | 基于**有效行为观测**（behavior 且回显有效）的真 V 段断言（贡献覆盖） |
| `layer_mismatch` | draft 标 layer=V，实为配置存在性检查（名 V 实 G=伪覆盖/秩亏） |
| `source_kind` / `source_ref` | 本 check_point 步的来源类型/定位（核 source_ref 真支撑期望值） |
| `query_object_invalid` | 观测步回显语法错误/孤立 ^（dangling，无有效回显） |
| `expect_is_error_echo` / `spec_conflict_suspect` | 期望值本身是设备错误回显(Invalid input/not support…) / 且来源 kind=intent(仅凭脑图意图、无手册溯源)=疑似脑图预期与手册冲突 |
| `is_distribution_assertion` / `count_tautology_suspect` | 分布区间断言(distribution_derived 或有界计数区间正则,分布类合法 V) / 命中计数用无界 `\d+`(任意数都过=恒真) |
| `count_hardcoded_suspect` / `asserts_literal_hit_ip` | 分布算法下命中计数写死固定数(偶对偶错) / 分布算法下 dig found 写死单个成员 IP(写死命中落点=不可证伪) |
| `suspect` / `suspect_reason` | 本 cp 存疑(layer_mismatch / dangling / spec_conflict) / 可读说明 |

case 级（顶层）字段：

| 字段 | 含义 |
|------|------|
| `has_mutating_under_test` | case 含 clear/no… 瞬时态命令（意图通常要测其运行时行为） |
| `genuine_v_count` | 名副其实的 V 段断言数（真覆盖目标行为的断言） |
| `weak_v_coverage_suspect` | 有被测瞬时态行为却 `genuine_v_count==0`——秩亏/弱 V 覆盖（恒真嫌疑） |
| `spec_conflict_suspect` | 任一断言「kind=intent + 错误回显」——疑似脑图预期与手册/实机冲突（断言设备报错却无手册依据） |
| `has_distribution_method` / `lb_methods` | 配了分布算法 rr/wrr/grr/gwrr / 检出的算法 token |
| `has_distribution_assertion` / `distribution_assertion_count` | 有分布区间断言 / 其条数 |
| `count_tautology_count` / `distribution_coverage_gap_suspect` | 无界计数恒真断言数 / 配了分布算法却无分布区间也无关系断言（漏测分布，dongkl WEAK_no_count 类） |
| `count_hardcoded_count` / `hardcoded_count_suspect` | 写死固定命中计数断言数 / 分布算法下存在这类写死计数（偶对偶错） |
| `asserts_literal_hit_ip_count` / `hardcoded_hit_ip_suspect` | 写死单次命中落点 IP 的断言数 / 分布算法下存在这类写死命中 IP（observe-then-assert，778012 根因） |

## 互斥分支（逐 check_point 选一条走）

- **A 普通字面断言**（mode=found/not_found，cp_h 空，suspect 全 false）：
  核 `source_ref` 是否真支撑期望值——`kind=manual` 精读那一处，`kind=precedent` 看那条先例的同类断言。
  支撑 → 覆盖到位；ref 缺失/对不上 → 低分/CUT。

- **B 捕获比较断言**（寄存器引用，`cp_h` 非空）：照"同源可比 + 方向对"判（见 SKILL.md 例外段）。
  G 列空属正常、**不砍**；只看 (a) 捕获源与本次观测同源可比？(b) found/not_found 方向对上需求的同/异关系？

- **C `<RUNTIME>` 占位**（source_kind=device_runtime）：判**方向相反**的事——这个点是不是**真的**离线不可知？
  弃权理由成立 → 覆盖到位（诚实标待验点）；本可离线定值却偷懒标占位 → CUT（误标弃权）。**绝不因"没填具体值"判 CUT**。

- **C2 分布区间断言**（`is_distribution_assertion==true`，source_kind=distribution_derived 或有界计数区间正则）：
  分布类算法（rr/wrr）的合法 V 覆盖——各后端累计命中∈统计区间（守恒 Σ==N，已过 emit 守恒+反恒真门）。
  **绝不因"没写死单次命中数/是区间不是定值"判 CUT**。判**方向相反**的两件事：
  (a) 算法类型对不对——rr/wrr 才用分布区间；ga（优先级故障切换）/一致性哈希/会话保持是确定性映射，套了分布区间反而错 → CUT，改回 B 关系断言；
  (b) 有没有退化恒真——`count_tautology_suspect`（命中计数用无界数值正则，任意数都过）或区间上界≥总次数 → CUT。
  case 级 `distribution_coverage_gap_suspect==true`（配了 rr/wrr 却无分布区间断言也无关系断言）= 漏测分布 → **CUT**，重做意见指明应补分布区间断言（`dist` 声明：发 N 次→统计命令→各后端命中∈[N/k±容差]）。

- **C2′ 分布算法下的写死落点（observe-then-assert，必 CUT）**：`hardcoded_hit_ip_suspect==true`（dig 断言写死某个成员 IP，等于断言"这一发必中它"）或 `hardcoded_count_suspect==true`（命中计数写死固定数）——分布算法(rr/wrr)下命中哪个/命中几次由运行时轮转起点决定，写死=偶对偶错的假断言（与 absolute_position 同病）。**判 CUT**，重做意见指明：单次命中改 H 捕获比较关系断言（`captured_relation`，验"两次同/异"），多次累计命中改分布区间断言（`dist`）；都不要写死单次命中的 IP / 计数。（这正是 778012 首轮带病 PASS 的形态，确定性信号现已能拦。）

- **D 恒真/弱 V 覆盖审查**（`layer_mismatch==true` 或 case 级 `weak_v_coverage_suspect==true`）：
  按论文"覆盖只由 V 段断言判定"——`layer_mismatch` 的断言是"配 X→show X→found X"的配置存在性检查（名 V 实 G），
  不验任何业务行为；若 case 有被测瞬时态行为（clear/no…）却 `genuine_v_count==0`（全是配置存在性凑数）→ V 段覆盖=0=秩亏 → **CUT**。
  重做意见须指明：应补对**被测行为**的 V 段断言——断言对象必须是被测命令**实际所动的对象**
  （运行时表清除前后的差异、重新请求后行为的变化等），期望回显/期望值由 draft 查手册/先例溯源、
  **不在重做意见里替它给定**（给定了就是把本意见当答案模板抄，答案错了会逼出上机必 fail 的假断言）——
  而非去 found 一张被测命令根本不动的静态配置表。
  **⚠ 豁免（防误杀删除/配置验证类，对抗 review MEDIUM）**：若 case 意图本就是「删除/清除某配置」（`no/clear 某配置` + 用 `show`/`not_found` 验证**该配置**删除生效），
  则该 config/not_found 断言验的是**被测删除操作的正确效果**（配置删后不在了）= 覆盖到位，**不算秩亏、不因 weak_v 误 CUT**。
  秩亏专指：动**运行时态**（session/连接表/统计态）的命令却去 found 一张该命令**根本不动**的静态配置表
  （断言对象 ≠ 被测命令所动的对象）；删除配置 + 验证该配置已删（断言对象 = 被删对象），是合法覆盖，放行。

- **E 预期冲突审查**（`spec_conflict_suspect==true`）：该断言期望值是设备错误回显，但来源 `kind=intent`（无手册/先例溯源）。
  核 `source_ref`：若 ref 只是复述脑图预期（"需求：提示不支持ALL参数"）、grep 手册无依据、甚至 ref 自相矛盾（"设备应拒绝**合法的** ALL"）→
  **脑图预期与手册/实机冲突**，draft 改不动（改了就是迎合错误预期、编一个上机必 fail 的假断言）→ **CUT**，根因标 `用例预期冲突`。
  实证 589432：断言期望某参数被设备拒绝并报错，ref 却只是复述脑图预期、手册查无此限制——重做也编不出有手册依据的断言。
  （历史案例只说明形态；具体参数在当前设备上合不合法，以手册/先例为准，勿把案例当行为结论引用。）

## Validation（输出前自检）

- 每条判定逐条引用 `row_line` + `source_ref`（来源对不上的明确写"读出来是 X，期望是 Y"）。
- 走 D 分支判 CUT 的，把"命令改 X 表 / 断言查 Y 表（恒存在）"写清。

## 交付（工具提交 + 文本标记双通道）

结论定了先调 **`submit_verdict`**（verdict=PASS|CUT；CUT 附 root_cause=`用例预期冲突`（期望值无任何
手册/先例支撑，且与手册/实机矛盾，非 draft 可修）或 `可修复`（草稿质量问题，重做有望通过）；
caveats=上机注意事项数组；report_md=完整审批报告）。凭证由工具落盘，合并门直接认。

**然后返回的末行仍单独成行输出文本标记**：`判定：PASS` 或 `判定：CUT`（CUT 前一行
`根因：用例预期冲突|可修复`）——pipeline fallback 的 `_parse_grade_verdict`
（解析正则 `根因\s*[:：]\s*(用例预期冲突|可修复)`，取最后一个匹配）靠这行，双通道并存。
