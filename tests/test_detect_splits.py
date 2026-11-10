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


# ------------------------------------------------------------ shape_passes
def _one(passes):
    assert len(passes) == 1, passes
    assert passes[0][0] is not None
    return passes[0][0]


def test_shape_passes_cardinal_directions():
    north = LineString([(0, 0), (0, 100)])   # EPSG:3310-style meters
    assert math.isclose(_one(ds.shape_passes(north, Point(5, 50))), 0.0, abs_tol=1e-9)
    south = LineString([(0, 100), (0, 0)])
    assert math.isclose(_one(ds.shape_passes(south, Point(5, 50))), 180.0, abs_tol=1e-9)
    east = LineString([(0, 0), (100, 0)])
    assert math.isclose(_one(ds.shape_passes(east, Point(50, 5))), 90.0, abs_tol=1e-9)


def test_shape_passes_guards():
    line = LineString([(0, 0), (0, 100)])
    assert ds.shape_passes(line, Point(500, 50)) == []         # shape misses the stop
    # terminal stop: chord clamps at the shape end, heading survives
    assert math.isclose(_one(ds.shape_passes(line, Point(0, 99))), 0.0, abs_tol=1e-9)
    assert math.isclose(_one(ds.shape_passes(line, Point(0, 1))), 0.0, abs_tol=1e-9)


def test_shape_passes_out_and_back_detected():
    # an out-and-back traverses the stop twice; plain project() sees only the
    # first visit. Both passes are reported (nearest first) so the lookup can
    # flag the attribution as AMBIGUOUS — such a stop never drives a constraint
    line = LineString([(-100, 0), (100, 0), (-100, 0)])
    passes = ds.shape_passes(line, Point(0, 5))
    assert len(passes) == 2
    hs = sorted(p[0] for p in passes)
    assert math.isclose(hs[0], 90.0, abs_tol=1e-9)
    assert math.isclose(hs[1], 270.0, abs_tol=1e-9)
    # symmetric turnaround: one merged pass, degenerate chord -> bearing None
    tp = ds.shape_passes(line, Point(100, 0))
    assert len(tp) == 1 and tp[0][0] is None


def test_shape_passes_corner_turn_is_one_pass():
    # a route turning at the stop's corner stays inside the neighborhood the
    # whole way through — ONE pass reading the approach direction, not a
    # phantom second visit on the cross street
    turn = LineString([(0, -100), (0, 0), (100, 0)])
    passes = ds.shape_passes(turn, Point(3, -15))
    assert len(passes) == 1
    assert math.isclose(passes[0][0], 0.0, abs_tol=1e-9)   # northbound approach


def test_lookup_far_return_leg_keeps_full_coverage():
    from types import SimpleNamespace
    # the shape leaves the stop's street and returns on ANOTHER street 20 m
    # away — that is the normal corner situation (the cross street's leg),
    # NOT out-and-back ambiguity; the stop keeps its own street's heading
    detour = LineString([(0, -100), (0, 100), (50, 100), (50, 20), (-100, 20)])
    lk = ds.HeadingLookup({}, {("u", "r1", 0): detour})
    hs, full = lk.headings(SimpleNamespace(
        base64_url="u", stop_id="s1", route_dirs="r1|0", route_ids=""), Point(3, 0))
    assert hs == [0.0] and full


def test_lookup_near_second_pass_is_ambiguous():
    from types import SimpleNamespace
    # out-and-back on the stop's own street: both passes within a roadway
    # width -> verdict still reads the closest pass, but coverage is partial
    # so the verdict can never become a constraint
    line = LineString([(-100, 0), (100, 0), (-100, 0)])
    lk = ds.HeadingLookup({}, {("u", "r1", 0): line})
    hs, full = lk.headings(SimpleNamespace(
        base64_url="u", stop_id="s1", route_dirs="r1|0", route_ids=""), Point(0, 5))
    assert hs == [90.0]
    assert not full


def test_heading_lookup_coverage():
    from types import SimpleNamespace
    north = LineString([(0, 0), (0, 100)])
    pt = Point(2, 50)
    # r2 serves the stop but has no shape -> headings exist, coverage partial
    lk = ds.HeadingLookup({}, {("u", "r1", 0): north})
    hs, full = lk.headings(SimpleNamespace(
        base64_url="u", stop_id="s1", route_dirs="r1|0;r2|0", route_ids=""), pt)
    assert hs == [0.0] and not full
    # both routes shaped -> full
    lk2 = ds.HeadingLookup({}, {("u", "r1", 0): north, ("u", "r2", 0): north})
    _, full2 = lk2.headings(SimpleNamespace(
        base64_url="u", stop_id="s1", route_dirs="r1|0;r2|0", route_ids=""), pt)
    assert full2
    # per-stop shapes are complete by construction
    lk3 = ds.HeadingLookup({("u", "s1"): [north]}, {})
    hs3, full3 = lk3.headings(SimpleNamespace(
        base64_url="u", stop_id="s1", route_dirs="", route_ids=""), pt)
    assert hs3 == [0.0] and full3


def test_carry_forward_keeps_separated_pairs_only():
    prev = pd.DataFrame([
        {"a_url": "u1", "a_stop": "1", "b_url": "u2", "b_stop": "2"},   # separated
        {"a_url": "u1", "a_stop": "3", "b_url": "u2", "b_stop": "4"},   # re-nominated
        {"a_url": "u1", "a_stop": "9", "b_url": "gone", "b_stop": "9"},  # stop vanished
    ])
    nominated = {frozenset({("u1", "3"), ("u2", "4")})}
    known = {("u1", "1"), ("u2", "2"), ("u1", "3"), ("u2", "4"), ("u1", "9")}
    out = ds.carry_forward(prev, nominated, known)
    assert len(out) == 1 and out.iloc[0]["a_stop"] == "1"
    assert ds.carry_forward(None, set(), set()).empty
    assert ds.carry_forward(pd.DataFrame(), set(), set()).empty


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
