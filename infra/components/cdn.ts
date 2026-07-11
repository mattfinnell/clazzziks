import * as pulumi from '@pulumi/pulumi';
import * as aws from '@pulumi/aws';
import { stack, tags } from '../config';

export interface Cdn {
  distribution: aws.cloudfront.Distribution;
}

export interface CdnArgs {
  siteBucket: aws.s3.BucketV2;
  eip: aws.ec2.Eip;
}

// CloudFront in front of the SPA (S3, default behavior) and the API (EC2 Elastic
// IP, /api/* behavior). Also wires the S3 bucket policy that grants the OAC read
// access — kept here because it depends on the distribution ARN.
export function createCdn(args: CdnArgs): Cdn {
  const { siteBucket, eip } = args;

  const oac = new aws.cloudfront.OriginAccessControl('oac', {
    originAccessControlOriginType: 's3',
    signingBehavior: 'always',
    signingProtocol: 'sigv4',
    description: `clazzziks-${stack} S3 OAC`,
  });

  // HTTPS-everywhere (edge enforcement): every viewer response carries HSTS so
  // browsers refuse to talk to the site over plain HTTP after the first visit.
  // Viewers are already redirected HTTP -> HTTPS by each behavior below; this
  // makes that stick. The CloudFront <-> origin hop stays HTTP by design.
  const securityHeaders = new aws.cloudfront.ResponseHeadersPolicy('security-headers', {
    securityHeadersConfig: {
      strictTransportSecurity: {
        accessControlMaxAgeSec: 31536000, // 1 year
        includeSubdomains: true,
        preload: true,
        override: true,
      },
    },
  });

  // Shared config for the two API behaviors (GraphQL + the /files download
  // stream). Both proxy to the EC2 origin, force HTTPS to viewers, and are
  // uncacheable (POST GraphQL + unique per-download tokens).
  const apiBehavior = {
    targetOriginId: 'api',
    viewerProtocolPolicy: 'redirect-to-https' as const,
    allowedMethods: ['DELETE', 'GET', 'HEAD', 'OPTIONS', 'PATCH', 'POST', 'PUT'],
    cachedMethods: ['GET', 'HEAD'],
    forwardedValues: { queryString: true, cookies: { forward: 'all' as const }, headers: ['*'] },
    responseHeadersPolicyId: securityHeaders.id,
    minTtl: 0,
    defaultTtl: 0,
    maxTtl: 0,
  };

  const distribution = new aws.cloudfront.Distribution('distribution', {
    comment: `clazzziks-${stack}`,
    enabled: true,
    defaultRootObject: 'index.html',
    origins: [
      {
        originId: 's3',
        domainName: siteBucket.bucketRegionalDomainName,
        originAccessControlId: oac.id,
        s3OriginConfig: { originAccessIdentity: '' }, // required field when using OAC
      },
      {
        originId: 'api',
        // CloudFront rejects raw IP addresses as an origin domain — use the EIP's
        // public DNS name (resolves to the same Elastic IP).
        domainName: eip.publicDns,
        customOriginConfig: {
          httpPort: 80,
          httpsPort: 443,
          originProtocolPolicy: 'http-only',
          originSslProtocols: ['TLSv1.2'], // required field; unused since origin is http-only
          originReadTimeout: 60, // default account max; 180 needs a Service Quotas increase
          originKeepaliveTimeout: 5,
        },
      },
    ],
    defaultCacheBehavior: {
      targetOriginId: 's3',
      viewerProtocolPolicy: 'redirect-to-https',
      allowedMethods: ['GET', 'HEAD'],
      cachedMethods: ['GET', 'HEAD'],
      forwardedValues: { queryString: false, cookies: { forward: 'none' } },
      responseHeadersPolicyId: securityHeaders.id,
      compress: true,
      minTtl: 0,
    },
    // The API is GraphQL (/graphql) plus the binary download stream (/files/*);
    // both proxy to the EC2 origin. (Was a single /api/* behavior pre-GraphQL.)
    orderedCacheBehaviors: [
      { pathPattern: '/graphql', ...apiBehavior },
      { pathPattern: '/files/*', ...apiBehavior },
    ],
    customErrorResponses: [
      { errorCode: 403, responseCode: 200, responsePagePath: '/index.html' },
      { errorCode: 404, responseCode: 200, responsePagePath: '/index.html' },
    ],
    restrictions: { geoRestriction: { restrictionType: 'none' } },
    viewerCertificate: { cloudfrontDefaultCertificate: true },
    tags,
  });

  // Bucket policy: allow CloudFront OAC to read objects.
  new aws.s3.BucketPolicy('site-bucket-policy', {
    bucket: siteBucket.id,
    policy: pulumi.all([siteBucket.arn, distribution.arn]).apply(([bucketArn, distArn]) =>
      JSON.stringify({
        Version: '2012-10-17',
        Statement: [{
          Sid: 'AllowCloudFront',
          Effect: 'Allow',
          Principal: { Service: 'cloudfront.amazonaws.com' },
          Action: 's3:GetObject',
          Resource: `${bucketArn}/*`,
          Condition: { StringEquals: { 'AWS:SourceArn': distArn } },
        }],
      })
    ),
  });

  return { distribution };
}
