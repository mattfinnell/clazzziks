# CLAZZZIKS — Infrastructure

Pulumi (TypeScript) project that provisions the CLAZZZIKS audio downloader on AWS.

## Architecture

```
CloudFront distribution
  ├── /* ──────────────────→ S3 bucket (React SPA, via OAC)
  └── /api/* ──────────────→ EC2 Elastic IP (60 s read timeout)
                                └── nginx :80 → FastAPI container :8000
                                                  └── RDS Postgres :5432 (private)
```

- **EC2 t3.small / t3.micro** — Amazon Linux 2023 instance running the FastAPI
  backend inside Docker. On first boot the user data script installs Docker,
  reads the DB (and optional Firebase) secret from Secrets Manager, assembles the
  container env, pulls the image from ECR, installs nginx, and wires everything up.
  Staging uses a `t3.micro`; production uses a `t3.small`.
- **RDS Postgres** — one managed instance per environment (`db.t4g.micro`),
  living in the VPC's private-by-policy subnets (`publiclyAccessible: false`),
  reachable only from the EC2 instance's security group on `:5432`. The master
  password is generated and rotated by RDS in **Secrets Manager**
  (`manageMasterUserPassword`) — it is never stored in Pulumi config or state.
  Production retains backups (7 days), enables deletion protection, and takes a
  final snapshot on destroy; staging is ephemeral.
- **Secrets Manager** — holds the RDS master password and, optionally, a Firebase
  service-account JSON (seeded from the `firebaseCredentials` Pulumi secret). The
  EC2 instance role is granted read access to exactly those secret ARNs.
- **EBS 50 GiB gp3** — attached at `/data`; used as ffmpeg scratch space (and to
  hold `firebase.json` when Firebase auth is configured).
- **Elastic IP** — stable public IPv4 address. CloudFront uses the EIP's public
  DNS name (`eip.publicDns`) as the `/api/*` HTTP origin — CloudFront rejects a
  raw IP address as an origin domain.
- **S3 + CloudFront** — the React SPA is uploaded from `frontend/dist/`; the
  distribution serves it over HTTPS. 403/404s return `index.html` so the SPA
  handles its own routing.
- **ECR repository** — Pulumi builds the `Dockerfile` at the repo root and
  pushes the image automatically on each `pulumi up`.

> **CloudFront timeout note:** the `/api/*` origin read timeout is set to **60
> seconds** — the default account maximum. (Going higher, up to 180 s, requires a
> Service Quotas increase for CloudFront's "Origin response timeout"; bump
> `originReadTimeout` in `index.ts` once granted.) Downloads that take longer
> should hit the Elastic IP directly (`elasticIp` stack output), which goes
> straight to nginx (300 s `proxy_read_timeout`) and bypasses CloudFront.

## Prerequisites

Inside the **devcontainer** these are already installed (Node, the Pulumi CLI, the
AWS CLI, and Docker via the devcontainer features + `post-create.sh`). Outside it:

- [Node.js](https://nodejs.org/) 18+
- [Pulumi CLI](https://www.pulumi.com/docs/install/): `curl -fsSL https://get.pulumi.com | sh`
- [AWS CLI](https://aws.amazon.com/cli/) configured (`aws configure`)
- Docker (used by Pulumi to build and push the backend container image)

**AWS IAM permissions:** the deploying user needs to create EC2/VPC, RDS, S3,
CloudFront, ECR, IAM (roles + instance profile), and Secrets Manager resources.
For a personal account the simplest durable option is to attach
`AdministratorAccess` to the user. A scoped alternative is the union of
`AmazonEC2FullAccess`, `AmazonRDSFullAccess`, `AmazonS3FullAccess`,
`CloudFrontFullAccess`, `AmazonEC2ContainerRegistryFullAccess`,
`SecretsManagerReadWrite`, and `IAMFullAccess`. A user without these gets
`UnauthorizedOperation` 403s on the very first `pulumi preview` (e.g.
`ec2:DescribeImages`). A user can't self-grant — attach the policy from the
console as the account root (or another admin identity).

**Devcontainer Docker credentials:** inside the VS Code devcontainer, the Dev
Containers extension writes a `credsStore` into `~/.docker/config.json` whose
helper doesn't implement the `list` verb. Pulumi's image build then fails with
`error listing credentials - err: exit status 255`. Remove that key (it falls
back to plaintext `auths`, which is fine for builds). `post-create.sh` strips it
automatically; if you hit it after a manual change, re-run that script or delete
the `credsStore` line by hand.

## Setup

```bash
cd infra
npm install

# Choose a state backend and log in (one-time). Either Pulumi Cloud:
pulumi login
# …or local/self-managed state (no account needed):
#   pulumi login --local        # ~/.pulumi
#   pulumi login s3://my-bucket  # an S3 backend
```

## Deploy

```bash
# Build the React app first — Pulumi syncs frontend/dist/ to S3
cd frontend && pnpm install && pnpm build && cd ..

# One-time: create stacks (skip if they already exist)
cd infra
pulumi stack init staging
pulumi stack init production

# Deploy
pulumi stack select production
pulumi up
```

### Admin email (secret, per stack)

The DB-owner admin email is a secret — it is stored in Secrets Manager and read
onto the instance at boot, never committed in plaintext:

```bash
pulumi config set --secret clazzziks:adminEmail you@example.com
```

If left unset, no owner is seeded (open/dev mode treats the local caller as admin).

### Optional: Firebase auth (per stack)

Auth is off unless a Firebase service-account JSON is configured. To enable it:

```bash
pulumi config set --secret clazzziks:firebaseCredentials "$(cat service-account.json)"
pulumi config set clazzziks:firebaseProjectId  <project-id>
pulumi config set clazzziks:allowedEmails      a@example.com,b@example.com  # optional allowlist
```

The JSON is stored in Secrets Manager and fetched onto the instance at boot.

Each deploy exposes these stack outputs:

| Output | Description |
|---|---|
| `siteUrl` | CloudFront HTTPS URL — use this for normal access |
| `elasticIp` | EC2 Elastic IP (HTTP) — use this if a download exceeds the 60 s CF timeout |
| `distributionId` | CloudFront distribution ID (for cache invalidations) |
| `dbEndpoint` | RDS Postgres endpoint hostname |
| `dbSecretArn` | Secrets Manager ARN of the RDS-managed master password |

After deploying a new frontend build, invalidate the CloudFront cache:

```bash
aws cloudfront create-invalidation \
  --distribution-id $(pulumi stack output distributionId) \
  --paths '/*'
```

## Tear down

```bash
pulumi stack select staging
pulumi destroy

# Production is protected:
#  - S3 bucket uses retainOnDelete — empty and delete it manually first.
#  - RDS has deletion protection — flip it off, then up, before destroy:
#      pulumi config set clazzziks:dbDeletionProtection false
#      pulumi up
#    (destroy then takes a final snapshot named clazzziks-production-final).
pulumi stack select production
pulumi destroy
```

## Project structure

```
infra/
├── index.ts                # all AWS resources (ECR, VPC, EC2, EIP, RDS, Secrets Manager, S3, CloudFront)
├── Pulumi.yaml             # Pulumi project config
├── Pulumi.staging.yaml     # staging stack config
├── Pulumi.production.yaml  # production stack config
├── package.json
└── tsconfig.json
```

## Useful Pulumi commands

```bash
pulumi stack ls                        # list all stacks
pulumi stack select staging            # switch to staging
pulumi preview                         # show pending changes
pulumi up                              # deploy
pulumi destroy                         # tear down
pulumi stack output siteUrl            # print a specific output
```
