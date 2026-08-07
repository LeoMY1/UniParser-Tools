from uniparser_agent.pdf2vqa.prompts import build_vqa_extract_prompt


def test_prompt_uses_dataflow_field_contract() -> None:
    prompt = build_vqa_extract_prompt()

    assert 'only need to output "id" field for **chapter titles, questions and solutions**' in prompt
    assert 'DO NOT output "id" field for labels and answers.' in prompt
    assert "YOU MUST KEEP SHORT ANSWERS" in prompt
    assert "You MUST include all images referenced in the question/answer/solution." in prompt
    assert "format the formula-derived result in Markdown inline LaTeX `$...$`" in prompt
    assert "<answer>$2^6$</answer>" in prompt
    assert "<answer>3.14</answer>" in prompt
    assert "<br/>" not in prompt
    assert "Never output the literal" not in prompt
