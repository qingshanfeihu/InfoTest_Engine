---
name: fill-g-column
description: 填充G列+生成xlsx。调用 qa_fill_g_column 一键完成。TRIGGER: fill-g-column, 填G列, 生成xlsx
allowed-tools: qa_fill_g_column qa_assemble_xlsx
---

调用 `qa_fill_g_column`，**指定对应人名的 JSON**：

```
qa_fill_g_column(decomposed_json_path="workspace/inputs/yzg/<name>_decomposed.json")
```

如 `yzg_decomposed.json`、`dongkl_decomposed.json`。

如果还没分解，先调 `qa_decompose_test_cases` 再调 `qa_fill_g_column`。
