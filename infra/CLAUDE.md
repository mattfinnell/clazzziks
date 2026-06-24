# Infra — Claude Instructions

Pulumi (TypeScript) project. All infra work lives in `infra/`.

## Running commands

Always run from `infra/`. Select a stack before previewing or deploying:

```bash
cd infra
pulumi stack ls                        # list stacks
pulumi stack select staging            # switch to staging
pulumi stack select production         # switch to production

pulumi preview                         # preview changes
pulumi up                              # deploy
pulumi destroy                         # tear down
pulumi stack output siteUrl            # print a specific output
```

TypeScript must compile before Pulumi can run. If you see type errors, fix them
first — `pulumi preview` will catch them.

## File layout

| File | Purpose |
|---|---|
| `index.ts` | All AWS resources: ECR, VPC, EC2, EIP, EBS, S3, CloudFront |
| `Pulumi.yaml` | Pulumi project config |
| `Pulumi.staging.yaml` | Staging stack config (t3.micro, ephemeral bucket) |
| `Pulumi.production.yaml` | Production stack config (t3.small, retained bucket) |

## Changing environment sizing

Edit the relevant `Pulumi.<env>.yaml` file. Changes take effect on the next
`pulumi up`. The config keys are:

| Key | Staging | Production |
|---|---|---|
| `clazzziks:instanceType` | `t3.micro` | `t3.small` |
| `clazzziks:retainBucket` | `false` | `true` |

## Adding a new AWS resource

Add it to `index.ts`. If it needs environment-specific values, read them from
`pulumi.Config` and set them in both `Pulumi.staging.yaml` and
`Pulumi.production.yaml`.

## Key constraints

- **CloudFront read timeout** is hard-capped at 180 seconds. Downloads that take
  longer must hit the Elastic IP directly over HTTP (`elasticIp` stack output).
- **nginx** proxies port 80 → localhost:8000 with 300 s `proxy_read_timeout` and
  `proxy_send_timeout`. The full nginx config is written by the EC2 user data
  script on first boot.
- **EBS device name** — t3 instances are Nitro-based; the OS sees the 50 GiB
  data volume as `/dev/nvme1n1` (not `/dev/xvdf`). The user data polls for the
  device before formatting it.
- **ECR image** — `awsx.ecr.Image` in `index.ts` builds and pushes the
  `Dockerfile` at the repo root. Docker must be running locally for `pulumi up`
  to succeed.
- **Frontend must be built before deploying** — `pulumi up` syncs `frontend/dist/`
  to S3. Run `cd frontend && pnpm build` first.
- **CloudFront cache invalidation is manual** — after deploying a new frontend,
  run: `aws cloudfront create-invalidation --distribution-id <id> --paths '/*'`
  (the `distributionId` stack output has the ID).
- **Production S3 bucket uses `retainOnDelete`** — `pulumi destroy` on the
  production stack will not delete the bucket. Empty and delete it manually via
  the AWS console or CLI if you truly want a clean teardown.
