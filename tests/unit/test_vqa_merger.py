import json
from pathlib import Path

from uniparser_agent.pdf2vqa.vqa_merger import jsonl_to_md


def test_jsonl_to_md_places_answer_in_its_own_markdown_block(tmp_path: Path) -> None:
    jsonl_path = tmp_path / "merged.jsonl"
    md_path = tmp_path / "merged.md"
    data = {
        "label": 1,
        "question": "问题",
        "answer": "结果：\n\n$$\nx = 1\n$$",
        "solution": "",
    }
    jsonl_path.write_text(json.dumps(data, ensure_ascii=False) + "\n", encoding="utf-8")

    jsonl_to_md(jsonl_path, md_path)

    assert md_path.read_text(encoding="utf-8") == (
        "### Question 1\n\n问题\n\n**Answer:**\n\n结果：\n\n$$\nx = 1\n$$\n\n---\n\n"
    )
