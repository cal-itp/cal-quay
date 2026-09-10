"""
Pull the full list of current California GTFS stops, minus stops we shouldn't
consider: the 511 regional aggregator's duplicate copies and rail-only stations.

Source: mart_gtfs_rollup.fct_monthly_scheduled_stops — every stop that had
scheduled service in the most recent month. More complete on feeds than
dim_stops_latest.

Exclusions:
  - feed "Bay Area 511 Regional Schedule": the aggregate feed re-publishing every
    Bay Area operator's stops; each operator also appears via its own
    per-operator 511 feed, so these rows are duplicates. (A handful of stops
    that only exist in the regional feed are dropped too — first-pass tradeoff.)
    Excluded by name, not by its Combined Regional Feed flag, because the other
    combined feed (VCTC GMV) is Ventura County's best source and must stay.
  - Regional Precursor Feeds: an operator's direct feed that MTC 511 (or VCTC)
    ingests and re-publishes — the same network twice, often with renamed stop
    ids (VTA 3022 -> 511's 63022), which the exact-duplicate filter can't
    catch. A precursor is kept when it's the operator's only feed in the pull
    (e.g. Santa Cruz METRO).
  - rail-only stops: route_types within {0 tram/light rail, 1 subway, 2 rail} —
    stations, not curbside stops. Stops also served by bus are kept.
  - exact duplicates: the same stop (identical stop_id + name + coordinates)
    published under two dataset names for one operator (e.g. a legacy feed and
    its vendor replacement, both without an analysis_name mapping). One row is
    kept, preferring the properly mapped agency label.

Two stages, so iterating on the cleaning logic never re-hits BigQuery:
  1. pull  — the raw query result is saved untouched to stops_raw_<YYYY_MM>.parquet
  2. process — exclusions/dedupe run on the raw file, writing stops_<YYYY_MM>.csv
     plus .gpkg (QGIS + ArcGIS Pro) and .fgb (FlatGeobuf)
If a raw parquet already exists, the script just reprocesses it; --refresh forces
a new BigQuery pull.

Requires `gcloud auth application-default login` (cal-itp-data-infra).

  uv run scripts/pull_stops.py --dry-run   # estimate the scan, pull nothing
  uv run scripts/pull_stops.py             # pull only if no raw file, then process
  uv run scripts/pull_stops.py --refresh   # force a fresh pull
"""

import argparse
from pathlib import Path

import geopandas as gpd
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = REPO_ROOT / "data"

TABLE = "cal-itp-data-infra.mart_gtfs_rollup.fct_monthly_scheduled_stops"
TABLE_DATASETS = "cal-itp-data-infra.mart_transit_database.dim_gtfs_datasets"

EXCLUDE_FEEDS = {"Bay Area 511 Regional Schedule"}
RAIL_ROUTE_TYPES = {"0", "1", "2"}

