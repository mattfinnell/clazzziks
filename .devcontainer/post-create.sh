#!/usr/bin/env bash
# Runs once on devcontainer creation (postCreateCommand). Idempotent so it is
# safe to re-run. Executes from the workspace folder (/workspaces/clazzziks).
set -u

echo "==> Installing tooling"
npm install -g @anthropic-ai/claude-code || true
corepack enable pnpm || npm install -g pnpm || true

# Pulumi (infrastructure) is provided by the devcontainer feature
# (ghcr.io/devcontainers-extra/features/pulumi). If it's somehow missing
# (e.g. a feature-less rebuild), install it via the official script.
if ! command -v pulumi >/dev/null 2>&1; then
  curl -fsSL https://get.pulumi.com | sh
fi
# Ensure ~/.pulumi/bin is on PATH for interactive shells (script-install fallback).
grep -qF '.pulumi/bin' "$HOME/.zshrc" 2>/dev/null || echo 'export PATH="$HOME/.pulumi/bin:$PATH"' >> "$HOME/.zshrc"
grep -qF '.pulumi/bin' "$HOME/.bashrc" 2>/dev/null || echo 'export PATH="$HOME/.pulumi/bin:$PATH"' >> "$HOME/.bashrc"
export PATH="$HOME/.pulumi/bin:$PATH"

# Ensure uv is on PATH (installed to /usr/local/bin via Dockerfile symlink).
# If somehow missing (e.g. plain pip-based rebuild), install it now.
if ! command -v uv >/dev/null 2>&1; then
  curl -LsSf https://astral.sh/uv/install.sh | sh
  export PATH="$HOME/.local/bin:$PATH"
fi
# Persist PATH for interactive shells if not already set.
grep -qF '.local/bin' "$HOME/.zshrc" 2>/dev/null || echo 'export PATH="$HOME/.local/bin:$PATH"' >> "$HOME/.zshrc"
grep -qF '.local/bin' "$HOME/.bashrc" 2>/dev/null || echo 'export PATH="$HOME/.local/bin:$PATH"' >> "$HOME/.bashrc"

# The Python package lives in backend/; install it with dev extras via uv.
cd backend && uv sync --extra dev && cd ..

# Install Pulumi (infra) project dependencies.
cd infra && npm install && cd ..

# --- AWS ------------------------------------------------------------------
# AWS credentials come from the host via the ~/.aws bind mount (devcontainer.json),
# so `aws configure` only has to be run once and persists across container
# rebuilds. The default region (us-west-2, matching the Pulumi stacks) is set via
# containerEnv. Verify the credentials resolve; if not, print how to fix it.
# Non-fatal: a fresh clone with no AWS account yet should still finish setup.
echo "==> Checking AWS credentials"
if command -v aws >/dev/null 2>&1; then
  if aws sts get-caller-identity >/dev/null 2>&1; then
    echo "    AWS OK: $(aws sts get-caller-identity --query Arn --output text) (region ${AWS_REGION:-unset})"
  else
    echo "    AWS credentials NOT configured. Run 'aws configure' (here or on the"
    echo "    host — the ~/.aws bind mount keeps them in sync). Region defaults to"
    echo "    us-west-2 via containerEnv, so you can leave the region prompt blank."
  fi
else
  echo "    aws CLI not found (expected from the aws-cli devcontainer feature)."
fi

# --- Docker ---------------------------------------------------------------
# The Dev Containers extension injects a `credsStore` into ~/.docker/config.json
# whose helper doesn't implement the `list` verb. Pulumi's image build (BuildKit)
# calls `list` and fails with "error listing credentials - err: exit status 255".
# Strip the key so Docker falls back to plaintext `auths` (fine for builds).
if [ -f "$HOME/.docker/config.json" ] && command -v python3 >/dev/null 2>&1; then
  echo "==> Removing dev-containers docker credsStore (breaks BuildKit credential listing)"
  python3 - "$HOME/.docker/config.json" <<'PY' || true
import json, sys
p = sys.argv[1]
try:
    with open(p) as f:
        cfg = json.load(f)
