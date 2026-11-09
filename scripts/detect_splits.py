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
EXTRA_PASS_MAX_M = 15.0  # extra passes beyond the closest must be this close:
                         # the opposite travel lane of the stop's own street is
                         # within a roadway width; farther = the cross street
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
        # ~45% of shapes arrive as MultiLineString: BigQuery nodes
        # self-crossing routes into pieces (not path-ordered, so they can't
        # be re-stitched). shape_passes reads each part separately and the
        # lookup flags near revisits as ambiguity -> partial coverage.
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


def shape_passes(line, pt) -> list:
    """-> [(bearing-or-None, closest distance), ...], one entry per PASS of
    `line` near `pt`, nearest first. An out-and-back or loop shape traverses
    the stop's neighborhood more than once; the extra visits can't be
    attributed without stop-sequence data, so the caller treats them as
    AMBIGUITY, never as extra evidence.

    A pass = one maximal arc-length interval where the line stays within
    MAX_SHAPE_DIST_M of the stop; a second pass requires the line to LEAVE
    that neighborhood and return (so a route turning at the stop's corner is
    still one pass — its chord, like plain projection, reads the approach).
    Chords clamp at the shape ends so TERMINAL stops keep their final travel
    direction; a stop exactly at a symmetric turnaround yields a degenerate
    chord -> bearing None (conservative: no heading -> review, no constraint)."""
    if hasattr(line, "geoms"):   # multi-part shape: each part separately
        return sorted((p for part in line.geoms for p in shape_passes(part, pt)),
                      key=lambda x: x[1])
    xy = np.asarray(line.coords)
    if len(xy) < 2:
        return []
    p = np.array([pt.x, pt.y])
    a = xy[:-1]
    d = xy[1:] - a
    seg2 = (d ** 2).sum(axis=1)
    seglen = np.sqrt(seg2)
    cum = np.concatenate([[0.0], np.cumsum(seglen)])
    R = MAX_SHAPE_DIST_M

    # arc-length intervals where each segment sits inside the R-neighborhood
    # (|a + t*d - p| <= R solved per segment), then merged where contiguous
    intervals = []
    for k in range(len(seglen)):
        if seg2[k] == 0:
            continue
        ap = p - a[k]
        bq = float((ap * d[k]).sum())
        cq = float((ap ** 2).sum()) - R * R
        disc = bq * bq - seg2[k] * cq
        if disc < 0:
            continue
        sq = math.sqrt(disc)
        t0 = max(0.0, (bq - sq) / seg2[k])
        t1 = min(1.0, (bq + sq) / seg2[k])
        if t0 <= t1:
            intervals.append((cum[k] + t0 * seglen[k], cum[k] + t1 * seglen[k]))
    if not intervals:
        return []
    intervals.sort()
    merged = [list(intervals[0])]
    for s0, s1 in intervals[1:]:
        if s0 <= merged[-1][1] + 1e-6:
            merged[-1][1] = max(merged[-1][1], s1)
        else:
            merged.append([s0, s1])

    # closest approach + chord bearing per pass, nearest pass first
    t = np.clip(((p - a) * d).sum(axis=1) / np.where(seg2 == 0, 1.0, seg2), 0.0, 1.0)
    proj = a + t[:, None] * d
    dist = np.hypot(*(p - proj).T)
    s_c = cum[:-1] + t * seglen
    out = []
    for s0, s1 in merged:
        mask = (s_c >= s0 - 1e-6) & (s_c <= s1 + 1e-6) & (dist <= R)
        if not mask.any():
            continue
        dmin = float(dist[mask].min())
        s = float(s_c[mask][np.argmin(dist[mask])])
        pa = line.interpolate(max(0.0, s - CHORD_M))
        pb = line.interpolate(min(line.length, s + CHORD_M))
        brg = (math.degrees(math.atan2(pb.x - pa.x, pb.y - pa.y)) % 360.0
               if not pa.equals(pb) else None)
        out.append((brg, dmin))
    return sorted(out, key=lambda x: x[1])


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
    per-stop shapes when pulled, else route-level shapes via the stop's own
    route_dirs / route_ids. Keyed by FEED url, never by agency label — the
    same (agency, stop_id) can name two different physical stops in two feeds."""

    def __init__(self, stop_ix: dict, route_ix: dict):
        self.stop_ix, self.route_ix = stop_ix, route_ix
        self._cache: dict = {}

    def shapes_for(self, url, sid, route_dirs, route_ids) -> tuple:
        """-> (expected_route_ids | None, [(route_id, geom), ...]).

        expected=None means the per-stop pull supplied the shapes (complete by
        construction: it enumerated the stop's actual serving trips)."""
        shapes = self.stop_ix.get((url, str(sid)), [])
        if shapes:
            return None, [(None, g) for g in shapes]
        expected = set()
        rds = set()
        if isinstance(route_dirs, str) and route_dirs:
            for tok in route_dirs.split(";"):
                if "|" in tok:
                    rt, d = tok.rsplit("|", 1)
                    rds.add((rt, int(d)))
                    expected.add(rt)
        if isinstance(route_ids, str) and route_ids:
            for rt in route_ids.split(";"):
                if rt:
                    expected.add(rt)
                    if rt not in {r for r, _ in rds}:
                        rds |= {(rt, d) for d in (-1, 0, 1) if (url, rt, d) in self.route_ix}
        return expected, [((rt), self.route_ix[(url, rt, d)]) for rt, d in sorted(rds)
                          if (url, rt, d) in self.route_ix]

    def headings(self, row, pt3310) -> tuple:
        """`row`: a canonicalizer record (base64_url/stop_id/route_dirs/route_ids).

        -> (sorted headings, full_coverage). The CLOSEST pass of each shape
        supplies its heading (same semantics as plain projection). Coverage is
        FULL only when every route serving the stop contributed a heading AND
        no shape re-enters the stop's neighborhood within EXTRA_PASS_MAX_M —
        a verdict computed from a subset can invert (a missing parallel shape
        reads as perpendicular), and a tight-corner/out-and-back revisit can't
        be attributed without stop-sequence data, so neither may constrain."""
        key = (row.base64_url, str(row.stop_id))
        if key not in self._cache:
            expected, shapes = self.shapes_for(
                row.base64_url, row.stop_id,
                getattr(row, "route_dirs", None), getattr(row, "route_ids", None))
            hs: set = set()
            observed: set = set()
            ambiguous = False
            for rt, line in shapes:
                passes = shape_passes(line, pt3310)
                if not passes:
                    continue
                brg, _ = passes[0]
                if any(dm <= EXTRA_PASS_MAX_M for _, dm in passes[1:]):
                    ambiguous = True
                if brg is not None:
                    observed.add(rt)
                    hs.add(round(brg, 1))
            full = (bool(hs) and not ambiguous
                    and (expected is None or observed == expected))
            self._cache[key] = (sorted(hs), full)
        return self._cache[key]


def carry_forward(prev, nominated_keys: set, known_stops: set):
    """Previously adjudicated pairs to RE-adjudicate this run (anti-oscillation).

    Nomination only sees SAME-group pairs, so once a constraint separates its
    endpoints the pair stops being nominated; dropping it would let the next
    cluster run remerge the stops, which the run after would split again.
    Keep any prior pair not re-nominated whose stops both still exist —
    verdicts are refreshed against current shapes, never copied forward."""
    cols = {"a_url", "a_stop", "b_url", "b_stop"}
    if prev is None or prev.empty or not cols <= set(prev.columns):
        return pd.DataFrame(columns=sorted(cols))
    keep = []
    for r in prev.itertuples():
        pk = frozenset({(r.a_url, str(r.a_stop)), (r.b_url, str(r.b_stop))})
        if len(pk) == 2 and pk not in nominated_keys and pk <= known_stops:
            keep.append(r.Index)
    return prev.loc[keep]


# ---------------------------------------------------------------------- main
def main() -> None:
    canon = latest("canonicalizer_stops_*.csv")
    df = pd.read_csv(canon, low_memory=False, dtype={"stop_id": str, "stop_code": str})
    if "base64_url" not in df.columns:
        raise SystemExit(f"{canon.name} has no base64_url column — re-run "
                         "cluster_stops.py (feed-keyed identity) first.")
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

    lookup = HeadingLookup(*load_shapes())

    def adjudicate(a, pa, b, pb, signal, bearing_diff):
        ha, fa = lookup.headings(a, pa)
        hb, fb = lookup.headings(b, pb)
        return {
            "cluster_id": a.cluster_id, "sep_m": round(float(pa.distance(pb)), 1),
            "bearing_diff": bearing_diff, "signal": signal,
            "a_agency": a.analysis_name, "a_url": a.base64_url,
            "a_stop": a.stop_id, "a_name": a.stop_name,
            "b_agency": b.analysis_name, "b_url": b.base64_url,
            "b_stop": b.stop_id, "b_name": b.stop_name,
            "n_agencies": a.n_agencies,
            "a_headings": ";".join(str(h) for h in ha),
            "b_headings": ";".join(str(h) for h in hb),
            "coverage": "full" if fa and fb else "partial",
            "verdict": classify(ha, hb),
        }

    rows = [adjudicate(cand.iloc[i], pts.geometry.iloc[i],
                       cand.iloc[j], pts.geometry.iloc[j],
                       "+".join(sigs), diffs.get((i, j)))
            for (i, j), sigs in sorted(signals.items())]

    # anti-oscillation: pairs adjudicated before but no longer same-group
    # (their constraint worked) are re-adjudicated, never dropped
    prev = None
    if OUT.exists():
        try:
            prev = pd.read_csv(OUT, dtype=str)
        except pd.errors.EmptyDataError:
            prev = None
    nominated_keys = {
        frozenset({(cand.iloc[i].base64_url, str(cand.iloc[i].stop_id)),
                   (cand.iloc[j].base64_url, str(cand.iloc[j].stop_id))})
        for (i, j) in signals}
    dfix: dict = {}
    for k, r in enumerate(df.itertuples()):
        dfix.setdefault((r.base64_url, str(r.stop_id)), k)
    carried = carry_forward(prev, nominated_keys, set(dfix))
    if len(carried):
        pts_all = gpd.GeoSeries(
            gpd.points_from_xy(df.stop_lon, df.stop_lat),
            crs="EPSG:4326").to_crs(CA_ALBERS)
        for r in carried.itertuples():
            ka = dfix[(r.a_url, str(r.a_stop))]
            kb = dfix[(r.b_url, str(r.b_stop))]
            sig = r.signal if "carried" in str(r.signal) else f"{r.signal}+carried"
            rows.append(adjudicate(df.iloc[ka], pts_all.iloc[ka],
                                   df.iloc[kb], pts_all.iloc[kb],
                                   sig, r.bearing_diff))
        print(f"  carried forward {len(carried):,} previously adjudicated pairs "
              f"(separated by an earlier run; re-adjudicated, not copied)")

    # explicit schema: an empty result still writes headers, so a later
    # cluster_stops.py run loads an empty constraint set instead of crashing
    res = pd.DataFrame(rows, columns=[
        "cluster_id", "sep_m", "bearing_diff", "signal",
        "a_agency", "a_url", "a_stop", "a_name",
        "b_agency", "b_url", "b_stop", "b_name",
        "n_agencies", "a_headings", "b_headings", "coverage", "verdict"])
    res.to_csv(OUT, index=False)

    print(f"\n{len(res):,} adjudicated pairs -> {OUT}")
    if len(res):
        print(res["verdict"].value_counts().to_string())
        is_con = res["verdict"].str.startswith(SPLIT_CONSTRAINT_PREFIXES)
        full = res["coverage"] == "full"
        print(f"{int((is_con & full).sum()):,} pairs become cannot-link constraints; "
              f"{int((is_con & ~full).sum()):,} confirm-grade pairs held back as "
              f"partial-coverage (re-run cluster_stops.py to apply)")


if __name__ == "__main__":
    main()
