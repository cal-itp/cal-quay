"""
Detect grouped stops that should be SEPARATE registry stops (implements #16).

Two nomination signals find same-group pairs that look like different boarding
locations; route-shape travel headings then adjudicate every nominated pair:

  nominate  A. street geometry — each stop snaps to its nearest road edge
               (clearly: >= CLEAR_MARGIN_M nearer its own street than the
               other stop's street); street orientations 60-120 deg apart
               means the pair boards on perpendicular streets of one corner.
            B. crossed names — "A St & B St" vs "B St & A St" in one group.
  adjudicate   travel heading at the stop from each serving route's shape
               (project the stop, take a +-CHORD_M chord, compass bearing).
               direction_id is never compared across feeds — headings are
               physical. Verdicts:
                 min pairwise diff < 30 deg      -> VETO (parallel: same street+direction)
                 all diffs in [60, 120] deg      -> CONFIRM kitty (perpendicular)
                 min pairwise diff > 150 deg     -> across-street (antiparallel)
                 anything else                   -> mixed       (review only)
                 either stop lacks shapes        -> no-shapes   (review only)

Output: data/split_pairs.csv. CONFIRM / across-street rows become cannot-link
constraints the next time cluster_stops.py runs; VETO / mixed / no-shapes rows
are kept for the human-review queue. Verdicts shape the PROPOSAL only — every
multi-agency grouping still goes through human review (54-case imagery audit:
36/36 decided CONFIRM+VETO verdicts correct, across-street all "unsure").

Inputs: newest canonicalizer_stops_*.csv + stops_*.csv, data/roads_near_stops.fgb,
data/route_shapes.csv (scripts/pull_shapes.py) and optionally data/stop_shapes.csv.

  uv run scripts/detect_splits.py
"""

import json
import math
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
from shapely.geometry import shape as shp_shape

from cluster_stops import SPLIT_CONSTRAINT_PREFIXES, TRIMMED_ROADS, ensure_roads

REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = REPO_ROOT / "data"
OUT = DATA_DIR / "split_pairs.csv"
CA_ALBERS = "EPSG:3310"

ROAD_NEAR_M = 15.0      # stop must be this close to "its" street
MIN_SEP_M = 5.0         # ignore (near-)coincident pairs
PERP_LO, PERP_HI = 60.0, 120.0
CLEAR_MARGIN_M = 5.0    # own street must be this much nearer than the other's

CHORD_M = 10.0          # heading chord half-length along the shape
MAX_SHAPE_DIST_M = 30.0  # shape must pass this close to the stop to count
PARALLEL_MAX_DEG = 30.0
ANTI_MIN_DEG = 150.0

VERDICT_VETO = "VETO (parallel: same street+direction)"
VERDICT_CONFIRM = "CONFIRM kitty (perpendicular)"
VERDICT_ACROSS = "across-street (antiparallel)"


def latest(pattern: str) -> Path:
    hits = sorted(DATA_DIR.glob(pattern))
    if not hits:
        raise SystemExit(f"No {pattern} in data/ — run the pipeline first.")
    return hits[-1]


# ---------------------------------------------------------------- nomination
def seg_bearing_at(line, pt, step=3.0):
    """Street orientation (deg, mod 180) of `line` nearest to `pt` (EPSG:3310)."""
    s = line.project(pt)
    a = line.interpolate(max(0.0, s - step))
    b = line.interpolate(min(line.length, s + step))
    if a.equals(b):
        return None
    return math.degrees(math.atan2(b.x - a.x, b.y - a.y)) % 180.0


def street_geometry_pairs(cand: pd.DataFrame, pts: gpd.GeoDataFrame,
                          roads: gpd.GeoDataFrame) -> list:
    """Same-group pairs on clearly perpendicular streets -> [(i, j, bearing_diff)]."""
    near = gpd.sjoin_nearest(pts[["geometry"]], roads[["geometry"]],
                             how="left", max_distance=ROAD_NEAR_M, distance_col="_d")
    near = near[~near.index.duplicated(keep="first")]
    cand = cand.copy()
    cand["road_idx"] = near["index_right"]
    cand["road_d"] = near["_d"]

    bearings = np.full(len(cand), np.nan)
    for i, (ri, geom) in enumerate(zip(cand["road_idx"], pts.geometry)):
        if pd.isna(ri):
            continue
        b = seg_bearing_at(roads.geometry.iloc[int(ri)], geom)
        if b is not None:
            bearings[i] = b
    print(f"  street bearings for {np.isfinite(bearings).sum():,} stops")

    out = []
    xy = np.c_[pts.geometry.x, pts.geometry.y]
    for _, grp in cand.groupby("cluster_id"):
        idx = grp.index.to_numpy()
        for ii in range(len(idx)):
            for jj in range(ii + 1, len(idx)):
                a, b = idx[ii], idx[jj]
                ba, bb = bearings[a], bearings[b]
                if not (np.isfinite(ba) and np.isfinite(bb)):
                    continue
                if float(np.hypot(*(xy[a] - xy[b]))) < MIN_SEP_M:
                    continue
                diff = abs(ba - bb) % 180.0
                diff = min(diff, 180.0 - diff)
                if not (PERP_LO <= diff <= PERP_HI):
                    continue
                # each stop must be CLEARLY on its own street — near a corner,
                # coincident curb records snap to different cross-streets
                ra = roads.geometry.iloc[int(cand.at[a, "road_idx"])]
                rb = roads.geometry.iloc[int(cand.at[b, "road_idx"])]
                ga, gb = pts.geometry.iloc[a], pts.geometry.iloc[b]
                if (ga.distance(rb) < cand.at[a, "road_d"] + CLEAR_MARGIN_M or
                        gb.distance(ra) < cand.at[b, "road_d"] + CLEAR_MARGIN_M):
                    continue
                out.append((a, b, round(diff, 1)))
    return out


