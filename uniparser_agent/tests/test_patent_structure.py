from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from uniparser_agent.chemistry.patent_structure import (
    BlockResolver,
    build_patent_structure,
    pages_tree_sha256,
    write_patent_structure,
)
from uniparser_agent.parse.options import SCIENTIFIC_PAPER_TRIGGER


def _block(block_id: int, page: int, order: int, block_type: str, text: str = "") -> dict:
    return {
        "token": "repeated-token",
        "page": page,
        "order": order,
        "block": block_id,
        "type": block_type,
        "text": text,
        "bbox": {"x1": 0.1, "y1": 0.2, "x2": 0.3, "y2": 0.4},
        "bboxes": [],
        "page_size": [1000, 1400],
        "direction": -1,
        "hidden": False,
    }


def _cn_patent_fixture() -> dict:
    molecule_group = _block(13, 1, 3, "moleculegroup", "label=(I)")
    molecule_group["items"] = [
        {
            **_block(13, 1, 4, "molecule"),
            "smi": "CCO",
            "markush": False,
        }
    ]
    drawing = _block(51, 4, 1, "image")
    drawing["items"] = [
        {
            **_block(51, 4, 2, "expression"),
            "reactions": [],
        }
    ]
    return {
        "filename": "CN123456789A.pdf",
        "token": "fixture-token",
        "pages_tree": [
            [
                _block(1, 0, 0, "keyvalue", "(10)申请公布号 CN 123456789 A"),
                _block(2, 0, 1, "pageheader", ""),
            ],
            [
                _block(10, 1, 0, "pageheader", "CN 123456789 A"),
                _block(11, 1, 1, "pageheader", "权利要求书"),
                _block(12, 1, 2, "paragraph", "1. 一种式(I)化合物。"),
                molecule_group,
            ],
            [
                _block(20, 2, 0, "paragraph", "其中R1选自氢或卤素。"),
            ],
            [
                _block(10, 3, 0, "pageheader", "CN 123456789 A"),
                _block(31, 3, 1, "pageheader", "说明书"),
                _block(32, 3, 2, "title", "技术领域"),
                _block(33, 3, 3, "paragraph", "[0001] 本发明涉及药物化学领域。"),
                _block(34, 3, 4, "title", "背景技术"),
                _block(35, 3, 5, "paragraph", "[0002] 现有药物仍有不足。"),
                _block(36, 3, 6, "paragraph", "[0005] 发明目的"),
                _block(37, 3, 7, "paragraph", "[0006] 本发明提供一种化合物。"),
                _block(38, 3, 8, "title", "附图说明"),
                _block(39, 3, 9, "paragraph", "[0007] 图1为反应路线。"),
                _block(40, 3, 10, "title", "具体实施方式"),
                _block(41, 3, 11, "paragraph", "[0008] 实施例1制备目标化合物。"),
            ],
            [
                _block(50, 4, 0, "pageheader", "说明书附图"),
                drawing,
                _block(52, 4, 3, "hline"),
                _block(53, 4, 4, "pagenumber", "1/1页"),
            ],
        ],
    }


def _nodes_by_type(structure: dict) -> dict[str, dict]:
    top_nodes = structure["tree"]["children"]
    nodes = {node["node_type"]: node for node in top_nodes}
    nodes.update({node["node_type"]: node for node in nodes["description"]["children"]})
    return nodes


def _leaf_refs(structure: dict) -> list[dict]:
    refs = []
    for node in structure["tree"]["children"]:
        if node["children"]:
            for child in node["children"]:
                refs.extend(child["block_refs"])
        else:
            refs.extend(node["block_refs"])
    return refs


def _assert_filtered(value: object) -> None:
    if isinstance(value, dict):
        assert not {"bbox", "bboxes", "direction", "hidden", "page_size", "token"} & set(value)
        for item in value.values():
            _assert_filtered(item)
    elif isinstance(value, list):
        for item in value:
            _assert_filtered(item)


