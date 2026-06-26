import * as pulumi from '@pulumi/pulumi';

import { createNetwork } from './components/network';
import { createImage } from './components/image';
import { createSecrets } from './components/secrets';
import { createDatabase } from './components/database';
import { createIam } from './components/iam';
import { buildUserData } from './components/userdata';
import { createCompute } from './components/compute';
import { createFrontend } from './components/frontend';
import { createCdn } from './components/cdn';

// ── Backend: image, network, data, compute ───────────────────────────────────
const { vpc, instanceSg, dbSg } = createNetwork();
const { image } = createImage();
const { firebaseSecret, adminEmailSecret } = createSecrets();
const { db, masterSecretArn } = createDatabase(vpc, dbSg);
const { instanceProfile } = createIam(masterSecretArn, firebaseSecret, adminEmailSecret);

const userData = buildUserData({ db, masterSecretArn, image, firebaseSecret, adminEmailSecret });
const { eip } = createCompute({ vpc, instanceSg, instanceProfile, userData });

// ── Frontend: S3 + CloudFront ─────────────────────────────────────────────────
const { siteBucket } = createFrontend();
const { distribution } = createCdn({ siteBucket, eip });

// ── Outputs ───────────────────────────────────────────────────────────────────
export const siteUrl        = pulumi.interpolate`https://${distribution.domainName}`;
export const elasticIp      = eip.publicIp;
export const distributionId = distribution.id;
export const dbEndpoint     = db.address;
export const dbSecretArn     = masterSecretArn;
