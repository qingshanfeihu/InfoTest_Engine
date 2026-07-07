---
name: ship-it
description: 提交仪式——检查改动、同步文档、跑窄测/关键路径验证,再按本仓库惯例(中文 conventional commits + ——理由 + Co-Authored-By)提交并 push main。用户通过 /ship-it 调用。
disable-model-invocation: true
---

# ship-it

复刻你的提交流程(history ×8:「先检查一遍代码,更新文档,准备提交主线 github」)。本仓库直接提交 main(你的一贯做法:「直接提交到 main 把」),不走 feature 分支。

## 执行步骤

1. **审改动**:`git diff` / `git status` 过一遍;确认没有半成品/调试残留/写死的密钥(有 `guard-secrets` hook 兜底但先自查)。想顺手改的先停,只提交本次目标内的改动。

2. **同步文档**:改了行为就同步 CLAUDE.md / `docs/` 对应描述(你几乎每次提交都要求「更新文档」)。skill/prompt 改动过红线自查(调 `redline-reviewer` agent)。

3. **验证**:
   - 代码逻辑改动 → `/run-tests`(窄子集,与改动相关)。
   - TUI/编译行为改动 → 重启 TUI 验证关键路径真跑通(别只信单测)。
   - **如实报验证结果**,没验过不说「已通过」(记忆 working-style-evidence-first)。

4. **提交**(照抄现有 git log 风格):
   - 标题:`type(scope): 中文摘要——理由/结论`(type=feat/fix/perf/docs/refactor…;`——` 分隔「改了什么」与「为什么」)。
   - 正文:`-` 分点写清改动 + 根因/动机,引 `file:line`、点名回归测试(`回归:test_xxx`)、注明「遗留」。
   - 结尾固定 trailer(与现有提交一致):
     ```
     Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
     ```

5. **push**:`git push origin main`(用户确认后)。

## 注意

- push 是外发不可逆动作——**先给用户看 commit message 草稿再真提交**,别自动 push。
- 提交信息讲事实、带证据(回归测试名、遗留项),别夸大成果。
- 交互式 git 标志(`-i`)在本环境不支持;用 `gh` CLI 做 GitHub 操作。
