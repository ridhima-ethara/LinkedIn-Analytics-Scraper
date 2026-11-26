# LinkedIn Page Analytics — Extracted vs Unavailable Report

- **Page:** LOCAL FIXTURE (tests/fixture_analytics.html)
- **Run id:** offline-fixture-run
- **Started (UTC):** 2026-11-25T11:55:16+00:00
- **Finished (UTC):** 2026-11-25T11:55:16+00:00
- **Date range applied (read back from LinkedIn):** 01/01/2026 - 11/25/2026
- **Date window requested:** 2026-01-01 .. 2026-11-25 — **VERIFIED**
- **Window check:** LinkedIn displays 2026-01-01 .. 2026-11-25, matching the requested 2026-01-01 .. 2026-11-25 (within 2 day(s)).
- **Authenticated session:** n/a (local fixture, no LinkedIn access)
- **Browser:** Playwright  / Firefox (headless=True)

## Summary

| Requested metrics | Extracted | Partial | Not accessible | Extra breakdown rows |
|---|---|---|---|---|
| 38 | 32 | 0 | 6 | 34 |


### By category

| Category | Extracted | Partial | Not accessible |
|---|---|---|---|
| Overview | 4 | 0 | 0 |
| Content | 3 | 0 | 1 |
| Visitors | 3 | 0 | 0 |
| Visitors > Demographics | 1 | 0 | 4 |
| Life Page | 3 | 0 | 0 |
| Followers | 2 | 0 | 0 |
| Search Appearance | 2 | 0 | 1 |
| Individual Post Analytics | 11 | 0 | 0 |
| Video Posts | 3 | 0 | 0 |


### Reasons for incomplete metrics

| Limitation | Count | Meaning |
|---|---|---|
| data_unavailable | 2 | Data unavailable: the section loaded but LinkedIn itself reports no data for the selected date range / post type. |
| linkedin_ui | 4 | LinkedIn UI limitation: the metric is not rendered in the accessible admin interface (or LinkedIn changed/removed that element). |


## 1. Successfully extracted

| Category | Metric | Value | Unit | Date range | Source section |
|---|---|---|---|---|---|
| Overview | Search Appearances | 1200 | count | 01/01/2026 - 11/25/2026 | Page Analytics > Overview |
| Overview | New Followers | 214 | count | 01/01/2026 - 11/25/2026 | Page Analytics > Overview |
| Overview | Post Impressions | 45901 | count | 01/01/2026 - 11/25/2026 | Page Analytics > Overview |
| Overview | Page Visitors | 2045 | count | 01/01/2026 - 11/25/2026 | Page Analytics > Overview |
| Content | Reactions | 1004 | count | 01/01/2026 - 11/25/2026 | Page Analytics > Content |
| Content | Comments | 87 | count | 01/01/2026 - 11/25/2026 | Page Analytics > Content |
| Content | Reposts | 22 | count | 01/01/2026 - 11/25/2026 | Page Analytics > Content |
| Visitors | Page Views | 7129 | count | 01/01/2026 - 11/25/2026 | Page Analytics > Visitors |
| Visitors | Unique Visitors | 2045 | count | 01/01/2026 - 11/25/2026 | Page Analytics > Visitors |
| Visitors | Custom Button Clicks | 38 | count | 01/01/2026 - 11/25/2026 | Page Analytics > Visitors |
| Visitors > Demographics | Job Function | 3 | buckets | 01/01/2026 - 11/25/2026 | Page Analytics > Visitors > Visitor demographics |
| Life Page | Page Views | 1220 | count | 01/01/2026 - 11/25/2026 | Page Analytics > Visitors > Page views by page |
| Life Page | Unique Visitors | 480 | count | 01/01/2026 - 11/25/2026 | Page Analytics > Visitors > Page views by page |
| Life Page | Last Updated | Nov 12, 2026 | date | 01/01/2026 - 11/25/2026 | Page Analytics > Visitors > Page views by page |
| Followers | Total Followers | 13204 | count | 01/01/2026 - 11/25/2026 | Page Analytics > Followers |
| Followers | New Followers | 214 | count | 01/01/2026 - 11/25/2026 | Page Analytics > Followers |
| Search Appearance | Page Searches | 1200 | count | 01/01/2026 - 11/25/2026 | Page Analytics > Search appearances |
| Search Appearance | Top Page Searcher Demographics | 3 | buckets | 01/01/2026 - 11/25/2026 | Page Analytics > Search appearances |
| Individual Post Analytics | Impressions | 2 | posts | per post (see detail.per_post) | Page Analytics > Content > Post analytics |
| Individual Post Analytics | Members Reached | 2 | posts | per post (see detail.per_post) | Page Analytics > Content > Post analytics |
| Individual Post Analytics | Page Viewers from This Post | 2 | posts | per post (see detail.per_post) | Page Analytics > Content > Post analytics |
| Individual Post Analytics | Followers Gained from This Post | 2 | posts | per post (see detail.per_post) | Page Analytics > Content > Post analytics |
| Individual Post Analytics | Engagement | 2 | posts | per post (see detail.per_post) | Page Analytics > Content > Post analytics |
| Individual Post Analytics | Engagement Rate | 2 | posts | per post (see detail.per_post) | Page Analytics > Content > Post analytics |
| Individual Post Analytics | Clicks | 2 | posts | per post (see detail.per_post) | Page Analytics > Content > Post analytics |
| Individual Post Analytics | Click Through Rate | 2 | posts | per post (see detail.per_post) | Page Analytics > Content > Post analytics |
| Individual Post Analytics | Reactions | 2 | posts | per post (see detail.per_post) | Page Analytics > Content > Post analytics |
| Individual Post Analytics | Comments | 2 | posts | per post (see detail.per_post) | Page Analytics > Content > Post analytics |
| Individual Post Analytics | Reposts | 2 | posts | per post (see detail.per_post) | Page Analytics > Content > Post analytics |
| Video Posts | Video Views | 2 | posts | per post (see detail.per_post) | Page Analytics > Content > Post analytics (video) |
| Video Posts | Watch Time | 2 | posts | per post (see detail.per_post) | Page Analytics > Content > Post analytics (video) |
| Video Posts | Average Watch Time | 2 | posts | per post (see detail.per_post) | Page Analytics > Content > Post analytics (video) |


