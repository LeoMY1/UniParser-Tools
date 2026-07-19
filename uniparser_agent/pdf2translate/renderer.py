"""PyMuPDF overlay renderer: cover original text and redraw translations."""

from __future__ import annotations

import re
import unicodedata
from pathlib import Path
from typing import Any

import fitz  # PyMuPDF

from uniparser_agent.pdf2translate.mathtext import render_inline_math
from uniparser_agent.pdf2translate.models import TranslateUnit

# Fixed font sizes by UniParser block type (pt). Same type → same size.
FONT_SIZE_BY_TYPE: dict[str, float] = {
    "documenttitle": 16.0,
    "title": 12.0,
    "paragraph": 10.0,
    "abstract": 10.0,
    "reference": 9.0,
    "tablecaption": 9.0,
    "figurecaption": 9.0,
    "caption": 9.0,
    "imagecaption": 9.0,
}
DEFAULT_TYPE_FONT_SIZE = 10.0
_LINE_HEIGHT_FACTOR = 1.35
_MAX_GROW_FACTOR = 6.0

# Do not start a line with these (CJK punctuation rules).
_NO_LINE_START = set("，。、；：！？）》」』】〉%℃°")
# Prefer not ending a line with these.
_NO_LINE_END = set("（「『【《〈")

# Prefer Simplified-Chinese faces: their ，。 sit low-left in the em-box.
# PingFang.ttc often resolves to PingFangHK, where punctuation is vertically
# centered and looks "too high" next to Han characters.
_CJK_FONT_CANDIDATES = (
    "/System/Library/Fonts/Hiragino Sans GB.ttc",
    "/System/Library/Fonts/Supplemental/Songti.ttc",
    "/System/Library/Fonts/STHeiti Light.ttc",
    "/System/Library/Fonts/PingFang.ttc",
    "/Library/Fonts/Arial Unicode.ttf",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJKsc-Regular.otf",
    "/usr/share/fonts/google-noto-cjk/NotoSansCJK-Regular.ttc",
)


def font_size_for_type(block_type: str) -> float:
    """Return the unified font size for a UniParser block type."""
    return float(FONT_SIZE_BY_TYPE.get((block_type or "").strip().lower(), DEFAULT_TYPE_FONT_SIZE))


def _resolve_font(fontfile: str | None, fontname: str) -> tuple[str, str | None]:
    if fontfile:
        path = Path(fontfile).expanduser()
        if path.is_file():
            return "custom", str(path)
    for candidate in _CJK_FONT_CANDIDATES:
        if Path(candidate).is_file():
            return "custom", candidate
    return fontname or "china-s", None


def _measure_font(fontfile: str | None) -> fitz.Font:
    if fontfile and Path(fontfile).is_file():
        return fitz.Font(fontfile=fontfile)
    for candidate in _CJK_FONT_CANDIDATES:
        if Path(candidate).is_file():
            return fitz.Font(fontfile=candidate)
    return fitz.Font("helv")


def build_page_rect_map(pdf_path: str | Path) -> dict[int, tuple[float, float]]:
    doc = fitz.open(str(pdf_path))
    try:
        return {
            i: (float(page.rect.width), float(page.rect.height))
            for i, page in enumerate(doc)
        }
    finally:
        doc.close()


def _is_cjk_char(ch: str) -> bool:
    o = ord(ch)
    return (
        0x4E00 <= o <= 0x9FFF
        or 0x3400 <= o <= 0x4DBF
        or 0xF900 <= o <= 0xFAFF
        or 0x3000 <= o <= 0x303F
        or 0xFF00 <= o <= 0xFFEF
    )


def _tokenize_for_wrap(text: str) -> list[str]:
    """Split into CJK chars / CJK punct (atomic) and Latin words (keep together)."""
    text = unicodedata.normalize("NFC", text)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[^\S\n]+", " ", text)
    tokens: list[str] = []
    i = 0
    n = len(text)
    while i < n:
        ch = text[i]
        if ch == "\n":
            tokens.append("\n")
            i += 1
            continue
        if _is_cjk_char(ch) or ch in _NO_LINE_START or ch in _NO_LINE_END:
            tokens.append(ch)
            i += 1
            continue
        if ch == " ":
            # Soft break: attach to following Latin word when possible.
            j = i + 1
            while j < n and text[j] == " ":
                j += 1
            if j < n and not _is_cjk_char(text[j]) and text[j] not in _NO_LINE_START | _NO_LINE_END and text[j] != "\n":
                k = j
                while k < n and text[k] not in " \n" and not _is_cjk_char(text[k]) and text[k] not in _NO_LINE_START | _NO_LINE_END:
                    k += 1
                tokens.append(" " + text[j:k])
                i = k
            else:
                i = j
            continue
        # Latin / digit / symbol run
        j = i + 1
        while (
            j < n
            and text[j] not in " \n"
            and not _is_cjk_char(text[j])
            and text[j] not in _NO_LINE_START | _NO_LINE_END
        ):
            j += 1
        tokens.append(text[i:j])
        i = j
    return tokens


