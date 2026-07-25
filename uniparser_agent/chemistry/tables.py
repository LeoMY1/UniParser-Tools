"""Parse UniParser table.structure HTML into catalog and activity rows."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
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


@dataclass
class ActivityRow:
    kind: str  # ic50 | inhibition | viability | synergy
    example_or_label: str
    value: str
    unit: str = ""
    partner: str = ""
    raw: str = ""
    page: int = 0
    smi: str = ""


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


def clean_numeric(text: str) -> str | None:
    cleaned = (
        text.replace("$", "")
        .replace("\\", "")
        .replace("{", "")
        .replace("}", "")
        .replace("pm", "")
        .replace("\\pm", "")
    )
    m = re.search(r"([\d]+\.?[\d]*)", cleaned)
    return m.group(1) if m else None


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


def _pair_cells(row: list[str]) -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    i = 0
    while i + 1 < len(row):
        pairs.append((row[i].strip(), row[i + 1].strip()))
        i += 2
    return pairs


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


def extract_activity_tables(pages: list[Any]) -> list[ActivityRow]:
    activities: list[ActivityRow] = []
    for page in pages:
        page_blocks = page if isinstance(page, list) else [page]
        for block in walk_blocks(page_blocks):
            struct = block.get("structure") or ""
            if not isinstance(struct, str) or not struct.startswith("<table"):
                continue
            page_no = int(block.get("page", 0))
            flat = struct
            table = parse_html_table(struct)

            if "IC" in flat and "实施例" in flat:
                for r in table:
                    for left, right in _pair_cells(r):
                        if not re.match(r"^\d+$", left):
                            continue
                        val = clean_numeric(right)
                        if not val:
                            continue
                        activities.append(
                            ActivityRow(
                                kind="ic50",
                                example_or_label=left,
                                value=val,
                                unit="μM",
                                raw=f"{left}|{right}",
                                page=page_no,
                            )
                        )
                continue

            if "细胞活力" in flat or "吉西他滨" in flat or "顺铂" in flat:
                for r in table:
                    for left, right in _pair_cells(r):
                        if "实施例" not in left and not re.search(r"实施例\s*\d+", left):
                            if re.match(r"^\d+$", left) and right in ("是", "否"):
                                activities.append(
                                    ActivityRow(
                                        kind="synergy",
                                        example_or_label=left,
                                        value=right,
                                        page=page_no,
                                        raw=f"{left}|{right}",
                                    )
                                )
                            continue
                        m = re.search(r"实施例\s*(\d+)", left)
                        if not m:
                            continue
                        ex = m.group(1)
                        partner = ""
                        if "吉西他滨" in left:
                            partner = "gemcitabine"
                        elif "顺铂" in left:
                            partner = "cisplatin"
                        elif "氟尿嘧啶" in left or "5-FU" in left:
                            partner = "5-FU"
                        dose_m = re.search(r"([\d.]+)\s*μM", left)
                        dose = dose_m.group(1) if dose_m else ""
                        val = right.replace("%", "").strip()
                        activities.append(
                            ActivityRow(
                                kind="viability",
                                example_or_label=ex,
                                value=val,
                                unit="%",
                                partner=partner or (f"alone@{dose}uM" if dose else "alone"),
                                raw=left,
                                page=page_no,
                            )
                        )
                continue

            if "协同" in flat:
                for r in table:
                    for left, right in _pair_cells(r):
                        if re.match(r"^\d+$", left) and right in ("是", "否"):
                            activities.append(
                                ActivityRow(
                                    kind="synergy",
                                    example_or_label=left,
                                    value=right,
                                    page=page_no,
                                    raw=f"{left}|{right}",
                                )
                            )
                continue

            if "抑制率" in flat or "血小板" in flat:
                for r in table[1:]:
                    if len(r) < 3:
                        continue
                    comp = r[0]
                    inhib = clean_numeric(r[2])
                    if not inhib:
                        continue
                    label = ""
                    smi = ""
                    m = re.search(r"化合物\s*\(?([IVX]+)\)?", comp)
                    if m:
                        label = m.group(1)
                    smi_m = re.match(r"^([A-Za-z0-9@+\-\\/\[\]\(\)=#$]+)", comp.strip())
                    if smi_m and any(c in smi_m.group(1) for c in "CNOc"):
                        smi = smi_m.group(1).split()[0]
                    if not label and "对照" in comp:
                        label = "control"
                    if not label and "氯吡格雷" in comp:
                        label = "clopidogrel"
                    activities.append(
                        ActivityRow(
                            kind="inhibition",
                            example_or_label=label or comp[:40],
                            value=inhib,
                            unit="%",
                            smi=smi,
                            raw=comp[:120],
                            page=page_no,
                        )
                    )
    return activities


def extract_paragraphs(pages: list[Any]) -> dict[int, list[str]]:
    by_page: dict[int, list[str]] = {}
    for page in pages:
        page_blocks = page if isinstance(page, list) else [page]
        for block in walk_blocks(page_blocks):
            if block.get("type") not in ("paragraph", "title", "tablecaption", "imagecaption"):
                continue
            text = (block.get("text") or "").strip()
            if not text:
                continue
            page_no = int(block.get("page", 0))
            by_page.setdefault(page_no, []).append(text)
    return by_page


def activity_row_to_dict(row: ActivityRow) -> dict[str, Any]:
    return asdict(row)


def catalog_row_to_dict(row: CatalogRow) -> dict[str, Any]:
    return asdict(row)
