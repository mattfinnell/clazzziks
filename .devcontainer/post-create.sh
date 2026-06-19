#!/usr/bin/env bash
# Runs once on devcontainer creation (postCreateCommand). Idempotent so it is
# safe to re-run. Executes from the workspace folder (/workspaces/clazzziks).
set -u

echo "==> Installing tooling"
npm install -g @anthropic-ai/claude-code || true
# The Python package lives in backend/; install it (with dev extras for tests).
pip install -e './backend[dev]' 2>/dev/null || pip install -r backend/requirements.txt 2>/dev/null || true

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

echo "==> post-create complete"