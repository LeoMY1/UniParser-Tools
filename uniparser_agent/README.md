# UniParser Agent

A single CLI around UniParser with three capabilities:

1. **Chemistry library** (`run` / `ingest` / `show` / `export`): extract molecules and reactions into local SQLite.
2. **Exam pdf2vqa** (`vqa`): extract multimodal question/answer pairs from exam PDFs — see [pdf2vqa/README.md](pdf2vqa/README.md).
3. **PDF translation** (`translate`): UniParser layout-block overlay translation — see [pdf2translate/README.md](pdf2translate/README.md).

[中文文档](README_cn.md)

## When to use

- You have PDFs or images of chemistry literature and want a **structured library** of compounds and reactions.
- You already parsed a document with UniParser and want to **ingest** the result into a database without parsing again.
- You need **counts and CSV exports** for downstream analysis or review.
- You need **VQA extraction** from exam papers (see pdf2vqa docs).
- You need **layout-preserving PDF translation** into Chinese (`zh-CN`; see pdf2translate docs).

## Install

```bash
cd uniparser_agent
uv sync
```

Requires Python 3.11+.

Set your UniParser API key before parsing (**never hardcode keys in source**):

```bash
export UNIPARSER_API_KEY="your-api-key"
```

Optional environment variables:

| Variable | Purpose | Default |
|----------|---------|---------|
| `UNIPARSER_API_KEY` | API key for `parse`, `run`, `vqa`, and `translate` parsing | *(required for parsing)* |
| `UNIPARSER_BASE_URL` | UniParser API base URL | `https://uniparser.dp.tech` |
| `UNIPARSER_AGENT_DB` | Default SQLite database path | `~/.uniparser-agent/chemistry.db` |
| `OPENAI_API_KEY` | LLM key for `vqa` / `translate` | *(required when using LLM)* |
| `OPENAI_BASE_URL` | OpenAI-compatible LLM `base_url` | *(required; no built-in default)* |
| `OPENAI_MODEL` | LLM model name | *(required; no built-in default)* |

For `vqa` / `translate`, you can also pass `--api-key` / `--base-url` / `--model` (CLI overrides env).

## Quick start

```bash
uv run uniparser-agent run /path/to/paper.pdf --doc-id paper1
uv run uniparser-agent show paper1
uv run uniparser-agent export paper1 --out ./exports/paper1
```

---

## Commands

### `run` — parse and build the library in one step

Most common command. Calls UniParser to parse the document, then extracts molecules and reactions into the database.

```bash
uv run uniparser-agent run INPUT [OPTIONS]
```

