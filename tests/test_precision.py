"""The antimeridian, and the places binary floating point bites.

Coverage here is planar: rings are read in degrees and nothing wraps, so a zone
that reaches across 180 degrees has to be split the way GeoJSON asks. These
tests hold that limitation still, next to the numeric edges a catalogue meets
in practice: zones a few metres across, slivers far thinner than their
envelope, borders that arithmetic misses by one bit, and lattices whose span
divides evenly.
"""

from __future__ import annotations

import pytest

from delivery_zones import (
    BoundingBox,
    GeometryError,
    Point,
    Polygon,
    Zone,
    ZoneIndex,
    haversine_metres,
    point_in_polygon,
    scan_coverage,
)

EAST_OF_THE_SEAM = [
    [179.0, 0.0],
    [180.0, 0.0],
    [180.0, 1.0],
    [179.0, 1.0],
    [179.0, 0.0],
]
WEST_OF_THE_SEAM = [
    [-180.0, 0.0],
    [-179.0, 0.0],
    [-179.0, 1.0],
    [-180.0, 1.0],
    [-180.0, 0.0],
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


def _seam_index():
    return ZoneIndex(
        [
            _zone(
                "pacific",
                [[EAST_OF_THE_SEAM], [WEST_OF_THE_SEAM]],
                kind="MultiPolygon",
            )
        ]
    )


def test_a_ring_written_straight_across_the_seam_wraps_the_wrong_way():
    naive = Polygon.from_rings([_rect(179.0, 0.0, -179.0, 1.0)])

    assert naive.bbox == BoundingBox(-179.0, 0.0, 179.0, 1.0)
    assert point_in_polygon(naive, (0.0, 0.5))
    assert not point_in_polygon(naive, (179.5, 0.5))


def test_splitting_at_the_seam_covers_both_sides_and_nothing_between():
    index = _seam_index()

    assert index.covers((179.5, 0.5))
    assert index.covers((-179.5, 0.5))
    assert not index.covers((0.0, 0.5))
    assert [zone.zone_id for zone in index.zones_containing((179.5, 0.5))] == ["pacific"]


def test_the_seam_itself_belongs_to_one_side_only():
    index = _seam_index()

    assert index.covers((-180.0, 0.5))
    assert not index.covers((180.0, 0.5))


def test_a_longitude_past_the_seam_is_refused():
    with pytest.raises(GeometryError):
        Point.from_coordinates([180.5, 0.5])


def test_distance_across_the_seam_takes_the_short_way():
    metres = haversine_metres((179.9, 0.0), (-179.9, 0.0))

    assert metres == pytest.approx(22239.0, abs=50.0)


def test_the_envelope_of_a_seam_crossing_catalogue_spans_the_globe():
    report = scan_coverage(_seam_index(), spacing=1.0)

    assert report.area == BoundingBox(-180.0, 0.0, 180.0, 1.0)
    assert report.samples == 722
    assert not report.is_complete
    assert report.covered_fraction < 0.05


def test_a_zone_a_few_metres_across_still_answers():
    block = Polygon.from_rings([_rect(13.4, 52.5, 13.40001, 52.50001)])

    assert point_in_polygon(block, (13.400005, 52.500005))
    assert not point_in_polygon(block, (13.400015, 52.500005))


def test_a_border_computed_by_arithmetic_can_land_outside():
    block = Polygon.from_rings([_rect(0.1, 0.1, 0.3, 0.3)])

    assert point_in_polygon(block, (0.2, 0.2))
    assert 0.1 + 0.2 != 0.3
    assert not point_in_polygon(block, (0.2, 0.1 + 0.2))


def test_a_sliver_is_far_thinner_than_its_envelope():
    corridor = Polygon.from_rings(
        [[[0.0, 0.0], [1.0, 1.0], [1.0, 1.0001], [0.0, 0.0001], [0.0, 0.0]]]
    )

    assert corridor.bbox == BoundingBox(0.0, 0.0, 1.0, 1.0001)
    assert point_in_polygon(corridor, (0.5, 0.50005))
    assert corridor.bbox.contains(Point(0.5, 0.9))
    assert not point_in_polygon(corridor, (0.5, 0.9))


def test_a_repeated_vertex_does_not_change_the_answer():
    clean = Polygon.from_rings([_rect(0.0, 0.0, 1.0, 1.0)])
    exported = Polygon.from_rings(
        [
            [
                [0.0, 0.0],
                [0.5, 0.0],
                [0.5, 0.0],
                [1.0, 0.0],
                [1.0, 1.0],
                [0.0, 1.0],
                [0.0, 0.0],
            ]
        ]
    )

    for probe in ((0.5, 0.5), (0.25, 0.75), (1.5, 0.5), (0.5, 1.0)):
        assert point_in_polygon(exported, probe) == point_in_polygon(clean, probe)
    assert exported.area == pytest.approx(clean.area)


def test_an_unclosed_ring_reads_the_same_as_a_closed_one():
    closed = Polygon.from_rings([_rect(0.0, 0.0, 1.0, 1.0)])
    unclosed = Polygon.from_rings([_rect(0.0, 0.0, 1.0, 1.0)[:-1]])

    assert unclosed == closed


def test_a_lattice_whose_span_divides_evenly_keeps_its_last_row():
    index = ZoneIndex([_zone("block", [_rect(0.0, 0.0, 1.0, 1.0)])])

    report = scan_coverage(index, spacing=0.1, area=BoundingBox(0.0, 0.0, 0.3, 0.3))

    assert report.samples == 16
    assert report.is_complete, report.describe()


def test_zones_spread_around_the_globe_are_each_found_on_their_own():
    zones = [
        _zone(f"z{base}", [_rect(float(base), 0.0, float(base) + 1.0, 1.0)])
        for base in range(-170, 150, 20)
    ]
    index = ZoneIndex(zones)

    assert len(index) == 16
    for zone in zones:
        centre = (zone.polygons[0].bbox.min_lon + 0.5, 0.5)
        assert [found.zone_id for found in index.zones_containing(centre)] == [
            zone.zone_id
        ]
        assert not index.covers((zone.polygons[0].bbox.min_lon + 5.0, 0.5))
