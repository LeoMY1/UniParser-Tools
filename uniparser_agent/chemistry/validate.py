from __future__ import annotations

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
