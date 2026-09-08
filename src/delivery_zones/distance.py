"""How far the serving store is, and a hook for how long the ride takes.

A lookup ends where dispatch begins: once the zones covering an address are
known, the next question is which store is close and how long a courier needs.
The first half is geometry and lives here, as a great-circle distance between
the address and the store position a zone declares. The second half is not:
travel time depends on streets, traffic and the vehicle, and none of that is in
a polygon. So travel time is a hook rather than a calculation, and the
constant-speed estimator shipped alongside it is a placeholder for tests and
rough delivery tiers, not a routing engine.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from math import asin, cos, radians, sin, sqrt

from .geometry import Point
from .lookup import ZoneIndex
from .resolution import TieBreak, ZonePolicy, all_matches, ranked_by
from .zones import Zone

__all__ = [
    "EARTH_RADIUS_M",
    "DistanceError",
    "ServiceHint",
    "TravelTime",
    "by_nearest_store",
    "constant_speed",
    "distance_to_store",
    "haversine_metres",
    "nearest_store",
    "service_hints",
    "serving_store",
]

EARTH_RADIUS_M = 6371008.8

TravelTime = Callable[[Point, Point, float], float]


class DistanceError(ValueError):
    """Raised when a distance or an estimate is asked for and cannot be given."""


def _as_point(value: Point | Sequence[float]) -> Point:
    return value if isinstance(value, Point) else Point.from_coordinates(value)


def haversine_metres(
    origin: Point | Sequence[float],
    destination: Point | Sequence[float],
) -> float:
    """Great-circle distance between two positions on a spherical earth.

    Accurate to a fraction of a percent over city distances, and still a line
    over the ground rather than a route along it.
    """
    start = _as_point(origin)
    end = _as_point(destination)
    lat_start = radians(start.lat)
    lat_end = radians(end.lat)
    half_lat = (lat_end - lat_start) / 2.0
    half_lon = radians(end.lon - start.lon) / 2.0
    inner = sin(half_lat) ** 2 + cos(lat_start) * cos(lat_end) * sin(half_lon) ** 2
    return 2.0 * EARTH_RADIUS_M * asin(sqrt(min(1.0, inner)))


def serving_store(zone: Zone) -> Point:
    """Where the zone's store stands.

    A zone that declares no position cannot be measured against, and saying so
    beats reporting a distance from somewhere invented.
    """
    if zone.store_location is None:
        raise DistanceError(
            f"zone {zone.zone_id!r} declares no store_location, "
            f"so its distance to an address cannot be measured"
        )
    return zone.store_location


def distance_to_store(zone: Zone, address: Point | Sequence[float]) -> float:
    """Straight-line metres from *address* to the store serving the zone."""
    return haversine_metres(serving_store(zone), _as_point(address))


@dataclass(frozen=True, slots=True)
class ServiceHint:
    """What one matching zone says about reaching an address.

    ``travel_time_s`` is whatever the hook returned, and ``None`` when no hook
    was given.
    """

    zone: Zone
    store: Point
    distance_m: float
    travel_time_s: float | None = None


def service_hints(
    index: ZoneIndex,
    address: Point | Sequence[float],
    *,
    policy: ZonePolicy = all_matches,
    travel_time: TravelTime | None = None,
) -> tuple[ServiceHint, ...]:
    """Distance — and optionally travel time — for the zones covering *address*.

    Hints come back in the order the policy left the zones in, so ranking stays
    the caller's decision. A matched zone without a declared store position
    raises :class:`DistanceError`: an incomplete catalogue is worth seeing.
    """
    target = _as_point(address)
    return tuple(
        _hint(zone, target, travel_time)
        for zone in index.zones_containing(target, policy=policy)
    )


def nearest_store(
    index: ZoneIndex,
    address: Point | Sequence[float],
    *,
    policy: ZonePolicy = all_matches,
    travel_time: TravelTime | None = None,
) -> ServiceHint | None:
    """The closest serving store for *address*, or ``None`` when none reaches it."""
    hints = service_hints(index, address, policy=policy, travel_time=travel_time)
    if not hints:
        return None
    return min(hints, key=lambda hint: hint.distance_m)


def by_nearest_store(address: Point | Sequence[float], tie_break: TieBreak) -> ZonePolicy:
    """Prefer the zone whose store sits closest to *address* in a straight line."""
    target = _as_point(address)
    return ranked_by(lambda zone: distance_to_store(zone, target), tie_break)


def constant_speed(kmh: float, *, detour: float = 1.0) -> TravelTime:
    """A placeholder estimate: the straight line stretched by *detour*, at a fixed speed.

    Enough for tests and rough delivery tiers. Anything that depends on the
    street network belongs in a routing service behind the same hook.
    """
    if isinstance(kmh, bool) or not isinstance(kmh, (int, float)) or kmh <= 0.0:
        raise DistanceError(f"speed must be a positive number of km/h, got {kmh!r}")
    if isinstance(detour, bool) or not isinstance(detour, (int, float)) or detour < 1.0:
        raise DistanceError(f"detour factor must be at least 1.0, got {detour!r}")
    metres_per_second = float(kmh) * 1000.0 / 3600.0
    stretch = float(detour)

    def estimate(store: Point, address: Point, metres: float) -> float:
        return metres * stretch / metres_per_second

    return estimate


def _hint(zone: Zone, address: Point, travel_time: TravelTime | None) -> ServiceHint:
    store = serving_store(zone)
    metres = haversine_metres(store, address)
    return ServiceHint(
        zone=zone,
        store=store,
        distance_m=metres,
        travel_time_s=(
            None if travel_time is None else float(travel_time(store, address, metres))
        ),
    )
