import * as path from 'path';
import * as cdk from 'aws-cdk-lib';
import { Construct } from 'constructs';
import * as ec2 from 'aws-cdk-lib/aws-ec2';
import * as iam from 'aws-cdk-lib/aws-iam';
import * as s3 from 'aws-cdk-lib/aws-s3';
import * as s3deploy from 'aws-cdk-lib/aws-s3-deployment';
import * as cloudfront from 'aws-cdk-lib/aws-cloudfront';
import * as origins from 'aws-cdk-lib/aws-cloudfront-origins';
import { DockerImageAsset } from 'aws-cdk-lib/aws-ecr-assets';
import { EnvConfig } from './config';

// Path from this file (infra/lib/) up to the monorepo root.
const REPO_ROOT = path.join(__dirname, '../../');

export interface ClazzzikStackProps extends cdk.StackProps {
  config: EnvConfig;
}

export class ClazzzikStack extends cdk.Stack {
  constructor(scope: Construct, id: string, props: ClazzzikStackProps) {
    super(scope, id, props);
    const { config } = props;

    cdk.Tags.of(this).add('Project', 'clazzziks');
    cdk.Tags.of(this).add('Environment', config.envName);

    // ── ECR image ──────────────────────────────────────────────────────────
    // CDK builds the Dockerfile at the repo root and pushes it to a managed
    // ECR repository. The resulting imageUri is embedded in the user data.
    const imageAsset = new DockerImageAsset(this, 'BackendImage', {
      directory: REPO_ROOT,
      file: 'Dockerfile',
    });

    // ── Network ────────────────────────────────────────────────────────────
    // Single public subnet, no NAT gateway — the instance has a public
    // Elastic IP and egresses directly to the internet.
    const vpc = new ec2.Vpc(this, 'Vpc', {
      maxAzs: 1,
      natGateways: 0,
      subnetConfiguration: [
        {
          name: 'public',
          subnetType: ec2.SubnetType.PUBLIC,
          cidrMask: 24,
        },
      ],
    });

    // ── Security group ─────────────────────────────────────────────────────
    const sg = new ec2.SecurityGroup(this, 'InstanceSg', {
      vpc,
      description: `clazzziks-${config.envName} instance`,
      allowAllOutbound: true,
    });
    sg.addIngressRule(ec2.Peer.anyIpv4(), ec2.Port.tcp(80), 'HTTP');
    sg.addIngressRule(ec2.Peer.anyIpv4(), ec2.Port.tcp(443), 'HTTPS');

    // ── IAM role ───────────────────────────────────────────────────────────
    // The instance must pull the Docker image from ECR at boot.
    // SSMCore enables Session Manager for shell access without SSH keys.
    const instanceRole = new iam.Role(this, 'InstanceRole', {
      assumedBy: new iam.ServicePrincipal('ec2.amazonaws.com'),
      managedPolicies: [
        iam.ManagedPolicy.fromAwsManagedPolicyName('AmazonEC2ContainerRegistryReadOnly'),
        iam.ManagedPolicy.fromAwsManagedPolicyName('AmazonSSMManagedInstanceCore'),
      ],
    });
    imageAsset.repository.grantPull(instanceRole);

    // ── User data ──────────────────────────────────────────────────────────
    // t3 instances are Nitro-based: the OS sees the data volume as
    // /dev/nvme1n1 regardless of the /dev/xvdf name in the block device
    // mapping. We wait for the device before formatting.
    const userData = ec2.UserData.forLinux();
    userData.addCommands(
      // Mount the 50 GiB gp3 data volume at /data
      'while [ ! -b /dev/nvme1n1 ]; do sleep 1; done',
      'mkfs -t xfs /dev/nvme1n1',
      'mkdir -p /data',
      'mount /dev/nvme1n1 /data',
      "echo '/dev/nvme1n1 /data xfs defaults,nofail 0 2' >> /etc/fstab",

      // Install Docker and start it so we can pull the image
      'dnf install -y docker',
      'systemctl enable docker',
      'systemctl start docker',

      // Authenticate with ECR, then pull and run the container
      `aws ecr get-login-password --region ${this.region} | docker login --username AWS --password-stdin ${this.account}.dkr.ecr.${this.region}.amazonaws.com`,
      `docker run -d --restart=always -p 8000:8000 -v /data:/data ${imageAsset.imageUri}`,

      // Install nginx
      'dnf install -y nginx',

      // Write a minimal nginx config that reverse-proxies port 80 → :8000.
      // Single-quoted heredoc delimiter prevents shell expansion of $vars.
      `cat > /etc/nginx/nginx.conf << 'NGINXEOF'
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
NGINXEOF`,

      'systemctl enable nginx',
      'systemctl start nginx',
    );

    // ── EC2 instance ───────────────────────────────────────────────────────
    const instance = new ec2.Instance(this, 'Instance', {
      vpc,
      vpcSubnets: { subnetType: ec2.SubnetType.PUBLIC },
      instanceType: config.instanceType,
      machineImage: ec2.MachineImage.latestAmazonLinux2023(),
      securityGroup: sg,
      role: instanceRole,
      userData,
      blockDevices: [
        {
          deviceName: '/dev/xvdf',
          volume: ec2.BlockDeviceVolume.ebs(50, {
            volumeType: ec2.EbsDeviceVolumeType.GP3,
            deleteOnTermination: true,
          }),
        },
      ],
    });

    // ── Elastic IP ─────────────────────────────────────────────────────────
    const eip = new ec2.CfnEIP(this, 'ElasticIp', {
      instanceId: instance.instanceId,
    });

    // ── Frontend bucket ────────────────────────────────────────────────────
    // All access goes through CloudFront via OAC — no public S3 access.
    // Production bucket is retained on `cdk destroy` to prevent data loss.
    const siteBucket = new s3.Bucket(this, 'SiteBucket', {
      blockPublicAccess: s3.BlockPublicAccess.BLOCK_ALL,
      removalPolicy: config.removalPolicy,
      autoDeleteObjects: config.autoDeleteObjects,
    });

    // ── CloudFront ─────────────────────────────────────────────────────────
    const s3Origin = origins.S3BucketOrigin.withOriginAccessControl(siteBucket);

    // CloudFront → EC2 over HTTP; CDK enforces a 180 s max for readTimeout.
    const apiOrigin = new origins.HttpOrigin(eip.attrPublicIp, {
      httpPort: 80,
      readTimeout: cdk.Duration.seconds(180),
    });

    const distribution = new cloudfront.Distribution(this, 'Distribution', {
      comment: `clazzziks-${config.envName}`,
      defaultBehavior: {
        origin: s3Origin,
        viewerProtocolPolicy: cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
        cachePolicy: cloudfront.CachePolicy.CACHING_OPTIMIZED,
        compress: true,
      },
      additionalBehaviors: {
        '/api/*': {
          origin: apiOrigin,
          viewerProtocolPolicy: cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
          cachePolicy: cloudfront.CachePolicy.CACHING_DISABLED,
          allowedMethods: cloudfront.AllowedMethods.ALLOW_ALL,
        },
      },
      defaultRootObject: 'index.html',
      errorResponses: [
        { httpStatus: 403, responseHttpStatus: 200, responsePagePath: '/index.html' },
        { httpStatus: 404, responseHttpStatus: 200, responsePagePath: '/index.html' },
      ],
    });

    // ── Frontend deployment ─────────────────────────────────────────────────
    // Prerequisite: `cd frontend && npm run build` before running `cdk deploy`.
    new s3deploy.BucketDeployment(this, 'FrontendDeploy', {
      sources: [s3deploy.Source.asset(path.join(REPO_ROOT, 'frontend/dist'))],
      destinationBucket: siteBucket,
      distribution,
      distributionPaths: ['/*'],
    });

    // ── Outputs ────────────────────────────────────────────────────────────
    new cdk.CfnOutput(this, 'SiteUrl', {
      value: `https://${distribution.distributionDomainName}`,
      description: 'CloudFront URL — frontend + API (180 s read timeout via CF)',
    });

    new cdk.CfnOutput(this, 'ElasticIpOutput', {
      exportName: `${this.stackName}-ElasticIp`,
      value: eip.attrPublicIp,
      description: 'EC2 Elastic IP — direct API access (HTTP, no CloudFront timeout)',
    });

    new cdk.CfnOutput(this, 'DistributionId', {
      value: distribution.distributionId,
      description: 'CloudFront distribution ID (needed for manual cache invalidation)',
    });
  }
}
