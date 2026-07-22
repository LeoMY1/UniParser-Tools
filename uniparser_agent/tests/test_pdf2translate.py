"""Unit tests for pdf2translate."""

from __future__ import annotations

import json
import re
from pathlib import Path

import fitz
import pytest
from typer.testing import CliRunner

from uniparser_agent.cli import app
from uniparser_agent.pdf2translate.glossary import (
    GlossaryEntry,
    hit_glossary_entries,
    load_glossary_csv,
    majority_vote_terms,
)
from uniparser_agent.pdf2translate.layout_adapter import (
    norm_bbox_to_pdf,
    pages_tree_to_units,
)
from uniparser_agent.pdf2translate.models import BBox, TranslateUnit
from uniparser_agent.pdf2translate.pipeline import run_translate_pipeline
from uniparser_agent.pdf2translate.prompts import build_context_fields, build_translate_system_prompt
from uniparser_agent.pdf2translate.renderer import render_translated_pdf
from uniparser_agent.pdf2translate.translator import (
    TranslateLLMClient,
    TranslateStats,
    parse_and_validate_batch,
    protect_formulas,
    restore_formulas,
    translate_units,
)


def _unit(
    unit_id: str,
    text: str,
    *,
    page: int = 0,
    order: int = 0,
    block_type: str = "paragraph",
) -> TranslateUnit:
    return TranslateUnit(
        unit_id=unit_id,
        page=page,
        order=order,
        block_type=block_type,
        text=text,
        bbox_norm={"x1": 0, "y1": 0, "x2": 1, "y2": 1},
        page_size_px=(100, 100),
        bbox_pdf=BBox(10, 10, 90, 40),
        translate=True,
        status="pending",
    )


def test_norm_bbox_to_pdf_top_left() -> None:
    bbox = norm_bbox_to_pdf(
        {"x1": 0.1, "y1": 0.1, "x2": 0.5, "y2": 0.3},
        page_width=100.0,
        page_height=200.0,
    )
    assert bbox.x0 == pytest.approx(10.0)
    assert bbox.x1 == pytest.approx(50.0)
    assert bbox.y0 == pytest.approx(20.0)
    assert bbox.y1 == pytest.approx(60.0)


def test_pages_tree_to_units_whitelist_and_skip() -> None:
    data = {
        "pages_tree": [
            [
                {
                    "page": 0,
                    "order": 1,
                    "type": "paragraph",
                    "text": "Hello world",
                    "bbox": {"x1": 0.1, "y1": 0.1, "x2": 0.8, "y2": 0.2},
                    "page_size": [100, 200],
                },
                {
                    "page": 0,
                    "order": 2,
                    "type": "equation",
                    "latex_repr": "x^2",
                    "text": "",
                    "bbox": {"x1": 0.1, "y1": 0.3, "x2": 0.5, "y2": 0.4},
                    "page_size": [100, 200],
                },
                {
                    "page": 0,
                    "order": 3,
                    "type": "pageheader",
                    "text": "header",
                    "bbox": {"x1": 0.1, "y1": 0.0, "x2": 0.9, "y2": 0.05},
                    "page_size": [100, 200],
                },
            ]
        ]
    }
    units = pages_tree_to_units(data, page_rect_map={0: (100.0, 200.0)})
    assert len(units) == 3
    assert units[0].translate is True and units[0].status == "pending"
    assert units[1].translate is False and units[1].skip_reason == "type:equation"
    assert units[2].translate is False and units[2].skip_reason == "type:pageheader"


def test_protect_and_restore_formulas() -> None:
    text = "Energy $E=mc^2$ and display $$a+b$$."
    protected, placeholders = protect_formulas(text)
    assert "$E=mc^2$" not in protected
    assert "<<EQ0>>" in protected
    assert "<<EQ1>>" in protected
    restored = restore_formulas(protected.replace("Energy", "能量"), placeholders)
    assert "$E=mc^2$" in restored
    assert "$$a+b$$" in restored


