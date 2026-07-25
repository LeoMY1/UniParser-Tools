from __future__ import annotations

import json
from pathlib import Path

import pytest

from uniparser_agent.chemistry.enrich import enrich_compounds, parse_enrich_response
from uniparser_agent.chemistry.export_csv import export_doc_csv, export_library_csv
from uniparser_agent.chemistry.extract import extract_from_pages_tree
from uniparser_agent.chemistry.join import build_logical_compounds
from uniparser_agent.chemistry.jobspec import JobSpec
from uniparser_agent.chemistry.pipeline import ingest_pages_tree
from uniparser_agent.chemistry.store import ChemistryStore
from uniparser_agent.chemistry.validate import build_markush_record, validate_smiles
from uniparser_agent.parse.service import load_pages_tree


FIXTURE = Path(__file__).parent / "fixtures" / "minimal_pages_tree.json"
CATALOG_FIXTURE = Path(__file__).parent / "fixtures" / "chemistry_catalog_pages_tree.json"
MIXED_FIXTURE = Path(__file__).parent / "fixtures" / "chemistry_mixed_types_pages_tree.json"


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


def test_build_logical_compounds_from_catalog() -> None:
    doc = json.loads(CATALOG_FIXTURE.read_text(encoding="utf-8"))
    compounds = build_logical_compounds(doc, "fixture-catalog")
    labels = {c.label for c in compounds}
    assert "I-1" in labels
    assert "I-2" in labels
    i1 = next(c for c in compounds if c.label == "I-1")
    assert i1.smi == "CCO"
    assert i1.name == "乙醇"
    assert any(a.get("kind") == "ic50" for a in i1.activity_rows)


def test_build_logical_compounds_keeps_markush_intermediate_reactant_product() -> None:
    """IA product presence must not drop Markush, intermediates, or unlabeled reactants."""
    doc = json.loads(MIXED_FIXTURE.read_text(encoding="utf-8"))
    compounds = build_logical_compounds(doc, "fixture-mixed")
    by_label = {c.label: c for c in compounds}

    assert "I" in by_label
    assert by_label["I"].markush or "*" in (by_label["I"].smi or "")

    assert "1" in by_label
    assert by_label["1"].markush or "*" in (by_label["1"].smi or "")

    assert "IA" in by_label
    assert not by_label["IA"].markush
    assert "*" not in (by_label["IA"].smi or "")

    reactant_smi = "O=C(/C=C\\Nc1ccccc1)c1ccccc1C#Cc1ccccc1"
    reactants = [c for c in compounds if c.smi == reactant_smi]
    assert reactants, "unlabeled embodiment reactant should be kept"
    assert all(c.label != "IA" for c in reactants)

    assert len(compounds) >= 4


def test_enrich_mock_llm() -> None:
    doc = json.loads(CATALOG_FIXTURE.read_text(encoding="utf-8"))
    compounds = build_logical_compounds(doc, "fixture-catalog")

    def fake_chat(system_prompt: str, user_content: str) -> str:
        payload = json.loads(user_content)
        items = []
        for card in payload["compounds"]:
            items.append(
                {
                    "compound_label": card["label"],
                    "name": card.get("name") or "",
                    "smiles": card.get("smiles") or "",
                    "role": "example_product",
                    "semantic_summary": f"{card['label']} is an example compound with tabulated activity.",
                    "activities": [
                        {
                            "activity_type": "IC50",
                            "activity_value": "0.31",
                            "activity_unit": "uM",
                            "assay": "NQO1",
                            "evidence": "table",
                        }
                    ]
                    if card["label"] == "I-1"
                    else [],
                    "confidence": 0.9,
                }
            )
        return json.dumps({"compounds": items}, ensure_ascii=False)

    enriched = enrich_compounds(
        "fixture-catalog",
        compounds,
        chat_fn=fake_chat,
        skip_enrich=False,
    )
    i1 = next(c for c in enriched if c.label == "I-1")
    assert "example compound" in i1.semantic_summary
    assert i1.role == "example_product"
    assert i1.activities_json
    assert i1.activities_json[0]["activity_type"] == "IC50"


def test_parse_enrich_response_fences() -> None:
    raw = '```json\n{"compounds":[{"compound_label":"I-1","semantic_summary":"x","activities":[]}]}\n```'
    items = parse_enrich_response(raw)
    assert items[0]["compound_label"] == "I-1"


