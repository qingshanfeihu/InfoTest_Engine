"""``main.common`` — 通用工具与外部依赖封装。

此子包为 canonical 命名空间，下含:

* :mod:`main.common.paths`          — 路径常量 + 源文档权威度
* :mod:`main.common.env`            — ``environment`` 文件加载
* :mod:`main.common.qwen`           — LangChain ``ChatTongyi`` 封装
* :mod:`main.common.vector_store`   — Qdrant 向量库封装
* :mod:`main.common.progress`       — 终端进度条
* :mod:`main.common.utils`          — JSON I/O、哈希、原子写入
* :mod:`main.common.cli_commands`   — CLI 命令字符串工具（L1/L3/L4/L5 复用）
* :mod:`main.common.release_markers` — trunk 文本的 deferred/template_placeholder 识别（L3）

旧的扁平 import 路径（``from main.knowledge_paths import ...`` 等）仍保留为
兼容 shim，至少向后 1–2 个版本可用。新代码优先使用本子包的路径。
"""
