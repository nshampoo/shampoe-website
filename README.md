# shampoe.com

Personal site: a workshop of the tools I've built, a live "dashboard of randomness", and an About page. Static HTML in `site/`, hosted on AWS with CDK in `infra/`.

## Layout

| Path | What |
| --- | --- |
| `site/index.html` | Workshop (homepage): intro, live strip, tool cards |
| `site/<tool>/` | How-and-why page per tool (`citibike`, `tomo`, `volo`, `park-it`, `this-site`, `epicPlanning`), using `story.css` |
| `site/citibike/open/`, `site/volo/open/`, `site/epicPlanning/open/` | The tool itself under the site header (iframe of `/<tool>/app/`) |
| `site/live/` | Live page; `live.js` renders `/live.json` there and on the homepage |
| `site/about/` | About page (photos in `site/img/about/`) |
| `partials/` | Shared header and footer; copy into every page with `node scripts/sync-chrome.mjs` |
| `live-feed/handler.py` | Lambda that writes `/live.json` every 15 minutes |
| `infra/` | CDK stack: S3, CloudFront (+ router function), ACM, Route 53, live feed |

## How requests are routed

- `shampoe.com` serves `site/` from a private S3 bucket through CloudFront; `www` redirects to it.
- `/<app>/app/*` passes through to that app's own CloudFront (listed in `infra/bin/infra.ts`), so its deploys show up here live.
- Paths without a trailing slash get one (`/about` -> `/about/`), and missing pages show `404.html`.

## Live data

`live-feed/handler.py` gathers GitHub pushes, Goodreads books, Citi Bike Tides stats, Volo daily drop-in counts (DynamoDB table named in SSM at `/volo-notifier/stats-table`), and Strava. Each source is optional.

Strava needs credentials in SSM at `/shampoe-site/strava` (SecureString JSON with `client_id`, `client_secret`, `refresh_token`). Run maps drop the first and last 400 m; only slow "Flag Football" activities count as games.

## Deploy

```
cd infra
npm install
AWS_PROFILE=personal npm run deploy
```

`npm run deploy` first runs `scripts/order-projects.mjs`, which orders the workshop rows newest first by each row's GitHub repo (`data-repo`) creation date, then deploys. Commit `site/index.html` if it reordered anything.

After editing `partials/`, run `node scripts/sync-chrome.mjs` before deploying.

## TODO

- [x] Add Tomo
- [x] Volo: per-day drop-in counts (total + flag football) charted on the Live page
- [x] Connect Strava (API app + credentials in SSM)
- [x] Resume PDF at `site/resume.pdf`
- [ ] Backburner: Spotify "now playing" on the Live page (needs a Spotify developer app)
- [x] Add the Citi Bike Parking app (Park It) as its own page
