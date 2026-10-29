"""Finding the places no zone reaches, and the ones no policy can decide.

A catalogue is easy to check one address at a time and hard to judge as a
whole: two rings that almost meet leave the street between them unserved, and a
hole cut around a lake swallows the houses on its shore. A scan samples a
lattice over the served area, asks the index about every position and groups
the misses into gaps, so a hole in coverage shows up in a test run instead of a
failed order.

The mirror image of a hole is an overlap no rule can settle: two zones of equal
priority covering the same street leave the order to whichever was declared
first. An ambiguity scan walks the same lattice with a policy and collects the
positions where it raises :class:`AmbiguousCoverage`, so an undecidable
catalogue fails the same way a hole does.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass, field
from math import isfinite

from .geometry import BoundingBox, Point
from .lookup import ZoneIndex
from .resolution import AmbiguousCoverage, ZonePolicy
from .zones import Zone

__all__ = [
    "DEFAULT_MAX_SAMPLES",
    "AmbiguityReport",
    "CoverageError",
    "CoverageGap",
    "CoverageReport",
    "scan_ambiguity",
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
    """A run of neighbouring sampled positions that share the same finding."""

    points: tuple[Point, ...]
    bbox: BoundingBox = field(init=False, compare=False, repr=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "points", tuple(self.points))
        if not self.points:
            raise CoverageError("a gap needs at least one position")
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


@dataclass(frozen=True, slots=True)
class AmbiguityReport:
    """Where a policy found leaders it could not separate."""

    area: BoundingBox
    spacing: float
    samples: int
    ambiguous: int
    gaps: tuple[CoverageGap, ...]
    zone_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "gaps", tuple(self.gaps))
        object.__setattr__(self, "zone_ids", tuple(self.zone_ids))

    @property
    def is_decided(self) -> bool:
        """Whether the policy picked a winner at every sampled position."""
        return not self.gaps

    def describe(self) -> str:
        """A single line to hand to an assertion when a scan finds a tie."""
        if self.is_decided:
            return (
                f"the policy decides all {self.samples} samples "
                f"at spacing {self.spacing}"
            )
        worst = self.gaps[0]
        point = worst.representative
        return (
            f"{self.ambiguous} of {self.samples} sampled positions have no winner "
            f"in {len(self.gaps)} area(s); the largest holds {worst.size} of them, "
            f"around ({point.lon:.6f}, {point.lat:.6f}); "
            f"zones ranking equally: {', '.join(self.zone_ids)}"
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
    lattice = _lattice(index, spacing, area, max_samples)

    misses: dict[tuple[int, int], Point] = {}
    covered = 0
    for cell, point in lattice.positions():
        if index.covers(point):
            covered += 1
        else:
            misses[cell] = point

    return CoverageReport(
        area=lattice.box,
        spacing=lattice.spacing,
        samples=lattice.samples,
        covered=covered,
        gaps=_cluster(misses),
    )


def scan_ambiguity(
    index: ZoneIndex,
    policy: ZonePolicy,
    *,
    spacing: float,
    area: BoundingBox | None = None,
    max_samples: int = DEFAULT_MAX_SAMPLES,
) -> AmbiguityReport:
    """Sample a lattice over *area* and report where *policy* elects nobody.

    The lattice is the one :func:`scan_coverage` walks, and the same caveats
    about *spacing* apply. Only :class:`AmbiguousCoverage` is collected: a
    position no zone reaches leaves the policy with nothing to rank and is a
    matter for a coverage scan, while any other error a policy raises travels
    on untouched.
    """
    if not callable(policy):
        raise TypeError(f"policy must be a policy callable, got {policy!r}")
    lattice = _lattice(index, spacing, area, max_samples)

    undecided: dict[tuple[int, int], Point] = {}
    names: dict[str, None] = {}
    for cell, point in lattice.positions():
        try:
            index.zones_containing(point, policy=policy)
        except AmbiguousCoverage as clash:
            undecided[cell] = point
            for zone in clash.zones:
                names[zone.zone_id] = None

    return AmbiguityReport(
        area=lattice.box,
        spacing=lattice.spacing,
        samples=lattice.samples,
        ambiguous=len(undecided),
        gaps=_cluster(undecided),
        zone_ids=tuple(names),
    )


@dataclass(frozen=True, slots=True)
class _Lattice:
    """The positions a scan visits, shared by every kind of scan."""

    box: BoundingBox
    spacing: float
    columns: int
    rows: int

    @property
    def samples(self) -> int:
        return self.columns * self.rows

    def positions(self) -> Iterator[tuple[tuple[int, int], Point]]:
        for column in range(self.columns):
            lon = min(self.box.min_lon + column * self.spacing, self.box.max_lon)
            for row in range(self.rows):
                lat = min(self.box.min_lat + row * self.spacing, self.box.max_lat)
                yield (column, row), Point(lon, lat)


def _lattice(
    index: ZoneIndex,
    spacing: float,
    area: BoundingBox | None,
    max_samples: int,
) -> _Lattice:
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
    return _Lattice(box=box, spacing=float(spacing), columns=columns, rows=rows)


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


def _cluster(found: dict[tuple[int, int], Point]) -> tuple[CoverageGap, ...]:
    """Group adjacent findings, so one area is reported once instead of per sample."""
    remaining = dict(found)
    gaps: list[CoverageGap] = []
    for start in sorted(found):
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
        gaps.append(CoverageGap(tuple(found[cell] for cell in sorted(members))))
    gaps.sort(key=lambda gap: (-gap.size, gap.bbox.min_lon, gap.bbox.min_lat))
    return tuple(gaps)
