from __future__ import annotations

import json
from pathlib import Path

from uniparser_agent.chemistry.extract import extract_from_pages_tree
from uniparser_agent.chemistry.validate import build_markush_record, validate_smiles
from uniparser_agent.parse.service import load_pages_tree


FIXTURE = Path(__file__).parent / "fixtures" / "minimal_pages_tree.json"


def test_load_pages_tree() -> None:
    doc = load_pages_tree(FIXTURE)
    assert "pages_tree" in doc


def test_extract_molecules_and_reactions() -> None:
    doc = json.loads(FIXTURE.read_text(encoding="utf-8"))
    molecules, reactions = extract_from_pages_tree(doc)
    assert len(molecules) == 3
    assert len(reactions) == 1
    assert reactions[0].reactants == "CCO"
    assert reactions[0].conditions == "DCM"


def test_extract_supports_v13_esmi_case_and_list_bbox() -> None:
    doc = {
        "pages_tree": [
            [
                {
                    "type": "Molecule",
                    "page": 1,
                    "block": 2,
                    "esmi": "[CH3][CH2][OH]",
                    "bbox": [0.1, 0.2, 0.3, 0.4],
                }
            ]
        ]
    }

    molecules, reactions = extract_from_pages_tree(doc)

    assert reactions == []
    assert len(molecules) == 1
    assert molecules[0].smi == "[CH3][CH2][OH]"
    assert molecules[0].bbox == {"x1": 0.1, "y1": 0.2, "x2": 0.3, "y2": 0.4}


def test_validate_smiles() -> None:
    record = validate_smiles("CCO")
    assert record is not None
    assert record.inchikey
    assert validate_smiles("not-a-smiles") is None


def test_markush_hash_stable() -> None:
    a = build_markush_record("*C*", "caption")
    b = build_markush_record("*C*", "caption")
    assert a.content_hash == b.content_hash
