"""
Pull route shapes for every (feed, route) serving a grouping-candidate stop.

Route-level (not per-stop) to stay off dim_stop_times: targets come from the
route_dirs / route_ids columns of the stops pull, for stops in any MULTI-STOP
group (same-agency corners split too — detect_splits nominates them all).
Feed versions are the ACTIVE ones per cohort URL as of the rollup month-end
AND today — the same pair pull_stops uses for route_dirs, so a stop whose
directions came from the month-end version still finds its shapes. One best
shape per (feed, route, direction) by trip count.

  uv run scripts/pull_shapes.py --dry-run     # print scan size only
  uv run scripts/pull_shapes.py               # ~14 GB measured (Oct cohort)
  uv run scripts/pull_shapes.py --per-stop    # ~28 GB: shapes per (feed, stop)

Output: data/route_shapes.csv (route_id, direction_id, shape GeoJSON) —
consumed by detect_splits.py for travel-heading adjudication.

--per-stop additionally writes data/stop_shapes.csv for every stop appearing
in split_pairs.csv, joining through dim_stop_times so (a) rollup-vs-trips
route_id mismatches and shapeless route tokens don't lose coverage, and
(b) the shape variant that actually SERVES the stop wins (not the route's
statewide-dominant branch). detect_splits treats these as complete evidence,
restoring full coverage where route-level matching can't.
"""

import argparse
import json
from pathlib import Path

import pandas as pd

from pull_stops import active_feeds

REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = REPO_ROOT / "data"
OUT = DATA_DIR / "route_shapes.csv"
OUT_STOP = DATA_DIR / "stop_shapes.csv"
MAX_SCAN_GB = 40.0   # hard gate; measured: ~14 GB route-level, ~28 GB per-stop

ST = "cal-itp-data-infra.mart_gtfs.dim_stop_times"
TR = "cal-itp-data-infra.mart_gtfs.dim_trips"
RT = "cal-itp-data-infra.mart_gtfs.dim_routes"
SH = "cal-itp-data-infra.mart_gtfs.dim_shapes_arrays"


def latest_stops() -> Path:
    hits = sorted(DATA_DIR.glob("stops_[0-9]*.csv"))
    if not hits:
        raise SystemExit("No data/stops_<YYYY_MM>.csv — run pull_stops.py first.")
    return hits[-1]


def latest_canonicalizer() -> Path:
    hits = sorted(DATA_DIR.glob("canonicalizer_stops_*.csv"))
    if not hits:
        raise SystemExit("No canonicalizer output — run cluster_stops.py first.")
    return hits[-1]


def cohort_month_end(stops_path: Path):
    """stops_2026_09.csv -> 2026-09-30 (the rollup month's last day)."""
    import re
    m = re.search(r"stops_(\d{4})_(\d{2})", stops_path.name)
    if not m:
        raise SystemExit(f"can't parse rollup month from {stops_path.name}")
    first = pd.Timestamp(year=int(m.group(1)), month=int(m.group(2)), day=1)
    return (first + pd.offsets.MonthEnd(1)).date()


def targets() -> pd.DataFrame:
    """(base64_url, route_id) pairs serving any stop in a multi-STOP group."""
    canon = pd.read_csv(latest_canonicalizer(), low_memory=False, dtype=str)
    s9 = pd.read_csv(latest_stops(), low_memory=False, dtype=str)
    size = pd.to_numeric(canon["cluster_size"], errors="coerce")
    key = ["base64_url", "stop_id"] if "base64_url" in canon.columns else \
          ["analysis_name", "stop_id"]
    cand = canon[size >= 2][key].drop_duplicates()
    s = s9.merge(cand, on=key)
    out = set()
    for r in s.itertuples():
        routes = set()
        if isinstance(r.route_dirs, str) and r.route_dirs:
            routes |= {t.rsplit("|", 1)[0] for t in r.route_dirs.split(";") if t}
        if isinstance(r.route_ids, str) and r.route_ids:
            routes |= {x for x in r.route_ids.split(";") if x}
        out |= {(r.base64_url, rt) for rt in routes}
    t = pd.DataFrame(sorted(out), columns=["base64_url", "route_id"])
    print(f"{len(t):,} (feed, route) targets from {len(s):,} candidate stop records")
    return t


