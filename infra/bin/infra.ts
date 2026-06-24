#!/usr/bin/env node
import * as cdk from 'aws-cdk-lib';
import { ClazzzikStage } from '../lib/clazzziks-stage';
import { STAGING, PRODUCTION } from '../lib/config';

const app = new cdk.App();

const env = {
  account: process.env.CDK_DEFAULT_ACCOUNT,
  region: process.env.CDK_DEFAULT_REGION ?? 'us-east-1',
};

new ClazzzikStage(app, 'Staging', STAGING, { env });
new ClazzzikStage(app, 'Production', PRODUCTION, { env });
