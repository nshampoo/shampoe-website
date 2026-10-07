#!/usr/bin/env node
import * as cdk from 'aws-cdk-lib/core';
import { SiteStack } from '../lib/site-stack';

const app = new cdk.App();

// us-east-1 is required: CloudFront only accepts ACM certificates from that region.
new SiteStack(app, 'PersonalSite', {
  env: { account: '404933715334', region: 'us-east-1' },
  tags: { project: 'personal-website' },
  domainName: 'shampoe.com',
  hostedZoneId: 'Z05164909E60W3KXYNYM',
  apps: {
    citibike: 'd2g10dtmnepqv0.cloudfront.net', // Citi Bike Tides (~/Code/citibike-migration)
    volo: 'd1wfj80t6mlo6z.cloudfront.net', // Volo Drop-in Alerts (~/Code/volo-notification-service)
    epicPlanning: 'doccazxgqqfry.cloudfront.net', // Epic Weekend Planner (~/Code/nyc-skiing-calculator)
  },
});
