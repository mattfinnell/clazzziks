import * as path from 'path';
import * as aws from '@pulumi/aws';
import * as awsx from '@pulumi/awsx';
import { REPO_ROOT, config, tags } from '../config';

export interface Image {
  repo: aws.ecr.Repository;
  image: awsx.ecr.Image;
}

// Builds the Dockerfile at the repo root and pushes it to ECR.
// Docker must be running locally for `pulumi up` to succeed.
export function createImage(): Image {
  const repo = new aws.ecr.Repository('backend', {
    forceDelete: !config.retainBucket,
    tags,
  });

  const image = new awsx.ecr.Image('backend-image', {
    repositoryUrl: repo.repositoryUrl,
    context: REPO_ROOT,
    // Absolute path — the provider resolves `dockerfile` relative to the Pulumi
    // program dir (infra/), not the build context.
    dockerfile: path.join(REPO_ROOT, 'Dockerfile'),
    platform: 'linux/amd64',
  });

  return { repo, image };
}
