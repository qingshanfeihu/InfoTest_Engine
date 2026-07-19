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
6-8 entries 草案 **8**（5 statements + 3 reference_closures）→ **#52 fine-check 后 landed 4 statements + 2 closures**（订正见 §5）。

## §5 LLM-Eng fine-check 订正记录（#52 cross-check，审计痕迹保留、非静默重写）

本草案 pattern 从 §7 CLI 频度推、未逐字核 manual（§6 已预留「待精校」口）——LLM-Eng #52 fine-check 对 manual verbatim 精校，**Theory 读 manual 复核全部 concur**：

| # | 我 draft | LLM-Eng 订正 | manual verbatim 证据（Theory 复核） | 判 |
|---|---|---|---|---|
| F1 | slb_real_health_bind 首 token=rs | **DROP**（+其 closure） | manual `slb real health <hc_name> <real_service> <ip> <port>` 首参=**hc_name 非 real**（我捕获错 token）；gold standard health 全用 `slb virtual health on\|off`（VS-toggle，多卷 verbatim、零 real ref） | concur DROP |
| F2 | vip/rsip `[\d.]+`（IPv4 only） | widen `[0-9a-fA-F:.]` | gold standard `slb virtual tcp v1 2::abcd`（IPv6 VS verbatim）+ SLB IPv6 test list | concur |
| F3 | port `\d+` 必需 | port optional | `slb real dns dns_rs1 192.168.2.x` / `"RS_DNS_1" 10.1.1.10`（无 port verbatim） | concur |
| F4 | roles vs/rs/group | rename concern→`name` | dangling_references detector 读固定 concern（sdns host_pool_bind 用 `name`）——vs/rs/group 读不到崩 closure | concur |
| F5 | slb_policy_needs_vs_and_group | narrow policy→VS；policy→group DEFERRED | policy→group=multi-concern closure，detector 现 single-concern；见 RULING（recommend generalize detector） | concur narrow |

**净结果 theoretically sound**：drop 1=纠我 pattern 实证错误、narrow 1=detector 机制约束下正确 scoping、F2/F3=覆盖**扩大**（我 draft 过窄）。cross-check 抓到 3 实证错误+2 遗漏——正是 §6 预留「pattern 待逐字精校」口的设计闭环。G3/G5 仍 DEFERRED（scoped）。
