"""Point-in-zone lookup over a prepared spatial index.

Coverage questions arrive one address at a time while a catalogue can hold
hundreds of overlapping polygons. Building an index therefore pays the
preparation cost once: every ring is flattened into an edge table and every
polygon is bucketed into a uniform grid keyed by its envelope, so a lookup
tests only the polygons registered in the address' cell instead of scanning
the whole catalogue.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from math import isqrt
from typing import Any

from .geometry import BoundingBox, Point, Polygon
from .resolution import ZonePolicy, all_matches
from .zones import Zone, zones_from_geojson

__all__ = ["ZoneIndex", "point_in_polygon"]

_MAX_GRID_SIDE = 64


def _as_point(value: Any) -> Point:
    return value if isinstance(value, Point) else Point.from_coordinates(value)


@dataclass(frozen=True, slots=True)
class _PreparedRing:
    """A ring reduced to the edges a crossing test can actually hit.

    Each edge is stored as ``(lat_start, lat_end, lon_start, inverse_slope)``.
    Horizontal edges are dropped because a horizontal ray never crosses them,
    which also makes the slope division safe to precompute.
    """

    edges: tuple[tuple[float, float, float, float], ...]

    @classmethod
    def prepare(cls, points: Sequence[Point]) -> "_PreparedRing":
        edges: list[tuple[float, float, float, float]] = []
        previous = points[-1]
        for current in points:
            if previous.lat != current.lat:
                slope = (previous.lon - current.lon) / (previous.lat - current.lat)
                edges.append((current.lat, previous.lat, current.lon, slope))
            previous = current
        return cls(tuple(edges))

    def wraps(self, lon: float, lat: float) -> bool:
        """Even-odd crossing count of a ray running east from the position."""
        inside = False
        for lat_start, lat_end, lon_start, slope in self.edges:
            if (lat_start > lat) != (lat_end > lat):
                if lon < lon_start + (lat - lat_start) * slope:
                    inside = not inside
        return inside


@dataclass(frozen=True, slots=True)
class _PreparedPolygon:
    bbox: BoundingBox
    exterior: _PreparedRing
    holes: tuple[_PreparedRing, ...]

    @classmethod
    def prepare(cls, polygon: Polygon) -> "_PreparedPolygon":
        return cls(
            bbox=polygon.bbox,
            exterior=_PreparedRing.prepare(polygon.exterior),
            holes=tuple(_PreparedRing.prepare(hole) for hole in polygon.holes),
        )

    def contains(self, point: Point) -> bool:
        if not self.bbox.contains(point):
            return False
        if not self.exterior.wraps(point.lon, point.lat):
            return False
        return not any(hole.wraps(point.lon, point.lat) for hole in self.holes)


def point_in_polygon(polygon: Polygon, point: Point | Sequence[float]) -> bool:
    """Test one polygon once; use :class:`ZoneIndex` for repeated lookups."""
    return _PreparedPolygon.prepare(polygon).contains(_as_point(point))


def _envelope(boxes: Sequence[BoundingBox]) -> BoundingBox:
    """The envelope around every box, degenerate when there is nothing to bound.

    An index without polygons also has no grid cells, so its degenerate
    envelope is never consulted.
    """
    if not boxes:
        return BoundingBox(0.0, 0.0, 0.0, 0.0)
    return BoundingBox(
        min(box.min_lon for box in boxes),
        min(box.min_lat for box in boxes),
        max(box.max_lon for box in boxes),
        max(box.max_lat for box in boxes),
    )


def _cell_axis(value: float, low: float, high: float, side: int) -> int:
    span = high - low
    if span <= 0.0:
        return 0
    return min(side - 1, max(0, int((value - low) / span * side)))


class ZoneIndex:
    """Which zones cover an address, answered from prepared geometry.

    Zones may overlap, so a lookup collects every match in the order the zones
    were given and hands the result to a policy. The default policy keeps all
    of them: picking a winner is the caller's decision, not the index's.
    """

    __slots__ = ("_zones", "_polygons", "_bounds", "_side", "_cells")

    def __init__(self, zones: Iterable[Zone]) -> None:
        self._zones: tuple[Zone, ...] = tuple(zones)
        self._polygons: tuple[tuple[int, _PreparedPolygon], ...] = tuple(
            (position, _PreparedPolygon.prepare(polygon))
            for position, zone in enumerate(self._zones)
            for polygon in zone.polygons
        )
        self._bounds = _envelope([prepared.bbox for _, prepared in self._polygons])
        self._side = max(1, min(_MAX_GRID_SIDE, isqrt(len(self._polygons))))
        self._cells = self._bucket()

    @classmethod
    def from_geojson(cls, document: Mapping[str, Any]) -> "ZoneIndex":
        """Read a GeoJSON FeatureCollection, or a single Feature, and index it."""
        return cls(zones_from_geojson(document))

    @property
    def zones(self) -> tuple[Zone, ...]:
        return self._zones

    def zones_containing(
        self,
        point: Point | Sequence[float],
        *,
        policy: ZonePolicy = all_matches,
    ) -> tuple[Zone, ...]:
        """Zones covering the address, narrowed by *policy*.

        Matches reach the policy in the order the zones were given, so a policy
        that ranks on declaration order gets a stable input.
        """
        target = _as_point(point)
        found: list[Zone] = []
        seen: set[int] = set()
        for position, prepared in self._candidates(target):
            if position in seen:
                continue
            if prepared.contains(target):
                seen.add(position)
                found.append(self._zones[position])
        return policy(found)

    def covers(self, point: Point | Sequence[float]) -> bool:
        """Whether at least one zone reaches the address."""
        target = _as_point(point)
        return any(prepared.contains(target) for _, prepared in self._candidates(target))

    def _candidates(self, point: Point) -> Iterable[tuple[int, _PreparedPolygon]]:
        if not self._bounds.contains(point):
            return ()
        cell = (self._column(point.lon), self._row(point.lat))
        return (self._polygons[slot] for slot in self._cells.get(cell, ()))

    def _bucket(self) -> dict[tuple[int, int], tuple[int, ...]]:
        cells: dict[tuple[int, int], list[int]] = {}
        for slot, (_, prepared) in enumerate(self._polygons):
            box = prepared.bbox
            columns = range(self._column(box.min_lon), self._column(box.max_lon) + 1)
            rows = range(self._row(box.min_lat), self._row(box.max_lat) + 1)
            for column in columns:
                for row in rows:
                    cells.setdefault((column, row), []).append(slot)
        return {key: tuple(slots) for key, slots in cells.items()}

    def _column(self, lon: float) -> int:
        return _cell_axis(lon, self._bounds.min_lon, self._bounds.max_lon, self._side)

    def _row(self, lat: float) -> int:
        return _cell_axis(lat, self._bounds.min_lat, self._bounds.max_lat, self._side)

    def __len__(self) -> int:
        return len(self._zones)

    def __repr__(self) -> str:
        return f"<ZoneIndex zones={len(self._zones)} polygons={len(self._polygons)}>"
