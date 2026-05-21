# Step 6.5 字面自检详细做法

Step 6.5 强制调 helper script 一次性产出 6 类异常，本文件给具体的"如何把脚本输出映射到评审报告"细则。

## 调用方式

```bash
python main/qa_agent/skills/test-case-review/scripts/sanity_check.py knowledge/data/markdown/qa/<用例文件名>.md
```

输出 JSON，含：

```json
{
  "status": "issues_found",
  "total_issues": 35,
  "total_rows": 263,
  "checks": {
    "block_mode_mismatch": [...],
    "outlier_identifiers": {...},
    "field_emptiness": {...},
    "duplicates_and_typos": {...},
    "type_marking_consistency": [...],
    "numerical_regularity": {...}
  }
}
```

## 6 类异常 → 评审优先级映射

### `block_mode_mismatch` → P0（数据错误）
**含义**：连续相邻行的 mode 突变（如行 76/78 都是 enc_name，行 77 突然写 enc_ip）。
**为什么 P0**：测试人员会照错描述执行，整条用例失效。
**报告写法**：列出每条 issue 的行号 + neighbor_mode + this_line_mode + desc_preview。
**例**：
> 行 77 mode 错位：邻居用例都是 `enc_name`，但描述写的是 `mode 为 enc_ip` —— 应改为 `enc_name`，否则 enc_name 的 passwd Negative 边界（特殊字符）就漏测了。

### `outlier_identifiers` → P0（错别字）
**含义**：标识符离群（如 vs11 出现 81 次但 vs12 仅 3 次）。
**判断准则**：top 标识符出现 ≥ 20 次时才认为有"主流"概念；离群项 ≤ 主流的 1/5 时才算可疑。
**报告写法**：写"行 X：vs12 仅出现 N 次，主流是 vs11（M 次），疑似错别字"。
**注意**：g3/g4 这种"同时存在的不同 group 名"通常合法（不同测试场景命名）；vs11→vs12 这种"主流名突然变一个字符"通常是错别字。结合上下文判断。

### `field_emptiness` → P1（结构性问题）
**含义**：字段填充率 < 50%。
**重点关注**：
- `Result` / `Automated` / `Test Build` 100% 空 → **用例可能从未真正执行过**（这是评审最强信号，必须 P0 标出）
- `ID` 96%+ 空 → 违反自家 Option Definition（Case ID 应 10 位数字）
- `Release` / `Note` 高空率 → 跟踪信息缺失
**报告写法**：表格列出每个字段的 `空值数 / 总数 (百分比)`，并说明影响。

### `duplicates_and_typos` → P0（错别字 + 复制粘贴）
**含义**：中文叠字（"为为"）+ 未闭合双引号 + Description 列完全重复（>20 字符）。
**子类**：
- 中文叠字 → P0：明显是"配置参数为a"被打成"配置参数为为a"
- 未闭合双引号 → P1：可能是 Markdown 转义问题，但要核对是否影响读
- Description 重复（如 segment webui 跟 webui 字字相同）→ P0：要么删除冗余，要么明确说明差异

### `type_marking_consistency` → P1（规范执行不到位）
**含义**：同类用例（如 CLI help 提示）标了不同的 Test Types（如有的标 Configuration、有的标 Boundary）。
**报告写法**：列出每个 Type 下的代表性用例行号，标"标记不一致"。

### `numerical_regularity` → P1
**子类**：
- Stress 持续时间不规律（如 12/13/14/12/13/14/15/16h）→ 应统一时长或给递增依据
- Priority 分布跟 BUG 严重度不匹配（如 BUG `Sev=low` 但 High 用例 > 50%）→ 标"过度测试或 BUG 严重度被低估"

## 报告结构建议

字面自检结果作为评审报告"二、基于证据的判断"的一个独立子段：

```markdown
### 字面自检（Step 6.5 helper script 输出）

**P0 数据错误（X 项）**
- 行 77 mode 错位：...
- 行 222 vs12 错别字：...
- 中文叠字 7 处：行 70/71/76/77/81/82/83 ...
- segment webui 章节 80 条用例字字重复 webui 章节：...

**P1 结构性问题（Y 项）**
- 字段全空率：Result/Automated/Test Build/Note 各 100% → 用例可能从未执行
- ID 空率 96%（253/263）→ 违反 Option Definition
- Stress 时长不规律：12/13/14/12/13/14/15/16h
```

## 跳过 / 例外

如果脚本输出 `total_issues=0`，**不要**编造问题——直接在报告里写"字面自检通过，无机械错误"。
如果脚本本身报错（如文件路径不对），先用 `qa_deepagent_ls` 确认路径再重试，不要因为脚本失败就跳过 Step 6.5。
