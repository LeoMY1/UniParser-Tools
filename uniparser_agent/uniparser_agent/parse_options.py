"""Scientific-paper parse preset (matches uniparser_tools.cli.core.parse_options)."""

from __future__ import annotations

SCIENTIFIC_PAPER_TRIGGER: dict[str, object] = {
    "lang": "unknown",
    "sync": True,
    "textual": 2,
    "equation": 2,
    "table": 2,
    "chart": -1,
    "figure": -1,
    "expression": -1,
    "molecule": 1,
    "ordering_method": "xy_cut_exp",
}
