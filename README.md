# shampoe.com

Personal site. A static page in `site/`, hosted on AWS with CDK in `infra/`.

- `shampoe.com` serves `site/` from a private S3 bucket through CloudFront.
- Apps hosted on their own CloudFront (listed in `infra/bin/infra.ts`) appear under the site header:
  - `shampoe.com/<app>/` is a page in `site/<app>/` with the header over an iframe of `/<app>/app/`.
  - `shampoe.com/<app>/app/` passes through to that app's CloudFront, so its deploys show up here live.
  - Current apps: `citibike` (Citi Bike Tides) and `volo` (Volo Drop-in Alerts; password is its invite code).
- `www.shampoe.com` redirects to `shampoe.com`.

## Deploy

```
cd infra
npm install
AWS_PROFILE=personal npx cdk deploy
```

Edit `site/` and re-run the deploy to publish changes.

## TODO

- [ ] Add Tomo
- [ ] Add the Citi Bike Parking app (`~/Code/citibike-parking`). It's an iOS app, not a web page on CloudFront, so it probably gets its own page in `site/` rather than an entry in `infra/bin/infra.ts`.
