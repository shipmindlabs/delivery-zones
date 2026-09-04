"""Coverage scans: a hole should fail a test run, not an order."""

from __future__ import annotations

import pytest

from delivery_zones import (
    BoundingBox,
    CoverageError,
    Point,
    Zone,
    ZoneIndex,
    scan_coverage,
    uncovered_points,
    zones_envelope,
)


def _ring(min_lon, min_lat, max_lon, max_lat):
    return [
        [min_lon, min_lat],
        [max_lon, min_lat],
        [max_lon, max_lat],
        [min_lon, max_lat],
        [min_lon, min_lat],
    ]


def _zone(zone_id, box, *, hole=None):
    rings = [_ring(*box)]
    if hole is not None:
        rings.append(_ring(*hole))
    return Zone.from_geojson(
        {
            "type": "Feature",
            "id": zone_id,
            "geometry": {"type": "Polygon", "coordinates": rings},
            "properties": {"store_id": "store-1", "fee_tier": "standard"},
        }
    )


def test_solid_coverage_reports_no_gaps():
    index = ZoneIndex([_zone("a", (0.0, 0.0, 1.0, 1.0))])

    report = scan_coverage(index, spacing=0.2, area=BoundingBox(0.1, 0.1, 0.9, 0.9))

    assert report.is_complete, report.describe()
    assert report.samples == 25
    assert report.covered == 25
    assert report.uncovered == 0
    assert report.covered_fraction == 1.0


def test_strip_between_two_zones_is_found():
    index = ZoneIndex(
        [_zone("west", (0.0, 0.0, 1.0, 1.0)), _zone("east", (2.0, 0.0, 3.0, 1.0))]
    )

    report = scan_coverage(index, spacing=0.2, area=BoundingBox(0.1, 0.1, 2.9, 0.9))

    assert not report.is_complete
    assert report.samples == 75
    assert report.uncovered == 25
    assert len(report.gaps) == 1
    gap = report.gaps[0]
    assert gap.size == 25
    assert 1.0 < gap.bbox.min_lon and gap.bbox.max_lon < 2.0
    assert not index.covers(gap.representative)
    assert "uncovered" in report.describe()


def test_separate_holes_are_reported_separately():
    index = ZoneIndex(
        [
            _zone("west", (0.0, 0.0, 1.0, 1.0)),
            _zone("middle", (2.0, 0.0, 3.0, 1.0)),
            _zone("east", (4.0, 0.0, 5.0, 1.0)),
        ]
    )

    report = scan_coverage(index, spacing=0.2, area=BoundingBox(0.1, 0.1, 4.9, 0.9))

    assert [gap.size for gap in report.gaps] == [25, 25]
    assert report.gaps[0].bbox.min_lon < report.gaps[1].bbox.min_lon


def test_hole_inside_a_polygon_is_uncovered():
    index = ZoneIndex([_zone("ring", (0.0, 0.0, 3.0, 3.0), hole=(1.0, 1.0, 2.0, 2.0))])

    report = scan_coverage(index, spacing=0.2, area=BoundingBox(0.1, 0.1, 2.9, 2.9))

    assert len(report.gaps) == 1
    gap = report.gaps[0]
    assert gap.size == 25
    assert 1.0 < gap.bbox.min_lon and gap.bbox.max_lon < 2.0
    assert 1.0 < gap.bbox.min_lat and gap.bbox.max_lat < 2.0


def test_scan_defaults_to_the_envelope_of_the_zones():
    index = ZoneIndex(
        [_zone("west", (0.0, 0.0, 1.0, 1.0)), _zone("east", (2.0, 0.5, 3.0, 2.0))]
    )

    report = scan_coverage(index, spacing=0.5)

    assert report.area == BoundingBox(0.0, 0.0, 3.0, 2.0)
    assert report.area == zones_envelope(index.zones)


def test_an_area_the_zones_never_reach_is_all_gap():
    index = ZoneIndex([_zone("west", (0.0, 0.0, 1.0, 1.0))])

    report = scan_coverage(index, spacing=0.5, area=BoundingBox(10.0, 10.0, 11.0, 11.0))

    assert report.covered == 0
    assert report.covered_fraction == 0.0
    assert len(report.gaps) == 1
    assert report.gaps[0].size == report.samples == 9


def test_uncovered_points_keeps_the_order_given():
    index = ZoneIndex([_zone("west", (0.0, 0.0, 1.0, 1.0))])

    missing = uncovered_points(index, [(0.5, 0.5), (5.0, 5.0), Point(0.2, 0.2), [7.0, 1.0]])

    assert missing == (Point(5.0, 5.0), Point(7.0, 1.0))


def test_spacing_must_be_positive():
    index = ZoneIndex([_zone("west", (0.0, 0.0, 1.0, 1.0))])

    with pytest.raises(CoverageError):
        scan_coverage(index, spacing=0.0)


def test_a_scan_that_would_run_away_is_refused():
    index = ZoneIndex([_zone("west", (0.0, 0.0, 1.0, 1.0))])

    with pytest.raises(CoverageError):
        scan_coverage(index, spacing=0.5, max_samples=8)


def test_an_empty_catalogue_needs_an_explicit_area():
    index = ZoneIndex([])

    with pytest.raises(CoverageError):
        scan_coverage(index, spacing=0.5)

    report = scan_coverage(index, spacing=0.5, area=BoundingBox(0.0, 0.0, 1.0, 1.0))
    assert report.covered == 0
    assert len(report.gaps) == 1