## 2. Partially extracted

_none_


## 3. Not accessible

| Category | Metric | Limitation | Exact reason | Source URL |
|---|---|---|---|---|
| Content | Impressions | data_unavailable | LinkedIn shows an empty state on this section ('No data available for the selected date range'), so no value is rendered for label(s) ['Impressions', 'Total impressions']. | file:///Users/macbookpro/Documents/LinkedIn%20Analytics%20scrape/tests/fixture_analytics.html |
| Visitors > Demographics | Company Size | linkedin_ui | The visitor-demographics selector did not offer 'Company size' (tried: ['Company size', 'Company sizes']). | file:///Users/macbookpro/Documents/LinkedIn%20Analytics%20scrape/tests/fixture_analytics.html |
| Visitors > Demographics | Industry | linkedin_ui | The visitor-demographics selector did not offer 'Industry' (tried: ['Industry', 'Industries']). | file:///Users/macbookpro/Documents/LinkedIn%20Analytics%20scrape/tests/fixture_analytics.html |
| Visitors > Demographics | Location | linkedin_ui | The visitor-demographics selector did not offer 'Location' (tried: ['Location', 'Locations']). | file:///Users/macbookpro/Documents/LinkedIn%20Analytics%20scrape/tests/fixture_analytics.html |
| Visitors > Demographics | Seniority | linkedin_ui | The visitor-demographics selector did not offer 'Seniority' (tried: ['Seniority', 'Seniority level']). | file:///Users/macbookpro/Documents/LinkedIn%20Analytics%20scrape/tests/fixture_analytics.html |
| Search Appearance | Top Keywords | data_unavailable | No keyword list rendered; LinkedIn empty state: 'No data available for the selected date range'. | file:///Users/macbookpro/Documents/LinkedIn%20Analytics%20scrape/tests/fixture_analytics.html |


## Section navigation outcomes

| Section | Outcome | URL | Reason |
|---|---|---|---|
| overview | ok | file:///Users/macbookpro/Documents/LinkedIn%20Analytics%20scrape/tests/fixture_analytics.html | - |
| content | ok | file:///Users/macbookpro/Documents/LinkedIn%20Analytics%20scrape/tests/fixture_analytics.html | - |
| visitors | ok | file:///Users/macbookpro/Documents/LinkedIn%20Analytics%20scrape/tests/fixture_analytics.html | - |
| life_page | ok | file:///Users/macbookpro/Documents/LinkedIn%20Analytics%20scrape/tests/fixture_analytics.html | - |
| followers | ok | file:///Users/macbookpro/Documents/LinkedIn%20Analytics%20scrape/tests/fixture_analytics.html | - |
| search_appearances | ok | file:///Users/macbookpro/Documents/LinkedIn%20Analytics%20scrape/tests/fixture_analytics.html | - |
| posts | ok | file:///Users/macbookpro/Documents/LinkedIn%20Analytics%20scrape/tests/fixture_analytics.html | - |


## Run notes

- [overview] date-window check: LinkedIn displays 2026-01-01 .. 2026-11-25, matching the requested 2026-01-01 .. 2026-11-25 (within 2 day(s)).
- [content] post performance table captured: 2 row(s), 2 with a resolvable post URN
- [life_page] reusing tables captured on the Visitors tab
- [posts] date window 2026-01-01 .. 2026-11-25: 2 post(s) inside, 0 excluded, 0 with an unparseable date (kept)
- [posts] opening individual analytics for 2 of 2 in-scope post(s) (2 listed, extraction.max_posts=2)
- [posts] NOTE: LinkedIn reports post-level metrics cumulatively since each post was published and does not filter them by date range; the window only selects WHICH posts are opened. Each metric's date_range records what the post page displayed.


## Limitation legend

- **none** — No limitation — value captured from the live page.
- **linkedin_ui** — LinkedIn UI limitation: the metric is not rendered in the accessible admin interface (or LinkedIn changed/removed that element).
- **permissions** — Permissions limitation: the signed-in account's role on this Page does not grant access to that section.
- **data_unavailable** — Data unavailable: the section loaded but LinkedIn itself reports no data for the selected date range / post type.
- **automation_failure** — Automation failure: navigation or parsing in this script failed — re-runnable.
- **session_expired** — Session limitation: the authenticated LinkedIn session expired or was challenged mid-run; re-authenticate with login.py and re-run.
- **not_attempted** — Not attempted: the section was disabled or never reached in this run.

---
_No value in this report is estimated, inferred or back-filled: every number was read from the rendered LinkedIn page, and anything that could not be read is listed above with its reason._
