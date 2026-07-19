# SLB Grammar Entries Draft（#51 sequencing follow-up）

> #51-C 派生：draft SLB **first-batch**（G1 virtual / G2 real+group binding / G4 health check——scoped pilot,**skip G3/G5 deferred**）文法条目,让 SLB enablement 与 #52 SSL **并行**、不 serialize。
> **collision 避让**：本文是 **schema-shaped 草案表、不 edit `domain_grammar.json`**（LLM-Eng #52 正并发改该文件加 ssl 条目）。LLM-Eng 单写者一遍机械合入本表 + ssl 条目、四关同审。
> **schema**：statement={pattern(named-group regex),roles,provenance};reference_closure={id,references,defines,normalize,skip_leading_verbs,provenance}——严格同 sdns 现役条目。
> **诚实标注**：pattern 从 §7 SLB CLI 闭集频度推,**精确语法（可选参数序/引号）待 LLM-Eng 对 manual 逐字精校**（本草案给结构骨架+roles+provenance，非终态 regex）。

## §1 statements（5 条，merge into `domain_grammar.json.statements`）

| id | pattern（草案，待精校） | roles | provenance |
|---|---|---|---|
| `slb_virtual_service_define` | `slb\s+virtual\s+\w+\s+"?(?P<vs>[\w.-]+)"?\s+(?P<vip>[\d.]+)\s+(?P<port>\d+)` | vs=VS名 / vip=虚拟IP / port=端口 | §7 G1(`slb virtual service` 1181/`virtual http` 171/`virtual tcp` 121)；B §4.2 HTTPS2 VS |
| `slb_real_service_define` | `slb\s+real\s+\w+\s+"?(?P<rs>[\w.-]+)"?\s+(?P<rsip>[\d.]+)\s+(?P<port>\d+)` | rs=real名 / rsip=后端IP / port=端口 | §7 G2(`slb real http` 296/`real tcp` 186)；B G4 health-flip real IP:port driven |
| `slb_group_member` | `slb\s+group\s+member\s+"?(?P<group>[\w.-]+)"?\s+"?(?P<rs>[\w.-]+)"?` | group=组名 / rs=成员real名 | §7 G2(`slb group member` 808) |
| `slb_policy_default` | `slb\s+policy\s+default\s+"?(?P<vs>[\w.-]+)"?\s+"?(?P<group>[\w.-]+)"?` | vs=VS名 / group=组名 | §7 G2/G6(`slb policy default` 380) |
| `slb_real_health_bind` | `slb\s+real\s+health\s+"?(?P<rs>[\w.-]+)"?` | rs=被健检的real名 | §7 G4(`slb real health` 131)；B G4 health-flip THICK(41 assertion lines,good/bad) |

## §2 reference_closures（3 条，merge into `domain_grammar.json.reference_closures`）

> 语义同 sdns `cname_member_needs_local_host`：引用形态命中而定义形态缺席=**引用断头**（离线引用图可查,设备可能静默接受）。normalize=name（SLB 对象名,非 dns_name）。

| id | references | defines | normalize | skip_leading_verbs | provenance |
|---|---|---|---|---|---|
| `slb_group_member_needs_real` | `slb_group_member`(rs) | `slb_real_service_define`(rs) | name | no/clear/show | §7 G2:group 成员必先定义 real,否则 member 引用悬空 |
| `slb_policy_needs_vs_and_group` | `slb_policy_default`(vs,group) | `slb_virtual_service_define`(vs) + `slb_group_member`(group) | name | no/clear/show | §7 G2 binding:policy 绑定 VS↔group,二者未定义则绑定断头 |
| `slb_health_needs_real` | `slb_real_health_bind`(rs) | `slb_real_service_define`(rs) | name | no/clear/show | §7 G4:health 挂在 real 上,real 未定义则健检无对象；B G4 41 lines 均先配 real |

## §3 merge 指令（给 LLM-Eng 单写者）

- **机械合入**：§1 五条 → `statements` dict（key=id）;§2 三条 → `reference_closures` list（append）。与 ssl 条目**同一 batch、单写者一遍**,避免 domain_grammar.json 并发写冲突。
- **合入前精校（LLM-Eng）**：① pattern regex 对 SLB manual（`SLB methods introduction.md` / apv cli md）逐字核——可选参数序、引号规则、`slb virtual {type}` 的 type 闭集(tcp/http/tcps/tuxedo…§7 G1)；② `footprint_node`/`silently_accepted` 字段按 sdns 体例补（本草案未填,待设备实证或 manual 定——**诚实留空、不臆造**）。
- **first-batch scope**：仅 G1/G2/G4（scoped pilot,#51-C SLB-first SCOPED verdict）。**G3 scheduling-distribution / G5 L4 persistence 的文法 DEFERRED**（B 证零先例=novel authoring,押 footprint-building 后,勿在本批加）。
- **四关**：合入后随 ssl 条目走四关（Design 一致性 + Theory 理论面 + redline + leader pytest）。本草案 Theory 侧结构=引用闭包同 sdns 现役体例,理论面无新构件（复用既有 statement/reference_closure 机制,零新公式）。

## §4 estimate 对账
6-8 entries 预期 → 实交 **8**（5 statements + 3 reference_closures），覆盖 first-batch G1/G2/G4 的定义形态 + 引用闭包。G3/G5 DEFERRED 未计（scoped）。
