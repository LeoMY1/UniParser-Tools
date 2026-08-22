"""Excel export for the Markush general-formula analysis table."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import xlsxwriter
from PIL import Image


SHEET_NAME = "通式结构分析"
HEADERS = (
    "文档ID",
    "通式ID",
    "通式编号",
    "通式名称",
    "通式角色",
    "通式结构示例图",
    "Markush SMILES",
    "可变基团及参数定义",
    "证据位置",
)

_ROLE_LABELS = {
    "target_compound": "目标化合物",
    "starting_material": "起始原料",
    "intermediate": "中间体",
    "unknown": "未知",
}


def _evidence_text(value: Any) -> str:
    if not isinstance(value, list):
        return ""
    parts: list[str] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        kind = "结构" if item.get("kind") == "formula" else "上下文"
        page = int(item.get("page_index") or 0) + 1
        block_index = item.get("block_index")
        block = item.get("block")
        parts.append(f"{kind}:第{page}页/block_index={block_index}/block={block}")
    return "\n".join(parts)


def _json_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    return str(value)


def _image_scale(path: Path, max_width: int = 210, max_height: int = 145) -> tuple[float, float]:
    with Image.open(path) as image:
        width, height = image.size
    if width <= 0 or height <= 0:
        return 1.0, 1.0
    scale = min(max_width / width, max_height / height, 1.0)
    return scale, scale


def write_general_formula_excel(rows: list[dict[str, Any]], output_path: str | Path) -> Path:
    """Write one image-anchored row per unique Markush formula."""
    path = Path(output_path).expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    workbook = xlsxwriter.Workbook(str(path))
    workbook.set_properties(
        {
            "title": "Markush通式结构分析表",
            "subject": "CN专利说明书中的Markush通式",
            "comments": "结构图来自UniParser molecule.source；文本证据由说明书锚点检索Agent按需获取。",
        }
    )
    worksheet = workbook.add_worksheet(SHEET_NAME)
    worksheet.hide_gridlines(2)
    worksheet.freeze_panes(1, 3)
    worksheet.set_tab_color("#1F4E78")

    header_format = workbook.add_format(
        {
            "bold": True,
            "font_color": "#FFFFFF",
            "bg_color": "#1F4E78",
            "align": "center",
            "valign": "vcenter",
            "border": 1,
            "border_color": "#B4C6E7",
        }
    )
    text_format = workbook.add_format(
        {
            "font_color": "#1F2937",
            "valign": "top",
            "text_wrap": True,
            "border": 1,
            "border_color": "#D9E2F3",
        }
    )
    centered_format = workbook.add_format(
        {
            "font_color": "#1F2937",
            "align": "center",
            "valign": "vcenter",
            "text_wrap": True,
            "border": 1,
            "border_color": "#D9E2F3",
        }
    )
    smiles_format = workbook.add_format(
        {
            "font_name": "Courier New",
            "font_size": 9,
            "font_color": "#1F2937",
            "valign": "top",
            "text_wrap": True,
            "border": 1,
            "border_color": "#D9E2F3",
        }
    )
    missing_image_format = workbook.add_format(
        {
            "font_color": "#9C0006",
            "bg_color": "#FFC7CE",
            "align": "center",
            "valign": "vcenter",
            "border": 1,
            "border_color": "#D9E2F3",
        }
    )

    worksheet.set_row(0, 28)
    for column, header in enumerate(HEADERS):
        worksheet.write(0, column, header, header_format)

    worksheet.set_column("A:A", 18)
    worksheet.set_column("B:B", 11)
    worksheet.set_column("C:C", 15)
    worksheet.set_column("D:D", 28)
    worksheet.set_column("E:E", 14)
    worksheet.set_column("F:F", 31)
    worksheet.set_column("G:G", 42)
    worksheet.set_column("H:H", 58)
    worksheet.set_column("I:I", 42)

    for row_index, row in enumerate(rows, start=1):
        worksheet.set_row(row_index, 120)
        values = (
            row.get("doc_id"),
            row.get("formula_id"),
            row.get("formula_label"),
            row.get("formula_name"),
            _ROLE_LABELS.get(str(row.get("formula_role") or "unknown"), "未知"),
        )
        for column, value in enumerate(values):
            worksheet.write(row_index, column, _json_text(value), centered_format if column < 3 else text_format)

        image_value = row.get("structure_image")
        image_path = Path(str(image_value)).expanduser() if image_value else None
        if image_path is not None and image_path.is_file():
            x_scale, y_scale = _image_scale(image_path)
            worksheet.write_blank(row_index, 5, None, centered_format)
            worksheet.insert_image(
                row_index,
                5,
                str(image_path),
                {
                    "x_scale": x_scale,
                    "y_scale": y_scale,
                    "x_offset": 8,
                    "y_offset": 8,
                    "object_position": 1,
                    "description": f"{row.get('formula_id', '')} {row.get('formula_label', '')} Markush structure",
                },
            )
        else:
            worksheet.write(row_index, 5, "未获取结构图", missing_image_format)

        worksheet.write(row_index, 6, _json_text(row.get("markush_smiles")), smiles_format)
        worksheet.write(row_index, 7, _json_text(row.get("variable_definition_text")), text_format)
        worksheet.write(row_index, 8, _evidence_text(row.get("evidence_locations")), text_format)

    last_row = max(1, len(rows))
    worksheet.autofilter(0, 0, last_row, len(HEADERS) - 1)
    worksheet.set_landscape()
    worksheet.fit_to_pages(1, 0)
    worksheet.repeat_rows(0)
    workbook.close()
    return path
