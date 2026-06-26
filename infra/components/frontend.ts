import * as path from 'path';
import * as aws from '@pulumi/aws';
import * as synced from '@pulumi/synced-folder';
import { REPO_ROOT, tags, config } from '../config';

export interface Frontend {
  siteBucket: aws.s3.BucketV2;
}

// S3 bucket holding the built React SPA. All access goes through CloudFront via
// OAC — no public S3 access. Production retains the bucket on delete; staging
// allows a clean teardown.
export function createFrontend(): Frontend {
  const siteBucket = new aws.s3.BucketV2('site-bucket', { tags }, {
    retainOnDelete: config.retainBucket,
  });

  new aws.s3.BucketPublicAccessBlock('site-bucket-pab', {
    bucket: siteBucket.id,
    blockPublicAcls: true,
    blockPublicPolicy: true,
    ignorePublicAcls: true,
    restrictPublicBuckets: true,
  });

  // Prerequisite: `cd frontend && pnpm build` before running `pulumi up`.
  // CloudFront cache invalidation is NOT automatic — run manually after deploy:
  //   aws cloudfront create-invalidation --distribution-id <id> --paths '/*'
  new synced.S3BucketFolder('frontend', {
    path: path.join(REPO_ROOT, 'frontend/dist'),
    bucketName: siteBucket.bucket,
    acl: 'private',
  });

  return { siteBucket };
}
