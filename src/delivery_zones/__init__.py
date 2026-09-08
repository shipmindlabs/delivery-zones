"""Delivery coverage by polygons."""

from .coverage import (
    CoverageError,
    CoverageGap,
    CoverageReport,
    scan_coverage,
    uncovered_points,
    zones_envelope,
)
from .distance import (
    DistanceError,
    ServiceHint,
    TravelTime,
    by_nearest_store,
    constant_speed,
    distance_to_store,
    haversine_metres,
    nearest_store,
    service_hints,
    serving_store,
)
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
    ranked_by,
    zone_area,
)
from .zones import ServiceHours, ServiceWindow, Zone, ZoneError, zones_from_geojson

__version__ = "0.1.0"

__all__ = [
    "AmbiguousCoverage",
    "BoundingBox",
    "CoverageError",
    "CoverageGap",
    "CoverageReport",
    "DistanceError",
    "GeometryError",
    "Point",
    "Polygon",
    "ServiceHint",
    "ServiceHours",
    "ServiceWindow",
    "TieBreak",
    "TravelTime",
    "Zone",
    "ZoneError",
    "ZoneIndex",
    "ZonePolicy",
    "__version__",
    "all_matches",
    "by_nearest_store",
    "by_priority",
    "by_smallest_area",
    "constant_speed",
    "distance_to_store",
    "haversine_metres",
    "nearest_store",
    "point_in_polygon",
    "polygons_from_geojson",
    "ranked_by",
    "scan_coverage",
    "service_hints",
    "serving_store",
    "uncovered_points",
    "zone_area",
    "zones_envelope",
    "zones_from_geojson",
]
