# AB 1599 Implementation Plan — California Transit Stop Registry

**DRAFT v0.1 · October 13, 2026 · for stakeholder review**

This document lays out the components of the AB 1599 implementation so stakeholders can see
what is planned, sign off, or push back ("we shouldn't do X — have you thought of Y?").
Nothing here is final except the statute. Items marked **⚑ DECISION** need an explicit call;
items marked *(recommended, not required)* go beyond the legal minimum and are deliberately
separable.


---

## 1. What the law requires — the floor

AB 1599 (Ahrens) is now law: **signed September 18, 2026 — Chapter 269, Statutes of 2026**
([bill status](https://leginfo.legislature.ca.gov/faces/billStatusClient.xhtml?bill_id=202520260AB1599);
chaptered text and floor analysis saved in [`sources/`](../sources/)).

| Requirement | Who | Statute | Deadline |
|---|---|---|---|
| Create the **California Transit Stop Registry**: a centralized, statewide dataset of standardized transit stop information, **with input from transit operators** | Caltrans | Gov. Code §14113(a) | **June 1, 2027** |
| Registry contains, per stop (*"but is not limited to"*): **name, location, seating available (y/n), sheltered (y/n), unique identifier** | Caltrans | §14113(b) | June 1, 2027 |
| Conform each stop's **name and location** to the registry | Transit operators (TDA §99210 definition) | PUC §99150.5(b)(1) | **January 1, 2028** |
| Use the registry's **unique identifier** "when publishing any dataset with stop information" — *"including, but not limited to"* GTFS, seating/shelter info, stop-level ridership, trip-planning formats, agency open datasets | Transit operators | PUC §99150.5(b)(2) | January 1, 2028 |
| **Report seating and shelter** per stop, **using the unique identifier** | Transit operators | PUC §99150.5(b)(3) | January 1, 2028 |

**Provisions that shape this plan** (easy to overlook, all statutory):

- **§14113(c): we may NOT require operators to change their own stop numbering.** Agencies
  keep their internal stop_ids forever; conformance means *carrying* the registry ID, never
  renumbering. This is the law, not a courtesy.
- **§14113(a)/(d): operator input is mandatory, twice.** The registry must be created "with
  input from transit operators," and the department must consider operator input on design,
  data sources, collection methods, and compliance guidance — explicitly "to limit adverse
  financial and human resources impacts." The focus group (§8.2) is how we discharge this.
- **§14113(a): "maximize the use of publicly available data."** Building from the existing
  GTFS warehouse isn't just pragmatic — it's the statutory direction.
- **§14113(a): update "at least once per year."** The legal cadence floor is annual; this
  plan's monthly publication (§4) comfortably exceeds it.
- **§14113(a): voluntary submissions are permitted** from agencies, operators, and state,
  regional, or local authorities. Permitted, not solicited — this plan treats unstructured
  submissions as a last resort, because matching messy external data to the registry is
  expensive (§4.3).
- **§14113(a): liability shield.** The department is not liable for information made
  available or not made available through the registry.
- **§99150.5(b)(3): amenity reporting is keyed by our ID.** Agencies literally cannot
  perform their reporting duty until they have their identifiers — the crosswalk (§7.1)
  is a statutory prerequisite and must land well before Jan 2028.

What the law does **not** require — everything below is our discretion:

- **No ID format.** §14113(b)(5) says only "a unique identifier … as established by the
  department." Format, structure, and assignment model are ours to design (§5).
- **No amenities beyond seating and shelter.** The Senate amendments deliberately narrowed
  "amenities" down to seating + sheltered — lighting, signage, ADA details are optional
  enrichment, not statutory.
- **No stop type, no version history, no API.** Useful, planned, but discretionary — and
  §14113(b)'s "but is not limited to" expressly leaves room to add them.
- **No portal or submission mechanism.** How agencies interact with the registry is ours to
  design — which is where most of this plan's value lives.
- **No dataset mechanics.** The law says the ID must appear in every published stop
  dataset, but not *how* — no field name, file format, or schema is specified. Defining
  those conventions ("put it in this field, named this, per dataset type") falls to our
  guidance (§7) — and if we don't define them, 200 operators will each invent their own
  way to comply.

**The timeline is short:** ~8 months to the registry deadline, ~15 months to operator
conformance. That drives the "floor first, quality second, ecosystem third" phasing in §3.

---

## 2. Where we are today — the data foundation

Working analysis lives in [cal-itp/cal-quay](https://github.com/cal-itp/cal-quay)
(see the [README](https://github.com/cal-itp/cal-quay/blob/main/README.md) for how to run it).

**An estimate of the statewide stop picture** (August 2026 complete month + September 2026 extract, via
[`scripts/pull_stops.py`](https://github.com/cal-itp/cal-quay/blob/main/scripts/pull_stops.py)):

| Figure | Count |
|---|---:|
| Stops served in the latest complete month | 113,998 |
| Additional current-extract-only stops (unserved entries, stations/entrances, newer feeds) | 24,937 |
| Excluded: Bay Area 511 regional-aggregator duplicates | −21,812 |
| Excluded: precursor-feed duplicates (operator feeds re-published by 511/VCTC) | −15,911 |
| Excluded: rail-only stops (handled separately; single-operator rail is authoritative) | −1,979 |
| Excluded: exact cross-feed duplicates | −4,415 |
| **Working universe of stops** | **95,413** |
| Distinct agency feed labels publishing these stops | 205 |

(205 counts *feed labels*, which approximate but don't equal organizations. The Cal-ITP
Airtable lists **258 organizations with at least one fixed-route service** (721 services,
646 currently operating) — the gap is orgs publishing under a shared or parent feed label,
or not publishing GTFS at all. 205 is the data denominator; 258 is the outreach
denominator used in §8.)

**The shared-stop problem:** there are roughly **3,000–6,000 places in California where
two or more agencies each publish their own record for the same physical stop** (the range
depends on the matching method; the current first pass finds 3,168 such corners, involving
6,851 stop records from 153 agencies). Everything else — **~96% of stops — is
single-agency**, where assigning an ID is trivial. The hard part is concentrated in a few
thousand locations, mostly in and around LA.

**Concrete failure modes the registry fixes** (worth using in every presentation):

- **Banning:** one physical stop, four agencies, four different names (from the Assembly
  Transportation Committee analysis of the bill).
- **Artesia (OCTA / LA Metro):** a badly mispositioned stop lands far enough from its
  partners that proximity grouping misses it entirely — the worst position errors are the
  hardest to find automatically. This motivates the position-accuracy workstream (§6).

---

## 3. The plan at a glance — three horizons

The work is organized into three
horizons. **Horizon 1 is the guaranteed floor** — if everything else slips, this alone
satisfies the statute. Horizons 2 and 3 are "do if we have time / do next," in priority
order. Each workstream section below (§4–§9) is organized the same way.

| | Horizon 1 — **Comply** (now–Jun 2027) | Horizon 2 — **Align** (now–Jan 2028) | Horizon 3 — **Improve** (2028+) |
|---|---|---|---|
| **Theme** | Publish a legally compliant registry v0 | Two-way loop: agencies adopt IDs, fix discrepancies | Registry as living infrastructure |
| **Registry (§4)** | Pin snapshot, assign IDs, publish dataset + crosswalk | Versioned updates; corrections flow in | Self-serve portal; API writes |
| **ID system (§5)** | Scheme decided (⚑ §5: stability, format, assignment); v0 IDs assigned | IDs appear in agency GTFS | New-stop IDs routine under the chosen scheme; merges/splits routine; voluntary `stop_code` convergence begins (§6.4) |
| **Analysis (§6)** | Review tool stood up; **human review of all multi-agency areas statewide — every group we can identify gets one registry ID** | Discrepancy + egregious-error reports out to agencies; verify fixes landed; re-sweep for groups the first pass missed | Name suggestions; parent_station and field recommendations; richer amenity QA |
| **ID delivery (§7)** | Crosswalk CSV published | API + done-for-you GTFS enrichment; agency hub | Hub becomes standard distribution for small agencies |
| **Customer success (§8)** | Small-agency **focus group** (5–8 agencies) proves the ask is doable | Tiered onboarding of all ~258 fixed-route organizations; CRM tracking | Steady-state support; annual re-certification |
| **Website (§9)** | GitHub Pages site: plan, minimum requirements, FAQ | Guidance docs; agency status pages *if* report cards are adopted (§6.5) | Public dashboards; change-log feeds |

**The critical path to June 1, 2027:**

| When | Milestone |
|---|---|
| Nov 2026 | Baseline snapshot pinned — the stop universe v0 is built from |
| Nov–Dec 2026 | **⚑ ID scheme decided** (§5) — blocks all ID assignment |
| Nov 2026 – Mar 2027 | Human review of shared-stop areas (high-confidence merges land first) |
| in parallel | Seating/shelter seeding (§4.3) |
| Apr 2027 | Registry v0 freeze — IDs assigned for the full working universe |
| May 2027 | Publish, one month ahead of the statutory deadline |

**Merge-coverage goal:** identify as many groups as possible and give each **one** registry
number in v0. That means working the full statewide multi-agency queue (~3,000–6,000 areas)
through human review before the freeze — at a keyboard-tool pace of even ~1–2 minutes per
area this is a few reviewer-weeks, not a blocker — and running both matching methods
(geohash cells *and* distance-based) so boundary-straddlers aren't silently left unmerged.

**Fallback rule for the deadline:** where an area genuinely can't be resolved in time
(disputed, ambiguous even on imagery, awaiting agency bay-labeling), we do **not**
guess-merge. That residual ships as separate IDs and merges later via retire-and-redirect.
A wrong merge is much more expensive than a late one — but the residual should be small,
not the default.

---

## 4. Workstream A — The registry itself

Two environments, in this order:

**A1. Internal staging registry (first).** Where data is loaded, validated, corrected, and
reviewed before anything is published. This is where the review tool (§6), override files,
and amenity collection land. Not public. (Kickoff consensus; this draft agrees.)

**A2. Published registry (the statutory artifact).** A versioned, dated, bulk-downloadable
dataset: one row per physical stop with ID, name, location, seating, shelter — plus the
crosswalk table (§7). Published on a predictable cadence (monthly, then faster).

Contents. Field names follow an existing standard wherever one exists — GTFS `stops.txt`
or the [transit-amenity-atlas schema](https://github.com/cal-itp/transit-amenity-atlas/blob/main/schema.md)
— and new names are invented only where no standard covers the concept. **The universal
identifier is proposed as an *additional* field: it never overwrites or replaces an
agency's `stop_id` or `stop_code`** — the agency's own identifiers stay untouched (which
is also the law, §14113(c)) and are carried in the crosswalk (§7.1).

| Field | Exact name (source) | Possible values | Status |
|---|---|---|---|
| Unique identifier | `stop_ca_universal_id` *(new — ⚑ name TBD, §7)* | format ⚑ undecided (§5) | **Required** — an extra column alongside, never instead of, the agency's IDs |
| Agency's own identifiers | `stop_id`, `stop_code` *(GTFS, the agency's values)* | unchanged, as published by each agency | **Untouchable** (§14113(c)) — live in the crosswalk, one row per agency reference |
| Canonical name | `stop_name` *(GTFS)* | free text | **Required** — seeded from the operating agency's name (§6.3) |
| Canonical location | `stop_lat`, `stop_lon` *(GTFS)* | WGS84 decimal degrees | **Required** — selected from agency-provided positions, not averaged (§6.1) |
| Seating | `bench` *(atlas)* | yes / no / unknown | **Required** — seeding strategy in §4.3 |
| Shelter | `shelter` *(atlas)* | yes / no / unknown | **Required** — seeding strategy in §4.3 |
| Operators serving the stop | `operator` *(atlas)* | semicolon-joined agency names | Derived from member feeds |
| Engineering coordinate | e.g. `eng_lat`, `eng_lon` *(new)* | WGS84, survey/design-grade — distinct from the customer-facing position | ***(internal-only)*** — for Traffic Ops, Construction, permitting (§4.4); not published, at least initially |
| Stop placement | e.g. `placement` *(new)* | near-side / far-side / midblock | *(recommended)* — standard traffic-engineering attribute (§4.4) |
| Station structure | `location_type`, `parent_station` *(GTFS)* | GTFS enums (stop/platform, station, entrance, node, boarding area); parent reference | *(recommended)* carried where agencies provide it; recommendations in §6.4 |
| Wheelchair access | `wheelchair_boarding` *(GTFS)* | unknown / accessible / not accessible | *(recommended)* carried where agencies provide it |
| Richer amenities | `lit`, `departures_board`, `bin`, `has_power` *(atlas)*; `osm_id` | yes/no; realtime / timetable / no; yes/no; yes/no; OSM id | *(recommended)* Horizon 3 enrichment — names and enums verbatim from the atlas so the two stay joinable |
| Match zone | *(new, geometry)* | polygon per stop, from shared-stop review | *(matching artifact)* — see §6.1; published as part of the repo |
| Version history | *(new)* | per change: timestamp, field, old → new, source | *(recommended but strongly held)* — required for the two-way loop in §6 to work |

**4.3 Seating & shelter (the sleeper requirement — with a statutory bootstrap).** The
registry must *contain* these fields by June 2027, but the statute's own filling mechanism
— operator reporting, keyed by the unique identifier (§99150.5(b)(3)) — isn't due until
Jan 2028. The law bridges the gap itself: §14113 defines the registry's seating/shelter
values *as reported under §99150.5* and directs the department to "maximize the use of
publicly available data." So v0 ships with best-available seeded values (GTFS, the
transit-amenity-atlas work, published asset inventories) plus provenance/confidence
flags, and "unknown" is a legitimate v0 value.

Filling the gaps then follows a strict preference order — each step is a fallback, not an
equal alternative:

1. **Preferred: the agency carries seating/shelter in its own GTFS**, in the fields we
   specify (§7). Their normal publishing cycle then satisfies the §99150.5(b)(3)
   reporting duty automatically, keyed by the registry ID, every time they update — no
   separate reporting channel to run.
2. **Backup: the pre-filled spreadsheet — or the hub map.** For agencies that attempted the GTFS route and
   couldn't (or can't yet), we share a sheet *we* generate — their stops, their stop_ids,
   the registry IDs, our current y/n values — and they only mark corrections. Because the
   sheet starts from the registry, returned rows match back mechanically. No fuzzy
   matching, no cleanup. Hub-hosted agencies get the same thing in map form (§7): click
   your stop, toggle seating/shelter — registry-keyed edits, zero reconciliation.
3. **Absolute worst case: their spreadsheet.** An agency hands us a homegrown Excel or
   asset inventory and we match it to the registry by hand. We'll take it rather than
   lose the data — but we never suggest it. Unkeyed, unstructured submissions are
   expensive to reconcile, which is why this plan runs **no open call for voluntary
   submissions** even though §14113(a) would allow accepting them.

The kickoff's "statewide amenity data collection campaign" should be scoped to exactly
this y/n floor for Horizon 1 (the Senate amendments deliberately narrowed "amenities" to
these two); richer amenity collection is Horizon 3 (see §12 — flagged).

**⚑ DECISION (technology):** where the registry lives (hosting, database, publication
pipeline). The kickoff left this open. Proposal to evaluate against: keep Horizon 1 boring —
the warehouse (BigQuery) remains the processing home, the published artifact is flat files
(CSV/GeoParquet/GeoJSON) on a public bucket + the website, and the "internal staging
registry" is a thin review database rather than a new
platform. Platform shopping (full registry product, Abzu-style) is a Horizon 3 question,
decided with real usage data.

### 4.4 Internal Caltrans user groups

The registry serves an unusually broad cross-section of Caltrans programs — each needing
stop data for different operational and planning purposes. This breadth is an argument for
the richer-than-statutory fields above (engineering coordinate, placement, amenities) and
for the internal registry being more than a staging area. *(⚑ This inventory is guesses —
they need to be VERIFIED with each office; rows marked ? are the shakiest. Several rows
also describe needs only a richer Horizon-3 registry would meet — v0 carries ID, name,
position, seating, shelter.)*

| Program | What they need from the registry |
|---|---|
| **Traffic Operations** | Safe stop placement on State Highway corridors; access geometry (crosswalks, slopes, ramps); **engineering-grade coordinates** for design decisions |
| **Rail & Mass Transportation** | Statewide transit funding oversight; compliance and service coordination; standardized naming and identifiers |
| **Data & Digital Services (DDS)** | Implements the statute: GTFS ingestion and stop aggregation, open-data publication, the Stop ID system, agency data-quality coordination |
| **Transportation Planning** | Corridor and long-range multimodal planning; amenity/accessibility data for equity and climate analyses; statewide standardization to integrate regional plans |
| **Maintenance / Pavement & ROW Imaging** | **?** Street-level imagery to check stop condition and find missing/damaged infrastructure — though stop amenities are usually the transit agency's or city's assets, not Caltrans-maintained |
| **Local Assistance** | ? |
| **Environmental, Sustainability & Equity** | **?** Access/amenity data for disadvantaged-community impact analysis — overlaps Planning's row and needs richer data than v0 carries |
| **Safety & Complete Streets** | Stop safety and multimodal access assessment; prioritize pedestrian-scale lighting, shelters, curb ramps, boarding pads |
| **Research (DRISI)** | Statewide stop data for modeling, travel-behavior, service-gap, and ridership analysis |
| **Construction & Project Delivery** | Engineering coordinates when a project relocates a stop; stable identifiers for as-built conditions |
| **District Transit Coordinators & Permitting** | Encroachment permits for stops on the State Highway System; ownership, maintenance responsibility, compliance |
| **Executive, Legislative & External Affairs** | Policymaker briefings and AB 1599 status updates (the law itself mandates no formal report); public-facing clarity on transit assets |

---

## 5. Workstream B — The universal ID

### 5.1 Status: no decision — options and arguments only

§14113(b) leaves the identifier entirely to the department, and the kickoff agreed that
identifier design needs further discussion and consultation with transit agencies. This
section therefore makes **no recommendation**. It catalogs the questions, the options, and
the arguments for and against each, so the decision is made once and deliberately —
**⚑ DECISION, target Nov–Dec 2026 at the weekly meeting, with focus-group agency input
(§8.2) before anything is frozen.** The questions compound in order: first stability, then
format, then who assigns.

#### Q1 — Should an ID stay stable forever, or be allowed to change over time?

| Option | Arguments for | Arguments against |
|---|---|---|
| **Stable forever** — assigned once; survives renames, repositions, operator changes; merges/splits retire IDs with redirects that keep old references resolvable | Downstream keys keep working: work orders, asset inventories, support cases, signage configs, research datasets don't break when stop data is corrected. Longitudinal analysis stays joinable across years. Avoids a failure mode we've seen in the wild: identity carried by a mutable operator code, which two pipelines can interpret differently. The registry's whole pitch to consumers is "a reference you can trust" | Requires a real registry: assignment service, redirect machinery, history. The ID alone tells a human nothing — region/name need a lookup |
| **Derived / allowed to change** — ID computed from the stop's attributes, chiefly position (geohash; Evan's June 2026 flowchart) | Anyone can compute an ID from coordinates alone — no central issuer, no waiting on Caltrans, near-zero infrastructure. The ID encodes where the stop is, so a gross position error is visible in the ID itself | The ID changes whenever the position is corrected — and our first big campaign *is* position correction, so the keys churn exactly when the data improves. Stops near cell boundaries get two plausible IDs. Every consumer must handle ID changes, so redirect/history machinery is needed anyway — just paid by everyone downstream instead of by the registry |

**What Entur does, and why.** Norway's national stop register (NSR) uses stable, assigned,
sequential IDs — `NSR:StopPlace:337` for a station/stop area, `NSR:Quay:42` for an individual
platform or bay — assigned centrally, exactly once. The ID never changes when the stop's name,
position, amenities, or operator change; each operator's original IDs are preserved forever
alongside as key-values (`imported-id`), and when stops are merged the old references remain
resolvable. Their reasoning: the register exists to give journey planners, ticketing systems,
and national datasets a reference that outlives operator data churn — if the ID were derived
from mutable attributes, every data correction would become a breaking change pushed to every
consumer. (Entur NSR research docs are migrating into this repo —
[issue #06](https://github.com/cal-itp/cal-quay/blob/main/issues/06-migrate-strategy-and-research-docs.md).)

#### Q2 — Format

| Option | Example | Arguments for | Arguments against |
|---|---|---|---|
| **Geographic-prefixed, human-readable** | `CA-SAC-00001234` | Humans can eyeball the region; sorts/groups by county; reads well in a report, a plan set, or a phone call; matches how districts and public works actually talk about places | The prefix is a claim that can become false — a stop corrected across a county line, a boundary dispute, an agency spanning counties. Then either the ID changes (breaking Q1-stability) or the prefix lies. Geography can always be derived from the coordinates when needed, so encoding it in the key buys little |
| **Opaque assigned digits** | `CA-73140926` | Nothing in the key can go stale; no creation-order or count revealed; optional check digit catches transposition when an ID is read over the phone or keyed into a work order | Means nothing to a human on its own; region requires a lookup. Less immediately legible in meetings and documents |
| **Sequential integer, namespaced** (Entur NSR style) | `CAT:StopPlace:414` | Simplest to generate; sortable; proven at national scale in Norway; namespace makes collisions with other systems impossible | Reveals creation order and total count; verbose for field use; the namespace convention feels foreign outside transit-data circles |
| **Geohash-derived** | `Stop:9q9p3xyz1` | See Q1 "derived" — self-computable, position-encoding | See Q1 "derived" — churns on position correction; boundary ambiguity. Choosing this format *is* choosing "allowed to change" on Q1 |

Couplings to keep in view: the geohash option answers Q1 as "changes over time"; the other
three are stable-forever formats. A **display-alias layer** — rendering
`CA-73140926 (SAC — Florin Rd & 24th St)` wherever humans read IDs — could pair with *any*
stable option; whether geography belongs **in the key itself** or **in the record, rendered
for display** is the core argument to have. One more coupling: if the Horizon-3 ambition
of voluntary `stop_code` convergence (§6.4) is taken seriously, the format should be
printable on a pole sign and easy to read aloud or text to an arrivals service — which
favors short digit strings over long namespaced forms. None of these is selected yet.

#### Q3 — Who assigns new IDs?

| Option | Arguments for | Arguments against |
|---|---|---|
| **Central assignment** (Caltrans/DDS issues; Entur model) | Guarantees uniqueness; single source of truth; keeps merge/split bookkeeping in one place | A bottleneck unless turnaround is fast; small agencies must know how to ask |
| **Pre-allocated ranges** (each agency gets a block) | Agencies self-serve within their range; no waiting | Coordination overhead; gaps and exhausted ranges; agency consolidations muddy ownership |
| **Fully derived** (anyone computes it) | Zero dependency on Caltrans | Two agencies at the same stop compute different IDs unless position-derived — which re-raises Q1 |

#### Q4 — Station / platform structure

Any scheme must handle large facilities: a station-level identity with child identities per
bay or platform (Entur's StopPlace → Quay is the working reference). The ~58 major
facilities (≥60 m span or ≥12 stops) will be labeled bay-by-bay by the operating agency
rather than auto-merged. Whether child bays get full registry IDs, suffixed IDs, or
registry-station + agency-bay hybrids is part of the format decision.

### 5.3 Who uses the ID — and what it lets them do

| User | With this ID, I can… |
|---|---|
| **Transit agencies** (scheduling/GTFS) | Publish my GTFS with the state ID attached and know every downstream app merges my stop with my neighbor agency's — without renaming my own stop_ids (guaranteed by §14113(c)) |
| **Maintenance & asset management** | Tie shelters, benches, work orders, and inspections to a stable key that survives GTFS renumbering and operator changes |
| **Engineering** | Reference exact stops in plan sets and project scoping; join stop locations to curb, ADA, and collision data |
| **Complete Streets** | Inventory amenity and accessibility gaps along a corridor across every operator that serves it |
| **Corridor planners** | Name the specific nodes a project touches ("these 14 IDs") and track them across agencies and years |
| **Customer success / agency support** (CRM — see §8.3) | Thread three agencies' tickets about the same pole into one record; track per-agency onboarding against a definite stop list |
| **Local public works** | Reference the stop in encroachment permits and sidewalk/curb projects so operators get notified of work at their stops |
| **Digital signage** | Key a physical sign to the physical stop and subscribe to *all* arrivals there, regardless of which agency's feed they arrive in |
| **Mapping & mobility platforms** (Apple, Transit, Google) | Deduplicate multi-agency stops for routing and transfer display (the Banning fix) |
| **Accessibility & disability communities** | Look up seating/shelter/boarding info for the physical stop, not per-agency fragments |
| **Researchers & developers** | Join ridership, amenity, and service datasets statewide; longitudinal analysis when stops move or consolidate |

(Full user stories to be developed with the focus group, §8.2 — these one-liners are the
seed set.)

### 5.4 Lifecycle events any scheme must answer

Whichever way Q1–Q4 go, the decision doc must specify what happens at each of these moments
(the options below show the trade-space, not decisions):

- **New stop:** who assigns the ID and how fast? Central assignment (same-week, eventually
  same-day turnaround) vs. agency self-serve from a range vs. self-computed — follows
  directly from Q3.
- **Moved stop:** small correction = same ID with history? Relocation beyond some threshold
  (⚑ threshold TBD) — same stop or new stop? Under a derived scheme, *any* move changes the ID.
- **Merge** (two records turn out to be one physical stop) / **split** (one record turns out
  to be two): which ID survives, and how do old references keep resolving? Every option
  needs some redirect/alias answer here — Entur keeps all prior IDs resolvable forever.
- **Decommission:** retire-and-never-reuse (preserves longitudinal analysis) vs. allow reuse
  (cheaper keyspace, but a reused ID silently corrupts historical joins).

---

## 6. Workstream C — Analysis & the two-way conversation

**This is the heart of the program.** The kickoff framed the registry as a dataset to
publish. This draft's position (§12): the published dataset is the *output* — the *product*
is the loop where we detect a problem, tell the agency specifically what to change, they
change it (or tell us why not), and we verify the fix landed in their next GTFS. That loop,
once built, carries everything else: position fixes now, name and structure suggestions
later, amenity updates forever. It also makes us the natural coordinator *between* agencies
sharing a stop — a role nobody holds today.

Every sub-workstream below follows the same cycle:

> **detect → propose → notify → agency acts, declines, or opens a conversation → verify in
> next feed → close**

Tracked per-issue and visible to the agency. There must be a real **decline-or-conversation
path**: an agency disagreeing is a recorded outcome — and often the start of the actual
coordination work between agencies — not a nag loop.

### 6.1 Shared stops — pick the canonical position (the low-hanging fruit)

Where multiple agencies serve the same physical stop with discrepant coordinates:

1. Detect the multi-agency groups (started work on this — 3,168 cells, need to expand to distance-based matching).
2. For groups with serious discrepancy, **select the best existing agency position as
   canonical — never average/synthesize a new point** (see §12; this reverses the Pairwise
   Integrate approach piloted in June). Automated pre-pick with confidence scoring; a human
   confirms every multi-agency area in a purpose-built review tool — candidate points over
   satellite imagery, fast keyboard confirm/override.
3. Notify **all** agencies at the stop: "we believe this is the canonical position — please
   adjust your GTFS coordinates to match."
4. Verify in the warehouse that each agency's next feed version actually moved; close out.

**The rules are deliberately unwritten.** How far off is far enough to ask (10 feet? 30?),
what counts as "serious discrepancy," when a human look is required — we don't know yet,
and pretending otherwise would be premature. The expectation is that **the rules get
figured out from real-world data as the first fixes happen**, then written down once
they've survived contact with actual stops and agencies.

**Match zones — remember every decision as a shape, not just a point.** When a reviewer
resolves a shared-stop area, we save two geometries: the **canonical point** (where the
stop really is) and a **match-zone polygon** traced around where the member agencies'
points actually sit — including the wrong ones. The polygon is the registry stop's
standing claim on that patch of ground, and it does three jobs:

1. **Future matching becomes deterministic.** Next month's feeds arrive; a stop point that
   lands inside a zone is associated to that registry ID automatically. No re-clustering
   from scratch, no re-litigating solved areas. A point landing in *no* zone (or in two)
   is the only thing that generates new review work.
2. **Adjacent stops stay distinct.** Three stops in a row each own their own polygon, with
   the boundary between them drawn where the reviewer put it — so "these points belong to
   this one, those to that one" survives as data, exactly where cell-grid methods guess.
3. **Error tolerance is per-stop, not global.** A stop whose members have historically
   scattered 40 m gets a generous zone; a tight downtown pair gets narrow ones. The zones
   *encode* the real-world rules §6.1 says we'll learn — stop by stop.

Default: build a zone for **every** multi-agency area as its review decision is recorded
(the review tool exports point + polygon together). This also addresses the
boundary-straddle weakness of geohash binning (the Artesia problem): zones are shaped to
each stop's actual error pattern, not to grid lines. **⚑ Open question — generation
method:** hull-of-observed-members plus a buffer, a Voronoi split between neighboring
canonicals, reviewer-drawn where automation is wrong — or something smarter (a plain
per-stop match radius may suffice for isolated stops; polygons earn their keep where stops
crowd). Single-agency stops may get zones lazily, the first time a mismatch actually
occurs. Zones live in the internal registry as a matching artifact and we publish these as a part of our repo.

**Matching test cases.** Whatever matching method and zones we end up with must get these
seven canonical cases right — they're the regression suite for this section, and the
review tool should surface each type:

| # | Scenario | Expected |
|---|---|---|
| 1 | Same physical stop, different names ("Main & 1st" vs "1st St & Main Ave") | Match — one ID |
| 2 | Same stop, offset coordinates (one agency's point ~15 m off) | Match — one ID |
| 3 | Opposite sides of an intersection, ~50 m apart | No match — two IDs |
| 4 | Multi-agency pile-up: four agencies, four names, four coordinate sets (Banning) | One ID |
| 5 | Stop relocated ~200 m down the street | Policy call — the §5.4 move-threshold ⚑ |
| 6 | Rail station with multiple platforms | Station-level ID with children (§5 Q4) |
| 7 | Two stops sharing a geohash cell but on different streets | No match — exactly where cell binning fails and zones must not |

### 6.2 Egregious position errors — direct reports

Some stops are off in ways that are unmistakable once seen. **Possible problems we've
seen so far:** a stop placed in a roadway/freeway median, stops in the wrong city, and the
two stop codes attached to each other's stations in a regional feed, kilometers apart.
Each gets an individual report to that agency: map/screenshot, what
we think is wrong, the suggested correction, and a tracked issue. How we *find* these is
still open — badly mispositioned stops often escape proximity grouping entirely (Artesia),
so candidate methods include route-shape sanity checks, distance-to-road measures, and
plain ad-hoc reports (one of the worst cases we know of arrived by email). Like §6.1,
detection rules and
thresholds get worked out from real cases, not specified up front.

### 6.3 Names — accept by default, suggest deliberately

**Default: the registry adopts the operating agency's current stop name.** Agencies are never
blocked on naming. Since registry names are seeded *from* agency names, §99150.5 name
conformance is automatic at seed time. Legislative intent backs this light touch: the
Assembly floor analysis describes the Banning fix as assigning one ID *"allowing the
transit agencies to continue to call the stop by their unique names while also ensuring
mapping applications understand it is the same location."* Where we think a name should change — four different
names at one Banning stop; "Main St & 1st Ave" vs "1st & Main" — we issue a **suggested**
name through the same loop as position fixes. Multi-agency stops need one registry name even
when members disagree; pick one (operating-agency majority, or the facility owner's),
suggest alignment to the others, don't force it in Horizon 1–2.

### 6.4 Field & structure recommendations *(Horizon 3, recommended not required)*

The same loop eventually carries richer asks: add `parent_station` structure at transit
centers, fill `wheelchair_boarding`, fix `location_type`, adopt the GTFS fields we specify
(§7). Always framed as recommendations with a clear "this is beyond the legal minimum"
label.

The endgame of this track: **voluntary convergence on the universal ID as the
rider-facing stop code.** §14113(c) means we can never require it — but nothing stops an
agency from *choosing* to set its `stop_code` to the universal ID, and the natural moment
costs nothing: the next scheduled signage refresh, fare-system update, or re-signing
project. An agency that converges gets one number on the pole, in the trip app, in the
arrival-prediction text, and in every state dataset. If agencies do this at their own
pace, California's rider-facing stop numbering unifies over the years without a single
mandate. (`stop_code` only — we would never suggest converging `stop_id`, which is
internal plumbing wired through the agency's own systems.) This ambition feeds the §5
format decision: an ID that may end up printed on signs and texted by riders should be
short, digit-friendly, and unambiguous read aloud.

### 6.5 Per-agency reports — an idea, not a commitment

A possible future output: a generated report per agency — their stops, open suggestions
(position, name, fields), what's been fixed — perhaps published on the website (§9), which
would let an agency's board, regional agency (MPO/RTPA), and riders see status without asking us. — it has real upsides (transparency, gentle
accountability) and real risks (feels like a scorecard, could sour the §6 conversation).
⚑ Worth discussing down the road, once the loop is running and focus-group agencies (§8.2)
have reacted to the idea. If adopted, the public-vs-private question comes with it.

---

## 7. Workstream D — Getting the IDs back to agencies

The registry fails if IDs stay in our database. **The preferred path: the agency updates its
own GTFS** with the fields we specify (the ID field, and conformed name/position). Every
other path exists to make that eventually possible — not to replace it.

| Path | For whom | What happens |
|---|---|---|
| **1. Crosswalk file** (floor, everyone) | All agencies | Published table: `agency + your stop_id → universal ID (+ canonical name/position, suggested fixes)`. CSV + GeoJSON, versioned, free |
| **2. API** | Technical agencies & vendors | Query by stop_id, by location, bulk; returns IDs + canonical records. Also the channel for new-stop requests |
| **3. Validation tool** | Agencies mid-update | Upload your GTFS and get back: "27 stops matched, 2 new (IDs assigned), 1 position 40 m off canonical, 3 missing IDs" — pass/fail before publishing |
| **4. Done-for-you enrichment** | Low-capacity agencies | Agency sends current GTFS (no changes on their end); we return it with `stop_ca_universal_id` (⚑ field name TBD) filled in, names/positions conformed |
| **5. Agency hub hosting** | Smallest agencies | We publish the enriched feed on the Caltrans **agency hub** as their feed of record, until their vendor or staff can take it back |

**Paths 4–5 are not new inventions — they extend what DDS already does.** DDS already
*creates* GTFS for 15+ services (small shuttles and municipal operators, via the Data
Quality branch's GTFS schedule-creation service, with spreadsheet templates agencies
already know) and already *hosts* feeds at
[gtfs.dds.dot.ca.gov](https://gtfs.dds.dot.ca.gov/), backed by a repo. The agency hub is
that service, extended: enriched feeds with registry IDs, more agencies. Several agencies
also produce their GTFS from Excel today — the sample spreadsheet templates exist and can
carry the ID column from day one.

**The hub also grows a write side: a map of your own stops.** A hub-hosted agency has no
GTFS pipeline of its own, so it needs *some* way to tell us when reality changes. The
simplest honest answer is geospatial: log in, see your stops on a map, click one —
confirm or correct seating/shelter, flag "this stop moved," note a new or closed stop.
Every edit lands keyed to the registry ID (they're editing *our* record of *their*
stops), so it flows into the hosted feed and the registry with no matching step — the
same property that makes the §4.3 pre-filled spreadsheet safe, in a form that fits
inherently geospatial facts. Scope it deliberately small: an agency can only see and edit
its own stops, and only the fields we open up. **Location is the hard boundary: a stop's
position is editable only when we completely control the agency's GTFS** (the hub
generates their feed, so moving the pin moves the stop everywhere — one source of truth).
An agency that publishes its own GTFS can *flag* a position problem here, but the actual
move must land in their feed through the normal loop (§6.1) — otherwise the registry and
their published GTFS drift apart, which is the exact disease this program exists to cure. This doubles as the working pilot for the
Horizon-3 "self-serve portal" question (§4 ⚑) — before any Abzu-style platform decision,
we'll know how real small agencies actually behave in a stop editor.

**What the law says — §99150.5(b)(2), verbatim:** operators must *"use the unique
identifier that conforms with the California Transit Stop Registry when publishing any
dataset with stop information, including, but not limited to, General Transit Feed
Specification datasets, transit stop seating and shelter information, stop-level ridership
datasets, or any other format used to incorporate transit service information to a
generally available trip-planning mobile application, or during publication of agency open
datasets."* So GTFS **is** named — as one example in a deliberately non-exhaustive list —
but **no mechanics are mandated**: no field name, no file format, no schema. Two
consequences: we're free to choose the mechanics, and agency obligations are **wider than
GTFS** — ridership extracts, seating/shelter reporting, open-data portal exports all must
carry the ID, and guidance must say so. Note also §99150.5(b)(3): agencies report
seating/shelter *using the unique identifier* — the crosswalk (path 1) is a statutory
prerequisite for agencies to perform their own reporting duty.

**⚑ DECISION (dataset mechanics):** when an agency publishes data, how does the
universal ID physically appear? Four candidate mechanics:

1. **Custom GTFS column — the draft's lean for Jan 2028.** Agencies add one column (e.g.
   `stop_ca_universal_id`) to `stops.txt`. Works today: no standards body to wait on, and
   nearly all California stop data is published as GTFS — so this one move covers most of
   the compliance surface.
2. **Formal GTFS extension — pursue in parallel, Horizon 3.** Propose the field to the
   GTFS spec community so it becomes official. Right long-term (other states will copy
   California), but spec consensus takes years — it can't be the Jan 2028 answer.
3. **Registry-as-canonical with exports — on the table, not leaned to.** Flip the
   direction: the registry becomes the authoritative dataset and publishes exports that
   apps consume (Norway's model). A much bigger change to how California publishes.
4. **Non-GTFS conventions — mandatory homework under every option.** The law covers *any*
   dataset with stop info, so guidance must also name the ID column for ridership CSVs,
   shapefiles, and open-data exports, whichever option above wins.

---

## 8. Workstream E — Customer success & agency engagement

The outreach universe is **~258 organizations with at least one fixed-route service**
(per the Cal-ITP Airtable; 205 of them publish stops under their own feed label today —
see §2). Three capability tiers:

| Tier | Who | What they get |
|---|---|---|
| **Self-serve** | LA Metro, SF Muni, AC Transit, … | Docs, API, validation tool. They hit Jan 2028 on their own |
| **Capable with guidance** | Mid-size municipal operators | Pre-filled spreadsheets, templates, a named human, office hours |
| **High-touch** | Rural, small, tribal operators | Done-for-you enrichment (§7.4), hub hosting (§7.5), phone-level support |

### 8.2 Small-agency focus group — the first move

Before writing guidance for ~258 organizations, run the actual exercise with a handful of
them.
This is also a statutory duty, not just good practice: §14113(a) requires the registry be
created *"with input from transit operators,"* and §14113(d) requires considering operator
input on design, data sources, and compliance guidance *"to limit adverse financial and
human resources impacts."* The focus group is how we discharge both, documented.
**Step zero: a check-in with the customer success team** — they own the agency
relationships and should shape (and bless) the recruit list before any outreach.

**Recruit by technology stack, not by size alone.** What it takes to get a field into an
agency's GTFS depends almost entirely on *how their GTFS gets made*. The Transit Technology
Stacks Airtable records a GTFS-creation stack per service; recruiting one representative
agency per major stack means the focus group's lessons generalize to everyone else on that
stack. The major stacks and draft candidates (⚑ list to be vetted with customer success):

| GTFS-creation stack | ~Services on it | Draft candidate |
|---|---:|---|
| Trillium GTFS Manager | 60+ | Humboldt Transit Authority, or Mendocino Transit Authority |
| Remix (CalSTA-provided) | ~17 | Redding Area Bus Authority |
| DDS GTFS-creation service (we make their GTFS) | 15 | Any of the LA-county shuttles (e.g. Glendora, Alhambra) — trivially done-for-you, proves path §7.4 end-to-end |
| Trapeze scheduling export | 14 | **Santa Barbara MTD** |
| Giro HASTUS export | 12 | **Monterey-Salinas Transit** |
| Excel / spreadsheet-built GTFS | 6 | Ojai Trolley or Glendale Beeline — the sample sheets already exist |
| CAD/AVL-generated (Connextionz, GMV, Passio, …) | ~12 | Pasadena Transit or SLO RTA |
| MTC 511-published | 6 | Union City Transit — tests the "my regional feed publishes for me" case |
| In-house pipeline | 2 | Tulare County Regional Transit |

With each, run the same drill:

- Can they add a field to their GTFS at all? Who actually edits it — staff, vendor,
  scheduler export config, consultant?
- How long does one round trip take, from our crosswalk and asks landing to their
  corrected feed being published?
- What breaks? What wording confuses? What does their vendor charge?
- Which delivery path (§7.1–7.5) does each naturally reach for?

Output: validated guidance docs *per stack* ("here's how to carry the ID out of HASTUS /
Trillium / your spreadsheet"), a realistic per-agency effort estimate (the single most
important input to Horizon 2 planning), tested tooling, and testimonials. A vendor-stack
win multiplies: one worked path through Trillium covers 60+ services. This also discharges
the "incorporate transit operator input into registry design" kickoff item — including on
the ID scheme (§5) before it's frozen.

### 8.3 Onboarding machinery

- **CRM tracking:** one record per agency — tier, vendor, contacts, delivery path, status
  against Jan 2028, legally-obligated flag, open suggestions from §6. **⚑ Tooling:** two
  candidates. *Airtable* — the team is fast with it, and the agency universe already
  lives there (the 258 organizations, services, and technology stacks are existing
  records — tracking becomes added fields and links, not an integration project).
  *Salesforce* — the eventual enterprise home, but still in development. Proposed:
  start in Airtable now, migrate to Salesforce when it's ready, and confirm the plan
  with customer success at the check-in.
- **Sequence:** the customer-success check-in comes first, then the focus group, then
  willing/engaged agencies, then regional clusters (peer knowledge spreads), then
  interagency corridors (most rider benefit), and finally the long tail with high-touch
  support.
- **Vendor track in parallel:** most small agencies' GTFS is actually edited by a vendor or
  generated by a scheduling/CAD-AVL product (§8.2 table). Direct engagement with
  Trillium/Optibus, Remix, GIRO, Trapeze et al. turns one integration into dozens of
  compliant agencies.
- **Leverage existing relationships:** Cal-ITP agency relationships, MPOs/RTPAs for regional
  coordination (kickoff item — agreed).
- **The legally-obligated list:** the State Controller's annual TDA *Transit Operators and
  Non-Transit Claimants* report is the authoritative roster of §99210 operators. Reconcile
  it against the ~258 so each CRM record carries a flag: legally obligated vs. voluntary
  invite.

### 8.4 The message to agencies (short-term vs. long-term)

Published plainly on the website (§9):

> **Required by law (Jan 1, 2028):** match your stop names/locations to the registry, carry
> the registry ID in your published stop data, report seating & shelter. Here's the minimum
> path, here are our free tools, and a human reads **hello@calitp.org**.
>
> **Where this is going (optional, later):** suggested position/name improvements, station
> structure, richer amenities. We'll always label what's required vs. recommended, and
> changes will come with notice.

---

## 9. Workstream F — The website

Public site, built from a GitHub repo via GitHub Pages (MkDocs Material or similar — same
toolchain as other Cal-ITP docs; versioned, PR-reviewable, free).

| Horizon 1 | Horizon 2 | Horizon 3 |
|---|---|---|
| This plan, published | Per-agency status pages — only if adopted (§6.5) | Live dashboards (adoption %, open vs. closed suggestions) |
| "What the law requires of you" page (§8.4) | Guidance docs & how-tos per delivery path (§7) | Change-log / RSS for registry releases |
| FAQ + contact | Crosswalk & registry download pages | API docs |
| | Validation tool front door | |

The repo-based site doubles as the public record of decisions (this doc, decision log,
release notes) — stakeholders can literally watch the plan evolve via pull requests.

---

## 10. Governance

- **Weekly implementation meeting** (kickoff action item — agreed). Standing agenda:
  decision log review, horizon-1 critical path, blockers.
- **Decision log** in the repo: every ⚑ in this doc gets an entry — options, call, date,
  owner. The ⚑ list, in rough order of urgency:
  1. ID scheme — stability (Q1), format (Q2), assignment model (Q3), station structure
     (Q4) (§5) — blocks all ID assignment; target Nov–Dec 2026, after focus-group input
  2. Registry hosting/publication tech (§4) — keep-it-boring proposal on the table
  4. CRM for agency tracking (§8.3)
  5. Per-agency reports — whether to do them at all; if yes, public vs. private (§6.5)
  6. Stop-move threshold / same-stop policy (§5.4)
- **Who does what** (exactly one sign-off owner per row; names get attached to roles at
  the weekly meeting). "Registry team" = the
  engineers/analysts building and operating the system; "Program lead" = the person
  empowered to say a requirement is met:

| Activity | Does the work | Signs off | Gives input | Kept informed |
|---|---|---|---|---|
| ID system design | Registry team | Program lead | Focus-group agencies, app vendors (Apple/Transit), Entur precedent | All operators |
| Registry build & publication | Registry team | Program lead | DDS GIS branch | — |
| Shared-stop review & canonical picks | Registry team + reviewers | Program lead | Operating agencies (confirm/dispute) | Regional feed builders (511/VCTC); RTPAs as relevant |
| Discrepancy notifications & verification | Customer success + registry team | Program lead | Agencies | Regional feed builders (511/VCTC); RTPAs as relevant |
| Guidance docs & website | Registry team | Program lead | Focus-group agencies (clarity review) | — |
| Agency compliance (Jan 2028) | Transit operators | Caltrans (statutory) | Registry team (tools, support) | Apps, riders |
| Legislative reporting / implementation plan | Program lead | Division leadership | Registry team | — |

---

## 11. Risks

| Risk | Mitigation |
|---|---|
| Shared-stop human review doesn't finish by Apr 2027 | Fallback rule (§3): unreviewed areas ship unmerged, merge later via redirect. Floor is never blocked |
| Agencies ignore suggestions (we lack Norway's statutory leverage — kickoff point, agreed) | The law *does* mandate conformance for TDA recipients; beyond that: make the easy path genuinely easy (§7), a genuine decline-or-conversation path so agencies engage rather than ignore (§6), regional pressure via the RTPA that allocates their TDA funds, TDA-compliance framing |
| Seating/shelter data doesn't exist anywhere for many stops | y/n floor only; pre-filled spreadsheets; provenance flags; "unknown" is an acceptable v0 value with a plan to fill it |
| Vendor bottleneck (many small agencies share a few GTFS stacks) | Recruit the focus group per stack (§8.2); engage the stack owners directly (Trillium GTFS Manager alone covers 60+ services; Remix, Trapeze, HASTUS, CAD/AVL vendors the bulk of the rest) — one vendor fix onboards dozens of agencies |
| ID scheme debated past the target date | The decision log forces it at the weekly meeting with focus-group input; latest responsible moment is ~Jan 2027 for ID assignment and review to finish before the Apr 2027 registry freeze |
| Warehouse build-lag produces wrong published numbers | Pinned dated snapshots only; never live pulls |
| A wrong merge ships (two real stops under one ID) | Human review of every multi-agency merge; splits supported with redirects; agencies can dispute via the loop |
| Steady-state funding is thin (low hundreds of thousands/yr from 2027–28 per Senate Approps; agency costs likely not reimbursable) | Keep the operating model lean — boring tech (§4), automation-first loop, self-serve paths; make the free tools genuinely cheap for agencies (§14113(d) obligation); scope Horizon 3 to what the envelope sustains |

---

## 12. Positions this draft takes (flagged for discussion)

Where this document deliberately differs from, or sharpens, the kickoff discussion —
stakeholders should treat these as proposals to accept or challenge:

1. **The two-way loop is the product; the published registry is an output.** The kickoff
   emphasized the registry as a separate dataset to publish. We will publish it — but the
   lasting value is the conversation where we detect, suggest, the agency acts, and we
   verify (§6), which
   also positions us to coordinate *between* agencies. The dataset alone would be one more
   aggregated file; the loop is what makes it converge toward true.
2. **Select, don't average.** Canonical positions are chosen from existing agency points;
   we never synthesize averaged coordinates (contra the June Pairwise Integrate pilot,
   which moves every point and manufactures false merges across streets).
3. **Human review on every multi-agency merge.** Automation narrows 95k stops to a few
   thousand candidates; it doesn't make final merge calls.
4. **The ID scheme is left genuinely open** (§5) — no format, stability model, or assignment
   model is pre-selected in this draft; options and arguments are cataloged for a
   deliberate decision made with focus-group agency input. The draft asserts only one
   constraint: whatever scheme is chosen must answer, up front, what happens to an ID when
   a stop's position is corrected (§5.1 Q1) — because position correction is our first
   major campaign.
5. **Amenity campaign scoped to the statutory y/n floor for Horizon 1** — the kickoff's
   statewide amenity collection campaign is real but belongs in Horizon 3 beyond
   seating/shelter; don't let shelter-lighting-signage completeness threaten June 2027.
6. **Keep Horizon 1 technology boring** — flat-file publication + thin review DB before any
   registry platform purchase/build.
7. **Agencies keep their own stop_ids forever** — and this one is no longer just a
   position: §14113(c) *forbids* requiring an operator to change its own stop numbering.
   Conformance means carrying the universal ID and matching name/position — never
   renumbering internal systems.

---

## Appendix A — Internal addendum (not for the public site)

The internal-facing version of this plan adds:

- **Internal staging registry** (§4.A1): review states, override files/tables (e.g., the
  multi-level rail station overrides), provenance and confidence columns, reviewer
  assignments.
- **Review tool** operations: queue priorities (ambiguous pick / in-roadway / station
  complexes first), keyboard workflow, decision storage — each decision exporting
  canonical point + match-zone polygon (§6.1) — and review-pace metrics
  (areas per hour, which sets the staffing math for the statewide queue).
- **Engineering coordinates** (§4.4): internal-only second position per stop; sourcing
  (surveys, ROW imaging, as-builts), update rules, and who may edit.
- **Issue tracker internals:** per-agency suggestion queues before they're published,
  escalation paths (unresponsive agency, then its RTPA — the body that allocates its TDA
  funds — then the TDA-compliance conversation).
- **Snapshot & pipeline discipline:** pinned snapshot dates, cache/reprocess flow
  ([repo README](https://github.com/cal-itp/cal-quay/blob/main/README.md)).

## Appendix B — Source documents

- [AB 1599 — Ch. 269, Stats. 2026](https://leginfo.legislature.ca.gov/faces/billNavClient.xhtml?bill_id=202520260AB1599)
  [Assembly floor analysis, concurrence vote (local PDF)](../sources/AB1599-assembly-floor-analysis-2026-08-21.pdf)
- [Kickoff meeting notes, Oct 6 2026](../AB%201599%20Kickoff%20Meeting.pdf)
- [cal-itp/cal-quay](https://github.com/cal-itp/cal-quay) — scripts, issue drafts, analysis notes
- Entur NSR (Norway) research — ID system & data model
