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
zone.is_open_at(datetime(2026, 8, 24, 10, 0))    # True, a Monday morning
```

Use `zones_from_geojson` to read a whole `FeatureCollection`. Zones without
declared service hours are always open.

### Coverage lookups

`ZoneIndex` prepares the polygons once and buckets them into a grid, so asking
which zones reach an address does not walk the whole catalogue. Coverage may
overlap, so a lookup returns every match in the order the zones were given.

```python
from delivery_zones import ZoneIndex

index = ZoneIndex.from_geojson(feature_collection)

index.zones_containing((13.40, 52.52))   # every zone reaching the address
index.covers((13.40, 52.52))             # True if at least one does
```

A position is a GeoJSON pair (longitude first) or a `Point`. For a one-off
check against a single polygon there is `point_in_polygon`.

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
fee tier, open-right-now, nearest store — fits the same slot.

## License

MIT — see [LICENSE](LICENSE).

Maintained by [Shipmind Labs](https://shipmindlabs.com).
