from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass
class JobSpec:
    doc_id: str = ""
    source: str = ""
    output_dir: Path | None = None
    db_path: Path | None = None

    def to_json(self) -> str:
        payload = asdict(self)
        if self.output_dir is not None:
            payload["output_dir"] = str(self.output_dir)
        if self.db_path is not None:
            payload["db_path"] = str(self.db_path)
        return json.dumps(payload, ensure_ascii=False)
