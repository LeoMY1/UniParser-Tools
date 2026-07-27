from __future__ import annotations

import json
from pathlib import Path

import pytest

from uniparser_agent.chemistry.bioactivity import (
    attach_bioactivity_records,
    extract_bioactivity_via_llm,
)
from uniparser_agent.chemistry.enrich import (
    enrich_compounds,
    merge_enrichment,
    parse_enrich_response,
)
from uniparser_agent.chemistry.export_csv import export_doc_csv, export_library_csv
from uniparser_agent.chemistry.extract import extract_from_pages_tree
from uniparser_agent.chemistry.jobspec import JobSpec
from uniparser_agent.chemistry.join import LogicalCompound, build_logical_compounds
from uniparser_agent.chemistry.link_evidence import merge_links, parse_link_response
from uniparser_agent.chemistry.patent_chunks import (
    build_patent_chunks,
    pack_patent_chunks,
)
from uniparser_agent.chemistry.pipeline import ingest_pages_tree
from uniparser_agent.chemistry.store import ChemistryStore
from uniparser_agent.chemistry.text_units import TextUnit, build_text_units
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
    assert not i1.activity_rows


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


def test_build_logical_compounds_leaves_local_context_empty() -> None:
    doc = json.loads(CATALOG_FIXTURE.read_text(encoding="utf-8"))
    compounds = build_logical_compounds(doc, "fixture-catalog")
    assert compounds
    assert all(c.local_context == "" for c in compounds)


def test_build_text_units_excludes_image() -> None:
    doc = {
        "pages_tree": [
            [
                {
                    "type": "paragraph",
                    "page": 1,
                    "block": 1,
                    "text": "实施例1制备I-1，收率80%。",
                },
                {
                    "type": "image",
                    "page": 1,
                    "block": 2,
                    "source": "data:image/png;base64," + ("A" * 300),
                    "items": [
                        {
                            "type": "figuregroup",
                            "page": 1,
                            "block": 20,
                            "items": [
                                {
                                    "type": "moleculegroup",
                                    "page": 1,
                                    "block": 21,
                                    "items": [
                                        {
                                            "type": "molecule",
                                            "page": 1,
                                            "block": 21,
                                            "smi": "c1ccccc1",
                                        },
                                        {
                                            "type": "moleculeid",
                                            "page": 1,
                                            "block": 22,
                                            "text": "(IA)",
                                        },
                                    ],
                                }
                            ],
                        }
                    ],
                },
                {
                    "type": "table",
                    "page": 1,
                    "block": 3,
                    "structure": "<table><tr><td>I-1</td><td>乙醇</td></tr></table>",
                },
                {
                    "type": "moleculegroup",
                    "page": 1,
                    "block": 4,
                    "items": [
                        {"type": "molecule", "page": 1, "block": 4, "smi": "CCO"},
                        {"type": "moleculeid", "page": 1, "block": 5, "text": "(I-1)"},
                        {
                            "type": "image",
                            "page": 1,
                            "block": 6,
                            "source": "data:image/png;base64," + ("B" * 300),
                        },
                    ],
                },
            ]
        ]
    }
    units = build_text_units(doc)
    assert units
    assert all(u.type != "image" for u in units)
    assert any(u.type == "paragraph" for u in units)
    assert any(u.type == "table" and "I-1" in u.text for u in units)
    assert any(u.type == "moleculegroup" and "CCO" in u.text for u in units)
    assert any(u.type == "moleculegroup" and "IA" in u.text for u in units)
    assert not any("data:image" in u.text for u in units)


