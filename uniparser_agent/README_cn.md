# UniParser Agent

统一 CLI 工具：基于 UniParser 做文档解析，并提供两类功能——

1. **化学建库**（`run` / `ingest` / `show` / `export`）：从科技文献抽取分子与反应，写入本地 SQLite。
2. **习题 pdf2qa**（`vqa`）：从习题/试卷 PDF 抽取问答对，详见 [pdf2qa/README.md](pdf2qa/README.md)。

[English README](README.md)

## 什么时候用

- 手上有化学文献 PDF/图片，想整理成**可查询的分子与反应库**。
- 文档已经用 UniParser 解析过，想**直接入库**，不必再调解析接口。
- 需要查看**抽取统计**，或导出 **CSV** 做后续分析、人工核对。
- 需要从习题卷抽取 **题干 / 答案 / 解析**（见 pdf2qa 说明）。

## 安装

```bash
cd uniparser_agent
uv sync
```

需要 Python 3.11+。

解析前请设置 UniParser API Key：

```bash
export UNIPARSER_API_KEY="your-api-key"
```

可选环境变量：

| 变量 | 作用 | 默认值 |
|------|------|--------|
| `UNIPARSER_API_KEY` | `parse`、`run` 调用解析接口时使用 | 解析时必填 |
| `UNIPARSER_BASE_URL` | UniParser API 地址 | `https://uniparser.dp.tech` |
| `UNIPARSER_AGENT_DB` | 默认 SQLite 数据库路径 | `~/.uniparser-agent/chemistry.db` |

## 快速开始

```bash
uv run uniparser-agent run /path/to/paper.pdf --doc-id paper1
uv run uniparser-agent show paper1
uv run uniparser-agent export paper1 --out ./exports/paper1
```

---

## 命令说明

### `run` — 一步完成解析并建库

最常用的命令。调用 UniParser 解析文档，再将分子与反应写入数据库。

```bash
uv run uniparser-agent run INPUT [选项]
```

