# delivery-zones

Delivery coverage by polygons: point-in-zone lookups, overlapping zones and
picking the store that serves an address.

## Status

Pre-alpha. The public API is not stable yet.

## Installation

```bash
pip install delivery-zones
```

From a checkout:

```bash
pip install -e .
```

## Usage

Zones are built from GeoJSON features and held in memory, so no database is
required. Each zone carries the metadata a caller acts on: the store serving
it, the delivery fee tier and the hours it accepts orders.

```python
from datetime import datetime

from delivery_zones import Zone

zone = Zone.from_geojson(
    {
        "type": "Feature",
        "id": "downtown",
        "geometry": {
            "type": "Polygon",
            "coordinates": [
                [
                    [13.37, 52.51],
                    [13.42, 52.51],
                    [13.42, 52.54],
                    [13.37, 52.54],
                    [13.37, 52.51],
                ]
            ],
        },
        "properties": {
            "store_id": "store-1",
            "fee_tier": "standard",
            "priority": 10,
            "store_location": [13.39, 52.52],
            "service_hours": [
                {"weekday": "mon", "opens": "09:00", "closes": "21:00"}
            ],
        },
    }
)

zone.zone_id                                     # "downtown"
zone.store_id                                    # "store-1"
zone.fee_tier                                    # "standard"
zone.priority                                    # 10, or 0 when undeclared
zone.store_location                              # Point(13.39, 52.52), or None
zone.is_open_at(datetime(2026, 8, 24, 10, 0))    # True, a Monday morning
```

### Loading a catalogue

A catalogue is usually a `FeatureCollection` on disk or from a service. Read it
with `zones_from_geojson`, or hand the document straight to the index:

```python
import json

from delivery_zones import ZoneIndex, zones_from_geojson

with open("zones.geojson", encoding="utf-8") as handle:
    document = json.load(handle)

zones = zones_from_geojson(document)     # a tuple of Zone, in file order
index = ZoneIndex(zones)                 # or ZoneIndex.from_geojson(document)

len(index)                               # how many zones it holds
index.zones                              # them, in the order they were given
```

`properties` must carry `store_id` and `fee_tier`; `zone_id` falls back to the
feature's `id`, and `service_hours`, `priority` and `store_location` are
optional. Zones without declared service hours are always open. A feature that
is missing one of the required properties, or whose ring has fewer than three
positions, raises `ZoneError` or `GeometryError` naming what is wrong — a bad
entry fails the load instead of quietly dropping out of coverage.

Declaration order is kept end to end: it decides what a lookup returns and what
`TieBreak.FIRST` means, so the file is the tie-breaker of last resort. An index
is a snapshot that prepares every ring once; when the catalogue changes, build a
new one rather than mutating this one.

### Coverage lookups

`ZoneIndex` prepares the polygons once and buckets them into a grid, so asking
which zones reach an address does not walk the whole catalogue. Coverage may
overlap, so a lookup returns every match in the order the zones were given.

```python
index.zones_containing((13.40, 52.52))   # every zone reaching the address
index.covers((13.40, 52.52))             # True if at least one does
```

A position is a GeoJSON pair (longitude first) or a `Point`. For a one-off
check against a single polygon there is `point_in_polygon`.

### Who delivers to this address

The question a dispatcher actually asks is answered in three steps: which zones
reach the address, which of them is supposed to win, and how far its store is.

```python
from delivery_zones import TieBreak, by_priority, nearest_store

address = (13.40, 52.52)

serving = index.zones_containing(address, policy=by_priority(TieBreak.FIRST))
if not serving:
    ...                                  # nobody covers it; refuse the order

zone = serving[0]
zone.store_id                            # who takes it
zone.fee_tier                            # what it costs
zone.is_open_at(datetime.now())          # whether they take it now

nearest_store(index, address).distance_m # how far the closest store is
```

The library answers the first step and gives you the vocabulary for the second;
the rule itself stays yours.

### Overlapping zones

A city hub and a store's own ring routinely cover the same street, and which
one serves the address is a business rule. Pass a policy to say which:

```python
from delivery_zones import TieBreak, by_priority, by_smallest_area

index.zones_containing(address)                                    # all matches
index.zones_containing(address, policy=by_priority(TieBreak.FIRST))
index.zones_containing(address, policy=by_smallest_area(TieBreak.RAISE))
```

`by_priority` ranks on the zone's `priority` property, higher first;
`by_smallest_area` prefers the tightest coverage, which is usually the most
specific zone. Neither invents a winner when the leaders rank equally: the
tie-break is a required argument, and `TieBreak.FIRST` keeps the first zone in
declaration order, `TieBreak.ALL` returns every leader and `TieBreak.RAISE`
raises `AmbiguousCoverage` so a bad catalogue surfaces instead of routing at
random.

