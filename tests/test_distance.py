"""Distance hints: how far the store is, and who is allowed to guess the ride."""

from __future__ import annotations

import pytest

from delivery_zones import (
    AmbiguousCoverage,
    DistanceError,
    Point,
    TieBreak,
    Zone,
    ZoneIndex,
    by_nearest_store,
    constant_speed,
    distance_to_store,
    haversine_metres,
    nearest_store,
    service_hints,
)


def _ring(min_lon, min_lat, max_lon, max_lat):
    return [
        [min_lon, min_lat],
        [max_lon, min_lat],
        [max_lon, max_lat],
        [min_lon, max_lat],
        [min_lon, min_lat],
    ]


def _zone(zone_id, box, *, store=None):
    properties = {"store_id": f"store-{zone_id}", "fee_tier": "standard"}
    if store is not None:
        properties["store_location"] = list(store)
    return Zone.from_geojson(
        {
            "type": "Feature",
            "id": zone_id,
            "geometry": {"type": "Polygon", "coordinates": [_ring(*box)]},
            "properties": properties,
        }
    )


def test_a_degree_of_latitude_is_about_111_kilometres():
    metres = haversine_metres((13.4, 52.0), (13.4, 53.0))

    assert metres == pytest.approx(111195.0, abs=100.0)


def test_distance_is_symmetric_and_zero_at_the_same_place():
    here = Point(13.4, 52.52)
    there = Point(13.5, 52.48)

    assert haversine_metres(here, here) == 0.0
    assert haversine_metres(here, there) == pytest.approx(haversine_metres(there, here))


def test_a_store_position_is_read_from_the_feature():
    zone = _zone("downtown", (0.0, 0.0, 1.0, 1.0), store=(0.4, 0.5))

    assert zone.store_location == Point(0.4, 0.5)
    assert distance_to_store(zone, (0.4, 0.51)) == pytest.approx(1111.9, abs=5.0)


def test_hints_arrive_one_per_matching_zone():
    index = ZoneIndex(
        [
            _zone("hub", (0.0, 0.0, 1.0, 1.0), store=(0.9, 0.5)),
            _zone("ring", (0.2, 0.2, 0.8, 0.8), store=(0.45, 0.5)),
        ]
    )

    hints = service_hints(index, (0.5, 0.5))

    assert [hint.zone.zone_id for hint in hints] == ["hub", "ring"]
    assert hints[1].distance_m < hints[0].distance_m
    assert all(hint.travel_time_s is None for hint in hints)


def test_the_travel_time_hook_sees_store_address_and_distance():
    index = ZoneIndex([_zone("hub", (0.0, 0.0, 1.0, 1.0), store=(0.4, 0.5))])
    seen = []

    def hook(store, address, metres):
        seen.append((store, address, metres))
        return metres / 5.0

    hint = service_hints(index, (0.5, 0.5), travel_time=hook)[0]

    assert seen == [(Point(0.4, 0.5), Point(0.5, 0.5), hint.distance_m)]
    assert hint.travel_time_s == pytest.approx(hint.distance_m / 5.0)


def test_constant_speed_divides_the_stretched_line_by_the_speed():
    estimate = constant_speed(30.0)
    stretched = constant_speed(30.0, detour=1.5)

    assert estimate(Point(0.0, 0.0), Point(0.0, 0.1), 10_000.0) == pytest.approx(1200.0)
    assert stretched(Point(0.0, 0.0), Point(0.0, 0.1), 10_000.0) == pytest.approx(1800.0)


def test_an_impossible_speed_is_refused():
    with pytest.raises(DistanceError):
        constant_speed(0.0)

    with pytest.raises(DistanceError):
        constant_speed(30.0, detour=0.5)


def test_nearest_store_picks_the_closer_of_two_overlapping_zones():
    index = ZoneIndex(
        [
            _zone("hub", (0.0, 0.0, 1.0, 1.0), store=(0.9, 0.5)),
            _zone("ring", (0.2, 0.2, 0.8, 0.8), store=(0.45, 0.5)),
        ]
    )

    hint = nearest_store(index, (0.5, 0.5))

    assert hint is not None
    assert hint.zone.zone_id == "ring"
    assert hint.store == Point(0.45, 0.5)


def test_an_address_no_zone_reaches_has_no_nearest_store():
    index = ZoneIndex([_zone("hub", (0.0, 0.0, 1.0, 1.0), store=(0.4, 0.5))])

    assert nearest_store(index, (5.0, 5.0)) is None
    assert service_hints(index, (5.0, 5.0)) == ()


def test_by_nearest_store_narrows_a_lookup_to_the_closest():
    index = ZoneIndex(
        [
            _zone("hub", (0.0, 0.0, 1.0, 1.0), store=(0.9, 0.5)),
            _zone("ring", (0.2, 0.2, 0.8, 0.8), store=(0.45, 0.5)),
        ]
    )

    chosen = index.zones_containing(
        (0.5, 0.5), policy=by_nearest_store((0.5, 0.5), TieBreak.FIRST)
    )

    assert [zone.zone_id for zone in chosen] == ["ring"]


def test_two_zones_sharing_a_store_do_not_get_a_silent_winner():
    index = ZoneIndex(
        [
            _zone("north", (0.0, 0.0, 1.0, 1.0), store=(0.4, 0.5)),
            _zone("south", (0.2, 0.2, 0.8, 0.8), store=(0.4, 0.5)),
        ]
    )

    with pytest.raises(AmbiguousCoverage):
        index.zones_containing((0.5, 0.5), policy=by_nearest_store((0.5, 0.5), TieBreak.RAISE))


def test_a_zone_without_a_store_position_cannot_be_measured():
    index = ZoneIndex([_zone("hub", (0.0, 0.0, 1.0, 1.0))])

    with pytest.raises(DistanceError):
        service_hints(index, (0.5, 0.5))

    assert index.covers((0.5, 0.5))
