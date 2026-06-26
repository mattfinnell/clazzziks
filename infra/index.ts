import * as path from 'path';
import * as pulumi from '@pulumi/pulumi';
import * as aws from '@pulumi/aws';
import * as awsx from '@pulumi/awsx';
import * as synced from '@pulumi/synced-folder';

// Pulumi runs index.ts in place via ts-node (no bin/ compile step), so __dirname
// is infra/ and the repo root is one level up.
const REPO_ROOT = path.join(__dirname, '../');
const stack = pulumi.getStack(); // 'staging' | 'production'

// ── Config ──────────────────────────────────────────────────────────────────
const cfg = new pulumi.Config();
const instanceType = cfg.get('instanceType') ?? 't3.micro';
const retainBucket = cfg.getBoolean('retainBucket') ?? false;

// Database sizing / durability (per-env via Pulumi.<stack>.yaml).
const dbInstanceClass = cfg.get('dbInstanceClass') ?? 'db.t4g.micro';
const dbAllocatedStorage = cfg.getNumber('dbAllocatedStorage') ?? 20;
const dbBackupRetentionDays = cfg.getNumber('dbBackupRetentionDays') ?? 1;
const dbDeletionProtection = cfg.getBoolean('dbDeletionProtection') ?? false;

// Non-secret backend knobs passed straight into the container as env vars.
const rateLimit = cfg.get('rateLimit');
const rateWindowSeconds = cfg.get('rateWindowSeconds');

// Admin email seeds the DB owner. Kept as a secret so it never appears in
// plaintext config, stack state, or EC2 user data — stored in Secrets Manager
// and read onto the box at boot.
const adminEmail = cfg.getSecret('adminEmail');

// Optional Firebase auth. When firebaseCredentials is unset the env runs open,
// matching the backend's secret-free fallback (clazzziks/auth.py).
const firebaseCredentials = cfg.getSecret('firebaseCredentials'); // service-account JSON
const firebaseProjectId = cfg.get('firebaseProjectId');
const allowedEmails = cfg.get('allowedEmails');
const firebaseEnabled = firebaseCredentials !== undefined;

const tags = { Project: 'clazzziks', Environment: stack };

