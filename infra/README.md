# CLAZZZIKS — Infrastructure

AWS CDK (TypeScript) project that provisions the CLAZZZIKS audio downloader on AWS.

## Architecture

```
CloudFront distribution
  ├── /* ──────────────────→ S3 bucket (React SPA, via OAC)
  └── /api/* ──────────────→ EC2 Elastic IP (180 s read timeout)
                                └── nginx :80 → FastAPI container :8000
```

- **EC2 t3.small / t3.micro** — Amazon Linux 2023 instance running the FastAPI
  backend inside Docker. On first boot the user data script installs Docker,
  pulls the image from ECR, installs nginx, and wires everything up via
  systemd. Staging uses a `t3.micro`; production uses a `t3.small`.
- **EBS 50 GiB gp3** — attached at `/data`; used as ffmpeg scratch space.
  Downloaded audio is written here and streamed back in the same request.
- **Elastic IP** — stable public IPv4 address associated with the instance.
  CloudFront uses it as the `/api/*` HTTP origin.
- **S3 + CloudFront** — the React SPA is uploaded from `frontend/dist/`; the
  distribution is invalidated on every deploy. Unknown paths (403 / 404) return
  `index.html` so the SPA can handle its own routing.
- **ECR repository** — CDK builds the `Dockerfile` at the repo root and pushes
  the image automatically on each `cdk deploy`.

> **CloudFront timeout note:** CDK enforces a 180-second maximum for CloudFront
> custom-origin read timeouts. Downloads that take longer should hit the EC2
> Elastic IP directly over HTTP (`ElasticIpOutput` CloudFormation output).

## Prerequisites

- [Node.js](https://nodejs.org/) 18+
- [AWS CLI](https://aws.amazon.com/cli/) configured (`aws configure`)
- [AWS CDK CLI](https://docs.aws.amazon.com/cdk/latest/guide/cli.html):
  `npm i -g aws-cdk`
- Docker (used by CDK to build and push the backend container image)

## Setup

```bash
cd infra
npm install
```

## Deploy

```bash
# Build the React app first — CDK bundles frontend/dist/ into S3
cd frontend && pnpm install && pnpm build && cd ..

# One-time bootstrap per AWS account + region
cd infra && npx cdk bootstrap

# Deploy
npx cdk deploy Production/Clazzziks
```

Each deploy prints three outputs:

| Output | Description |
|---|---|
| `SiteUrl` | CloudFront HTTPS URL — use this for normal access |
| `ElasticIpOutput` | EC2 Elastic IP (HTTP) — use this if a download exceeds the 180 s CF timeout |
| `DistributionId` | CloudFront distribution ID (for manual cache invalidations) |

## Tear down

```bash
npx cdk destroy Production/Clazzziks
# The S3 bucket uses RETAIN — empty and delete it manually via the AWS console or CLI.
```

## Project structure

```
infra/
├── bin/
│   └── infra.ts            # CDK app entry point (Staging + Production stages)
├── lib/
│   ├── config.ts           # EnvConfig interface + STAGING / PRODUCTION values
│   ├── clazzziks-stage.ts  # cdk.Stage wrapper
│   └── clazzziks-stack.ts  # all AWS resources (EC2, EIP, EBS, S3, CloudFront)
├── cdk.json                # CDK app config + feature flags
├── package.json
└── tsconfig.json
```

## Useful CDK commands

```bash
npx cdk ls                           # list all stacks
npx cdk diff Staging/Clazzziks       # show pending changes (staging)
npx cdk diff Production/Clazzziks    # show pending changes (production)
npx cdk synth Production/Clazzziks   # emit CloudFormation template (no deploy)
npx cdk deploy Production/Clazzziks  # deploy
npx cdk destroy Production/Clazzziks # tear down
```
