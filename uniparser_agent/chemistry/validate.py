from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Literal

from rdkit import Chem
from rdkit.Chem import inchi


ValidationStatus = Literal["valid", "invalid", "markush"]


@dataclass
class CompoundRecord:
    canonical_smiles: str
    inchikey: str
    validation_status: ValidationStatus = "valid"


@dataclass
class MarkushRecord:
    scaffold_smi: str
    caption: str
    content_hash: str


def is_markush_structure(smi: str, caption: str, markush_flag: bool) -> bool:
    if markush_flag:
        return True
    if "*" in smi or "*" in caption:
        return True
    return bool(re.search(r"<a>\d*:[R\[]", caption))


def validate_smiles(raw_smi: str) -> CompoundRecord | None:
    smi = (raw_smi or "").strip()
    if not smi or "*" in smi:
        return None
    mol = Chem.MolFromSmiles(smi)
    if mol is None:
        return None
    canonical = Chem.MolToSmiles(mol, canonical=True)
    try:
        inchikey = inchi.MolToInchiKey(mol)
    except Exception:
        return None
    if not inchikey:
        return None
    return CompoundRecord(canonical_smiles=canonical, inchikey=inchikey, validation_status="valid")


def markush_hash(scaffold_smi: str, caption: str) -> str:
    scaffold = (scaffold_smi or "").strip()
    cap = (caption or "").strip()
    payload = f"{scaffold}\n{cap}".encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def build_markush_record(scaffold_smi: str, caption: str) -> MarkushRecord:
    scaffold = (scaffold_smi or "").strip() or (caption or "").strip()
    cap = (caption or "").strip()
    return MarkushRecord(
        scaffold_smi=scaffold,
        caption=cap,
        content_hash=markush_hash(scaffold, cap),
    )


def try_resolve_text_to_inchikey(text: str) -> str | None:
    text = (text or "").strip()
    if not text or "*" in text:
        return None
    record = validate_smiles(text)
    return record.inchikey if record else None