def build_sql(t: pd.DataFrame, active: pd.DataFrame) -> str:
    # an empty frame would render IN () / UNNEST([]) — invalid SQL (cf. #15)
    assert len(t), "no (feed, route) targets — run pull_stops + cluster_stops first"
    assert len(active), "no active feed versions matched the target URLs"
    rows = ",\n".join(
        f"STRUCT({json.dumps(u)} AS u, {json.dumps(r)} AS r)" for u, r in t.itertuples(index=False))
    days = sorted({ts.strftime("%Y-%m-%d") for ts in active["_feed_valid_from"]})
    day_list = ", ".join(f"TIMESTAMP '{d}'" for d in days)
    key_list = ", ".join(f"'{k}'" for k in sorted(set(active["feed_key"])))
    return f"""
WITH tgt AS (SELECT * FROM UNNEST([{rows}])),
route_shapes AS (
  SELECT tr.base64_url, tr.feed_key, tr.route_id,
         IFNULL(tr.direction_id, -1) AS direction_id, tr.shape_id,
         COUNT(*) AS n_trips
  FROM `{TR}` tr
  JOIN tgt ON tgt.u = tr.base64_url AND tgt.r = tr.route_id
  WHERE TIMESTAMP_TRUNC(tr._feed_valid_from, DAY) IN ({day_list})
    AND tr.feed_key IN ({key_list})
    AND tr.shape_id IS NOT NULL
  GROUP BY 1, 2, 3, 4, 5
),
best AS (
  SELECT * FROM route_shapes
  QUALIFY ROW_NUMBER() OVER (
    PARTITION BY base64_url, route_id, direction_id
    ORDER BY n_trips DESC, shape_id) = 1
)
SELECT
  b.base64_url, b.route_id, b.direction_id, b.n_trips,
  ANY_VALUE(rt.route_short_name) AS route_short_name,
  ANY_VALUE(ST_ASGEOJSON(ST_SIMPLIFY(
    ST_MAKELINE(ARRAY(SELECT pt FROM UNNEST(sh.pt_array) AS pt)), 3))) AS shape_geojson
FROM best b
JOIN `{SH}` sh ON sh.feed_key = b.feed_key AND sh.shape_id = b.shape_id
LEFT JOIN `{RT}` rt ON rt.feed_key = b.feed_key AND rt.route_id = b.route_id
  AND TIMESTAMP_TRUNC(rt._feed_valid_from, DAY) IN ({day_list})
WHERE TIMESTAMP_TRUNC(sh._feed_valid_from, DAY) IN ({day_list})
  AND sh.feed_key IN ({key_list})
GROUP BY 1, 2, 3, 4
"""


def stop_targets() -> pd.DataFrame:
    """(base64_url, stop_id) for every stop in a pair that NEEDS rescue —
    non-full coverage (missing/shapeless routes, revisits, no shapes). Pairs
    already adjudicated on full evidence don't pay for a stop_times scan."""
    p = DATA_DIR / "split_pairs.csv"
    if not p.exists():
        raise SystemExit("No data/split_pairs.csv — run detect_splits.py first.")
    sp = pd.read_csv(p, dtype=str)
    if "coverage" in sp.columns:
        sp = sp[sp["coverage"] != "full"]
    pairs = ({(r.a_url, r.a_stop) for r in sp.itertuples()}
             | {(r.b_url, r.b_stop) for r in sp.itertuples()})
    t = pd.DataFrame(sorted(pairs), columns=["base64_url", "stop_id"])
    print(f"{len(t):,} (feed, stop) targets from {len(sp):,} non-full-coverage pairs")
    return t


