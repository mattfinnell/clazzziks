#!/usr/bin/env bash
# Runs on the HOST before the devcontainer is created (initializeCommand) — NOT
# inside the container. Its sole job is to guarantee the host-side sources for
# the bind mounts in devcontainer.json exist before Docker wires them up.
# Idempotent, so it is safe to re-run on every container start.
#
# Why this matters: a single-file bind mount whose source is missing on the host
# gets silently created by Docker as a *directory*, which breaks the mount. We
# pre-create each source as the right kind of thing (dir vs file) here.
set -eu

# Directories bind-mounted into the container (see devcontainer.json "mounts").
# Created empty if absent so each mount has a real directory to map.
for dir in \
  "$HOME/.devcontainer-tmp" \
  "$HOME/.claude" \
  "$HOME/.oh-my-zsh" \
  "$HOME/.aws" \
  "$HOME/.pulumi"; do
  mkdir -p "$dir"
done

# Single-file mount sources must exist as FILES (else Docker makes a directory).
touch "$HOME/.zshrc"

# Pulumi's state dir (~/.pulumi on the host) is bind-mounted to PULUMI_HOME in
# the container, so logins, plugins, and stacks persist across rebuilds. Mounting
# the whole directory (not just credentials.json) lets `pulumi logout`/`login`
# create and remove credentials.json freely. The dir is created in the loop
# above; nothing else to seed.
