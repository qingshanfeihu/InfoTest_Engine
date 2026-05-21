# Phase 7 SKILL 精简实验结果

## 实验背景

Plan：SKILL.md 从 238 行精简到 42 行（去掉 8 步阅读链/进度清单/sub-agent），
加两条软提醒，DeepSeek thinking=disabled，Memory 重设计为通用回调架构。

## 实验配置

- 模型：DeepSeek v4-pro
- thinking：disabled（除 Test C 外）
- SKILL：精简版 42 行（除特别标注外）
- Memory：通用回调架构（评审 adapter）

## 评审对象

两个版本的同一份用例：
- **评审前原始版**：`/Users/jiangyongze/Downloads/Test List bug-to-case 121100 Cookie会话保持加密.xlsx`（273条）
- **评审后修改版**：`knowledge/data/markdown/qa/Test List bug-to-case 121100 Cookie会话保持加密.md`（265条，含人工评审建议的修改）

注意：之前 Phase 4-6 实验用的是"评审后修改版"MD。

## 实验结果

### 评审前原始版（xlsx）

| 测试 | 配置 | API调用 | 工具调用 | 建议数 | P0 | P1 | P2 |
|------|------|---------|---------|--------|----|----|-----|
| A | DS thinking=off + 精简SKILL + xlsx | 19 | 27 | **14** | 2 | 7 | 5 |
| B | DS thinking=off + SKILL触发(同query) | 13 | 23 | **14** | 2 | 7 | 5 |
| C | DS thinking=on + 精简SKILL + xlsx | 10 | 22 | **12** | 3 | 5 | 4 |

### 评审前原始版（MD，从xlsx新转换）

| 测试 | 配置 | API调用 | 工具调用 | 建议数 | P0 | P1 | P2 |
|------|------|---------|---------|--------|----|----|-----|
| D | DS thinking=off + SKILL + MD(/tmp，sandbox外) | 10 | 17 | **11** | 1 | 5 | 5 |
| E | DS thinking=off + SKILL + MD(sandbox内) | 12 | 16 | **13** | 3 | 5 | 5 |

注：Test D 因 sandbox 限制实际读的是知识库旧 MD，不公平。Test E 是公平对比。

### 评审后修改版（知识库MD，与之前实验同文件）

| 测试 | 配置 | API调用 | 工具调用 | 建议数 | P0 | P1 | P2 |
|------|------|---------|---------|--------|----|----|-----|
| F2 | DS thinking=off + **精简SKILL 42行** | 10 | 15 | **12** | 2 | 5 | 5 |

### Opus 静态读（CC agent，评审前原始版 xlsx）

| 测试 | 配置 | 耗时 | 工具调用 | 建议数 | P0 | P1 | P2 |
|------|------|------|---------|--------|----|----|-----|
| Opus | Opus 4.7 静态读 + 两条提醒 | 144s | 15 | **10** | 2 | 4 | 4 |

### 之前 Phase 4-6 实验（评审后修改版 MD，旧 SKILL 238行）

| 测试 | 配置 | 耗时 | 建议数 |
|------|------|------|--------|
| B(旧) | DS thinking=on + 旧SKILL 238行 | 245s | **15** |
| F(旧) | DS thinking=off + 旧SKILL 238行 | 644s | **18** |
| G(旧) | Opus 静态读（无SKILL） | 120s | **23** |

## 关键发现

### 1. SKILL 精简导致建议数下降

同一个 MD 文件（评审后修改版）：
- 旧 SKILL 238行 + thinking=off = **18 条**
- 精简 SKILL 42行 + thinking=off = **12 条**
- **差距：-6 条（33% 下降）**

结论：SKILL 阅读链对 DeepSeek 有 +6 条的增益，精简到 42 行过了头。

### 2. 输入格式（xlsx vs MD）影响不大

同一份原始数据：
- xlsx 输入 = 14 条
- MD 输入（sandbox内）= 13 条
- **差距：-1 条（可忽略）**

结论：格式不是瓶颈。

### 3. thinking=off 仍然优于 thinking=on

- thinking=off = 14 条
- thinking=on = 12 条
- **差距：+2 条**

结论：关 thinking 对 DeepSeek 评审更好（一致结论）。

### 4. Opus 数量少但质量碾压

Opus 只出 10 条，但包含：
- P0-1："只测了加密没测保持"——核心功能缺口
- P0-2："明文到加密过渡"——兼容性缺口
- P1-5："默认密钥一致性"——HA 场景

这些是 DeepSeek 14 条里完全没有的深度洞察。

### 5. 文件版本差异导致之前对比不公平

- 知识库 MD = 评审后修改版（含 global/default/详细 configure 描述）
- Downloads xlsx = 评审前原始版（不含这些）
- 之前 18 条 vs 现在 14 条的差距中，约 2 条来自文件版本差异，约 4 条来自 SKILL 精简

## 结论

1. **SKILL 不应精简到 42 行**——DeepSeek 需要阅读链引导（+6 条增益）
2. **但旧 SKILL 238 行有无用步骤**——进度清单/sub-agent/Step 3.5/6.6 可去掉
3. **最优方案**：中间版本 SKILL（~100-120行）+ thinking=off + 两条软提醒
4. **格式不是瓶颈**——xlsx 和 MD 效果一样
5. **模型能力是核心瓶颈**——Opus 10 条质量 > DeepSeek 14 条数量
