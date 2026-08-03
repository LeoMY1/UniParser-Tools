"""Wrap a chat function to dump system/user/raw responses to disk."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Callable

from uniparser_agent.chemistry.bioactivity import parse_bioactivity_response
from uniparser_agent.chemistry.enrich import parse_enrich_response
from uniparser_agent.chemistry.link_evidence import parse_link_response


ChatFn = Callable[[str, str], str]

DEFAULT_OUT_DIR = Path("/root/code/test/chemistry/llm_io_debug")


class DumpingChat:
    """One LLM call → link_XXX.json or sum_XXX.json under ``out_dir / doc_id``."""

    def __init__(
        self,
        base_chat: ChatFn,
        *,
        out_dir: Path,
        doc_id: str,
        model: str = "",
    ) -> None:
        self._base = base_chat
        self.out_dir = Path(out_dir).expanduser().resolve() / doc_id
        self.doc_id = doc_id
        self.model = model
        self._link_index = 0
        self._sum_index = 0
        self._act_index = 0
        self.out_dir.mkdir(parents=True, exist_ok=True)

    @property
    def batch_count(self) -> int:
        return self._act_index + self._link_index + self._sum_index

    @property
    def act_count(self) -> int:
        return self._act_index

    @property
    def link_count(self) -> int:
        return self._link_index

    @property
    def sum_count(self) -> int:
        return self._sum_index

    def __call__(self, system_prompt: str, user_content: str) -> str:
        kind = _call_kind(user_content)
        if kind == "act":
            batch_index = self._act_index
            self._act_index += 1
            filename = f"act_{batch_index:03d}.json"
            parse_fn = parse_bioactivity_response
        elif kind == "link":
            batch_index = self._link_index
            self._link_index += 1
            filename = f"link_{batch_index:03d}.json"
            parse_fn = parse_link_response
        else:
            batch_index = self._sum_index
            self._sum_index += 1
            filename = f"sum_{batch_index:03d}.json"
            parse_fn = parse_enrich_response

        labels = _labels_from_user(user_content, kind=kind)
        raw = ""
        parsed_ok = False
        error: str | None = None
        try:
            raw = self._base(system_prompt, user_content)
            try:
                parse_fn(raw)
                parsed_ok = True
            except Exception as exc:  # noqa: BLE001 — record parse failure
                error = f"parse_error: {exc}"
        except Exception as exc:  # noqa: BLE001 — record chat failure
            error = f"chat_error: {exc}"
            raise
        finally:
            payload = {
                "doc_id": self.doc_id,
                "kind": kind,
                "batch_index": batch_index,
                "labels": labels,
                "model": self.model,
                "system_prompt": system_prompt,
                "user_content": user_content,
                "attempts": [
                    {
                        "raw_response": raw,
                        "parsed_ok": parsed_ok,
                        "error": error,
                    }
                ],
            }
            path = self.out_dir / filename
            path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return raw


def _call_kind(user_content: str) -> str:
    try:
        data = json.loads(user_content)
    except json.JSONDecodeError:
        return "sum"
    if isinstance(data, dict) and "activity_table" in data:
        return "act"
    if isinstance(data, dict) and "chunks" in data:
        return "link"
    return "sum"


def _labels_from_user(user_content: str, *, kind: str) -> list[str]:
    try:
        data = json.loads(user_content)
    except json.JSONDecodeError:
        return []
    if not isinstance(data, dict):
        return []
    if kind == "act":
        table = data.get("activity_table")
        if isinstance(table, dict) and table.get("source_table_id"):
            return [str(table["source_table_id"])]
        return []
    if kind == "link":
        molecules = data.get("molecules")
        if not isinstance(molecules, list):
            return []
        labels: list[str] = []
        for c in molecules:
            if not isinstance(c, dict):
                continue
            lab = c.get("label") or c.get("compound_id") or ""
            if lab:
                labels.append(str(lab))
        return labels
    compounds = data.get("compounds")
    if not isinstance(compounds, list):
        return []
    labels = []
    for c in compounds:
        if not isinstance(c, dict):
            continue
        lab = c.get("label") or c.get("compound_label") or ""
        if lab:
            labels.append(str(lab))
    return labels


def make_dumping_chat_fn(
    base_chat: ChatFn,
    *,
    out_dir: Path | str = DEFAULT_OUT_DIR,
    doc_id: str,
    model: str = "",
) -> DumpingChat:
    return DumpingChat(base_chat, out_dir=Path(out_dir), doc_id=doc_id, model=model)
