# 反向依赖追问规则

读完 BUG 描述和产品设计文档之后，按 feature 类别主动追问反向依赖。这些规则来自老版评审 `_TAG_TO_ARCH_QUERIES`——它们是产品架构层面的"已知陷阱"，不是测试维度字典。

只在 BUG 真的涉及对应 feature 时才提；不在表里的 feature 不要硬套。

## 关键陷阱表

### Cookie / Session / Persistence / Policy 类
- **必查反向依赖**：uproxy 七层处理 → fast path 旁路风险
- **为什么**：cookie 类功能必须走 uproxy（七层处理），开启 fast path / http turbo 后，部分流量可能旁路 uproxy，导致 cookie 不被插入或重写
- **典型测试缺口**：开启 turbo 后 enc_name/enc_ip 加密 cookie 是否仍然正确；fast path 命中规则下 ircookie 是否生效
- **追问关键词**：fast path / http turbo / uproxy / 4 层 vs 7 层

### IPv6 / Dual Stack / TLS / SSL / Encryption 类
- **必查反向依赖**：IPv4 等效 IPv6 双栈一致性
- **为什么**：网络层 feature 必须 IPv4/IPv6 行为对等，单栈测试不够
- **典型测试缺口**：enc_ip 模式下 RS 是 IPv6 时加密结果格式；HTTPS 终止 + cookie 加密配合；IPv4-only / IPv6-only / 双栈 RS 各自行为
- **追问关键词**：dual stack / nat64 / dns64 / IPv6 RS

### HTTP/2 / H2 / fasthttp 类
- **必查反向依赖**：HTTP/2 旁路的 L7 feature 列表
- **为什么**：HTTP/2 大部分走 fasthttp 处理，许多 HTTP/1.1 的 L7 feature 在 HTTP/2 下不可用
- **典型测试缺口**：HTTP/2 客户端访问下 cookie 加密 / persistence 是否仍然生效；HTTP/1.1↔HTTP/2 协议切换时配置一致性
- **追问关键词**：HTTP/2 不支持的 feature / fasthttp 旁路 / h2 协议升级

### Reload / Upgrade / Config Save 类
- **必查反向依赖**：配置持久化 + 版本兼容回退
- **为什么**：reload 后配置丢失、跨版本升级时新字段被丢弃 / 旧字段被强制清零是常见现场问题
- **典型测试缺口**：write mem 后 reload 系统配置仍可见 + AES 密码 hash 一致；旧版本配置升级到新版本是否被正确识别；新版本配置降级到旧版本的行为（保留 / 删除 / 报错）
- **追问关键词**：reload / write mem / upgrade / downgrade / 版本兼容

## 怎么用这张表

1. 读完 BUG 描述（Step 1）和设计文档（Step 2）后，把功能关键词跟上表 4 类对照
2. 命中类别 → 把对应"典型测试缺口"问一遍当前用例，缺则写到评审报告缺口章节
3. **不命中**也是合法结论——不要为了打卡硬扣帽子
4. **追问关键词**只是辅助让你想到方向，最终缺口必须能追溯到产品文档 / Test Strategy 里的具体证据
