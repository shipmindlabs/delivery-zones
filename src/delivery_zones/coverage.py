"""Finding the places no zone reaches, before a customer does.

A catalogue is easy to check one address at a time and hard to judge as a
whole: two rings that almost meet leave the street between them unserved, and a
hole cut around a lake swallows the houses on its shore. A scan samples a
lattice over the served area, asks the index about every position and groups
the misses into gaps, so a hole in coverage shows up in a test run instead of a
failed order.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from math import isfinite

from .geometry import BoundingBox, Point
from .lookup import ZoneIndex
from .zones import Zone

__all__ = [
    "DEFAULT_MAX_SAMPLES",
    "CoverageError",
    "CoverageGap",
    "CoverageReport",
    "scan_coverage",
    "uncovered_points",
    "zones_envelope",
]

DEFAULT_MAX_SAMPLES = 1_000_000


class CoverageError(ValueError):
    """Raised when a scan is asked for something it cannot answer."""


def _as_point(value: Point | Sequence[float]) -> Point:
    return value if isinstance(value, Point) else Point.from_coordinates(value)


@dataclass(frozen=True, slots=True)
class CoverageGap:
    """A run of neighbouring sampled positions that no zone reaches."""

    points: tuple[Point, ...]
    bbox: BoundingBox = field(init=False, compare=False, repr=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "points", tuple(self.points))
        if not self.points:
            raise CoverageError("a gap needs at least one uncovered position")
        object.__setattr__(self, "bbox", BoundingBox.around(self.points))

    @property
    def size(self) -> int:
        """How many sampled positions the gap holds."""
        return len(self.points)

    @property
    def representative(self) -> Point:
        """The sample nearest the gap's centre, to paste into a bug report."""
        centre_lon = (self.bbox.min_lon + self.bbox.max_lon) / 2.0
        centre_lat = (self.bbox.min_lat + self.bbox.max_lat) / 2.0
        return min(
            self.points,
            key=lambda point: (point.lon - centre_lon) ** 2 + (point.lat - centre_lat) ** 2,
        )


@dataclass(frozen=True, slots=True)
class CoverageReport:
    """What a scan saw: how much of the area was reached and where it was not."""

    area: BoundingBox
    spacing: float
    samples: int
    covered: int
    gaps: tuple[CoverageGap, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "gaps", tuple(self.gaps))

    @property
    def uncovered(self) -> int:
        return self.samples - self.covered

    @property
    def is_complete(self) -> bool:
        """Whether every sampled position was reached by some zone."""
        return not self.gaps

    @property
    def covered_fraction(self) -> float:
        return 1.0 if not self.samples else self.covered / self.samples

    def describe(self) -> str:
        """A single line to hand to an assertion when a scan finds holes."""
        if self.is_complete:
            return (
                f"coverage is complete over {self.samples} samples "
                f"at spacing {self.spacing}"
            )
        worst = self.gaps[0]
        point = worst.representative
        return (
            f"{self.uncovered} of {self.samples} sampled positions are uncovered "
            f"in {len(self.gaps)} gap(s); the largest holds {worst.size} of them, "
            f"around ({point.lon:.6f}, {point.lat:.6f})"
        )


def zones_envelope(zones: Iterable[Zone]) -> BoundingBox:
    """The envelope around every polygon of every zone."""
    boxes = [polygon.bbox for zone in zones for polygon in zone.polygons]
    if not boxes:
        raise CoverageError("there are no zones to bound; pass an explicit area")
    return BoundingBox(
        min(box.min_lon for box in boxes),
        min(box.min_lat for box in boxes),
        max(box.max_lon for box in boxes),
        max(box.max_lat for box in boxes),
    )


def uncovered_points(
    index: ZoneIndex,
    points: Iterable[Point | Sequence[float]],
) -> tuple[Point, ...]:
    """The given addresses that no zone reaches, in the order supplied."""
    return tuple(point for point in map(_as_point, points) if not index.covers(point))


def scan_coverage(
    index: ZoneIndex,
    *,
    spacing: float,
    area: BoundingBox | None = None,
    max_samples: int = DEFAULT_MAX_SAMPLES,
) -> CoverageReport:
    """Sample a lattice over *area* and report the positions no zone reaches.

    *spacing* is given in degrees and decides what the scan can see: a gap
    narrower than the lattice slips between samples. Without an explicit *area*
    the scan covers the envelope of the indexed zones, which finds holes inside
    the catalogue but not districts it forgot entirely. A sample landing exactly
    on a zone border may fall either way, so a spacing that does not align with
    the rings gives a stabler answer.
    """
    if not isinstance(spacing, (int, float)) or isinstance(spacing, bool):
        raise CoverageError(f"spacing must be a number of degrees, got {spacing!r}")
    if not isfinite(spacing) or spacing <= 0.0:
        raise CoverageError(f"spacing must be greater than zero, got {spacing!r}")
    box = zones_envelope(index.zones) if area is None else area
    if box.min_lon > box.max_lon or box.min_lat > box.max_lat:
        raise CoverageError(f"area is inverted: {box!r}")

    columns = _steps(box.min_lon, box.max_lon, spacing)
    rows = _steps(box.min_lat, box.max_lat, spacing)
    total = columns * rows
    if total > max_samples:
        raise CoverageError(
            f"scanning this area at spacing {spacing} would take {total} samples, "
            f"over the limit of {max_samples}; widen the spacing or shrink the area"
        )

    misses: dict[tuple[int, int], Point] = {}
    covered = 0
    for column in range(columns):
        lon = min(box.min_lon + column * spacing, box.max_lon)
        for row in range(rows):
            lat = min(box.min_lat + row * spacing, box.max_lat)
            point = Point(lon, lat)
            if index.covers(point):
                covered += 1
            else:
                misses[(column, row)] = point

    return CoverageReport(
        area=box,
        spacing=float(spacing),
        samples=total,
        covered=covered,
        gaps=_cluster(misses),
    )


def _steps(low: float, high: float, spacing: float) -> int:
    """How many lattice positions fit between *low* and *high*, ends included.

    The division is nudged to the nearest whole number first: a span that is an
    exact multiple of the spacing often divides to just under it in binary
    floating point, which would silently drop the last column of a scan.
    """
    span = high - low
    if span <= 0.0:
        return 1
    count = span / spacing
    nearest = round(count)
    if abs(count - nearest) < 1e-9:
        count = float(nearest)
    return int(count) + 1


def _cluster(misses: dict[tuple[int, int], Point]) -> tuple[CoverageGap, ...]:
    """Group adjacent misses, so one hole is reported once instead of per sample."""
    remaining = dict(misses)
    gaps: list[CoverageGap] = []
    for start in sorted(misses):
        if start not in remaining:
            continue
        remaining.pop(start)
        members = [start]
        stack = [start]
        while stack:
            column, row = stack.pop()
            neighbours = (
                (column - 1, row),
                (column + 1, row),
                (column, row - 1),
                (column, row + 1),
            )
            for neighbour in neighbours:
                if neighbour in remaining:
                    remaining.pop(neighbour)
                    members.append(neighbour)
                    stack.append(neighbour)
        gaps.append(CoverageGap(tuple(misses[cell] for cell in sorted(members))))
    gaps.sort(key=lambda gap: (-gap.size, gap.bbox.min_lon, gap.bbox.min_lat))
    return tuple(gaps)
