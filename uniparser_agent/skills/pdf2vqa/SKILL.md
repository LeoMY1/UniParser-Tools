---
name: pdf2vqa
description: Convert exercise, exam, workbook, question-bank, or question-and-answer PDFs into structured VQA datasets with questions, short answers, worked solutions, LaTeX formulas, and referenced images. Use when Codex should run an installed uniparser-agent CLI with the current active agent as the inference model instead of calling the configured external Qwen/OpenAI-compatible LLM, including single PDFs, separate question/answer PDFs, and existing pages_tree.json inputs.
---

# PDF to VQA

Use the staged pdf2vqa workflow. Let the installed `uniparser-agent` command handle parsing, chunking, validation, merging, image paths, and exports; use the current active agent only for the inference stage.

## Prerequisite

Require the `uniparser-agent` project to be installed and the `uniparser-agent` command to be available on `PATH`. Verify this with `uniparser-agent --help` before starting. If the command is unavailable, stop and ask the user to install `uniparser-agent`; do not fall back to repository-relative Python imports.

## Workflow

1. Resolve the input mode:
   - One document: pass the PDF, image, or public PDF URL as `INPUT`.
   - Separate booklets: pass the question PDF as `INPUT` and the answer PDF with `--answer-pdf`.
   - Existing parse: omit `INPUT` and pass `--pages-tree`.
2. Choose an explicit output directory. For a batch, create one test root and use one child directory per source PDF name. State the planned directory before a long run; if the user requested confirmation first, wait for it.
3. Run `uniparser-agent vqa-prepare` with the selected input arguments, output directory, and `--json`.
4. Read `prepare_meta.json`. Process every entry in `requests` by ascending `index`:
   - Read the complete `request_path` file.
   - Follow its system and user prompts exactly.
   - Perform inference directly as the current agent. Do not call an external LLM and do not launch nested `codex exec` processes.
   - Write only the raw XML-like response to the corresponding `response_path`. Do not add commentary or Markdown fences.
5. Run `uniparser-agent vqa-validate RUN_DIR --json`.
   - If validation fails, inspect the reported chunk and repair only its response file.
   - Repeat until validation succeeds. Read [references/output-contract.md](references/output-contract.md) when diagnosing validation failures.
6. Run `uniparser-agent vqa-finalize RUN_DIR --json`.
7. Inspect `merged_vqa_pairs.md`, `merged_vqa_pairs.jsonl`, and referenced images. Report the output directory, pair count, missing question/answer/solution counts, and any visible extraction uncertainty.

## Guardrails

- Preserve the formal extraction prompt embedded in each request file; do not recreate or summarize it.
- Preserve the canonical English `question_type` value required by the prompt in every VQA pair.
- Keep question and solution fields as source content IDs. Only the answer field may contain extracted text.
- Preserve image IDs as plain numeric IDs in their correct question or solution position.
- Never fabricate a missing answer or solution.
- Do not manually perform final Markdown joining, image embedding, VQA merging, or ShareGPT conversion.
- Keep `llm_raw_response.txt`; it is the complete inference audit record.
- If UniParser, SSH, or network access fails, stop the run and preserve the partial output instead of inventing results.

## Commands

Single PDF:

```bash
uniparser-agent vqa-prepare INPUT -o OUTPUT_DIR --json
```

Separate question and answer PDFs:

```bash
uniparser-agent vqa-prepare QUESTIONS.pdf -o OUTPUT_DIR --answer-pdf ANSWERS.pdf --json
```

Existing pages tree:

```bash
uniparser-agent vqa-prepare --pages-tree pages_tree.json -o OUTPUT_DIR --json
```

Validate and finalize:

```bash
uniparser-agent vqa-validate OUTPUT_DIR --json
uniparser-agent vqa-finalize OUTPUT_DIR --json
```
