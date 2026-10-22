"""
Group statewide stops: distance cluster -> constrained direction/road split
-> OSM-scored canonical pick.

  1. DBSCAN by ground distance (28 m, haversine) — distance-based grouping.
  2. Pairwise constraints: same-feed stops serving a shared route in opposite
     directions (>5 m apart), or stops separated by a drive-network road, must
     be in different groups. Merge nearby groups only if ALL member pairs are
     compatible. Exact-coordinate duplicates always stay together.
  3. OSM scoring: dist-to-road + in_roadway per stop (EPSG:3310, statewide). The
     canonical pick demotes in-roadway stops, then prefers the most-served.

OSM road data, read per spatial tile: prefers data/roads_near_stops.fgb (geometry-
only edges within 150 m of any stop — build with scripts/trim_roads.py), falling
back to the full atlas norcal/socal drive networks (~1.8 GB). With neither present,
the trimmed file is auto-downloaded (~220 MB, once) from the public cal-itp bucket.

  uv run scripts/cluster_stops.py
  uv run scripts/cluster_stops.py --input data/stops_2026_09.csv
"""

import argparse
import math
import urllib.request
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import pyogrio
from shapely.geometry import LineString
from shapely.ops import linemerge, unary_union
from sklearn.cluster import DBSCAN

REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = REPO_ROOT / "data"
ATLAS_DATA = Path.home() / "github/transit-amenity-atlas/data"
ATLAS_FGBS = [ATLAS_DATA / "norcal_drive_network.fgb", ATLAS_DATA / "socal_drive_network.fgb"]
TRIMMED_ROADS = DATA_DIR / "roads_near_stops.fgb"   # scripts/trim_roads.py
ROADS_URL = ("https://storage.googleapis.com/calitp-publish-data-analysis"
             "/cal-quay/roads_near_stops.fgb")
DRIVE_FGBS = [TRIMMED_ROADS] if TRIMMED_ROADS.exists() else ATLAS_FGBS

EPS_M = 28.0
EARTH_R = 6_371_000.0
LARGE_SPAN_M = 60.0
LARGE_N = 12
CA_ALBERS = "EPSG:3310"       # statewide equal-distance projection (meters)
IN_ROADWAY_M = 3.0
MIN_SEP_M = 5.0               # minimum separation for a direction conflict
COINCIDENT_TOL_M = 1e-6       # numerical zero; never cannot-link coincident stops
TILE_DEG = 0.2                # ~22 km tiles for reading road geometry
PAD_DEG = 0.004               # ~440 m bbox pad so edge stops see nearby roads


def latest_stops() -> Path:
    hits = sorted(DATA_DIR.glob("stops_[0-9]*.csv"))
    if not hits:
        raise SystemExit("No data/stops_<YYYY_MM>.csv — run pull_stops.py first.")
    return hits[-1]


def dbscan_labels(df: pd.DataFrame) -> np.ndarray:
    pts = np.radians(df[["stop_lat", "stop_lon"]].to_numpy())
    db = DBSCAN(eps=EPS_M / EARTH_R, min_samples=1, metric="haversine",
                algorithm="ball_tree").fit(pts)
    return db.labels_


# ---- combined direction / road constraints ----
def rd_map(s) -> dict:
    d: dict = {}
    if not isinstance(s, str):
        return d
    for tok in s.split(";"):
        if "|" in tok:
            r, di = tok.rsplit("|", 1)
            if di != "-1":
                d.setdefault(r, set()).add(di)
    return d


def _conflict(a: dict, b: dict, feed_a, feed_b) -> bool:
    # Route IDs and direction IDs are feed-local. Unknown feeds cannot establish
    # a shared route either; agency labels are not a substitute for feed identity.
    if pd.isna(feed_a) or pd.isna(feed_b) or not feed_a or feed_a != feed_b:
        return False
    return any(a[r].isdisjoint(b[r]) for r in a.keys() & b.keys())


def _road_separates(seg: LineString, merged_roads) -> bool:
    """A point intersection inside the stop-to-stop segment separates the stops.

    Union/linemerge joins node-split roads before intersection. Inspecting the
    intersection also catches junctions that remain MultiLineString boundaries.
    Touches at either stop and collinear line overlaps are not crossings.
    """
    intersection = seg.intersection(merged_roads)

    def interior_point(geom):
        if geom.is_empty:
            return False
        if geom.geom_type == "Point":
            along = seg.project(geom)
            return COINCIDENT_TOL_M < along < seg.length - COINCIDENT_TOL_M
        if hasattr(geom, "geoms"):
            return any(interior_point(part) for part in geom.geoms)
        return False

    return interior_point(intersection)


