#!/usr/bin/env bash
# Runs once on devcontainer creation (postCreateCommand). Idempotent so it is
# safe to re-run. Executes from the workspace folder (/workspaces/clazzziks).
set -u

echo "==> Installing tooling"
npm install -g @anthropic-ai/claude-code || true
corepack enable pnpm || npm install -g pnpm || true
npm install -g aws-cdk || true

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

# Install CDK project dependencies.
cd infra && npm install && cd ..

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

echo "==> post-create complete"