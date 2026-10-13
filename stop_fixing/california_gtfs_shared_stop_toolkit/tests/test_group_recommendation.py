"""Unit test for the reviewer-facing group recommendation step.

The synthetic end-to-end data mostly produces groups that already have a
recommendation, a TieBreakRec point, or agencies agreeing within 25 ft. This
test builds small made-up groups that reach every other rule, so each branch
of the precedence is checked directly.

Usage:  python tests/test_group_recommendation.py
"""
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from shared_stop_toolkit import workflow as wf


def row(group, key, agency, stop_id, **extra):
    base = {"shared_stop_group_id": group, "source_key": key, "agency": agency, "stop_id": stop_id,
            "stop_name": f"{agency} stop {stop_id}", "recommended_source_key": "", "recommendation_location_score": "",
            "recommendation_status": "Review Needed", "recommended_agency": "", "recommended_stop_id": "",
            "tiebreak_rec": "", "shared_stop_score": "60", "boarding_side": "", "road_dist_ft": None}
    base.update(extra)
    return base


rows = [
    # 1. existing recommendation (B was recommended)
    row("G1", "a1", "A", "1", recommended_source_key="b1", recommendation_location_score="80"),
    row("G1", "b1", "B", "2", recommended_source_key="b1", recommendation_location_score="80"),
    # 2. TieBreakRec point
    row("G2", "a2", "A", "3", tiebreak_rec="Y", road_dist_ft=20.0),
    row("G2", "b2", "B", "4", road_dist_ft=5.0),
    # 3. strongest group evidence (3 records; c3 is in the two strongest pairs)
    row("G3", "a3", "A", "5"), row("G3", "b3", "B", "6"), row("G3", "c3", "C", "7"),
    # 4. boarding side: only b4 is LIKELY
    row("G4", "a4", "A", "8", boarding_side="UNLIKELY"), row("G4", "b4", "B", "9", boarding_side="LIKELY"),
    # 5. boarding-position clues: a5 scores higher
    row("G5", "a5", "A", "10"), row("G5", "b5", "B", "11"),
    # 6. road distance: farthest from the centerline (same direction as TieBreakRec)
    row("G6", "a6", "A", "12", road_dist_ft=4.6), row("G6", "b6", "B", "13", road_dist_ft=11.49),
    # 7. agencies agree within 25 ft
    row("G7", "a7", "A", "14", recommendation_status="Agreement Within 25 ft"),
    row("G7", "b7", "B", "15", recommendation_status="Agreement Within 25 ft"),
    # 8. nothing distinguishes the points
    row("G8", "z8", "A", "16"), row("G8", "b8", "B", "17"),
]
pairs = pd.DataFrame([
    {"source_key_a": "a3", "source_key_b": "c3", "shared_stop_score": 90},
    {"source_key_a": "b3", "source_key_b": "c3", "shared_stop_score": 85},
    {"source_key_a": "a3", "source_key_b": "b3", "shared_stop_score": 40},
])
for g in ("G1", "G2", "G4", "G5", "G6", "G7", "G8"):
    keys = [r["source_key"] for r in rows if r["shared_stop_group_id"] == g]
    pairs.loc[len(pairs)] = {"source_key_a": keys[0], "source_key_b": keys[1], "shared_stop_score": 60}

out = wf._apply_group_review_recommendations(pd.DataFrame(rows), pairs, boarding_position_by_source={"a5": 3, "b5": 1})
selected = out[out["selected_point_flag"] == "Y"].set_index("shared_stop_group_id")
expected = {
    "G1": ("b1", wf.group_basis_existing),
    "G2": ("a2", wf.group_basis_tiebreak),
    "G3": ("c3", wf.group_basis_group_evidence),
    "G4": ("b4", wf.group_basis_boarding_side),
    "G5": ("a5", wf.group_basis_boarding_position),
    "G6": ("b6", wf.group_basis_road),
    "G7": ("a7", wf.group_basis_agreement),
    "G8": ("b8", wf.group_basis_arbitrary),
}
problems = []
for gid, (key, basis) in expected.items():
    got = (selected.at[gid, "source_key"], selected.at[gid, "group_recommendation_basis"])
    if got != (key, basis):
        problems.append(f"{gid}: expected {key} / {basis}, got {got[0]} / {got[1]}")
    members = out[out["shared_stop_group_id"] == gid]
    if members["group_recommended_stop"].nunique() != 1:
        problems.append(f"{gid}: Recommended Stop is not repeated on every member")

# A TieBreakRec point that is not selected must stop the run.
bad = pd.DataFrame([row("G9", "a9", "A", "1", tiebreak_rec="Y"), row("G9", "b9", "B", "2")])
original = wf._apply_group_review_recommendations
try:
    forced = original(bad, pd.DataFrame(columns=["source_key_a", "source_key_b", "shared_stop_score"]))
    if forced.set_index("source_key").at["a9", "selected_point_flag"] != "Y":
        problems.append("G9: TieBreakRec point was not selected")
except RuntimeError as e:
    problems.append(f"G9: unexpected error {e}")

print()
if problems:
    print("GROUP RECOMMENDATION TEST FAILED")
    for p in problems:
        print("  - " + p)
    sys.exit(1)
print(f"GROUP RECOMMENDATION TEST PASSED: all {len(expected)} selection rules pick the expected point and basis.")
