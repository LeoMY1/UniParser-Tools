# 化学分子库（`uniparser-agent`）

把化学专利或科技文献里的**化合物**整理成可查询的本地分子库，并可导出 CSV 做核对与分析。当前版本只建分子库，不抽取反应式。

## 能做什么

- 输入本地 **PDF / 图片**，或公开 **PDF URL**
- 自动对齐结构式、化合物代号、化学名与活性（如 IC50）
- 入库范围包括目标产物、Markush 通式、机理中间体与实施例原料；同一代号或同一无标签 SMILES 合并为一行
- （可选）用大模型为每个化合物写简要说明，并整理活性字段
- 结果写入本地 **SQLite**，也可导出 **CSV**
- 已有 UniParser 的 `pages_tree.json` 时，可跳过解析、直接入库

典型流程：

```text
PDF / pages_tree.json → 抽取并入库 → 查看统计 → 导出 CSV
```

## 安装

需要 Python 3.11+。

```bash
cd uniparser_agent
uv sync
```

## 配置

按你的用法配置环境变量即可。

| 变量 | 何时需要 | 说明 |
|------|----------|------|
| `UNIPARSER_API_KEY` | 从 PDF/图片/URL 解析时（`run`） | UniParser API Key |
| `OPENAI_API_KEY` | 需要大模型摘要时 | LLM API Key |
| `OPENAI_BASE_URL` | 需要大模型摘要时 | OpenAI 兼容接口地址（如 `.../v1`） |
| `OPENAI_MODEL` | 需要大模型摘要时 | 模型名 |
| `UNIPARSER_BASE_URL` | 可选 | 默认 `https://uniparser.dp.tech` |
| `UNIPARSER_AGENT_DB` | 可选 | 默认数据库 `~/.uniparser-agent/chemistry.db` |

```bash
export UNIPARSER_API_KEY="your-uniparser-key"
# 需要摘要时再配置：
export OPENAI_API_KEY="your-llm-key"
export OPENAI_BASE_URL="http://your-server/v1"
export OPENAI_MODEL="your-model-name"
```

不配 `OPENAI_*`，或命令加 `--skip-enrich`，仍可入库，只是没有大模型摘要。也可用 `--api-key` / `--base-url` / `--model` 在命令行临时覆盖。

## 快速开始

### 从 PDF 一键建库

```bash
uv run uniparser-agent run /path/to/patent.pdf --doc-id CN115974847A
```

终端会打印化合物数量、解析目录和数据库路径。

### 已有解析结果时直接入库

```bash
uv run uniparser-agent ingest /path/to/pages_tree.json --doc-id CN115974847A
```

### 先不调大模型（更快、省费用）

```bash
uv run uniparser-agent run /path/to/patent.pdf \
  --doc-id CN115974847A \
  --skip-enrich
```

### 查看并导出

`run` / `ingest` 若用了自定义 `--db`，`show` / `export` 必须带上**同一个** `--db`（或设置 `UNIPARSER_AGENT_DB`），否则会去默认库里找文档：

```bash
uv run uniparser-agent show CN115974847A --db /path/to/chemistry.db
uv run uniparser-agent export CN115974847A --db /path/to/chemistry.db
```

## 结果在哪里

| 输出 | 默认位置 | 如何改 |
|------|----------|--------|
| 分子库（SQLite） | `~/.uniparser-agent/chemistry.db` | `--db` 或 `UNIPARSER_AGENT_DB` |
| 解析结果（仅 `run`） | `~/Uni-Parser-Skill/<文件名>/` | `-o` / `--output-dir` |
| CSV（单文档） | `./exports/<DOC_ID>/` | `--out` |
| CSV（全库） | `./exports/library/` | `--out` |

`show` / `export` 默认也读 `~/.uniparser-agent/chemistry.db`。自定义库路径后请始终加相同的 `--db`。

解析目录中通常有 `pages_tree.json`（可再次用 `ingest` 入库）以及 Markdown 等文件。

导出目录中通常有：

- `<DOC_ID>_documents.csv` — 文档信息
- `<DOC_ID>_compounds.csv` — 化合物列表

全库导出对应为 `documents.csv`、`compounds.csv`。

## 如何读导出结果

`compounds.csv` 每一行是一个化合物：

