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

- 用户说 "评审 / review / 审一下" → 第一个 tool_call 必须是 qa_invoke_skill(skill="test-case-review")
- 找不到匹配 skill 才走通用 grep 路径

## 已确认的失败案例（避免重犯）

- DashScope 端点不走本地 cc switch 代理（详见 /memories/feedback/）

## 维护规则

- 单条规则一行；>300 行触发 dream task LLM 蒸馏
- 用户显式说 "以后 / 下次 / 记住" 才升级到 /memories/preferences.md，普通对话留 /working/
- 用户说 "评审 / review / 审一下" + 明确提及测试用例/BUG/测试策略 → 第一个 tool_call 必须是 qa_invoke_skill(skill="test-case-review")，且立即执行（不延迟、不先 grep）
- 用例编号 21xxx 系列默认走 cookie / SLB HTTP 加密相关 spec，优先调用 web_bug_search(BUG-XXXXXX) 获取上下文
