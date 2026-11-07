# Draft AB 1599 Agency Outreach Sample

**Status:** Draft for customer-success review; do not treat as an approved contact list.

This 10-agency draft is based on the user-provided
`ab1599-outreach-sample.md`. It replaces the Siskiyou County Transportation
Agency, Glenn County Transportation Commission, and Eastern Sierra Transit
Authority with similar small or rural operators, and replaces Culver CityBus
with Santa Monica. It is not a statistically representative sample or the
legally obligated operator roster. Reconcile legal status separately, as described in
[the implementation plan](./implementation-plan.md#83-onboarding-machinery), and
have customer success review the list before contacting agencies.

## Tier and capacity mapping

Agency tiers and size codes below come from the user-provided
`TDQ Agency Tiers with Agency Size.csv`. The requested tier-to-support mapping is
the starting point, with agency size used to account for staff capacity:

| Spreadsheet tier | Outreach grouping |
|---|---|
| B | High-touch |
| C | Medium-touch |
| A or D | Self-service when large; medium-touch when small or medium |

Small and medium agencies are not presumed to have staff capacity for self-service.
Size codes (S, M, L) are shown as listed in the spreadsheet. This is an
outreach-support mapping, not a statutory classification. The sample includes
one Tier B, two Tier C, three Tier A, and four Tier D agencies; the resulting
support mix is one high-touch, six medium-touch, and three self-service.

## Candidate agencies

| Agency | Tier | Agency size | Outreach grouping | GTFS build method (dataset evidence) | California region | Caltrans district | Why include |
|---|---:|---:|---|---|---|---:|---|
| Monterey Salinas Transit (MST) | A | L | Self-service | GTFS Schedule: MST and Cal-ITP listed as producers; GTFS-RT vehicle positions, trip updates, and alerts also listed. | Central Coast | 5 | Large agency suitable for self-service testing; ask how it and neighboring operators coordinate inventory and ongoing updates at shared transfer points. |
| Lake Transit Authority | C | S | Medium-touch | GTFS Schedule: data set producer shows as Trillium, may be out of date | North Coast | 1 | Small rural operator suited to test capacity for agencies where staff have multiple roles. |
| Trinity County | B | S | High-touch | GTFS Schedule: Trinity County and Via/Remix listed as producers; GTFS-RT: Swiftly listed. | North State | 2 |Tests hands-on support for a high touch small rural operator that has faced significant technical challenges with maintaining their GTFS and has reached out to us for support. |
| Sacramento Regional Transit District (SacRT) | A | L | Self-service | CSV lists a historic Folsom Stage GTFS Schedule produced by SacRT; current core-feed build method not established by that row. | Sacramento Valley | 3 | Large agency suited to self-service testing; its parent/child stop structures make it useful to examine how inventory and updates are coordinated across related services. |
| Yolo County Transportation District | C | S | Medium-touch | GTFS Schedule: Yolo County Transportation District listed as producer; GTFS-RT: TripSpark listed. | Sacramento Valley | 3 | Small regional operator suited to templates and office hours; clarify which stops the district maintains versus local or partner operators. |
| County of Nevada Transit Services Division | A | S | Medium-touch | No matching agency dataset row identified in the supplied GTFS datasets CSV; method unconfirmed. | Sierra foothills | 3 | Small size supports guided rather than self-service onboarding; determine whether the county or local partners own and update shared stop records. |
| Long Beach Transit | D | L | Self-service | GTFS Schedule: Long Beach Transit and Cal-ITP listed; GTFS-RT vehicle positions: agency listed, Vontas Cloud inferred from URI domain. | Los Angeles County | 7 | Large agency suitable for self-service and scale testing; ask how it coordinates shared urban stops and maintenance with Metro and neighboring operators. |
| City of Torrance (Torrance Transit) | D | M | Medium-touch | GTFS Schedule: City of Torrance listed; GTFS-RT: Swiftly and Clever Devices listed. | Los Angeles County | 7 | Medium size fits guided support; use templates to clarify inventory and amenity reporting and responsibility for stops shared with Metro or nearby operators. |
| City of Santa Monica (Big Blue Bus) | D | M | Medium-touch | GTFS Schedule: City of Santa Monica and Cal-ITP listed; GTFS-RT feeds list Swiftly and Clever Devices. | Los Angeles County | 7 | Medium size fits guided support; its dense network can test stop verification and clarify who maintains locations shared with Metro or neighboring operators. |
| City of Gardena (GTrans) | D | S | Medium-touch | GTFS Schedule: City of Gardena and Trillium listed; GTFS-RT: agency listed. | Los Angeles County | 7 | Small size warrants a named contact and templates; test capacity to validate stop details and coordinate shared-stop updates with Metro or nearby operators. |

This revision retains the non-replaced agencies from the supplied sample,
replaces the three named rural agencies and swaps Culver CityBus for Santa Monica.
The shared-stop responsibilities in the suitability notes are questions for
outreach, not claims about existing arrangements. Caltrans districts indicate
primary service areas. Confirm service boundaries and current agency records
during customer-success review.

The build-method column summarizes matching rows in the supplied GTFS datasets
CSV. GTFS Schedule denotes static schedule data; GTFS-RT denotes real-time feeds.
Producer names may identify a publisher or vendor, not the system or staff that
authored the feed. A vendor not named in the CSV is not assumed; any URI-based
inference is labeled, and missing records are marked unconfirmed.

## What to test in outreach

Use the same core questions with each agency, adjusting the level of assistance to
the mapped support group:

- Where is the agency's current stop inventory maintained, and which published
  datasets contain stop information?
- Who can confirm stop names and locations and provide seating and shelter data?
- How would the agency associate the registry identifier with its stops in GTFS
  and other stop datasets without replacing its own stop identifiers?
- What data, vendor help, or staff effort would be needed, and what follow-up
  support would make the work feasible?

High-touch outreach should offer hands-on help with inventory and data collection;
medium-touch outreach should offer templates and a named contact; self-service
outreach should provide documentation and validation tools, then gather feedback
on gaps. Keep statutory requirements distinct from optional registry improvements.
