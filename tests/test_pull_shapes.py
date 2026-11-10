"""pull_shapes guards: SQL-building inputs and cohort month-end parsing."""

import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import pull_shapes as ps  # noqa: E402


def test_build_sql_rejects_empty_inputs():
    t = pd.DataFrame({"base64_url": ["u"], "route_id": ["r"]})
    active = pd.DataFrame({"feed_key": ["k"],
                           "_feed_valid_from": [pd.Timestamp("2026-09-01")]})
    with pytest.raises(AssertionError):
        ps.build_sql(t.iloc[0:0], active)      # no targets -> UNNEST([])
    with pytest.raises(AssertionError):
        ps.build_sql(t, active.iloc[0:0])      # no versions -> IN ()
    sql = ps.build_sql(t, active)
    assert "TIMESTAMP '2026-09-01'" in sql and "'k'" in sql


def test_cohort_month_end():
    assert str(ps.cohort_month_end(Path("stops_2026_09.csv"))) == "2026-09-30"
    assert str(ps.cohort_month_end(Path("stops_2026_12.csv"))) == "2026-12-31"
    assert str(ps.cohort_month_end(Path("stops_2024_02.csv"))) == "2024-02-29"
    with pytest.raises(SystemExit):
        ps.cohort_month_end(Path("stops.csv"))
