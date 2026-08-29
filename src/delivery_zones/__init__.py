"""Delivery coverage by polygons."""

from .geometry import (
    BoundingBox,
    GeometryError,
    Point,
    Polygon,
    polygons_from_geojson,
)
from .lookup import ZoneIndex, point_in_polygon
from .resolution import (
    AmbiguousCoverage,
    TieBreak,
    ZonePolicy,
    all_matches,
    by_priority,
    by_smallest_area,
    zone_area,
)
from .zones import ServiceHours, ServiceWindow, Zone, ZoneError, zones_from_geojson

__version__ = "0.1.0"

__all__ = [
    "AmbiguousCoverage",
    "BoundingBox",
    "GeometryError",
    "Point",
    "Polygon",
    "ServiceHours",
    "ServiceWindow",
    "TieBreak",
    "Zone",
    "ZoneError",
    "ZoneIndex",
    "ZonePolicy",
    "__version__",
    "all_matches",
    "by_priority",
    "by_smallest_area",
    "point_in_polygon",
    "polygons_from_geojson",
    "zone_area",
    "zones_from_geojson",
]
