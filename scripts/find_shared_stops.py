"""
Find multi-agency shared stops: group stops by geohash cell and keep the cells
where two or more agencies each publish a stop — the candidate shared stops
the registry needs to consolidate.

Geohashes are computed by BigQuery in pull_stops.py (ST_GEOHASH at precisions
7/8/9.

Reads the newest data/stops_*.csv from pull_stops.py (or --input). Writes
shared_stops_<date>.csv plus .gpkg / .fgb — one row per stop, grouped by cell,
most-shared cells first.

  uv run scripts/find_shared_stops.py
  uv run scripts/find_shared_stops.py --precision 9
"""

import argparse
from pathlib import Path

import geopandas as gpd
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = REPO_ROOT / "data"

OUT_COLS = [
    "geohash", "n_agencies", "n_stops", "agency", "feed_name",
    "stop_id", "stop_name", "stop_lat", "stop_lon", "route_types",
]


def latest_stops_csv() -> Path:
    candidates = sorted(
        DATA_DIR.glob("stops_[0-9]*.csv"), key=lambda p: p.stat().st_mtime
    )
    if not candidates:
        raise SystemExit("No data/stops_<YYYY_MM>.csv — run pull_stops.py first.")
    return candidates[-1]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--input", type=Path, help="stops CSV (default: newest data/stops_*.csv)")
    ap.add_argument("--precision", type=int, default=8, choices=(7, 8, 9),
                    help="geohash cell size (8 = ~38x19 m)")
    ap.add_argument("--include-unserved", action="store_true",
                    help="also group latest-extract-only stops (unserved/stations)")
    ap.add_argument("--outdir", type=Path, default=DATA_DIR, help="output directory")
    args = ap.parse_args()

    src = args.input or latest_stops_csv()
    df = pd.read_csv(src, dtype={"stop_id": str, "stop_code": str, "route_types": str})
    if not args.include_unserved and "served_in_month" in df.columns:
        df = df[df["served_in_month"]]
    print(f"{len(df):,} stops from {src.name}")

    df["geohash"] = df[f"geohash_id_{args.precision}"]
    grp = df.groupby("geohash")["analysis_name"]
    df["n_agencies"] = grp.transform("nunique")
    df["n_stops"] = grp.transform("size")

    shared = (
        df[df["n_agencies"] >= 2]
        .rename(columns={"analysis_name": "agency"})
        .sort_values(["n_agencies", "n_stops", "geohash", "agency"],
                     ascending=[False, False, True, True])
        .reset_index(drop=True)
    )[OUT_COLS]

    stamp = pd.Timestamp.now().strftime("%Y_%m_%d")
    csv_out = args.outdir / f"shared_stops_{stamp}.csv"
    gpkg_out = args.outdir / f"shared_stops_{stamp}.gpkg"
    fgb_out = args.outdir / f"shared_stops_{stamp}.fgb"

    shared.to_csv(csv_out, index=False)
    gdf = gpd.GeoDataFrame(
        shared, geometry=gpd.points_from_xy(shared["stop_lon"], shared["stop_lat"]), crs="EPSG:4326"
    )
    gdf.to_file(gpkg_out, layer="shared_stops", driver="GPKG")
    gdf.to_file(fgb_out, driver="FlatGeobuf")

    print(
        f"  {shared['geohash'].nunique():,} shared cells (precision {args.precision}) / "
        f"{len(shared):,} stops / {shared['agency'].nunique()} agencies"
    )
    print(f"  CSV        -> {csv_out}")
    print(f"  GeoPackage -> {gpkg_out}  (QGIS + ArcGIS)")
    print(f"  FlatGeobuf -> {fgb_out}  (QGIS; ArcGIS via Data Interop)")


if __name__ == "__main__":
    main()
