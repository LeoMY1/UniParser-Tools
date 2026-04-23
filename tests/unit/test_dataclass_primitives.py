"""Tests for ``Point`` and ``BBox`` in ``uniparser_tools.common.dataclass``.

These invariants were previously only checked in the module ``__main__`` block.
"""
from __future__ import annotations

import pytest

from uniparser_tools.common.dataclass import BBox, Point


class TestPoint:
    def test_arithmetic(self) -> None:
        assert Point(1, 1) + Point(1, 1) == Point(2, 2)
        assert Point(1, 1) - Point(1, 1) == Point(0, 0)
        assert Point(1, 1) * 2 == Point(2, 2)
        assert Point(1, 1) / 2 == Point(0.5, 0.5)

    def test_tuple_arithmetic(self) -> None:
        assert Point(1, 1) + (2, 3) == Point(3, 4)
        assert Point(5, 5) - (2, 3) == Point(3, 2)

    def test_indexing_and_len(self) -> None:
        p = Point(1, 2)
        assert len(p) == 2
        assert p[0] == 1
        assert p[1] == 2
        assert list(iter(p)) == [1, 2]

    def test_rounding_properties(self) -> None:
        assert Point(1.4, 1.6).round.tuple == (1, 2)
        assert Point(1.9, 2.1).int.tuple == (1, 2)
        assert Point(1.1, 1.9).ceil.tuple == (2, 2)
        assert Point(1.9, 1.1).floor.tuple == (1, 1)

    def test_distance(self) -> None:
        assert Point(0, 0).distance_to(Point(3, 4)) == pytest.approx(5.0)
        assert Point(0, 0).distance_to(Point(3, 4), method="manhattan") == pytest.approx(7.0)
        with pytest.raises(NotImplementedError):
            Point(0, 0).distance_to(Point(1, 1), method="bogus")


class TestBBoxGeometry:
    def test_basic_properties(self) -> None:
        b = BBox(1, 1, 3, 4)
        assert b.width == 2
        assert b.height == 3
        assert b.area == 6
        assert b.wh == (2, 3)
        assert b.xyxy == (1, 1, 3, 4)
        assert b.ctr.tuple == (2, 2.5)
        assert len(b) == 4

    def test_intersection_and_union(self) -> None:
        assert BBox(0, 0, 1, 1).intersection(BBox(0, 0, 1, 1)) == BBox(0, 0, 1, 1)
        assert BBox(0, 0, 1, 1).intersection(BBox(1, 1, 2, 2)) == BBox(0, 0, 0, 0)
        assert BBox(0, 0, 1, 1).intersection(BBox(0.5, 0.5, 1.5, 1.5)) == BBox(0.5, 0.5, 1, 1)
        assert BBox(0, 0, 1, 1).union(BBox(2, 2, 3, 3)) == BBox(0, 0, 3, 3)

    def test_iou(self) -> None:
        assert BBox(0, 0, 1, 1).iou(BBox(0, 0, 1, 1)) == 1
        assert BBox(0, 0, 1, 1).iou(BBox(1, 1, 2, 2)) == 0
        assert BBox(0, 0, 1, 1).iou(BBox(0.5, 0.5, 1.5, 1.5)) == pytest.approx(0.25 / (1 + 1 - 0.25))

    def test_iof(self) -> None:
        assert BBox(0, 0, 1, 1).iof(BBox(0, 0, 1, 1)) == 1
        assert BBox(0, 0, 1, 1).iof(BBox(1, 1, 2, 2)) == 0
        assert BBox(0, 0, 1, 1).iof(BBox(0.5, 0.5, 1.5, 1.5)) == pytest.approx(0.25)

    def test_scale_and_shift(self) -> None:
        assert BBox(1, 1, 2, 2) * 4 == BBox(4, 4, 8, 8)
        assert BBox(1, 1, 2, 2) / 2 == BBox(0.5, 0.5, 1, 1)
        assert BBox(1, 1, 2, 2) * [2, 4] == BBox(2, 4, 4, 8)
        assert BBox(1, 1, 2, 2) / [2, 4] == BBox(0.5, 0.25, 1, 0.5)
        assert BBox(0, 0, 4, 4) - (1, 1) == BBox(-1, -1, 3, 3)
        assert BBox(0, 0, 4, 4) + (1, 1) == BBox(1, 1, 5, 5)

    def test_expand_and_shrink(self) -> None:
        wh = (10, 10)
        assert BBox(1, 1, 2, 2).expand(1, wh) == BBox(0, 0, 3, 3)
        assert BBox(1, 1, 2, 2).expand(100, wh) == BBox(0, 0, 10, 10)
        assert BBox(2, 2, 8, 8).shrink(1, wh) == BBox(3, 3, 7, 7)

    def test_corners_and_centers(self) -> None:
        b = BBox(0, 0, 4, 2)
        assert b.tl == Point(0, 0)
        assert b.tr == Point(4, 0)
        assert b.bl == Point(0, 2)
        assert b.br == Point(4, 2)
        assert b.tc == Point(2, 0)
        assert b.bc == Point(2, 2)
        assert b.lc == Point(0, 1)
        assert b.rc == Point(4, 1)
