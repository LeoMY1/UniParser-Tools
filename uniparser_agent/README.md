# UniParser Agent

Command-line tools for UniParser document parsing and exam VQA extraction.

- `parse`: parse a local PDF/image or public PDF URL into `pages_tree.json` and Markdown.
- `vqa`: extract question, answer, and solution pairs from a document or an existing
  `pages_tree.json`; figures are exported for multimodal datasets.

[中文文档](README_cn.md) · [Full pdf2vqa documentation](pdf2vqa/README.md)

## Install

```bash
cd uniparser_agent
uv sync
```

Python 3.11 or newer is required.

## Configuration

```bash
export UNIPARSER_API_KEY="your-uniparser-key"
export OPENAI_API_KEY="your-llm-key"
export OPENAI_BASE_URL="https://example.com/v1"
export OPENAI_MODEL="your-model"
```

`UNIPARSER_API_KEY` is not needed when `vqa` receives an existing
`pages_tree.json`. The LLM options can also be supplied with `--api-key`,
`--base-url`, and `--model`.

## Parse

```bash
uv run uniparser-agent parse /path/to/document.pdf
uv run uniparser-agent parse /path/to/document.pdf -o ./parsed --overwrite
```

## Extract VQA pairs

Single booklet:

```bash
uv run uniparser-agent vqa /path/to/exam.pdf -o ./vqa_out --overwrite
```

Question and answer booklets:

```bash
uv run uniparser-agent vqa /path/to/questions.pdf \
  --answer-pdf /path/to/answers.pdf \
  -o ./vqa_out \
  --overwrite
```

Reuse a prior parse:

```bash
uv run uniparser-agent vqa \
  --pages-tree /path/to/pages_tree.json \
  -o ./vqa_out \
  --overwrite
```

The VQA output includes:

- `merged_vqa_pairs.jsonl`
- `merged_vqa_pairs.md`
- `vqa_images/`
- `vqa_sharegpt.json`
- `run_meta.json`

See [pdf2vqa/README.md](pdf2vqa/README.md) for the full CLI reference,
pipeline stages, schemas, and output layout.

## Test

```bash
uv run pytest \
  tests/test_vqa_adapter.py \
  tests/test_vqa_parser.py \
  tests/test_vqa_images.py \
  tests/test_pdf_merger.py \
  tests/test_llm_config.py
```
