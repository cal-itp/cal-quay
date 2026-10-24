"""
Regression test for the stop-grouping pipeline (~220 synthetic stops).

Builds a labeled fixture whose ground-truth grouping is known, then runs the REAL
grouping code (`cluster_stops.dbscan_labels` -> `osm_features_and_road_split` ->
`merge_coincident`) and asserts it recovers the exact partition. `_read_roads` is
monkeypatched with mock road geometry, so the test is deterministic and needs no
BigQuery or OSM data.

Covers every case the matching rules must get right:
  A. shared corner (2–5 agencies, same spot)                 -> one group
  B. inbound/outbound, same feed, opposite direction, ~20 m  -> two groups
  C. across a road, different agencies, road centerline between -> two groups
  D. coincident stops, opposite direction (same point)        -> one group
  E. transitivity trap (A–B–C with a road only between A & C)  -> {A,B}, {C}
  F. opposite corners ~50 m apart                             -> two groups (distance)
  G. isolated single-agency stops                             -> own group each

    uv run --with pytest python -m pytest tests/test_grouping_regression.py -q
"""

import math
import sys
from pathlib import Path

import geopandas as gpd
import pandas as pd
from shapely.geometry import LineString

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import cluster_stops as cs  # noqa: E402

LAT0, LON0 = 36.0, -119.0
DEG_PER_M_LAT = 1.0 / 111_320.0


class Fixture:
    """Accumulates stops (with ground-truth group) + mock roads, placing each
    'site' on a 0.02 deg grid (~2 km apart) so sites never interfere."""

    def __init__(self):
        self.stops: list[dict] = []
        self.roads: list[LineString] = []
        self._site = 0

    def new_site(self) -> tuple[float, float]:
        k = self._site
        self._site += 1
        return (LAT0 + (k // 12) * 0.02, LON0 + (k % 12) * 0.02)

    def _ll(self, site, east_m, north_m):
        lat = site[0] + north_m * DEG_PER_M_LAT
        lon = site[1] + east_m / (111_320.0 * math.cos(math.radians(site[0])))
        return lat, lon

    def add(self, site, east_m, north_m, feed, rdir, group):
        lat, lon = self._ll(site, east_m, north_m)
        self.stops.append({
            "stop_id": f"s{len(self.stops)}", "analysis_name": feed, "base64_url": feed,
            "stop_lat": lat, "stop_lon": lon, "route_dirs": rdir,
            "total_stop_arrivals": 100, "true_group": group,
        })

    def add_road(self, site, east_m, n0_m, n1_m):
        """Vertical road at a given easting, spanning a north range."""
        p0 = self._ll(site, east_m, n0_m)
        p1 = self._ll(site, east_m, n1_m)
        self.roads.append(LineString([(p0[1], p0[0]), (p1[1], p1[0])]))

    def frame(self):
        df = pd.DataFrame(self.stops)
        roads = gpd.GeoDataFrame(geometry=self.roads, crs="EPSG:4326")
        return df, roads


def build_fixture():
    f = Fixture()
    g = 0  # ground-truth group counter

    # A. shared corner: 2–5 different agencies clustered within ~12 m -> one group
    for k in range(25):
        site = f.new_site()
        for a in range(2 + k % 4):
            f.add(site, east_m=a * 3, north_m=(a % 2) * 2, feed=f"A{k}_ag{a}",
                  rdir=f"R{a}|0", group=g)
        g += 1

    # B. inbound/outbound: same feed, opposite direction, ~20 m apart -> two groups
    for k in range(25):
        site = f.new_site()
        feed = f"B{k}"
        f.add(site, -10, 0, feed, "R1|0", g); g += 1
        f.add(site, 10, 0, feed, "R1|1", g); g += 1

    # C. across a road: different agencies, road centerline between -> two groups
    for k in range(15):
        site = f.new_site()
        f.add(site, -10, 0, f"C{k}_w", "Rw|0", g); g += 1
        f.add(site, 10, 0, f"C{k}_e", "Re|0", g); g += 1
        f.add_road(site, east_m=0, n0_m=-30, n1_m=30)

    # D. coincident, opposite direction (same point) -> one group (never split)
    for k in range(8):
        site = f.new_site()
        feed = f"D{k}"
        f.add(site, 0, 0, feed, "R1|0", g)
        f.add(site, 0, 0, feed, "R1|1", g)
        g += 1

    # E. transitivity trap: A(-6) B(0, on road) C(6); road only truly between A & C
    for k in range(5):
        site = f.new_site()
        f.add(site, -6, 0, f"E{k}_a", "Ra|0", g)      # A  }
        f.add(site, 0, 0, f"E{k}_b", "Rb|0", g)       # B  } -> one group {A,B}
        g += 1
        f.add(site, 6, 0, f"E{k}_c", "Rc|0", g)       # C  -> separate group
        g += 1
        f.add_road(site, east_m=0, n0_m=-30, n1_m=30)

    # F. opposite corners ~50 m apart -> two groups (DBSCAN distance alone)
    for k in range(6):
        site = f.new_site()
        f.add(site, -25, 0, f"F{k}_w", "R|0", g); g += 1
        f.add(site, 25, 0, f"F{k}_e", "R|0", g); g += 1

    # G. isolated single-agency stops -> own group
    for k in range(15):
        site = f.new_site()
        f.add(site, 0, 0, f"G{k}", "R|0", g); g += 1

    return f.frame()


def _run_grouping(df, roads, monkeypatch):
    monkeypatch.setattr(cs, "_read_roads", lambda bbox: roads)
    df = df.reset_index(drop=True)
    df["_db"] = cs.dbscan_labels(df)
    df["cluster_id"] = df["_db"].astype(str)
    df, forbidden = cs.osm_features_and_road_split(df)
    df = cs.merge_coincident(df)
    cs.assert_no_cannot_links(df, forbidden)
    return df


def _partition(df, col):
    return {frozenset(grp.index) for _, grp in df.groupby(col)}


def test_grouping_recovers_ground_truth(monkeypatch):
    df, roads = build_fixture()
    df = _run_grouping(df, roads, monkeypatch)

    recovered = _partition(df, "cluster_id")
    truth = _partition(df, "true_group")

    if recovered != truth:
        # pairwise precision/recall for a readable failure
        idx = list(df.index)
        rc = df["cluster_id"].to_dict()
        tg = df["true_group"].to_dict()
        tp = fp = fn = 0
        for a in range(len(idx)):
            for b in range(a + 1, len(idx)):
                i, j = idx[a], idx[b]
                same_r, same_t = rc[i] == rc[j], tg[i] == tg[j]
                tp += same_r and same_t
                fp += same_r and not same_t
                fn += (not same_r) and same_t
        prec = tp / (tp + fp) if tp + fp else 1.0
        rec = tp / (tp + fn) if tp + fn else 1.0
        extra = recovered - truth
        missing = truth - recovered
        raise AssertionError(
            f"grouping != ground truth\n"
            f"  pairwise precision={prec:.3f} recall={rec:.3f} "
            f"(fp={fp} over-grouped, fn={fn} under-grouped)\n"
            f"  groups: recovered={len(recovered)} truth={len(truth)}\n"
            f"  {len(extra)} recovered groups not in truth; {len(missing)} truth groups not recovered"
        )


def test_fixture_size():
    df, _ = build_fixture()
    assert 200 <= len(df) <= 240, f"fixture is {len(df)} stops"
    assert df["true_group"].nunique() >= 140