# Stopgap agency labels for the 41 datasets whose analysis_name is blank in the
# transit database (as of Sept 2026). Derived from the warehouse's own org links
# (dim_provider_gtfs_data.organization_name), and where the operator's OTHER
# feed already has an analysis_name, matched to that exact string so the labels
# merge. The smarter fix, in preference order:
#   (a) get analysis_name filled in the Airtable transit database for these
#       datasets — it flows to dim_gtfs_datasets automatically and this dict
#       can be deleted; or
#   (b) label by organization_name via dim_provider_gtfs_data
#       (schedule_gtfs_dataset_key join, _is_current). Reviewed Sept 2026: every
#       feed in the pull has a current org link, so this self-heals as new
#       feeds appear — but 11 feeds link to >1 org (consolidated feeds like
#       Humboldt/Sacramento/VCTC GMV/Flixbus) and need an analysis_name
#       fallback, and the precursor guard below must then key on org rather
#       than label (mixed org/analysis_name labels diverge for pairs like the
#       Sonoma precursor vs its 511 subfeed, letting duplicates back in).
# Separately, dim_organizations.public_currently_operating is a possible SCOPE
# filter, not a labeling fix: ~20 feeds in the pull belong to orgs marked not
# publicly operating (university shuttles — Stanford, UC*, CSULB, Pepperdine,
# USD — private TMAs, FlixBus/Greyhound, cruise/ferry operators). Whether those
# stops belong in the AB 1599 registry is an open question for Caltrans; if
# not, it's a one-line filter via the dim_provider_gtfs_data organization join.
ALIASES = {
    "AC Transit Schedule": "Alameda-Contra Costa Transit District",
    "Basin Transit GMV Schedule": "Basin Transit",
    "Bay Area 511 Emery Express Schedule": "Quarterra Living Inc",
    "Bulldog Express PassioGo Schedule": "Fresno State University",
    "CSULB Shuttle PassioGo Schedule": "California State University Long Beach",
    "Clovis PassioGo Schedule": "City of Clovis",
    "Commute.org Schedules": "Commute.org and Menlo Park Community Shuttles Schedule",
    "County Connection Schedule": "Central Contra Costa Transit Authority",
    "Dana Point Trolley PassioGo Schedule": "City of Dana Point",
    "Desert Roadrunner GMV Schedule": "Palo Verde Valley Transit Agency",
    "Emery Go-Round TripShot Schedule": "Emeryville Transportation Management Agency",
    "Gold Coast Schedule": "Ventura County (VCTC, Gold Coast, Cities of Camarillo, Moorpark, Ojai, Simi Valley, Thousand Oaks)",
    "Golden Gate Bridge Schedule": "Golden Gate Bridge, Highway and Transportation District",
    "LAX Shuttles Schedule": "Los Angeles World Airports",
    "Long Beach Transit Water Taxis GTFS Schedule": "Long Beach Transit",
    "MVGO Schedule": "Mountain View Transportation Management Association",
    "Merced GMV Schedule": "Transit Joint Powers Authority for Merced County",
    "Moorpark Schedule": "Ventura County (VCTC, Gold Coast, Cities of Camarillo, Moorpark, Ojai, Simi Valley, Thousand Oaks)",
    "Mountain Transit GMV Schedule": "Mountain Area Regional Transit Authority",
    "Mountain View Community Shuttle Schedule": "City of Mountain View",
    "Peppedine University Shuttles Schedule": "Pepperdine University",
    "Ridgecrest Schedule": "City of Ridgecrest",
    "SCVTA Schedule": "Santa Clara Valley Transportation Authority",
    "Santa Rosa CityBus GMV Schedule": "City of Santa Rosa",
    "Simi Valley Schedule": "Ventura County (VCTC, Gold Coast, Cities of Camarillo, Moorpark, Ojai, Simi Valley, Thousand Oaks)",
    "SolTrans Schedule": "Solano Transportation Authority",
    "Sonoma County Transit Schedule": "Sonoma County Transit Schedule",
    "Sonoma Schedule": "Sonoma County Transit Schedule",
    "South San Francisco Schedule": "City of South San Francisco",
    "SunLine GMV Schedule": "SunLine Transit Agency",
    "Tahoe Transportation District GMV Schedule": "Tahoe Transportation District",
    "Thousand Oaks Schedule": "Ventura County (VCTC, Gold Coast, Cities of Camarillo, Moorpark, Ojai, Simi Valley, Thousand Oaks)",
    "Tri-Valley Wheels Schedule": "Livermore-Amador Valley Transit Authority",
    "University of San Diego Tram Services Schedule": "University of San Diego",
    "VCTC Intercity Schedule": "Ventura County (VCTC, Gold Coast, Cities of Camarillo, Moorpark, Ojai, Simi Valley, Thousand Oaks)",
    "Vacaville Schedule": "City of Vacaville",
    "Victor Valley GMV Schedule": "Victor Valley Transit Authority",
    "Vine GMV Schedule": "Napa Valley Transportation Authority",
    "Vine Schedule": "Napa Valley Transportation Authority",
    "WestCAT Schedule": "Western Contra Costa Transit Authority",
    "Yuba-Sutter PassioGo Schedule": "Yuba-Sutter Transit Authority",
}

