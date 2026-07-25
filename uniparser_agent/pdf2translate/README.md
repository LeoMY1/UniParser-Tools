# pdf2translate

UniParser-based PDF in-place visual translation (MVP).

中文说明见 [README_cn.md](README_cn.md)。

## What it does

1. Parse PDF with UniParser (or reuse `pages_tree.json`)
2. Select text blocks with bbox (`paragraph` / `title` / ...)
3. Build glossary (auto by default) + cross-block context
4. Translate via OpenAI-compatible LLM (non-empty validation + per-unit retry)
5. Cover original text and redraw translation inside the original bbox with PyMuPDF

Target language is fixed to **zh-CN**.

## Requirements

```bash
export UNIPARSER_API_KEY="your-uniparser-key"   # needed unless --pages-tree
export PDF_TRANSLATE_API_KEY="your-llm-key"     # or VQA_LLM_API_KEY / ARK_API_KEY
```

Optional:


| Variable                 | Purpose                 | Default                                        |
| ------------------------ | ----------------------- | ---------------------------------------------- |
| `UNIPARSER_API_KEY`      | UniParser parse API key | required for live parse                        |
| `UNIPARSER_BASE_URL`     | UniParser endpoint      | `https://uniparser.dp.tech`                    |
| `PDF_TRANSLATE_API_KEY`  | LLM API key             | falls back to `VQA_LLM_API_KEY` / `ARK_API_KEY` |
| `PDF_TRANSLATE_BASE_URL` | LLM base URL            | Ark default                                    |
| `PDF_TRANSLATE_MODEL`    | LLM model               | Ark default                                    |
| `PDF_TRANSLATE_BATCH_SIZE` | Units per LLM request | `12`                                           |
| `PDF_TRANSLATE_MAX_WORKERS` | Parallel LLM batches | `4`                                            |


Do **not** hardcode API keys in source files.

## CLI

```bash
# Parse + translate to zh-CN
uv run uniparser-agent translate ./paper.pdf -o ./translate_out --overwrite

# Reuse existing pages_tree
uv run uniparser-agent translate ./paper.pdf \
  --pages-tree ./parse/pages_tree.json \
  -o ./translate_out \
  --overwrite \
  --debug-layout

# Manual glossary (CSV: source,target[,tgt_lng]) + optional disable auto glossary
uv run uniparser-agent translate ./paper.pdf -o ./out --glossary ./terms.csv
uv run uniparser-agent translate ./paper.pdf -o ./out --no-auto-glossary
```

## Outputs


| File                    | Meaning                                      |
| ----------------------- | -------------------------------------------- |
| `translated.pdf`        | Overlay-translated PDF                       |
| `parse/pages_tree.json` | UniParser layout tree                        |
| `translate_units.jsonl` | Per-block source/translation/status          |
| `run_meta.json`         | Languages, model, counts, timings            |
| `llm_raw/`              | Raw LLM responses + per-call meta            |
| `glossary_auto.json`    | Auto-extracted glossary (when enabled)       |
| `glossary_auto.csv`     | Same glossary in CSV form                    |
| `layout_debug.pdf`      | Optional bbox debug overlay                  |


## Quality guards

- Rejects empty `translated_text`; accepts aliases `translation` / `text`
- Incomplete batches trigger per-unit retries (up to 2)
- Failed units keep original text (no blank overlay)
- Glossary hits are injected only for matching units
- Each unit may include `context_title` / `context_prev` (read-only; not translated)

## Typography

Font size is **fixed by UniParser block type** (not fitted per bbox):

| Type | Size (pt) |
|------|-----------|
| `documenttitle` | 16 |
| `title` | 12 |
| `paragraph` / `abstract` | 10 |
| `reference` / captions | 9 |

If text does not fit the original box at that size, the draw rect grows downward; the type size is not reduced.

## Inline math

UniParser emits inline formulas as LaTeX like ``$ 55.00\% $``. Translation keeps that form; at **render** time they are converted to Unicode display text (e.g. ``55.00%``, ``β₁``, ``P₁, …, Pₖ``).

## MVP limits

- Block-level cover + redraw (not BabelDOC character-level content rewrite)
- Skips equations, tables, figures, headers/footers by default
- Requires local PDF input (URL/image-only not supported yet)
- Long translations may overflow the grown box (status `overflow`) but keep the type font size