def wrap_cjk_text(text: str, max_width: float, fontsize: float, font: fitz.Font) -> list[str]:
    """Wrap mixed CJK/Latin text without insert_textbox's English-word bias."""
    if max_width <= 1:
        return [text]

    def width_of(s: str) -> float:
        return float(font.text_length(s, fontsize=fontsize))

    lines: list[str] = []
    for paragraph in text.split("\n"):
        if paragraph == "":
            lines.append("")
            continue
        tokens = _tokenize_for_wrap(paragraph)
        cur = ""
        for tok in tokens:
            if tok == "\n":
                lines.append(cur)
                cur = ""
                continue
            candidate = cur + tok
            if width_of(candidate) <= max_width or not cur:
                if width_of(candidate) > max_width and not cur:
                    # Oversized Latin token: hard-break by character.
                    for ch in tok.lstrip():
                        c2 = cur + ch
                        if width_of(c2) <= max_width or not cur:
                            cur = c2
                        else:
                            lines.append(cur)
                            cur = ch
                else:
                    cur = candidate
                continue

            # Would overflow: apply punctuation glue rules.
            if len(tok) == 1 and tok in _NO_LINE_START and cur:
                # Keep closing punct with previous line even if slightly wide.
                cur = candidate
                continue

            # Avoid ending previous line with opening punct.
            if cur and cur[-1] in _NO_LINE_END:
                # move opening punct to next line with tok
                open_ch = cur[-1]
                prev = cur[:-1]
                if prev:
                    lines.append(prev)
                cur = (open_ch + tok).lstrip()
                continue

            lines.append(cur)
            cur = tok.lstrip() if tok.startswith(" ") else tok

        if cur:
            lines.append(cur)

        # Reduce 1–2 glyph orphan last lines by borrowing from previous.
        if len(lines) >= 2 and 0 < len(lines[-1]) <= 2:
            prev, last = lines[-2], lines[-1]
            if len(prev) > 4:
                # Move last 2 chars of prev onto last line when widths allow.
                move = prev[-2:]
                new_prev = prev[:-2]
                new_last = move + last
                if width_of(new_prev) <= max_width and width_of(new_last) <= max_width:
                    lines[-2] = new_prev
                    lines[-1] = new_last

    return lines or [""]


def _ensure_page_font(page: fitz.Page, fontname: str, fontfile: str | None) -> str:
    if fontfile:
        try:
            page.insert_font(fontname=fontname, fontfile=fontfile)
        except Exception:  # noqa: BLE001 - font may already be present
            pass
    return fontname


def _draw_wrapped_lines(
    page: fitz.Page,
    rect: fitz.Rect,
    lines: list[str],
    *,
    fontsize: float,
    fontname: str,
    fontfile: str | None,
    measure_font: fitz.Font,
) -> bool:
    """Draw pre-wrapped lines; return True if all lines fit vertically."""
    _ensure_page_font(page, fontname, fontfile)
    line_h = fontsize * _LINE_HEIGHT_FACTOR
    # Baseline from em-box top (rect.y0), using font ascender — not a flat
    # ``fontsize`` offset, which misplaces CJK glyphs/punctuation.
    asc = float(measure_font.ascender) if measure_font.ascender > 0.5 else 0.88
    y = rect.y0 + fontsize * asc
    fits = True
    for line in lines:
        if y > rect.y1 + 0.5:
            fits = False
            break
        if line:
            kwargs: dict[str, Any] = {
                "fontsize": fontsize,
                "fontname": fontname,
                "color": (0, 0, 0),
            }
            if fontfile:
                kwargs["fontfile"] = fontfile
            page.insert_text((rect.x0, y), line, **kwargs)
        y += line_h
    return fits


def _rect_for_lines(
    page: fitz.Page,
    unit: TranslateUnit,
    line_count: int,
    fontsize: float,
) -> fitz.Rect:
    rect = fitz.Rect(*unit.bbox_pdf.as_tuple())
    need_h = max(rect.height, fontsize * _LINE_HEIGHT_FACTOR * max(line_count, 1) + fontsize * 0.2)
    max_h = max(rect.height, fontsize * _LINE_HEIGHT_FACTOR * _MAX_GROW_FACTOR)
    need_h = min(need_h, max_h)
    if need_h <= rect.height + 0.5:
        return rect
    grow = need_h - rect.height
    return fitz.Rect(
        rect.x0,
        max(0.0, rect.y0 - grow * 0.05),
        rect.x1,
        min(page.rect.height, rect.y1 + grow * 0.95),
    )