except Exception:
    sys.exit(0)
if cfg.pop("credsStore", None) is not None:
    with open(p, "w") as f:
        json.dump(cfg, f, indent=2)
PY
fi

# --- SSH ------------------------------------------------------------------
# The host's keys are bind-mounted read-only at ~/.ssh-localhost. Copy them to
# ~/.ssh so OpenSSH can apply the strict permissions it requires (a read-only
# bind mount can't be chmod'd, and wrong perms make ssh ignore the key).
if [ -d "$HOME/.ssh-localhost" ]; then
  echo "==> Installing SSH keys from host"
  mkdir -p "$HOME/.ssh"
  cp -rf "$HOME/.ssh-localhost/." "$HOME/.ssh/"
  chmod 700 "$HOME/.ssh"
  find "$HOME/.ssh" -type f -exec chmod 600 {} \;
  chmod 644 "$HOME/.ssh/"*.pub 2>/dev/null || true
else
  echo "==> No host ~/.ssh mounted (skipping SSH key install)"
fi

# Trust GitHub's host key so the first git@ connection doesn't prompt/fail.
echo "==> Trusting github.com host key"
ssh-keyscan -t rsa,ecdsa,ed25519 github.com >> "$HOME/.ssh/known_hosts" 2>/dev/null || true
if [ -f "$HOME/.ssh/known_hosts" ]; then
  sort -u "$HOME/.ssh/known_hosts" -o "$HOME/.ssh/known_hosts"
  chmod 644 "$HOME/.ssh/known_hosts"
fi

# --- Shell config ---------------------------------------------------------
# ~/.oh-my-zsh-host is a read-only bind-mount of the host's Oh My Zsh install
# (its themes plus $ZSH_CUSTOM — the custom plugins the host .zshrc expects,
# e.g. zsh-autosuggestions / zsh-syntax-highlighting). Copy it over the
# container's default OMZ so the shell has the same plugins/themes. Copying
# (rather than sourcing the read-only mount) lets OMZ write its cache/update
# files without mutating the host install. The -n test skips an empty mount
# (host had no ~/.oh-my-zsh, so initializeCommand created an empty stub).
if [ -d "$HOME/.oh-my-zsh-host" ] && [ -n "$(ls -A "$HOME/.oh-my-zsh-host" 2>/dev/null)" ]; then
  echo "==> Importing host Oh My Zsh"
  rm -rf "$HOME/.oh-my-zsh"
  cp -rf "$HOME/.oh-my-zsh-host" "$HOME/.oh-my-zsh"
else
  echo "==> No host ~/.oh-my-zsh mounted (keeping container default)"
fi

# ~/.zshrc-host is a live bind-mount of the host's ~/.zshrc. Source it from
# within the container's ~/.zshrc so every shell start picks up host config.
echo "==> Wiring host .zshrc"
grep -qF 'zshrc-host' "$HOME/.zshrc" || echo '[ -f ~/.zshrc-host ] && source ~/.zshrc-host' >> "$HOME/.zshrc"

# --- Git ------------------------------------------------------------------
echo "==> Configuring git remote 'origin'"
git config --global --add safe.directory /workspaces/clazzziks
REMOTE_URL="git@github.com:mattfinnell/clazzziks.git"
if git -C /workspaces/clazzziks remote get-url origin >/dev/null 2>&1; then
  git -C /workspaces/clazzziks remote set-url origin "$REMOTE_URL"
else
  git -C /workspaces/clazzziks remote add origin "$REMOTE_URL"
fi
git -C /workspaces/clazzziks remote -v

# --- pre-commit -----------------------------------------------------------
# The pre-commit binary is installed by the devcontainer feature. Install the
# git hook only if the repo ships a config.
if [ -f "$PWD/.pre-commit-config.yaml" ] && [ -d "$PWD/.git" ]; then
  echo "==> Installing pre-commit hook"
  pre-commit install || true
else
  echo "==> No .pre-commit-config.yaml / git repo (skipping pre-commit install)"
fi

echo "==> post-create complete"
