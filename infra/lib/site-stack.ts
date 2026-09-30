import * as path from 'path';
import * as cdk from 'aws-cdk-lib/core';
import * as acm from 'aws-cdk-lib/aws-certificatemanager';
import * as cloudfront from 'aws-cdk-lib/aws-cloudfront';
import * as origins from 'aws-cdk-lib/aws-cloudfront-origins';
import * as route53 from 'aws-cdk-lib/aws-route53';
import * as r53targets from 'aws-cdk-lib/aws-route53-targets';
import * as s3 from 'aws-cdk-lib/aws-s3';
import * as s3deploy from 'aws-cdk-lib/aws-s3-deployment';
import { Construct } from 'constructs';

export interface SiteStackProps extends cdk.StackProps {
  domainName: string;
  hostedZoneId: string;
  /** The Citi Bike Tides CloudFront domain, served here under /citibike/. */
  citibikeDomain: string;
}

/**
 * shampoe.com
 *
 *   shampoe.com, www.shampoe.com ──> CloudFront (HTTPS)
 *     ├─ /citibike/*  ──> Citi Bike Tides' own CloudFront (prefix stripped; its live data keeps updating)
 *     └─ everything else ──> site bucket (private; uploaded from site/ by `cdk deploy`)
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

    // Runs on every request: www -> bare domain, /citibike -> /citibike/ (so the page's relative
    // data/... fetches resolve under it), and /citibike/x -> /x for the Citi Bike origin.
    // The cache key uses the rewritten path, so /citibike/ and / would share one cache entry;
    // the x-site header (keyed on by citibikeCache below) keeps them apart.
    const router = new cloudfront.Function(this, 'Router', {
      runtime: cloudfront.FunctionRuntime.JS_2_0,
      code: cloudfront.FunctionCode.fromInline(`
function redirect(location) {
  return { statusCode: 301, statusDescription: 'Moved Permanently', headers: { location: { value: location } } };
}
function handler(event) {
  var req = event.request;
  if (req.headers.host && req.headers.host.value === '${wwwName}') return redirect('https://${domainName}' + req.uri);
  if (req.uri === '/citibike') return redirect('/citibike/');
  if (req.uri.startsWith('/citibike/')) {
    req.uri = req.uri.slice('/citibike'.length);
    req.headers['x-site'] = { value: 'citibike' };
  }
  return req;
}`),
    });
    const functionAssociations = [{ function: router, eventType: cloudfront.FunctionEventType.VIEWER_REQUEST }];

    // CACHING_OPTIMIZED plus the x-site header in the cache key.
    const citibikeCache = new cloudfront.CachePolicy(this, 'CitibikeCache', {
      headerBehavior: cloudfront.CacheHeaderBehavior.allowList('x-site'),
      enableAcceptEncodingGzip: true,
      enableAcceptEncodingBrotli: true,
    });

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
      additionalBehaviors: {
        '/citibike*': {
          // No origin request policy, so the Host header becomes the Citi Bike CloudFront domain, which it requires.
          origin: new origins.HttpOrigin(props.citibikeDomain, {
            protocolPolicy: cloudfront.OriginProtocolPolicy.HTTPS_ONLY,
          }),
          viewerProtocolPolicy: cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
          compress: true,
          // Honors the origin's Cache-Control: 60 s for live data, 5 min for the page.
          cachePolicy: citibikeCache,
          functionAssociations,
        },
      },
      priceClass: cloudfront.PriceClass.PRICE_CLASS_100, // North America + Europe edges: cheapest tier
    });

    new s3deploy.BucketDeployment(this, 'Deploy', {
      sources: [s3deploy.Source.asset(path.join(__dirname, '../../site'))],
      destinationBucket: site,
      cacheControl: [s3deploy.CacheControl.fromString('public, max-age=300')],
      distribution,
      distributionPaths: ['/*'],
    });

    const target = route53.RecordTarget.fromAlias(new r53targets.CloudFrontTarget(distribution));
    for (const [id, recordName] of [['Apex', domainName], ['Www', wwwName]]) {
      new route53.ARecord(this, `${id}A`, { zone, recordName, target });
      new route53.AaaaRecord(this, `${id}Aaaa`, { zone, recordName, target });
    }

    new cdk.CfnOutput(this, 'SiteUrl', { value: `https://${domainName}` });
    new cdk.CfnOutput(this, 'CloudFrontUrl', { value: `https://${distribution.distributionDomainName}` });
  }
}
