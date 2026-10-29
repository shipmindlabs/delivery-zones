"""Ambiguity scans: the places a policy cannot pick a winner.

A hole in coverage refuses an order loudly; an unresolvable overlap serves it
quietly from whichever zone happened to be declared first. These tests pin the
second case down: equal-ranked rings have to show up as an area of the map, and
a tie-break that decides has to leave the map clean.
"""

from __future__ import annotations

import pytest

from delivery_zones import (
    AmbiguousCoverage,
    BoundingBox,
    CoverageError,
    TieBreak,
    Zone,
    ZoneIndex,
    by_priority,
    by_smallest_area,
    scan_ambiguity,
)

# A lattice whose columns avoid the rings' own borders.
AREA = BoundingBox(0.05, 0.05, 1.45, 0.85)
SPACING = 0.1


def _ring(min_lon, min_lat, max_lon, max_lat):
    return [
        [min_lon, min_lat],
        [max_lon, min_lat],
        [max_lon, max_lat],
        [min_lon, max_lat],
        [min_lon, min_lat],
    ]


def _zone(zone_id, box, *, priority=0):
    return Zone.from_geojson(
        {
            "type": "Feature",
            "id": zone_id,
            "geometry": {"type": "Polygon", "coordinates": [_ring(*box)]},
            "properties": {
                "store_id": f"store-{zone_id}",
                "fee_tier": "standard",
                "priority": priority,
            },
        }
    )


def _twin_rings(east_priority=5):
    return ZoneIndex(
        [
            _zone("west", (0.0, 0.0, 1.0, 1.0), priority=5),
            _zone("east", (0.5, 0.0, 1.5, 1.0), priority=east_priority),
        ]
    )


def test_two_equal_priority_rings_yield_one_gap_over_their_overlap():
    index = _twin_rings()

    report = scan_ambiguity(
        index, by_priority(TieBreak.RAISE), spacing=SPACING, area=AREA
    )

    assert report.samples == 135
    assert not report.is_decided
    assert report.ambiguous == 45
    assert len(report.gaps) == 1
    gap = report.gaps[0]
    assert gap.size == 45
    assert 0.5 <= gap.bbox.min_lon and gap.bbox.max_lon < 1.0
    assert report.zone_ids == ("west", "east")
    assert "west" in report.describe()


def test_the_representative_of_a_gap_still_raises():
    index = _twin_rings()
    policy = by_priority(TieBreak.RAISE)

    report = scan_ambiguity(index, policy, spacing=SPACING, area=AREA)

    with pytest.raises(AmbiguousCoverage):
        index.zones_containing(report.gaps[0].representative, policy=policy)


def test_a_tie_break_that_keeps_the_first_zone_decides_everywhere():
    index = _twin_rings()

    report = scan_ambiguity(
        index, by_priority(TieBreak.FIRST), spacing=SPACING, area=AREA
    )

    assert report.is_decided, report.describe()
    assert report.ambiguous == 0
    assert report.gaps == ()
    assert report.zone_ids == ()
    assert "135" in report.describe()


def test_unequal_priorities_settle_the_overlap():
    index = _twin_rings(east_priority=1)

    report = scan_ambiguity(
        index, by_priority(TieBreak.RAISE), spacing=SPACING, area=AREA
    )

    assert report.is_decided, report.describe()


def test_rings_of_the_same_size_are_ambiguous_by_area_too():
    index = _twin_rings(east_priority=1)

    report = scan_ambiguity(
        index, by_smallest_area(TieBreak.RAISE), spacing=SPACING, area=AREA
    )

    assert report.ambiguous == 45
    assert len(report.gaps) == 1


def test_positions_no_zone_reaches_are_not_ambiguous():
    index = ZoneIndex(
        [
            _zone("west", (0.0, 0.0, 1.0, 1.0), priority=5),
            _zone("east", (2.0, 0.0, 3.0, 1.0), priority=5),
        ]
    )

    report = scan_ambiguity(
        index,
        by_priority(TieBreak.RAISE),
        spacing=0.2,
        area=BoundingBox(0.1, 0.1, 2.9, 0.9),
    )

    assert report.is_decided, report.describe()


def test_two_undecidable_overlaps_are_reported_separately():
    index = ZoneIndex(
        [
            _zone("west", (0.0, 0.0, 1.0, 1.0), priority=5),
            _zone("east", (0.5, 0.0, 1.5, 1.0), priority=5),
            _zone("far-west", (3.0, 0.0, 4.0, 1.0), priority=7),
            _zone("far-east", (3.5, 0.0, 4.5, 1.0), priority=7),
        ]
    )

    report = scan_ambiguity(
        index,
        by_priority(TieBreak.RAISE),
        spacing=SPACING,
        area=BoundingBox(0.05, 0.05, 4.45, 0.85),
    )

    assert report.samples == 405
    assert [gap.size for gap in report.gaps] == [45, 45]
    assert report.gaps[0].bbox.max_lon < report.gaps[1].bbox.min_lon


def test_a_scan_checks_its_spacing_policy_and_budget():
    index = _twin_rings()

    with pytest.raises(CoverageError):
        scan_ambiguity(index, by_priority(TieBreak.RAISE), spacing=0.0)

    with pytest.raises(CoverageError):
        scan_ambiguity(
            index, by_priority(TieBreak.RAISE), spacing=SPACING, max_samples=8
        )

    with pytest.raises(TypeError):
        scan_ambiguity(index, "highest priority wins", spacing=SPACING)
