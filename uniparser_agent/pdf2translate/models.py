"""Data models for PDF translation units."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


TRANSLATABLE_TYPES = frozenset(
    {
        "paragraph",
        "title",
        "documenttitle",
        "abstract",
        "caption",
        "reference",
        "tablecaption",
        "figurecaption",
    }
)

SKIP_TYPES = frozenset(
    {
        "equation",
        "equationinline",
        "equationid",
        "table",
        "tablefootnote",
        "figure",
        "image",
        "chart",
        "molecule",
        "moleculeid",
        "expression",
        "hline",
        "pageheader",
        "pagefooter",
        "pagenumber",
        "group",
        "figuregroup",
        "tablegroup",
        "toc",
    }
)


@dataclass
class BBox:
    """Page rectangle in PyMuPDF coordinates (origin top-left, y downward)."""

    x0: float
    y0: float
    x1: float
    y1: float

    def as_tuple(self) -> tuple[float, float, float, float]:
        return (self.x0, self.y0, self.x1, self.y1)

    def width(self) -> float:
        return max(0.0, self.x1 - self.x0)

    def height(self) -> float:
        return max(0.0, self.y1 - self.y0)

    def to_dict(self) -> dict[str, float]:
        return {"x0": self.x0, "y0": self.y0, "x1": self.x1, "y1": self.y1}


@dataclass
class TranslateUnit:
    unit_id: str
    page: int
    order: int
    block_type: str
    text: str
    bbox_norm: dict[str, float]
    page_size_px: tuple[float, float]
    bbox_pdf: BBox
    translate: bool = True
    skip_reason: str | None = None
    translated_text: str | None = None
    status: str = "pending"  # pending|translated|skipped|failed|overflow
    error: str | None = None
    font_size: float | None = None
    placeholders: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["bbox_pdf"] = self.bbox_pdf.to_dict()
        data["page_size_px"] = list(self.page_size_px)
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TranslateUnit:
        bbox = data.get("bbox_pdf") or {}
        page_size = data.get("page_size_px") or [1.0, 1.0]
        return cls(
            unit_id=str(data["unit_id"]),
            page=int(data["page"]),
            order=int(data.get("order") or 0),
            block_type=str(data.get("block_type") or ""),
            text=str(data.get("text") or ""),
            bbox_norm=dict(data.get("bbox_norm") or {}),
            page_size_px=(float(page_size[0]), float(page_size[1])),
            bbox_pdf=BBox(
                x0=float(bbox.get("x0", 0.0)),
                y0=float(bbox.get("y0", 0.0)),
                x1=float(bbox.get("x1", 0.0)),
                y1=float(bbox.get("y1", 0.0)),
            ),
            translate=bool(data.get("translate", True)),
            skip_reason=data.get("skip_reason"),
            translated_text=data.get("translated_text"),
            status=str(data.get("status") or "pending"),
            error=data.get("error"),
            font_size=data.get("font_size"),
            placeholders=dict(data.get("placeholders") or {}),
        )
