# shampoe.com design

## Goal

A personal site that shows the tools I've built (the workshop) and a live "dashboard of randomness" fed by things I build and do.

## Data sources

The live feed Lambda writes `/live.json` every 15 minutes from GitHub, Goodreads (a CSV export saved to SSM), Citi Bike Tides, Volo, Strava, and AWS Cost Explorer. Each source is optional.

## AWS cost tile

Shows the whole account's spend: this month so far, and the total over the last 13 months (Cost Explorer's default history).

- One `GetCostAndUsage` call (monthly, `UnblendedCost`) returns both numbers.
- Cost Explorer charges $0.01 per call. At the feed's 15-minute pace that is about 2,900 calls, or $29 a month. The feed reuses the cost in the previous `live.json` until the UTC day changes, so it makes about 30 calls a month ($0.30).
- AWS refreshes cost data a few times a day, so a daily number is at most about a day behind the console.

## Feed health

A source that fails just disappears from the page, which is how Goodreads was down for 5 days before anyone noticed.

- Each run carries forward every source's `ok` and `since` from the previous `live.json`. The Feed health tile lists them, down first.
- After 2 hours down, the feed emails once through SNS, and again on recovery. Short outages stay quiet. Error text goes only in the email, never in the public `live.json`.
- The feed tracks this itself instead of using a CloudWatch alarm per source: 6 alarms, and a source that stays down keeps its alarm red and hides new failures.
- One CloudWatch alarm on the Lambda's errors (missing data counts as failing) covers the feed itself breaking or not running.
- Cost: SNS email is free for the first 1,000 a month; one standard alarm is $0.10 a month at most.

## Goodreads

Goodreads stopped serving its RSS feeds (404) on 2026-10-27, even for a logged-in owner. `scripts/goodreads.py` reads the Export Library CSV and saves only what the tile shows to SSM (about 1 KB), so reviews, notes, and the to-read shelf stay private and deploys can't wipe it. Covers come from Open Library by ISBN, since the export has no cover URLs. "Books read" now counts the read shelf; the old number came from the profile page, which counts every shelf.

## Decided

- 2026-11-01: AWS cost covers the whole account, not just this site, and refreshes once a day.
- 2026-11-01: Feed health tile for every source, broken first; email an address kept in SSM after 2 hours down.
- 2026-11-01: Goodreads comes from a manual CSV export, since the RSS feeds are gone. Scraping shelf pages was too fragile.
- 2026-11-01: Show `UnblendedCost`: the full cost of what was used, however it was paid for (card or credits).

## Open decisions

- The total stops being all-time once the account is older than 13 months.
