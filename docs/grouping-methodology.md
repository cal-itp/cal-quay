# Stop grouping & canonical-pick methodology

How the statewide groupings map (`data/statewide_groupings_map.html` + the `*_zones` / `*_stops`
GIS layers) is produced. Scope: **bus stops** (rail is deferred — see `issues/C17`).

**Goal.** Take ~94k California GTFS stops and group the ones that are the *same physical stop* so
each can get one registry ID, then pick a canonical "primary" per group — the hard part being the
few thousand locations where multiple agencies each publish their own record for one stop.

**Guiding principles**
- **Rider's-boarding view:** a stop is where a rider boards. Stops on different corners / different
  streets / opposite sides of a street are *different* stops.
- **Select, never average.** The canonical position is an existing agency point, never a synthesized
  centroid.
- **Automation narrows, humans decide.** The pipeline reduces ~94k stops to a few thousand
  candidate groups; genuinely ambiguous ones are flagged for human review, not force-resolved.

---

## Pipeline

### 1. Data foundation — `scripts/pull_stops.py`
- **Sources (Cal-ITP warehouse):** the latest *complete* monthly rollup
  (`mart_gtfs_rollup.fct_monthly_scheduled_stops`, Sept 2026 — served stops with
  `route_type_array` / `route_id_array` / arrivals) **unioned with** `dim_stops_latest` (unserved
  `stops.txt` entries, station/entrance records, feeds missing from the rollup).
- **Geohashes** (levels 7/8/9) computed in SQL via `ST_GEOHASH`.
- **Direction data:** per-stop `{route_id|direction_id}` sets from `dim_stop_times ⋈ dim_trips`
  over a 45-day feed-version window, joined on `(base64_url, stop_id)` → the `route_dirs` column.
- **Exclusions:** the Bay Area 511 regional aggregator; regional precursor (re-published) feeds;
  **rail-only stops** (modes ⊆ {0 light-rail, 1 subway, 2 rail}); exact cross-feed duplicates.
- **Result:** **94,313 stops / 195 agencies** with `base64_url`, `location_type`, `parent_station`,
  `route_types`, `route_ids`, `route_dirs`, arrivals.

### 2. Grouping — distance, then constrained splits — `scripts/cluster_stops.py`
1. **Proximity (DBSCAN, 28 m, haversine, min_samples=1):** proposes candidate groups by ground
   distance only. (28 m bounds individual links, chosen to merge a ~15 m coordinate offset but not
   a ~50 m opposite-corner separation.)
2. **Cannot-link constraints** inside each candidate, from two independent signals:
   - **Service direction (GTFS-truth):** two stops of the **same feed** serving a shared route in
     **opposite** `direction_id`s, > 5 m apart → must separate (inbound/outbound across a street).
     Feed-scoped because `route_id` is only unique *within* a feed.
   - **Road crossing (physical-truth):** the segment between two stops crosses a drive-network road
     centerline — tested against the **merged** road geometry so a road split into segments at a
     node still registers — → must separate (opposite sides).
   - Coincident stops (same coordinate) are **never** cannot-linked.
3. **Partition:** nearest-first merging that refuses to join two partial groups if **any**
   cross-member pair is cannot-linked — avoiding the "a middle stop re-links a forbidden pair"
   transitivity trap of plain connected-components. A hard assertion verifies no final group
   violates a constraint (16,491 cannot-link pairs verified separated).
4. **Merge coincident:** groups sharing an exact position are merged (one physical stop).
- **Result:** ~82,474 groups; ~5,700 multi-agency.

### 3. Canonical pick (OSM-scored, provisional)
- Per stop (in EPSG:3310, statewide OSM drive networks read **per spatial tile** so 1.8 GB of road
  geometry is never loaded at once): `dist_to_road_meters`, `in_roadway` (< 3 m).
- **Score** = `−10·in_roadway + normalized(service count)`; the highest-scoring **existing** stop
  wins. Demotes stops sitting in the roadway, then prefers the best-served.
- **Review bucket:** large/ambiguous groups, or groups with no clear pick, are flagged for human
  review (no primary forced) — ~20 statewide. These are where "unreasonably complex" situations go.

### 4. Match zones — `scripts/map_canonical_picks.py`
- A **Voronoi partition** over all stops: each group's zone = the union of its members' Voronoi
  cells, clipped to a max radius (~25 m). A painter's pass carves overlaps so zones are **strictly
  disjoint with shared borders** — *connected within a group, no overlaps between groups*.
- Verified: of 81,282 non-shared stops, **0 fall inside a shared-group zone** — so a future feed's
  point landing in a zone genuinely belongs to that registry stop.

### 5. Outputs — `scripts/map_canonical_picks.py`
- Self-contained Leaflet/satellite **HTML** inspection map.
- **`*_zones.{fgb,geojson}`** (group polygons) and **`*_stops.{fgb,geojson}`** (member points) for
  QGIS/ArcGIS.

---

## Key parameters
| Parameter | Value | Where |
|---|---|---|
| DBSCAN eps | 28 m (haversine) | `cluster_stops.py` |
| Min separation for a direction conflict | 5 m | `cluster_stops.py` |
| In-roadway threshold | 3 m from centerline | `cluster_stops.py` |
| Roadway score penalty | −10 | `cluster_stops.py` |
| Zone max radius | 25 m | `map_canonical_picks.py` |
| Projection (distance/OSM) | EPSG:3310 (CA Albers) | both |
| Direction feed-version window | 45 days | `pull_stops.py` |

## Validation
Spot-checked against a set of 12 statewide shared-stop test cases (DDS, Oct 2026): **10/12
detected**. The 2 misses are a data-coverage gap (only one agency present in the pull) and one
close pair not grouped. A larger regression suite (the plan's 7 canonical cases plus a proposed
50–100 statewide cases) is the next validation step.

## Current limitations
- Canonical picks are **automated, not human-reviewed** (the review bucket marks the uncertain ones).
- Direction data covers **~56%** of served stops (45-day window).
- **Rail excluded** (`issues/C17`); Sept 2026 snapshot.
- Dedup can still drop an agency's membership record, and registry IDs are not yet persistent across
  runs (next-tier items from the adversarial review).
