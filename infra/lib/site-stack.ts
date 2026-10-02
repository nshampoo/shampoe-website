import * as path from 'path';
import * as cdk from 'aws-cdk-lib/core';
import * as acm from 'aws-cdk-lib/aws-certificatemanager';
import * as cloudfront from 'aws-cdk-lib/aws-cloudfront';
import * as events from 'aws-cdk-lib/aws-events';
import * as targets from 'aws-cdk-lib/aws-events-targets';
import * as iam from 'aws-cdk-lib/aws-iam';
import * as lambda from 'aws-cdk-lib/aws-lambda';
import * as logs from 'aws-cdk-lib/aws-logs';
import * as origins from 'aws-cdk-lib/aws-cloudfront-origins';
import * as route53 from 'aws-cdk-lib/aws-route53';
import * as r53targets from 'aws-cdk-lib/aws-route53-targets';
import * as s3 from 'aws-cdk-lib/aws-s3';
import * as s3deploy from 'aws-cdk-lib/aws-s3-deployment';
import { Construct } from 'constructs';

export interface SiteStackProps extends cdk.StackProps {
  domainName: string;
  hostedZoneId: string;
  /**
   * Apps hosted on their own CloudFront, by name: `{ citibike: 'dxxxx.cloudfront.net' }` serves that
   * distribution at /citibike/app/, which the page site/citibike/ embeds under the header.
   */
  apps: Record<string, string>;
}

/**
 * shampoe.com
 *
 *   shampoe.com, www.shampoe.com ──> CloudFront (HTTPS)
 *     ├─ /<app>/app/*    ──> that app's own CloudFront (prefix stripped), e.g. Citi Bike Tides, Volo
 *     └─ everything else ──> site bucket (private; uploaded from site/ by `cdk deploy`)
 *
 * /<app>/ is a page in site/ that shows the header over an iframe of /<app>/app/, so each app keeps
 * deploying on its own and shows up here live.
 *
 * www redirects to the bare domain.
 */
