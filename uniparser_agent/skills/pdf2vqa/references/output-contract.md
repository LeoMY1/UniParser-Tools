# Staged output contract

## Prepared run

`vqa-prepare` creates a collision-safe output directory containing:

- `prepare_meta.json`: run manifest and ordered request/response paths.
- `parse/pages_tree.json`: UniParser structure used by pdf2vqa.
- `llm_content_list.json`: sequential content IDs, text, tables, equations, and exported image paths.
- `vqa_images/`: images referenced by image content IDs.
- `agent_requests/chunk_NNNN.md`: exact system and user prompt for one inference chunk.
- `agent_responses/chunk_NNNN.txt`: expected raw response location; the agent creates this file.

## Response protocol

Return either one or more chapter blocks:

```xml
<chapter><title>7</title><vqa_pair><label>1</label><question_type>calculation</question_type><question>8,9</question><answer>$2^6$</answer><solution>10,11</solution></vqa_pair></chapter>
```

or, when the chunk contains no qualifying VQA content:

```xml
<empty></empty>
```

Rules enforced by validation:

- Do not use Markdown code fences or surrounding explanation.
- Each chapter has exactly one `title` and at least one `vqa_pair`.
- Each pair has exactly one `label`, `question_type`, `question`, `answer`, and `solution` tag; question, answer, and solution may be empty when source content is missing.
- `question_type` must be exactly one of `true_false`, `fill_in_the_blank`, `multiple_choice`, `calculation`, `proof`, or `other`.
- Chinese and English source headings map to the same canonical English value. Separated question and answer/solution rows must repeat the same value.
- `title`, `question`, and `solution` contain only comma-separated numeric IDs that exist in `llm_content_list.json`.
- `answer` contains extracted answer text, not a content ID.
- Image IDs use the same plain numeric representation as text IDs.

## Finalized run

`vqa-finalize` validates again, writes the complete concatenated response to `llm_raw_response.txt`, and produces:

- `response_validation.json`
- `extracted_vqa.jsonl`
- `merged_vqa_pairs.jsonl`
- `merged_vqa_pairs.md`
- `vqa_sharegpt.json`
- `run_meta.json`

If validation fails, final VQA files are not overwritten or regenerated. Repair the listed response file and run validation again.
