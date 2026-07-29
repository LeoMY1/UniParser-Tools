"""Unit tests for UniParser → LLM content-list adapter."""

from __future__ import annotations

from uniparser_agent.pdf2vqa.layout_adapter import pages_tree_to_content_list


def test_adapter_skips_noise_and_numbers_ids():
    data = {
        "pages_tree": [
            [
                {"type": "hline", "order": 0, "text": ""},
                {"type": "pageheader", "order": 1, "text": "header"},
                {"type": "paragraph", "order": 2, "text": "Q1 text"},
                {
                    "type": "equation",
                    "order": 3,
                    "latex_repr": "x^2=1",
                    "text": "",
                },
                {"type": "pagenumber", "order": 4, "text": "1"},
            ]
        ]
    }
    content = pages_tree_to_content_list(data)
    assert [c["id"] for c in content] == [0, 1]
    assert content[0]["type"] == "text"
    assert content[0]["text"] == "Q1 text"
    assert content[1]["type"] == "equation"
    assert "x^2=1" in content[1]["text"]