def build_stop_sql(t: pd.DataFrame, active: pd.DataFrame) -> str:
    assert len(t), "no (feed, stop) targets — run detect_splits.py first"
    assert len(active), "no active feed versions matched the target URLs"
    rows = ",\n".join(
        f"STRUCT({json.dumps(u)} AS u, {json.dumps(s)} AS s)" for u, s in t.itertuples(index=False))
    days = sorted({ts.strftime("%Y-%m-%d") for ts in active["_feed_valid_from"]})
    day_list = ", ".join(f"TIMESTAMP '{d}'" for d in days)
    key_list = ", ".join(f"'{k}'" for k in sorted(set(active["feed_key"])))
    return f"""
WITH tgt AS (SELECT * FROM UNNEST([{rows}])),
stop_shapes AS (
  SELECT st.base64_url, st.stop_id, tr.feed_key, tr.route_id,
         IFNULL(tr.direction_id, -1) AS direction_id, tr.shape_id,
         COUNT(*) AS n_trips
  FROM `{ST}` st
  JOIN `{TR}` tr ON st.feed_key = tr.feed_key AND st.trip_id = tr.trip_id
  JOIN tgt ON tgt.u = st.base64_url AND tgt.s = st.stop_id
  WHERE TIMESTAMP_TRUNC(st._feed_valid_from, DAY) IN ({day_list})
    AND st.feed_key IN ({key_list})
    AND TIMESTAMP_TRUNC(tr._feed_valid_from, DAY) IN ({day_list})
    AND tr.feed_key IN ({key_list})
    AND tr.shape_id IS NOT NULL
  GROUP BY 1, 2, 3, 4, 5, 6
),
best AS (
  SELECT * FROM stop_shapes
  QUALIFY ROW_NUMBER() OVER (
    PARTITION BY base64_url, stop_id, route_id, direction_id
    ORDER BY n_trips DESC, shape_id) = 1
)
SELECT
  b.base64_url, b.stop_id, b.route_id, b.direction_id, b.n_trips,
  ANY_VALUE(rt.route_short_name) AS route_short_name,
  ANY_VALUE(ST_ASGEOJSON(ST_SIMPLIFY(
    ST_MAKELINE(ARRAY(SELECT pt FROM UNNEST(sh.pt_array) AS pt)), 3))) AS shape_geojson
FROM best b
JOIN `{SH}` sh ON sh.feed_key = b.feed_key AND sh.shape_id = b.shape_id
LEFT JOIN `{RT}` rt ON rt.feed_key = b.feed_key AND rt.route_id = b.route_id
  AND TIMESTAMP_TRUNC(rt._feed_valid_from, DAY) IN ({day_list})
WHERE TIMESTAMP_TRUNC(sh._feed_valid_from, DAY) IN ({day_list})
  AND sh.feed_key IN ({key_list})
GROUP BY 1, 2, 3, 4, 5
"""


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--per-stop", action="store_true",
                    help="shapes per (feed, stop) via dim_stop_times -> stop_shapes.csv")
    args = ap.parse_args()
    from google.cloud import bigquery
    client = bigquery.Client(project="cal-itp-data-infra")
    t = stop_targets() if args.per_stop else targets()
    # month-end AND today, like pull_stops.pull_raw: route_dirs can come from
    # either version, so shapes must cover both or stops lose coverage
    month_end = cohort_month_end(latest_stops())
    urls = set(t["base64_url"])
    if args.per_stop:
        # today-only: dim_stop_times is the expensive table and the month-end
        # day set would double the scan (54 GB measured vs ~28). Stops that
        # exist ONLY in the month-end version (~100 statewide) stay on
        # route-level shapes / review instead.
        active = active_feeds(client, urls=urls)
        print(f"{len(active):,} active feed versions (today)")
    else:
        active = pd.concat([
            active_feeds(client, urls=urls, as_of=month_end),
            active_feeds(client, urls=urls),
        ]).drop_duplicates(subset=["feed_key"])
        print(f"{len(active):,} active feed versions (as of {month_end} and today)")
    sql = build_stop_sql(t, active) if args.per_stop else build_sql(t, active)
    job = client.query(sql, job_config=bigquery.QueryJobConfig(dry_run=True, use_query_cache=False))
    gb = job.total_bytes_processed / 1e9
    print(f"dry run: {gb:.2f} GB")
    if args.dry_run:
        return
    assert gb <= MAX_SCAN_GB, f"scan {gb:.1f} GB exceeds the {MAX_SCAN_GB:.0f} GB gate"
    df = client.query(sql).to_dataframe()
    out = OUT_STOP if args.per_stop else OUT
    df.to_csv(out, index=False)
    kind = "stop-route-direction" if args.per_stop else "route-direction"
    print(f"{len(df):,} {kind} shapes -> {out} ({out.stat().st_size / 1e6:.1f} MB)")


if __name__ == "__main__":
    main()
