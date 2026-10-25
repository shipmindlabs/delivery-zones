"""Opening hours belong to the store, not to the machine asking.

A window written as 18:00-02:00 is the store's own clock, so a server running
on UTC must convert before it reads a weekday and a time. These tests pin that
down from both sides: a zoned zone converts and refuses a naive moment, while
hours without a timezone keep reading the wall clock they are given.
"""

from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import pytest

from delivery_zones import (
    ServiceHours,
    TieBreak,
    Zone,
    ZoneError,
    ZoneIndex,
    by_priority,
    open_at,
    then,
)

try:
    BERLIN = ZoneInfo("Europe/Berlin")
    NEW_YORK = ZoneInfo("America/New_York")
except ZoneInfoNotFoundError:  # pragma: no cover - depends on the host
    pytest.skip("the system timezone database is unavailable", allow_module_level=True)

ADDRESS = (0.5, 0.5)
MORNINGS = [{"weekday": "mon", "opens": "09:00", "closes": "12:00"}]
NIGHTS = [{"weekday": "mon", "opens": "18:00", "closes": "02:00"}]
AFTER_MIDNIGHT = [{"weekday": "tue", "opens": "00:30", "closes": "02:00"}]
OFFICE = [{"weekday": "mon", "opens": "09:00", "closes": "17:00"}]

# Monday 23:30 UTC is Tuesday 01:30 in Berlin and Tuesday 08:30 in Tokyo.
LATE_MONDAY_UTC = datetime(2026, 8, 24, 23, 30, tzinfo=timezone.utc)


def _zone(zone_id, *, hours=None, tz=None, priority=0):
    properties = {
        "store_id": f"store-{zone_id}",
        "fee_tier": "standard",
        "priority": priority,
    }
    if hours is not None:
        properties["service_hours"] = hours
    if tz is not None:
        properties["timezone"] = tz
    return Zone.from_geojson(
        {
            "type": "Feature",
            "id": zone_id,
            "geometry": {
                "type": "Polygon",
                "coordinates": [
                    [[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0], [0.0, 0.0]]
                ],
            },
            "properties": properties,
        }
    )


def test_half_past_eleven_utc_is_open_in_a_store_closing_at_two_in_berlin():
    zone = _zone("night", hours=NIGHTS, tz="Europe/Berlin")

    assert zone.is_open_at(LATE_MONDAY_UTC)
    assert not zone.is_open_at(datetime(2026, 8, 25, 0, 30, tzinfo=timezone.utc))


def test_the_weekday_is_read_on_the_store_clock_too():
    zoned = _zone("after-midnight", hours=AFTER_MIDNIGHT, tz="Europe/Berlin")
    unzoned = _zone("after-midnight", hours=AFTER_MIDNIGHT)

    assert zoned.is_open_at(LATE_MONDAY_UTC)
    assert not unzoned.is_open_at(LATE_MONDAY_UTC)


def test_a_moment_from_a_third_timezone_converts_the_same_way():
    zone = _zone("night", hours=NIGHTS, tz="Europe/Berlin")
    moment = datetime(2026, 8, 24, 19, 30, tzinfo=NEW_YORK)

    assert moment == LATE_MONDAY_UTC
    assert zone.is_open_at(moment)


def test_the_same_utc_clock_reads_differently_in_summer_and_winter():
    zone = _zone("office", hours=OFFICE, tz="Europe/Berlin")

    assert zone.is_open_at(datetime(2026, 8, 24, 7, 30, tzinfo=timezone.utc))
    assert not zone.is_open_at(datetime(2026, 1, 26, 7, 30, tzinfo=timezone.utc))
    assert zone.is_open_at(datetime(2026, 1, 26, 8, 30, tzinfo=timezone.utc))


def test_a_naive_moment_is_refused_by_zoned_hours():
    zone = _zone("office", hours=OFFICE, tz="Europe/Berlin")

    with pytest.raises(ZoneError):
        zone.is_open_at(datetime(2026, 8, 24, 10, 0))


def test_hours_without_a_timezone_read_the_clock_they_are_given():
    zone = _zone("local", hours=MORNINGS)

    assert zone.is_open_at(datetime(2026, 8, 24, 10, 0))
    assert zone.is_open_at(datetime(2026, 8, 24, 10, 0, tzinfo=timezone.utc))
    assert zone.is_open_at(datetime(2026, 8, 24, 10, 0, tzinfo=NEW_YORK))
    assert not zone.is_open_at(datetime(2026, 8, 24, 13, 0, tzinfo=timezone.utc))


def test_a_timezone_that_names_nothing_fails_the_load():
    with pytest.raises(ZoneError):
        _zone("nowhere", hours=MORNINGS, tz="Mars/Olympus")

    with pytest.raises(ZoneError):
        _zone("blank", hours=MORNINGS, tz="")


def test_the_timezone_is_kept_and_the_local_reading_is_available():
    hours = ServiceHours.from_sequence(OFFICE, timezone="Europe/Berlin")

    assert hours.timezone == "Europe/Berlin"
    assert hours.local(LATE_MONDAY_UTC) == datetime(2026, 8, 25, 1, 30, tzinfo=BERLIN)
    assert ServiceHours.from_sequence(OFFICE).local(LATE_MONDAY_UTC) is LATE_MONDAY_UTC


def test_a_filter_elects_the_store_that_is_open_where_it_stands():
    index = ZoneIndex(
        [
            _zone("tokyo", hours=NIGHTS, tz="Asia/Tokyo", priority=10),
            _zone("berlin", hours=NIGHTS, tz="Europe/Berlin", priority=1),
        ]
    )
    policy = then(open_at(LATE_MONDAY_UTC), by_priority(TieBreak.FIRST))

    assert [zone.zone_id for zone in index.zones_containing(ADDRESS, policy=policy)] == [
        "berlin"
    ]