def _fit_and_draw(
    page: fitz.Page,
    unit: TranslateUnit,
    text: str,
    *,
    fontname: str,
    fontfile: str | None,
    measure_font: fitz.Font,
) -> tuple[str, float]:
    """Draw at unified type font size with CJK-aware wrapping."""
    fontsize = font_size_for_type(unit.block_type)
    # UniParser inline math ($ 55.00\% $) → display form (55.00%) before wrap/draw.
    text = render_inline_math(text, font=measure_font)
    base = fitz.Rect(*unit.bbox_pdf.as_tuple())
    max_width = max(base.width - 1.0, 1.0)
    lines = wrap_cjk_text(text, max_width, fontsize, measure_font)
    rect = _rect_for_lines(page, unit, len(lines), fontsize)

    # Grow further if vertical room still insufficient.
    line_h = fontsize * _LINE_HEIGHT_FACTOR
    need_h = fontsize * 0.2 + line_h * len(lines)
    while rect.height + 0.5 < need_h and rect.y1 < page.rect.height - 1:
        rect = fitz.Rect(rect.x0, rect.y0, rect.x1, min(page.rect.height, rect.y1 + line_h))

    page.draw_rect(rect, color=(1, 1, 1), fill=(1, 1, 1), overlay=True)
    fits = _draw_wrapped_lines(
        page,
        rect,
        lines,
        fontsize=fontsize,
        fontname=fontname,
        fontfile=fontfile,
        measure_font=measure_font,
    )
    return ("translated" if fits else "overflow"), fontsize


def _textbox_fits(
    page_width: float,
    page_height: float,
    rect: fitz.Rect,
    text: str,
    *,
    fontname: str,
    fontfile: str | None,
    fontsize: float,
) -> bool:
    """Compatibility helper used by tests: measure via CJK wrap."""
    del page_width, page_height, fontname
    font = _measure_font(fontfile)
    lines = wrap_cjk_text(text, max(rect.width - 1.0, 1.0), fontsize, font)
    need_h = fontsize * 0.2 + fontsize * _LINE_HEIGHT_FACTOR * len(lines)
    return need_h <= rect.height + 0.5


def render_translated_pdf(
    pdf_path: str | Path,
    units: list[TranslateUnit],
    output_path: str | Path,
    *,
    fontfile: str | None = None,
    fontname: str = "china-s",
    debug_layout: bool = False,
    debug_output_path: str | Path | None = None,
    min_font_size: float | None = None,
) -> dict[str, Any]:
    """Render translated units onto a copy of the original PDF.

    Font size is fixed by ``unit.block_type``. Line breaks use CJK-aware
    wrapping (not PyMuPDF ``insert_textbox`` English-word logic).
    """
    del min_font_size
    src = Path(pdf_path).expanduser().resolve()
    if not src.is_file():
        raise FileNotFoundError(f"PDF not found: {src}")
    if src.suffix.lower() != ".pdf":
        raise ValueError(f"Input must be a PDF file, got: {src.suffix}")

    out = Path(output_path).expanduser().resolve()
    out.parent.mkdir(parents=True, exist_ok=True)

    doc = fitz.open(str(src))
    stats = {
        "pages": doc.page_count,
        "drawn": 0,
        "overflow": 0,
        "skipped_draw": 0,
        "failed_draw": 0,
        "font_size_by_type": dict(FONT_SIZE_BY_TYPE),
    }

    resolved_fontname, resolved_fontfile = _resolve_font(fontfile, fontname)
    measure_font = _measure_font(resolved_fontfile)

    by_page: dict[int, list[TranslateUnit]] = {}
    for unit in units:
        by_page.setdefault(unit.page, []).append(unit)

    for page_index in range(doc.page_count):
        page = doc[page_index]
        for unit in by_page.get(page_index, []):
            if not unit.translated_text:
                stats["skipped_draw"] += 1
                continue
            if unit.status in {"skipped", "failed"} and not unit.translated_text:
                stats["skipped_draw"] += 1
                continue
            try:
                status, font_size = _fit_and_draw(
                    page,
                    unit,
                    unit.translated_text,
                    fontname=resolved_fontname,
                    fontfile=resolved_fontfile,
                    measure_font=measure_font,
                )
                unit.font_size = font_size
                if status == "overflow":
                    unit.status = "overflow"
                    stats["overflow"] += 1
                else:
                    unit.status = "translated"
                    stats["drawn"] += 1
            except Exception as exc:  # noqa: BLE001
                unit.status = "failed"
                unit.error = f"render_failed: {exc}"
                stats["failed_draw"] += 1

    if debug_layout:
        debug_doc = fitz.open(str(src))
        for page_index in range(debug_doc.page_count):
            page = debug_doc[page_index]
            for unit in by_page.get(page_index, []):
                rect = fitz.Rect(*unit.bbox_pdf.as_tuple())
                color = (1, 0, 0) if unit.translate else (0.4, 0.4, 0.4)
                page.draw_rect(rect, color=color, width=0.6)
                page.insert_text(
                    (rect.x0, max(rect.y0 - 2, 0)),
                    unit.unit_id,
                    fontsize=5,
                    color=color,
                )
        debug_path = (
            Path(debug_output_path).expanduser().resolve()
            if debug_output_path
            else out.with_name(out.stem + ".layout_debug.pdf")
        )
        debug_doc.save(str(debug_path))
        debug_doc.close()
        stats["debug_layout_path"] = str(debug_path)

    doc.save(str(out), garbage=3, deflate=True)
    doc.close()
    stats["output_path"] = str(out)
    return stats
