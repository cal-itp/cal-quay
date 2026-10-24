"""Fetch the public statewide stop-groupings dataset — no warehouse access needed.

Downloads canonicalizer_stops_statewide.csv from the public cal-itp bucket into
data/ (skipped if already present): every California transit stop (Sept 2026 GTFS,
92,676 records) with its grouping (`cluster_id`), multi-agency flag, and the
suggested primary stop per group (`is_canonical`). Produced by
scripts/cluster_stops.py; method in docs/grouping-methodology.md.

Standard library only — runs with bare python3, no environment setup:

  python3 scripts/fetch_stops.py

Then use it with anything that reads CSV, e.g.:

  import pandas as pd
  df = pd.read_csv("data/canonicalizer_stops_statewide.csv")
  shared = df[df["n_agencies"] >= 2]
"""

import csv
import urllib.request
from pathlib import Path

URL = ("https://storage.googleapis.com/calitp-publish-data-analysis"
       "/cal-quay/canonicalizer_stops_statewide.csv")
DEST = Path(__file__).resolve().parent.parent / "data" / "canonicalizer_stops_statewide.csv"


def main() -> None:
    if DEST.exists():
        print(f"already present: {DEST}")
    else:
        print(f"downloading {URL}")
        DEST.parent.mkdir(parents=True, exist_ok=True)
        part = DEST.with_suffix(".csv.part")
        urllib.request.urlretrieve(URL, part)
        part.rename(DEST)
        print(f"saved {DEST} ({DEST.stat().st_size / 1e6:.0f} MB)")
    with open(DEST, newline="", encoding="utf-8") as f:
        reader = csv.reader(f)
        header = next(reader)
        n = sum(1 for _ in reader)
    print(f"{n:,} stops; columns: {', '.join(header)}")


if __name__ == "__main__":
    main()