def test_restore_formulas_missing_placeholder_raises() -> None:
    with pytest.raises(ValueError, match="Missing placeholder"):
        restore_formulas("no placeholder", {"<<EQ0>>": "$x$"})


def test_parse_and_validate_rejects_empty_and_accepts_aliases() -> None:
    raw = json.dumps(
        [
            {"unit_id": "a", "translated_text": ""},
            {"unit_id": "b", "translation": "乙"},
            {"unit_id": "c", "text": "丙"},
            {"unit_id": "d"},
        ]
    )
    accepted, meta = parse_and_validate_batch(raw, expected_ids={"a", "b", "c", "d"})
    assert accepted == {"b": "乙", "c": "丙"}
    assert set(meta["empty_or_missing"]) == {"a", "d"}
    assert meta["complete"] is False


def test_translate_units_with_fake_client() -> None:
    unit = _unit("u1", "Hello $x$")

    def fake_chat(*, system_prompt: str, user_content: str) -> str:
        payload = json.loads(user_content)
        assert payload[0]["text"].startswith("Hello")
        assert "<<EQ0>>" in payload[0]["text"]
        return json.dumps(
            [{"unit_id": "u1", "translated_text": "你好 <<EQ0>>"}],
            ensure_ascii=False,
        )

    client = TranslateLLMClient(api_key="test", chat_fn=fake_chat)
    translate_units([unit], client=client, auto_glossary=False)
    assert unit.status == "translated"
    assert unit.translated_text == "你好 $x$"


def test_empty_batch_then_item_retry_succeeds(tmp_path: Path) -> None:
    units = [_unit("u1", "Hello"), _unit("u2", "World", order=1)]
    calls: list[str] = []

    def fake_chat(*, system_prompt: str, user_content: str) -> str:
        payload = json.loads(user_content)
        calls.append("batch" if len(payload) > 1 else "item")
        if len(payload) > 1:
            return json.dumps(
                [
                    {"unit_id": "u1", "translated_text": ""},
                    {"unit_id": "u2", "translated_text": ""},
                ]
            )
        uid = payload[0]["unit_id"]
        return json.dumps([{"unit_id": uid, "translated_text": f"译-{uid}"}])

    client = TranslateLLMClient(api_key="test", chat_fn=fake_chat, batch_size=2)
    stats = TranslateStats()
    translate_units(
        units,
        client=client,
        auto_glossary=False,
        output_dir=tmp_path,
        stats_out=stats,
        max_retries=1,
    )
    assert all(u.status == "translated" for u in units)
    assert units[0].translated_text == "译-u1"
    assert "batch" in calls and "item" in calls
    assert stats.item_retries >= 2
    assert stats.empty_rejected >= 2
    assert (tmp_path / "llm_raw").is_dir()
    assert any((tmp_path / "llm_raw").glob("batch_*.txt"))
    assert any((tmp_path / "llm_raw").glob("unit_*.txt"))


def test_item_retry_final_failure_keeps_original() -> None:
    unit = _unit("u1", "Hello")

    def fake_chat(*, system_prompt: str, user_content: str) -> str:
        return json.dumps([{"unit_id": "u1", "translated_text": ""}])

    client = TranslateLLMClient(api_key="test", chat_fn=fake_chat)
    translate_units([unit], client=client, auto_glossary=False, max_retries=1)
    assert unit.status == "failed"
    assert unit.translated_text is None
    assert unit.text == "Hello"


def test_translate_units_batch_failure_keeps_original() -> None:
    unit = _unit("u1", "Hello")

    def bad_chat(*, system_prompt: str, user_content: str) -> str:
        raise RuntimeError("boom")

    client = TranslateLLMClient(api_key="test", chat_fn=bad_chat)
    translate_units([unit], client=client, auto_glossary=False, max_retries=0)
    assert unit.status == "failed"
    assert unit.translated_text is None


