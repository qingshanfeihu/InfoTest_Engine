# SSL 吃透报告（#50 · 2026-07-19 · leader 合成）

> 起因：用户令「先把产品和自动化完全吃透，我怀疑SSL那部分的excel模版中的函数你们团队根本就没仔细读，甚至怎么用都不知道」。
> 对账结论：**怀疑成立**——此前 #47-49 对 SSL 函数只做了签名计数/门放行验证/观测盘点，零人逐函数精读用法；本报告是补课产物。
> 三线原始产物（全部证据按 id 引，本报告不复制）：
> **A 机制** `team4_ssl_method_cards.md`（25 证书函数+12 TFTP 变体+execute+server 逐个源码精读，每条 file:line）
> **B 用法** `team4_ssl_usage_patterns.md`（45 卷金标准 354 次调用全挖，verbatim 行+3 个完整 walkthrough）
> **C 特性** `team4_slb_ssl_feature_model.md`（7 特性域产品模型+四方矩阵：产品↔框架↔人工↔观测）
> 评审链：三线交叉互检（CC1-CC3）→ Design 六维格式审（1F 单点修后转 P，15 条互引逐条读验）→ leader 合成。

## 一、理解层终判：8 域吃透 6、带缺口 2、未吃透 0

| 特性域 | verdict | 备注 |
|---|---|---|
| F1 证书生命周期 / F3 profile 绑定 / F4 SNI / F5 双向认证 CA 链 / F6 CRL / F7 协议套件 | **吃透** | 四面证据齐 |
| F2 国密 SM2 | 带缺口 | sm2 activate 在框架中被注释（ssl_comm:712）——设计意图 vs bug 待问产品侧 |
| F6' OCSP | 带缺口 | 有配置无 show 观测（#49 已定格），间接投影需一次上机 probe |

框架方法列终形态：**证书生命周期=25 个专用方法族**（csrVhost/importKey/importCert/importSni×5/RootCA/InterCA/CRLCA/sm2×7/activeCert…）；配置对象（profile/协议/OCSP settings）=通用 cmds_config；验证=execute（活体 `dic_operation.py:57`）+ 设备侧抓包 + routera 客户端工具 + execute 内嵌断言（四形态）。

## 二、「数不出、读出来才知道」的核心事实（吃透的增量价值）

1. **#48 曾引的 `ssh_server.py:151 def execute` 是注释块内死代码**（:130-160 三引号块）；活体在 `dic_operation.py:57`。结论侥幸不变，但「grep 命中≠读过」被钉在自己证据上——本任务价值的第一实证。
2. **证书导入双分支**：文件名 `.key/.crt/.pem` 结尾→本地读文件内联粘贴；否则→TFTP 从硬编码 `172.16.35.215` 取。**CC3 实证：金标准全走本地分支**——床就绪只需本地 `cert/epolicy_ssl/*` 树，不需 TFTP 服务器。
3. **SM2 是 3 参双证书体系**（`keyType,vhost,keyFile`，签名/加密证书分开）——B 线曾按 RSA 观察泛化成 2 参，被 A 线源码+8 行金标准 verbatim 对账逮住（CC2）。若漏此项，worker 编 sm2 用例必产坏行。
4. **静默失败面 S1-S5**（V 层邻接假 fail 面，归因必备知识）：S1 证书文件缺→print+return 静默跳过，import 没发生、后续断言假 fail（最主风险）；S2 execute 动作名模糊匹配（≥0.8）误派→None；S3 server 超时部分输出；S4 TFTP 不可达；S5 H 存 None。
5. **CSR subject 硬编码**（US/CA/San Jose/clickarray/qa）——worker 不可变更，期望值必须按此。
6. **SSL 加密验证金标准实法=设备侧抓包+hex 断言**：`debug trace live tcp`（I 列注入端口）→ `found (1703 03)|(17 0303)`（TLS record 头）。#49 观测盘点漏了这整条通道（Theory 自认入档），taxonomy 修正为三值+execute 自验第四形态。
7. **金标准 SSL 用例把「编译器 105 卷零产出」的四能力用了个遍**：证书族 320 行 / execute 165 / server231 264 / 抓包步全用 I 列——真 SSL 测试离不开这四条路径；同时印证 I 列在 sdns 域零使用纯属需求侧（#48 归因再证）。
8. **断言层可迁移**：TLS record/目的 IP 断言全用现有 found/not_found 算子——卡点确认在证书/execute/server 前置步的 emit 产出，不在断言。

## 三、交叉互检战果（三线合璧的方法论证明)

- CC1：importKey/importCert 恒 2 参——源码↔金标准互证一致。
- CC2：sm2 3 参——**分歧不抹平出真金**，B 线观察错误被 A 线源码逮住并订正（审计痕迹保留）。
- CC3：TFTP 分支金标准未走——床依赖收窄（needs-probe 清单减重）。
- 双向订正：A 逮 B 的 sm2；B 的金标准 ground truth 反过来校 A 的参数分析；C 两次初判（漏抓包通道/「无专用方法」预判）被 A/B 证伪后诚实改判。

## 四、床就绪清单（收窄后，试点前一次性 probe）

必需：① 本地 `cert/epolicy_ssl/*` 证书树存在 ② server213/231/232 后端 config env 可达。
probe 项：③ import 交互 prompt 实际文本 ④ execute 模糊误派率 ⑤ 长证书内联是否截断 ⑥ routera openssl/curl 工具链 ⑦ OCSP 间接投影（`show statistics ssl`/stapling）。
已排除：TFTP .215 服务器（金标准未走）。

## 五、对试点的意义与开放问题

- **试点最短路径**：证书族 emit 通道（文法数据层 #23 P2-3）+ 上述床 probe → 照金标准证书导入序列（B 线 §3.1 walkthrough）编首批 1-2 卷。
- **attributor 知识候选**：S1-S5 静默失败面应入归因参考（防「假断言错」误归）。
- **产品侧问题候选**：sm2 activate 被注释（设计意图?）；OCSP config-有/show-无不对称；F4 SNI 有专用方法但金标准零用例（能力从未被人工测过）。
- **方法论沉淀**：「吃透=A 机制+B 用法+C 特性三线合璧+交叉互检」，此为新域接入五步单第 0 步的标准做法；「grep 命中≠读过/观察≠读参数/盘点≠读用法」三教训分别入 Design/LLM-Eng/Theory 记忆。
