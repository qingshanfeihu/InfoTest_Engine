# 产品文档地图

`knowledge/data/markdown/product/` 下的 30 份文档按用途分类。**评审用例时不要全读**，按本表按需取。

## 设计文档（理解架构与设计意图）

| 文档 | 适用于评审什么类用例 |
|---|---|
| `HTTP2_Design_Doc.md`（14KB）| HTTP/2 系列 |
| `HTTP2_refactor_design.md`（28KB）| HTTP/2 重构后的功能 |
| `HTTP2_cache_Design_Doc.md`（14KB）| HTTP/2 + cache |
| `APV_Network_DNS64_design.md`（11KB）| DNS64 / NAT64 |
| `ustack设计架构V3.md`（43KB）| **uproxy / fast path 等基础架构**——cookie / session / policy 类必读 |

## 功能规格（理解参数语义与边界）

| 文档 | 适用于 |
|---|---|
| `SLB_HTTP_COOKIE_SAMESITE_spec.md` | cookie SameSite |
| `APV_SLB_HTTP2_spec.md` / `APV_SLB_HTTP2_spec_phaseII.md` | HTTP/2 |
| `APV_SLB_HTTP20_spec.md` | HTTP/2 早期版本 |
| `APV_Network_DNS64_spec.md` | DNS64 |
| `APV_Support_Multi_Segment_Spec.md`（30KB）| 多段隔离 |
| `APV_segment_user supports_changing_password.md` | segment 用户密码 |
| `APV_SLB_ic_ec_rc support chi_hi as the first choise method_spec.md` | IC/EC/RC 算法 chi/hi |
| `SW_Func_Spec_*.md`（4 份）| 功能规格说明书 |

## CLI 与应用手册（查具体参数）

**注意**：这些是大文件（每份 >500KB），用 `qa_deepagent_grep` 定位 + `qa_deepagent_read_file` offset/limit 读 50 行附近就够，**禁止全读**。

| 文档 | 大小 | 用法 |
|---|---|---|
| `cli__part1-4.md` | 共 1.9MB | grep CLI 字面定位 |
| `app__part1-2.md` | 共 0.7MB | grep WebUI 操作步骤 |
| `cookie methods.md` | 10KB | cookie 系列必读 |
| `httponly.md` | 4KB | cookie httponly |

## PRD / 产品需求白皮书

| 文档 | 适用于 |
|---|---|
| `APV_SLB_HTTP2.0_Phase1_prd.md` | HTTP/2 早期 PRD |
| `WP-无缝适配Cookie SameSite属性的增强要求.md` | cookie SameSite 增强 PRD |

## 评审参考映射

按 BUG 关键词快速定位优先读什么：

- **cookie / ircookie / session / persistence**：先读 `cookie methods.md` + `ustack设计架构V3.md`（找 uproxy 部分）+ `SLB_HTTP_COOKIE_SAMESITE_spec.md`
- **http2 / h2**：`HTTP2_refactor_design.md` + `APV_SLB_HTTP2_spec_phaseII.md`
- **cache**：`HTTP2_cache_Design_Doc.md`
- **ipv6 / dns64**：`APV_Network_DNS64_design.md` + `APV_Network_DNS64_spec.md` + `APV IPv6应用交付网关.md`
- **segment / 多租户**：`APV_Support_Multi_Segment_Spec.md` + `APV Segmentation Deployment Guide_*.md`

## 测试方法论

`knowledge/data/markdown/qa/Test Strategy*.md` 是测试方法论沉淀：

- `Test Strategy SLB_HTTP2_phaseII.md`（31KB）—— HTTP/2 系列评审的反向依赖追问点
- `Test Strategy_HTTP protocol.md` —— HTTP 协议测试通用原则