def test_build_cn_patent_structure_has_fixed_depth_and_block_locations() -> None:
    document = _cn_patent_fixture()
    structure = build_patent_structure(document, "CN123456789A")
    nodes = _nodes_by_type(structure)

    assert structure["schema_version"] == "2.0"
    assert structure["patent_format"] == "CN"
    assert structure["source"]["sha256"] == pages_tree_sha256(document)
    assert [page["node_type"] for page in structure["page_map"]] == [
        "front_matter",
        "claims",
        "claims",
        "description",
        "drawings",
    ]
    assert (nodes["front_matter"]["page_start"], nodes["front_matter"]["page_end"]) == (1, 1)
    assert (nodes["claims"]["page_start"], nodes["claims"]["page_end"]) == (2, 3)
    assert (nodes["description"]["page_start"], nodes["description"]["page_end"]) == (4, 4)
    assert (nodes["drawings"]["page_start"], nodes["drawings"]["page_end"]) == (5, 5)
    assert nodes["claims"]["children"] == []
    assert all(child["children"] == [] for child in nodes["description"]["children"])
    assert [(ref["page_index"], ref["block_index"]) for ref in nodes["claims"]["block_refs"]] == [
        (1, 0),
        (1, 1),
        (1, 2),
        (1, 3),
        (2, 0),
    ]


def test_description_uses_title_then_short_paragraph_fallback() -> None:
    structure = build_patent_structure(_cn_patent_fixture(), "CN123456789A")
    nodes = _nodes_by_type(structure)

    assert {ref["block"] for ref in nodes["technical_field"]["block_refs"]} == {32, 33}
    assert {ref["block"] for ref in nodes["background"]["block_refs"]} == {34, 35}
    assert {ref["block"] for ref in nodes["invention_summary"]["block_refs"]} == {36, 37}
    assert {ref["block"] for ref in nodes["drawings_description"]["block_refs"]} == {38, 39}
    assert {ref["block"] for ref in nodes["detailed_description"]["block_refs"]} == {40, 41}
    assert {ref["block"] for ref in nodes["description_other"]["block_refs"]} == {10, 31}
    assert nodes["invention_summary"]["heading_ref"]["block"] == 36


def test_resolver_filters_noise_and_fields_but_keeps_nested_chemistry() -> None:
    document = _cn_patent_fixture()
    structure = build_patent_structure(document, "CN123456789A")
    resolver = BlockResolver(document, structure)

    claims = resolver.resolve("claims")
    assert [block["block"] for block in claims] == [12, 13, 20]
    molecule_group = next(block for block in claims if block["type"] == "moleculegroup")
    assert molecule_group["items"][0]["type"] == "molecule"
    assert molecule_group["items"][0]["smi"] == "CCO"

    drawings = resolver.resolve("drawings")
    assert [block["type"] for block in drawings] == ["image"]
    assert drawings[0]["items"][0]["type"] == "expression"
    assert drawings[0]["items"][0]["reactions"] == []
    _assert_filtered(claims)
    _assert_filtered(drawings)
    assert not hasattr(resolver, "resolve_raw")
    assert "bbox" in document["pages_tree"][1][2]


def test_resolver_can_attach_stable_locations_without_a_second_read_path() -> None:
    document = _cn_patent_fixture()
    structure = build_patent_structure(document, "CN123456789A")
    resolver = BlockResolver(document, structure)

    located = resolver.resolve("claims", include_locations=True)

    assert located[0]["locator"] == {"page_index": 1, "block_index": 2, "block": 12}
    assert located[0]["content"]["text"] == "1. 一种式(I)化合物。"
    assert "bbox" not in located[0]["content"]
    assert not hasattr(resolver, "resolve_raw")


def test_refs_cover_every_top_level_block_once_without_source_ref() -> None:
    document = _cn_patent_fixture()
    structure = build_patent_structure(document, "CN123456789A")
    refs = _leaf_refs(structure)
    locations = [(ref["page_index"], ref["block_index"]) for ref in refs]

    assert len(locations) == sum(len(page) for page in document["pages_tree"])
    assert len(locations) == len(set(locations))
    assert all(set(ref) == {"page_index", "block_index", "block"} for ref in refs)
    assert "source_ref" not in json.dumps(structure)
    assert "unit_refs" not in structure
    assert structure["warnings"] == []


def test_resolver_rejects_a_different_pages_tree() -> None:
    document = _cn_patent_fixture()
    structure = build_patent_structure(document, "CN123456789A")
    changed_document = copy.deepcopy(document)
    changed_document["pages_tree"][1][2]["text"] = "changed"

    with pytest.raises(ValueError, match="does not match"):
        BlockResolver(changed_document, structure)


def test_write_patent_structure_and_fixed_expression_mode(tmp_path: Path) -> None:
    output_path = write_patent_structure(
        _cn_patent_fixture(),
        "CN123456789A",
        tmp_path / "patent_structure.json",
    )
    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert payload["doc_id"] == "CN123456789A"
    assert SCIENTIFIC_PAPER_TRIGGER["molecule"] == 1
    assert SCIENTIFIC_PAPER_TRIGGER["expression"] == 1