| Argument / option | Required | Description |
|-------------------|----------|-------------|
| `INPUT` | Yes | Local PDF/image path, or a public PDF URL |
| `--doc-id` | No | Document ID used in the database and export filenames. Defaults to the file name without extension (e.g. `paper1` for `paper1.pdf`) |
| `--profile` | No | What to extract when ingesting. See [Profiles](#profiles). Default: `scientific-paper` |
| `-o`, `--output-dir` | No | Where to save parse results (`pages_tree.json`, Markdown, etc.). Default: `~/Uni-Parser-Skill/<file-stem>/` |
| `--db` | No | SQLite database path. Default: `UNIPARSER_AGENT_DB` or `~/.uniparser-agent/chemistry.db` |
| `--overwrite` | No | Replace the parse output directory if it already exists |
| `--json` | No | Print a JSON summary instead of human-readable text |

**Examples:**

```bash
# Parse a local patent PDF
uv run uniparser-agent run ~/papers/patent1.pdf --doc-id patent1

# Parse a public PDF URL
uv run uniparser-agent run "https://example.com/paper.pdf" --doc-id paper1

# Only extract molecules (skip reactions)
uv run uniparser-agent run paper.pdf --doc-id paper1 --profile molecules_only

# Custom parse output and database paths
uv run uniparser-agent run paper.pdf --doc-id paper1 \
  -o ./parsed/paper1 \
  --db ./data/my-library.db
```

---

### `parse` — parse only (no database ingest)

Calls UniParser and saves parse artifacts. Does **not** write to the chemistry library. Use this when you want to inspect parse results first, or ingest later with different settings.

```bash
uv run uniparser-agent parse INPUT [OPTIONS]
```

| Argument / option | Required | Description |
|-------------------|----------|-------------|
| `INPUT` | Yes | Local PDF/image path, or a public PDF URL |
| `-o`, `--output-dir` | No | Output directory. Default: `~/Uni-Parser-Skill/<file-stem>/` |
| `--overwrite` | No | Replace the output directory if it already exists |
| `--json` | No | Print parse result paths as JSON |

**Output files** (under the output directory):

- `pages_tree.json` — structured layout and chemistry blocks (used by `ingest`)
- `*.md` — readable Markdown
- Other parse metadata

**Examples:**

```bash
uv run uniparser-agent parse paper.pdf

uv run uniparser-agent parse paper.pdf -o ./parsed/paper1

uv run uniparser-agent parse paper.pdf -o ./parsed/paper1 --overwrite
```

---

### `ingest` — ingest from an existing `pages_tree.json`

Reads a parse result and writes molecules/reactions into the database. Does **not** call the UniParser API.

```bash
uv run uniparser-agent ingest PAGES_TREE [OPTIONS]
```

| Argument / option | Required | Description |
|-------------------|----------|-------------|
| `PAGES_TREE` | Yes | Path to `pages_tree.json` |
| `--doc-id` | No | Document ID. Defaults to the parent folder name of `pages_tree.json` (e.g. `paper1` if the path is `./parsed/paper1/pages_tree.json`) |
| `--profile` | No | What to extract. Default: `scientific-paper` |
| `--db` | No | SQLite database path |
| `--source` | No | Original file path or URL to record in the database (for reference only) |
| `--json` | No | Print ingest statistics as JSON |

**Examples:**

```bash
# Ingest after a separate parse step
uv run uniparser-agent ingest ./parsed/paper1/pages_tree.json --doc-id paper1

# Re-ingest with a different profile (no API call)
uv run uniparser-agent ingest ~/Uni-Parser-Skill/patent1/pages_tree.json \
  --doc-id patent1 \
  --profile molecules_only

# Record the original PDF path
uv run uniparser-agent ingest ./parsed/paper1/pages_tree.json \
  --doc-id paper1 \
  --source ~/papers/paper1.pdf
```

---

### `show` — view extraction statistics

Prints counts for a document already in the database.

```bash
uv run uniparser-agent show DOC_ID [OPTIONS]
```

| Argument / option | Required | Description |
|-------------------|----------|-------------|
| `DOC_ID` | Yes | Document ID used during `run` or `ingest` |
| `--db` | No | SQLite database path |
| `--json` | No | Print statistics as JSON |

**Example output:**

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

| Field | Meaning |
|-------|---------|
| `extractions` | Total structure occurrences found in the document |
| `unique_compounds` | Distinct valid concrete molecules (deduplicated) |
| `markush` | Markush scaffold occurrences |
| `invalid` | Structures that failed validation |
| `reactions` | Reaction records found |

**Examples:**

```bash
uv run uniparser-agent show patent1

uv run uniparser-agent show paper1 --db ./data/my-library.db
```

---

### `vqa` — exam VQA extraction

Extract question / answer / solution pairs (with figures when present) from exam PDFs. Outputs include `merged_vqa_pairs.*`, `vqa_images/`, and `vqa_sharegpt.json`. Full details: [pdf2vqa/README.md](pdf2vqa/README.md).

```bash
# Single booklet
uv run uniparser-agent vqa /path/to/exam.pdf -o ./vqa_out --overwrite

# Question booklet + answer booklet (local PDFs; merged then parsed once)
uv run uniparser-agent vqa /path/to/questions.pdf \
  --answer-pdf /path/to/answers.pdf \
  -o ./vqa_out \
  --overwrite
```

| Argument / option | Required | Description |
|-------------------|----------|-------------|
| `INPUT` | Yes* | Question booklet (or single exam PDF). `*` omit only with `--pages-tree` |
| `--answer-pdf` | No | Answer booklet PDF (local only; cannot combine with `--pages-tree`) |
| `--pages-tree` | No | Skip UniParser and reuse an existing `pages_tree.json` |
| `-o`, `--output-dir` | No | Output directory (default `./vqa_out`) |
| `--overwrite` | No | Replace output directory if it exists |

---

### `translate` — in-place visual PDF translation

Uses UniParser layout blocks, covers original text, and redraws Chinese translations in the original bbox. Target language is fixed to `zh-CN`. See [pdf2translate/README.md](pdf2translate/README.md).

```bash
uv run uniparser-agent translate INPUT.pdf -o ./translate_out --overwrite
```

| Argument / option | Required | Description |
|-------------------|----------|-------------|
| `INPUT.pdf` | Yes | Local PDF path |
| `--source-lang` | No | Optional source-language hint |
| `--pages-tree` | No | Reuse an existing `pages_tree.json` and skip UniParser parse |
| `-o`, `--output-dir` | No | Output directory (default `./translate_out`) |
| `--font` | No | Optional TTF/OTF font file for translated text |
| `--glossary` | No | Manual glossary CSV (`source,target[,tgt_lng]`) |
| `--auto-glossary` / `--no-auto-glossary` | No | Auto-extract glossary (default: on) |
| `--overwrite` | No | Replace output directory if it exists |
| `--debug-layout` | No | Also write `layout_debug.pdf` |
| `--json` | No | Print machine-readable JSON summary |

**Examples:**

```bash
export UNIPARSER_API_KEY="your-api-key"
export OPENAI_API_KEY="your-llm-key"
export OPENAI_BASE_URL="https://api.openai.com/v1"
export OPENAI_MODEL="gpt-4o-mini"

uv run uniparser-agent translate ./paper.pdf -o ./translate_out --overwrite

uv run uniparser-agent translate ./paper.pdf \
  --pages-tree ./parse/pages_tree.json \
  -o ./translate_out \
  --glossary ./terms.csv \
  --debug-layout \
  --overwrite
```

---

### `export` — export to CSV

Export one document, or export the **full molecular library** (deduplicated across all documents).

```bash
uv run uniparser-agent export DOC_ID [OPTIONS]
uv run uniparser-agent export --all [OPTIONS]
```

| Argument / option | Required | Description |
|-------------------|----------|-------------|
| `DOC_ID` | One of `DOC_ID` or `--all` | Document ID |
| `--all` | One of `DOC_ID` or `--all` | Export the full library (all ingested documents) |
| `--out` | No | Export directory. Default: `./exports/<DOC_ID>/` for one doc, `./exports/library/` for `--all` |
| `--db` | No | SQLite database path |
| `--json` | No | Print export summary and file paths as JSON |

**Single-document export** (`export DOC_ID`):

| File | Contents |
|------|----------|
| `<DOC_ID>_extractions.csv` | Every structure occurrence in that document |
| `<DOC_ID>_compounds.csv` | Deduplicated molecules found in that document |
| `<DOC_ID>_reactions.csv` | Reactions in that document |

**Full library export** (`export --all`):

| File | Contents |
|------|----------|
| `documents.csv` | All ingested documents |
| `compounds.csv` | **Library-wide deduplicated molecules** (includes `doc_count`, `doc_ids`) |
| `markush_scaffolds.csv` | Library-wide Markush scaffolds (includes `doc_count`, `doc_ids`) |
| `extractions.csv` | All extraction records (includes `doc_id`) |
| `reactions.csv` | All reactions (includes `doc_id`) |

After batch parsing, use `--all` to get the complete library in one step.

**Examples:**

```bash
# Export one document
uv run uniparser-agent export paper1 --out ./exports/paper1

# Export the full library
uv run uniparser-agent export --all --out ./exports/library
```

---

## Profiles

The `--profile` option controls what is extracted during `ingest` and `run`:

| Profile | What you get |
|---------|----------------|
| `scientific-paper` (default) | Molecules, Markush scaffolds, and reactions |
| `molecules_only` | Molecules and Markush scaffolds |
| `reactions_only` | Reactions only |

Parsing always uses the same UniParser settings; the profile only affects ingest.

```bash
uv run uniparser-agent run patent.pdf --doc-id patent1 --profile molecules_only
```

---

## Common workflows

**Batch ingest and export the full library:**

```bash
uv run uniparser-agent run paper1.pdf --doc-id paper1
uv run uniparser-agent run paper2.pdf --doc-id paper2
uv run uniparser-agent export --all --out ./exports/library
```

**Parse first, ingest later:**

```bash
uv run uniparser-agent parse paper.pdf -o ./parsed/paper1
uv run uniparser-agent ingest ./parsed/paper1/pages_tree.json --doc-id paper1
```

**Re-ingest with different settings (no API call):**

```bash
uv run uniparser-agent ingest ./parsed/paper1/pages_tree.json --doc-id paper1 --profile reactions_only
```
