"""Polygons shaped the way cities are drawn: notches, lakes and shared borders.

A rectangle proves the arithmetic but not the coverage. Real zones have a
concave notch around a park, a lake cut out of the middle and sometimes an
island inside that lake. These tests pin down what such shapes answer, and
which side of a shared border an address falls on.
"""

from __future__ import annotations

import pytest

from delivery_zones import (
    BoundingBox,
    Point,
    Polygon,
    Zone,
    ZoneIndex,
    point_in_polygon,
    scan_coverage,
)

# A U opening north: arms over 0..1 and 2..3, joined by a base below lat 1.
U_SHAPE = [
    [0.0, 0.0],
    [3.0, 0.0],
    [3.0, 3.0],
    [2.0, 3.0],
    [2.0, 1.0],
    [1.0, 1.0],
    [1.0, 3.0],
    [0.0, 3.0],
    [0.0, 0.0],
]


def _rect(min_lon, min_lat, max_lon, max_lat):
    return [
        [min_lon, min_lat],
        [max_lon, min_lat],
        [max_lon, max_lat],
        [min_lon, max_lat],
        [min_lon, min_lat],
    ]


def _zone(zone_id, coordinates, *, kind="Polygon"):
    return Zone.from_geojson(
        {
            "type": "Feature",
            "id": zone_id,
            "geometry": {"type": kind, "coordinates": coordinates},
            "properties": {"store_id": "store-1", "fee_tier": "standard"},
        }
    )


def test_the_notch_of_a_concave_zone_is_not_covered():
    horseshoe = Polygon.from_rings([U_SHAPE])

    assert horseshoe.bbox == BoundingBox(0.0, 0.0, 3.0, 3.0)
    assert point_in_polygon(horseshoe, (0.5, 2.0))
    assert point_in_polygon(horseshoe, (2.5, 2.0))
    assert point_in_polygon(horseshoe, (1.5, 0.5))
    assert horseshoe.bbox.contains(Point(1.5, 2.0))
    assert not point_in_polygon(horseshoe, (1.5, 2.0))


def test_the_area_of_a_concave_ring_is_not_the_area_of_its_envelope():
    horseshoe = Polygon.from_rings([U_SHAPE])

    assert horseshoe.area == pytest.approx(9.0 - 2.0)


def test_a_notch_shows_up_as_one_gap_in_a_scan():
    index = ZoneIndex([_zone("horseshoe", [U_SHAPE])])

    report = scan_coverage(index, spacing=0.2, area=BoundingBox(0.1, 0.1, 2.9, 2.9))

    assert report.samples == 225
    assert len(report.gaps) == 1
    gap = report.gaps[0]
    assert gap.size == 50
    assert 1.0 < gap.bbox.min_lon and gap.bbox.max_lon < 2.0
    assert gap.bbox.min_lat > 1.0
    assert not index.covers(gap.representative)


def test_two_lakes_are_both_cut_out_of_a_zone():
    lakeside = Polygon.from_rings(
        [
            _rect(0.0, 0.0, 4.0, 4.0),
            _rect(1.0, 1.0, 2.0, 2.0),
            _rect(2.5, 2.5, 3.5, 3.5),
        ]
    )

    assert point_in_polygon(lakeside, (0.5, 0.5))
    assert point_in_polygon(lakeside, (2.25, 2.25))
    assert not point_in_polygon(lakeside, (1.5, 1.5))
    assert not point_in_polygon(lakeside, (3.0, 3.0))
    assert lakeside.area == pytest.approx(16.0 - 1.0 - 1.0)


def test_a_hole_border_falls_the_same_way_as_a_zone_border():
    ring = Polygon.from_rings([_rect(0.0, 0.0, 3.0, 3.0), _rect(1.0, 1.0, 2.0, 2.0)])

    assert not point_in_polygon(ring, (1.0, 1.5))
    assert point_in_polygon(ring, (2.0, 1.5))


def test_an_island_inside_a_lake_is_served_again():
    index = ZoneIndex(
        [
            _zone(
                "lakeside",
                [
                    [_rect(0.0, 0.0, 4.0, 4.0), _rect(1.0, 1.0, 3.0, 3.0)],
                    [_rect(1.5, 1.5, 2.5, 2.5)],
                ],
                kind="MultiPolygon",
            )
        ]
    )

    assert index.covers((0.5, 0.5))
    assert not index.covers((1.2, 1.2))
    assert index.covers((2.0, 2.0))
    assert [zone.zone_id for zone in index.zones_containing((2.0, 2.0))] == ["lakeside"]


def test_winding_order_does_not_change_coverage():
    counter_clockwise = Polygon.from_rings([_rect(0.0, 0.0, 1.0, 1.0)])
    clockwise = Polygon.from_rings([list(reversed(_rect(0.0, 0.0, 1.0, 1.0)))])

    for probe in ((0.5, 0.5), (0.1, 0.9), (1.5, 0.5), (0.5, 1.5)):
        assert point_in_polygon(clockwise, probe) == point_in_polygon(
            counter_clockwise, probe
        )
    assert clockwise.area == pytest.approx(counter_clockwise.area)


def test_neighbours_sharing_a_street_do_not_both_claim_it():
    index = ZoneIndex(
        [
            _zone("west", [_rect(0.0, 0.0, 1.0, 1.0)]),
            _zone("east", [_rect(1.0, 0.0, 2.0, 1.0)]),
        ]
    )

    assert [zone.zone_id for zone in index.zones_containing((1.0, 0.5))] == ["east"]
    assert [zone.zone_id for zone in index.zones_containing((0.0, 0.5))] == ["west"]
    assert [zone.zone_id for zone in index.zones_containing((0.5, 0.0))] == ["west"]
    assert index.zones_containing((2.0, 0.5)) == ()
    assert index.zones_containing((0.5, 1.0)) == ()
