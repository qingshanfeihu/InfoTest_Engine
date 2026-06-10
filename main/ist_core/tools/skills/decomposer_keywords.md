# 拆分工具关键词配置

## 0. Phase + Type 推断关键词

用于推断步骤的阶段（Phase）和类型（Type）。

### Trigger phase - client_action

| 关键词模式 | 说明 |
|-----------|------|
| `dig\s`、`dig @` | DNS 查询 |
| `ping\s`、`ping -c` | 连通性测试 |
| `curl\s`、`wget\s` | HTTP 请求 |
| `发包`、`打流量`、`发送请求`、`发送流量`、`发送` | 流量测试 |
| `访问`、`请求`、`客户端发起` | 客户端动作 |
| `nslookup`、`^host\s` | DNS 查询（host 命令必须在行首） |
| `ssh\s`、`telnet\s` | 远程访问 |

### Verify phase - capture_verify

| 关键词模式 | 说明 |
|-----------|------|
| `debug`、`trace`、`抓取` | 设备抓包验证（debug/trace） |
| `tcpdump`、`wireshark`、`抓包` | 客户端/服务器抓包验证 |
| `查看`、`验证`、`检查`、`确认` | 验证操作 |
| `显示`、`show\s`、`查看配置` | 查询状态 |
| `断言`、`预期`、`应该`、`应当` | 断言操作 |
| `成功`、`失败`、`正常`、`异常` | 结果判断 |
| `包含`、`不包含`、`存在`、`不存在` | 内容检查 |
| `一致`、`不一致`、`匹配`、`不匹配` | 比较操作 |
| `命中`、`返回`、`解析` | 结果验证 |
| `日志`、`log`、`syslog` | 日志查看 |

### Setup phase - device_config

| 关键词模式 | 说明 |
|-----------|------|
| `配置`、`创建`、`添加`、`设置`、`删除`、`no\s`、`启用`、`禁用`、`开启`、`关闭` | 设备配置操作 |
| `导入`、`导出`、`绑定`、`解绑`、`激活`、`取消激活` | 证书/资源操作 |
| `sdns\s`、`slb\s`、`ha\s`、`firewall`、`ip\s`、`interface`、`vlan`、`bond` | 网络配置命令 |
| `初始化`、`基础环境`、`前置`、`setup`、`初始化SDNS` | 初始化操作 |
| `write\s`、`保存`、`save`、`write memory` | 保存配置 |
| `重启`、`reboot`、`升级`、`降级` | 系统操作 |
| `sdns host`、`sdns service`、`sdns pool`、`sdns listener`、`sdns zone` | SDNS 配置 |
| `slb virtual`、`slb real`、`slb group` | SLB 配置 |
| `ssl host`、`ssl monitor`、`证书`、`certificate` | SSL 配置 |
| `monitor`、`健康检查`、`health check` | 健康检查配置 |
| `查看`、`验证`、`检查`、`确认` | 验证操作 |
| `显示`、`show\s`、`查看配置` | 查询状态 |
| `断言`、`预期`、`应该`、`应当` | 断言操作 |
| `成功`、`失败`、`正常`、`异常` | 结果判断 |
| `包含`、`不包含`、`存在`、`不存在` | 内容检查 |
| `一致`、`不一致`、`匹配`、`不匹配` | 比较操作 |
| `日志`、`log`、`syslog` | 日志查看 |

### Verify phase - device_query

| 关键词模式 | 说明 |
|-----------|------|
| `show sdns` | SDNS 状态查询 |
| `show slb` | SLB 状态查询 |
| `show ha` | HA 状态查询 |
| `show ip` | IP 状态查询 |
| `show interface` | 接口状态查询 |
| `show vlan` | VLAN 状态查询 |
| `show route` | 路由状态查询 |
| `查看状态`、`查询状态` | 状态查询 |

---

## 1. Actor 分类关键词

用于判断步骤由谁执行（APV_0/APV_1/test_env/check_point）。

