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