@pytest.fixture()
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "test.db"


def test_ingest_skip_enrich(db_path: Path) -> None:
    jobspec = JobSpec.from_profile("molecules_only", db_path=db_path)
    summary = ingest_pages_tree(
        CATALOG_FIXTURE,
        jobspec=jobspec,
        doc_id="fixture-doc",
        source=str(CATALOG_FIXTURE),
        db_path=db_path,
        skip_enrich=True,
    )
    assert summary.doc_id == "fixture-doc"
    assert summary.n_compounds >= 2
    assert summary.n_with_activities >= 1

    with ChemistryStore(db_path) as store:
        stats = store.get_document_stats("fixture-doc")
        assert stats["compounds"] == summary.n_compounds
        rows = store.fetch_compounds_for_doc("fixture-doc")
        assert any(r["compound_label"] == "I-1" for r in rows)
        assert any(r["activities_json"] and r["activities_json"] != "[]" for r in rows)


def test_ingest_with_mock_enrich(db_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from uniparser_agent.chemistry import enrich as enrich_mod

    def fake_chat(system_prompt: str, user_content: str) -> str:
        payload = json.loads(user_content)
        return json.dumps(
            {
                "compounds": [
                    {
                        "compound_label": c["label"],
                        "name": c.get("name") or "",
                        "role": "claimed_compound",
                        "semantic_summary": f"Summary for {c['label']}.",
                        "activities": [],
                        "confidence": 0.8,
                    }
                    for c in payload["compounds"]
                ]
            },
            ensure_ascii=False,
        )

    original = enrich_mod.enrich_compounds

    def wrapped(doc_id, compounds, **kwargs):
        kwargs["chat_fn"] = fake_chat
        kwargs["skip_enrich"] = False
        return original(doc_id, compounds, **kwargs)

    monkeypatch.setattr(enrich_mod, "enrich_compounds", wrapped)
    # Also patch pipeline import
    import uniparser_agent.chemistry.pipeline as pipe

    monkeypatch.setattr(pipe, "enrich_compounds", wrapped)

    jobspec = JobSpec.from_profile("molecules_only", db_path=db_path)
    summary = ingest_pages_tree(
        CATALOG_FIXTURE,
        jobspec=jobspec,
        doc_id="enriched-doc",
        source=str(CATALOG_FIXTURE),
        db_path=db_path,
        skip_enrich=False,
    )
    assert summary.n_enriched >= 1
    with ChemistryStore(db_path) as store:
        rows = store.fetch_compounds_for_doc("enriched-doc")
        assert any(r["semantic_summary"] for r in rows)


def test_export_csv_two_tables(db_path: Path, tmp_path: Path) -> None:
    jobspec = JobSpec.from_profile("molecules_only", db_path=db_path)
    ingest_pages_tree(
        CATALOG_FIXTURE,
        jobspec=jobspec,
        doc_id="fixture-doc",
        source=str(CATALOG_FIXTURE),
        db_path=db_path,
        skip_enrich=True,
    )
    with ChemistryStore(db_path) as store:
        paths = export_doc_csv(store, "fixture-doc", tmp_path / "out")
        lib = export_library_csv(store, tmp_path / "library")
    assert Path(paths["compounds"]).exists()
    assert Path(paths["documents"]).exists()
    assert "extractions" not in paths
    assert "reactions" not in paths
    assert Path(lib["documents"]).exists()
    assert Path(lib["compounds"]).exists()
    assert set(lib.keys()) == {"documents", "compounds"}


def test_reingest_replaces_compounds(db_path: Path) -> None:
    jobspec = JobSpec.from_profile("molecules_only", db_path=db_path)
    ingest_pages_tree(
        CATALOG_FIXTURE,
        jobspec=jobspec,
        doc_id="fixture-doc",
        db_path=db_path,
        skip_enrich=True,
    )
    ingest_pages_tree(
        CATALOG_FIXTURE,
        jobspec=jobspec,
        doc_id="fixture-doc",
        db_path=db_path,
        skip_enrich=True,
    )
    with ChemistryStore(db_path) as store:
        rows = store.fetch_compounds_for_doc("fixture-doc")
        # No duplicates from re-ingest
        labels = [r["compound_label"] for r in rows if r["compound_label"]]
        assert labels.count("I-1") == 1
