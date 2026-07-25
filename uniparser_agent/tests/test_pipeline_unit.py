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


def test_ingest_molecules_only_profile(db_path: Path) -> None:
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
    assert summary.n_reactions == 0

    with ChemistryStore(db_path) as store:
        stats = store.get_document_stats("fixture-doc")
        assert stats["compounds"] == summary.n_compounds
        assert stats["reactions"] == 0


def test_export_csv(db_path: Path, tmp_path: Path) -> None:
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
    assert Path(paths["compounds"]).exists()
    assert Path(paths["documents"]).exists()
    assert "reactions" not in paths


def test_export_library_csv(db_path: Path, tmp_path: Path) -> None:
    jobspec = JobSpec.from_profile("molecules_only", db_path=db_path)
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
        paths = export_library_csv(store, tmp_path / "library")

    assert Path(paths["documents"]).exists()
    assert Path(paths["compounds"]).exists()
    assert set(paths.keys()) == {"documents", "compounds"}

    import csv

    with (tmp_path / "library" / "compounds.csv").open(encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    assert len(rows) >= 2
    # I-1 / CCO should appear once in library dedupe with doc_count 2
    ethanol = [r for r in rows if r.get("canonical_smiles") == "CCO" or r.get("smi") == "CCO"]
    assert ethanol
    assert int(ethanol[0]["doc_count"]) == 2
