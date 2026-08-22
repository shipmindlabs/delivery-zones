"""Polygon geometry for delivery coverage, read from GeoJSON.

Positions follow the GeoJSON axis order (longitude, then latitude) and rings
are stored without the repeated closing position, which keeps later traversal
free of special cases.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

__all__ = [
    "BoundingBox",
    "GeometryError",
    "Point",
    "Polygon",
    "polygons_from_geojson",
]


class GeometryError(ValueError):
    """Raised when coordinates do not describe a usable polygon."""


@dataclass(frozen=True, slots=True)
class Point:
    """A WGS84 position: longitude first, then latitude."""

    lon: float
    lat: float

    def __post_init__(self) -> None:
        if not -180.0 <= self.lon <= 180.0:
            raise GeometryError(f"longitude out of range: {self.lon!r}")
        if not -90.0 <= self.lat <= 90.0:
            raise GeometryError(f"latitude out of range: {self.lat!r}")

    @classmethod
    def from_coordinates(cls, coordinates: Any) -> "Point":
        """Read a GeoJSON position; a third element (altitude) is dropped."""
        if isinstance(coordinates, (str, bytes)) or not isinstance(coordinates, Sequence):
            raise GeometryError(f"position must be a coordinate pair, got {coordinates!r}")
        if len(coordinates) < 2:
            raise GeometryError(f"position needs longitude and latitude, got {coordinates!r}")
        lon, lat = coordinates[0], coordinates[1]
        for value in (lon, lat):
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise GeometryError(f"position coordinates must be numbers, got {coordinates!r}")
        return cls(float(lon), float(lat))


@dataclass(frozen=True, slots=True)
class BoundingBox:
    """The axis-aligned envelope of a set of positions."""

    min_lon: float
    min_lat: float
    max_lon: float
    max_lat: float

    @classmethod
    def around(cls, points: Iterable[Point]) -> "BoundingBox":
        collected = tuple(points)
        if not collected:
            raise GeometryError("cannot bound an empty set of positions")
        lons = [point.lon for point in collected]
        lats = [point.lat for point in collected]
        return cls(min(lons), min(lats), max(lons), max(lats))

    def contains(self, point: Point) -> bool:
        return (
            self.min_lon <= point.lon <= self.max_lon
            and self.min_lat <= point.lat <= self.max_lat
        )


@dataclass(frozen=True, slots=True)
class Polygon:
    """An exterior ring with optional holes.

    Rings accept either :class:`Point` instances or raw coordinate pairs, and a
    repeated closing position is discarded on the way in.
    """

    exterior: tuple[Point, ...]
    holes: tuple[tuple[Point, ...], ...] = ()
    bbox: BoundingBox = field(init=False, compare=False, repr=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "exterior", _ring(self.exterior, "exterior"))
        object.__setattr__(self, "holes", tuple(_ring(hole, "hole") for hole in self.holes))
        object.__setattr__(self, "bbox", BoundingBox.around(self.exterior))

    @classmethod
    def from_rings(cls, rings: Any) -> "Polygon":
        """Build a polygon from GeoJSON rings: the first one bounds, the rest cut."""
        if isinstance(rings, (str, bytes)) or not isinstance(rings, Sequence):
            raise GeometryError(f"polygon coordinates must be a list of rings, got {rings!r}")
        if not rings:
            raise GeometryError("polygon has no rings")
        return cls(exterior=rings[0], holes=tuple(rings[1:]))


def _point(value: Any) -> Point:
    return value if isinstance(value, Point) else Point.from_coordinates(value)


def _ring(coordinates: Any, role: str) -> tuple[Point, ...]:
    if isinstance(coordinates, (str, bytes)) or not isinstance(coordinates, Iterable):
        raise GeometryError(f"{role} ring must be a sequence of positions, got {coordinates!r}")
    points = tuple(_point(item) for item in coordinates)
    if len(points) > 1 and points[0] == points[-1]:
        points = points[:-1]
    if len(points) < 3:
        raise GeometryError(f"{role} ring needs at least three distinct positions")
    return points


def polygons_from_geojson(geometry: Mapping[str, Any]) -> tuple[Polygon, ...]:
    """Read a GeoJSON Polygon or MultiPolygon geometry."""
    if not isinstance(geometry, Mapping):
        raise GeometryError(f"geometry must be a GeoJSON mapping, got {type(geometry).__name__}")
    kind = geometry.get("type")
    coordinates = geometry.get("coordinates")
    if coordinates is None:
        raise GeometryError("geometry has no coordinates")
    if kind == "Polygon":
        return (Polygon.from_rings(coordinates),)
    if kind == "MultiPolygon":
        if isinstance(coordinates, (str, bytes)) or not isinstance(coordinates, Sequence):
            raise GeometryError("MultiPolygon coordinates must be a list of polygons")
        polygons = tuple(Polygon.from_rings(rings) for rings in coordinates)
        if not polygons:
            raise GeometryError("MultiPolygon has no members")
        return polygons
    raise GeometryError(f"unsupported geometry type: {kind!r}")
