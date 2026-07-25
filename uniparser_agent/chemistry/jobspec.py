from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Literal


class IngestModule(str, Enum):
    COMPOUNDS = "compounds"
    MARKUSH = "markush"
    REACTIONS = "reactions"


class ValidateMode(str, Enum):
    STRICT = "strict"
    LENIENT = "lenient"


PROFILE_MODULES: dict[str, tuple[IngestModule, ...]] = {
    "scientific-paper": (IngestModule.COMPOUNDS, IngestModule.MARKUSH, IngestModule.REACTIONS),
    "molecules_only": (IngestModule.COMPOUNDS, IngestModule.MARKUSH),
    "reactions_only": (IngestModule.REACTIONS,),
}


@dataclass
class JobSpec:
    parse_preset: Literal["scientific-paper"] = "scientific-paper"
    modules: tuple[IngestModule, ...] = field(
        default_factory=lambda: PROFILE_MODULES["molecules_only"]
    )
    validate: ValidateMode = ValidateMode.STRICT
    doc_id: str = ""
    source: str = ""
    output_dir: Path | None = None
    db_path: Path | None = None

    def to_json(self) -> str:
        payload = asdict(self)
        payload["modules"] = [m.value for m in self.modules]
        payload["validate"] = self.validate.value
        if self.output_dir is not None:
            payload["output_dir"] = str(self.output_dir)
        if self.db_path is not None:
            payload["db_path"] = str(self.db_path)
        return json.dumps(payload, ensure_ascii=False)

    @classmethod
    def from_profile(
        cls,
        profile: str,
        *,
        doc_id: str = "",
        source: str = "",
        output_dir: Path | None = None,
        db_path: Path | None = None,
        validate: ValidateMode = ValidateMode.STRICT,
    ) -> JobSpec:
        if profile not in PROFILE_MODULES:
            raise ValueError(f"Unknown profile: {profile!r}. Choose from {list(PROFILE_MODULES)}.")
        return cls(
            parse_preset="scientific-paper",
            modules=PROFILE_MODULES[profile],
            validate=validate,
            doc_id=doc_id,
            source=source,
            output_dir=output_dir,
            db_path=db_path,
        )

    def has_module(self, module: IngestModule) -> bool:
        return module in self.modules