def pairwise_constraints(route_dirs, feeds, lats, lons, pts_xy, road_lines):
    """Return a symmetric cannot-link matrix and haversine distances."""
    maps = [rd_map(x) for x in route_dirs]
    n = len(maps)
    cannot_link = np.zeros((n, n), dtype=bool)
    distances = np.zeros((n, n), dtype=float)
    merged_roads = unary_union(road_lines)
    if merged_roads.geom_type == "MultiLineString":
        merged_roads = linemerge(merged_roads)
    for i in range(n):
        for j in range(i + 1, n):
            distance = _haversine_m(lats[i], lons[i], lats[j], lons[j])
            distances[i, j] = distances[j, i] = distance
            if distance <= COINCIDENT_TOL_M:
                continue
            forbidden = (distance > MIN_SEP_M
                         and _conflict(maps[i], maps[j], feeds[i], feeds[j]))
            if not forbidden and not merged_roads.is_empty:
                forbidden = _road_separates(LineString([pts_xy[i], pts_xy[j]]),
                                            merged_roads)
            cannot_link[i, j] = cannot_link[j, i] = forbidden
    return cannot_link, distances


def partition_compatible(cannot_link, distances, positions) -> list:
    """Nearest-first merging, checking every cross-member constraint.

    Seed indivisible groups at exact coordinates so merge_coincident cannot
    later undo the constraints. Only propose links within the DBSCAN radius:
    after removing forbidden links, distant compatible stops should not jump
    across an incompatible stop to reunite. This retains local connectivity
    without the forbidden-pair transitivity of connected components.
    """
    groups: dict = {}
    for i, pos in enumerate(positions):
        groups.setdefault(tuple(pos), []).append(i)
    members = {k: v for k, v in enumerate(groups.values())}
    owner = {i: k for k, group in members.items() for i in group}
    n = len(positions)
    edges = sorted((distances[i, j], i, j)
                   for i in range(n) for j in range(i + 1, n)
                   if distances[i, j] <= EPS_M and not cannot_link[i, j])
    for _, i, j in edges:
        a, b = owner[i], owner[j]
        if a == b or cannot_link[np.ix_(members[a], members[b])].any():
            continue
        for k in members[b]:
            owner[k] = a
        members[a].extend(members.pop(b))
    labels = {}
    colors = [labels.setdefault(owner[i], len(labels)) for i in range(n)]
    for group in members.values():
        if cannot_link[np.ix_(group, group)].any():
            raise AssertionError(f"Cannot-linked stops in subgroup: {group}")
    return colors


def assert_no_cannot_links(df: pd.DataFrame, forbidden_pairs) -> None:
    """Validate FINAL IDs, including any merges after the constrained split."""
    ids = df["cluster_id"]
    for i, j in forbidden_pairs:
        if ids.at[i] == ids.at[j]:
            raise AssertionError(
                f"Cannot-linked rows {i} and {j} in final group {ids.at[i]}")


def ensure_roads() -> None:
    """Resolve road sources; download the trimmed statewide file if none exist.

    No-op when data/roads_near_stops.fgb (or the full atlas pair) is already
    present — the ~220 MB download happens at most once.
    """
    global DRIVE_FGBS
    if TRIMMED_ROADS.exists():
        DRIVE_FGBS = [TRIMMED_ROADS]
        return
    if all(f.exists() for f in ATLAS_FGBS):
        DRIVE_FGBS = ATLAS_FGBS
        return
    print("  roads: no local road file; downloading roads_near_stops.fgb (~220 MB)")
    TRIMMED_ROADS.parent.mkdir(parents=True, exist_ok=True)
    part = TRIMMED_ROADS.with_suffix(".fgb.part")
    urllib.request.urlretrieve(ROADS_URL, part)
    n_edges = pyogrio.read_info(part)["features"]   # raises if truncated/corrupt
    part.rename(TRIMMED_ROADS)
    print(f"  roads: saved {TRIMMED_ROADS.name} ({n_edges:,} edges, "
          f"{TRIMMED_ROADS.stat().st_size / 1e6:.0f} MB)")
    DRIVE_FGBS = [TRIMMED_ROADS]


def _read_roads(bbox) -> gpd.GeoDataFrame:
    parts = []
    for f in DRIVE_FGBS:
        if not f.exists():
            continue
        try:
            r = gpd.read_file(f, bbox=tuple(bbox), engine="pyogrio")
        except Exception:
            continue
        if len(r):
            parts.append(r[["geometry"]])
    if not parts:
        return gpd.GeoDataFrame(geometry=[], crs="EPSG:4326")
    return pd.concat(parts, ignore_index=True).set_crs("EPSG:4326")


