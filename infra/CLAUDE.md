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
| `index.ts` | All AWS resources: ECR, VPC, EC2, EIP, EBS, RDS, Secrets Manager, S3, CloudFront |
| `Pulumi.yaml` | Pulumi project config |
| `Pulumi.staging.yaml` | Staging stack config (t3.micro, db.t4g.micro, ephemeral) |
| `Pulumi.production.yaml` | Production stack config (t3.small, durable DB, retained bucket) |

## Changing environment sizing

Edit the relevant `Pulumi.<env>.yaml` file. Changes take effect on the next
`pulumi up`. The config keys are:

| Key | Staging | Production | Notes |
|---|---|---|---|
| `clazzziks:instanceType` | `t3.micro` | `t3.small` | EC2 size |
| `clazzziks:retainBucket` | `false` | `true` | retain S3 bucket + RDS final snapshot |
| `clazzziks:dbInstanceClass` | `db.t4g.micro` | `db.t4g.micro` | RDS size |
| `clazzziks:dbAllocatedStorage` | `20` | `20` | GiB |
| `clazzziks:dbBackupRetentionDays` | `1` | `7` | automated backup window |
| `clazzziks:dbDeletionProtection` | `false` | `true` | blocks accidental DB destroy |
| `clazzziks:rateLimit` | `20` | `20` | `CLAZZZIKS_RATE_LIMIT` |
| `clazzziks:rateWindowSeconds` | `3600` | `3600` | `CLAZZZIKS_RATE_WINDOW_SECONDS` |

### Secrets (per stack, set out-of-band — not committed)

```bash
pulumi config set --secret clazzziks:adminEmail you@example.com   # CLAZZZIKS_ADMIN_EMAIL (DB owner seed)
pulumi config set --secret clazzziks:firebaseCredentials "$(cat sa.json)"
pulumi config set clazzziks:firebaseProjectId <project-id>
pulumi config set clazzziks:allowedEmails a@x.com,b@y.com # TODO : Does this need to exist if allowed emails are in RDS?
```

The **admin email is a secret** — stored in Secrets Manager and fetched onto the
instance at boot, so it never lands in plaintext config, stack state, or user
data. Leave `firebaseCredentials` unset to run the env open (auth off), matching
the backend's secret-free fallback. The DB password is **never** set by hand —
RDS generates and rotates it in Secrets Manager (`manageMasterUserPassword`).

## Adding a new AWS resource

Add it to `index.ts`. If it needs environment-specific values, read them from
`pulumi.Config` and set them in both `Pulumi.staging.yaml` and
`Pulumi.production.yaml`.

## Key constraints

- **Database is RDS Postgres** — one managed instance per stack, in the VPC's
  public subnets but `publiclyAccessible: false` and SG-locked to the instance SG
  (only the EC2 box reaches `:5432`). The VPC spans **2 AZs** because an RDS DB
  subnet group requires at least two; there is still **no NAT gateway**.
- **No DB password in code or config** — RDS uses `manageMasterUserPassword`, so
  the password is generated and rotated in Secrets Manager. The EC2 user data
  fetches the secret at boot via the instance IAM role and assembles
  `CLAZZZIKS_DATABASE_URL`. Same pattern for the optional Firebase secret. The
  IAM `RolePolicy` grants `secretsmanager:GetSecretValue` on exactly those ARNs.
- **Container env vars are wired in user data** — `docker run` receives
  `CLAZZZIKS_DATABASE_URL` plus the non-secret knobs and (when Firebase is set)
  `CLAZZZIKS_FIREBASE_CREDENTIALS` pointing at `/data/firebase.json`.
- **CloudFront read timeout** for the `/api/*` origin is set to **60 s** in
  `index.ts` (`originReadTimeout`). 60 s is the default account maximum; values up
  to 180 s require a Service Quotas increase for CloudFront's "Origin response
  timeout" (without it, `pulumi up` fails with `InvalidOriginReadTimeout`).
  Downloads that take longer must hit the Elastic IP directly over HTTP
  (`elasticIp` stack output), which reaches nginx (300 s) and bypasses CloudFront.
- **CloudFront `/api/*` origin is the EIP's public DNS** (`eip.publicDns`), not the
  raw IP — CloudFront rejects an IP address as an origin domain name.
