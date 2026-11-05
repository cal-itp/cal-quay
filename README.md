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
