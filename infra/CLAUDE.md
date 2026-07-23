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

Resources are organized by component. `index.ts` is a thin orchestrator that
wires the component factories together and exports the stack outputs; each file
under `components/` owns one slice of the architecture.

| File | Purpose |
|---|---|
| `index.ts` | Orchestrator: calls the component factories in dependency order, exports outputs |
| `config.ts` | Shared config (per-stack values), `tags`, `region`, `accountId`, `REPO_ROOT` |
| `components/network.ts` | VPC + security groups (instance, db) |
| `components/image.ts` | ECR repository + Docker image build/push |
| `components/secrets.ts` | Secrets Manager entries (admin email, Firebase) |
| `components/database.ts` | RDS subnet group + Postgres instance (+ master secret ARN) |
| `components/iam.ts` | Instance role + profile + secrets read policy |
| `components/userdata.ts` | EC2 first-boot script builder |
| `components/compute.ts` | AMI lookup + EC2 instance + Elastic IP + association |
| `components/frontend.ts` | S3 bucket + public-access block + `dist/` sync |
| `components/cdn.ts` | CloudFront + OAC + S3 bucket policy |
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

Add it to the relevant `components/<area>.ts` file (or a new one), exporting any
handle other components need from its factory, and wire it in `index.ts`. Keep a
resource's first-arg **name string stable** when moving code between files — the
Pulumi URN is derived from it, so renaming forces a destroy/recreate. If the
resource needs environment-specific values, read them in `config.ts` from
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
- **HTTPS is edge-enforced.** Every CloudFront behavior uses
  `viewerProtocolPolicy: redirect-to-https` and attaches a `ResponseHeadersPolicy`
  (`security-headers` in `cdn.ts`) that adds **HSTS**. The CloudFront↔origin hop is
  intentionally HTTP (nginx :80); there is no ACM cert / custom domain (the default
  CloudFront cert terminates TLS at the edge).
- **The API behaviors are `/graphql` and `/files/*`** (was a single `/api/*` before
  the GraphQL migration), both proxying to the EC2 origin.
- **CloudFront read timeout** for the API origin is set to **60 s** in
  `cdn.ts` (`originReadTimeout`). 60 s is the default account maximum; values up
  to 180 s require a Service Quotas increase for CloudFront's "Origin response
  timeout" (without it, `pulumi up` fails with `InvalidOriginReadTimeout`).
  Downloads that take longer must hit the Elastic IP directly over HTTP
  (`elasticIp` stack output), which reaches nginx (300 s) and bypasses CloudFront.
- **The API origin domain is the EIP's public DNS** (`eip.publicDns`), not the
  raw IP — CloudFront rejects an IP address as an origin domain name.
- **nginx** proxies port 80 → localhost:8000 with 300 s `proxy_read_timeout` and
  `proxy_send_timeout`. The full nginx config is written by the EC2 user data
  script on first boot.
- **WebSockets** (the `progress` GraphQL subscription rides `/graphql` over WS):
  nginx sets `proxy_http_version 1.1` and the `Upgrade`/`Connection` headers via a
  `map $http_upgrade $connection_upgrade` block (in `userdata.ts`) so the handshake
  proxies through. CloudFront needs no extra config — the `/graphql` behavior already
  forwards all headers (`headers: ['*']`) and is uncacheable, so it passes WS through.
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

## Deploying

Datacenter: **us-west-2** (set in both `Pulumi.staging.yaml` and `Pulumi.production.yaml`;
`config.ts` reads it from `aws.config.region`).

**Status:** `staging` is deployed to the **`mattfinnell` Pulumi Cloud org**
(`app.pulumi.com/mattfinnell/clazzziks/staging`). The devcontainer's throwaway
ephemeral Pulumi agent org is unused (empty) and can be ignored — it expires on
its own; don't claim it.

### One-time environment setup (resolved on this machine)
- [x] **AWS credentials** — `aws configure` done; `~/.aws` is bind-mounted from the
      host (`.devcontainer/devcontainer.json`) so it persists across rebuilds.
      `post-create.sh` verifies them. Region defaults to us-west-2 via containerEnv.
- [x] **Pulumi backend** — own Pulumi Cloud via `pulumi login` (not the ephemeral
      agent org). `pulumi whoami` → `mattfinnell`.
- [x] **IAM permissions** — the deploying user needs to create EC2/VPC, RDS, S3,
      CloudFront, ECR, IAM, and Secrets Manager resources; `AdministratorAccess`
      attached (scoped alternative in `README.md`). Symptom if missing:
      `UnauthorizedOperation` 403 on the first `pulumi preview` (`ec2:DescribeImages`).
      A user can't self-grant — attach from the console as account root.
- [x] **Docker credsStore** — the devcontainer's injected `credsStore` helper has
      no `list` verb, so the image build dies with `error listing credentials -
      err: exit status 255`. `post-create.sh` strips it automatically on create.

### Deploy a stack (reusable — e.g. for production)
1. `cd infra && pulumi stack init <env>` (skip if the stack already exists).
2. `pulumi config set --secret clazzziks:adminEmail <you@example.com>`
   (seeded as VIP + admin on every boot; Firebase auth optional — leave unset to run open).
3. Build the frontend: `cd frontend && pnpm install && pnpm build`.
4. `cd infra && pulumi preview` then `pulumi up` (real, billable AWS infra; Docker must be running).
5. **If Firebase auth is enabled:** add the CloudFront domain
   (`pulumi stack output siteUrl` host) to Firebase Console → Authentication →
   Settings → **Authorized domains**, or Google sign-in fails with
   `auth/unauthorized-domain`. The domain is stable across `pulumi up`.
6. After a frontend change, invalidate the CDN cache:
   `aws cloudfront create-invalidation --distribution-id $(pulumi stack output distributionId) --paths '/*'`.

EC2 user-data boot (mount /data → Docker → image pull → nginx) takes a few minutes
after `up` returns; the API may 502/504 briefly before it's live.

### Verify
- `pulumi stack output siteUrl` → open the CloudFront HTTPS URL in a browser.
- `curl http://$(pulumi stack output elasticIp)/health` → direct EIP (bypasses the 60 s CF timeout); expect `{"status":"ok"}` once booted. A GraphQL probe: `curl -s http://$(pulumi stack output elasticIp)/graphql -H 'content-type: application/json' -d '{"query":"{ config { formats } }"}'`.
- `pulumi stack output dbEndpoint` → RDS hostname (private).
- Boot debugging: `aws ec2 get-console-output --region us-west-2 --instance-id <id> | tail -40`.
