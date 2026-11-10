"""Grouping regressions; run with `uv run python -m unittest discover -s tests`."""

import itertools
import math
import unittest
from unittest.mock import patch

import geopandas as gpd
import numpy as np
import pandas as pd
from shapely.geometry import LineString

from scripts.cluster_stops import (
    EARTH_R,
    assert_no_cannot_links,
    inject_split_pairs,
    load_split_pairs,
    merge_coincident,
    osm_features_and_road_split,
    pairwise_constraints,
    partition_compatible,
)


def group(xs, dirs=None, feeds=None, roads=()):
    """Equatorial coordinates give exact, simple haversine meter offsets."""
    n = len(xs)
    lats = np.zeros(n)
    lons = np.degrees(np.asarray(xs) / EARTH_R)
    positions = list(zip(lats, lons))
    cannot, distances = pairwise_constraints(
        dirs if dirs is not None else [""] * n,
        feeds if feeds is not None else ["feed-a"] * n,
        lats, lons, [(x, 0) for x in xs], roads)
    labels = partition_compatible(cannot, distances, positions)
    return labels, cannot, positions


class GroupingTests(unittest.TestCase):
    def test_same_feed_nb_sb_splits(self):
        labels, cannot, _ = group([0, 20], ["1|0", "1|1"])
        self.assertTrue(cannot[0, 1])
        self.assertNotEqual(*labels)

    def test_different_feeds_same_numbered_routes_share_corner(self):
        labels, cannot, _ = group([0, 20], ["1|0", "1|1"], ["a", "b"])
        self.assertFalse(cannot.any())
        self.assertEqual(*labels)

    def test_different_feeds_still_split_across_road(self):
        road = LineString([(10, -10), (10, 10)])
        labels, cannot, _ = group([0, 20], ["1|0", "1|1"], ["a", "b"], [road])
        self.assertTrue(cannot[0, 1])
        self.assertNotEqual(*labels)

    def test_unknown_feed_does_not_establish_shared_route(self):
        for feeds in ([None, None], [np.nan, np.nan], ["", ""]):
            labels, cannot, _ = group([0, 20], ["1|0", "1|1"], feeds)
            self.assertFalse(cannot.any())
            self.assertEqual(*labels)

    def test_direction_minimum_separation_and_unknown_direction(self):
        for xs, dirs in (([0, 4], ["R|0", "R|1"]),
                         ([0, 20], ["R|-1", "R|0"])):
            labels, cannot, _ = group(xs, dirs)
            self.assertFalse(cannot.any())
            self.assertEqual(*labels)

    def test_road_chain_cannot_reconnect_outer_pair(self):
        roads = [LineString([(0, -10), (0, 0)]),
                 LineString([(0, 0), (0, 10)])]
        for xs in itertools.permutations([-5, 0, 5]):
            labels, cannot, _ = group(xs, roads=roads)
            left, right = xs.index(-5), xs.index(5)
            self.assertTrue(cannot[left, right])
            self.assertNotEqual(labels[left], labels[right])
            self.assertEqual(len(set(labels)), 2)

    def test_direction_chain_does_not_rejoin_distant_outer_stops(self):
        labels, cannot, _ = group([0, 25, 50], ["R|0", "R|1", "R|0"])
        self.assertTrue(cannot[0, 1] and cannot[1, 2])
        self.assertFalse(cannot[0, 2])
        self.assertEqual(len(set(labels)), 3)

    def test_compatible_chain_is_not_oversplit(self):
        labels, cannot, _ = group([0, 25, 50])
        self.assertFalse(cannot.any())
        self.assertEqual(len(set(labels)), 1)

    def test_conflict_checked_against_every_member(self):
        # The closest pair is compatible; the third stop conflicts with only
        # one of its members, despite sharing an allowed nearby edge.
        labels, cannot, _ = group([0, 6, 15], ["R|0", "", "R|1"])
        self.assertTrue(cannot[0, 2])
        self.assertEqual(labels[0], labels[1])
        self.assertNotEqual(labels[0], labels[2])

    def test_combined_signals_apply_in_one_partition(self):
        labels, cannot, _ = group(
            [0, 8, 16], ["R|0", "R|1", ""],
            roads=[LineString([(12, -10), (12, 10)])])
        self.assertTrue(cannot[0, 1])  # direction only
        self.assertTrue(cannot[1, 2])  # road only
        self.assertEqual(len(set(labels)), 3)

    def test_node_split_and_junction_roads_separate(self):
        roads = [LineString([(0, -10), (0, 0)]),
                 LineString([(0, 0), (0, 10)])]
        for lines in (roads, roads + [LineString([(0, 0), (10, 10)])]):
            labels, cannot, _ = group([-5, 5], roads=lines)
            self.assertTrue(cannot[0, 1])
            self.assertNotEqual(*labels)

    def test_stop_endpoint_touch_and_collinear_overlap_do_not_split(self):
        for road in (LineString([(0, -10), (0, 10)]),
                     LineString([(-10, 0), (10, 0)])):
            labels, cannot, _ = group([0, 5], roads=[road])
            self.assertFalse(cannot.any())
            self.assertEqual(*labels)

    def test_coincident_stops_remain_atomic_despite_other_conflicts(self):
        labels, cannot, positions = group([0, 0, 10], ["R|0", "R|1", "R|0"])
        self.assertFalse(cannot[0, 1])
        self.assertTrue(cannot[1, 2])
        self.assertEqual(labels[0], labels[1])
        self.assertNotEqual(labels[0], labels[2])
        df = pd.DataFrame(positions, columns=["stop_lat", "stop_lon"])
        df["cluster_id"] = labels
        result = merge_coincident(df)
        pairs = list(zip(*np.where(np.triu(cannot, 1))))
        assert_no_cannot_links(result, pairs)
        # A later accidental merge must fail loudly.
        result["cluster_id"] = 0
        with self.assertRaises(AssertionError):
            assert_no_cannot_links(result, pairs)

    def test_nearby_road_separation_not_undone_by_rounding(self):
        labels, _, positions = group([-0.01, 0.01], roads=[
            LineString([(0, -10), (0, 10)])])
        df = pd.DataFrame(positions, columns=["stop_lat", "stop_lon"])
        df["cluster_id"] = labels
        self.assertEqual(merge_coincident(df)["cluster_id"].nunique(), 2)

    def test_injected_split_pair_separates_otherwise_compatible_stops(self):
        # Different feeds, no shared route bits, no road between: today these
        # merge. A heading-verdict pair (detect_splits.py) must split them.
        n = 2
        lats, lons = np.zeros(n), np.degrees(np.asarray([0, 20]) / EARTH_R)
        cannot, distances = pairwise_constraints(
            ["", ""], ["feed-a", "feed-b"], lats, lons, [(0, 0), (20, 0)], ())
        self.assertFalse(cannot.any())
        keys = [("feed-a", "100"), ("feed-b", "200")]
        inject_split_pairs(cannot, distances, keys,
                           {frozenset({("feed-a", "100"), ("feed-b", "200")})})
        self.assertTrue(cannot[0, 1])
        labels = partition_compatible(cannot, distances, list(zip(lats, lons)))
        self.assertNotEqual(*labels)

    def test_injected_split_pair_respects_min_separation(self):
        # A stale/bad pair must never split near-coincident records (<= 5 m).
        n = 2
        lats, lons = np.zeros(n), np.degrees(np.asarray([0, 3]) / EARTH_R)
        cannot, distances = pairwise_constraints(
            ["", ""], ["feed-a", "feed-b"], lats, lons, [(0, 0), (3, 0)], ())
        keys = [("feed-a", "100"), ("feed-b", "200")]
        inject_split_pairs(cannot, distances, keys,
                           {frozenset({("feed-a", "100"), ("feed-b", "200")})})
        self.assertFalse(cannot.any())

    def test_load_split_pairs_keeps_only_constraint_verdicts(self):
        import tempfile
        rows = (
            "cluster_id,a_url,a_stop,b_url,b_stop,verdict\n"
            "1,X,1,Y,2,CONFIRM kitty (perpendicular)\n"
            "2,X,3,Y,4,across-street (antiparallel)\n"
            "3,X,5,Y,6,VETO (parallel: same street+direction)\n"
            "4,X,7,Y,8,mixed\n"
            "5,X,9,Y,10,no-shapes\n"
            "6,X,11,X,11,CONFIRM kitty (perpendicular)\n"  # self-pair dropped
        )
        with tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False) as f:
            f.write(rows)
        pairs = load_split_pairs(f.name)
        # across-street is REVIEW-ONLY (imagery audit: all "unsure") — only
        # CONFIRM rows load as constraints
        self.assertEqual(pairs, {frozenset({("X", "1"), ("Y", "2")})})
        self.assertEqual(load_split_pairs("/nonexistent/split_pairs.csv"), set())

    def test_load_split_pairs_requires_full_coverage(self):
        import tempfile
        rows = (
            "cluster_id,a_url,a_stop,b_url,b_stop,coverage,verdict\n"
            "1,X,1,Y,2,full,CONFIRM kitty (perpendicular)\n"
            "2,X,3,Y,4,partial,CONFIRM kitty (perpendicular)\n"
        )
        with tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False) as f:
            f.write(rows)
        self.assertEqual(load_split_pairs(f.name),
                         {frozenset({("X", "1"), ("Y", "2")})})

    def test_load_split_pairs_tolerates_empty_outputs(self):
        import tempfile
        header_only = "cluster_id,a_url,a_stop,b_url,b_stop,verdict\n"
        for content in (header_only, "", "\n"):
            with tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False) as f:
                f.write(content)
            self.assertEqual(load_split_pairs(f.name), set())

    def test_split_pair_keyed_by_feed_does_not_split_colliding_ids(self):
        # The same (agency, stop_id) labels exist in two feeds at two different
        # places (the City of Roseville case). A constraint keyed to one feed's
        # urls must split only that cluster, never the look-alike.
        base = math.degrees(20 / EARTH_R)
        df = pd.DataFrame({
            "stop_id": ["100", "200", "100", "200"],
            "cluster_id": ["0", "0", "1", "1"],
            "analysis_name": ["CityX", "CityY", "CityX", "CityY"],
            "stop_lat": [34.0, 34.0 + base, 35.0, 35.0 + base],
            "stop_lon": [-118.0, -118.0, -117.0, -117.0],
            "route_dirs": ["", "", "", ""],
            "base64_url": ["feed-a", "feed-b", "feed-c", "feed-d"],
        })
        roads = gpd.GeoDataFrame(geometry=[], crs="EPSG:4326")
        pairs = {frozenset({("feed-a", "100"), ("feed-b", "200")})}
        with patch("scripts.cluster_stops._read_roads", return_value=roads):
            result, forbidden = osm_features_and_road_split(df, split_pairs=pairs)
        ids = result.set_index(["base64_url", "stop_id"])["cluster_id"]
        self.assertNotEqual(ids[("feed-a", "100")], ids[("feed-b", "200")])
        self.assertEqual(ids[("feed-c", "100")], ids[("feed-d", "200")])
        self.assertEqual(len(forbidden), 1)

    def test_split_pairs_through_full_tile_pipeline(self):
        df = pd.DataFrame({
            "stop_id": ["a", "b"], "cluster_id": ["0", "0"],
            "analysis_name": ["AgencyA", "AgencyB"],
            "stop_lat": [34.0, 34.0 + math.degrees(20 / EARTH_R)],
            "stop_lon": [-118.0, -118.0], "route_dirs": ["", ""],
            "base64_url": ["feed-a", "feed-b"],
        })
        roads = gpd.GeoDataFrame(geometry=[], crs="EPSG:4326")
        pairs = {frozenset({("feed-a", "a"), ("feed-b", "b")})}
        with patch("scripts.cluster_stops._read_roads", return_value=roads):
            result, forbidden = osm_features_and_road_split(df, split_pairs=pairs)
        self.assertEqual(result["cluster_id"].nunique(), 2)
        self.assertEqual(len(forbidden), 1)
        assert_no_cannot_links(result, forbidden)

    def test_direction_split_without_road_data(self):
        df = pd.DataFrame({
            "stop_id": ["a", "b"], "cluster_id": ["0", "0"],
            "stop_lat": [34.0, 34.0 + math.degrees(20 / EARTH_R)],
            "stop_lon": [-118.0, -118.0], "route_dirs": ["1|0", "1|1"],
            "base64_url": ["same-feed", "same-feed"],
        })
        roads = gpd.GeoDataFrame(geometry=[], crs="EPSG:4326")
        with patch("scripts.cluster_stops._read_roads", return_value=roads):
            result, pairs = osm_features_and_road_split(df)
        self.assertEqual(result["cluster_id"].nunique(), 2)
        self.assertEqual(len(pairs), 1)
        assert_no_cannot_links(result, pairs)


if __name__ == "__main__":
    unittest.main()
