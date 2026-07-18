from __future__ import annotations

import json
from pathlib import Path

import pytest

from uniparser_agent.chemistry.export_csv import export_doc_csv, export_library_csv
from uniparser_agent.chemistry.jobspec import JobSpec
from uniparser_agent.chemistry.pipeline import ingest_pages_tree
from uniparser_agent.chemistry.store import ChemistryStore


FIXTURE = Path(__file__).parent / "fixtures" / "minimal_pages_tree.json"


@pytest.fixture()
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "test.db"


def test_ingest_scientific_paper_profile(db_path: Path) -> None:
    jobspec = JobSpec.from_profile("scientific-paper", db_path=db_path)
    summary = ingest_pages_tree(
        FIXTURE,
        jobspec=jobspec,
        doc_id="fixture-doc",
        source=str(FIXTURE),
        db_path=db_path,
    )
    assert summary.doc_id == "fixture-doc"
    assert summary.n_extractions == 3
    assert summary.n_unique_compounds == 1
    assert summary.n_markush == 1
    assert summary.n_invalid == 1
    assert summary.n_reactions == 1

    with ChemistryStore(db_path) as store:
        stats = store.get_document_stats("fixture-doc")
        assert stats["reactions"] == 1


def test_export_csv(db_path: Path, tmp_path: Path) -> None:
    jobspec = JobSpec.from_profile("scientific-paper", db_path=db_path)
    ingest_pages_tree(
        FIXTURE,
        jobspec=jobspec,
        doc_id="fixture-doc",
        source=str(FIXTURE),
        db_path=db_path,
    )
    with ChemistryStore(db_path) as store:
        paths = export_doc_csv(store, "fixture-doc", tmp_path / "out")
    assert Path(paths["extractions"]).exists()
    assert Path(paths["reactions"]).exists()
    assert Path(paths["compounds"]).exists()


def test_export_library_csv(db_path: Path, tmp_path: Path) -> None:
    jobspec = JobSpec.from_profile("scientific-paper", db_path=db_path)
    for doc_id in ("doc-a", "doc-b"):
        ingest_pages_tree(
            FIXTURE,
            jobspec=jobspec,
            doc_id=doc_id,
            source=str(FIXTURE),
            db_path=db_path,
        )
    with ChemistryStore(db_path) as store:
        stats = store.get_library_stats()
        assert stats["documents"] == 2
        paths = export_library_csv(store, tmp_path / "library")

    assert Path(paths["documents"]).exists()
    assert Path(paths["compounds"]).exists()
    assert Path(paths["markush_scaffolds"]).exists()
    assert Path(paths["extractions"]).exists()
    assert Path(paths["reactions"]).exists()

    import csv

    with (tmp_path / "library" / "compounds.csv").open(encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    assert len(rows) == 2
    by_smiles = {row["canonical_smiles"]: row for row in rows}
    assert int(by_smiles["CCO"]["doc_count"]) == 2
    assert "doc-a" in by_smiles["CCO"]["doc_ids"]
    assert "doc-b" in by_smiles["CCO"]["doc_ids"]
