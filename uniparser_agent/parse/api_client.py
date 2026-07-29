"""Lightweight UniParser HTTP client (no uniparser-tools / OpenCV)."""

from __future__ import annotations

import base64
import traceback
import uuid
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import requests

from uniparser_agent.parse.options import SCIENTIFIC_PAPER_TRIGGER


PENDING_STATUSES = frozenset({"undefined", "waiting", "processing"})
IMAGE_SUFFIXES = frozenset({".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".tif", ".tiff"})


class UniParserApiClient:
    def __init__(self, host: str, api_key: str) -> None:
        if not api_key:
            raise ValueError("api_key can not be empty")
        if not host.startswith("http"):
            raise ValueError("host must start with http or https")
        self.api_key = api_key
        self.host = host.rstrip("/")
        self._user = uuid.uuid5(uuid.NAMESPACE_DNS, api_key)

    def to_token(self, task_id: str) -> str:
        return uuid.uuid5(self._user, task_id).hex

    def _headers(self) -> dict[str, str]:
        return {"X-API-Key": self.api_key}

    def trigger_file(self, file_path: str, *, trigger_kwargs: dict[str, Any] | None = None) -> dict[str, Any]:
        token = self.to_token(file_path)
        data = dict(SCIENTIFIC_PAPER_TRIGGER)
        if trigger_kwargs:
            data.update(trigger_kwargs)
        data["token"] = token
        try:
            with open(file_path, "rb") as fh:
                response = requests.post(
                    f"{self.host}/trigger-file-async",
                    files={"file": fh},
                    data=data,
                    headers=self._headers(),
                    timeout=600,
                )
            return response.json()
        except Exception:
            return {
                "status": "error",
                "token": token,
                "message": "trigger file failed",
                "description": traceback.format_exc(),
            }

    def trigger_url(self, pdf_url: str, *, trigger_kwargs: dict[str, Any] | None = None) -> dict[str, Any]:
        token = self.to_token(pdf_url)
        data = {"url": pdf_url, **SCIENTIFIC_PAPER_TRIGGER}
        if trigger_kwargs:
            data.update(trigger_kwargs)
        data["token"] = token
        try:
            response = requests.post(
                f"{self.host}/trigger-url-async",
                json=data,
                headers=self._headers(),
                timeout=600,
            )
            return response.json()
        except Exception:
            return {
                "status": "error",
                "token": token,
                "message": "trigger url failed",
                "description": traceback.format_exc(),
            }

    def trigger_snip(self, snip_path: str, *, trigger_kwargs: dict[str, Any] | None = None) -> dict[str, Any]:
        token = self.to_token(snip_path)
        data = dict(SCIENTIFIC_PAPER_TRIGGER)
        if trigger_kwargs:
            data.update(trigger_kwargs)
        data["token"] = token
        try:
            raw = Path(snip_path).read_bytes()
            img_b64 = base64.b64encode(raw).decode("ascii")
            response = requests.post(
                f"{self.host}/trigger-snip-async",
                data={"img": img_b64, **data},
                headers=self._headers(),
                timeout=600,
            )
            return response.json()
        except Exception:
            return {
                "status": "error",
                "token": token,
                "message": "trigger snip failed",
                "description": traceback.format_exc(),
            }

    def get_result(self, token: str, *, pages_tree: bool = False) -> dict[str, Any]:
        payload = {
            "token": token,
            "content": False,
            "objects": False,
            "pages_dict": False,
            "pages_tree": pages_tree,
            "molecule_source": False,
        }
        try:
            response = requests.post(
                f"{self.host}/get-result",
                json=payload,
                headers=self._headers(),
                timeout=600,
            )
            return response.json()
        except Exception:
            return {
                "status": "error",
                "token": token,
                "message": "get result failed",
                "description": traceback.format_exc(),
            }

    def get_formatted(self, token: str) -> dict[str, Any]:
        payload = {
            "token": token,
            "content": True,
            "objects": False,
            "pages_dict": False,
            "pages_tree": False,
            "molecule_source": False,
            "textual": "markdown",
            "table": "markdown",
            "molecule": "markdown",
            "chart": "markdown",
            "figure": "markdown",
            "expression": "markdown",
            "equation": "latex",
            "marginalia": False,
        }
        try:
            response = requests.post(
                f"{self.host}/get-formatted",
                json=payload,
                headers=self._headers(),
                timeout=600,
            )
            return response.json()
        except Exception:
            return {
                "status": "error",
                "token": token,
                "message": "get formatted failed",
                "description": traceback.format_exc(),
            }


def resolve_input(raw: str) -> tuple[str, str, Path | None]:
    """Return (kind, source_stem, path) where kind is file|image|url."""
    text = raw.strip()
    if not text:
        raise ValueError("INPUT must not be empty.")
    if text.startswith("http://") or text.startswith("https://"):
        segment = urlparse(text).path.rstrip("/").rsplit("/", 1)[-1]
        stem = segment or "url_document"
        for ext in (".pdf", ".png", ".jpg", ".jpeg", ".webp"):
            if stem.lower().endswith(ext):
                stem = stem[: -len(ext)]
                break
        return "url", stem or "url_document", None

    path = Path(text).expanduser().resolve()
    if not path.is_file():
        raise ValueError(f"File not found: {path}")
    stem = path.stem or "document"
    if path.suffix.lower() in IMAGE_SUFFIXES:
        return "image", stem, path
    return "file", stem, path
