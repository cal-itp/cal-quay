# Meeting Notes: LA Metro Stop Amenities Data Discussion

**Date:** November 4, 2026
**Attendees:**
- Vivek Bansal, Caltrans
- Benjamin Perez, Caltrans
- Nina Kin, Senior Manager of Systems Projects (Digital Experience), LA Metro

---

## 1. Southern California Outreach Candidates

Nina suggested these smaller agencies as possible next contacts:
- Long Beach
- Culver City Bus
- Gardena
- Torrance

## 2. LA Metro's Current GTFS Practices

- LA Metro checks its GTFS feeds with the MobilityData validator.
- Nina thinks a **separate stop amenities file** may be easier for Metro than adding fields to existing GTFS files.
- LA Metro has **over 12,000 stops**.

## 3. Stop Inventory and Ownership Challenges

- **No bus stop management process:** auditing and inventorying stops is an unsolved problem at LA Metro.
- **Stops are not managed in HASTUS.**
- **Spreadsheets:** the Stops and Zones department tracks physical bus stops in spreadsheets. Importing them into a database would be hard but possible, and it isn't an ideal solution.
- **Cities own the stops:** LA Metro doesn't own or maintain them, so it has little control over the amenity inventory.
- **Getting the data:** Metro has to contact each city for amenity information, and some cities may not track it at all.

### Key Hurdle: Liability Without Control
LA Metro could be held liable for the accuracy of stop amenity data, even though the cities maintain the amenities.

### Political Context
Incoming LA leadership wants a more proactive approach. Even so, any improvement still depends on the cities taking part.

## 4. Caltrans Database as a Central Repository

- **Vivek:** proposed making the Caltrans database the central repository for stop amenity data.
- **Nina:** asked whether cities could send data directly to Caltrans.
- **Vivek:** yes. Cities could log in with their email address and update their own records.
- **Considerations raised by Nina:**
  - Whether this works will depend on each city's technical capacity.
  - Cities would need LA Metro's stop IDs to match their records against.

## 5. Parent/Child Stops and Stop Clusters

- **Question:** how are parent and child stops handled for stop cluster groups?
- **Vivek:** Caltrans enters these by hand.
- **Nina:**
  - LA Metro's CAD/AVL system has no child stops. The software broke when Metro tried to load that data.
  - Metro wants to update its data to be compliant.

## 6. Unreferenced Stops in `stops.txt`

- **Nina:** unsure whether stops that appear in `stops.txt` but aren't used by any trip would break validation.
- **Vivek:** also unsure.
- **Nina:** asked whether stops must be tied to routes.
- **Vivek:** doesn't believe they need to be.
- **Takeaway:** if stops don't have to be tied to routes, LA Metro could track all stops (including amenity-only records) without causing validation errors.

---

## Open Questions
1. Does the MobilityData validator flag stops in `stops.txt` that no trip uses? If so, is it a warning or an error?
2. What is the most efficient way for cities to submit stop ID data?  Working through parent agencies like LA Metro? Or direct contact?
3. How would QA/QC of amenity data accuracy be split between LA Metro, the cities and Caltrans?
4. Could a separate stop amenities file be easier for agencies to comply with than extending existing GTFS files as suggested by Nina?

## Proposed Next Steps
| # | Action | Owner |
|---|--------|-------|
| 1 | Confirm how the validator treats unreferenced stops | Caltrans |
| 2 | Verify whether Long Beach, Culver City, Gardena, and Torrance meet the criteria for initial test outreach | Caltrans |
| 3 | Scope out an agency facing login and update process for a centralized stop registry data repository a Caltrans | Caltrans |
| 4 | If necessary, determine how difficult it would be to import data from the physical stop inventory maintained by LA Metro Stops and Zones Dept| Caltrans |