def test_glossary_hits_injected_into_prompt(tmp_path: Path) -> None:
    unit = _unit("u1", "We evaluate RETROSPECT on USPTO-50K.")
    glossary_csv = tmp_path / "terms.csv"
    glossary_csv.write_text(
        "source,target\nRETROSPECT,回顾式方法\nUSPTO-50K,USPTO-50K数据集\n",
        encoding="utf-8",
    )
    seen: list[str] = []

    def fake_chat(*, system_prompt: str, user_content: str) -> str:
        seen.append(system_prompt)
        return json.dumps([{"unit_id": "u1", "translated_text": "我们在 USPTO-50K 上评估回顾式方法。"}])

    client = TranslateLLMClient(api_key="test", chat_fn=fake_chat)
    translate_units(
        [unit],
        client=client,
        auto_glossary=False,
        glossary_path=glossary_csv,
    )
    assert any("RETROSPECT => 回顾式方法" in p for p in seen)
    assert any("USPTO-50K" in p for p in seen)


def test_load_glossary_csv_filters_tgt_lng(tmp_path: Path) -> None:
    path = tmp_path / "g.csv"
    path.write_text(
        "source,target,tgt_lng\nA,甲,zh-CN\nB,乙,en\nC,丙,\n",
        encoding="utf-8",
    )
    entries = load_glossary_csv(path, target_lang="zh-CN")
    assert {(e.source, e.target) for e in entries} == {("A", "甲"), ("C", "丙")}


def test_majority_vote_terms() -> None:
    entries = majority_vote_terms(
        [("Alpha", "甲"), ("Alpha", "甲"), ("Alpha", "乙"), ("Beta", "丙")]
    )
    by_src = {e.source: e.target for e in entries}
    assert by_src["Alpha"] == "甲"
    assert by_src["Beta"] == "丙"


def test_context_title_and_prev_cross_page() -> None:
    units = [
        _unit("t1", "Intro", page=0, order=0, block_type="title"),
        _unit("p1", "First para", page=0, order=1),
        _unit("p2", "Second para", page=1, order=0),
    ]
    ctx = build_context_fields(units)
    assert ctx["p1"]["context_title"] == "Intro"
    assert ctx["p1"]["context_prev"] == "Intro"
    assert ctx["p2"]["context_title"] == "Intro"
    assert ctx["p2"]["context_prev"] == "First para"


def test_context_fields_in_request_payload() -> None:
    units = [
        _unit("t1", "Methods", page=0, order=0, block_type="title"),
        _unit("p1", "We propose X.", page=0, order=1),
    ]
    captured: list[dict] = []

    def fake_chat(*, system_prompt: str, user_content: str) -> str:
        assert "Only translate the `text` field" in system_prompt or "context_title" in system_prompt
        payload = json.loads(user_content)
        captured.extend(payload)
        return json.dumps(
            [{"unit_id": item["unit_id"], "translated_text": f"译{item['unit_id']}"} for item in payload]
        )

    client = TranslateLLMClient(api_key="test", chat_fn=fake_chat, batch_size=10)
    translate_units(units, client=client, auto_glossary=False)
    by_id = {item["unit_id"]: item for item in captured}
    assert by_id["p1"]["context_title"] == "Methods"
    assert "translated_text" not in by_id["p1"]
    assert "text" in by_id["p1"]


def test_system_prompt_mentions_glossary() -> None:
    prompt = build_translate_system_prompt(
        glossary_entries=[GlossaryEntry("LambdaMART", "LambdaMART")]
    )
    assert "LambdaMART => LambdaMART" in prompt
    assert hit_glossary_entries("use LambdaMART model", [GlossaryEntry("LambdaMART", "L")])


def _make_sample_pdf(path: Path, text: str = "Original text block") -> Path:
    doc = fitz.open()
    page = doc.new_page(width=300, height=400)
    page.insert_textbox(fitz.Rect(40, 80, 260, 140), text, fontsize=12)
    doc.save(str(path))
    doc.close()
    return path


