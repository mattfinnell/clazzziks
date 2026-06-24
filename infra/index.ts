import * as path from 'path';
import * as pulumi from '@pulumi/pulumi';
import * as aws from '@pulumi/aws';
import * as awsx from '@pulumi/awsx';
import * as synced from '@pulumi/synced-folder';

const REPO_ROOT = path.join(__dirname, '../../');
const stack = pulumi.getStack(); // 'staging' | 'production'

// ── Config ──────────────────────────────────────────────────────────────────
const cfg = new pulumi.Config();
const instanceType = cfg.get('instanceType') ?? 't3.micro';
const retainBucket = cfg.getBoolean('retainBucket') ?? false;

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
  dockerfile: 'Dockerfile', // relative to context
  platform: 'linux/amd64',
});

// ── Network ──────────────────────────────────────────────────────────────────
// Single public subnet, no NAT gateway — the instance egresses via Elastic IP.
const vpc = new awsx.ec2.Vpc('vpc', {
  numberOfAvailabilityZones: 1,
  natGateways: { strategy: 'None' },
  subnetSpecs: [{ type: 'Public', cidrMask: 24 }],
  tags,
});

// ── Security group ───────────────────────────────────────────────────────────
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

// ── IAM ─────────────────────────────────────────────────────────────────────
// The instance pulls the Docker image from ECR at boot.
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
const region = aws.config.region ?? 'us-east-1';
const accountId = aws.getCallerIdentityOutput({}).accountId;

const userData = pulumi.interpolate`#!/bin/bash
while [ ! -b /dev/nvme1n1 ]; do sleep 1; done
mkfs -t xfs /dev/nvme1n1
mkdir -p /data
mount /dev/nvme1n1 /data
echo '/dev/nvme1n1 /data xfs defaults,nofail 0 2' >> /etc/fstab

dnf install -y docker
systemctl enable docker
systemctl start docker

aws ecr get-login-password --region ${region} | docker login --username AWS --password-stdin ${accountId}.dkr.ecr.${region}.amazonaws.com
docker run -d --restart=always -p 8000:8000 -v /data:/data ${image.imageUri}

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
      domainName: eip.publicIp,
      customOriginConfig: {
        httpPort: 80,
        httpsPort: 443,
        originProtocolPolicy: 'http-only',
        originReadTimeout: 180, // hard max enforced by CloudFront
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
