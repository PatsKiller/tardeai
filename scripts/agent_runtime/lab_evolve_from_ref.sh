#!/usr/bin/env bash
# Stage and run the LAB evolve packet from one exact reviewed Git commit.
#
# This wrapper never checks out, resets, switches, cleans, or mutates the host worktree.
# It extracts the migration, runtime source, config, and inner proof script from the same
# 40-character commit SHA into a mode-0700 temporary directory, then delegates to the
# fail-closed port-5433 LAB packet.
set -euo pipefail
umask 077

readonly GIT=/usr/bin/git
readonly TAR=/usr/bin/tar
readonly BASH=/usr/bin/bash
readonly REPO_DEFAULT=/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild
readonly REQUIRED_ACK=DISPOSABLE_LAB_NO_PRODUCTION_DATA

if [[ "${LAB_ACK:-}" != "$REQUIRED_ACK" ]]; then
  echo "BLOCKED_LAB_PROVISIONING: set LAB_ACK=$REQUIRED_ACK" >&2
  exit 2
fi
if [[ ! -x "$GIT" || ! -x "$TAR" || ! -x "$BASH" ]]; then
  echo "BLOCKED_LAB_PROVISIONING: required system executable unavailable" >&2
  exit 2
fi

readonly HOST_REPO="${REPO:-$REPO_DEFAULT}"
readonly SOURCE_REF="${AGENTIC_SOURCE_REF:-}"
if [[ ! -d "$HOST_REPO/.git" ]]; then
  echo "BLOCKED_LAB_PROVISIONING: REPO is not a Git worktree: $HOST_REPO" >&2
  exit 2
fi
if [[ ! "$SOURCE_REF" =~ ^[0-9a-fA-F]{40}$ ]]; then
  echo "BLOCKED_LAB_PROVISIONING: AGENTIC_SOURCE_REF must be one exact 40-character commit SHA" >&2
  exit 2
fi
if ! "$GIT" -C "$HOST_REPO" cat-file -e "$SOURCE_REF^{commit}" 2>/dev/null; then
  echo "BLOCKED_LAB_PROVISIONING: reviewed source commit is unavailable locally" >&2
  exit 2
fi

readonly RESOLVED_COMMIT="$("$GIT" -C "$HOST_REPO" rev-parse "$SOURCE_REF^{commit}")"
if [[ "${RESOLVED_COMMIT,,}" != "${SOURCE_REF,,}" ]]; then
  echo "BLOCKED_LAB_PROVISIONING: source ref did not resolve to the exact supplied commit" >&2
  exit 2
fi

required_paths=(
  migrations/agentic_runtime/0001_mvl.up.sql
  migrations/agentic_runtime/0001_mvl.down.sql
  scripts/agent_runtime/lab_evolve_1_to_8.sh
  config/agent_runtime_mvl.json
)
for path in "${required_paths[@]}"; do
  if ! "$GIT" -C "$HOST_REPO" cat-file -e "$RESOLVED_COMMIT:$path" 2>/dev/null; then
    echo "BLOCKED_LAB_PROVISIONING: required reviewed path unavailable at source commit: $path" >&2
    exit 2
  fi
done

readonly STAGE_ROOT="$(mktemp -d /tmp/agentic-lab-source.XXXXXX)"
cleanup() {
  rm -rf "$STAGE_ROOT"
}
trap cleanup EXIT
chmod 700 "$STAGE_ROOT"

# Read only from Git's object database. The dirty/current checkout is not trusted or changed.
"$GIT" -C "$HOST_REPO" archive "$RESOLVED_COMMIT" \
  migrations/agentic_runtime \
  scripts/agent_runtime \
  config/agent_runtime_mvl.json \
  | "$TAR" -x -C "$STAGE_ROOT"

readonly INNER="$STAGE_ROOT/scripts/agent_runtime/lab_evolve_1_to_8.sh"
if [[ ! -f "$INNER" ]]; then
  echo "BLOCKED_LAB_PROVISIONING: staged inner evolve packet unavailable" >&2
  exit 2
fi
chmod 700 "$INNER"

printf 'source_commit|%s\n' "$RESOLVED_COMMIT"
printf 'source_mode|PINNED_GIT_OBJECT_ARCHIVE\n'
printf 'host_worktree_checkout|UNCHANGED\n'
printf 'staged_inner_sha256|'; sha256sum "$INNER" | awk '{print $1}'
printf 'staged_up_migration_sha256|'; sha256sum "$STAGE_ROOT/migrations/agentic_runtime/0001_mvl.up.sql" | awk '{print $1}'
printf 'staged_down_migration_sha256|'; sha256sum "$STAGE_ROOT/migrations/agentic_runtime/0001_mvl.down.sql" | awk '{print $1}'

env LAB_ACK="$LAB_ACK" REPO="$STAGE_ROOT" "$BASH" "$INNER"
