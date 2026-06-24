# CLAZZZIKS — Infrastructure

Pulumi (TypeScript) project that provisions the CLAZZZIKS audio downloader on AWS.

## Architecture

```
CloudFront distribution
  ├── /* ──────────────────→ S3 bucket (React SPA, via OAC)
  └── /api/* ──────────────→ EC2 Elastic IP (180 s read timeout)
                                └── nginx :80 → FastAPI container :8000
```

- **EC2 t3.small / t3.micro** — Amazon Linux 2023 instance running the FastAPI
  backend inside Docker. On first boot the user data script installs Docker,
  pulls the image from ECR, installs nginx, and wires everything up.
  Staging uses a `t3.micro`; production uses a `t3.small`.
- **EBS 50 GiB gp3** — attached at `/data`; used as ffmpeg scratch space.
  Downloaded audio is written here and streamed back in the same request.
- **Elastic IP** — stable public IPv4 address. CloudFront uses it as the
  `/api/*` HTTP origin.
- **S3 + CloudFront** — the React SPA is uploaded from `frontend/dist/`; the
  distribution serves it over HTTPS. 403/404s return `index.html` so the SPA
  handles its own routing.
- **ECR repository** — Pulumi builds the `Dockerfile` at the repo root and
  pushes the image automatically on each `pulumi up`.

> **CloudFront timeout note:** CloudFront enforces a 180-second maximum read
> timeout. Downloads that take longer should hit the Elastic IP directly
> (`elasticIp` stack output).

## Prerequisites

- [Node.js](https://nodejs.org/) 18+
- [Pulumi CLI](https://www.pulumi.com/docs/install/): `curl -fsSL https://get.pulumi.com | sh`
- [AWS CLI](https://aws.amazon.com/cli/) configured (`aws configure`)
- Docker (used by Pulumi to build and push the backend container image)

## Setup

```bash
cd infra
npm install
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

Each deploy exposes three stack outputs:

| Output | Description |
|---|---|
| `siteUrl` | CloudFront HTTPS URL — use this for normal access |
| `elasticIp` | EC2 Elastic IP (HTTP) — use this if a download exceeds the 180 s CF timeout |
| `distributionId` | CloudFront distribution ID (for cache invalidations) |

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

# Production S3 bucket uses retainOnDelete — empty and delete it manually
# via the AWS console or CLI before running destroy.
pulumi stack select production
pulumi destroy
```

## Project structure

```
infra/
├── index.ts                # all AWS resources (ECR, VPC, EC2, EIP, S3, CloudFront)
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
