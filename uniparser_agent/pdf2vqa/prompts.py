from __future__ import annotations


def build_vqa_extract_prompt() -> str:
    return """
        You are an expert in answer college-level questions. You are given a json file. Your task is to segment the content, insert image tags, and extract source-grounded question-answer pairs:
1. Every json item has an "id" field. Your main task is to output this field.
2. You need to segment the content into multiple `<vqa_pair>`…`</vqa_pair>` blocks, each containing a question and its corresponding answer with solution.
3. If the problem or answer/solution is not complete, omit them. An answer/solution should be considered complete as long as either the answer or solution exists.
4. You need to put the images id into proper positions. You could look at the caption or context to decide where to put the image tags.
5. You will also need to extract the chapter title and each problem's label/number from the text.
6. Output only comma-separated source ids for **chapter titles, questions and solutions**. DO NOT OUTPUT THEIR ORIGINAL TEXT.
7. For every non-empty answer, output both the short answer copied from the source and the minimum source ids containing that answer in `<answer_source_ids>`.
8. Never summarize, infer, normalize, translate, or rewrite an answer. Preserve its exact source characters and LaTeX. The code will use the source ids to restore formatting if your copied answer differs.

Strict extraction rules:
** About questions and answers/solutions **
- Preserve each problem’s original label/number, such as "例1", "Example 3", "习题1", "11". Do not include the period after the number. Use Arabic numerals only. For example, if the label is "例一", convert it to "例1". If the label is "IV", convert it to "4".
- If the full label is "三、16", keep only "16". If the full label is "5.4", keep only "4".
- If there are multiple sub-questions (such as "(1)", "(a)") under one main question, always put them together in the same `<vqa_pair>`…`</vqa_pair>` block.
- The `<answer>` must be a short answer present in the items named by `<answer_source_ids>`. The source may be an explicit answer block or a solution block.
- Whenever `<answer>` is non-empty, `<answer_source_ids>` must also be non-empty. If no source span directly supports a short answer, leave both tags empty instead of inferring an answer.
- If a question and its answer/solution are contiguous, wrap them together as a single `<vqa_pair>`…`</vqa_pair>` block, e.g.:
  `<vqa_pair><label>1</label><question>…</question><answer>…</answer><answer_source_ids>…</answer_source_ids><solution>…</solution></vqa_pair>`
- If a question and its answer/solution are NOT contiguous (e.g. only question; only answer and/or solution; all questions at the front and all answers/solutions at the back), wrap each question or answer/solution in a `<vqa_pair>`…`</vqa_pair>` block with the missing part left empty. For example, if only questions appear:
  `<vqa_pair><label>1</label><question>…</question><answer></answer><answer_source_ids></answer_source_ids><solution></solution></vqa_pair>`
- In total, there are 7 possibilities: only question, only answer, only solution, question with answer, question with solution, answer with solution, full question and answer and solution.
- If multiple vqa pairs appear, wrap each vqa pair in its own `<vqa_pair>`…`</vqa_pair>` block.
- If you do not see the full solution, only extract the short answer and leave the solution empty. YOU MUST KEEP SHORT ANSWERS !!!
** About chapter/section titles **
- Always enclose vqa pairs in a `<chapter>`…`</chapter>` block, where <title>MAIN_TITLE_ID</title> is the id of the chapter title or section title.
- Normally, chapter/section titles appear before the questions/answers in an independent json item.
- There could be multiple `<chapter>`…`</chapter>` blocks if multiple chapters/sections exist.
- **Any title followed by a question/answer whose label/number is not 1, or title with a score such as "一、选择题（每题1分，共10分）", should NOT be extracted.**
- Do not use nested titles.
- Leave the title blank if there is no chapter title.
** About figures/diagrams **
- Whenever the question or answer/solution refers to a figure or diagram, record its "id" in question/answer/solution just like other text content.
- You MUST include all images referenced in the question/answer/solution.


If no qualifying content is found, output:
<empty></empty>

Output format (all tags run together, no extra whitespace or newlines except between entries):
<chapter><title>MAIN_TITLE_ID</title>
<vqa_pair><label>LABEL(EXTRACTED FROM TEXT)</label><question>QUESTION_IDS</question>
<answer>EXACT_SHORT_ANSWER</answer><answer_source_ids>ANSWER_SOURCE_IDS</answer_source_ids><solution>SOLUTION_IDS</solution></vqa_pair>
<vqa_pair><label>LABEL(EXTRACTED FROM TEXT)</label><question>QUESTION_IDS</question>
<answer>EXACT_SHORT_ANSWER</answer><answer_source_ids>ANSWER_SOURCE_IDS</answer_source_ids><solution></solution></vqa_pair>
</chapter>
<chapter><title>MAIN_TITLE_ID</title>
<vqa_pair><label>LABEL(EXTRACTED FROM TEXT)</label><question>QUESTION_IDS</question>
<answer>EXACT_SHORT_ANSWER</answer><answer_source_ids>ANSWER_SOURCE_IDS</answer_source_ids><solution>SOLUTION_IDS</solution></vqa_pair>
</chapter>


Example:
<chapter><title>7</title>
<vqa_pair><label>1</label><question>2,3</question>
<answer>Yes</answer><answer_source_ids>5</answer_source_ids><solution>5,6,7</solution></vqa_pair>
<vqa_pair><label>2</label><question>8,9,10</question>
<answer>3.14</answer><answer_source_ids>11</answer_source_ids><solution></solution></vqa_pair>
</chapter>
<chapter><title>12</title>
<vqa_pair><label>1</label><question></question>
<answer>2^6</answer><answer_source_ids>16</answer_source_ids><solution>16</solution></vqa_pair>
</chapter>

Please now process the provided json and output your result.
""".strip()
