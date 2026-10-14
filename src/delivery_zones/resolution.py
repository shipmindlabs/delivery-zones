"""Choosing between zones whose coverage overlaps.

Cities overlap: a courier hub reaches into the same streets as a store's own
ring, and both entries are correct. Which one serves the address is a business
decision, so this module offers policies instead of a default. Every ranking
policy also demands a tie-break, because two zones ranking equally is a normal
outcome and quietly keeping the first one hides it.

Policies compose, and the order is itself part of the rule: a filter such as
``open_at`` placed ahead of a ranking keeps a closed zone from winning on
priority, while the same filter behind the ranking only discards the winner it
already elected.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import datetime
from enum import Enum

from .zones import Zone

__all__ = [
    "AmbiguousCoverage",
    "TieBreak",
    "ZonePolicy",
    "all_matches",
    "by_priority",
    "by_smallest_area",
    "open_at",
    "ranked_by",
    "then",
    "zone_area",
]

ZonePolicy = Callable[[Sequence[Zone]], tuple[Zone, ...]]


class AmbiguousCoverage(LookupError):
    """Raised when zones rank equally and the caller asked not to guess."""

    def __init__(self, zones: Sequence[Zone]) -> None:
        self.zones: tuple[Zone, ...] = tuple(zones)
        names = ", ".join(zone.zone_id for zone in self.zones)
        super().__init__(f"zones rank equally at this address: {names}")


class TieBreak(Enum):
    """What a ranking policy does when it cannot separate the leaders."""

    FIRST = "first"
    ALL = "all"
    RAISE = "raise"


def all_matches(zones: Sequence[Zone]) -> tuple[Zone, ...]:
    """Keep every match, leaving the choice to the caller."""
    return tuple(zones)


def zone_area(zone: Zone) -> float:
    """Planar area of a zone's polygons, in square degrees.

    Comparable between nearby zones, not a measurement of ground area.
    """
    return sum(polygon.area for polygon in zone.polygons)


def by_priority(tie_break: TieBreak) -> ZonePolicy:
    """Prefer the highest ``priority``; zones without one sit at ``0``."""
    return ranked_by(lambda zone: float(-zone.priority), tie_break)


def by_smallest_area(tie_break: TieBreak) -> ZonePolicy:
    """Prefer the tightest coverage, usually the most specific zone."""
    return ranked_by(zone_area, tie_break)


def open_at(moment: datetime) -> ZonePolicy:
    """Keep the zones accepting orders at *moment*.

    A zone that declares no service hours is always open and always passes.
    Nothing is elected here, so an address whose zones are all closed comes
    back as the empty tuple that already reads as nobody serving it.
    """
    if not isinstance(moment, datetime):
        raise TypeError(f"moment must be a datetime, got {moment!r}")

    def policy(zones: Sequence[Zone]) -> tuple[Zone, ...]:
        return tuple(zone for zone in zones if zone.is_open_at(moment))

    return policy


def then(*policies: ZonePolicy) -> ZonePolicy:
    """Chain policies, feeding each result to the next.

    Order decides the rule: ``then(open_at(now), by_priority(TieBreak.FIRST))``
    ranks only the zones that are open, while the reverse ranks first and may
    discard its own winner. Chaining nothing keeps every match.
    """
    for stage in policies:
        if not callable(stage):
            raise TypeError(f"every stage must be a policy callable, got {stage!r}")

    def policy(zones: Sequence[Zone]) -> tuple[Zone, ...]:
        chosen = tuple(zones)
        for stage in policies:
            chosen = tuple(stage(chosen))
        return chosen

    return policy


def ranked_by(rank: Callable[[Zone], float], tie_break: TieBreak) -> ZonePolicy:
    """Build a policy keeping the zones with the lowest *rank*.

    Lower wins, so a measure that should prefer larger values negates itself.
    """
    if not isinstance(tie_break, TieBreak):
        raise TypeError(f"tie_break must be a TieBreak, got {tie_break!r}")

    def policy(zones: Sequence[Zone]) -> tuple[Zone, ...]:
        candidates = tuple(zones)
        if not candidates:
            return ()
        scores = [rank(zone) for zone in candidates]
        best = min(scores)
        leaders = tuple(
            zone for zone, score in zip(candidates, scores) if score == best
        )
        if len(leaders) == 1 or tie_break is TieBreak.ALL:
            return leaders
        if tie_break is TieBreak.FIRST:
            return leaders[:1]
        raise AmbiguousCoverage(leaders)

    return policy
