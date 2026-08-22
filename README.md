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
            "service_hours": [
                {"weekday": "mon", "opens": "09:00", "closes": "21:00"}
            ],
        },
    }
)

zone.zone_id                                     # "downtown"
zone.store_id                                    # "store-1"
zone.fee_tier                                    # "standard"
zone.is_open_at(datetime(2026, 8, 24, 10, 0))    # True, a Monday morning
```

Use `zones_from_geojson` to read a whole `FeatureCollection`. Zones without
declared service hours are always open.

## License

MIT — see [LICENSE](LICENSE).

Maintained by [Shipmind Labs](https://shipmindlabs.com).
