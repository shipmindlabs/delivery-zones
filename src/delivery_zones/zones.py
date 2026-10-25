"""Delivery zones: polygon coverage plus the metadata a caller acts on.

A zone answers what a dispatcher asks about an address: which store serves it,
what the delivery costs and whether the area is open right now. Zones are read
from GeoJSON features and kept in memory, so no database is involved.

Opening hours belong to the store rather than to the process asking, so service
hours may name an IANA timezone and are read on that clock.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, time, tzinfo
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .geometry import Point, Polygon, polygons_from_geojson

__all__ = [
    "ServiceHours",
    "ServiceWindow",
    "Zone",
    "ZoneError",
    "zones_from_geojson",
]


class ZoneError(ValueError):
    """Raised when a zone description is incomplete or contradictory."""


_WEEKDAY_NAMES = {
    "mon": 0,
    "monday": 0,
    "tue": 1,
    "tuesday": 1,
    "wed": 2,
    "wednesday": 2,
    "thu": 3,
    "thursday": 3,
    "fri": 4,
    "friday": 4,
    "sat": 5,
    "saturday": 5,
    "sun": 6,
    "sunday": 6,
}


def _parse_weekday(value: Any) -> int:
    if isinstance(value, str):
        try:
            return _WEEKDAY_NAMES[value.strip().lower()]
        except KeyError:
            raise ZoneError(f"unknown weekday: {value!r}") from None
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    raise ZoneError(f"weekday must be a name or a number from 0 to 6, got {value!r}")


def _parse_clock(value: Any, role: str) -> time:
    if isinstance(value, time):
        return value
    if isinstance(value, str):
        try:
            return time.fromisoformat(value)
        except ValueError:
            raise ZoneError(f"{role} is not an ISO time: {value!r}") from None
    raise ZoneError(f"{role} must be an ISO time such as '09:00', got {value!r}")


def _parse_timezone(value: Any) -> tzinfo:
    if not isinstance(value, str) or not value.strip():
        raise ZoneError(
            f"timezone must be an IANA name such as 'Europe/Berlin', got {value!r}"
        )
    try:
        return ZoneInfo(value)
    except (ValueError, ZoneInfoNotFoundError):
        raise ZoneError(f"unknown timezone: {value!r}") from None


@dataclass(frozen=True, slots=True)
class ServiceWindow:
    """One opening interval, half-open on the closing side. Monday is 0.

    A window whose closing time precedes its opening time runs past midnight
    into the following day.
    """

    weekday: int
    opens: time
    closes: time

    def __post_init__(self) -> None:
        if not 0 <= self.weekday <= 6:
            raise ZoneError(f"weekday must be between 0 and 6, got {self.weekday!r}")
        if self.opens == self.closes:
            raise ZoneError("a window that opens and closes at the same time is empty")

    @property
    def crosses_midnight(self) -> bool:
        return self.closes < self.opens

    def covers(self, moment: datetime) -> bool:
        clock = moment.time()
        if not self.crosses_midnight:
            return moment.weekday() == self.weekday and self.opens <= clock < self.closes
        if moment.weekday() == self.weekday and clock >= self.opens:
            return True
        return (moment.weekday() - 1) % 7 == self.weekday and clock < self.closes

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "ServiceWindow":
        """Read a window from ``{"weekday": ..., "opens": ..., "closes": ...}``."""
        if not isinstance(data, Mapping):
            raise ZoneError(f"service window must be a mapping, got {data!r}")
        missing = [key for key in ("weekday", "opens", "closes") if key not in data]
        if missing:
            raise ZoneError(f"service window is missing {', '.join(missing)}")
        return cls(
            weekday=_parse_weekday(data["weekday"]),
            opens=_parse_clock(data["opens"], "opens"),
            closes=_parse_clock(data["closes"], "closes"),
        )


@dataclass(frozen=True, slots=True)
class ServiceHours:
    """The windows during which a zone accepts orders.

    A store opens on its own clock. When ``timezone`` names an IANA zone such
    as ``"Europe/Berlin"``, a moment is converted into it before its weekday
    and clock are read, and a naive moment is refused instead of being assumed
    to be the store's local time. Without a timezone the moment is read exactly
    as it arrives, which is what a single-city catalogue on wall-clock
    datetimes wants.
    """

    windows: tuple[ServiceWindow, ...]
    timezone: str | None = None
    tz: tzinfo | None = field(init=False, compare=False, repr=False, default=None)

    def __post_init__(self) -> None:
        object.__setattr__(self, "windows", tuple(self.windows))
        if not self.windows:
            raise ZoneError("service hours need at least one window")
        if self.timezone is not None:
            object.__setattr__(self, "tz", _parse_timezone(self.timezone))

    def local(self, moment: datetime) -> datetime:
        """*moment* on the store's clock, unchanged when no timezone is named."""
        if not isinstance(moment, datetime):
            raise ZoneError(f"moment must be a datetime, got {moment!r}")
        if self.tz is None:
            return moment
        if moment.utcoffset() is None:
            raise ZoneError(
                f"service hours are declared in {self.timezone!r}, so the moment "
                f"must carry a timezone; got the naive {moment!r}"
            )
        return moment.astimezone(self.tz)

    def covers(self, moment: datetime) -> bool:
        reading = self.local(moment)
        return any(window.covers(reading) for window in self.windows)

    @classmethod
    def from_sequence(
        cls,
        data: Iterable[Mapping[str, Any]],
        *,
        timezone: str | None = None,
    ) -> "ServiceHours":
        if isinstance(data, (str, bytes, Mapping)) or not isinstance(data, Iterable):
            raise ZoneError(f"service hours must be a list of windows, got {data!r}")
        return cls(
            tuple(ServiceWindow.from_mapping(item) for item in data),
            timezone=timezone,
        )


