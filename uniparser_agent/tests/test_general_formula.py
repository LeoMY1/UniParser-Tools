from __future__ import annotations

import base64
import json
import zipfile
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageDraw

from uniparser_agent.chemistry.general_formula import (
    ContextUnit,
    FormulaOccurrence,
    FormulaRecord,
    build_description_context_units,
    build_formula_records,
    build_markush_inventory,
    write_general_formula_outputs,
)
from uniparser_agent.chemistry.general_formula_agent import (
    CONTEXT_TARGET_CHARS,
    MAX_AGENT_ROUNDS,
    MAX_ANCHOR_GAP_CHARS,
    MAX_ANCHOR_SPAN_CHARS,
    MAX_PACKET_FORMULAS,
    SEARCH_PAGE_SIZE,
    DescriptionContextIndex,
    apply_table_decisions,
    build_formula_ledger,
    run_formula_agent,
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
    structures = build_markush_inventory(_resolver(), "CN-fixture")
    formulas = build_formula_records(structures)

    assert [structure.structure_id for structure in structures] == ["S001", "S002", "S003"]
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

    structures = build_markush_inventory(resolver, "CN-fixture")

    assert [structure.structure_id for structure in structures[-2:]] == ["S004", "S005"]
    assert [structure.smi for structure in structures[-2:]] == ["", ""]


def test_same_structure_with_different_labels_keeps_separate_formula_records() -> None:
    document = _patent_fixture()
    document["pages_tree"][2][7]["items"][0]["text"] = "式(VI)"
    resolver = BlockResolver(document, build_patent_structure(document, "CN-fixture"))

    records = build_formula_records(build_markush_inventory(resolver, "CN-fixture"))

    same_structure = [record for record in records if record.structure_id == "S001"]
    assert [record.formula_label for record in same_structure] == ["式(I)", "式(VI)"]


def test_context_covers_complete_description_and_chunks_overlap() -> None:
    resolver = _resolver()
    formulas = build_formula_records(build_markush_inventory(resolver, "CN-fixture"))
    units = build_description_context_units(resolver, formulas)
    context = "\n".join(unit.text for unit in units)

    assert "R1选自氢" in context
    assert "[FORMULA formula_id=F001" in context
    assert "[FORMULA formula_id=F002" in context
    assert "[FORMULA formula_id=F003" in context
    assert "实施例1" in context
    assert "1. 一种式(I)化合物" not in context


def test_formula_agent_uses_bounded_packet_and_updates_evidence_ledger() -> None:
    resolver = _resolver()
    formulas = build_formula_records(build_markush_inventory(resolver, "CN-fixture"))
    units = build_description_context_units(resolver, formulas)
    prompts: list[dict] = []

    def fake_chat(system_prompt: str, user_content: str) -> str:
        payload = json.loads(user_content)
        prompts.append(payload)
        evidence = payload["allowed_unit_ids"][0]
        if payload["round"] == 1:
            return json.dumps(
                {
                    "updates": [
                        {
                            "formula_id": "F001",
                            "object_type": "uncertain",
                            "classification_reason": "当前片段缺少可变基团定义",
                            "formula_name": "式(I)化合物",
                            "formula_role": "target_compound",
                            "evidence_unit_ids": [evidence],
                            "definition_fragments": [],
                        }
                    ],
                    "complete_formula_ids": [],
                    "retrieval_requests": [
                        {
                            "tool": "find_occurrences",
                            "formula_ids": ["F001"],
                            "cursor": 0,
                            "reason": "find variable definitions",
                        }
                    ],
                },
                ensure_ascii=False,
            )
        return json.dumps(
            {
                "updates": [
                    {
                        "formula_id": "F001",
                        "object_type": "general_formula",
                        "classification_reason": "式(I)包含可变基团定义",
                        "formula_name": "",
                        "formula_role": "unknown",
                        "evidence_unit_ids": [evidence],
                        "definition_fragments": [
                            {"text": "R1选自氢、卤素或C1-C6烷基", "evidence_unit_ids": [evidence]}
                        ],
                    },
                    {
                        "formula_id": "F002",
                        "object_type": "scheme_generic_structure",
                        "classification_reason": "式(II)是合成中的通用中间体",
                        "formula_name": "",
                        "formula_role": "intermediate",
                        "evidence_unit_ids": [evidence],
                        "definition_fragments": [],
                    },
                    {
                        "formula_id": "F003",
                        "object_type": "general_formula",
                        "classification_reason": "式(III)是说明书披露的通式",
                        "formula_name": "",
                        "formula_role": "unknown",
                        "evidence_unit_ids": [evidence],
                        "definition_fragments": [],
                    },
                ],
                "complete_formula_ids": ["F001", "F002", "F003"],
                "retrieval_requests": [],
            },
            ensure_ascii=False,
        )

    result = run_formula_agent(
        "CN-fixture",
        formulas,
        units,
        chat_fn=fake_chat,
    )

    assert result.meta["llm_call_count"] == 2
    assert len(prompts) == 2
    assert len(result.packets) == 1
    assert all(len(context.text) <= CONTEXT_TARGET_CHARS for context in result.contexts)
    assert result.rows[0]["formula_role"] == "target_compound"
    assert result.rows[0]["variable_definition_text"] == "R1选自氢、卤素或C1-C6烷基"
    assert all(entry["status"] == "complete" for entry in result.ledger.values())


def test_agent_parameter_contract_matches_30_patent_audit() -> None:
    assert MAX_PACKET_FORMULAS == 20
    assert MAX_ANCHOR_GAP_CHARS == 3_000
    assert MAX_ANCHOR_SPAN_CHARS == 8_000
    assert CONTEXT_TARGET_CHARS == 12_000
    assert MAX_AGENT_ROUNDS == 4


def _synthetic_formula(formula_index: int) -> FormulaRecord:
    return FormulaRecord(
        doc_id="CN-synthetic",
        formula_id=f"F{formula_index:03d}",
        structure_id=f"S{formula_index:03d}",
        smi=f"*C{formula_index}",
    )


def test_packet_builder_enforces_formula_gap_and_span_limits() -> None:
    formulas = [_synthetic_formula(index) for index in range(1, 26)]
    unit = ContextUnit("p1_b0", 0, 0, 1, "paragraph", "x" * 30_000)
    index = DescriptionContextIndex([unit], formulas)

    index.formula_positions = {formula.formula_id: [100 + offset * 20] for offset, formula in enumerate(formulas)}
    packets = index.build_packets()
    assert [len(packet.formula_ids) for packet in packets] == [20, 5]

    index.formula_positions = {"F001": [100], "F002": [3_101]}
    index.formulas = formulas[:2]
    assert len(index.build_packets()) == 2

    index.formula_positions = {
        "F001": [100],
        "F002": [2_800],
        "F003": [5_500],
        "F004": [8_200],
    }
    index.formulas = formulas[:4]
    span_packets = index.build_packets()
    assert [len(packet.formula_ids) for packet in span_packets] == [3, 1]
    assert all(packet.context_end - packet.context_start <= CONTEXT_TARGET_CHARS for packet in span_packets)


def test_search_text_pages_results_five_at_a_time() -> None:
    units = [
        ContextUnit(
            unit_id=f"p{page + 1}_b0",
            page_index=page,
            block_index=0,
            block=page,
            block_type="paragraph",
            text=f"第{page + 1}处，其中 R1 表示氢或卤素。",
        )
        for page in range(7)
    ]
    formula = _synthetic_formula(1)
    formula.occurrences.append(FormulaOccurrence(0, 0, 0, 0, 0, "式(I)", None, 1.0))
    index = DescriptionContextIndex(units, [formula])
    packet = index.build_packets()[0]

    first_page = index.search_text(
        packet,
        round_index=2,
        formula_ids=("F001",),
        query="R1表示",
        cursor=0,
    )
    second_page = index.search_text(
        packet,
        round_index=3,
        formula_ids=("F001",),
        query="R1表示",
        cursor=1,
    )

    assert first_page.total_hits == 7
    assert len(first_page.source_ranges) == SEARCH_PAGE_SIZE
    assert first_page.next_cursor == 1
    assert len(second_page.source_ranges) == 2
    assert second_page.next_cursor is None


def test_agent_stops_after_two_distinct_retrievals_without_new_evidence() -> None:
    resolver = _resolver()
    formulas = build_formula_records(build_markush_inventory(resolver, "CN-fixture"))
    units = build_description_context_units(resolver, formulas)

    def fake_chat(system_prompt: str, user_content: str) -> str:
        payload = json.loads(user_content)
        round_index = payload["round"]
        request = (
            {"tool": "find_occurrences", "formula_ids": ["F001"], "cursor": 0}
            if round_index == 1
            else {"tool": "search_text", "formula_ids": ["F001"], "query": "不存在的定义"}
        )
        return json.dumps(
            {
                "updates": [],
                "complete_formula_ids": [],
                "retrieval_requests": [request],
            }
        )

    result = run_formula_agent("CN-fixture", formulas, units, chat_fn=fake_chat)

    assert result.meta["llm_call_count"] == 3
    assert [context.tool for context in result.contexts] == [
        "initial_context",
        "find_occurrences",
        "search_text",
    ]
    assert all(entry["status"] == "insufficient" for entry in result.ledger.values())


def test_agent_rejects_nonempty_fields_without_allowed_evidence() -> None:
    resolver = _resolver()
    formulas = build_formula_records(build_markush_inventory(resolver, "CN-fixture"))
    units = build_description_context_units(resolver, formulas)

    def fake_chat(system_prompt: str, user_content: str) -> str:
        return json.dumps(
            {
                "updates": [
                    {
                        "formula_id": "F001",
                        "formula_name": "无证据名称",
                        "formula_role": "target_compound",
                        "evidence_unit_ids": ["not-an-allowed-unit"],
                        "definition_fragments": [],
                    }
                ],
                "complete_formula_ids": [],
                "retrieval_requests": [{"tool": "browse_web", "formula_ids": ["F001"]}],
            },
            ensure_ascii=False,
        )

    result = run_formula_agent("CN-fixture", formulas, units, chat_fn=fake_chat)

    assert result.rows == []
    assert result.ledger["F001"]["formula_name_candidates"] == []
    assert result.ledger["F001"]["formula_role_candidates"] == []
    assert result.ledger["F001"]["table_action"] == "review"
    assert result.ledger["F001"]["evidence_unit_ids"] == []
    assert result.meta["llm_call_count"] == 1


def test_outputs_keep_original_images_and_embed_them_in_excel(tmp_path: Path) -> None:
    def classify_all(system_prompt: str, user_content: str) -> str:
        payload = json.loads(user_content)
        evidence = payload["allowed_unit_ids"][0]
        return json.dumps(
            {
                "updates": [
                    {
                        "formula_id": formula_id,
                        "object_type": "general_formula",
                        "classification_reason": "测试夹具中的通式候选",
                        "formula_name": "",
                        "formula_role": "unknown",
                        "evidence_unit_ids": [evidence],
                        "definition_fragments": [],
                    }
                    for formula_id in payload["packet"]["formula_ids"]
                ],
                "complete_formula_ids": payload["packet"]["formula_ids"],
                "retrieval_requests": [],
            },
            ensure_ascii=False,
        )

    outputs = write_general_formula_outputs(
        _resolver(),
        "CN-fixture",
        tmp_path,
        chat_fn=classify_all,
    )

    assert outputs.structure_count == 3
    assert outputs.formula_count == 3
    assert outputs.occurrence_count == 4
    assert outputs.image_count == 3
    assert outputs.llm_call_count == 1
    assert outputs.task_packets_path.is_file()
    assert outputs.evidence_ledger_path.is_file()
    assert outputs.agent_contexts_path.is_file()
    inventory = json.loads(outputs.inventory_path.read_text(encoding="utf-8"))
    assert [item["structure_id"] for item in inventory["structures"]] == ["S001", "S002", "S003"]
    assert [item["formula_id"] for item in inventory["formula_records"]] == ["F001", "F002", "F003"]
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


def test_object_classification_filters_table_without_extra_llm_calls() -> None:
    resolver = _resolver()
    formulas = build_formula_records(build_markush_inventory(resolver, "CN-fixture"))
    units = build_description_context_units(resolver, formulas)
    calls = 0

    def fake_chat(system_prompt: str, user_content: str) -> str:
        nonlocal calls
        calls += 1
        payload = json.loads(user_content)
        evidence = payload["allowed_unit_ids"][0]
        object_types = {
            "F001": "general_formula",
            "F002": "scheme_generic_structure",
            "F003": "substituent_option",
        }
        return json.dumps(
            {
                "updates": [
                    {
                        "formula_id": formula_id,
                        "object_type": object_type,
                        "classification_reason": "由相邻文字判定",
                        "formula_name": "",
                        "formula_role": "unknown",
                        "evidence_unit_ids": [evidence],
                        "definition_fragments": [],
                    }
                    for formula_id, object_type in object_types.items()
                ],
                "complete_formula_ids": list(object_types),
                "retrieval_requests": [],
            },
            ensure_ascii=False,
        )

    result = run_formula_agent("CN-fixture", formulas, units, chat_fn=fake_chat)

    assert calls == 1
    assert result.meta["llm_call_count"] == 1
    assert [row["formula_id"] for row in result.rows] == ["F001", "F002"]
    assert result.ledger["F003"]["object_type"] == "substituent_option"
    assert result.ledger["F003"]["table_action"] == "exclude"
    assert result.meta["excluded_formula_count"] == 1


def _same_structure_formula(formula_id: str, label: str | None, page_index: int) -> FormulaRecord:
    return FormulaRecord(
        doc_id="CN-dedupe",
        formula_id=formula_id,
        structure_id="S001",
        smi="*c1ccccc1",
        formula_label=label,
        occurrences=[FormulaOccurrence(page_index, 0, page_index, 0, 0, label, None, 1.0)],
    )


def test_table_dedupe_merges_only_equivalent_label_and_unique_unlabeled_copy() -> None:
    formulas = [
        _same_structure_formula("F001", "式（I）", 0),
        _same_structure_formula("F002", "Formula I", 1),
        _same_structure_formula("F003", None, 2),
    ]
    ledger = build_formula_ledger(formulas)
    for entry in ledger.values():
        entry["object_type"] = "general_formula"

    apply_table_decisions(formulas, ledger)

    assert ledger["F001"]["table_action"] == "keep"
    assert ledger["F002"]["table_action"] == "merge"
    assert ledger["F002"]["merge_target_formula_id"] == "F001"
    assert ledger["F003"]["table_action"] == "merge"
    assert ledger["F003"]["merge_target_formula_id"] == "F001"
    assert ledger["F001"]["merged_formula_ids"] == ["F002", "F003"]
    assert len(ledger["F001"]["occurrences"]) == 3


def test_table_dedupe_never_merges_different_nonempty_formula_labels() -> None:
    formulas = [
        _same_structure_formula("F001", "式(Ia)", 0),
        _same_structure_formula("F002", "式(Ia′)", 1),
        _same_structure_formula("F003", "式(Ib)", 2),
    ]
    ledger = build_formula_ledger(formulas)
    for entry in ledger.values():
        entry["object_type"] = "general_formula"

    apply_table_decisions(formulas, ledger)

    assert [ledger[formula.formula_id]["table_action"] for formula in formulas] == ["keep", "keep", "keep"]