// ── ECR image ───────────────────────────────────────────────────────────────
// Builds the Dockerfile at the repo root and pushes it to ECR.
// Docker must be running locally for `pulumi up` to succeed.
const repo = new aws.ecr.Repository('backend', {
  forceDelete: !retainBucket,
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

// ── Network ──────────────────────────────────────────────────────────────────
// Two public subnets (no NAT gateway — the instance egresses via Elastic IP).
// RDS requires a DB subnet group spanning >= 2 AZs, hence two AZs here. RDS is
// not publicly accessible, so it stays internal despite the public subnets.
const vpc = new awsx.ec2.Vpc('vpc', {
  numberOfAvailabilityZones: 2,
  natGateways: { strategy: 'None' },
  subnetSpecs: [{ type: 'Public', cidrMask: 24 }],
  // Pin the allocation strategy: awsx's default flips Legacy → Auto in the next
  // major. Setting it now (pre-deploy) avoids a forced subnet replacement later.
  subnetStrategy: 'Auto',
  tags,
});

// ── Security groups ──────────────────────────────────────────────────────────
const sg = new aws.ec2.SecurityGroup('instance-sg', {
  vpcId: vpc.vpcId,
  description: `clazzziks-${stack} instance`,
  egress: [{ fromPort: 0, toPort: 0, protocol: '-1', cidrBlocks: ['0.0.0.0/0'], description: 'all outbound' }],
  ingress: [
    { fromPort: 80,  toPort: 80,  protocol: 'tcp', cidrBlocks: ['0.0.0.0/0'], description: 'HTTP' },
    { fromPort: 443, toPort: 443, protocol: 'tcp', cidrBlocks: ['0.0.0.0/0'], description: 'HTTPS' },
  ],
  tags,
});

// Postgres reachable only from the EC2 instance — never from the internet.
const dbSg = new aws.ec2.SecurityGroup('db-sg', {
  vpcId: vpc.vpcId,
  description: `clazzziks-${stack} postgres`,
  egress: [{ fromPort: 0, toPort: 0, protocol: '-1', cidrBlocks: ['0.0.0.0/0'], description: 'all outbound' }],
  ingress: [
    { fromPort: 5432, toPort: 5432, protocol: 'tcp', securityGroups: [sg.id], description: 'Postgres from instance' },
  ],
  tags,
});

// ── RDS Postgres ─────────────────────────────────────────────────────────────
// manageMasterUserPassword=true → RDS generates the password and stores/rotates
// it in Secrets Manager. No password ever lives in Pulumi state or user data;
// the instance reads it at boot via its IAM role (below).
const dbSubnets = new aws.rds.SubnetGroup('db-subnets', {
  subnetIds: vpc.publicSubnetIds,
  tags,
});

const db = new aws.rds.Instance('db', {
  engine: 'postgres',
  engineVersion: '16',
  instanceClass: dbInstanceClass,
  allocatedStorage: dbAllocatedStorage,
  storageType: 'gp3',
  dbName: 'clazzziks',
  username: 'clazzziks',
  manageMasterUserPassword: true,
  dbSubnetGroupName: dbSubnets.name,
  vpcSecurityGroupIds: [dbSg.id],
  publiclyAccessible: false,
  multiAz: false,
  backupRetentionPeriod: dbBackupRetentionDays,
  deletionProtection: dbDeletionProtection,
  skipFinalSnapshot: !retainBucket,
  finalSnapshotIdentifier: retainBucket ? `clazzziks-${stack}-final` : undefined,
  applyImmediately: true,
  tags,
});

// ARN of the RDS-managed master password secret.
const masterSecretArn = db.masterUserSecrets.apply(s => s[0].secretArn);

// ── Firebase secret (optional) ───────────────────────────────────────────────
// Seeded from the `firebaseCredentials` Pulumi secret; the JSON stays encrypted
// in stack state and is fetched onto the box at boot, never baked into the image.
let firebaseSecret: aws.secretsmanager.Secret | undefined;
if (firebaseEnabled) {
  firebaseSecret = new aws.secretsmanager.Secret('firebase-creds', {
    description: `clazzziks-${stack} Firebase service-account JSON`,
    tags,
  });
  new aws.secretsmanager.SecretVersion('firebase-creds-v', {
    secretId: firebaseSecret.id,
    secretString: firebaseCredentials!,
  });
}

// ── Admin email secret (optional) ────────────────────────────────────────────
let adminEmailSecret: aws.secretsmanager.Secret | undefined;
if (adminEmail !== undefined) {
  adminEmailSecret = new aws.secretsmanager.Secret('admin-email', {
    description: `clazzziks-${stack} admin email (DB owner seed)`,
    tags,
  });
  new aws.secretsmanager.SecretVersion('admin-email-v', {
    secretId: adminEmailSecret.id,
    secretString: adminEmail,
  });
}

// ── IAM ─────────────────────────────────────────────────────────────────────
// The instance pulls the Docker image from ECR and reads its secrets at boot.
// SSMManagedInstanceCore enables Session Manager shell access (no SSH keys needed).
const instanceRole = new aws.iam.Role('instance-role', {
  assumeRolePolicy: aws.iam.assumeRolePolicyForPrincipal({ Service: 'ec2.amazonaws.com' }),
  managedPolicyArns: [
    'arn:aws:iam::aws:policy/AmazonEC2ContainerRegistryReadOnly',
    'arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore',
  ],
  tags,
});

const instanceProfile = new aws.iam.InstanceProfile('instance-profile', {
  role: instanceRole.name,
});

// Allow the instance to read exactly its DB secret (and Firebase secret if set).
const secretArns: pulumi.Input<string>[] = [masterSecretArn];
if (firebaseSecret) secretArns.push(firebaseSecret.arn);
if (adminEmailSecret) secretArns.push(adminEmailSecret.arn);

new aws.iam.RolePolicy('instance-secrets-policy', {
  role: instanceRole.id,
  policy: pulumi.all(secretArns).apply(arns =>
    JSON.stringify({
      Version: '2012-10-17',
      Statement: [{
        Effect: 'Allow',
        Action: ['secretsmanager:GetSecretValue'],
        Resource: arns,
      }],
    })
  ),
});

// ── AMI ──────────────────────────────────────────────────────────────────────
const ami = aws.ec2.getAmiOutput({
  mostRecent: true,
  owners: ['amazon'],
  filters: [
    { name: 'name',         values: ['al2023-ami-*-x86_64'] },
    { name: 'architecture', values: ['x86_64'] },
  ],
});

// ── User data ────────────────────────────────────────────────────────────────
// t3 instances are Nitro-based: the OS sees the EBS data volume as /dev/nvme1n1
// regardless of the /dev/xvdf name in the block-device mapping. We poll for
// the device before formatting.
const region = aws.config.region ?? 'us-west-2';
const accountId = aws.getCallerIdentityOutput({}).accountId;

// Non-secret env flags are known at deploy time; assemble them in TS.
const staticEnvFlags = [
  rateLimit ? `-e CLAZZZIKS_RATE_LIMIT=${rateLimit}` : '',
  rateWindowSeconds ? `-e CLAZZZIKS_RATE_WINDOW_SECONDS=${rateWindowSeconds}` : '',
].filter(Boolean).join(' ');

// Admin email: fetched from Secrets Manager at boot so it never sits in user data.
const adminSetup = adminEmailSecret
  ? pulumi.interpolate`ADMIN_ENV="-e CLAZZZIKS_ADMIN_EMAIL=$(aws secretsmanager get-secret-value --region ${region} --secret-id ${adminEmailSecret.arn} --query SecretString --output text)"
`
  : 'ADMIN_ENV=""\n';

// Firebase: fetch the JSON onto /data and export the matching env flags.
// When disabled, FIREBASE_ENV is empty and the container runs open.
const firebaseProjectFlag = firebaseProjectId ? ` -e CLAZZZIKS_FIREBASE_PROJECT_ID=${firebaseProjectId}` : '';
const allowedEmailsFlag = allowedEmails ? ` -e CLAZZZIKS_ALLOWED_EMAILS=${allowedEmails}` : '';
const firebaseSetup = firebaseSecret
  ? pulumi.interpolate`aws secretsmanager get-secret-value --region ${region} --secret-id ${firebaseSecret.arn} --query SecretString --output text > /data/firebase.json
FIREBASE_ENV="-e CLAZZZIKS_FIREBASE_CREDENTIALS=/data/firebase.json${firebaseProjectFlag}${allowedEmailsFlag}"
`
  : 'FIREBASE_ENV=""\n';

const userData = pulumi.interpolate`#!/bin/bash
set -euo pipefail
while [ ! -b /dev/nvme1n1 ]; do sleep 1; done
if ! blkid /dev/nvme1n1; then mkfs -t xfs /dev/nvme1n1; fi
mkdir -p /data
mount /dev/nvme1n1 /data
echo '/dev/nvme1n1 /data xfs defaults,nofail 0 2' >> /etc/fstab

dnf install -y docker jq
# Store Docker images + container layers on the 50 GiB /data volume. The AL2023
# root volume (~8 GiB) is too small for the ffmpeg-based image — pulling it onto
# root fails with "no space left on device", which aborts this script (set -e)
# before nginx ever starts. data-root must be set before docker first starts.
mkdir -p /data/docker /etc/docker
cat > /etc/docker/daemon.json << 'DOCKEREOF'
{ "data-root": "/data/docker" }
DOCKEREOF
systemctl enable docker
systemctl start docker

# Build the database URL from the RDS-managed secret (password URL-encoded).
DB_SECRET=$(aws secretsmanager get-secret-value --region ${region} --secret-id ${masterSecretArn} --query SecretString --output text)
DB_USER=$(echo "$DB_SECRET" | jq -r '.username|@uri')
DB_PASS=$(echo "$DB_SECRET" | jq -r '.password|@uri')
DATABASE_URL="postgresql+psycopg://$DB_USER:$DB_PASS@${db.address}:${db.port}/clazzziks"

${firebaseSetup}
${adminSetup}
aws ecr get-login-password --region ${region} | docker login --username AWS --password-stdin ${accountId}.dkr.ecr.${region}.amazonaws.com
docker run -d --restart=always -p 8000:8000 -v /data:/data \
  -e CLAZZZIKS_DATABASE_URL="$DATABASE_URL" \
  ${staticEnvFlags} \
  $ADMIN_ENV \
  $FIREBASE_ENV \
  ${image.imageUri}

dnf install -y nginx
cat > /etc/nginx/nginx.conf << 'NGINXEOF'
user nginx;
worker_processes auto;
error_log /var/log/nginx/error.log;
pid /run/nginx.pid;
include /usr/share/nginx/modules/*.conf;

events {
    worker_connections 1024;
}

http {
    log_format  main  '$remote_addr - $remote_user [$time_local] "$request" '
                      '$status $body_bytes_sent "$http_referer" '
                      '"$http_user_agent" "$http_x_forwarded_for"';
    access_log  /var/log/nginx/access.log  main;
    sendfile        on;
    tcp_nopush      on;
    keepalive_timeout 65;
    types_hash_max_size 4096;
    include /etc/nginx/mime.types;
    default_type application/octet-stream;

    server {
        listen 80;
        server_name _;
        location / {
            proxy_pass         http://localhost:8000;
            proxy_read_timeout 300s;
            proxy_send_timeout 300s;
            proxy_set_header   Host              $host;
            proxy_set_header   X-Real-IP         $remote_addr;
            proxy_set_header   X-Forwarded-For   $proxy_add_x_forwarded_for;
        }
    }
}
NGINXEOF
systemctl enable nginx
systemctl start nginx
`;

// ── EC2 instance ─────────────────────────────────────────────────────────────
const instance = new aws.ec2.Instance('instance', {
  ami: ami.id,
  instanceType,
  subnetId: vpc.publicSubnetIds.apply(ids => ids[0]),
  vpcSecurityGroupIds: [sg.id],
  iamInstanceProfile: instanceProfile.name,
  userData,
  // User-data only runs on first boot, so any change to it (e.g. enabling
  // Firebase, new env vars) must roll a fresh instance to take effect.
  userDataReplaceOnChange: true,
  ebsBlockDevices: [{
    deviceName: '/dev/xvdf',
    volumeSize: 50,
    volumeType: 'gp3',
    deleteOnTermination: true,
  }],
  tags: { ...tags, Name: `clazzziks-${stack}` },
});

// ── Elastic IP ───────────────────────────────────────────────────────────────
const eip = new aws.ec2.Eip('eip', { tags });
new aws.ec2.EipAssociation('eip-assoc', {
  instanceId: instance.id,
  allocationId: eip.id,
});

// ── Frontend S3 bucket ───────────────────────────────────────────────────────
// All access goes through CloudFront via OAC — no public S3 access.
// Production: retainOnDelete prevents destruction; staging: forceDestroy allows clean teardown.
const siteBucket = new aws.s3.BucketV2('site-bucket', { tags }, {
  retainOnDelete: retainBucket,
});

new aws.s3.BucketPublicAccessBlock('site-bucket-pab', {
  bucket: siteBucket.id,
  blockPublicAcls: true,
  blockPublicPolicy: true,
  ignorePublicAcls: true,
  restrictPublicBuckets: true,
});

// ── CloudFront ───────────────────────────────────────────────────────────────
const oac = new aws.cloudfront.OriginAccessControl('oac', {
  originAccessControlOriginType: 's3',
  signingBehavior: 'always',
  signingProtocol: 'sigv4',
  description: `clazzziks-${stack} S3 OAC`,
});

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
    compress: true,
    minTtl: 0,
  },
  orderedCacheBehaviors: [{
    pathPattern: '/api/*',
    targetOriginId: 'api',
    viewerProtocolPolicy: 'redirect-to-https',
    allowedMethods: ['DELETE', 'GET', 'HEAD', 'OPTIONS', 'PATCH', 'POST', 'PUT'],
    cachedMethods: ['GET', 'HEAD'],
    forwardedValues: { queryString: true, cookies: { forward: 'all' }, headers: ['*'] },
    minTtl: 0,
    defaultTtl: 0,
    maxTtl: 0,
  }],
  customErrorResponses: [
    { errorCode: 403, responseCode: 200, responsePagePath: '/index.html' },
    { errorCode: 404, responseCode: 200, responsePagePath: '/index.html' },
  ],
  restrictions: { geoRestriction: { restrictionType: 'none' } },
  viewerCertificate: { cloudfrontDefaultCertificate: true },
  tags,
});

// Bucket policy: allow CloudFront OAC to read objects
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

// ── Frontend deployment ───────────────────────────────────────────────────────
// Prerequisite: `cd frontend && pnpm build` before running `pulumi up`.
// CloudFront cache invalidation is NOT automatic — run manually after deploy:
//   aws cloudfront create-invalidation --distribution-id <id> --paths '/*'
new synced.S3BucketFolder('frontend', {
  path: path.join(REPO_ROOT, 'frontend/dist'),
  bucketName: siteBucket.bucket,
  acl: 'private',
});

// ── Outputs ───────────────────────────────────────────────────────────────────
export const siteUrl       = pulumi.interpolate`https://${distribution.domainName}`;
export const elasticIp     = eip.publicIp;
export const distributionId = distribution.id;
export const dbEndpoint     = db.address;
export const dbSecretArn    = masterSecretArn;