export class SiteStack extends cdk.Stack {
  constructor(scope: Construct, id: string, props: SiteStackProps) {
    super(scope, id, props);

    const { domainName } = props;
    const wwwName = `www.${domainName}`;

    const zone = route53.HostedZone.fromHostedZoneAttributes(this, 'Zone', {
      hostedZoneId: props.hostedZoneId,
      zoneName: domainName,
    });

    const certificate = new acm.Certificate(this, 'Cert', {
      domainName,
      subjectAlternativeNames: [wwwName],
      validation: acm.CertificateValidation.fromDns(zone),
    });

    const site = new s3.Bucket(this, 'Site', {
      blockPublicAccess: s3.BlockPublicAccess.BLOCK_ALL, // public access goes through CloudFront only
      encryption: s3.BucketEncryption.S3_MANAGED,
      enforceSSL: true,
      removalPolicy: cdk.RemovalPolicy.DESTROY,
      autoDeleteObjects: true, // everything here is rebuilt from site/
    });

    // Runs on every request:
    //   www -> bare domain
    //   /<app>, /<app>/app -> add the trailing slash (so the app's relative fetches resolve under it)
    //   /<app>/app/x -> /x for that app's origin
    //   any other path ending in / -> its index.html in the bucket
    //   a path with no file extension (/about) -> add the trailing slash
    // Redirects keep the query string, so invite links like /volo/?invite=... survive.
    // The cache key uses the rewritten path, so /citibike/app/ and / would share one cache entry;
    // the x-site header (keyed on by appCache below) keeps them apart.
    const router = new cloudfront.Function(this, 'Router', {
      runtime: cloudfront.FunctionRuntime.JS_2_0,
      code: cloudfront.FunctionCode.fromInline(`
var APPS = ${JSON.stringify(Object.keys(props.apps))};
function redirect(req, uri) {
  var qs = Object.keys(req.querystring).map(function (k) {
    var v = req.querystring[k].value;
    return v === '' ? k : k + '=' + v;
  }).join('&');
  var location = uri + (qs ? '?' + qs : '');
  return { statusCode: 301, statusDescription: 'Moved Permanently', headers: { location: { value: location } } };
}
function handler(event) {
  var req = event.request;
  if (req.headers.host && req.headers.host.value === '${wwwName}') return redirect(req, 'https://${domainName}' + req.uri);
  var m = req.uri.match(/^\\/([a-z0-9-]+)(\\/app)?(\\/.*)?$/);
  if (m && APPS.indexOf(m[1]) >= 0) {
    if (!m[3]) return redirect(req, req.uri + '/');
    if (m[2]) {
      req.uri = m[3];
      req.headers['x-site'] = { value: m[1] };
      return req;
    }
  }
  if (req.uri.endsWith('/')) {
    req.uri += 'index.html';
    return req;
  }
  var last = req.uri.slice(req.uri.lastIndexOf('/') + 1);
  if (last.indexOf('.') === -1) return redirect(req, req.uri + '/');
  return req;
}`),
    });
    const functionAssociations = [{ function: router, eventType: cloudfront.FunctionEventType.VIEWER_REQUEST }];

    // Like CACHING_OPTIMIZED, plus the x-site header in the cache key. Default TTL 0: a file with no
    // Cache-Control isn't held here (its own CloudFront still caches it), so an app's deploys show up
    // without invalidating this distribution. Citi Bike sets Cache-Control, so it's still cached.
    const appCache = new cloudfront.CachePolicy(this, 'AppCache', {
      headerBehavior: cloudfront.CacheHeaderBehavior.allowList('x-site'),
      defaultTtl: cdk.Duration.seconds(0),
      enableAcceptEncodingGzip: true,
      enableAcceptEncodingBrotli: true,
    });

    // No origin request policy, so the Host header becomes the app's CloudFront domain, which it requires.
    const additionalBehaviors: Record<string, cloudfront.BehaviorOptions> = {};
    for (const [name, appDomain] of Object.entries(props.apps)) {
      additionalBehaviors[`/${name}/app/*`] = {
        origin: new origins.HttpOrigin(appDomain, { protocolPolicy: cloudfront.OriginProtocolPolicy.HTTPS_ONLY }),
        viewerProtocolPolicy: cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
        compress: true,
        cachePolicy: appCache,
        functionAssociations,
      };
    }

    const distribution = new cloudfront.Distribution(this, 'Cdn', {
      comment: domainName,
      domainNames: [domainName, wwwName],
      certificate,
      defaultRootObject: 'index.html',
      defaultBehavior: {
        origin: origins.S3BucketOrigin.withOriginAccessControl(site),
        viewerProtocolPolicy: cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
        compress: true,
        cachePolicy: cloudfront.CachePolicy.CACHING_OPTIMIZED,
        functionAssociations,
      },
      additionalBehaviors,
      // Missing files come back from S3 as 403; show the site's own 404 page for both.
      errorResponses: [403, 404].map((httpStatus) => ({
        httpStatus,
        responseHttpStatus: 404,
        responsePagePath: '/404.html',
        ttl: cdk.Duration.minutes(1),
      })),
      priceClass: cloudfront.PriceClass.PRICE_CLASS_100, // North America + Europe edges: cheapest tier
    });

    new s3deploy.BucketDeployment(this, 'Deploy', {
      sources: [s3deploy.Source.asset(path.join(__dirname, '../../site'))],
      destinationBucket: site,
      cacheControl: [s3deploy.CacheControl.fromString('public, max-age=300')],
      // live.json is written by the live feed Lambda, not by deploys; excluding it also
      // keeps the deploy's cleanup step from deleting it.
      exclude: ['live.json'],
      distribution,
      distributionPaths: ['/*'],
    });

    // The Live page's data: every 15 minutes, gather GitHub, Goodreads, Citi Bike, Volo,
    // and Strava into /live.json. Each source is optional, so one failing never blanks the page.
    const liveFeed = new lambda.Function(this, 'LiveFeed', {
      runtime: lambda.Runtime.PYTHON_3_13,
      architecture: lambda.Architecture.ARM_64,
      handler: 'handler.handler',
      code: lambda.Code.fromAsset(path.join(__dirname, '../../live-feed'), { exclude: ['__pycache__'] }),
      memorySize: 512, // Citi Bike's hourly files add up to a few MB of JSON by evening
      timeout: cdk.Duration.minutes(1),
      environment: { BUCKET: site.bucketName },
      logGroup: new logs.LogGroup(this, 'LiveFeedLogs', {
        retention: logs.RetentionDays.ONE_MONTH,
        removalPolicy: cdk.RemovalPolicy.DESTROY,
      }),
    });
    site.grantPut(liveFeed, 'live.json');
    const param = (name: string) => cdk.Stack.of(this).formatArn({ service: 'ssm', resource: 'parameter', resourceName: name });
    liveFeed.addToRolePolicy(new iam.PolicyStatement({
      actions: ['ssm:GetParameter'],
      resources: [param('volo-notifier/stats-table'), param('shampoe-site/strava')],
    }));
    // Strava may rotate the refresh token, so the feed saves the new one back.
    liveFeed.addToRolePolicy(new iam.PolicyStatement({ actions: ['ssm:PutParameter'], resources: [param('shampoe-site/strava')] }));
    liveFeed.addToRolePolicy(new iam.PolicyStatement({
      actions: ['dynamodb:Scan'],
      resources: [cdk.Stack.of(this).formatArn({ service: 'dynamodb', resource: 'table', resourceName: 'VoloPoller-DropinStats*' })],
    }));
    new events.Rule(this, 'LiveFeedSchedule', {
      description: 'Refresh shampoe.com/live.json',
      schedule: events.Schedule.rate(cdk.Duration.minutes(15)),
      targets: [new targets.LambdaFunction(liveFeed, { retryAttempts: 0 })],
    });
    new cdk.CfnOutput(this, 'LiveFeedName', { value: liveFeed.functionName });

    const target = route53.RecordTarget.fromAlias(new r53targets.CloudFrontTarget(distribution));
    for (const [id, recordName] of [['Apex', domainName], ['Www', wwwName]]) {
      new route53.ARecord(this, `${id}A`, { zone, recordName, target });
      new route53.AaaaRecord(this, `${id}Aaaa`, { zone, recordName, target });
    }

    new cdk.CfnOutput(this, 'SiteUrl', { value: `https://${domainName}` });
    new cdk.CfnOutput(this, 'CloudFrontUrl', { value: `https://${distribution.distributionDomainName}` });
  }
}
