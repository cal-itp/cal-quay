"""Build a small statewide roads file for the grouping pipeline.

The atlas drive networks (norcal + socal, ~1.8 GB) carry 22 OSM attribute columns
and store every two-way street twice (osmnx directed edges). The pipeline only
needs road *geometry near bus stops*: the road-split test looks within 50 m of a
cluster bbox and in_roadway is a 3 m test, so edges intersecting a 150 m buffer
around any stop cover every use with margin.

Output: data/roads_near_stops.fgb (geometry-only, deduped, EPSG:4326).
cluster_stops.py prefers it over the atlas files when present, and auto-downloads
it from the public bucket when neither exists. After rebuilding (e.g. a new stops
pull), publish the refresh with:

  gsutil cp data/roads_near_stops.fgb gs://calitp-publish-data-analysis/cal-quay/

Usage: uv run scripts/trim_roads.py
"""

from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import shapely

REPO_ROOT = Path(__file__).resolve().parent.parent
ATLAS_DATA = Path.home() / "github/transit-amenity-atlas/data"
SOURCE_FGBS = [ATLAS_DATA / "norcal_drive_network.fgb",
               ATLAS_DATA / "socal_drive_network.fgb"]
STOPS_CSV = REPO_ROOT / "data" / "stops_2026_09.csv"
OUT = REPO_ROOT / "data" / "roads_near_stops.fgb"
BUFFER_M = 150.0
CA_ALBERS = "EPSG:3310"


def main() -> None:
    stops = pd.read_csv(STOPS_CSV, usecols=["stop_lat", "stop_lon"])
    buffers = (
        gpd.GeoSeries(gpd.points_from_xy(stops["stop_lon"], stops["stop_lat"]),
                      crs="EPSG:4326")
        .to_crs(CA_ALBERS).buffer(BUFFER_M).to_crs("EPSG:4326")
    )
    print(f"{len(stops):,} stops -> {BUFFER_M:.0f} m buffers")

    parts = []
    for f in SOURCE_FGBS:
        roads = gpd.read_file(f, columns=[], engine="pyogrio")
        hit = np.unique(roads.sindex.query(buffers, predicate="intersects")[1])
        print(f"{f.name}: {len(hit):,} / {len(roads):,} edges near stops")
        parts.append(roads.iloc[hit][["geometry"]])
        del roads

    out = pd.concat(parts, ignore_index=True).set_crs("EPSG:4326")

    # osmnx emits one directed edge per direction of travel; a two-way street is
    # the same line twice, reversed. Normalize to direction-independent WKB.
    fwd = shapely.to_wkb(out.geometry.values)
    rev = shapely.to_wkb(shapely.reverse(out.geometry.values))
    canon = np.where(fwd < rev, fwd, rev)
    out = out[~pd.Series(canon).duplicated().to_numpy()]
    print(f"after reverse-dedup: {len(out):,} edges")

    out.to_file(OUT, engine="pyogrio")
    print(f"wrote {OUT} ({OUT.stat().st_size / 1e6:.0f} MB)")


if __name__ == "__main__":
    main()