SQL = f"""
WITH latest_month AS (
  SELECT MAX(month_first_day) AS m FROM `{TABLE}`
),
name_map AS (
  SELECT
    name,
    ANY_VALUE(analysis_name) AS analysis_name,
    ANY_VALUE(regional_feed_type HAVING MAX _valid_from) AS regional_feed_type
  FROM `{TABLE_DATASETS}`
  WHERE name IS NOT NULL
  GROUP BY name
)
SELECT
  COALESCE(nm.analysis_name, ms.name) AS analysis_name,
  ms.name                             AS feed_name,
  nm.regional_feed_type,
  ms.stop_id,
  ms.stop_name,
  ms.stop_code,
  ms.stop_key,
  ST_Y(ms.pt_geom)                    AS stop_lat,
  ST_X(ms.pt_geom)                    AS stop_lon,
  ST_GEOHASH(ms.pt_geom, 7)           AS geohash_id_7,
  ST_GEOHASH(ms.pt_geom, 8)           AS geohash_id_8,
  ST_GEOHASH(ms.pt_geom, 9)           AS geohash_id_9,
  ms.route_type_array,
  ms.total_stop_arrivals,
  ms.day_type,
  ms.month_first_day
FROM `{TABLE}` ms
JOIN latest_month lm ON ms.month_first_day = lm.m
LEFT JOIN name_map nm ON ms.name = nm.name
"""


def _client():
    from google.cloud import bigquery

    return bigquery.Client(project="cal-itp-data-infra")


def dry_run() -> float:
    from google.cloud import bigquery

    jc = bigquery.QueryJobConfig(dry_run=True, use_query_cache=False)
    job = _client().query(SQL, job_config=jc)
    return job.total_bytes_processed / 1e9


def _union_route_types(s: pd.Series) -> str:
    """Union the per-day_type route_type arrays into a sorted 'a,b,c' string."""
    vals = set()
    for arr in s.dropna():
        vals.update(int(x) for x in arr)
    return ",".join(str(v) for v in sorted(vals))


def _rail_only(route_types: str) -> bool:
    types = set(route_types.split(",")) if route_types else set()
    return bool(types) and types <= RAIL_ROUTE_TYPES


def pull_raw(outdir: Path) -> Path:
    """Run the BigQuery pull and save the untouched result as parquet."""
    print(f"Querying BigQuery: {TABLE} (latest month)...")
    df = _client().query(SQL).to_dataframe()
    # plain datetime: the BigQuery client's 'dbdate' extension dtype doesn't
    # survive a parquet round-trip without db_dtypes imported at read time
    df["month_first_day"] = pd.to_datetime(df["month_first_day"])
    month = df["month_first_day"].iloc[0]
    raw_out = outdir / f"stops_raw_{month:%Y_%m}.parquet"
    df.to_parquet(raw_out, index=False)
    print(f"  {len(df):,} raw rows -> {raw_out}")
    return raw_out


