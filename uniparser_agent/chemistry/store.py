from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from uniparser_agent.chemistry.config import default_db_path
from uniparser_agent.chemistry.join import LogicalCompound
from uniparser_agent.chemistry.jobspec import JobSpec
from uniparser_agent.chemistry.validate import is_markush_structure, validate_smiles


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS documents (
    doc_id TEXT PRIMARY KEY,
    source TEXT NOT NULL,
    pages_tree_path TEXT,
    markdown_path TEXT,
    output_dir TEXT,
    token TEXT,
    parsed_at TEXT NOT NULL,
    jobspec_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS compounds (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    doc_id TEXT NOT NULL,
    smi TEXT,
    canonical_smiles TEXT,
    inchikey TEXT,
    validation_status TEXT NOT NULL,
    markush INTEGER NOT NULL DEFAULT 0,
    compound_label TEXT,
    name TEXT,
    example_no TEXT,
    role TEXT,
    caption TEXT,
    page INTEGER,
    block INTEGER,
    score REAL,
    source_type TEXT,
    semantic_summary TEXT,
    activities_json TEXT NOT NULL DEFAULT '[]',
    enrich_json TEXT,
    FOREIGN KEY (doc_id) REFERENCES documents(doc_id)
);

CREATE INDEX IF NOT EXISTS idx_compounds_doc_id ON compounds(doc_id);
CREATE INDEX IF NOT EXISTS idx_compounds_label ON compounds(doc_id, compound_label);
"""


@dataclass
class IngestSummary:
    doc_id: str
    n_compounds: int = 0
    n_unique_compounds: int = 0
    n_markush: int = 0
    n_invalid: int = 0
    n_with_activities: int = 0
    n_enriched: int = 0
    # Backward-compatible aliases used by older CLI/tests
    n_extractions: int = 0
    n_reactions: int = 0


class ChemistryStore:
    def __init__(self, db_path: Path | None = None) -> None:
        self.db_path = (db_path or default_db_path()).expanduser().resolve()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.db_path)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(SCHEMA_SQL)
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> ChemistryStore:
        return self

    def __exit__(self, *args) -> None:
        self.close()

    def upsert_document(
        self,
        *,
        doc_id: str,
        source: str,
        pages_tree_path: str,
        markdown_path: str | None,
        output_dir: str | None,
        token: str,
        jobspec: JobSpec,
    ) -> None:
        self._conn.execute(
            """
            INSERT INTO documents (
                doc_id, source, pages_tree_path, markdown_path, output_dir, token, parsed_at, jobspec_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(doc_id) DO UPDATE SET
                source=excluded.source,
                pages_tree_path=excluded.pages_tree_path,
                markdown_path=excluded.markdown_path,
                output_dir=excluded.output_dir,
                token=excluded.token,
                parsed_at=excluded.parsed_at,
                jobspec_json=excluded.jobspec_json
            """,
            (
                doc_id,
                source,
                pages_tree_path,
                markdown_path,
                output_dir,
                token,
                datetime.now(timezone.utc).isoformat(),
                jobspec.to_json(),
            ),
        )
        self._conn.commit()

    def delete_compounds_for_doc(self, doc_id: str) -> None:
        self._conn.execute("DELETE FROM compounds WHERE doc_id = ?", (doc_id,))
        self._conn.commit()

    def ingest_compounds(
        self,
        *,
        doc_id: str,
        source: str,
        pages_tree_path: str,
        markdown_path: str | None,
        output_dir: str | None,
        token: str,
        jobspec: JobSpec,
        compounds: list[LogicalCompound],
    ) -> IngestSummary:
        self.upsert_document(
            doc_id=doc_id,
            source=source,
            pages_tree_path=pages_tree_path,
            markdown_path=markdown_path,
            output_dir=output_dir,
            token=token,
            jobspec=jobspec,
        )
        self.delete_compounds_for_doc(doc_id)

        summary = IngestSummary(doc_id=doc_id)
        for c in compounds:
            markush = bool(c.markush) or is_markush_structure(c.smi, c.caption, c.markush)
            canonical = None
            inchikey = None
            validation_status = "invalid"
            if markush:
                validation_status = "markush"
                summary.n_markush += 1
            else:
                record = validate_smiles(c.smi)
                if record:
                    validation_status = "valid"
                    canonical = record.canonical_smiles
                    inchikey = record.inchikey
                else:
                    summary.n_invalid += 1

            activities = c.activities_json or []
            if activities:
                summary.n_with_activities += 1
            if c.semantic_summary:
                summary.n_enriched += 1

            page = c.pages[0] if c.pages else None
            self._conn.execute(
                """
                INSERT INTO compounds (
                    doc_id, smi, canonical_smiles, inchikey, validation_status, markush,
                    compound_label, name, example_no, role, caption, page, block, score,
                    source_type, semantic_summary, activities_json, enrich_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    doc_id,
                    c.smi or None,
                    canonical,
                    inchikey,
                    validation_status,
                    int(markush),
                    c.label or c.compound_label or None,
                    c.name or None,
                    c.example_no or None,
                    c.role or None,
                    c.caption or None,
                    page,
                    c.block,
                    c.score,
                    c.source_type or None,
                    c.semantic_summary or None,
                    json.dumps(activities, ensure_ascii=False),
                    json.dumps(c.enrich_json, ensure_ascii=False) if c.enrich_json else None,
                ),
            )
            summary.n_compounds += 1

        self._conn.commit()
        summary.n_unique_compounds = summary.n_compounds
        summary.n_extractions = summary.n_compounds
        return summary

    # Compatibility shim for older call sites during transition
    def ingest(self, **kwargs: Any) -> IngestSummary:
        if "compounds" in kwargs:
            return self.ingest_compounds(**kwargs)
        raise TypeError("ChemistryStore.ingest now requires compounds=list[LogicalCompound]")

    def get_document_stats(self, doc_id: str) -> dict[str, Any]:
        doc = self._conn.execute("SELECT * FROM documents WHERE doc_id = ?", (doc_id,)).fetchone()
        if not doc:
            raise KeyError(f"Document not found: {doc_id}")
        n_compounds = self._conn.execute(
            "SELECT COUNT(*) FROM compounds WHERE doc_id = ?",
            (doc_id,),
        ).fetchone()[0]
        return {
            "doc_id": doc_id,
            "source": doc["source"],
            "parsed_at": doc["parsed_at"],
            "pages_tree_path": doc["pages_tree_path"],
            "compounds": n_compounds,
            "extractions": n_compounds,
            "unique_compounds": n_compounds,
            "invalid": self._conn.execute(
                "SELECT COUNT(*) FROM compounds WHERE doc_id = ? AND validation_status = 'invalid'",
                (doc_id,),
            ).fetchone()[0],
            "markush": self._conn.execute(
                "SELECT COUNT(*) FROM compounds WHERE doc_id = ? AND validation_status = 'markush'",
                (doc_id,),
            ).fetchone()[0],
            "with_activities": self._conn.execute(
                """
                SELECT COUNT(*) FROM compounds
                WHERE doc_id = ? AND activities_json IS NOT NULL AND activities_json != '[]'
                """,
                (doc_id,),
            ).fetchone()[0],
            "enriched": self._conn.execute(
                """
                SELECT COUNT(*) FROM compounds
                WHERE doc_id = ? AND semantic_summary IS NOT NULL AND semantic_summary != ''
                """,
                (doc_id,),
            ).fetchone()[0],
            "reactions": 0,
        }

    def fetch_compounds_for_doc(self, doc_id: str) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT * FROM compounds WHERE doc_id = ? ORDER BY id",
            (doc_id,),
        ).fetchall()
        return [dict(row) for row in rows]

    def list_doc_ids(self) -> list[str]:
        rows = self._conn.execute("SELECT doc_id FROM documents ORDER BY doc_id").fetchall()
        return [str(row["doc_id"]) for row in rows]

    def get_library_stats(self) -> dict[str, Any]:
        return {
            "documents": self._conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0],
            "compounds": self._conn.execute("SELECT COUNT(*) FROM compounds").fetchone()[0],
        }

    def fetch_library_compounds(self) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            """
            SELECT
                COALESCE(inchikey, compound_label, smi, CAST(id AS TEXT)) AS dedupe_key,
                MIN(id) AS id,
                MAX(canonical_smiles) AS canonical_smiles,
                MAX(inchikey) AS inchikey,
                MAX(smi) AS smi,
                MAX(compound_label) AS compound_label,
                MAX(name) AS name,
                MAX(validation_status) AS validation_status,
                COUNT(DISTINCT doc_id) AS doc_count,
                GROUP_CONCAT(DISTINCT doc_id) AS doc_ids
            FROM compounds
            GROUP BY COALESCE(inchikey, compound_label, smi, CAST(id AS TEXT))
            ORDER BY id
            """
        ).fetchall()
        return [dict(row) for row in rows]

    def fetch_table(self, table: str, doc_id: str | None = None) -> list[dict[str, Any]]:
        allowed = {"compounds", "documents"}
        if table not in allowed:
            raise ValueError(f"Unknown table: {table}. Allowed: {sorted(allowed)}")
        if doc_id:
            rows = self._conn.execute(f"SELECT * FROM {table} WHERE doc_id = ?", (doc_id,)).fetchall()
        else:
            rows = self._conn.execute(f"SELECT * FROM {table}").fetchall()
        return [dict(row) for row in rows]
