"""Policies that compose: a filter ahead of a ranking.

A closed zone should not win on priority, so the order of the stages carries
the rule. These tests pin the composition down from both sides: filtering
first elects an open zone, ranking first elects a closed one and the filter
behind it leaves nothing at all.
"""

from __future__ import annotations

from datetime import datetime

import pytest

from delivery_zones import (
    AmbiguousCoverage,
    TieBreak,
    Zone,
    ZoneIndex,
    all_matches,
    by_priority,
    open_at,
    then,
)

MONDAY_MORNING = datetime(2026, 8, 24, 10, 0)
MONDAY_EVENING = datetime(2026, 8, 24, 22, 0)
MORNINGS = [{"weekday": "mon", "opens": "09:00", "closes": "12:00"}]
EVENINGS = [{"weekday": "mon", "opens": "18:00", "closes": "23:00"}]

ADDRESS = (0.5, 0.5)


def _ring(min_lon, min_lat, max_lon, max_lat):
    return [
        [min_lon, min_lat],
        [max_lon, min_lat],
        [max_lon, max_lat],
        [min_lon, max_lat],
        [min_lon, min_lat],
    ]


def _zone(zone_id, box, *, priority=0, hours=None):
    properties = {
        "store_id": f"store-{zone_id}",
        "fee_tier": "standard",
        "priority": priority,
    }
    if hours is not None:
        properties["service_hours"] = hours
    return Zone.from_geojson(
        {
            "type": "Feature",
            "id": zone_id,
            "geometry": {"type": "Polygon", "coordinates": [_ring(*box)]},
            "properties": properties,
        }
    )


def _day_and_night():
    return ZoneIndex(
        [
            _zone("hub", (0.0, 0.0, 1.0, 1.0), priority=10, hours=MORNINGS),
            _zone("ring", (0.2, 0.2, 0.8, 0.8), priority=1, hours=EVENINGS),
        ]
    )


def test_a_closed_high_priority_zone_loses_to_an_open_lower_one():
    index = _day_and_night()
    policy = then(open_at(MONDAY_EVENING), by_priority(TieBreak.FIRST))

    assert [zone.zone_id for zone in index.zones_containing(ADDRESS, policy=policy)] == [
        "ring"
    ]


def test_the_same_composition_elects_the_hub_while_it_is_open():
    index = _day_and_night()
    policy = then(open_at(MONDAY_MORNING), by_priority(TieBreak.FIRST))

    assert [zone.zone_id for zone in index.zones_containing(ADDRESS, policy=policy)] == [
        "hub"
    ]


def test_ranking_before_filtering_discards_its_own_winner():
    index = _day_and_night()
    policy = then(by_priority(TieBreak.FIRST), open_at(MONDAY_EVENING))

    assert index.zones_containing(ADDRESS, policy=policy) == ()


def test_an_address_whose_zones_are_all_closed_comes_back_empty():
    index = _day_and_night()
    policy = then(open_at(datetime(2026, 8, 24, 15, 0)), by_priority(TieBreak.FIRST))

    assert index.zones_containing(ADDRESS, policy=policy) == ()


def test_a_zone_without_service_hours_passes_every_moment():
    index = ZoneIndex([_zone("always", (0.0, 0.0, 1.0, 1.0))])

    for moment in (MONDAY_MORNING, MONDAY_EVENING, datetime(2026, 8, 25, 3, 0)):
        chosen = index.zones_containing(ADDRESS, policy=open_at(moment))
        assert [zone.zone_id for zone in chosen] == ["always"]


def test_a_filter_keeps_declaration_order():
    index = ZoneIndex(
        [
            _zone("first", (0.0, 0.0, 1.0, 1.0)),
            _zone("closed", (0.2, 0.2, 0.8, 0.8), hours=EVENINGS),
            _zone("second", (0.3, 0.3, 0.7, 0.7), hours=MORNINGS),
        ]
    )

    chosen = index.zones_containing(ADDRESS, policy=open_at(MONDAY_MORNING))

    assert [zone.zone_id for zone in chosen] == ["first", "second"]


def test_a_filter_can_settle_what_a_ranking_calls_ambiguous():
    index = ZoneIndex(
        [
            _zone("hub", (0.0, 0.0, 1.0, 1.0), priority=5, hours=MORNINGS),
            _zone("ring", (0.2, 0.2, 0.8, 0.8), priority=5, hours=EVENINGS),
        ]
    )

    with pytest.raises(AmbiguousCoverage):
        index.zones_containing(ADDRESS, policy=by_priority(TieBreak.RAISE))

    chosen = index.zones_containing(
        ADDRESS, policy=then(open_at(MONDAY_MORNING), by_priority(TieBreak.RAISE))
    )
    assert [zone.zone_id for zone in chosen] == ["hub"]


def test_chaining_nothing_keeps_every_match():
    index = _day_and_night()

    assert index.zones_containing(ADDRESS, policy=then()) == index.zones_containing(
        ADDRESS
    )
    assert index.zones_containing(
        ADDRESS, policy=then(all_matches, all_matches)
    ) == index.zones_containing(ADDRESS)


def test_a_filter_needs_a_moment_and_a_chain_needs_policies():
    with pytest.raises(TypeError):
        open_at("monday morning")

    with pytest.raises(TypeError):
        then(by_priority(TieBreak.FIRST), "open now")