| 参数 / 选项 | 必填 | 说明 |
|-------------|------|------|
| `INPUT` | 是 | 本地 PDF/图片路径，或公开的 PDF 链接 |
| `--doc-id` | 否 | 文档 ID，用于数据库和导出文件名。默认取文件名（不含扩展名），如 `paper1.pdf` → `paper1` |
| `--profile` | 否 | 入库时抽取哪些内容，见 [入库配置](#入库配置profile)。默认 `scientific-paper` |
| `-o`, `--output-dir` | 否 | 解析结果保存目录（含 `pages_tree.json`、Markdown 等）。默认 `~/Uni-Parser-Skill/<文件名>/` |
| `--db` | 否 | SQLite 数据库路径。默认读 `UNIPARSER_AGENT_DB`，否则 `~/.uniparser-agent/chemistry.db` |
| `--overwrite` | 否 | 若解析输出目录已存在，先删除再写入 |
| `--json` | 否 | 以 JSON 格式输出摘要，便于脚本调用 |

**示例：**

```bash
# 解析本地专利 PDF
uv run uniparser-agent run ~/papers/patent1.pdf --doc-id patent1

# 解析公开 PDF 链接
uv run uniparser-agent run "https://example.com/paper.pdf" --doc-id paper1

# 只抽取分子，不抽取反应
uv run uniparser-agent run paper.pdf --doc-id paper1 --profile molecules_only

# 指定解析输出目录和数据库路径
uv run uniparser-agent run paper.pdf --doc-id paper1 \
  -o ./parsed/paper1 \
  --db ./data/my-library.db
```

---

### `parse` — 仅解析，不入库

调用 UniParser 并保存解析结果，**不**写入化学文档库。适合先检查解析效果，或稍后用不同配置再入库。

```bash
uv run uniparser-agent parse INPUT [选项]
```

| 参数 / 选项 | 必填 | 说明 |
|-------------|------|------|
| `INPUT` | 是 | 本地 PDF/图片路径，或公开的 PDF 链接 |
| `-o`, `--output-dir` | 否 | 输出目录。默认 `~/Uni-Parser-Skill/<文件名>/` |
| `--overwrite` | 否 | 若输出目录已存在，先删除再写入 |
| `--json` | 否 | 以 JSON 输出解析结果路径 |

**输出文件**（在输出目录下）：

- `pages_tree.json` — 结构化版面与化学块（供 `ingest` 使用）
- `*.md` — 可读的 Markdown 正文
- 其他解析元数据

**示例：**

```bash
uv run uniparser-agent parse paper.pdf

uv run uniparser-agent parse paper.pdf -o ./parsed/paper1

uv run uniparser-agent parse paper.pdf -o ./parsed/paper1 --overwrite
```

---

### `ingest` — 从已有 `pages_tree.json` 入库

读取解析结果，将分子/反应写入数据库。**不**调用 UniParser 解析接口。

```bash
uv run uniparser-agent ingest PAGES_TREE [选项]
```

| 参数 / 选项 | 必填 | 说明 |
|-------------|------|------|
| `PAGES_TREE` | 是 | `pages_tree.json` 的路径 |
| `--doc-id` | 否 | 文档 ID。默认取 `pages_tree.json` 的上一级目录名（如路径为 `./parsed/paper1/pages_tree.json` 则默认为 `paper1`） |
| `--profile` | 否 | 抽取哪些内容。默认 `scientific-paper` |
| `--db` | 否 | SQLite 数据库路径 |
| `--source` | 否 | 记录原始文件路径或 URL（仅作备注，不影响抽取） |
| `--json` | 否 | 以 JSON 输出入库统计 |

**示例：**

```bash
# 先 parse 再 ingest
uv run uniparser-agent ingest ./parsed/paper1/pages_tree.json --doc-id paper1

# 换 profile 重新入库（不再调 API）
uv run uniparser-agent ingest ~/Uni-Parser-Skill/patent1/pages_tree.json \
  --doc-id patent1 \
  --profile molecules_only

# 同时记录原始 PDF 路径
uv run uniparser-agent ingest ./parsed/paper1/pages_tree.json \
  --doc-id paper1 \
  --source ~/papers/paper1.pdf
```

---

### `show` — 查看抽取统计

查看已入库文档的抽取数量。

```bash
uv run uniparser-agent show DOC_ID [选项]
```

| 参数 / 选项 | 必填 | 说明 |
|-------------|------|------|
| `DOC_ID` | 是 | `run` 或 `ingest` 时使用的文档 ID |
| `--db` | 否 | SQLite 数据库路径 |
| `--json` | 否 | 以 JSON 输出统计 |

**输出示例：**

```
doc_id: patent1
source: /path/to/patent1.pdf
parsed_at: 2026-07-11T12:00:00+00:00
extractions: 33
unique_compounds: 12
invalid: 0
markush: 13
reactions: 0
```

| 字段 | 含义 |
|------|------|
| `extractions` | 文档中识别到的结构总次数（含重复出现） |
| `unique_compounds` | 不重复的有效具体分子数 |
| `markush` | Markush 通式出现次数 |
| `invalid` | 校验失败的结构数 |
| `reactions` | 识别到的反应数 |

**示例：**

```bash
uv run uniparser-agent show patent1

uv run uniparser-agent show paper1 --db ./data/my-library.db
```

---

### `export` — 导出 CSV

导出单篇文档，或导出**完整分子库**（跨所有文档去重汇总）。

```bash
uv run uniparser-agent export DOC_ID [选项]
uv run uniparser-agent export --all [选项]
```

| 参数 / 选项 | 必填 | 说明 |
|-------------|------|------|
| `DOC_ID` | 与 `--all` 二选一 | 文档 ID |
| `--all` | 与 `DOC_ID` 二选一 | 导出完整分子库（所有已入库文档） |
| `--out` | 否 | 导出目录。单文档默认 `./exports/<DOC_ID>/`；全库默认 `./exports/library/` |
| `--db` | 否 | SQLite 数据库路径 |
| `--json` | 否 | 以 JSON 输出导出摘要与文件路径 |

**单文档导出**（`export DOC_ID`）：

| 文件 | 内容 |
|------|------|
| `<DOC_ID>_extractions.csv` | 该文档每次结构出现的明细 |
| `<DOC_ID>_compounds.csv` | 该文档涉及的去重分子 |
| `<DOC_ID>_reactions.csv` | 该文档的反应记录 |

**完整分子库导出**（`export --all`）：

| 文件 | 内容 |
|------|------|
| `documents.csv` | 所有已入库文档列表 |
| `compounds.csv` | **全库去重分子**（含 `doc_count`、`doc_ids`，表示出现在哪些文档） |
| `markush_scaffolds.csv` | 全库 Markush 通式（含 `doc_count`、`doc_ids`） |
| `extractions.csv` | 所有文档的抽取明细（含 `doc_id`） |
| `reactions.csv` | 所有文档的反应记录（含 `doc_id`） |

批量解析后，用 `--all` 即可得到完整分子库 CSV。

**示例：**

```bash
# 导出单篇文档
uv run uniparser-agent export paper1 --out ./exports/paper1

# 一键导出完整分子库
uv run uniparser-agent export --all --out ./exports/library
```

---

## 入库配置（Profile）

`--profile` 控制 `ingest` 和 `run` 时抽取哪些内容：

| Profile | 抽取内容 |
|---------|----------|
| `scientific-paper`（默认） | 分子、Markush 通式、反应 |
| `molecules_only` | 分子与 Markush 通式 |
| `reactions_only` | 仅反应 |

解析阶段参数固定；Profile 只影响入库内容。

```bash
uv run uniparser-agent run patent.pdf --doc-id patent1 --profile molecules_only
```

---

## 常见用法

**批量建库并导出完整分子库：**

```bash
uv run uniparser-agent run paper1.pdf --doc-id paper1
uv run uniparser-agent run paper2.pdf --doc-id paper2
uv run uniparser-agent export --all --out ./exports/library
```

**先解析、后入库：**

```bash
uv run uniparser-agent parse paper.pdf -o ./parsed/paper1
uv run uniparser-agent ingest ./parsed/paper1/pages_tree.json --doc-id paper1
```

**换配置重新入库（不再调 API）：**

```bash
uv run uniparser-agent ingest ./parsed/paper1/pages_tree.json --doc-id paper1 --profile reactions_only
```