def test_render_translated_pdf_draws_text(tmp_path: Path) -> None:
    pdf = _make_sample_pdf(tmp_path / "src.pdf")
    unit = TranslateUnit(
        unit_id="u1",
        page=0,
        order=0,
        block_type="paragraph",
        text="Original text block",
        bbox_norm={"x1": 0.13, "y1": 0.2, "x2": 0.87, "y2": 0.35},
        page_size_px=(300, 400),
        bbox_pdf=BBox(40, 80, 260, 140),
        translate=True,
        status="translated",
        translated_text="Translated text block",
    )
    out = tmp_path / "out.pdf"
    stats = render_translated_pdf(pdf, [unit], out)
    assert out.exists()
    assert stats["pages"] == 1
    doc = fitz.open(str(out))
    extracted = doc[0].get_text().replace("\xa0", " ")
    doc.close()
    assert "Translated text block" in extracted


def test_pipeline_with_pages_tree_and_fake_translator(tmp_path: Path) -> None:
    pdf = _make_sample_pdf(tmp_path / "paper.pdf", text="Hello world")
    tree = {
        "pages_tree": [
            [
                {
                    "page": 0,
                    "order": 1,
                    "type": "paragraph",
                    "text": "Hello world",
                    "bbox": {"x1": 0.13, "y1": 0.2, "x2": 0.87, "y2": 0.35},
                    "page_size": [300, 400],
                },
                {
                    "page": 0,
                    "order": 2,
                    "type": "equation",
                    "latex_repr": "a+b",
                    "bbox": {"x1": 0.1, "y1": 0.5, "x2": 0.4, "y2": 0.6},
                    "page_size": [300, 400],
                },
            ]
        ]
    }
    tree_path = tmp_path / "pages_tree.json"
    tree_path.write_text(json.dumps(tree), encoding="utf-8")

    def fake_chat(*, system_prompt: str, user_content: str) -> str:
        assert "zh-CN" in system_prompt
        payload = json.loads(user_content)
        return json.dumps(
            [
                {
                    "unit_id": payload[0]["unit_id"],
                    "translated_text": "你好世界",
                }
            ],
            ensure_ascii=False,
        )

    client = TranslateLLMClient(api_key="test", chat_fn=fake_chat)
    result = run_translate_pipeline(
        str(pdf),
        pages_tree_path=str(tree_path),
        output_dir=str(tmp_path / "out"),
        overwrite=True,
        debug_layout=True,
        auto_glossary=False,
        translator_client=client,
    )
    assert Path(result["paths"]["translated_pdf"]).exists()
    assert Path(result["paths"]["translate_units"]).exists()
    assert Path(result["paths"]["run_meta"]).exists()
    assert Path(result["paths"]["layout_debug_pdf"]).exists()
    assert Path(result["paths"]["llm_raw"]).is_dir()
    assert result["languages"]["target_lang"] == "zh-CN"
    assert result["counts"]["translated"] + result["counts"]["overflow"] >= 1
    assert result["counts"]["skipped"] >= 1

    doc = fitz.open(result["paths"]["translated_pdf"])
    text = doc[0].get_text()
    doc.close()
    assert "你好世界" in text


def test_pipeline_overwrite_preserves_pages_tree_under_output(tmp_path: Path) -> None:
    pdf = _make_sample_pdf(tmp_path / "paper.pdf", text="Hello")
    out = tmp_path / "out"
    out.mkdir()
    parse_dir = out / "parse"
    parse_dir.mkdir()
    tree = {
        "pages_tree": [
            [
                {
                    "page": 0,
                    "order": 1,
                    "type": "paragraph",
                    "text": "Hello",
                    "bbox": {"x1": 0.13, "y1": 0.2, "x2": 0.87, "y2": 0.35},
                    "page_size": [300, 400],
                }
            ]
        ]
    }
    tree_path = parse_dir / "pages_tree.json"
    tree_path.write_text(json.dumps(tree), encoding="utf-8")

    def fake_chat(*, system_prompt: str, user_content: str) -> str:
        payload = json.loads(user_content)
        return json.dumps(
            [{"unit_id": payload[0]["unit_id"], "translated_text": "你好"}],
            ensure_ascii=False,
        )

    client = TranslateLLMClient(api_key="test", chat_fn=fake_chat)
    result = run_translate_pipeline(
        str(pdf),
        pages_tree_path=str(tree_path),
        output_dir=str(out),
        overwrite=True,
        auto_glossary=False,
        translator_client=client,
    )
    assert Path(result["paths"]["translated_pdf"]).exists()
    assert Path(result["paths"]["pages_tree"]).exists()


