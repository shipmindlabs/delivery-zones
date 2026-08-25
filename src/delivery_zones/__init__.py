"""Delivery coverage by polygons."""

from .geometry import (
    BoundingBox,
    GeometryError,
    Point,
    Polygon,
    polygons_from_geojson,
)
from .lookup import ZoneIndex, point_in_polygon
from .zones import ServiceHours, ServiceWindow, Zone, ZoneError, zones_from_geojson

__version__ = "0.1.0"

__all__ = [
    "BoundingBox",
    "GeometryError",
    "Point",
    "Polygon",
    "ServiceHours",
    "ServiceWindow",
    "Zone",
    "ZoneError",
    "ZoneIndex",
    "__version__",
    "point_in_polygon",
    "polygons_from_geojson",
    "zones_from_geojson",
]
