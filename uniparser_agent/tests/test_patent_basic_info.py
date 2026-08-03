from __future__ import annotations

import json
from pathlib import Path

from uniparser_agent.chemistry.patent_basic_info import (
    TABLE_COLUMNS,
    build_patent_basic_info_table,
    write_patent_basic_info,
)
from uniparser_agent.chemistry.patent_structure import BlockResolver, build_patent_structure


def _block(block_type: str, text: str = "") -> dict:
    return {"type": block_type, "text": text, "bbox": {"x1": 0, "y1": 0, "x2": 1, "y2": 1}}


def _resolver(document: dict, doc_id: str) -> BlockResolver:
    return BlockResolver(document, build_patent_structure(document, doc_id))


def _granted_cn_patent() -> dict:
    return {
        "filename": "CN110092777B.pdf",
        "pages_tree": [
            [
                _block("keyvalue", "(12)发明专利"),
                _block("keyvalue", "(10)授权公告号 CN 110092777 B"),
                _block("keyvalue", "(45)授权公告日 2020.07.14"),
                _block("hline"),
                _block("keyvalue", "(21)申请号 201910459173.2"),
                _block("keyvalue", "(22)申请日 2019.05.29"),
                _block("keyvalue", "(65)同一申请的已公布的文献号\n申请公布号 CN 110092777 A"),
                _block("keyvalue", "(43)申请公布日 2019.08.06"),
                _block("keyvalue", "(73)专利权人 江西省中医药研究院\n地址 330046 江西省南昌市东湖区文教路\n529号"),
                _block("keyvalue", "(72)发明人 李雪 黄斌 赵诗云 彭智祥"),
                _block(
                    "keyvalue",
                    "(74)专利代理机构 苏州中合知识产权代理事务所(普通合伙)32266\n代理人 刘召民",
                ),
                _block("keyvalue", "(51)Int.Cl.\nC07D 405/08(2006.01)"),
                _block("keyvalue", "C07D 405/14(2006.01)\nA61P 7/02(2006.01)"),
                _block("keyvalue", "(54)发明名称一种脱水穿心莲内酯衍生物及其\n制备方法和应用"),
                _block("keyvalue", "(57)摘要"),
                _block("paragraph", "本发明公开了一种衍生物，"),
                _block("pageheader", "OCR generated page header"),
            ],
            [_block("paragraph", "并公开其制备方法和应用。")],
            [
                _block("pageheader", "权利要求书"),
                _block("keyvalue", "(54)发明名称权利要求书中的错误标题"),
            ],
        ],
    }


def test_build_patent_basic_info_uses_front_matter_navigation() -> None:
    document = _granted_cn_patent()
    table = build_patent_basic_info_table(_resolver(document, "CN110092777B"), "CN110092777B")
    row = table["rows"][0]

    assert table["table_name"] == "patent_basic_info"
    assert table["columns"] == list(TABLE_COLUMNS)
    assert table["extraction_scope"] == {
        "navigation_node": "front_matter",
        "partition_source": "patent_structure",
        "method": "rule_only",
        "uses_llm": False,
    }
    assert row == {
        "doc_id": "CN110092777B",
        "document_number": "CN110092777B",
        "kind_code": "B",
        "document_type": "发明专利",
        "document_status": "授权公告",
        "title": "一种脱水穿心莲内酯衍生物及其制备方法和应用",
        "application_number": "201910459173.2",
        "application_date": "2019-05-29",
        "publication_date": "2020-07-14",
        "application_publication_number": "CN110092777A",
        "application_publication_date": "2019-08-06",
        "authorization_announcement_date": "2020-07-14",
        "holder_role": "专利权人",
        "applicants_or_patentees": ["江西省中医药研究院"],
        "addresses": ["330046 江西省南昌市东湖区文教路 529号"],
        "inventors": ["李雪", "黄斌", "赵诗云", "彭智祥"],
        "ipc_codes": ["C07D 405/08", "C07D 405/14", "A61P 7/02"],
        "priority_claims": [],
        "agency": "苏州中合知识产权代理事务所(普通合伙)",
        "agency_code": "32266",
        "agents": ["刘召民"],
        "abstract": "本发明公开了一种衍生物，并公开其制备方法和应用。",
    }
    assert table["warnings"] == []


def test_application_publication_reuses_current_document_number() -> None:
    document = {
        "pages_tree": [
            [
                _block("keyvalue", "(10)申请公布号 CN 115974847 A"),
                _block("keyvalue", "(43)申请公布日 2023.04.18"),
                _block("keyvalue", "(21)申请号 202211621863.1"),
                _block("keyvalue", "(54)发明名称测试专利"),
            ]
        ]
    }
    table = build_patent_basic_info_table(_resolver(document, "CN115974847A"), "CN115974847A")
    row = table["rows"][0]

    assert row["document_status"] == "申请公布"
    assert row["application_publication_number"] == "CN115974847A"
    assert row["publication_date"] == "2023-04-18"
    assert row["authorization_announcement_date"] is None


def test_write_patent_basic_info_reports_missing_front_matter_fields(tmp_path: Path) -> None:
    document = {"pages_tree": [[]]}
    path = write_patent_basic_info(
        _resolver(document, "empty"),
        "empty",
        tmp_path / "patent_basic_info.json",
    )
    payload = json.loads(path.read_text(encoding="utf-8"))

    assert payload["rows"][0]["doc_id"] == "empty"
    assert payload["rows"][0]["document_number"] is None
    assert payload["warnings"] == [
        "front_matter_empty",
        "document_number_not_detected_in_front_matter",
        "title_not_detected_in_front_matter",
        "application_number_not_detected_in_front_matter",
    ]