def test_patent_chunks_keep_examples_claims_assays_separate() -> None:
    units = [
        TextUnit("u1", 1, 1, "title", "具体实施方式", 0),
        TextUnit("u2", 1, 2, "title", "实施例1", 1),
        TextUnit("u3", 1, 3, "paragraph", "反应2小时。", 2),
        TextUnit("u4", 1, 4, "paragraph", "1H NMR: 1.2 ppm。", 3),
        TextUnit("u5", 1, 5, "paragraph", "收率83%。", 4),
        TextUnit("u6", 2, 1, "title", "实施例2", 5),
        TextUnit("u7", 2, 2, "paragraph", "方法同实施例1，更换试剂。", 6),
        TextUnit("u8", 3, 1, "title", "权利要求", 7),
        TextUnit("u9", 3, 2, "paragraph", "1. 一种式I化合物。", 8),
        TextUnit("u10", 4, 1, "paragraph", "活性测定结果如下。", 9),
        TextUnit("u11", 4, 2, "table", "化合物\tIC50\nI-1\t0.3", 10),
    ]
    chunks = build_patent_chunks(units)
    example1 = next(c for c in chunks if c.example_no == "1")
    example2 = next(c for c in chunks if c.example_no == "2")
    assert example1.unit_ids == ["u2", "u3", "u4", "u5"]
    assert example2.references == ["example:1"]
    assert any(c.section_type == "claim" and c.claim_no == "1" for c in chunks)
    assert any(c.section_type == "assay" and "u11" in c.unit_ids for c in chunks)

    batches = pack_patent_chunks(chunks, max_chars=200)
    assert all(len({chunk.section_type for chunk in batch}) == 1 for batch in batches)
    assert {unit.unit_id for batch in batches for chunk in batch for unit in chunk.units} == {
        unit.unit_id for unit in units
    }

    large_table_units = [
        TextUnit("a1", 1, 1, "paragraph", "活性测定", 0),
        TextUnit(
            "a2",
            1,
            2,
            "table",
            "compound\tIC50\nunit\tμM\n" + "\n".join(f"I-{i}\t{i}.0" for i in range(20)),
            1,
        ),
    ]
    table_batches = pack_patent_chunks(
        build_patent_chunks(large_table_units),
        max_chars=110,
    )
    table_parts = [
        chunk
        for batch in table_batches
        for chunk in batch
        if chunk.parent_chunk_id and chunk.units[0].type == "table"
    ]
    assert len(table_parts) > 1
    assert all(part.units[0].text.startswith("compound\tIC50\nunit\tμM") for part in table_parts)


def test_merge_links_prioritizes_fact_and_records_budget_drops() -> None:
    compound = LogicalCompound(compound_id="I-1", label="I-1", smi="CCO")
    units = [
        TextUnit("spectra", 1, 1, "paragraph", "1H NMR " + ("1.23, " * 80), 0),
        TextUnit("yield", 1, 2, "paragraph", "I-1 收率83%。", 1),
        TextUnit("identity", 1, 3, "molecule", "label=I-1; smi=CCO", 2),
    ]
    merge_links(
        [compound],
        units,
        [
            {"unit_id": "spectra", "molecule_ids": ["I-1"], "relation": "characterization"},
            {"unit_id": "yield", "molecule_ids": ["I-1"], "relation": "synthesis"},
            {"unit_id": "identity", "molecule_ids": ["I-1"], "relation": "identity"},
        ],
        max_chars=45,
    )
    assert "收率83%" in compound.local_context
    assert compound.enrich_json["linked_unit_ids"] == ["spectra", "yield", "identity"]
    assert {item["unit_id"] for item in compound.enrich_json["dropped_unit_ids"]} == {
        "spectra"
    }


def test_bioactivity_extracts_each_endpoint_and_attaches_by_example() -> None:
    doc = {
        "pages_tree": [[
            {
                "type": "paragraph",
                "page": 1,
                "block": 1,
                "text": "细胞活性测定，固定浓度10 μM。",
            },
            {
                "type": "table",
                "page": 1,
                "block": 2,
                "structure": (
                    "<table><tr><th>实施例</th><th>IC50 μM</th>"
                    "<th>抑制率 %</th><th>FEP predicted</th></tr>"
                    "<tr><td>1</td><td>0.31 ± 0.03</td>"
                    "<td>&gt;80</td><td>-9.2</td></tr></table>"
                ),
            },
        ]]
    }

    def fake_chat(_system: str, user: str) -> str:
        row = json.loads(user)["activity_table"]["rows"][1]
        return json.dumps(
            {
                "table_has_assay_data": True,
                "source_table_id": "p1_b2",
                "readouts": [
                    {
                        "compound_label": "1",
                        "assay_name": "IC50 μM",
                        "readout_type": "IC50",
                        "value": "0.31",
                        "unit": "μM",
                        "conditions": "mean ± SD",
                        "source_row": row["source_row"],
                        "evidence": row["text"],
                    },
                    {
                        "compound_label": "1",
                        "assay_name": "抑制率 %",
                        "readout_type": "%inhibition",
                        "value": "80",
                        "unit": "%",
                        "conditions": ">",
                        "source_row": row["source_row"],
                        "evidence": row["text"],
                    },
                ],
            },
            ensure_ascii=False,
        )

    records = extract_bioactivity_via_llm(doc, chat_fn=fake_chat)
    assert [record["readout_type"] for record in records] == ["IC50", "%inhibition"]
    compounds = [LogicalCompound(compound_id="I-1", label="I-1", smi="CCO")]
    attach_bioactivity_records(compounds, records)
    assert len(compounds[0].activities_json) == 2
    assert {item["source_table_id"] for item in compounds[0].activities_json} == {"p1_b2"}


