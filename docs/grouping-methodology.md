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
- **Geohashes** (levels 7/8/9) computed in SQL via `ST_GEOHASH`, carried as reference columns
  only — grouping is distance-based (step 2) and does not use them.
- **Direction data:** per-stop `{route_id|direction_id}` sets from `dim_stop_times ⋈ dim_trips`,
  reading each feed's **latest active version** (`fct_daily_schedule_feeds`, with the versions'
  exact `_feed_valid_from` days as partition filters), joined on `(base64_url, stop_id)` → the
  `route_dirs` column. (A recency window here is wrong: it skips stable feeds whose current
  version is months old, which capped coverage at ~56%.) This join is the dominant cost of the
  pull — ~87.5 GB scanned (up from ~25 GB), since it reaches the full-version `dim_stop_times`;
  restricting to the cohort's feed versions keeps it partition-pruned (unrestricted it is ~3×).
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
   - **Travel-heading verdicts (shape-truth, optional):** pairs adjudicated by
     `scripts/detect_splits.py` (§2b) whose route-shape headings confirm perpendicular
     (kitty-corner) or antiparallel (across-street) boarding join in as cannot-links whenever
     `data/split_pairs.csv` is present.
   - Coincident stops (same coordinate) are **never** cannot-linked.
3. **Partition:** nearest-first merging that refuses to join two partial groups if **any**
   cross-member pair is cannot-linked — avoiding the "a middle stop re-links a forbidden pair"
   transitivity trap of plain connected-components. A hard assertion verifies no final group
   violates a constraint (16,491 cannot-link pairs verified separated).
4. **Merge coincident:** groups sharing an exact position are merged (one physical stop).
- **Result:** ~82,474 groups; ~5,700 multi-agency.

### 2b. Split detection — travel headings — `scripts/detect_splits.py`
Finds grouped stops that should be **separate registry stops** (stops boarding on different
streets of one corner, or opposite sides of one street). Two nomination signals, one physical
adjudicator:
- **Nominate:** (A) *street geometry* — each stop's nearest road edge; street orientations
  60–120° apart with each stop clearly (≥ 5 m) nearer its own street; (B) *crossed names* —
  "A St & B St" vs "B St & A St" in one group. The signals are complementary (names catch
  corner stops whose points snap to the same street).
- **Adjudicate:** the **travel heading** at each stop from its serving routes' shapes
  (`scripts/pull_shapes.py`, active feed versions; project the stop, ±10 m chord, compass
  bearing — chords clamp at shape ends so terminal stops keep their final heading).
  `direction_id` is never compared across feeds; headings are physical. Verdicts: min pairwise
  difference < 30° → **VETO** (parallel — same street and direction, a false candidate);
  all differences 60–120° → **CONFIRM** kitty-corner; min > 150° → **across-street**
  (antiparallel); else **mixed**; missing shapes → **no-shapes**.
- Only CONFIRM rows **with full shape coverage** become constraints;
  VETO/mixed/no-shapes/**across-street** and partial-coverage rows stay in
  `data/split_pairs.csv` for the review queue (the imagery audit scored every across-street
  case "unsure" — antiparallel headings also arise from one mispositioned stop point — so
  that class is human-decided). Coverage is full only when every route serving the stop contributed a heading (a
  missing parallel shape would read as perpendicular) **and** no shape re-enters the stop's
  neighborhood within a roadway width (an out-and-back or tight-corner revisit can't be
  attributed to a boarding without stop-sequence data — the closest pass still supplies the
  verdict text, but the ambiguity blocks the constraint).
- Pairs adjudicated in an earlier run that are no longer same-group (their constraint worked)
  are **carried forward and re-adjudicated** on every run — otherwise the next clustering
  would remerge them and the system would oscillate.
- **Verdicts shape the proposal only** — every multi-agency grouping still passes human
  review with the verdict and headings as evidence.

### 3. Canonical pick (OSM-scored, provisional)
- Per stop (in EPSG:3310, OSM road geometry read **per spatial tile**): `dist_to_road_meters`,
  `in_roadway` (< 3 m).
- **Road data:** `data/roads_near_stops.fgb` — geometry-only OSM drive-network edges within 150 m
  of any stop (223 MB vs the 1.8 GB source networks; built by `scripts/trim_roads.py`; decisions
  verified identical). Auto-downloaded on first run from the public bucket:
  `https://storage.googleapis.com/calitp-publish-data-analysis/cal-quay/roads_near_stops.fgb`
  (© OpenStreetMap contributors, ODbL).
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
| Direction version selection | latest active feed version | `pull_stops.py` |
| Heading chord | ±10 m along the shape (clamped at ends) | `detect_splits.py` |
| Shape-passes-stop guard | 30 m | `detect_splits.py` |
| Revisit-ambiguity radius (extra passes) | 15 m (~a roadway width) | `detect_splits.py` |
| Parallel veto / perpendicular confirm / antiparallel | < 30° / all 60–120° / > 150° | `detect_splits.py` |

## Validation
Spot-checked against a set of 12 statewide shared-stop test cases (DDS, Oct 2026): **10/12
detected**. The 2 misses are a data-coverage gap (only one agency present in the pull) and one
close pair not grouped. A larger regression suite (the plan's 7 canonical cases plus a proposed
50–100 statewide cases) is the next validation step.

**Split detection (Oct 2026 cohort, run 2026-11-09):** 956 same-group pairs adjudicated
statewide → 698 CONFIRM / 143 VETO / 20 across-street / 60 mixed / 35 no-shapes. Coverage
gating plus the per-stop shapes rescue (`pull_shapes.py --per-stop`, joining through
dim_stop_times for pairs whose routes publish no shapes) leave **667 constraints**, with only
31 confirm-grade pairs held back as partial. A 54-case satellite-imagery audit ratified
**every decided CONFIRM (19/19) and VETO (17/17)** verdict; those human-verified pairs ship as
real-coordinate regression fixtures (`tests/fixtures/human_verified_pairs.csv`) and the suite
asserts the pipeline splits/keeps each one. Applying the constraints statewide: **81,222 final
groups** (91,809 stops, 5,338 multi-agency corners), all 667 pairs separated; a second
detect→cluster cycle is a fixed point (carried-forward pairs re-adjudicate identically).
Across-street verdicts were the hard class on imagery (all "unsure") — the class is
review-only (2026-11-09 decision).

## Current limitations
- Canonical picks are **automated, not human-reviewed** (the review bucket marks the uncertain ones).
- Direction data covers **~97%** of stops (latest active feed versions; the residue is feeds
  that publish no `direction_id`).
- When a feed's **month-end and today versions differ**, their `route|dir` values are unioned into
  one set per stop (to recover stops dropped in the newer version). If a route's `route_id` or
  `direction_id` encoding changed between the two versions, this could in principle manufacture a
  false direction split. Not observed on current data; the precise fix is to treat today's version
  as authoritative and fall back to month-end only for stops it no longer contains.
- **Rail excluded** (`issues/C17`); Sept 2026 snapshot.
- Dedup can still drop an agency's membership record, and registry IDs are not yet persistent across
  runs (next-tier items from the adversarial review).
