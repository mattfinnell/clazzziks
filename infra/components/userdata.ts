import * as pulumi from '@pulumi/pulumi';
import * as aws from '@pulumi/aws';
import * as awsx from '@pulumi/awsx';
import { region, accountId, config } from '../config';

export interface UserDataArgs {
  db: aws.rds.Instance;
  masterSecretArn: pulumi.Input<string>;
  image: awsx.ecr.Image;
  firebaseSecret?: aws.secretsmanager.Secret;
  adminEmailSecret?: aws.secretsmanager.Secret;
}

// Assembles the EC2 first-boot script. t3 instances are Nitro-based: the OS sees
// the EBS data volume as /dev/nvme1n1 regardless of the /dev/xvdf block-device
// name, so the script polls for the device before formatting.
export function buildUserData(args: UserDataArgs): pulumi.Output<string> {
  const { db, masterSecretArn, image, firebaseSecret, adminEmailSecret } = args;

  // Non-secret env flags are known at deploy time; assemble them in TS.
  const staticEnvFlags = [
    config.rateLimit ? `-e CLAZZZIKS_RATE_LIMIT=${config.rateLimit}` : '',
    config.rateWindowSeconds ? `-e CLAZZZIKS_RATE_WINDOW_SECONDS=${config.rateWindowSeconds}` : '',
  ].filter(Boolean).join(' ');

  // Admin email: fetched from Secrets Manager at boot so it never sits in user data.
  const adminSetup = adminEmailSecret
    ? pulumi.interpolate`ADMIN_ENV="-e CLAZZZIKS_ADMIN_EMAIL=$(aws secretsmanager get-secret-value --region ${region} --secret-id ${adminEmailSecret.arn} --query SecretString --output text)"
`
    : 'ADMIN_ENV=""\n';

  // Firebase: fetch the JSON onto /data and export the matching env flags.
  // When disabled, FIREBASE_ENV is empty and the container runs open.
  const firebaseProjectFlag = config.firebaseProjectId ? ` -e CLAZZZIKS_FIREBASE_PROJECT_ID=${config.firebaseProjectId}` : '';
  const allowedEmailsFlag = config.allowedEmails ? ` -e CLAZZZIKS_ALLOWED_EMAILS=${config.allowedEmails}` : '';
  const firebaseSetup = firebaseSecret
    ? pulumi.interpolate`aws secretsmanager get-secret-value --region ${region} --secret-id ${firebaseSecret.arn} --query SecretString --output text > /data/firebase.json
FIREBASE_ENV="-e CLAZZZIKS_FIREBASE_CREDENTIALS=/data/firebase.json${firebaseProjectFlag}${allowedEmailsFlag}"
`
    : 'FIREBASE_ENV=""\n';

  return pulumi.interpolate`#!/bin/bash
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
}