| 关键词模式 | Actor | 说明 |
|-----------|-------|------|
| `dig\s`、`ping\s`、`curl\s`、`wget\s`、`发包`、`访问`、`请求` | test_env | 客户端工具 |
| `备机`、`APV_1`、`apv1`、`standby`、`slave`、`peer` | APV_1 | 备机 |
| `配置`、`添加`、`创建`、`设置`、`删除`、`no\s`、`sdns`、`slb`、`firewall`、`route` | APV_0 | 设备配置 |
| `show`、`查看`、`write\s`、`reboot`、`重启`、`启用`、`开启`、`关闭` | APV_0 | 设备操作 |
| `dig`、`ping`、`curl`、`wget`、`访问`、`请求`、`发包`、`打流量`、`客户端` | test_env | 客户端/测试环境 |
| `check\d*\]`、`预期`、`验证`、`断言`、`应当`、`应该`、`成功`、`失败`、`正常`、`异常` | check_point | 断言检查点 |

**注意**：check_point 规则不能包含 `$`（空字符串匹配），否则任何文本都会被匹配为 check_point。

---

## 2. Action 推断关键词

用于判断步骤的具体动作类型。

### APV_0 的 Action

| 关键词模式 | Action | 说明 |
|-----------|--------|------|
| `reboot`、`重启`、`升级`、`降级` | execute | 特权操作（脱离config模式） |
| `write\s`、`保存`、`save` | cmd_config | 保存配置命令 |
| `初始化`、`基础环境`、`基础配置`、`前置`、`setup` | cmds_config | 多条初始化命令 |
| `配置`、`添加`、`创建`、`设置`、`删除`、`no\s`、`启用`、`开启`、`关闭`、`show`、`查看` | cmd_config | 单条配置命令 |

### APV_1 的 Action

| 关键词模式 | Action | 说明 |
|-----------|--------|------|
| `show`、`查看`、`检查`、`显示` | cmd_config | 查看命令 |
| `配置`、`添加`、`创建`、`设置`、`删除` | cmd_config | 单条配置命令 |

### test_env 的 Action

| 关键词模式 | Action | 说明 |
|-----------|--------|------|
| `ping` | clientc | ping测试 |
| `curl`、`wget`、`http` | clientc | HTTP请求 |
| `dig`、`nslookup`、`dns` | routera | DNS查询 |
| `发包`、`syn`、`flood`、`压力`、`stress`、`压测`、`循环`、`多次` | clientc | 发包/压力测试 |

### check_point 的 Action

| 关键词模式 | Action | 说明 |
|-----------|--------|------|
| `失败`、`错误`、`不能`、`无法`、`不支持`、`丢`、`不包含`、`不存在`、`不应` | not_found | 负向断言 |
| `成功`、`正常`、`可以`、`能够`、`应该`、`包含`、`存在`、`正确` | found | 正向断言 |

---

## 3. 高位动作匹配关键词

用于匹配特殊的高位动作，直接标记 action。

| 关键词模式 | Action | Actor | 说明 |
|-----------|--------|-------|------|
| `配满\d+条sdns listener` | 配满sdns listener | APV_0 | 配满sdns listener |
| `删除sdns listener` | 删除sdns listener | APV_0 | 删除sdns listener |
| `配满\d+条sdns host name` | 配满sdns host name | APV_0 | 配满sdns host name |
| `删除sdns host name` | 删除sdns host name | APV_0 | 删除sdns host name |

---

## 4. 功能依赖关键词

用于检测跨模块依赖，自动注入前置功能步骤。

| 关键词 | 依赖步骤 | 说明 |
|-------|---------|------|
| `vip` | 创建SLB虚拟服务 | sdns listener on slb vip → 先创建 slb virtual |
| `ha fip` | 配置HA浮动IP | sdns on ha fip → 先配置 ha fip |
| `全域名功能` | 配置全域名功能 | 需要 zone + nameserver + record 前置 |

---

## 5. 模块检测关键词

用于从模块路径和步骤文本推断大模块（SDNS/SLB/HA 等）。

| 关键词 | 大模块 | 说明 |
|-------|--------|------|
| `sdns` | SDNS | SDNS 功能 |
| `slb`、`virtual`、`real`、`group`、`健康检查` | SLB | SLB 功能 |
| `ha`、`高可用` | HA | HA 功能 |
| `firewall`、`acl`、`安全策略`、`访问规则` | Firewall | 防火墙功能 |
| `llb`、`链路负载` | LLB | 链路负载 |
| `gslb` | GSLB | 全局负载 |
| `ssl` | SSL | SSL 功能 |
| `dpi`、`深度报文` | DPI | 深度报文检测 |
| `qos`、`服务质量` | QoS | 服务质量 |
| `cluster`、`集群` | Cluster | 集群 |
| `link-aggregation`、`链路聚合`、`bond` | LinkAggr | 链路聚合 |
| `ipsec`、`ike`、`vpn`、`tunnel` | VPN | VPN 功能 |
| `route`、`bgp`、`ospf`、`路由` | Routing | 路由功能 |
| `dns64`、`nat64` | IPv6 | IPv6 功能 |

