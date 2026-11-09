"""
Split-detection tests: heading classifier units + human-verified regression.

The regression fixture (tests/fixtures/human_verified_pairs.csv) is the
2026-10-31 imagery spot-check: real-coordinate same-group pairs whose shape-
heading verdict a human ratified on satellite imagery ("correct" only).
CONFIRM pairs must end up in different groups once their verdicts are injected
as cannot-links; VETO pairs (verdict correctly vetoed a split) must stay
together. Runs the REAL pipeline (dbscan -> constrained split -> coincident
merge) with roads mocked empty, so it needs no data/ downloads.

    uv run --with pytest python -m pytest tests/test_detect_splits.py -q
"""

import math
import sys
from pathlib import Path

import geopandas as gpd
import pandas as pd
from shapely.geometry import LineString, Point

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import cluster_stops as cs  # noqa: E402
import detect_splits as ds  # noqa: E402

FIXTURES = Path(__file__).resolve().parent / "fixtures"


# ------------------------------------------------------------- classifier
def test_classify_perpendicular_confirms():
    assert ds.classify([0.0], [90.0]) == ds.VERDICT_CONFIRM
    assert ds.classify([350.0], [80.0]) == ds.VERDICT_CONFIRM  # wraps past north


def test_classify_parallel_vetoes():
    assert ds.classify([0.0], [5.0]) == ds.VERDICT_VETO
    assert ds.classify([10.0], [350.0]) == ds.VERDICT_VETO     # 20 deg across north
    # one shared direction vetoes even when another pairing looks perpendicular
    assert ds.classify([0.0, 90.0], [0.0]) == ds.VERDICT_VETO


def test_classify_antiparallel_is_across_street():
    assert ds.classify([0.0], [180.0]) == ds.VERDICT_ACROSS
    assert ds.classify([10.0], [185.0]) == ds.VERDICT_ACROSS


def test_classify_mixed_and_missing():
    assert ds.classify([0.0], [45.0]) == "mixed"
    assert ds.classify([], [90.0]) == "no-shapes"
    assert ds.classify([0.0], []) == "no-shapes"


def test_classify_thresholds_are_exclusive():
    # exactly at the parallel bound -> not a veto; falls through to mixed
    assert ds.classify([0.0], [ds.PARALLEL_MAX_DEG]) == "mixed"
    assert ds.classify([0.0], [ds.PERP_LO]) == ds.VERDICT_CONFIRM
    assert ds.classify([0.0], [ds.PERP_HI]) == ds.VERDICT_CONFIRM


# ------------------------------------------------------------- heading_at
def test_heading_at_cardinal_directions():
    north = LineString([(0, 0), (0, 100)])   # EPSG:3310-style meters
    assert math.isclose(ds.heading_at(north, Point(5, 50)), 0.0, abs_tol=1e-9)
    south = LineString([(0, 100), (0, 0)])
    assert math.isclose(ds.heading_at(south, Point(5, 50)), 180.0, abs_tol=1e-9)
    east = LineString([(0, 0), (100, 0)])
    assert math.isclose(ds.heading_at(east, Point(50, 5)), 90.0, abs_tol=1e-9)


def test_heading_at_guards():
    line = LineString([(0, 0), (0, 100)])
    assert ds.heading_at(line, Point(500, 50)) is None         # shape misses the stop
    # terminal stop: chord clamps at the shape end, heading survives
    assert math.isclose(ds.heading_at(line, Point(0, 99)), 0.0, abs_tol=1e-9)
    assert math.isclose(ds.heading_at(line, Point(0, 1)), 0.0, abs_tol=1e-9)


# ------------------------------------------------------------- crossed names
def test_crossed_name_parsing():
    assert ds.name_parts("18th St & Castro St") == ("18th st", "castro st")
    assert ds.name_parts("Castro St & 18th St") == ("castro st", "18th st")
    assert ds.name_parts("Telegraph / Garfield") == ("telegraph", "garfield")
    assert ds.name_parts("Main St and 1st Ave") == ("main st", "1st ave")
    assert ds.name_parts("Union Station") is None
    assert ds.name_parts("A & B & C") is None
    assert ds.name_parts(None) is None
    a, b = ds.name_parts("A St & B St"), ds.name_parts("B St & A St")
    assert a == (b[1], b[0])


# ------------------------------------------- human-verified regression cases
def _load_fixture():
    fx = pd.read_csv(FIXTURES / "human_verified_pairs.csv",
                     dtype={"a_stop": str, "b_stop": str})
    assert len(fx) >= 30, "human-verified fixture lost rows"
    assert (fx["human"] == "correct").all()
    return fx


def test_fixture_integrity():
    fx = _load_fixture()
    n_confirm = fx["verdict"].str.startswith("CONFIRM").sum()
    n_veto = fx["verdict"].str.startswith("VETO").sum()
    assert n_confirm >= 15 and n_veto >= 15


def test_human_verified_pairs_regression(monkeypatch):
    fx = _load_fixture()
    monkeypatch.setattr(
        cs, "_read_roads",
        lambda bbox: gpd.GeoDataFrame(geometry=[], crs="EPSG:4326"))

    # one row per distinct stop, at its real coordinates
    stops = {}
    for _, r in fx.iterrows():
        for side in ("a", "b"):
            key = (r[f"{side}_agency"], r[f"{side}_stop"])
            stops.setdefault(key, (r[f"{side}_lat"], r[f"{side}_lon"]))
    df = pd.DataFrame([
        {"stop_id": sid, "analysis_name": ag, "base64_url": f"feed-{ag}",
         "stop_lat": lat, "stop_lon": lon, "route_dirs": ""}
        for (ag, sid), (lat, lon) in stops.items()])

    constrained = fx[fx["verdict"].str.startswith(cs.SPLIT_CONSTRAINT_PREFIXES)]
    pairs = {frozenset({(f"feed-{r.a_agency}", r.a_stop), (f"feed-{r.b_agency}", r.b_stop)})
             for r in constrained.itertuples()}

    df["_db"] = cs.dbscan_labels(df)
    df["cluster_id"] = df["_db"].astype(str)
    df, forbidden = cs.osm_features_and_road_split(df, split_pairs=pairs)
    df = cs.merge_coincident(df)
    cs.assert_no_cannot_links(df, forbidden)

    ids = df.set_index(["analysis_name", "stop_id"])["cluster_id"]
    in_constraint = {k for p in pairs for k in p}
    for r in fx.itertuples():
        ka, kb = (r.a_agency, r.a_stop), (r.b_agency, r.b_stop)
        if str(r.verdict).startswith(cs.SPLIT_CONSTRAINT_PREFIXES):
            assert ids[ka] != ids[kb], f"human-confirmed split regressed: {ka} | {kb}"
        elif (str(r.verdict).startswith("VETO") and float(r.sep_m) <= cs.EPS_M
              and ka not in in_constraint and kb not in in_constraint):
            assert ids[ka] == ids[kb], f"human-vetoed split re-split: {ka} | {kb}"
