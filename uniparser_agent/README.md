# UniParser Agent

UniParser Agent 是基于 UniParser 的文档处理包，提供统一的命令行入口：

- `parse`：将 PDF、图片或公开 PDF URL 解析为结构化文档。
- `vqa`：从习题、试卷、题册或答案册中提取题目、答案、解析和相关图片，并生成结构化 VQA 数据。
- `translate`：复用 UniParser 版面信息，将 PDF 原位翻译并输出可视化结果。
- `ingest` / `run`：从 `pages_tree.json` 或原始文档构建 Chemistry 分子库。
- `show` / `export`：检查和导出 Chemistry 文档及全库数据。

本包包含文档解析、LLM 调用、PDF2VQA、PDF2Translate 和 Chemistry 流程所需的公共模块。
所有生成型命令都使用独立输出目录；目标目录已存在时会创建带数字后缀的同级目录，
不会删除已有结果。

安装方式、配置说明、命令参数、处理流程和输出格式，请参阅对应文档：

- [PDF2VQA 文档](pdf2vqa/README.md)
- [PDF2Translate 文档](pdf2translate/README.md)
- [Chemistry 文档](chemistry/README.md)
