# California Transit Stop Registry — Scoping Document \- DRAFT

## 1\. Project Purpose / Mission Statement

**What [AB 1599](https://leginfo.legislature.ca.gov/faces/billNavClient.xhtml?bill_id=202520260AB1599) mandates:**

Caltrans must create the California Transit Stop Registry — a centralized, statewide dataset of standardized transit stop information — by June 1, 2027 (Gov. Code §14113). Every transit operator receiving TDA funds must conform their stop names and locations to the registry and use its unique identifiers in all published datasets (GTFS, amenity data, ridership data, trip-planning feeds) by January 1, 2028 (Pub. Util. Code §99150.5).

*(Dates per AB 1599 as enrolled Aug 30, 2026 — both deadlines slipped ~6–7 months from the version this doc was originally drafted against: registry Dec 31 2026 → June 1 2027; operator compliance June 1 2027 → Jan 1 2028.)*

**The problem this solves:**

Today, transit stop data in California is fragmented across 200+ operators. When multiple agencies serve the same physical stop, it appears as separate entries with inconsistent names, locations, and IDs. A rider transferring between agencies sees conflicting information in trip-planning apps. An analyst trying to measure systemwide ridership or accessibility can't join datasets across operators. A new agency entering a corridor has no canonical reference for where stops exist.

The Banning example from the Assembly Transportation Committee analysis makes this concrete: one physical stop where four different agencies each call it by a different name. Under the registry, that location gets one ID — the universal stop ID — and mapping applications understand it's the same place for routing purposes.

**Success looks like:**

- A transit rider in Banning sees one stop, not four, when planning a transfer  
- An analyst can run a statewide query: "show me every stop that is the same universal stop ID across agencies, with shelter and wheelchair access"  
- A new mobility provider entering a market gets a clean, canonical list of stops with unique IDs  
- Every GTFS feed published in California uses the same universal stop ID for the same physical location

## 2\. Products & Deliverables

Based on the AB 1599 mandate and Entur's NSR model, and the draft team notes, there are four product lines:

### 2a. The Registry (data product)

The core deliverable. A database of every transit stop in California, each with:

- **Universal stop ID** —   
- **Canonical name and location** — the authoritative name and lat/lon for each stop

	**OPTIONAL:**

- **Stop type** — on-street bus, rail station, ferry terminal, etc.  
  - **Amenities** — shelter, bench, lighting, wheelchair accessibility  
  - **Version history** — stops change over time (names, locations, amenities). Full audit trail.

**Stakeholders:** 

- DDS (presumptive \- builds/maintains),   
- transit operators (consume),   
- trip-planning apps (consume via GTFS), 

**Requirements:**  
	

- Accessible via API and bulk download (daily export, like Entur's NeTEx dumps)  
- Supports incremental updates (new stops, stop changes, stop decommissions)  
- Spatial query capability ("stops within X meters of point")  
- Versioned — every change tracked with timestamp and source

### 2b. Stop ID Mapping Table

The on-ramp for agencies. Every agency needs: "my stop\_id X \-\> universal ID Y." If this isn't 

**Stakeholders:**   
Transit operators (primary users),   
DDS (maintains mappings)

**Requirements:**

- Queryable by agency \+ original stop\_id → returns universal ID  
- Downloadable as a flat file (CSV/GTFS-friendly)  
- Updated when stops are merged, split, or re-identified  
- Original IDs preserved indefinitely (like Entur's keyValues system)

### 2c. Guidance Documentation

Agencies need to know what's required and how to do it. This covers:

- What fields they need to add to GTFS (or whatever format is chosen)  
- Timeline for compliance (AB 1599 says operators conform by January 1, 2028\)  
- How to request corrections or report issues with the registry  
- How new stops get added to the registry  
- What happens when multiple agencies share a stop  
- How stop consolidations and decommissions are handled

**Stakeholders:** Transit operators, DDS, Caltrans

### 2e. Support Structure

Agencies will have edge cases, bad data, and questions. Entur has [Abzu](https://github.com/entur/abzu) — a full React admin UI where county staff edit stops directly. Options for California:

- **Admin UI** (like Abzu) — agencies self-serve edits, Cal-ITP approves?  
- **Ticketing/issue tracker** — agencies submit corrections, Cal-ITP staff resolves?  
- **Office hours / direct support** — for smaller agencies without technical staff  
- **Automated validation** — flagging inconsistencies before they become problems  
- **Tools \-** 

**Stakeholders:** Transit operators, Cal-ITP support team

**Open question:** Which model? The draft notes ask: "Support structure for agencies to request assistance?" This needs a decision on what Cal-ITP can sustain operationally.

### 2d. Meeting Agencies Where They Are

Not all 200+ California transit operators are the same. Some publish GTFS daily with dedicated technical staff. Others have one part-time person managing everything in a spreadsheet.

**The agency spectrum:**

| Tier | Description | Examples | Needs |
| :---- | :---- | :---- | :---- |
| **Self-serve** | Full-time technical staff, GTFS is routine | LA Metro, SF Muni, AC Transit | API access, docs, validation tooling — they'll handle onboarding themselves |
| **Capable with guidance** | Some technical capacity, GTFS exists but may have gaps | Mid-size municipal operators | Step-by-step guidance, templates, a human to answer questions |
| **High-touch** | Little to no technical staff, GTFS may be outdated or nonexistent | Rural/small operators, tribal transit | Someone needs to walk them through it. Pre-filled stop data. Possibly generate compliant GTFS for them |

- **Pre-populated stop inventory** — pull each agency's current GTFS stops from the warehouse, match against the registry, give them a spreadsheet: "here are your stops, here are their universal IDs, confirm or correct"  
- **Validation-as-you-go** — a tool where an agency uploads their GTFS and gets: "3 stops matched, 2 new stops detected, 1 stop missing coordinates — fix these before publishing"  
- **Automated name cleanup** — flag common problems ("Main St & 1st Ave" vs "1st & Main" → here's the canonical name)  
- **Self-serve GTFS export** — for agencies that can't modify their GTFS pipeline, generate a compliant export from the registry that they host  
- **Done-for-you universal IDs** — agency submits their existing GTFS (no changes needed on their end). Cal-ITP adds the universal stop ID to every stop, returns the enriched GTFS. Agency can either take it back and host it themselves, or opt into Cal-ITP hosting the enriched feed. This removes the single biggest barrier for low-capability agencies: they don't need to touch their GTFS pipeline at all.

**Outreach strategy (customer success team window):**

1. **Start with the willing** — agencies already engaged with Cal-ITP, Better Buses participants. Get early wins, generate testimonials.  
2. **Regional clustering** — group agencies by geography. Success in one region creates peer knowledge-sharing.  
3. **Prioritize interagency corridors** — where transfers between operators are common, the registry has the most immediate rider benefit.  
4. **Tiered timeline** — self-serve agencies hit the legislative deadline independently. High-touch agencies get active support from customer success while the team exists, then transition to self-serve tools.

---

### 5d. Stop consolidation rules

*"Two stops are being consolidated, what is the requirement for how those should be handled?"*

Open questions for California:

- What's the threshold? Two stops within X meters with the same name → auto-merge? Or always human review?  
- Who resolves disputes? What if two agencies disagree about whether their stops are the same?  
- How do we communicate changes to trip-planning apps?

### 

**What do Mobility Providers Want or Need?**

-   
-   
-   
- 

**Some suggested rules around the stop consolidation**

Analysis (Needs to be re-verified):  
 \- California has \~135k GTFS stops. The genuine cross-agency reconciliation problem is only \~5,615 locations — roughly 4% of all stops. The other \~96% are single-agency stops that just need an ID minted (trivial).  
\- Of those, 76% are high-confidence and 55% are within 10 m — the bulk are easy auto-merges. The genuinely hard tail (medium confidence / larger offset) is only \~1,500–1,800 pairs — a human-reviewable amount.  
\- It's geographically concentrated: every top feed-pair involves LA Metro. The Bay Area cross-agency overlap is a smaller slice still.

 1\. Protected single-operator rail → excluded entirely.  
  BART, Caltrain, ACE, Amtrak, Capitol Corridor, Muni Metro \+ VTA light rail. Their stops are authoritative and unique; agencies shouldn't reshape them, so they  
  never enter cross-agency matching. Dropped at load by operator name. (\~851 stops, 5-county.)

  2\. "Bay Area 511 Regional" aggregator → cluster-aware de-dup.  
  Drop a 511 stop only when a non-511 (precursor) operator stop sits in the same cluster. Keep 511 stops in clusters with no other  
  source (don't orphan operators that only publish via 511). Runs after clustering. (\~17.7k dropped, 305 kept.)

  3\. Major facilities → out of scope, handed to the agency.  
  A cluster is MAJOR\_STATION if it spans ≥ 60 m OR has ≥ 12 stops.   
  The operating agency labels each bay. (\~58 clusters / 865 stops.) Thresholds tunable.

### 5e. Test case suite

*"Generate test cases that we care about — near but should be distinct. Should be combined."*

Formalized test categories for the matching algorithm:

| \# | Scenario | Expected |
| :---- | :---- | :---- |
| 1 | Same physical stop, different names ("Main & 1st" vs "1st St & Main Ave") | **Match** |
| 2 | Same stop, offset coordinates (one agency's lat/lon is 15m off) | **Match** |
| 3 | Opposite sides of intersection, 50m apart | **No match** |
| 4 | Multi-agency: 4 agencies at one location (Banning), each with different stop\_id, name, coordinates | **One universal ID** |
| 5 | Stop relocated 200m down the street | **New universal ID?** Policy decision needed |
| 6 | Rail station with multiple platforms (parent-child) | **Station-level ID** with platform sub-IDs (Entur's StopPlace → Quay model) |
| 7 | Stops that share a geohash cell but are on different streets | **No match** (this is where geohash-based grouping fails) |

## 4\. RACI

The draft notes ask: *"Who is responsible or empowered to say we've met the requirements?"*

R \= Does the work | A \= Signs off / answerable | C \= Provides input | I \= Kept in the loop

| Activity | R | A | C | I |
| :---- | :---- | :---- | :---- | :---- |
| **ID system design** (format, generation, claiming) | Registry team | Program lead | Transit app developers (Apple, Transit), Entur precedent | Transit operators |
| **Registry build & deployment** | Registry team | Program lead | Cloud infrastructure | — |
| **Initial stop population** (bulk import \+ matching) | Registry team | Program lead | Transit operators (validate their data) | — |
| **Stop matching quality** (near vs. combined decisions) | Registry team | Program lead | Transit operators (confirm/correct) | — |
| **Guidance documentation** | Registry team | Program lead | Transit operators (review for clarity), analysts | — |
| **Agency compliance** (adopting universal IDs by Jan 2028\) | Transit operators | Caltrans (legislative mandate) | Registry team (support, validation tooling) | Trip-planning apps, riders |
| **Ongoing registry maintenance** (new stops, changes, decommissions) | Registry team | Program lead | Transit operators (submit changes) | — |
| **Data quality enforcement** | Registry team | Program lead | Transit operators | — |

**Notes:**

- "Registry team" \= the engineers/analysts building and operating the system  
- "Program lead" \= the person empowered to say "this meets the requirements"  
- On the compliance row, Caltrans as an institution holds the legislative mandate (AB 1599 says "the department shall create"), but day-to-day accountability sits with the program lead

**Agency involvement:**

The notes ask: *"Especially if any agencies are involved — what does that look like?"* Agencies are Responsible for compliance but Consulted during design and onboarding. Critical touchpoints:

1. **Design review** — does the ID format and guidance make sense to agencies with limited technical staff?  
2. **Stop matching validation** — agencies confirm "yes, our stop X is the same physical location as their stop Y" (or dispute it)  
3. **Onboarding support** — smaller agencies will need hands-on help (ties back to Section 2d — the support structure decision)

---

## 

## 

## 5\. Open Questions & Decisions Needed

The draft notes surfaced several questions that need resolution before Phase 1 design can lock in.

### 5a. GTFS extension or undocumented field?

*"Does ITP want to push a GTFS extension for this, or use an undocumented extension (just a custom field thrown in)? Apple, Transit already interested."*

| Approach | Pros | Cons |
| :---- | :---- | :---- |
| **GTFS extension** (propose to spec) | Legitimate, future-proof, other states could adopt | Slow — spec proposal, community buy-in, adoption timeline. Won't land by Jun 2027 |
| **Undocumented custom field** (e.g., `stop_ca_universal_id`) | Fast to deploy. Apple/Transit can consume immediately | Risk of collision if GTFS later standardizes something similar |
| **Entur's approach** — GTFS as downstream export, NeTEx as canonical | Sidesteps the GTFS question entirely. Universal ID lives in the canonical format | Requires agencies to adopt or Cal-ITP to generate GTFS on their behalf |

### 

### 

### 

### 

### 

### 5b. Universal ID format

The notes converge on assigned IDs (Entur-style), not derived IDs (geohash). Open sub-questions:

| Approach | Example | Pros | Cons |
| :---- | :---- | :---- | :---- |
| **Simple integer** | `CAT:StopPlace:1` | Easiest to generate and reason about | Reveals creation order and total count |
| **Hashed/opaque** | `CAT:StopPlace:XK92B` | Hides cardinality | Harder to debug, sort, reason about |
| **Entur's gap-less integer** | `NSR:StopPlace:414` | Dense, sortable | Requires Hazelcast/PostgreSQL machinery for a constraint we don't share |

### 

### 5c. New stop creation — who assigns the ID?

*"If a new stop is added — can they calculate the universal ID on their own? Or does Cal-ITP need to do it for them?"*

| Approach | Pros | Cons |
| :---- | :---- | :---- |
| **Central assignment** (Cal-ITP issues IDs) | Guarantees uniqueness, single source of truth | Bottleneck if agencies add stops frequently |
| **Pre-allocated ranges** (each agency gets a block) | Agencies self-serve within their range | Coordination overhead, gaps, what happens when ranges exhaust |
| **Derived ID** (hash of agency \+ stop\_id) | Fully decentralized | Not a true universal ID — two agencies at same stop produce different IDs |

### Phased Approach

**Phase 1: Design & Prototype (now – Aug 2026\)**

- ID system design — format, generation approach, claiming rules. Reference: [Entur ID system](http://../research/entur-nsr/id-system-and-model.md)  
- Data model finalized — building on [transit-amenity-atlas schema](https://github.com/cal-itp/transit-amenity-atlas/blob/main/schema.md), adding versioning and ID mapping. Reference: [Entur data model](http://../research/entur-nsr/id-system-and-model.md#part-2-data-model-class-hierarchy)  
- Canonical format decision — GTFS extension vs. NeTEx vs. custom. Draft notes: "Does ITP want to push a GTFS extension for this, or use an undocumented extension? Apple, Transit already interested"  
- Initial stop ingestion prototype — can we match stops from 2-3 test agencies?  
- Test case generation — the "near but distinct" and "should be combined" cases from draft notes

**Phase 2: Build & Initial Population (Sep – Nov 2026\)**

- Registry infrastructure built and deployed  
- Bulk import of existing GTFS stops from all TDA-funded operators (sourcing from [Cal-ITP warehouse](https://dbt-docs.dds.dot.ca.gov/#!/model/model.calitp_warehouse.dim_stops_latest), using transit-amenity-atlas schema as reference)  
- First-pass stop matching and deduplication. Reference: [Entur import types](http://../research/entur-nsr/README.md#3-import-strategy--handle-bad-data) (INITIAL, MERGE, ID\_MATCH, MATCH)  
- ID mapping table populated  
- API and bulk download available

**Phase 3: Agency Onboarding (Dec 2026 – May 2027\)**

- Guidance documentation published  
- Support structure in place  
- Agencies review their stop mappings, submit corrections  
- Data quality feedback loop — agencies flag issues, Cal-ITP resolves  
- Validation tooling — agencies can check their GTFS against the registry before publishing

**Phase 4: Compliance (Jun 2027+)**

- All TDA-funded operators using universal stop IDs in published datasets  
- Ongoing maintenance — new stops, changes, decommissions  
- Longitudinal analysis becomes possible (draft notes: "ridership analysis", "analysis if things moved")

**Key dependencies:**

- Phase 2 depends on getting GTFS data from all agencies (some may not have it, or have poor quality — transit-amenity-atlas already surfaces this)  
- Agency onboarding timeline is tight — 6 months for 200+ operators to review and conform  
- The ID system design decision (Phase 1\) locks in the data model for everything else

**Biggest risk:** Phase 2's stop matching. Entur had to build four import types to handle inconsistent data from 60 operators. California has 200+. The Cal-ITP warehouse already surfaces the matching challenge: stops from different agencies cluster at the same physical location with different names, slightly different coordinates, or different attributions. This is where the draft notes' test cases become critical — "near but distinct" vs. "should be combined."

---