def test_unlabeled_exact_smiles_merges_but_distinct_structure_remains() -> None:
    doc = {
        "pages_tree": [[
            {
                "type": "moleculegroup",
                "page": 1,
                "block": 1,
                "items": [
                    {"type": "molecule", "page": 1, "block": 1, "smi": "CCO"},
                    {"type": "moleculeid", "page": 1, "block": 2, "text": "(I-1)"},
                ],
            },
            {
                "type": "molecule",
                "page": 2,
                "block": 1,
                "smi": "CCO",
                # Parser flags can be noisy; exact match to a concrete labeled
                # structure must still merge.
                "markush": True,
            },
            {"type": "molecule", "page": 2, "block": 2, "smi": "CCN"},
        ]]
    }
    compounds = build_logical_compounds(doc, "duplicates")
    assert len([c for c in compounds if c.smi == "CCO"]) == 1
    assert next(c for c in compounds if c.smi == "CCO").label == "I-1"
    assert len([c for c in compounds if c.smi == "CCN"]) == 1


def test_summary_rejects_unsupported_measurement_and_persists_uncertainty() -> None:
    compound = LogicalCompound(
        compound_id="I-1",
        label="I-1",
        smi="CCO",
        local_context="I-1 was isolated and characterized.",
    )
    merge_enrichment(
        [compound],
        [
            {
                "compound_label": "I-1",
                "role": "example_product",
                "semantic_summary": "I-1 was obtained in 83% yield.",
                "evidence_quotes": ["not in context"],
                "uncertainties": ["SMILES conflicts with the textual identity."],
                "confidence": 0.9,
            }
        ],
    )
    assert "83%" not in compound.semantic_summary
    assert "an unverified condition" in compound.semantic_summary
    assert compound.enrich_json["status"] == "ok_with_validation"
    assert compound.enrich_json["structure_text_conflict"] is True
    assert compound.enrich_json["invalid_evidence_quote_count"] == 1


def test_link_then_summarize_with_fake_chat() -> None:
    doc = json.loads(CATALOG_FIXTURE.read_text(encoding="utf-8"))
    compounds = build_logical_compounds(doc, "fixture-catalog")
    units = build_text_units(doc)
    para = next(u for u in units if u.type == "paragraph")

    def fake_chat(system_prompt: str, user_content: str) -> str:
        payload = json.loads(user_content)
        if "activity_table" in payload:
            table = payload["activity_table"]
            if table["source_table_id"] != "p2_b4":
                return '{"table_has_assay_data":false,"readouts":[]}'
            row = table["rows"][1]
            return json.dumps(
                {
                    "table_has_assay_data": True,
                    "source_table_id": "p2_b4",
                    "readouts": [
                        {
                            "compound_label": "1",
                            "assay_name": "NAD(P)H IC50",
                            "target": "NQO1",
                            "readout_type": "IC50",
                            "value": "0.31",
                            "unit": "μM",
                            "conditions": "mean ± SD",
                            "source_row": row["source_row"],
                            "evidence": row["text"],
                        },
                        {
                            "compound_label": "2",
                            "assay_name": "NAD(P)H IC50",
                            "target": "NQO1",
                            "readout_type": "IC50",
                            "value": "0.50",
                            "unit": "μM",
                            "conditions": "mean ± SD",
                            "source_row": row["source_row"],
                            "evidence": row["text"],
                        },
                    ],
                },
                ensure_ascii=False,
            )
        if "chunks" in payload:
            return json.dumps(
                {
                    "links": [
                        {
                            "unit_id": para.unit_id,
                            "molecule_ids": ["I-1"],
                            "relation": "synthesis",
                        }
                    ]
                },
                ensure_ascii=False,
            )
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
                    "evidence_quotes": [para.text] if card["label"] == "I-1" else [],
                    "uncertainties": [],
                    "structure_text_conflict": False,
                    "confidence": 0.9,
                }
            )
        return json.dumps({"compounds": items}, ensure_ascii=False)

    enriched = enrich_compounds(
        "fixture-catalog",
        compounds,
        pages_tree_doc=doc,
        chat_fn=fake_chat,
        skip_enrich=False,
    )
    i1 = next(c for c in enriched if c.label == "I-1")
    assert "实施例1" in i1.local_context or "I-1" in i1.local_context
    assert i1.enrich_json.get("evidence_unit_ids")
    assert i1.enrich_json.get("strategy") == "link_then_summarize"
    assert "example compound" in i1.semantic_summary
    assert i1.role == "example_product"
    assert i1.activities_json
    assert i1.activities_json[0]["activity_value"] == "0.31"
    assert i1.enrich_json.get("evidence_quotes")


