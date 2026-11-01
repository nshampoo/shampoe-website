# shampoe.com design

## Goal

A personal site that shows the tools I've built (the workshop) and a live "dashboard of randomness" fed by things I build and do.

## Data sources

The live feed Lambda writes `/live.json` every 15 minutes from GitHub, Goodreads, Citi Bike Tides, Volo, Strava, and AWS Cost Explorer. Each source is optional.

## AWS cost tile

Shows the whole account's spend: this month so far, and the total over the last 13 months (Cost Explorer's default history).

- One `GetCostAndUsage` call (monthly, `UnblendedCost`) returns both numbers.
- Cost Explorer charges $0.01 per call. At the feed's 15-minute pace that is about 2,900 calls, or $29 a month. The feed reuses the cost in the previous `live.json` until the UTC day changes, so it makes about 30 calls a month ($0.30).
- AWS refreshes cost data a few times a day, so a daily number is at most about a day behind the console.

## Decided

- 2026-11-01: AWS cost covers the whole account, not just this site, and refreshes once a day.
- 2026-11-01: Show `UnblendedCost`: the full cost of what was used, however it was paid for (card or credits).

## Open decisions

- The total stops being all-time once the account is older than 13 months.
