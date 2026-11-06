# Draft AB 1599 Agency Outreach Sample 

**Status:** Draft for customer-success review; do not treat as an approved contact list.

This is a 10-agency draft for testing AB 1599 stop-data outreach
and collection. It retains the four requested Southern California agencies and
selects six different agencies for geographic coverage elsewhere in California.
It is not a statistically representative sample or the legally obligated operator
roster. Reconcile legal status separately, as described in
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
one Tier B, three Tier C, and six Tier A/D agencies; the resulting support mix is
one high-touch, eight medium-touch, and one self-service.

## Candidate agencies

| Agency | Tier | Agency size | Outreach grouping | California region | Caltrans district | Why include |
|---|---:|---:|---|---|---:|---|
| Monterey Salinas Transit (MST) | A | L | Self-service | Central Coast | 5 | Tests self-service with a large agency and adds a major Central Coast service area. |
| Siskiyou County Transportation Agency | C | S | Medium-touch | Far North | 2 | Highly responsive small rural agency that will have GTFS RT adoption by the end of the year. Tests guided support with a highly engaged small rural county agency. |
| Trinity County | B | S | High-touch | North State | 2 | Tests hands-on support for a high touch small rural operator that has faced significant technical challenges with maintaining their GTFS and has reached out to us for support. |
| Sacramento Regional Transit District (SacRT) | A | L | Self-service | Sacramento Valley | 3 | Tests self-service with a large urban operator with several parent and child organization transit stops. |
| Glenn County Transportation Commission | C | S | Medium-touch | Sacramento Valley / North State | 3 | Has expressed interest in stop ammenity inventory in previous discussions. Adds a small rural agency in the northern Sacramento Valley. |
| Eastern Sierra Transit Authority | C | S | Medium-touch | Eastern Sierra | 9 | Extends coverage to the eastern side of the state and a remote service area. |
| Long Beach Transit | D | L | Self-service | Los Angeles County | 7 | Suggested outreach target from LA Metro contact; large size supports the self-service test. |
| City of Torrance (Torrance Transit) | D | M | Medium-touch | Los Angeles County | 7 | Suggested outreach target from LA Metro contact; medium size suggests guided support. |
| City of Culver City (Culver CityBus) | D | S | Medium-touch | Los Angeles County | 7 | Suggested outreach target from LA Metro contacts; small size warrants staff support. |
| City of Gardena (GTrans) | D | S | Medium-touch | Los Angeles County | 7 | Suggested outreach target from LA Metro contact; small size warrants staff support. |

This revised draft replaces all six non-Southern-California agencies from the
previous sample, retains all four requested Southern California agencies, and
includes three Far North agencies. Caltrans districts indicate the agencies'
primary service areas. The list should be checked against current
technology-stack and service records during customer-success review.

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
