"""Parse UniParser table.structure HTML into catalog and activity rows."""

from __future__ import annotations

import re
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Any, Iterator


class TableParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.rows: list[list[str]] = []
        self._row: list[str] | None = None
        self._cell: str | None = None
        self._in_td = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "tr":
            self._row = []
        elif tag in ("td", "th"):
            self._cell = ""
            self._in_td = True

    def handle_endtag(self, tag: str) -> None:
        if tag in ("td", "th") and self._in_td:
            assert self._row is not None
            self._row.append((self._cell or "").strip())
            self._in_td = False
            self._cell = None
        elif tag == "tr" and self._row is not None:
            if any(c for c in self._row):
                self.rows.append(self._row)
            self._row = None

    def handle_data(self, data: str) -> None:
        if self._in_td:
            self._cell = (self._cell or "") + data


@dataclass
class CatalogRow:
    label: str
    name: str
    smi: str
    page: int


def walk_blocks(blocks: list[Any] | None) -> Iterator[dict[str, Any]]:
    for block in blocks or []:
        if not isinstance(block, dict):
            continue
        yield block
        items = block.get("items")
        if isinstance(items, list):
            yield from walk_blocks(items)


def parse_html_table(structure: str) -> list[list[str]]:
    parser = TableParser()
    parser.feed(structure)
    return parser.rows


def normalize_label(text: str) -> str:
    t = (text or "").strip()
    t = t.replace("（", "(").replace("）", ")")
    t = re.sub(r"^化合物\s*", "", t)
    t = t.strip()
    if re.match(r"^I-\d+$", t):
        return t
    m_ix = re.search(r"\((I-\d+)\)", t) or re.search(r"\b(I-\d+)\b", t)
    if m_ix:
        return m_ix.group(1)
    m2 = re.search(r"\(([IVX]+)\)", t)
    if m2:
        return m2.group(1)
    m3 = re.search(r"\((I[A-F])\)", t)
    if m3:
        return m3.group(1)
    if re.match(r"^[IVX]+$", t):
        return t
    if re.match(r"^I[A-F]$", t):
        return t
    return t


def extract_catalog_tables(pages: list[Any]) -> list[CatalogRow]:
    rows: list[CatalogRow] = []
    seen: set[str] = set()
    for page in pages:
        page_blocks = page if isinstance(page, list) else [page]
        for block in walk_blocks(page_blocks):
            struct = block.get("structure") or ""
            if not isinstance(struct, str) or not struct.startswith("<table"):
                continue
            page_no = int(block.get("page", 0))
            table = parse_html_table(struct)
            for r in table:
                if len(r) < 3:
                    continue
                label = r[0].strip()
                if not re.match(r"^I-\d+$", label):
                    continue
                name = r[1].strip()
                smi = r[2].strip()
                if not smi or smi in ("结构式",):
                    continue
                if label in seen:
                    continue
                seen.add(label)
                rows.append(CatalogRow(label=label, name=name, smi=smi, page=page_no))
    return rows
