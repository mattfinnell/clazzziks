import * as path from 'path';
import * as pulumi from '@pulumi/pulumi';
import * as aws from '@pulumi/aws';

// Pulumi runs index.ts in place via ts-node (no bin/ compile step), so __dirname
// is infra/ and the repo root is one level up.
export const REPO_ROOT = path.join(__dirname, '../');

export const stack = pulumi.getStack(); // 'staging' | 'production'
export const region = aws.config.region ?? 'us-west-2';
export const accountId = aws.getCallerIdentityOutput({}).accountId;

// Tags applied to every resource.
export const tags = { Project: 'clazzziks', Environment: stack };

const cfg = new pulumi.Config();

// Per-environment configuration (set in Pulumi.<stack>.yaml). Secrets
// (adminEmail, firebaseCredentials) are read with getSecret so they stay
// encrypted in stack state and never land in plaintext config or user data.
export const config = {
  instanceType: cfg.get('instanceType') ?? 't3.micro',
  retainBucket: cfg.getBoolean('retainBucket') ?? false,

  // Database sizing / durability.
  dbInstanceClass: cfg.get('dbInstanceClass') ?? 'db.t4g.micro',
  dbAllocatedStorage: cfg.getNumber('dbAllocatedStorage') ?? 20,
  dbBackupRetentionDays: cfg.getNumber('dbBackupRetentionDays') ?? 1,
  dbDeletionProtection: cfg.getBoolean('dbDeletionProtection') ?? false,

  // Non-secret backend knobs passed straight into the container as env vars.
  rateLimit: cfg.get('rateLimit'),
  rateWindowSeconds: cfg.get('rateWindowSeconds'),

  // Admin email seeds the DB owner; kept secret (Secrets Manager + boot fetch).
  adminEmail: cfg.getSecret('adminEmail'),

  // Optional Firebase auth. Unset firebaseCredentials → the env runs open,
  // matching the backend's secret-free fallback (clazzziks/auth.py).
  firebaseCredentials: cfg.getSecret('firebaseCredentials'), // service-account JSON
  firebaseProjectId: cfg.get('firebaseProjectId'),
  allowedEmails: cfg.get('allowedEmails'),
};

export const firebaseEnabled = config.firebaseCredentials !== undefined;
