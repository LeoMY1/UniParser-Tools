from __future__ import annotations

from pathlib import Path

import pytest

from uniparser_agent.chemistry.export_csv import export_doc_csv, export_library_csv
from uniparser_agent.chemistry.jobspec import JobSpec
from uniparser_agent.chemistry.pipeline import ingest_pages_tree
from uniparser_agent.chemistry.store import ChemistryStore


FIXTURE = Path(__file__).parent / "fixtures" / "minimal_pages_tree.json"
CATALOG_FIXTURE = Path(__file__).parent / "fixtures" / "chemistry_catalog_pages_tree.json"


@pytest.fixture()
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "test.db"


def test_ingest_compounds(db_path: Path, tmp_path: Path) -> None:
    jobspec = JobSpec(db_path=db_path)
    structure_dir = tmp_path / "structure"
    summary = ingest_pages_tree(
        CATALOG_FIXTURE,
        jobspec=jobspec,
        doc_id="fixture-doc",
        source=str(CATALOG_FIXTURE),
        db_path=db_path,
        patent_output_dir=structure_dir,
        skip_enrich=True,
    )
    assert summary.doc_id == "fixture-doc"
    assert summary.n_compounds >= 2
    assert Path(summary.patent_structure_path) == structure_dir / "patent_structure.json"
    assert Path(summary.patent_structure_path).exists()
    assert Path(summary.patent_basic_info_path) == structure_dir / "patent_basic_info.json"
    assert Path(summary.patent_basic_info_path).exists()
    assert Path(summary.general_formula_analysis_path) == structure_dir / "general_formula_analysis.json"
    assert Path(summary.general_formula_analysis_path).exists()
    assert Path(summary.general_formula_excel_path) == structure_dir / "general_formula_analysis.xlsx"
    assert Path(summary.general_formula_excel_path).exists()
    with ChemistryStore(db_path) as store:
        stats = store.get_document_stats("fixture-doc")
        assert stats["compounds"] == summary.n_compounds


def test_export_csv(db_path: Path, tmp_path: Path) -> None:
    jobspec = JobSpec(db_path=db_path)
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
    assert Path(paths["compounds"]).exists()
    assert Path(paths["documents"]).exists()
    assert "reactions" not in paths


def test_export_library_csv(db_path: Path, tmp_path: Path) -> None:
    jobspec = JobSpec(db_path=db_path)
    for doc_id in ("doc-a", "doc-b"):
        ingest_pages_tree(
            CATALOG_FIXTURE,
            jobspec=jobspec,
            doc_id=doc_id,
            source=str(CATALOG_FIXTURE),
            db_path=db_path,
            skip_enrich=True,
        )
    with ChemistryStore(db_path) as store:
        stats = store.get_library_stats()
        assert stats["documents"] == 2
        expected_compounds = stats["compounds"]
        paths = export_library_csv(store, tmp_path / "library")

    assert Path(paths["documents"]).exists()
    assert Path(paths["compounds"]).exists()
    assert set(paths.keys()) == {"documents", "compounds"}

    import csv

    with (tmp_path / "library" / "compounds.csv").open(encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    assert len(rows) == expected_compounds
    assert {"doc_id", "role", "semantic_summary", "activities_json", "enrich_json"} <= set(rows[0])
    # Full-library export preserves the document-level row from each document.
    ethanol = [r for r in rows if r.get("canonical_smiles") == "CCO" or r.get("smi") == "CCO"]
    assert len(ethanol) == 2
    assert {r["doc_id"] for r in ethanol} == {"doc-a", "doc-b"}
