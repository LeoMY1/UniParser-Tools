# UniParser Agent

用于 UniParser 文档解析和试卷 VQA 提取的命令行工具。

- `parse`：将本地 PDF、图片或公开 PDF URL 解析为 `pages_tree.json` 和 Markdown。
- `vqa`：从原始文档或已有 `pages_tree.json` 提取题目、答案和解析，并导出图片用于多模态数据集。

[English](README.md) · [pdf2vqa 完整文档](pdf2vqa/README.md)

## 安装

```bash
cd uniparser_agent
uv sync
```

需要 Python 3.11 或更高版本。

## 配置

```bash
export UNIPARSER_API_KEY="your-uniparser-key"
export OPENAI_API_KEY="your-llm-key"
export OPENAI_BASE_URL="https://example.com/v1"
export OPENAI_MODEL="your-model"
```

使用已有 `pages_tree.json` 时无需 `UNIPARSER_API_KEY`。LLM 配置也可以通过
`--api-key`、`--base-url` 和 `--model` 传入。

## 解析文档

```bash
uv run uniparser-agent parse /path/to/document.pdf
uv run uniparser-agent parse /path/to/document.pdf -o ./parsed --overwrite
```

## 提取 VQA

单份题册：

```bash
uv run uniparser-agent vqa /path/to/exam.pdf -o ./vqa_out --overwrite
```

题册与答案册：

```bash
uv run uniparser-agent vqa /path/to/questions.pdf \
  --answer-pdf /path/to/answers.pdf \
  -o ./vqa_out \
  --overwrite
```

复用已有解析结果：

```bash
uv run uniparser-agent vqa \
  --pages-tree /path/to/pages_tree.json \
  -o ./vqa_out \
  --overwrite
```

主要输出：

- `merged_vqa_pairs.jsonl`
- `merged_vqa_pairs.md`
- `vqa_images/`
- `vqa_sharegpt.json`
- `run_meta.json`

完整参数、流程和数据结构见 [pdf2vqa/README.md](pdf2vqa/README.md)。

## 测试

```bash
uv run pytest \
  tests/test_vqa_adapter.py \
  tests/test_vqa_parser.py \
  tests/test_vqa_images.py \
  tests/test_pdf_merger.py \
  tests/test_llm_config.py
```
