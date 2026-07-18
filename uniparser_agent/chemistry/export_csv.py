from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

from uniparser_agent.chemistry.store import ChemistryStore


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if rows:
        with path.open("w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
            writer.writeheader()
            writer.writerows(rows)
    else:
        path.write_text("", encoding="utf-8")


def export_doc_csv(store: ChemistryStore, doc_id: str, out_dir: Path) -> dict[str, str]:
    out_dir.mkdir(parents=True, exist_ok=True)
    paths: dict[str, str] = {}

    tables = {
        "extractions": "extraction_records",
        "reactions": "reactions",
        "compounds": "compounds",
    }
    for filename, table in tables.items():
        if table == "compounds":
            rows = store.fetch_compounds_for_doc(doc_id)
        else:
            rows = store.fetch_table(table, doc_id=doc_id)
        path = out_dir / f"{doc_id}_{filename}.csv"
        _write_csv(path, rows)
        paths[filename] = str(path)
    return paths


LIBRARY_EXPORTS: dict[str, str] = {
    "documents": "documents.csv",
    "compounds": "compounds.csv",
    "markush_scaffolds": "markush_scaffolds.csv",
    "extractions": "extractions.csv",
    "reactions": "reactions.csv",
}


def export_library_csv(store: ChemistryStore, out_dir: Path) -> dict[str, str]:
    """Export the full deduplicated library across all documents."""
    out_dir.mkdir(parents=True, exist_ok=True)
    paths: dict[str, str] = {}

    datasets = {
        "documents": store.fetch_table("documents"),
        "compounds": store.fetch_library_compounds(),
        "markush_scaffolds": store.fetch_library_markush(),
        "extractions": store.fetch_table("extraction_records"),
        "reactions": store.fetch_table("reactions"),
    }
    for name, filename in LIBRARY_EXPORTS.items():
        path = out_dir / filename
        _write_csv(path, datasets[name])
        paths[name] = str(path)
    return paths