def name_parts(nm) -> tuple | None:
    """'A St & B St' -> ('a st', 'b st'); None unless exactly two parts."""
    if not isinstance(nm, str):
        return None
    s = nm.lower()
    for sep in (" & ", "&", " and ", " / ", "/", " @ ", "@", " at "):
        if sep in s:
            parts = [" ".join(p.split()).strip(" .,") for p in s.split(sep)]
            if len(parts) == 2 and parts[0] and parts[1] and parts[0] != parts[1]:
                return (parts[0], parts[1])
            return None
    return None


def crossed_name_pairs(cand: pd.DataFrame, pts: gpd.GeoDataFrame) -> list:
    """Same-group pairs named 'A & B' vs 'B & A', > MIN_SEP_M apart -> [(i, j)]."""
    parts = [name_parts(nm) for nm in cand["stop_name"]]
    xy = np.c_[pts.geometry.x, pts.geometry.y]
    out = []
    for _, grp in cand.groupby("cluster_id"):
        idx = grp.index.to_numpy()
        for ii in range(len(idx)):
            for jj in range(ii + 1, len(idx)):
                a, b = idx[ii], idx[jj]
                pa, pb = parts[a], parts[b]
                if pa is None or pb is None or pa != (pb[1], pb[0]):
                    continue
                if float(np.hypot(*(xy[a] - xy[b]))) < MIN_SEP_M:
                    continue
                out.append((a, b))
    return out


# -------------------------------------------------------------- adjudication
def load_shapes() -> tuple[dict, dict]:
    """(stop-level, route-level) shape indexes with EPSG:3310 geometries."""
    def to_3310(geojson_strs):
        geoms = [shp_shape(json.loads(g)) for g in geojson_strs]
        return list(gpd.GeoSeries(geoms, crs="EPSG:4326").to_crs(CA_ALBERS))

    stop_ix: dict = {}
    p = DATA_DIR / "stop_shapes.csv"
    if p.exists():
        df = pd.read_csv(p, dtype=str)
        for r, geom in zip(df.itertuples(), to_3310(df["shape_geojson"])):
            stop_ix.setdefault((r.base64_url, str(r.stop_id)), []).append(geom)
        print(f"  {len(df):,} per-stop shapes")

    route_ix: dict = {}
    # optional historical backfill first, so active-version shapes (the
    # canonical pull_shapes.py output) overwrite any overlapping keys
    for fname in ("route_shapes_backfill.csv", "route_shapes.csv"):
        p = DATA_DIR / fname
        if not p.exists():
            continue
        df = pd.read_csv(p, dtype=str)
        df["direction_id"] = df["direction_id"].astype(float).astype(int)
        for r, geom in zip(df.itertuples(), to_3310(df["shape_geojson"])):
            route_ix[(r.base64_url, r.route_id, r.direction_id)] = geom
        print(f"  {len(df):,} route-direction shapes from {fname}")
    if not stop_ix and not route_ix:
        raise SystemExit("No shape data — run scripts/pull_shapes.py first.")
    return stop_ix, route_ix


def heading_at(line, pt) -> float | None:
    """Compass travel bearing (deg, 0=N) of `line` where it passes `pt`; None
    when the shape doesn't pass near the stop. The chord clamps at the shape
    ends so TERMINAL stops still get a heading (their final travel direction)."""
    if line.distance(pt) > MAX_SHAPE_DIST_M:
        return None
    s = line.project(pt)
    a = line.interpolate(max(0.0, s - CHORD_M))
    b = line.interpolate(min(line.length, s + CHORD_M))
    if a.equals(b):
        return None
    return math.degrees(math.atan2(b.x - a.x, b.y - a.y)) % 360.0


def fold180(d: float) -> float:
    d = abs(d) % 360.0
    return min(d, 360.0 - d)


def classify(ha: list, hb: list) -> str:
    """Verdict from the two stops' travel-heading sets."""
    if not ha or not hb:
        return "no-shapes"
    diffs = [fold180(a - b) for a in ha for b in hb]
    mn = min(diffs)
    if mn < PARALLEL_MAX_DEG:
        return VERDICT_VETO
    if all(PERP_LO <= d <= PERP_HI for d in diffs):
        return VERDICT_CONFIRM
    if mn > ANTI_MIN_DEG:
        return VERDICT_ACROSS
    return "mixed"


