# cal-quay

The California Transit Stop Registry — Cal-ITP's working space for
[AB 1599](https://leginfo.legislature.ca.gov/faces/billNavClient.xhtml?bill_id=202520260AB1599)
(signed Sept 18, 2026 — Chapter 269, Statutes of 2026), which requires Caltrans to publish a statewide registry giving every
physical transit stop one canonical identity and universal ID by **June 1, 2027** (Gov. Code
§14113). TDA-funded operators must then conform their stop names/locations to the registry and
use its identifiers by **Jan 1, 2028** (Pub. Util. Code §99150.5).

## Public dataset — statewide stop groupings

No warehouse access needed. Every California transit stop (Sept 2026 GTFS, 92,676 records)
with its grouping, multi-agency flag, and suggested primary stop per group:

```bash
python3 scripts/fetch_stops.py        # stdlib-only; saves to data/ (skips if present)
```

or fetch directly:
<https://storage.googleapis.com/calitp-publish-data-analysis/cal-quay/canonicalizer_stops_statewide.csv>
(18 MB CSV). Key columns: `cluster_id` (grouping), `n_agencies` (≥2 = shared stop),
`is_canonical` (suggested primary), `cluster_type`, `stop_lat`/`stop_lon`. Produced by
`scripts/cluster_stops.py`; method in `docs/grouping-methodology.md`. Refreshed with each
statewide run.

## `stop_fixing/`

Tools for sizing and working through the matching problem — the stops where multiple agencies
each publish their own entry for the same physical place.

### `count_stop_areas.py`

Sizes the multi-agency overlap: how many **stop areas actually need analysis** vs. how many are
single-agency stops that just need an ID minted. It pulls current stops live from BigQuery,
clusters them by ground distance, removes protected single-operator rail, the 511 regional
aggregator's duplicates, and major stations, then counts the multi-agency clusters that remain.

It builds on [`cal-itp/transit-amenity-atlas`](https://github.com/cal-itp/transit-amenity-atlas)
(the canonicalizer's `cluster.py` and `exclusions.py` are the single source of truth for the
clustering and exclusion rules).

```bash
gcloud auth application-default login                    # cal-itp-data-infra access
export CALQUAY_ATLAS_STOP_IDS=~/github/transit-amenity-atlas/stop_ids
python stop_fixing/count_stop_areas.py                   # live pull, ~1 min
python stop_fixing/count_stop_areas.py --cache data/stops_live_2026_06_03.csv  # re-use a pull
```

Outputs (written to `data/`, gitignored):
- `stops_live_<date>.csv` — the raw BigQuery pull (cache for re-runs)
- `stop_areas_to_analyze_<date>.csv` — the in-scope multi-agency clusters, the input to the
  review workflow

**Known limitation:** `analysis_name` is feed-level, so light rail bundled inside a mixed agency
(Muni Metro, VTA LRT, LA Metro Rail, SD Trolley, Sac RT) is not yet excluded — that needs GTFS
`route_type`.