Every policy returns a tuple, empty when nothing covers the address. A policy
is just a callable from matched zones to chosen ones, so a rule of your own —
fee tier, open right now — fits the same slot; `ranked_by` builds one from any
measure of a zone.

### Shapes the world actually has

Concave zones and holes are honoured as written: only the envelope test is
rectangular, so a notch around a park or a lake cut out of the middle stays
uncovered, and an island inside that lake is served again as a second polygon
of the same zone. Borders are half-open — a position on a zone's southern or
western edge is inside it, on its northern or eastern edge outside — so two
zones meeting along a street do not both claim the addresses on it.

Coverage is planar: rings are measured in degrees and nothing wraps. A zone
reaching across the antimeridian has to be split into two polygons at ±180, the
way GeoJSON asks; a ring written straight from 179 to -179 covers the other
half of the planet instead, and the envelope of such a catalogue spans the
globe. Distances are unaffected, since `haversine_metres` reads the short way
round.

### Coverage checks and holes

Overlaps are visible in a lookup; the places no zone reaches are not. A scan
walks a lattice over the served area, asks the index about every position and
groups the misses, so a strip between two rings — or a hole cut around a lake —
fails a test run instead of an order.

```python
from delivery_zones import BoundingBox, scan_coverage, uncovered_points

report = scan_coverage(index, spacing=0.002)

assert report.is_complete, report.describe()

report.uncovered                 # sampled positions no zone reaches
report.gaps[0].size              # how many of them this gap holds
report.gaps[0].representative    # a position inside it, ready to paste into a bug
report.gaps[0].bbox              # where to look on a map
```

`spacing` is in degrees and decides what the scan can see: a gap narrower than
the lattice slips between samples, while a fine spacing over a whole city costs
many lookups, which is why `max_samples` refuses a scan larger than a million
positions. By default the scan covers the envelope of the indexed zones; pass
`area=BoundingBox(...)` to check a district the catalogue is supposed to reach
but may have forgotten. A sample landing exactly on a zone border may fall
either way, so prefer a spacing that does not align with your rings.

For addresses you already have — a delivery history, a list of test
addresses — `uncovered_points(index, positions)` returns those that no zone
reaches, in the order given.

### Distance and service-time hints

A lookup says which stores reach an address; dispatch also asks how far away
they are. Give a zone a `store_location` and every match carries a straight-line
distance to it.

```python
from delivery_zones import constant_speed, nearest_store, service_hints

hints = service_hints(index, address)
hints[0].zone.store_id
hints[0].distance_m              # great-circle metres from store to address

nearest_store(index, address)    # the closest hint, or None if nothing covers it

hints = service_hints(index, address, travel_time=constant_speed(22.0, detour=1.35))
hints[0].travel_time_s
```

The distance is a line over the ground, not a route along it: it knows nothing
about rivers, one-way streets or traffic, and a store two blocks away across a
railway can still be a ten-minute ride. Travel time is therefore a hook rather
than a calculation — pass any callable taking `(store, address,
straight_line_metres)` and returning seconds, and a routing service answers in
the package's place. `constant_speed` is the placeholder for tests and rough
fee tiers: it stretches the straight line by a detour factor and divides by a
fixed speed.

Ranking on distance fits the policy slot as well:

```python
from delivery_zones import TieBreak, by_nearest_store

index.zones_containing(address, policy=by_nearest_store(address, TieBreak.FIRST))
```

A zone that declares no `store_location` cannot be measured against, and asking
for its distance raises `DistanceError` instead of inventing a position.

## What this library is not

It answers where a catalogue of polygons reaches, and stops there.

- **Not a geocoder.** Lookups take coordinates. Turning "Torstraße 1" into a
  longitude and latitude happens before the first call.
- **Not a routing engine.** Distances are great-circle lines; travel time is a
  hook for a service that knows the streets.
- **Not a GIS toolkit.** There is no union, intersection, buffering or
  simplification of polygons, and no reprojection: everything is WGS84 degrees,
  as GeoJSON delivers them. Editing zone shapes belongs in whatever draws them.
- **Not spherical.** Point-in-polygon is planar, so rings are straight in
  degrees rather than great circles and nothing wraps at the antimeridian. Over
  a city the difference is invisible; over a continent-sized zone it is not.
- **Not a store.** Zones live in memory for the life of the process. Loading,
  caching and reloading a changed catalogue are the caller's job — and with
  immutable zones, reloading is just building a new index.

## Development

```bash
pip install -e ".[test]"
python -m pytest
```

## License

MIT — see [LICENSE](LICENSE).

Maintained by [Shipmind Labs](https://shipmindlabs.com).
