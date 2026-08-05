from uniparser_agent.pdf2vqa.prompts import build_vqa_extract_prompt


def test_answer_line_break_protocol_is_explicit() -> None:
    prompt = build_vqa_extract_prompt()

    assert "When a line break is required inside `<answer>`, output `<br/>`." in prompt
    assert r"Never output the literal characters `\n` to represent a line break." in prompt
    assert "Keep LaTeX backslashes unchanged." in prompt