def osm_features_and_road_split(df: pd.DataFrame) -> tuple[pd.DataFrame, list]:
    """Add OSM features and jointly split direction/road conflicts per tile.

    Retain forbidden row pairs for validation after merge_coincident.
    """
    df["dist_to_road_meters"] = np.nan
    df["_road"] = 0
    forbidden_pairs = []

    size = df.groupby("cluster_id")["stop_id"].transform("size")
    cand = df[size > 1].copy()
    # assign every cluster to one tile (by centroid) so its members stay together
    cent = cand.groupby("cluster_id")[["stop_lat", "stop_lon"]].mean()
    cent["_tx"] = np.floor(cent["stop_lon"] / TILE_DEG).astype(int)
    cent["_ty"] = np.floor(cent["stop_lat"] / TILE_DEG).astype(int)
    cand = cand.join(cent[["_tx", "_ty"]], on="cluster_id")

    tiles = cand.groupby(["_tx", "_ty"])
    print(f"  OSM: {len(cand):,} stops in multi-stop clusters across {tiles.ngroups:,} tiles")
    done = 0
    for (tx, ty), grp in tiles:
        bbox = (tx * TILE_DEG - PAD_DEG, ty * TILE_DEG - PAD_DEG,
                (tx + 1) * TILE_DEG + PAD_DEG, (ty + 1) * TILE_DEG + PAD_DEG)
        roads = _read_roads(bbox)
        pts = gpd.GeoDataFrame(
            grp, geometry=gpd.points_from_xy(grp["stop_lon"], grp["stop_lat"]),
            crs="EPSG:4326").to_crs(CA_ALBERS)
        if not roads.empty:
            roads = roads.to_crs(CA_ALBERS)
            near = gpd.sjoin_nearest(pts[["geometry"]], roads[["geometry"]],
                                     how="left", distance_col="_d")
            near = near[~near.index.duplicated(keep="first")]
            df.loc[grp.index, "dist_to_road_meters"] = near["_d"]
        rsindex = roads.sindex if not roads.empty else None
        # Direction constraints still apply when no roads are available.
        for cid, cg in pts.groupby(grp["cluster_id"]):
            xy = [(p.x, p.y) for p in cg.geometry]
            minx = min(x for x, _ in xy) - 50; maxx = max(x for x, _ in xy) + 50
            miny = min(y for _, y in xy) - 50; maxy = max(y for _, y in xy) + 50
            idx = (list(rsindex.intersection((minx, miny, maxx, maxy)))
                   if rsindex is not None else [])
            lines = list(roads.geometry.iloc[idx]) if idx else []
            positions = list(zip(cg["stop_lat"], cg["stop_lon"]))
            cannot_link, distances = pairwise_constraints(
                cg["route_dirs"].tolist(), cg["base64_url"].tolist(),
                cg["stop_lat"].to_numpy(), cg["stop_lon"].to_numpy(), xy, lines)
            colors = partition_compatible(cannot_link, distances, positions)
            df.loc[cg.index, "_road"] = colors
            i, j = np.where(np.triu(cannot_link, k=1))
            forbidden_pairs.extend(zip(cg.index.to_numpy()[i], cg.index.to_numpy()[j]))
        done += 1
        if done % 50 == 0:
            print(f"    ...{done:,}/{tiles.ngroups:,} tiles")

    df["in_roadway"] = df["dist_to_road_meters"].fillna(np.inf) < IN_ROADWAY_M
    df["cluster_id"] = df["cluster_id"] + "_r" + df["_road"].astype(str)
    return df, forbidden_pairs


# ---- metadata / scoring ----
def _haversine_m(lat1, lon1, lat2, lon2) -> float:
    p = math.pi / 180
    a = (math.sin((lat2 - lat1) * p / 2) ** 2
         + math.cos(lat1 * p) * math.cos(lat2 * p) * math.sin((lon2 - lon1) * p / 2) ** 2)
    return 2 * EARTH_R * math.asin(math.sqrt(a))


def span_m(sub: pd.DataFrame) -> float:
    la, lo = sub["stop_lat"].to_numpy(), sub["stop_lon"].to_numpy()
    if len(la) < 2:
        return 0.0
    if len(la) > 40:
        return _haversine_m(la.min(), lo.min(), la.max(), lo.max())
    return max(_haversine_m(la[i], lo[i], la[j], lo[j])
               for i in range(len(la)) for j in range(i + 1, len(la)))


