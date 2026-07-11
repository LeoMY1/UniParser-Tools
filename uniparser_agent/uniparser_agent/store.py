from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from uniparser_agent.config import default_db_path
from uniparser_agent.extract import MoleculeExtraction, ReactionExtraction
from uniparser_agent.jobspec import IngestModule, JobSpec
from uniparser_agent.validate import (
    build_markush_record,
    is_markush_structure,
    validate_smiles,
)


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
    canonical_smiles TEXT NOT NULL,
    inchikey TEXT NOT NULL UNIQUE,
    validation_status TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS markush_scaffolds (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    scaffold_smi TEXT NOT NULL,
    caption TEXT NOT NULL,
    content_hash TEXT NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS extraction_records (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    doc_id TEXT NOT NULL,
    smi TEXT,
    caption TEXT,
    markush INTEGER NOT NULL,
    page INTEGER,
    block INTEGER,
    bbox_json TEXT,
    score REAL,
    validation_status TEXT NOT NULL,
    compound_id INTEGER,
    markush_id INTEGER,
    FOREIGN KEY (doc_id) REFERENCES documents(doc_id),
    FOREIGN KEY (compound_id) REFERENCES compounds(id),
    FOREIGN KEY (markush_id) REFERENCES markush_scaffolds(id)
);

CREATE TABLE IF NOT EXISTS reactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    doc_id TEXT NOT NULL,
    page INTEGER,
    block INTEGER,
    bbox_json TEXT,
    reactants TEXT NOT NULL,
    products TEXT NOT NULL,
    conditions TEXT NOT NULL,
    reactant_compound_ids_json TEXT,
    product_compound_ids_json TEXT,
    FOREIGN KEY (doc_id) REFERENCES documents(doc_id)
);
"""


@dataclass
class IngestSummary:
    doc_id: str
    n_extractions: int = 0
    n_unique_compounds: int = 0
    n_markush: int = 0
    n_invalid: int = 0
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

    def _get_compound_id(self, inchikey: str) -> int:
        row = self._conn.execute(
            "SELECT id FROM compounds WHERE inchikey = ?",
            (inchikey,),
        ).fetchone()
        if row:
            return int(row["id"])
        raise KeyError(inchikey)

    def _upsert_compound(self, canonical_smiles: str, inchikey: str, validation_status: str) -> int:
        self._conn.execute(
            """
            INSERT INTO compounds (canonical_smiles, inchikey, validation_status)
            VALUES (?, ?, ?)
            ON CONFLICT(inchikey) DO UPDATE SET
                canonical_smiles=excluded.canonical_smiles,
                validation_status=excluded.validation_status
            """,
            (canonical_smiles, inchikey, validation_status),
        )
        self._conn.commit()
        return self._get_compound_id(inchikey)

    def _upsert_markush(self, scaffold_smi: str, caption: str, content_hash: str) -> int:
        self._conn.execute(
            """
            INSERT INTO markush_scaffolds (scaffold_smi, caption, content_hash)
            VALUES (?, ?, ?)
            ON CONFLICT(content_hash) DO UPDATE SET
                scaffold_smi=excluded.scaffold_smi,
                caption=excluded.caption
            """,
            (scaffold_smi, caption, content_hash),
        )
        self._conn.commit()
        row = self._conn.execute(
            "SELECT id FROM markush_scaffolds WHERE content_hash = ?",
            (content_hash,),
        ).fetchone()
        return int(row["id"])

    def ingest(
        self,
        *,
        doc_id: str,
        source: str,
        pages_tree_path: str,
        markdown_path: str | None,
        output_dir: str | None,
        token: str,
        jobspec: JobSpec,
        molecules: list[MoleculeExtraction],
        reactions: list[ReactionExtraction],
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

        summary = IngestSummary(doc_id=doc_id)
        inchikey_cache: dict[str, int] = {}

        def compound_id_for_text(text: str) -> int | None:
            record = validate_smiles(text)
            if not record:
                return None
            key = record.inchikey
            if key in inchikey_cache:
                return inchikey_cache[key]
            row = self._conn.execute(
                "SELECT id FROM compounds WHERE inchikey = ?",
                (key,),
            ).fetchone()
            if row:
                cid = int(row["id"])
                inchikey_cache[key] = cid
                return cid
            if jobspec.has_module(IngestModule.COMPOUNDS):
                cid = self._upsert_compound(
                    record.canonical_smiles,
                    record.inchikey,
                    record.validation_status,
                )
                inchikey_cache[key] = cid
                return cid
            return None

        for mol in molecules:
            summary.n_extractions += 1
            validation_status = "invalid"
            compound_id = None
            markush_id = None

            if is_markush_structure(mol.smi, mol.caption, mol.markush):
                validation_status = "markush"
                if jobspec.has_module(IngestModule.MARKUSH):
                    record = build_markush_record(mol.smi, mol.caption)
                    markush_id = self._upsert_markush(
                        record.scaffold_smi,
                        record.caption,
                        record.content_hash,
                    )
                    summary.n_markush += 1
            else:
                record = validate_smiles(mol.smi)
                if record:
                    validation_status = "valid"
                    if jobspec.has_module(IngestModule.COMPOUNDS):
                        compound_id = self._upsert_compound(
                            record.canonical_smiles,
                            record.inchikey,
                            record.validation_status,
                        )
                        inchikey_cache[record.inchikey] = compound_id
                else:
                    summary.n_invalid += 1

            if jobspec.has_module(IngestModule.COMPOUNDS) or jobspec.has_module(IngestModule.MARKUSH):
                self._conn.execute(
                    """
                    INSERT INTO extraction_records (
                        doc_id, smi, caption, markush, page, block, bbox_json, score,
                        validation_status, compound_id, markush_id
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        doc_id,
                        mol.smi,
                        mol.caption,
                        int(mol.markush),
                        mol.page,
                        mol.block,
                        json.dumps(mol.bbox) if mol.bbox else None,
                        mol.score,
                        validation_status,
                        compound_id,
                        markush_id,
                    ),
                )

        if jobspec.has_module(IngestModule.REACTIONS):
            for rxn in reactions:
                reactant_ids = [cid for t in rxn.reactant_texts if (cid := compound_id_for_text(t))]
                product_ids = [cid for t in rxn.product_texts if (cid := compound_id_for_text(t))]
                self._conn.execute(
                    """
                    INSERT INTO reactions (
                        doc_id, page, block, bbox_json, reactants, products, conditions,
                        reactant_compound_ids_json, product_compound_ids_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        doc_id,
                        rxn.page,
                        rxn.block,
                        json.dumps(rxn.bbox) if rxn.bbox else None,
                        rxn.reactants,
                        rxn.products,
                        rxn.conditions,
                        json.dumps(reactant_ids),
                        json.dumps(product_ids),
                    ),
                )
                summary.n_reactions += 1

        self._conn.commit()
        summary.n_unique_compounds = int(
            self._conn.execute(
                """
                SELECT COUNT(DISTINCT compound_id) FROM extraction_records
                WHERE doc_id = ? AND compound_id IS NOT NULL
                """,
                (doc_id,),
            ).fetchone()[0]
        )
        return summary

    def get_document_stats(self, doc_id: str) -> dict[str, Any]:
        doc = self._conn.execute("SELECT * FROM documents WHERE doc_id = ?", (doc_id,)).fetchone()
        if not doc:
            raise KeyError(f"Document not found: {doc_id}")
        return {
            "doc_id": doc_id,
            "source": doc["source"],
            "parsed_at": doc["parsed_at"],
            "pages_tree_path": doc["pages_tree_path"],
            "extractions": self._conn.execute(
                "SELECT COUNT(*) FROM extraction_records WHERE doc_id = ?",
                (doc_id,),
            ).fetchone()[0],
            "unique_compounds": self._conn.execute(
                """
                SELECT COUNT(DISTINCT compound_id) FROM extraction_records
                WHERE doc_id = ? AND compound_id IS NOT NULL
                """,
                (doc_id,),
            ).fetchone()[0],
            "invalid": self._conn.execute(
                """
                SELECT COUNT(*) FROM extraction_records
                WHERE doc_id = ? AND validation_status = 'invalid'
                """,
                (doc_id,),
            ).fetchone()[0],
            "markush": self._conn.execute(
                """
                SELECT COUNT(*) FROM extraction_records
                WHERE doc_id = ? AND validation_status = 'markush'
                """,
                (doc_id,),
            ).fetchone()[0],
            "reactions": self._conn.execute(
                "SELECT COUNT(*) FROM reactions WHERE doc_id = ?",
                (doc_id,),
            ).fetchone()[0],
        }

    def fetch_compounds_for_doc(self, doc_id: str) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            """
            SELECT DISTINCT c.*
            FROM compounds c
            JOIN extraction_records e ON e.compound_id = c.id
            WHERE e.doc_id = ?
            ORDER BY c.id
            """,
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
            "markush_scaffolds": self._conn.execute("SELECT COUNT(*) FROM markush_scaffolds").fetchone()[0],
            "extractions": self._conn.execute("SELECT COUNT(*) FROM extraction_records").fetchone()[0],
            "reactions": self._conn.execute("SELECT COUNT(*) FROM reactions").fetchone()[0],
        }

    def fetch_library_compounds(self) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            """
            SELECT
                c.id,
                c.canonical_smiles,
                c.inchikey,
                c.validation_status,
                COUNT(DISTINCT e.doc_id) AS doc_count,
                GROUP_CONCAT(DISTINCT e.doc_id) AS doc_ids
            FROM compounds c
            LEFT JOIN extraction_records e ON e.compound_id = c.id
            GROUP BY c.id
            ORDER BY c.id
            """
        ).fetchall()
        return [dict(row) for row in rows]

    def fetch_library_markush(self) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            """
            SELECT
                m.id,
                m.scaffold_smi,
                m.caption,
                m.content_hash,
                COUNT(DISTINCT e.doc_id) AS doc_count,
                GROUP_CONCAT(DISTINCT e.doc_id) AS doc_ids
            FROM markush_scaffolds m
            LEFT JOIN extraction_records e ON e.markush_id = m.id
            GROUP BY m.id
            ORDER BY m.id
            """
        ).fetchall()
        return [dict(row) for row in rows]

    def fetch_table(self, table: str, doc_id: str | None = None) -> list[dict[str, Any]]:
        allowed = {
            "compounds",
            "markush_scaffolds",
            "extraction_records",
            "reactions",
            "documents",
        }
        if table not in allowed:
            raise ValueError(f"Unknown table: {table}")
        if doc_id and table in {"extraction_records", "reactions"}:
            rows = self._conn.execute(f"SELECT * FROM {table} WHERE doc_id = ?", (doc_id,)).fetchall()
        elif doc_id and table == "documents":
            rows = self._conn.execute(f"SELECT * FROM {table} WHERE doc_id = ?", (doc_id,)).fetchall()
        else:
            rows = self._conn.execute(f"SELECT * FROM {table}").fetchall()
        return [dict(row) for row in rows]
