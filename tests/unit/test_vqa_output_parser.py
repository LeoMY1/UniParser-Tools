from uniparser_agent.pdf2vqa.output_parser import parse_llm_response


def test_selected_blocks_are_separated_for_markdown_rendering() -> None:
    content_list = [
        {"id": 0, "text": "Question"},
        {"id": 1, "type": "text", "text": "Text split across"},
        {"id": 2, "type": "text", "text": "two layout blocks."},
        {
            "id": 3,
            "type": "table",
            "table_body": (
                "<table><tr><td>Symmetry</td><td>Wave number</td></tr>"
                "<tr><td>$ A_{1} $</td><td>$ cm^{-1} $</td></tr></table>"
            ),
        },
        {"id": 4, "type": "text", "text": "Text after the table."},
        {"id": 5, "type": "equation", "text": "$$\nx = 1\n$$"},
    ]
    response = """\
<chapter><title></title>
<vqa_pair><label>1</label><question>0</question><answer></answer><solution>1,2,3,4,5</solution></vqa_pair>
</chapter>
"""

    parsed = parse_llm_response(response, content_list)

    assert parsed[0]["solution"] == (
        "Text split across\n"
        "two layout blocks.\n\n"
        "| Symmetry | Wave number |\n"
        "| --- | --- |\n"
        "| $ A_{1} $ | $ cm^{-1} $ |\n\n"
        "Text after the table.\n\n"
        "$$\nx = 1\n$$"
    )


def test_answer_is_returned_as_direct_llm_text() -> None:
    response = (
        "<chapter><title></title>"
        "<vqa_pair><label>1</label><question></question>"
        r"<answer>计算结果：<br/>$$<br/>E = mc^2<br/>$$<br>完成</answer>"
        "<solution></solution></vqa_pair>"
        "</chapter>"
    )

    parsed = parse_llm_response(response, [])

    assert parsed[0]["answer"] == r"计算结果：<br/>$$<br/>E = mc^2<br/>$$<br>完成"


def test_answer_preserves_latex_backslashes_and_literal_backslash_n() -> None:
    response = (
        "<chapter><title></title>"
        "<vqa_pair><label>1</label><question></question>"
        r"<answer>$\nu + \nabla f \neq 0$\n下一行</answer>"
        "<solution></solution></vqa_pair>"
        "</chapter>"
    )

    parsed = parse_llm_response(response, [])

    assert parsed[0]["answer"] == r"$\nu + \nabla f \neq 0$\n下一行"


def test_answer_preserves_unbalanced_display_math() -> None:
    response = (
        "<chapter><title></title>"
        "<vqa_pair><label>1</label><question></question>"
        "<answer>结果：$$x = 1</answer><solution></solution></vqa_pair>"
        "</chapter>"
    )

    parsed = parse_llm_response(response, [])

    assert parsed[0]["answer"] == "结果：$$x = 1"
