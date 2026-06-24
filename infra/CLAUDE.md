# Infra — Claude Instructions

AWS CDK (TypeScript) project. All infra work lives in `infra/`.

## Running commands

Always run CDK from `infra/`:

```bash
cd infra
npx cdk ls                           # list stacks
npx cdk diff Staging/Clazzziks       # preview changes (staging)
npx cdk diff Production/Clazzziks    # preview changes (production)
npx cdk synth Production/Clazzziks   # emit CloudFormation (no deploy)
npx cdk deploy Production/Clazzziks  # deploy
```

TypeScript must compile before CDK can run. If you see type errors, fix them
before deploying — `npx cdk synth` will catch them.

## File layout

| File | Purpose |
|---|---|
| `lib/config.ts` | `EnvConfig` interface + `STAGING` / `PRODUCTION` values |
| `lib/clazzziks-stage.ts` | `cdk.Stage` wrapper — groups the stack under a named stage |
| `lib/clazzziks-stack.ts` | All AWS resources: EC2, EIP, EBS, S3, CloudFront |
| `bin/infra.ts` | CDK app entry — instantiates both Staging and Production stages |

## Changing environment sizing

Edit `lib/config.ts`. The `EnvConfig` interface documents every field. Changes
take effect on the next `cdk deploy`.

## Adding a new AWS resource

Add it to `lib/clazzziks-stack.ts`. If it needs environment-specific values
(different sizes, retention, etc.) add the field to `EnvConfig` in `config.ts`
and set values in both `STAGING` and `PRODUCTION`.

## Key constraints

- **CloudFront read timeout** is hard-capped at 180 seconds by CDK. Downloads
  that take longer must hit the Elastic IP directly over HTTP.
- **nginx** is configured to proxy port 80 → localhost:8000 with 300 s
  `proxy_read_timeout` and `proxy_send_timeout`. The full nginx config is
  written to `/etc/nginx/nginx.conf` by the EC2 user data script on first boot.
- **EBS device name** — t3 instances are Nitro-based; the OS sees the 50 GiB
  data volume as `/dev/nvme1n1` (not `/dev/xvdf`). The user data waits for
  the device to appear before formatting it.
- **ECR image** — `DockerImageAsset` in `clazzziks-stack.ts` builds and pushes
  the `Dockerfile` at the repo root to a CDK-managed ECR repository. Docker
  must be running locally for `cdk deploy` (or `cdk synth`) to succeed.
- **Frontend must be built before deploying** — `cdk deploy` bundles
  `frontend/dist/` into S3 via `BucketDeployment`. Run
  `cd frontend && pnpm build` first.
- **Production S3 bucket uses `RETAIN`** — `cdk destroy Production/Clazzziks`
  will not delete the bucket. Empty and delete it manually via the AWS console
  or CLI if you truly want a clean teardown.