def classify(size: int, span: float, n_ag: int) -> str:
    if span >= LARGE_SPAN_M or size >= LARGE_N:
        return "AMBIGUOUS_LARGE"
    return "MULTI_FEED_CORNER" if n_ag >= 2 else "SINGLE_FEED"


def merge_coincident(df: pd.DataFrame) -> pd.DataFrame:
    """Merge any groups that share an exact stop position. Two stops at the same
    coordinate are one physical stop, so they must be one group — but a split can
    color them differently via conflicts with a third, distant stop."""
    parent: dict = {}

    def find(x):
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    # Exact positions only: rounding can merge genuinely separated stops on
    # opposite sides of a road. The constrained partition already seeds these
    # exact-coordinate groups before any other merges.
    tmp = df[["stop_lat", "stop_lon", "cluster_id"]]
    n0 = df["cluster_id"].nunique()
    for _, grp in tmp.groupby(["stop_lat", "stop_lon"]):
        u = grp["cluster_id"].unique()
        for c in u[1:]:
            parent[find(c)] = find(u[0])
    df["cluster_id"] = [find(c) for c in df["cluster_id"]]
    print(f"  merged coincident positions -> {df['cluster_id'].nunique():,} groups (was {n0:,})")
    return df


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--input", type=Path)
    ap.add_argument("--output", type=Path, default=DATA_DIR / "canonicalizer_stops_statewide.csv")
    args = ap.parse_args()

    ensure_roads()
    src = args.input or latest_stops()
    df = pd.read_csv(src, dtype={"stop_id": str, "stop_code": str,
                                 "route_dirs": str, "route_ids": str,
                                 "base64_url": str, "parent_station": str}, low_memory=False)
    df["stop_lat"] = pd.to_numeric(df["stop_lat"], errors="coerce")
    df["stop_lon"] = pd.to_numeric(df["stop_lon"], errors="coerce")
    df = df.dropna(subset=["stop_lat", "stop_lon"]).reset_index(drop=True)
    print(f"{len(df):,} stops from {src.name}")

    df["_db"] = dbscan_labels(df)
    print(f"  {df['_db'].nunique():,} distance clusters (DBSCAN {EPS_M:.0f} m)")

    df["cluster_id"] = df["_db"].astype(str)

    before = df["cluster_id"].nunique()
    df, forbidden_pairs = osm_features_and_road_split(df)
    rsplit = df["cluster_id"].nunique() - before
    print(f"  combined direction/road split added {rsplit:,} groups "
          f"-> {df['cluster_id'].nunique():,} final groups")

    df = merge_coincident(df)
    assert_no_cannot_links(df, forbidden_pairs)
    print(f"  verified {len(forbidden_pairs):,} cannot-link pairs across final groups")

    g = df.groupby("cluster_id")
    df["cluster_size"] = g["stop_id"].transform("size")
    df["n_agencies"] = g["analysis_name"].transform("nunique")
    span = g.apply(span_m, include_groups=False)
    df["cluster_span_meters"] = df["cluster_id"].map(span).round(1)
    df["cluster_type"] = [classify(s, sp, n) for s, sp, n in
                          zip(df["cluster_size"], df["cluster_span_meters"], df["n_agencies"])]

    # score: demote in-roadway hard, then prefer the most-served stop
    arr = pd.to_numeric(df.get("total_stop_arrivals"), errors="coerce").fillna(0)
    df["score"] = (-10.0 * df["in_roadway"].astype(float)
                   + arr / (arr.max() + 1.0)).round(4)
    df["is_canonical"] = False
    df.loc[df["score"].groupby(df["cluster_id"]).idxmax(), "is_canonical"] = True
    df["canonicalization_method"] = np.where(df["cluster_size"] == 1, "TRIVIAL", "OSM_HEURISTIC")
    df["confidence"] = np.nan

    cols = ["analysis_name", "feed_name", "stop_id", "stop_code", "stop_name",
            "stop_lat", "stop_lon", "route_dirs", "route_ids", "served_in_month",
            "cluster_id", "cluster_size", "cluster_span_meters", "cluster_type",
            "n_agencies", "dist_to_road_meters", "in_roadway", "score", "confidence",
            "is_canonical", "canonicalization_method", "location_type", "parent_station"]
    df[[c for c in cols if c in df.columns]].to_csv(args.output, index=False)

    corners = df[(df["n_agencies"] >= 2) & (df["cluster_type"] == "MULTI_FEED_CORNER")]
    print(f"  in-roadway stops: {df['in_roadway'].sum():,} | "
          f"multi-agency corners: {corners['cluster_id'].nunique():,}")
    print(f"  CSV -> {args.output}")


if __name__ == "__main__":
    main()
