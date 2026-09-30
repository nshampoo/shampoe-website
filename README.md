# shampoe.com

Personal site. A static page in `site/`, hosted on AWS with CDK in `infra/`.

- `shampoe.com` serves `site/` from a private S3 bucket through CloudFront.
- `shampoe.com/citibike/` is a page in `site/citibike/` with the site header over an iframe of `/citibike/app/`.
- `shampoe.com/citibike/app/` passes through to the Citi Bike Tides CloudFront distribution, so its live data stays live.
- `www.shampoe.com` redirects to `shampoe.com`.

## Deploy

```
cd infra
npm install
AWS_PROFILE=personal npx cdk deploy
```

Edit `site/` and re-run the deploy to publish changes.