def test_inline_math_renders_percent_and_symbols() -> None:
    from uniparser_agent.pdf2translate.mathtext import latex_inner_to_display, render_inline_math

    assert latex_inner_to_display(r" 55.00\% ") == "55.00%"
    # Without a font constraint, use Unicode sub/superscripts.
    assert latex_inner_to_display(r" \beta_{1} = 0.9 ") == "β₁ = 0.9"
    assert latex_inner_to_display(r" P_{1}, \ldots, P_{K} ") == "P₁, …, Pₖ"
    assert latex_inner_to_display(r" ^{*1} ") == "∗¹"
    assert latex_inner_to_display(r" \epsilon = 10^{-9} ") == "ε = 10⁻⁹"

    text = r"达到 $ 55.00\% $ 的top-1和 $ 86.18\% $ 的top-10"
    out = render_inline_math(text)
    assert "$" not in out
    assert "\\%" not in out
    assert "55.00%" in out
    assert "86.18%" in out


def test_inline_math_falls_back_when_font_lacks_subscripts() -> None:
    import fitz
    from uniparser_agent.pdf2translate.mathtext import latex_inner_to_display

    font = fitz.Font(fontfile="/System/Library/Fonts/Hiragino Sans GB.ttc")
    # Hiragino GB has β/ε but not ₁ / ⁻.
    assert latex_inner_to_display(r" \beta_{1} = 0.9 ", font=font) == "β1 = 0.9"
    assert latex_inner_to_display(r" \epsilon = 10^{-9} ", font=font) == "ε = 10^-9"
    assert latex_inner_to_display(r" 55.00\% ", font=font) == "55.00%"

    from uniparser_agent.pdf2translate.renderer import _CJK_FONT_CANDIDATES, _resolve_font

    assert "Hiragino Sans GB" in _CJK_FONT_CANDIDATES[0] or "Songti" in _CJK_FONT_CANDIDATES[0]
    _name, path = _resolve_font(None, "china-s")
    assert path is not None
    # On macOS CI/dev machines Hiragino GB should win over PingFang HK.
    assert "PingFang" not in path or not Path("/System/Library/Fonts/Hiragino Sans GB.ttc").is_file()

    from uniparser_agent.pdf2translate.renderer import FONT_SIZE_BY_TYPE, font_size_for_type

    assert font_size_for_type("documenttitle") == FONT_SIZE_BY_TYPE["documenttitle"]
    assert font_size_for_type("title") == FONT_SIZE_BY_TYPE["title"]
    assert font_size_for_type("paragraph") == FONT_SIZE_BY_TYPE["paragraph"]
    assert font_size_for_type("title") > font_size_for_type("paragraph")
    assert font_size_for_type("paragraph") > font_size_for_type("reference")
    assert font_size_for_type("mystery") == 10.0


def test_wrap_cjk_keeps_latin_words_intact() -> None:
    import fitz
    from uniparser_agent.pdf2translate.renderer import _measure_font, wrap_cjk_text

    font = _measure_font(None)
    text = "RETROSPECT将一个ChemAlign Transformer提案模型与LambdaMART重排序。"
    lines = wrap_cjk_text(text, max_width=180.0, fontsize=10.0, font=font)
    joined = "".join(lines)
    assert "RETROSPECT" in joined
    assert "ChemAlign" in joined
    assert "Transformer" in joined
    # Must not split Latin identifiers across lines mid-token.
    for line in lines:
        assert "RETROSPEC" not in line or "RETROSPECT" in line
        assert not re.search(r"ChemAlig$", line)
        assert not re.search(r"^n Transformer", line)
    assert any("RETROSPECT" in line for line in lines)