@dataclass(frozen=True, slots=True)
class Zone:
    """A delivery area: where it reaches, who serves it and on what terms.

    A zone with no declared service hours is treated as always open, and hours
    that name a timezone are read on the store's clock. Where coverage
    overlaps, ``priority`` ranks the zone against its neighbours: the higher
    number wins, and a zone that declares nothing sits at ``0``.
    ``store_location`` is where the serving store stands; distance hints need
    it, everything else works without it.
    """

    zone_id: str
    store_id: str
    fee_tier: str
    polygons: tuple[Polygon, ...]
    service_hours: ServiceHours | None = None
    priority: int = 0
    store_location: Point | None = None

    def __post_init__(self) -> None:
        for name in ("zone_id", "store_id", "fee_tier"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ZoneError(f"{name} must be a non-empty string, got {value!r}")
        object.__setattr__(self, "polygons", tuple(self.polygons))
        if not self.polygons:
            raise ZoneError(f"zone {self.zone_id!r} covers no polygons")
        if isinstance(self.priority, bool) or not isinstance(self.priority, int):
            raise ZoneError(f"priority must be an integer, got {self.priority!r}")
        if self.store_location is not None and not isinstance(self.store_location, Point):
            object.__setattr__(
                self, "store_location", Point.from_coordinates(self.store_location)
            )

    def is_open_at(self, moment: datetime) -> bool:
        return self.service_hours is None or self.service_hours.covers(moment)

    @classmethod
    def from_geojson(cls, feature: Mapping[str, Any]) -> "Zone":
        """Build a zone from a GeoJSON Feature.

        ``properties`` must carry ``store_id`` and ``fee_tier``; ``zone_id``
        falls back to the feature's ``id``, while ``service_hours``,
        ``timezone``, ``priority`` and ``store_location`` are optional.
        """
        if not isinstance(feature, Mapping):
            raise ZoneError(f"feature must be a GeoJSON mapping, got {type(feature).__name__}")
        if feature.get("type") != "Feature":
            raise ZoneError(f"expected a GeoJSON Feature, got {feature.get('type')!r}")
        geometry = feature.get("geometry")
        if geometry is None:
            raise ZoneError("feature has no geometry")
        properties = feature.get("properties") or {}
        if not isinstance(properties, Mapping):
            raise ZoneError(f"feature properties must be a mapping, got {properties!r}")
        missing = [key for key in ("store_id", "fee_tier") if key not in properties]
        if missing:
            raise ZoneError(f"feature properties are missing {', '.join(missing)}")
        hours = properties.get("service_hours")
        return cls(
            zone_id=properties.get("zone_id", feature.get("id")),
            store_id=properties["store_id"],
            fee_tier=properties["fee_tier"],
            polygons=polygons_from_geojson(geometry),
            service_hours=(
                None
                if hours is None
                else ServiceHours.from_sequence(
                    hours, timezone=properties.get("timezone")
                )
            ),
            priority=properties.get("priority", 0),
            store_location=properties.get("store_location"),
        )


def zones_from_geojson(document: Mapping[str, Any]) -> tuple[Zone, ...]:
    """Read a GeoJSON FeatureCollection, or a single Feature, into zones."""
    if not isinstance(document, Mapping):
        raise ZoneError(f"document must be a GeoJSON mapping, got {type(document).__name__}")
    kind = document.get("type")
    if kind == "Feature":
        return (Zone.from_geojson(document),)
    if kind == "FeatureCollection":
        features = document.get("features")
        if isinstance(features, (str, bytes)) or not isinstance(features, Sequence):
            raise ZoneError("FeatureCollection has no list of features")
        return tuple(Zone.from_geojson(feature) for feature in features)
    raise ZoneError(f"unsupported GeoJSON type: {kind!r}")
