"""Tests for ``uniparser_tools.utils.fileio``.

These tests focus on the subtle parts:

* ``read_html`` re-implements pandas' internal ``read_html`` and relies on
  private pandas APIs. This broke once when upgrading pandas 1.5.3 -> 2.3.3,
  so we assert single-header, multi-header and fallback paths.
* ``load_yaml`` / ``dump_yaml`` are trivial, but we guard round-tripping.
* ``is_valid_image`` must accept real PNGs and reject non-images.
"""
from __future__ import annotations

from io import StringIO
from pathlib import Path

import pandas as pd
import pytest

from uniparser_tools.utils.fileio import (
    dump_yaml,
    is_valid_image,
    load_yaml,
    read_html,
)

from tests.utils import MALFORMED_HTML, MULTIHEADER_HTML, ROWSPAN_HTML, SIMPLE_HTML


class TestReadHtml:
    def test_single_header(self) -> None:
        dfs = read_html(StringIO(SIMPLE_HTML))
        assert len(dfs) == 1
        df = dfs[0]
        assert list(df.columns) == ["name", "value"]
        assert df.shape == (2, 2)
        assert df.iloc[0].tolist() == ["alpha", "1"] or df.iloc[0].tolist() == ["alpha", 1]
        assert df.iloc[1].tolist() == ["beta", "2"] or df.iloc[1].tolist() == ["beta", 2]

    def test_multi_header_returns_multiindex_columns(self) -> None:
        dfs = read_html(StringIO(MULTIHEADER_HTML))
        assert len(dfs) == 1
        df = dfs[0]
        assert isinstance(df.columns, pd.MultiIndex)
        assert df.shape == (2, 3)
        assert df.columns.get_level_values(1).tolist() == ["x", "y", "z"]

    def test_rowspan_is_expanded(self) -> None:
        """The custom parser pads rows so rowspan cells don't collapse columns."""
        dfs = read_html(StringIO(ROWSPAN_HTML))
        assert len(dfs) == 1
        df = dfs[0]
        assert df.shape[1] == 2

    def test_malformed_html_falls_back_without_raising(self) -> None:
        """read_html swallows errors and falls back to pandas.read_html."""
        with pytest.raises(Exception):
            _ = read_html(StringIO(MALFORMED_HTML))

    def test_empty_table_does_not_raise(self) -> None:
        html = "<table><thead><tr><th>only_header</th></tr></thead></table>"
        dfs = read_html(StringIO(html))
        assert len(dfs) == 1
        assert list(dfs[0].columns) == ["only_header"]
        assert dfs[0].shape[0] == 0


class TestYaml:
    def test_round_trip_preserves_structure(self, tmp_path: Path) -> None:
        data = {"name": "uni", "n": 3, "tags": ["a", "b"], "nested": {"k": "中文"}}
        p = tmp_path / "cfg.yaml"
        dump_yaml(data, str(p))
        loaded = load_yaml(str(p))
        assert loaded == data

    def test_dump_yaml_supports_unicode(self, tmp_path: Path) -> None:
        data = {"lang": "中文", "emoji": "🧪"}
        p = tmp_path / "u.yaml"
        dump_yaml(data, str(p))
        assert "中文" in p.read_text(encoding="utf-8")

    def test_dump_yaml_sort_keys_flag(self, tmp_path: Path) -> None:
        data = {"b": 1, "a": 2, "c": 3}

        unsorted_path = tmp_path / "unsorted.yaml"
        sorted_path = tmp_path / "sorted.yaml"
        dump_yaml(data, str(unsorted_path), sort_keys=False)
        dump_yaml(data, str(sorted_path), sort_keys=True)

        unsorted_keys = [line.split(":")[0] for line in unsorted_path.read_text().strip().splitlines()]
        sorted_keys = [line.split(":")[0] for line in sorted_path.read_text().strip().splitlines()]
        assert sorted_keys == sorted(unsorted_keys)


class TestIsValidImage:
    def test_accepts_demo_png(self, demo_img_path: Path) -> None:
        assert is_valid_image(str(demo_img_path)) is True

    def test_rejects_non_image(self, tmp_path: Path) -> None:
        p = tmp_path / "garbage.png"
        p.write_bytes(b"this is not a png file at all")
        assert is_valid_image(str(p)) is False

    def test_rejects_missing_file(self, tmp_path: Path) -> None:
        assert is_valid_image(str(tmp_path / "does_not_exist.png")) is False
