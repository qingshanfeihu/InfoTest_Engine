---
name: AGENTS
created: 2026-05-21T00:00:00+08:00
updated: 2026-05-21T00:00:00+08:00
---
# IST-Core 项目长期指令

deepagents MemoryMiddleware 在每次 agent 启动时把本文件内容注入 system prompt。
改动后立即生效（下一轮新 agent 实例），不需要重启服务。

## 产品域强约束（与 _prompt.py Product Domain 互补）

- APV / NSAE 命令禁止用 F5 / A10 / Radware / NetScaler / HAProxy 类比解释
- 用例编号 21xxx 系列默认走 cookie / SLB HTTP 加密相关 spec，先 web_bug_search

## 评审入口约定

- 用户说 "评审 / review / 审一下" → 第一个 tool_call 必须是 qa_invoke_skill(skill="test-list-review")
- 找不到匹配 skill 才走通用 grep 路径

## 已确认的失败案例（避免重犯）

- DashScope 端点不走本地 cc switch 代理（详见 /memories/feedback/）

## 维护规则

- 单条规则一行；>300 行触发 dream task LLM 蒸馏
- 用户显式说 "以后 / 下次 / 记住" 才升级到 /memories/preferences.md，普通对话留 /working/
- 用户说 "评审 / review / 审一下" + 明确提及测试用例/BUG/测试策略 → 第一个 tool_call 必须是 qa_invoke_skill(skill="test-list-review")，且立即执行（不延迟、不先 grep）
- 用例编号 21xxx 系列默认走 cookie / SLB HTTP 加密相关 spec，优先调用 web_bug_search(BUG-XXXXXX) 获取上下文
文件操作必须限制在 knowledge/data/ 和 workspace/ 目录内，禁止使用绝对路径（如 /Users/...），避免 sandbox 路径错误
- SDNS 测试用例初始化必须包含 `sdns listener <ip>` 和 `sdns host method <host_name> rr` 命令，且 init_commands 参数必须用换行分隔各命令，不能空格拼接。
- SDNS 测试中，dig 查询域名必须使用框架初始化配置中已有的域名（如 autotest.com），外部域名（如 www.example.com）可能因 SDNS 未配置转发而返回 NXDOMAIN。
- SDNS 测试中，框架模块 sdns 的初始化配置会自动执行以下命令：sdns on、sdns host name autotest.com、sdns service ip ip1 172.16.35.231、sdns pool name pool1、sdns pool service pool1 ip1、sdns host pool autotest.com pool1。因此，测试用例可以直接使用 autotest.com 作为已配置的域名进行查询，无需额外配置。
配置 SSL 服务时，创建 ssl host 后必须执行 `ssl start <host_name>` 启用；对于 real 类型服务（`slb real https` / `slb real tcps`），还需先执行 `ssl host real <name> <real_service>` 绑定，否则 SSL 不生效。
- 已确认的失败案例：agent 频繁使用单数目录名（workspace/input/、workspace/output/）导致路径错误，应始终使用复数形式（workspace/inputs/、workspace/outputs/、workspace/defects/）
- 已确认的失败案例：agent 频繁使用单数目录名（workspace/input/、workspace/output/）导致路径错误，应始终使用复数形式（workspace/inputs/、workspace/outputs/、workspace/defects/）
- SDNS pool cname 在 Beta.APV-HG-K.10.5.0.585 (build Jun 25 2026) 上必须使用两步语法：`sdns pool cname name <pool_name>` 创建池，再 `sdns pool cname member <pool_name> <cname_target>` 添加成员；手册扁平语法在此 build 上被拒绝。
- SDNS 测试中，`clear sdns host method` 在 Beta.APV-HG-K.10.5.0.585 上不清除默认 rr 算法配置，只清除 wrr/ga 行。测试断言应避免假设表全空，要么用 `no sdns host method` 逐个删除，要么只断言非默认算法已移除。
- `show sdns host pool` 在 Beta.APV-HG-K.10.5.0.585 上只显示第一条 host-pool 关联，不要断言显示所有 pool。编写断言时应只检查第一条记录。
所有测试用例的 init_commands 必须用 \n（换行符）分隔各条命令，不能空格拼接（进卷成 cmds_config 步逐行发送；空格拼接会成一条非法长命令被设备拒）。