def process(raw_path: Path, outdir: Path) -> None:
    """Dedupe and exclude from a saved raw parquet; write the cleaned outputs."""
    df = pd.read_parquet(raw_path)
    df["stop_lat"] = pd.to_numeric(df["stop_lat"], errors="coerce")
    df["stop_lon"] = pd.to_numeric(df["stop_lon"], errors="coerce")
    df = df.dropna(subset=["stop_lat", "stop_lon"]).reset_index(drop=True)

    month = pd.to_datetime(df["month_first_day"].iloc[0])
    stamp = f"{month:%Y_%m}"

    # one row per stop: coords identical across day_types; union types, sum arrivals
    stops = (
        df.sort_values("total_stop_arrivals", ascending=False)
        .groupby("stop_key", as_index=False)
        .agg(
            analysis_name=("analysis_name", "first"),
            feed_name=("feed_name", "first"),
            regional_feed_type=("regional_feed_type", "first"),
            stop_id=("stop_id", "first"),
            stop_name=("stop_name", "first"),
            stop_code=("stop_code", "first"),
            stop_lat=("stop_lat", "first"),
            stop_lon=("stop_lon", "first"),
            geohash_id_7=("geohash_id_7", "first"),
            geohash_id_8=("geohash_id_8", "first"),
            geohash_id_9=("geohash_id_9", "first"),
            total_stop_arrivals=("total_stop_arrivals", "sum"),
            route_types=("route_type_array", _union_route_types),
        )
    )
    stops["month"] = f"{month:%Y-%m}"
    stops["analysis_name"] = (
        stops["feed_name"].map(ALIASES).fillna(stops["analysis_name"])
    )
    n_all = len(stops)

    dup_511 = stops["feed_name"].isin(EXCLUDE_FEEDS)
    rail = stops["route_types"].map(_rail_only)
    # a precursor feed duplicates its 511/VCTC re-publication — drop it, unless
    # it's the operator's only feed in the pull (then it IS the source)
    precursor = stops["regional_feed_type"] == "Regional Precursor Feed"
    label_has_other = (~precursor).groupby(stops["analysis_name"]).transform("any")
    dup_precursor = precursor & label_has_other
    stops = stops[~dup_511 & ~rail & ~dup_precursor]

    # same stop under two dataset names -> keep one, preferring a mapped agency
    # label over the raw "<feed> Schedule" fallback (fallback <=> names equal)
    stops["_fallback"] = stops["analysis_name"] == stops["feed_name"]
    stops = stops.sort_values("_fallback")
    dup_exact = stops.duplicated(subset=["stop_id", "stop_name", "stop_lat", "stop_lon"])
    stops = stops[~dup_exact].drop(columns="_fallback").reset_index(drop=True)

    print(
        f"  {n_all:,} unique served stops (month {month:%Y-%m}); excluding "
        f"{dup_511.sum():,} 511-regional duplicates + "
        f"{dup_precursor.sum():,} precursor-feed duplicates + {rail.sum():,} rail-only + "
        f"{dup_exact.sum():,} exact cross-feed duplicates "
        f"-> {len(stops):,} stops across {stops['analysis_name'].nunique()} agencies"
    )

    csv_out = outdir / f"stops_{stamp}.csv"
    gpkg_out = outdir / f"stops_{stamp}.gpkg"
    fgb_out = outdir / f"stops_{stamp}.fgb"

    stops.to_csv(csv_out, index=False)
    gdf = gpd.GeoDataFrame(
        stops, geometry=gpd.points_from_xy(stops["stop_lon"], stops["stop_lat"]), crs="EPSG:4326"
    )
    gdf.to_file(gpkg_out, layer="stops", driver="GPKG")
    gdf.to_file(fgb_out, driver="FlatGeobuf")

    print(f"  CSV        -> {csv_out}  (feed to: find_shared_stops.py)")
    print(f"  GeoPackage -> {gpkg_out}  (QGIS + ArcGIS)")
    print(f"  FlatGeobuf -> {fgb_out}  (QGIS; ArcGIS via Data Interop)")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true", help="estimate scan size and exit")
    ap.add_argument(
        "--refresh", action="store_true",
        help="pull fresh from BigQuery even if a raw parquet exists",
    )
    ap.add_argument("--outdir", type=Path, default=DATA_DIR, help="output directory")
    args = ap.parse_args()

    if args.dry_run:
        print(f"dry-run scan: {dry_run():.2f} GB")
        return

    args.outdir.mkdir(exist_ok=True)
    raws = sorted(args.outdir.glob("stops_raw_*.parquet"))
    if raws and not args.refresh:
        raw = raws[-1]
        print(f"Reprocessing {raw.name} (use --refresh for a fresh BigQuery pull)")
    else:
        raw = pull_raw(args.outdir)
    process(raw, args.outdir)


if __name__ == "__main__":
    main()