def test_merge_links_drops_whole_units_over_budget() -> None:
    compounds = build_logical_compounds(
        json.loads(CATALOG_FIXTURE.read_text(encoding="utf-8")),
        "fixture-catalog",
    )
    i1 = next(c for c in compounds if c.label == "I-1")
    units = [
        TextUnit(unit_id="p1_b1", page=1, block=1, type="paragraph", text="AAAA"),
        TextUnit(unit_id="p1_b2", page=1, block=2, type="paragraph", text="BBBB"),
        TextUnit(unit_id="p1_b3", page=1, block=3, type="paragraph", text="CCCC"),
    ]
    merge_links(
        [i1],
        units,
        [
            {"unit_id": "p1_b1", "molecule_ids": ["I-1"]},
            {"unit_id": "p1_b2", "molecule_ids": ["I-1"]},
            {"unit_id": "p1_b3", "molecule_ids": ["I-1"]},
        ],
        max_chars=10,
    )
    assert i1.local_context == "AAAA\nBBBB"
    assert i1.enrich_json["evidence_unit_ids"] == ["p1_b1", "p1_b2"]
    assert "CCCC" not in i1.local_context


def test_parse_link_response() -> None:
    raw = '{"links":[{"unit_id":"p1_b1","molecule_ids":["I-1"],"relation":"synthesis"}]}'
    items = parse_link_response(raw)
    assert items[0]["unit_id"] == "p1_b1"


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
    assert not i1.activities_json


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
    assert summary.n_with_activities == 0

    with ChemistryStore(db_path) as store:
        stats = store.get_document_stats("fixture-doc")
        assert stats["compounds"] == summary.n_compounds
        rows = store.fetch_compounds_for_doc("fixture-doc")
        assert any(r["compound_label"] == "I-1" for r in rows)
        assert all(not r["activities_json"] or r["activities_json"] == "[]" for r in rows)


def test_ingest_with_mock_enrich(db_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from uniparser_agent.chemistry import enrich as enrich_mod

    def fake_chat(system_prompt: str, user_content: str) -> str:
        payload = json.loads(user_content)
        if "activity_table" in payload:
            return '{"table_has_assay_data":false,"readouts":[]}'
        if "chunks" in payload:
            links = []
            for chunk in payload.get("chunks") or []:
                for u in chunk.get("units") or []:
                    if not isinstance(u, dict):
                        continue
                    text = str(u.get("text") or "")
                    mol_ids = []
                    for m in payload.get("molecules") or []:
                        if not isinstance(m, dict):
                            continue
                        lab = str(m.get("label") or m.get("compound_id") or "")
                        if lab and lab in text:
                            mol_ids.append(lab)
                    if mol_ids:
                        links.append(
                            {
                                "unit_id": u["unit_id"],
                                "molecule_ids": mol_ids,
                                "relation": "synthesis",
                            }
                        )
            return json.dumps({"links": links}, ensure_ascii=False)
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
