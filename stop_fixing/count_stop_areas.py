"""
Count multi-agency stop areas that need matching analysis (live from BigQuery).

The AB 1599 registry's real work is the *multi-agency overlap*: physical locations
where two or more agencies each publish their own stop. Single-agency stops just
need a universal ID minted — trivial. This script sizes the overlap problem.

Pipeline (reuses transit-amenity-atlas, the single source of truth):
  1. Pull current stops live from BigQuery (the create_geohashes_from_stops.py SQL).
  2. Cluster by ground distance (canonicalizer/cluster.py — DBSCAN, 28 m, haversine).
  3. Apply exclusions (canonicalizer/exclusions.py):
       - 511 regional aggregator -> cluster-aware de-dup
       - protected single-operator rail -> dropped (extended here with SMART/Metrolink/SJRRC)
       - major stations (span >= 60 m OR >= 12 stops) -> handed to the operating agency
  4. Count multi-agency, in-scope clusters = the stop areas that need analysis.

Known limitation: analysis_name is FEED-level, so light rail bundled inside a mixed
agency (Muni Metro, VTA LRT, LA Metro Rail, SD Trolley, Sac RT) is NOT excluded —
that needs GTFS route_type (join stop_times -> trips -> routes), a possible follow-up.

Setup:
  - `gcloud auth application-default login` with cal-itp-data-infra access.
  - Clone cal-itp/transit-amenity-atlas; point CALQUAY_ATLAS_STOP_IDS at its stop_ids/
    directory (defaults to ~/github/transit-amenity-atlas/stop_ids).
  - Run with an environment that has bigquery + scikit-learn + pandas (e.g. the atlas venv).

Pulled stops are cached to data/ so re-runs can skip BigQuery (--cache <file>).
"""

import argparse
import os
import re
import sys
from datetime import date
from pathlib import Path

import pandas as pd

# --- repo layout ---
REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = REPO_ROOT / "data"

# --- reuse the atlas modules directly (single source of truth) ---
ATLAS_STOP_IDS = Path(
    os.environ.get("CALQUAY_ATLAS_STOP_IDS")
    or Path.home() / "github" / "transit-amenity-atlas" / "stop_ids"
)
if not ATLAS_STOP_IDS.exists():
    sys.exit(
        f"transit-amenity-atlas not found at {ATLAS_STOP_IDS}.\n"
        "Clone cal-itp/transit-amenity-atlas and set CALQUAY_ATLAS_STOP_IDS to its stop_ids/ dir."
    )
sys.path.insert(0, str(ATLAS_STOP_IDS))
sys.path.insert(0, str(ATLAS_STOP_IDS / "canonicalizer"))

import cluster as cluster_mod  # noqa: E402  canonicalizer/cluster.py
import exclusions as excl  # noqa: E402  canonicalizer/exclusions.py

# Live-stops SQL — same join as create_geohashes_from_stops.py, minus the geohash cols.
STOPS_SQL = """
SELECT
  ds.feed_key,
  ds.base64_url,
  ds.feed_key AS feed_name,
  gd.analysis_name,
  ds.stop_id,
  ds.stop_name,
  ds.stop_lat,
  ds.stop_lon
FROM `mart_gtfs_schedule_latest.dim_stops_latest` ds
LEFT JOIN `mart_transit_database.dim_gtfs_datasets` gd
  ON ds.base64_url = gd.base64_url
WHERE gd._is_current = TRUE
  AND ds.stop_lat != 0.0
  AND ds.stop_lat IS NOT NULL
  AND ds.stop_lon IS NOT NULL
"""

# Extend the atlas's protected-rail regex with more single-operator rail agencies.
# (atlas covers BART / Caltrain / ACE / Amtrak / Capitol Corridor; add SMART, Metrolink, SJRRC.)
EXTRA_RAIL = re.compile(
    r"Sonoma-?Marin\s*Area\s*Rail|\bSMART\b|"
    r"Southern\s*California\s*Regional\s*Rail|Metrolink|"
    r"San\s*Joaquin\s*Regional\s*Rail",
    re.IGNORECASE,
)


def fetch_stops() -> pd.DataFrame:
    from google.cloud import bigquery

    client = bigquery.Client(project="cal-itp-data-infra")
    df = client.query(STOPS_SQL).to_dataframe()
    df["stop_lat"] = pd.to_numeric(df["stop_lat"], errors="coerce")
    df["stop_lon"] = pd.to_numeric(df["stop_lon"], errors="coerce")
    return df.dropna(subset=["stop_lat", "stop_lon"]).reset_index(drop=True)