class HeadingLookup:
    """Travel headings at a stop from the shapes of its serving routes:
    per-stop shapes when pulled, else route-level shapes via route_dirs/route_ids."""

    def __init__(self, stops: pd.DataFrame, stop_ix: dict, route_ix: dict):
        self.s = stops.set_index(["analysis_name", "stop_id"]).sort_index()
        self.stop_ix, self.route_ix = stop_ix, route_ix
        self._cache: dict = {}

    def shapes_for(self, agency, sid) -> list:
        try:
            rows = self.s.loc[[(agency, str(sid))]]
        except KeyError:
            return []
        row = rows.iloc[0]
        url = row["base64_url"]
        shapes = self.stop_ix.get((url, str(sid)), [])
        if shapes:
            return shapes
        rds = set()
        if isinstance(row.get("route_dirs"), str) and row["route_dirs"]:
            for tok in row["route_dirs"].split(";"):
                if "|" in tok:
                    rt, d = tok.rsplit("|", 1)
                    rds.add((rt, int(d)))
        if isinstance(row.get("route_ids"), str) and row["route_ids"]:
            known = {rt for rt, _ in rds}
            for rt in row["route_ids"].split(";"):
                if rt and rt not in known:
                    rds |= {(rt, d) for d in (-1, 0, 1) if (url, rt, d) in self.route_ix}
        return [self.route_ix[(url, rt, d)] for rt, d in sorted(rds)
                if (url, rt, d) in self.route_ix]

    def headings(self, agency, sid, pt3310) -> list:
        key = (agency, str(sid))
        if key not in self._cache:
            hs = [heading_at(line, pt3310) for line in self.shapes_for(agency, sid)]
            self._cache[key] = sorted({round(h, 1) for h in hs if h is not None})
        return self._cache[key]


# ---------------------------------------------------------------------- main
def main() -> None:
    canon = latest("canonicalizer_stops_*.csv")
    df = pd.read_csv(canon, low_memory=False)
    df["stop_id"] = df["stop_id"].astype(str)
    size = df.groupby("cluster_id")["stop_id"].transform("size")
    cand = df[size > 1].copy().reset_index(drop=True)
    pts = gpd.GeoDataFrame(
        cand, geometry=gpd.points_from_xy(cand.stop_lon, cand.stop_lat),
        crs="EPSG:4326").to_crs(CA_ALBERS)
    print(f"{len(cand):,} stops in multi-stop groups from {canon.name}")

    ensure_roads()
    roads = gpd.read_file(TRIMMED_ROADS, engine="pyogrio").to_crs(CA_ALBERS)
    print(f"{len(roads):,} road edges")

    geo = street_geometry_pairs(cand, pts, roads)
    names = crossed_name_pairs(cand, pts)
    signals: dict = {}
    diffs: dict = {}
    for i, j, bd in geo:
        signals[(i, j)] = ["street-geometry"]
        diffs[(i, j)] = bd
    for i, j in names:
        signals.setdefault((i, j), []).append("crossed-names")
    print(f"nominated: {len(geo):,} street-geometry + {len(names):,} crossed-names "
          f"-> {len(signals):,} distinct pairs")

    stops = pd.read_csv(latest("stops_[0-9]*.csv"), low_memory=False, dtype=str)
    lookup = HeadingLookup(stops, *load_shapes())

    rows = []
    for (i, j), sigs in sorted(signals.items()):
        a, b = cand.iloc[i], cand.iloc[j]
        ha = lookup.headings(a.analysis_name, a.stop_id, pts.geometry.iloc[i])
        hb = lookup.headings(b.analysis_name, b.stop_id, pts.geometry.iloc[j])
        sep = float(pts.geometry.iloc[i].distance(pts.geometry.iloc[j]))
        rows.append({
            "cluster_id": a.cluster_id, "sep_m": round(sep, 1),
            "bearing_diff": diffs.get((i, j)),
            "signal": "+".join(sigs),
            "a_agency": a.analysis_name, "a_stop": a.stop_id, "a_name": a.stop_name,
            "b_agency": b.analysis_name, "b_stop": b.stop_id, "b_name": b.stop_name,
            "n_agencies": a.n_agencies,
            "a_headings": ";".join(str(h) for h in ha),
            "b_headings": ";".join(str(h) for h in hb),
            "verdict": classify(ha, hb),
        })
    res = pd.DataFrame(rows)
    res.to_csv(OUT, index=False)

    print(f"\n{len(res):,} adjudicated pairs -> {OUT}")
    if len(res):
        print(res["verdict"].value_counts().to_string())
        nc = res["verdict"].str.startswith(SPLIT_CONSTRAINT_PREFIXES).sum()
        print(f"{nc:,} pairs become cannot-link constraints "
              f"(re-run cluster_stops.py to apply)")


if __name__ == "__main__":
    main()