def test_render_same_type_same_font_size(tmp_path: Path) -> None:
    from uniparser_agent.pdf2translate.renderer import FONT_SIZE_BY_TYPE

    pdf = tmp_path / "src.pdf"
    doc = fitz.open()
    page = doc.new_page(width=400, height=500)
    page.insert_text((40, 80), "1. Introduction", fontsize=12)
    page.insert_textbox(fitz.Rect(40, 120, 360, 200), "Short body.", fontsize=10)
    page.insert_textbox(fitz.Rect(40, 220, 360, 320), "Another longer body paragraph here.", fontsize=10)
    doc.save(str(pdf))
    doc.close()

    title = TranslateUnit(
        unit_id="t1",
        page=0,
        order=0,
        block_type="title",
        text="1. Introduction",
        bbox_norm={"x1": 0.1, "y1": 0.15, "x2": 0.5, "y2": 0.2},
        page_size_px=(400, 500),
        bbox_pdf=BBox(40, 68, 200, 82),
        translate=True,
        status="translated",
        translated_text="1. 引言",
    )
    p1 = TranslateUnit(
        unit_id="p1",
        page=0,
        order=1,
        block_type="paragraph",
        text="Short body.",
        bbox_norm={"x1": 0.1, "y1": 0.24, "x2": 0.9, "y2": 0.4},
        page_size_px=(400, 500),
        bbox_pdf=BBox(40, 120, 360, 160),
        translate=True,
        status="translated",
        translated_text="短正文。",
    )
    p2 = TranslateUnit(
        unit_id="p2",
        page=0,
        order=2,
        block_type="paragraph",
        text="Another longer body paragraph here.",
        bbox_norm={"x1": 0.1, "y1": 0.44, "x2": 0.9, "y2": 0.64},
        page_size_px=(400, 500),
        bbox_pdf=BBox(40, 220, 360, 280),
        translate=True,
        status="translated",
        translated_text="另一段更长的正文内容，用于验证同类型字号一致。",
    )
    out = tmp_path / "out.pdf"
    render_translated_pdf(pdf, [title, p1, p2], out)
    assert title.font_size == FONT_SIZE_BY_TYPE["title"]
    assert p1.font_size == FONT_SIZE_BY_TYPE["paragraph"]
    assert p2.font_size == FONT_SIZE_BY_TYPE["paragraph"]
    assert p1.font_size == p2.font_size


def test_render_textbox_fit_semantics() -> None:
    from uniparser_agent.pdf2translate.renderer import _textbox_fits

    assert _textbox_fits(
        300,
        400,
        fitz.Rect(40, 40, 260, 120),
        "你好世界",
        fontname="china-s",
        fontfile=None,
        fontsize=12,
    )
    assert not _textbox_fits(
        300,
        400,
        fitz.Rect(40, 40, 100, 55),
        "这是一段很长很长很长很长很长很长的中文翻译文本，用来验证放不下时返回 False",
        fontname="china-s",
        fontfile=None,
        fontsize=14,
    )


def test_pipeline_requires_pdf_extension(tmp_path: Path) -> None:
    bad = tmp_path / "note.txt"
    bad.write_text("x", encoding="utf-8")
    with pytest.raises(ValueError, match="PDF"):
        run_translate_pipeline(str(bad), overwrite=True)


def test_cli_translate_has_no_target_lang_option() -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["translate", "--help"])
    assert result.exit_code == 0
    assert "--target-lang" not in result.stdout
    assert "--glossary" in result.stdout
    assert "--no-auto-glossary" in result.stdout