- **nginx** proxies port 80 → localhost:8000 with 300 s `proxy_read_timeout` and
  `proxy_send_timeout`. The full nginx config is written by the EC2 user data
  script on first boot.
- **EBS device name** — t3 instances are Nitro-based; the OS sees the 50 GiB
  data volume as `/dev/nvme1n1` (not `/dev/xvdf`). The user data polls for the
  device before formatting it.
- **Docker storage lives on `/data`** — user data writes `/etc/docker/daemon.json`
  with `data-root: /data/docker` before starting Docker, so images and container
  layers land on the 50 GiB volume. The AL2023 root volume (~8 GiB) is too small
  for the ffmpeg-based image; pulling onto root fails with "no space left on
  device", which aborts the `set -e` user-data script before nginx starts (symptom:
  port 80 dead, CloudFront 504).
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
- **Production RDS is protected** — `dbDeletionProtection: true` and a final
  snapshot mean `pulumi destroy` on production fails until you flip
  `clazzziks:dbDeletionProtection` to `false` and `pulumi up`. Staging skips the
  final snapshot and tears down cleanly.

## TODO — Configure Pulumi & deploy staging (2026-06-26)

Goal: configure Pulumi and see CLAZZZIKS running in **staging** on AWS.

Datacenter: **us-west-2** (set in both `Pulumi.staging.yaml` and `Pulumi.production.yaml`;
`index.ts` reads it from `aws.config.region`).

Blockers found in devcontainer (must fix first — both are mine to do, interactive):
- [ ] **AWS credentials missing** (`aws sts get-caller-identity` -> NoCredentials).
      Run `aws configure` once — `~/.aws` is bind-mounted from the host
      (`.devcontainer/devcontainer.json`), so creds persist across rebuilds and
      `post-create.sh` verifies them on setup. Region defaults to us-west-2 via
      containerEnv (and is pinned to us-west-2 in Pulumi.staging.yaml).
- [ ] **Pulumi backend** is a throwaway ephemeral agent account, no real stacks.
      Decision: use my own Pulumi Cloud — `pulumi logout && pulumi login`.
      (Alternatives, not chosen: `pulumi login --local`, or claim the ephemeral org
      within ~3 days at https://app.pulumi.com/claim/019efd80-dbf6-7437-ada8-c8cf7c715ea1
      — claiming locks the org during the process, so it'd have to be done AFTER deploying.)

Also required (discovered during the first staging deploy):
- [ ] **IAM permissions** — the deploying user needs to create EC2/VPC, RDS, S3,
      CloudFront, ECR, IAM, and Secrets Manager resources. Attach
      `AdministratorAccess` (simplest, durable) or the scoped union listed in
      `README.md`. Symptom if missing: `UnauthorizedOperation` 403 on the first
      `pulumi preview` (`ec2:DescribeImages`). Self-grant is impossible — attach
      from the console as account root.
- [ ] **Docker credsStore** — the devcontainer's injected `credsStore` helper has
      no `list` verb, so the image build dies with `error listing credentials -
      err: exit status 255`. `post-create.sh` now strips it automatically; after a
      manual config change, re-run that script or delete the `credsStore` key.

Already OK: Pulumi CLI v3.248.0, AWS CLI v2, Docker running.

Deploy steps once unblocked:
- [ ] `cd infra && pulumi stack init staging`   (config file exists; stack does not)
- [ ] `pulumi config set --secret clazzziks:adminEmail mattfinnell104@gmail.com`
      (Firebase auth optional - leave unset to run open)
- [ ] Build frontend (dist/ is empty): `cd frontend && pnpm install && pnpm build`
- [ ] `cd infra && pulumi preview`  then  `pulumi up`  (real billable AWS infra)
- [ ] Note: EC2 user-data boot (Docker/nginx/secret fetch/image pull) takes a few
      min after `up` returns - API may 502 briefly before it's live.

Verify staging:
- [ ] `pulumi stack output siteUrl`     -> open CloudFront HTTPS URL in browser
- [ ] `curl http://$(pulumi stack output elasticIp)/api/...`  (direct EIP, bypasses 60s CF timeout)
- [ ] `pulumi stack output dbEndpoint`  -> RDS hostname (private)
