# cal-quay

The California Transit Stop Registry — Cal-ITP's working space for
[AB 1599](https://leginfo.legislature.ca.gov/faces/billNavClient.xhtml?bill_id=202520260AB1599)
(enrolled Aug 30, 2026), which requires Caltrans to publish a statewide registry giving every
physical transit stop one canonical identity and universal ID by **June 1, 2027** (Gov. Code
§14113). TDA-funded operators must then conform their stop names/locations to the registry and
use its identifiers by **Jan 1, 2028** (Pub. Util. Code §99150.5).

## `scripts/`

Two tools for sizing the matching problem — the stops where multiple agencies each publish their
own entry for the same physical place. Run with [uv](https://docs.astral.sh/uv/): `uv sync` once,
then `uv run scripts/<name>.py`.

```bash
gcloud auth application-default login                    # cal-itp-data-infra access
uv sync                                                  # one-time: create the env

uv run scripts/pull_stops.py --dry-run                   # ~3 GB scan — check first
uv run scripts/pull_stops.py                             # pulls once, reprocesses locally after
uv run scripts/find_shared_stops.py
```

### `pull_stops.py`
The full list of current California GTFS stops, minus the obvious out-of-scope rows: the latest
month of *served* stops from `mart_gtfs_rollup.fct_monthly_scheduled_stops` (more complete on
feeds than `dim_stops_latest`, which silently drops feeds on its `_is_current` join), excluding
the Bay Area 511 regional aggregator's duplicate copies, Regional Precursor Feeds (an operator's
direct feed that 511/VCTC re-publishes — kept only when it's the operator's sole feed), rail-only
stations (by GTFS `route_type`), and exact same-stop duplicates published under two dataset
names. Two stages: the raw query result is saved to `stops_raw_<YYYY_MM>.parquet`, and the
exclusions run as a separate local step — re-running the script reprocesses the raw file without
touching BigQuery (`--refresh` forces a new pull).

### `find_shared_stops.py`
Groups the pulled stops by geohash cell (default precision 8, ~38 m × 19 m — "the same corner")
and keeps cells where **two or more agencies** each have a stop: the candidate shared stops the
registry needs to consolidate. Geohashes come precomputed from BigQuery's `ST_GEOHASH` in the
pull (precisions 7/8/9, matching `transit-amenity-atlas`), so `--precision` switches cell size
without re-pulling.

Both write to `data/` (gitignored): a `<name>_<date>.csv` plus `.gpkg` (QGIS + ArcGIS Pro) and
`.fgb` (QGIS-native; ArcGIS via Data Interoperability) point layers.

**Known limitations of the first pass:** a single geohash cell can hold two genuinely distinct
stops (opposite curbs), and shared stops that straddle a cell boundary are missed — notably,
a badly mispositioned stop (e.g. an agency's coordinate ~100 ft off the shared pole) often lands
in a *different* cell from its partners, so the worst position errors are underrepresented here.
Catching those is the position-accuracy analysis (next deliverable), which needs distance-based
matching rather than cell binning.
