from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.main import get_command

from uniparser_agent.chemistry.pipeline import ingest_pages_tree, run_full_pipeline
from uniparser_agent.cli import app


def _block(block_type: str, text: str = "", **extra: object) -> dict:
    return {
        "type": block_type,
        "text": text,
        "block": extra.pop("block", 1),
        **extra,
    }


def _write_cn_pages_tree(path: Path) -> Path:
    document = {
        "filename": "CN123456789A.pdf",
        "pages_tree": [
            [
                _block("documenttitle", "CN 123456789 A", block=1),
                _block("keyvalue", "(54)发明名称测试化合物", block=2),
                _block("keyvalue", "(57)摘要\n测试摘要。", block=3),
            ],
            [
                _block("pageheader", "权利要求书", block=4),
                _block("paragraph", "1. 一种式I化合物。", block=5),
            ],
            [
                _block("pageheader", "说明书", block=6),
                _block("title", "发明内容", block=7),
                _block("paragraph", "本发明提供式(I)化合物，其中R为烷基。", block=8),
                _block(
                    "molecule",
                    "",
                    block=9,
                    order=3,
                    smi="*c1ccccc1",
                    markush=True,
                    conf=0.99,
                ),
                _block("title", "具体实施方式", block=10),
                _block("paragraph", "以下结合实施例进一步说明。", block=11),
            ],
        ],
    }
    path.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")
    return path


def test_ingest_pages_tree_writes_only_v2_patent_artifacts(tmp_path: Path) -> None:
    pages_tree_path = _write_cn_pages_tree(tmp_path / "pages_tree.json")
    output_dir = tmp_path / "artifacts"

    result = ingest_pages_tree(
        pages_tree_path,
        doc_id="CN123456789A",
        output_dir=output_dir,
        skip_llm=True,
    )

    assert result["doc_id"] == "CN123456789A"
    assert result["formula_count"] == 1
    assert result["formula_occurrence_count"] == 1
    assert result["formula_llm_call_count"] == 0
    for key in (
        "patent_structure_path",
        "patent_basic_info_path",
        "general_formula_inventory_path",
        "general_formula_context_chunks_path",
        "general_formula_analysis_path",
        "general_formula_excel_path",
        "general_formula_summary_path",
    ):
        assert Path(result[key]).is_file()

    structure = json.loads(Path(result["patent_structure_path"]).read_text(encoding="utf-8"))
    assert structure["schema_version"] == "2.2"
    assert [node["node_id"] for node in structure["tree"]["children"]] == [
        "front_matter",
        "claims",
        "description",
    ]
    assert not list(tmp_path.rglob("*.db"))
    assert not list(tmp_path.rglob("*.csv"))


def test_run_full_pipeline_parses_then_uses_new_chain(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    parse_dir = tmp_path / "parsed"
    parse_dir.mkdir()
    pages_tree_path = _write_cn_pages_tree(parse_dir / "pages_tree.json")

    def fake_parse_document(input_path: str, *, output_dir: str | None = None) -> dict:
        assert input_path == "patent.pdf"
        assert output_dir == str(parse_dir)
        return {
            "source_stem": "patent",
            "output_dir": str(parse_dir),
            "pages_tree_path": str(pages_tree_path),
            "markdown_path": str(parse_dir / "patent.md"),
            "token": "token",
            "input_type": "file",
        }

    monkeypatch.setattr(
        "uniparser_agent.chemistry.pipeline.parse_document",
        fake_parse_document,
    )

    result = run_full_pipeline(
        "patent.pdf",
        doc_id="CN123456789A",
        output_dir=str(parse_dir),
        skip_llm=True,
    )

    assert result["pages_tree_path"] == str(pages_tree_path)
    assert result["markdown_path"] == str(parse_dir / "patent.md")
    assert result["formula_count"] == 1
    assert result["skip_llm"] is True


def test_cli_does_not_expose_legacy_chemistry_chain() -> None:
    command = get_command(app)
    assert command.commands is not None
    assert {"show", "export"}.isdisjoint(command.commands)

    ingest = command.commands["ingest"]
    parameter_names = {parameter.name for parameter in ingest.params}
    assert "skip_llm" in parameter_names
    assert {"db", "skip_enrich"}.isdisjoint(parameter_names)