def drop_extra_rail(df: pd.DataFrame) -> tuple[pd.DataFrame, int]:
    s = excl._row_strings(df)
    mask = s.str.contains(EXTRA_RAIL)
    return df.loc[~mask].copy(), int(mask.sum())


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--eps-meters", type=float, default=28.0, help="DBSCAN cluster radius")
    ap.add_argument("--cache", type=Path, help="Load this CSV instead of querying BigQuery")
    ap.add_argument(
        "--save",
        type=Path,
        default=DATA_DIR / f"stops_live_{date.today():%Y_%m_%d}.csv",
        help="Where to write the pulled stops (default: data/stops_live_<date>.csv)",
    )
    args = ap.parse_args()

    DATA_DIR.mkdir(exist_ok=True)

    if args.cache and args.cache.exists():
        print(f"Loading cached stops from {args.cache}")
        df = pd.read_csv(args.cache, dtype={"stop_id": str})
        df["stop_lat"] = pd.to_numeric(df["stop_lat"], errors="coerce")
        df["stop_lon"] = pd.to_numeric(df["stop_lon"], errors="coerce")
        df = df.dropna(subset=["stop_lat", "stop_lon"]).reset_index(drop=True)
    else:
        print("Querying BigQuery (cal-itp-data-infra)...")
        df = fetch_stops()
        df.to_csv(args.save, index=False)
        print(f"  saved {len(df):,} stops -> {args.save}")

    print(f"stops with coords: {len(df):,}   agencies: {df['analysis_name'].nunique()}")

    # 1. cluster
    df["cluster_id"] = cluster_mod.assign_clusters(df, eps_meters=args.eps_meters)
    n_clusters_total = df["cluster_id"].nunique()
    print(f"clusters total (DBSCAN {args.eps_meters:g} m): {n_clusters_total:,}")

    # 2. exclusions, in order
    df, n_511 = excl.dedup_aggregator(df)
    print(f"  511 aggregator de-dup:          dropped {n_511:,} stops")

    df, n_rail = excl.drop_protected_operators(df)
    df, n_rail2 = drop_extra_rail(df)
    print(f"  protected single-operator rail: dropped {n_rail + n_rail2:,} stops")

    # 3. major-station flag needs cluster_span_meters; compute per cluster
    spans = df.groupby("cluster_id", group_keys=False).apply(
        lambda g: cluster_mod.cluster_span_meters(g), include_groups=False
    )
    df["cluster_span_meters"] = df["cluster_id"].map(spans)
    df, n_major = excl.flag_major_stations(df)

    # 4. per-cluster rollup
    per = df.groupby("cluster_id").agg(
        n_stops=("cluster_id", "size"),
        n_agencies=("analysis_name", "nunique"),
        major=("matching_scope", lambda s: (s == excl.SCOPE_MAJOR_STATION).any()),
    )
    multi = per["n_agencies"] > 1
    in_scope = multi & ~per["major"]

    # persist the in-scope stop areas for the next step (the review workflow)
    out = DATA_DIR / f"stop_areas_to_analyze_{date.today():%Y_%m_%d}.csv"
    in_scope_ids = per.index[in_scope]
    df[df["cluster_id"].isin(in_scope_ids)].to_csv(out, index=False)

    print("\n================  RESULT  ================")
    print(f"clusters remaining (after rail + 511 drops): {len(per):,}")
    print(f"  single-agency clusters (mint ID, trivial): {(~multi).sum():,}")
    print(f"  multi-agency clusters (total):             {multi.sum():,}")
    print(f"  multi-agency & MAJOR_STATION (to agency):  {(multi & per['major']).sum():,}")
    print(f"  >>> multi-agency IN-SCOPE (need analysis): {in_scope.sum():,}  <<<")
    print(f"      stops inside those in-scope clusters:  {per.loc[in_scope, 'n_stops'].sum():,}")
    print("\nagencies-per-cluster (in-scope multi-agency):")
    print(per.loc[in_scope, "n_agencies"].value_counts().sort_index().to_string())
    print(f"\nin-scope stop areas written -> {out}")


if __name__ == "__main__":
    main()
