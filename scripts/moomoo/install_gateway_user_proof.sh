#!/usr/bin/env bash
set -euo pipefail

# Stage the exact reviewed gateway SHA into a user-owned immutable runtime and
# install a disabled systemd --user proof unit. This script never creates the
# activation marker and never starts OpenD or the gateway.

EXPECTED_SHA="${1:-${EXPECTED_SHA:-}}"
BRANCH="${2:-${BRANCH:-agent/moomoo-l2-gateway-ipc-v1}}"
REPO="${TRADEAI_REPO_ROOT:-$HOME/trade-ai-v12-rebuild/trade-ai-v12-rebuild}"
RUNTIME_ROOT="${TRADEAI_GATEWAY_RUNTIME_ROOT:-$HOME/.local/share/tradeai/runtime/moomoo-l2-gateway}"
CONFIG_ROOT="${TRADEAI_GATEWAY_CONFIG_ROOT:-$HOME/.config/tradeai}"
UNIT_ROOT="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
RELEASE="$RUNTIME_ROOT/$EXPECTED_SHA"
CURRENT="$RUNTIME_ROOT/current"
UNIT_NAME="tradeai-moomoo-l2-gateway-proof.service"

fail() {
  printf 'gateway user-proof install failed: %s\n' "$*" >&2
  exit 1
}

[ -n "$EXPECTED_SHA" ] || fail "expected SHA is required as argument 1 or EXPECTED_SHA"
[[ "$EXPECTED_SHA" =~ ^[0-9a-f]{40}$ ]] || fail "expected SHA must be a full 40-character lowercase Git SHA"
git -C "$REPO" rev-parse --git-dir >/dev/null 2>&1 || fail "repository not found at $REPO"

cd "$REPO"
git fetch origin "$BRANCH:refs/remotes/origin/$BRANCH" --quiet
REMOTE_SHA="$(git rev-parse "origin/$BRANCH")"
[ "$REMOTE_SHA" = "$EXPECTED_SHA" ] || fail "origin/$BRANCH is $REMOTE_SHA, expected $EXPECTED_SHA"
git cat-file -e "${EXPECTED_SHA}^{commit}"

mkdir -p "$RUNTIME_ROOT" "$CONFIG_ROOT" "$UNIT_ROOT"
chmod 0700 "$CONFIG_ROOT"

if [ ! -d "$RELEASE" ]; then
  mkdir -p "$RELEASE"
  git archive "$EXPECTED_SHA" | tar -x -C "$RELEASE"
  chmod -R a-w "$RELEASE"
fi

[ -f "$RELEASE/scripts/moomoo/gateway_service.py" ] || fail "candidate gateway entry point missing"
[ -f "$RELEASE/config/moomoo_l2_gateway.example.yaml" ] || fail "candidate config missing"
[ -f "$RELEASE/config/systemd/user/$UNIT_NAME" ] || fail "candidate user unit missing"

PREVIOUS="$(readlink -f "$CURRENT" 2>/dev/null || true)"
printf '%s\n' "$PREVIOUS" >"$CONFIG_ROOT/moomoo_l2_gateway_proof.previous"
chmod 0600 "$CONFIG_ROOT/moomoo_l2_gateway_proof.previous"

ln -sfn "$RELEASE" "$RUNTIME_ROOT/current.next"
mv -Tf "$RUNTIME_ROOT/current.next" "$CURRENT"
[ "$(readlink -f "$CURRENT")" = "$RELEASE" ] || fail "current pointer did not resolve to exact release"

install -m 0600 \
  "$RELEASE/config/moomoo_l2_gateway.example.yaml" \
  "$CONFIG_ROOT/moomoo_l2_gateway_proof.yaml"

grep -Fx 'enabled: false' "$CONFIG_ROOT/moomoo_l2_gateway_proof.yaml" >/dev/null

printf 'TRADEAI_SOURCE_COMMIT=%s\n' "$EXPECTED_SHA" \
  >"$CONFIG_ROOT/moomoo_l2_gateway_proof.env"
chmod 0600 "$CONFIG_ROOT/moomoo_l2_gateway_proof.env"

install -m 0644 \
  "$RELEASE/config/systemd/user/$UNIT_NAME" \
  "$UNIT_ROOT/$UNIT_NAME"

rm -f "$CONFIG_ROOT/ENABLE_MOOMOO_L2_GATEWAY_PROOF"
systemctl --user daemon-reload
systemctl --user disable --now "$UNIT_NAME" >/dev/null 2>&1 || true

ACTIVE_STATE="$(systemctl --user show "$UNIT_NAME" -p ActiveState --value 2>/dev/null || true)"
SUB_STATE="$(systemctl --user show "$UNIT_NAME" -p SubState --value 2>/dev/null || true)"

cat <<EOF
{
  "contract": "moomoo-l2-gateway-user-proof-install-v1",
  "source_commit": "$EXPECTED_SHA",
  "branch": "$BRANCH",
  "release": "$RELEASE",
  "current": "$(readlink -f "$CURRENT")",
  "config_enabled": false,
  "activation_marker_present": false,
  "unit": "$UNIT_NAME",
  "active_state": "${ACTIVE_STATE:-unknown}",
  "sub_state": "${SUB_STATE:-unknown}",
  "trade_authority": "none"
}
EOF
