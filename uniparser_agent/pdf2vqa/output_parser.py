"""Parse LLM id-based VQA responses back into text VQA items."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from bs4 import BeautifulSoup


def _html_table_to_markdown(table_html: str) -> str:
    """Convert a simple HTML table so Markdown math remains renderable in cells."""
    if "<table" not in table_html.lower():
        return table_html

    soup = BeautifulSoup(table_html, "html.parser")
    table = soup.find("table")
    if table is None:
        return table_html

    rows: list[list[str]] = []
    for row in table.find_all("tr"):
        cells = row.find_all(["th", "td"], recursive=False)
        if not cells:
            continue
        values: list[str] = []
        for cell in cells:
            value = re.sub(r"\s+", " ", cell.get_text(" ", strip=True)).replace("|", r"\|")
            values.append(value)
            colspan = cell.get("colspan")
            if isinstance(colspan, str) and colspan.isdigit():
                values.extend([""] * (max(int(colspan), 1) - 1))
        rows.append(values)

    if not rows:
        return table_html

    column_count = max(len(row) for row in rows)
    normalized_rows = [row + [""] * (column_count - len(row)) for row in rows]

    def format_row(row: list[str]) -> str:
        return "| " + " | ".join(row) + " |"

    lines = [format_row(normalized_rows[0]), format_row(["---"] * column_count)]
    lines.extend(format_row(row) for row in normalized_rows[1:])
    return "\n".join(lines)


def _join_content_blocks(blocks: list[tuple[str, str]]) -> str:
    """Join soft text fragments without collapsing Markdown block boundaries."""
    if not blocks:
        return ""

    parts = [blocks[0][1]]
    previous_type = blocks[0][0]
    for current_type, current_text in blocks[1:]:
        separator = "\n" if previous_type == current_type == "text" else "\n\n"
        parts.extend((separator, current_text))
        previous_type = current_type
    return "".join(parts)


def _id_to_text(input_ids: str, content_list: list[dict[str, Any]], image_prefix: str = "vqa_images") -> str:
    blocks: list[tuple[str, str]] = []
    for raw_id in input_ids.replace(" ", "").split(","):
        if not raw_id:
            continue
        try:
            idx = int(raw_id)
        except ValueError:
            continue
        if idx < 0 or idx >= len(content_list):
            continue
        item = content_list[idx]
        if item.get("type") == "table" and (item.get("table_body") or item.get("text")):
            table_body = str(item.get("table_body") or item.get("text"))
            blocks.append(("table", _html_table_to_markdown(table_body)))
        elif "text" in item and item["text"]:
            item_type = str(item.get("type") or "text").strip().lower()
            blocks.append((item_type, str(item["text"])))
        elif "table_body" in item and item["table_body"]:
            blocks.append(("table", _html_table_to_markdown(str(item["table_body"]))))
        elif "img_path" in item:
            img_name = Path(str(item.get("img_path", ""))).name
            caption = item.get("image_caption") or ["image"]
            if isinstance(caption, list):
                alt = " ".join(str(c) for c in caption)
            else:
                alt = str(caption)
            blocks.append(("image", f"![{alt}]({image_prefix}/{img_name})"))
    return _join_content_blocks(blocks)


def _decode_answer_text(text: str) -> str:
    """Decode only the line-break syntax defined by the answer protocol."""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)
    return text.strip()


def _normalize_answer_markdown(text: str) -> str:
    """Put display-math segments on independent Markdown blocks."""
    parts = text.split("$$")
    if len(parts) % 2 == 0:
        raise ValueError("Unbalanced display-math delimiters in answer")

    blocks: list[str] = []
    for index, part in enumerate(parts):
        part = part.strip()
        if not part:
            continue
        if index % 2 == 0:
            blocks.append(part)
        else:
            blocks.append(f"$$\n{part}\n$$")
    return "\n\n".join(blocks)


def normalize_answer(text: str) -> str:
    """Normalize an answer without interpreting LaTeX escape sequences."""
    return _normalize_answer_markdown(_decode_answer_text(text))


def parse_llm_response(
    response: str,
    content_list: list[dict[str, Any]],
    *,
    image_prefix: str = "vqa_images",
) -> list[dict[str, Any]]:
    if "<empty>" in response and "</empty>" in response and "<vqa_pair>" not in response:
        return []

    qa_list: list[dict[str, Any]] = []
    for chapter_block in re.findall(r"<chapter>(.*?)</chapter>", response, flags=re.DOTALL):
        title_match = re.search(r"<title>(.*?)</title>", chapter_block, flags=re.DOTALL)
        chapter_title = _id_to_text(title_match.group(1).strip(), content_list, image_prefix) if title_match else ""
        for pair in re.findall(r"<vqa_pair>(.*?)</vqa_pair>", chapter_block, flags=re.DOTALL):
            q_match = re.search(r"<question>(.*?)</question>", pair, flags=re.DOTALL)
            a_match = re.search(r"<answer>(.*?)</answer>", pair, flags=re.DOTALL)
            s_match = re.search(r"<solution>(.*?)</solution>", pair, flags=re.DOTALL)
            label_match = re.search(r"<label>(.*?)</label>", pair, flags=re.DOTALL)
            if not label_match:
                continue
            if not ((q_match and label_match) or (a_match and label_match) or (s_match and label_match)):
                continue
            qa_list.append(
                {
                    "question": (_id_to_text(q_match.group(1).strip(), content_list, image_prefix) if q_match else ""),
                    "answer": normalize_answer(a_match.group(1)) if a_match else "",
                    "solution": (_id_to_text(s_match.group(1).strip(), content_list, image_prefix) if s_match else ""),
                    "label": label_match.group(1).strip(),
                    "chapter_title": chapter_title,
                }
            )
    return qa_list


def write_vqa_jsonl(qa_list: list[dict[str, Any]], output_path: str | Path) -> Path:
    out = Path(output_path).expanduser().resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as fh:
        for qa in qa_list:
            fh.write(json.dumps(qa, ensure_ascii=False) + "\n")
    return out
