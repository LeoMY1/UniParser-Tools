from __future__ import annotations

import base64
import json
import zipfile
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageDraw

from uniparser_agent.chemistry.general_formula import (
    CHUNK_OVERLAP_CHARS,
    CHUNK_TARGET_CHARS,
    ContextUnit,
    analyze_general_formulas,
    build_description_context_units,
    build_markush_inventory,
    chunk_context_units,
    write_general_formula_outputs,
)
from uniparser_agent.chemistry.patent_structure import BlockResolver, build_patent_structure


def _block(block_id: int, page: int, order: int, block_type: str, text: str = "") -> dict:
    return {
        "page": page,
        "order": order,
        "block": block_id,
        "type": block_type,
        "text": text,
        "bbox": {"x1": 0, "y1": 0, "x2": 10, "y2": 10},
        "token": "fixture-token",
    }


def _image_source(size: tuple[int, int]) -> str:
    image = Image.new("RGB", size, "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle((4, 4, size[0] - 5, size[1] - 5), outline="black", width=2)
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return base64.b64encode(buffer.getvalue()).decode("ascii")


def _formula_group(
    block_id: int,
    page: int,
    order: int,
    *,
    label: str,
    smi: str,
    image_size: tuple[int, int] = (100, 60),
) -> dict:
    group = _block(block_id, page, order, "moleculegroup")
    group["items"] = [
        {**_block(block_id, page, order, "moleculeid", label), "text": label},
        {
            **_block(block_id, page, order + 1, "molecule"),
            "smi": smi,
            "markush": True,
            "source": _image_source(image_size),
            "conf": 0.95,
        },
    ]
    return group


def _patent_fixture() -> dict:
    duplicate_claim = _formula_group(12, 1, 2, label="式(I)", smi="*C1=CC=CC=C1")
    first = _formula_group(35, 2, 5, label="式(I)", smi="*C1=CC=CC=C1", image_size=(80, 50))
    better_duplicate = _formula_group(
        37,
        2,
        7,
        label="式(I)",
        smi="*C1=CC=CC=C1",
        image_size=(160, 90),
    )
    second = _formula_group(39, 2, 9, label="式(II)", smi="*N(*)C")
    detailed_only = _formula_group(43, 2, 13, label="式(III)", smi="*OC")
    return {
        "filename": "CN-fixture.pdf",
        "pages_tree": [
            [
                _block(1, 0, 0, "keyvalue", "(10)申请公布号 CN 123456789 A"),
            ],
            [
                _block(10, 1, 0, "pageheader", "权利要求书"),
                _block(11, 1, 1, "paragraph", "1. 一种式(I)化合物。"),
                duplicate_claim,
            ],
            [
                _block(30, 2, 0, "pageheader", "说明书"),
                _block(31, 2, 1, "title", "技术领域"),
                _block(32, 2, 2, "paragraph", "本发明涉及药物化学。"),
                _block(33, 2, 3, "title", "发明内容"),
                _block(34, 2, 4, "paragraph", "本发明提供如下式(I)和式(II)所示的化合物。"),
                first,
                _block(36, 2, 6, "paragraph", "其中R1选自氢、卤素或C1-C6烷基。"),
                better_duplicate,
                _block(38, 2, 8, "paragraph", "优选地，R1为氟或氯；n为0至3。"),
                second,
                _block(40, 2, 10, "paragraph", "式(II)为合成式(I)的关键中间体。"),
                _block(41, 2, 11, "title", "具体实施方式"),
                _block(42, 2, 12, "paragraph", "实施例1不应进入发明内容上下文。"),
                detailed_only,
            ],
        ],
    }


def _resolver() -> BlockResolver:
    document = _patent_fixture()
    return BlockResolver(document, build_patent_structure(document, "CN-fixture"))


def test_inventory_scans_description_and_deduplicates_exact_raw_smi() -> None:
    formulas = build_markush_inventory(_resolver(), "CN-fixture")

    assert [formula.formula_id for formula in formulas] == ["F001", "F002", "F003"]
    assert [formula.smi for formula in formulas] == ["*C1=CC=CC=C1", "*N(*)C", "*OC"]
    assert [len(formula.occurrences) for formula in formulas] == [2, 1, 1]
    assert [formula.formula_label for formula in formulas] == ["式(I)", "式(II)", "式(III)"]
    assert all(occurrence.page_index != 1 for formula in formulas for occurrence in formula.occurrences)


def test_markush_candidates_without_smi_are_kept_separately() -> None:
    document = _patent_fixture()
    document["pages_tree"][2].extend(
        [
            _formula_group(44, 2, 14, label="式(IV)", smi=""),
            _formula_group(45, 2, 16, label="式(V)", smi=""),
        ]
    )
    resolver = BlockResolver(document, build_patent_structure(document, "CN-fixture"))

    formulas = build_markush_inventory(resolver, "CN-fixture")

    assert [formula.formula_label for formula in formulas[-2:]] == ["式(IV)", "式(V)"]
    assert [formula.smi for formula in formulas[-2:]] == ["", ""]


def test_context_covers_complete_description_and_chunks_overlap() -> None:
    resolver = _resolver()
    formulas = build_markush_inventory(resolver, "CN-fixture")
    units = build_description_context_units(resolver, formulas)
    context = "\n".join(unit.text for unit in units)

    assert "R1选自氢" in context
    assert "[FORMULA formula_id=F001" in context
    assert "[FORMULA formula_id=F002" in context
    assert "[FORMULA formula_id=F003" in context
    assert "实施例1" in context
    assert "1. 一种式(I)化合物" not in context

    chunks = chunk_context_units(units, target_chars=160, overlap_chars=30)
    assert len(chunks) > 1
    assert chunks[0].overlap_chars == 0
    assert all(chunk.overlap_chars > 0 for chunk in chunks[1:])
    assert all(chunk.unit_ids for chunk in chunks)


def test_one_oversized_block_uses_the_same_12000_800_chunk_rule() -> None:
    unit = ContextUnit(
        unit_id="p100_b1",
        page_index=99,
        block_index=1,
        block=123,
        block_type="paragraph",
        text="长" * 26_000,
    )

    chunks = chunk_context_units([unit])

    assert len(chunks) == 3
    assert all(len(chunk.text) <= CHUNK_TARGET_CHARS for chunk in chunks)
    assert [chunk.overlap_chars for chunk in chunks] == [
        0,
        CHUNK_OVERLAP_CHARS,
        CHUNK_OVERLAP_CHARS,
    ]


def test_chunk_llm_results_merge_by_formula_id_without_asking_llm_for_smiles() -> None:
    resolver = _resolver()
    formulas = build_markush_inventory(resolver, "CN-fixture")
    units = build_description_context_units(resolver, formulas)
    chunks = chunk_context_units(units, target_chars=180, overlap_chars=40)
    prompts: list[dict] = []

    def fake_chat(system_prompt: str, user_content: str) -> str:
        payload = json.loads(user_content)
        prompts.append(payload)
        evidence = payload["allowed_unit_ids"][0]
        return json.dumps(
            {
                "results": [
                    {
                        "formula_id": "F001",
                        "formula_name": "式(I)化合物",
                        "formula_role": "target_compound",
                        "evidence_unit_ids": [evidence],
                        "definition_fragments": [
                            {"text": "R1选自氢、卤素或C1-C6烷基", "evidence_unit_ids": [evidence]}
                        ],
                    }
                ]
            },
            ensure_ascii=False,
        )

    rows, meta = analyze_general_formulas(
        "CN-fixture",
        formulas,
        units,
        chunks,
        chat_fn=fake_chat,
    )

    assert meta["llm_call_count"] == len(chunks)
    assert len(prompts) == len(chunks)
    assert all(
        all(set(item) == {"formula_id", "formula_label", "occurrence_pages"} for item in prompt["formula_inventory"])
        for prompt in prompts
    )
    assert rows[0]["formula_role"] == "target_compound"
    assert rows[0]["variable_definition_text"] == "R1选自氢、卤素或C1-C6烷基"
    assert rows[1]["formula_role"] == "unknown"
    assert rows[2]["formula_role"] == "unknown"


def test_outputs_keep_original_images_and_embed_them_in_excel(tmp_path: Path) -> None:
    outputs = write_general_formula_outputs(
        _resolver(),
        "CN-fixture",
        tmp_path,
        skip_llm=True,
    )

    assert outputs.formula_count == 3
    assert outputs.occurrence_count == 4
    assert outputs.image_count == 3
    assert outputs.llm_call_count == 0
    analysis = json.loads(outputs.analysis_path.read_text(encoding="utf-8"))
    assert analysis["columns"] == [
        "doc_id",
        "formula_id",
        "formula_label",
        "formula_name",
        "formula_role",
        "structure_image",
        "markush_smiles",
        "variable_definition_text",
        "evidence_locations",
    ]
    assert len(analysis["rows"]) == 3
    assert all(Path(row["structure_image"]).is_file() for row in analysis["rows"])
    with Image.open(analysis["rows"][0]["structure_image"]) as representative:
        assert representative.width > 100  # the larger duplicate source wins
    with zipfile.ZipFile(outputs.excel_path) as archive:
        drawing_xml = "".join(
            archive.read(name).decode("utf-8")
            for name in archive.namelist()
            if name.startswith("xl/drawings/drawing") and name.endswith(".xml")
        )
    # XlsxWriter may reuse identical image binaries, but every formula row keeps
    # its own drawing anchor/cell embedding.
    assert drawing_xml.count("<xdr:twoCellAnchor") == 3