| 列 | 含义 |
|----|------|
| `compound_label` | 代号，如 `I-1`、`(V)` |
| `name` | 化学名 |
| `smi` / `canonical_smiles` | SMILES 结构 |
| `validation_status` | `valid` / `invalid` / `markush` |
| `example_no` | 实施例编号（有则填） |
| `role` | 角色（如目标化合物、中间体；有大模型摘要时才有） |
| `semantic_summary` | 自然语言摘要（有大模型摘要时才有） |
| `activities_json` | 活性数据（JSON 文本）；没有则为 `[]` |

活性示例：

```json
[
  {
    "activity_type": "IC50",
    "activity_value": 0.31,
    "activity_unit": "uM",
    "assay": "NQO1",
    "evidence": "0.31 ± 0.03"
  }
]
```

同一化合物出现在不同文档中会各有一行。`show` 可快速查看某篇文档的化合物数、活性条数、摘要条数等。

## 命令说明

### `run` — 解析并建库

```bash
uv run uniparser-agent run INPUT [选项]
```

| 选项 | 说明 |
|------|------|
| `INPUT` | 本地 PDF/图片，或公开 PDF 链接 |
| `--doc-id` | 文档编号（建议用专利公开号）；默认取文件名 |
| `-o`, `--output-dir` | 解析结果**目录**（`pages_tree.json` 等）；默认 `~/Uni-Parser-Skill/<文件名>/`。与 `--db` 无关，不会改数据库位置 |
| `--db` | 分子库 SQLite **文件**路径；默认 `~/.uniparser-agent/chemistry.db`（或环境变量 `UNIPARSER_AGENT_DB`）。与 `-o` 无关：只设 `-o` 时，库仍写到上述默认路径，不会进 `-o` 目录 |
| `--overwrite` | 解析目录已存在时先清空再写 |
| `--skip-enrich` | 不调用大模型 |
| `--api-key` / `--base-url` / `--model` | 覆盖 LLM 环境变量 |
| `--json` | 以 JSON 打印摘要 |

### `ingest` — 从 `pages_tree.json` 建库

适合已解析过、不想重复解析的情况。

```bash
uv run uniparser-agent ingest /path/to/pages_tree.json --doc-id DOC_ID
```

常用选项与 `run` 相同（`--doc-id`、`--db`、`--skip-enrich`、LLM 参数等）。可用 `--source` 记录原始 PDF 路径。

### `show` — 查看入库统计

```bash
uv run uniparser-agent show DOC_ID
uv run uniparser-agent show DOC_ID --db /path/to/chemistry.db
```

| 选项 | 说明 |
|------|------|
| `DOC_ID` | 文档编号，须与入库时一致 |
| `--db` | 数据库文件路径；须与 `run` / `ingest` 时相同。默认 `~/.uniparser-agent/chemistry.db` |

找不到文档时会打印当前打开的数据库路径，并提示传入匹配的 `--db`。

### `export` — 导出 CSV

```bash
uv run uniparser-agent export DOC_ID --db /path/to/chemistry.db
uv run uniparser-agent export DOC_ID --db /path/to/chemistry.db --out ./my_exports/DOC_ID
uv run uniparser-agent export --all --db /path/to/chemistry.db --out ./exports/library
```

| 选项 | 说明 |
|------|------|
| `DOC_ID` / `--all` | 导出单文档或全库 |
| `--db` | 与入库时相同的数据库文件；默认同上 |
| `--out` | 导出目录；默认见「结果在哪里」 |

## 使用建议

- 用稳定的 `--doc-id`（如专利公开号），方便查询和再次入库覆盖。
- `run` / `ingest` 用了 `--db` 时，`show` / `export` 也要带同一 `--db`（或 `export UNIPARSER_AGENT_DB=...`）。
- 同一 `doc-id` 再次入库会覆盖该文档旧结果，不会重复堆积。
- 可先 `--skip-enrich` 核对结构与表格，确认后再去掉该选项补写摘要。
- 原文无活性表或表格识别不全时，活性字段可能为空，属正常情况。
- 首次使用建议指定新的 `--db` 路径，避免与旧版数据库混用。
- 当前版本不入库反应式。

## 相关文档

- 工具总览：[../README_cn.md](../README_cn.md)
