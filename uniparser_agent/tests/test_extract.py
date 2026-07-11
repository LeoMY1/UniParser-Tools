from __future__ import annotations

import json
from pathlib import Path

import pytest

from uniparser_agent.extract import extract_from_pages_tree
from uniparser_agent.jobspec import JobSpec
from uniparser_agent.parse import load_pages_tree
from uniparser_agent.pipeline import ingest_pages_tree
from uniparser_agent.validate import build_markush_record, validate_smiles


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


def test_validate_smiles() -> None:
    record = validate_smiles("CCO")
    assert record is not None
    assert record.inchikey
    assert validate_smiles("not-a-smiles") is None


def test_markush_hash_stable() -> None:
    a = build_markush_record("*C*", "caption")
    b = build_markush_record("*C*", "caption")
    assert a.content_hash == b.content_hash