---

## 6. 前置条件推断关键词

用于根据模块和步骤描述，补充隐含的前置依赖。

| 关键词 | 前置说明 |
|-------|---------|
| `sdns listener` | 需要先启用SDNS功能(sdns on)并配置基础环境: sdns host name, sdns service ip, sdns pool, sdns host pool |
| `sdns host name` | 需要先启用SDNS功能(sdns on) |
| `sdns service ip` | 需要先启用SDNS功能(sdns on) |
| `sdns pool` | 需要先启用SDNS功能(sdns on)并定义sdns service |
| `sdns zone forward` | 需要先启用SDNS功能(sdns on) |
| `slb virtual` | 需要确保SLB功能已启用, 相关接口IP已配置 |
| `slb real` | 需要先定义slb group |
| `slb group` | 需要确保SLB功能已启用 |
| `ha synconfig` | 需要先配置HA基本环境(ha on, ha link, ha unit等) |

---

## 7. 验证步骤推断关键词

用于在 check_point 前推断应该执行的 show 命令。

| 关键词 | Show 命令 | 说明 |
|-------|----------|------|
| `persistence`、`会话保持` | show sdns host persistence | 查看会话保持配置 |
| `forward_only`、`zone forward` | show sdns host name | 查看域名配置 |
| `host name` | show sdns host name | 查看域名配置 |
| `service ip` | show sdns service ip | 查看服务IP配置 |
| `pool` | show sdns pool name | 查看池配置 |
| `zone` | show sdns zone name | 查看区域配置 |
| `listener` | show sdns listener | 查看监听器配置 |
| `slb`、`virtual` | show slb virtual-server | 查看虚拟服务配置 |
| `ha` | show ha status | 查看HA状态 |
| `dps` | show sdns dps path | 查看DPS路径 |
| `rewrite`、`http` | show http rewrite response | 查看HTTP重写配置 |

---

## 8. check_point 判断关键词

用于判断 check_point 是正向断言还是负向断言。

### 负向断言关键词（not_found）

```
失败、不能、无法、不支持、错误、不可以使用、不可以、未被保存、未生效、不存在、不命中
```

### 正向断言关键词（found）

```
成功、失败、正常、异常、可以使用、不可以、正确、错误、生效、未生效、同步、不同步、命中、不命中、显示、提示、删除、不存在
```

---

## 9. 客户端动作拆分关键词

用于检测"配置+客户端动作"合并步骤，拆分为两步。

| 关键词模式 | 说明 |
|-----------|------|
| `打流量` | 打流量动作 |
| `发送?(?:请求|流量|包)` | 发送动作 |
| `客户端` | 客户端动作 |
| `连续.*?(?:请求|访问|dig|ping)` | 连续请求动作 |
| `dig\s` | dig 命令 |
| `ping\s` | ping 命令 |
| `curl\s` | curl 命令 |
| `wget\s` | wget 命令 |
| `发包` | 发包动作 |

---

## 10. 用例描述动作词

用于判断用例描述是否应该作为步骤（extractor 中使用）。

| 关键词 | 说明 |
|-------|------|
| `配置` | 配置动作 |
| `创建` | 创建动作 |
| `删除` | 删除动作 |
| `发送` | 发送动作 |
| `修改` | 修改动作 |
| `设置` | 设置动作 |
| `启用` | 启用动作 |
| `禁用` | 禁用动作 |
| `开启` | 开启动作 |
| `关闭` | 关闭动作 |
| `添加` | 添加动作 |
| `移除` | 移除动作 |
| `导入` | 导入动作 |
| `导出` | 导出动作 |
| `绑定` | 绑定动作 |
| `解绑` | 解绑动作 |
| `重启` | 重启动作 |
| `升级` | 升级动作 |
