# 厂商 CLI 关键词表(识别「这是本产品自有命令」)

来源:主 agent 系统提示 Product Domain 节(2026-07-04 B2 资产分离迁出——资源归 knowledge,指令只留识别规则与本文件指针,见 docs/AUDIT_skill_standard_alignment.md)。

用途:判断某词是否 **信安世纪(Infosec)APV / NSAE** 自有 CLI。命中下列关键词 → 去 product/ 手册查证,不套 F5/A10/Radware/NetScaler/HAProxy 等通用 ADC 语义。

## 关键词

| 类别 | 关键词 |
|---|---|
| 顶层命令族 | `slb`、`sdns`、`gslb`、`apv`、`nsae`、`vlink` |
| real 服务 | `real http` / `real https` / `real tcp` / `real udp` |
| virtual 服务 | `virtual http` / `virtual https` |
| QoS | `policy qos` |
| 健康检查/会话保持缩写 | `hi` / `hip` / `chi`(等 group method 见下) |
| group method 缩写 | `rr`、`grr`、`sr`、`lc`、`lb`、`hi`、`hip`、`chi`、`ic`、`ec`、`rc`、`pi`、`pto`、`hh`、`chh`、`pu`、`hq` |

## 查证路径

- `knowledge/data/markdown/product/cli_*_Chapter*.md`(CLI 手册正文,`*` 匹配任意版本)
- `knowledge/data/markdown/product/cli_*_Appendix*.md`(附录)
- `knowledge/data/markdown/product/app_*_Chapter*.md`(应用配置指南)

未在上述文档命中 → 结论是「该命令在当前知识库未找到」,不按通用 ADC 经验编解释。
