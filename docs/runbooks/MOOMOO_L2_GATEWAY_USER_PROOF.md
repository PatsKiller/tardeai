# Moomoo L2 Gateway — No-Sudo User Proof

## Purpose

This is the accelerated data-only proof path for the dedicated Moomoo/OpenD gateway.
It avoids the root-owned production installation while preserving the same exact-SHA,
single-owner, fail-closed boundaries.

It does **not** authorize or enable:

- trade unlock;
- a paper or live order;
- an Active Trader session;
- 2FA;
- a database write;
- a production feature flag;
- a production service deployment.

The proof runtime is installed under:

```text
~/.local/share/tradeai/runtime/moomoo-l2-gateway/<full-sha>/
```

The disabled user unit is installed at:

```text
~/.config/systemd/user/tradeai-moomoo-l2-gateway-proof.service
```

The unit cannot start unless the operator separately creates:

```text
~/.config/tradeai/ENABLE_MOOMOO_L2_GATEWAY_PROOF
```

The installer never creates that marker.

## 1. Install the exact reviewed SHA, disabled

Run from the canonical production repository as `johnclaw`. The production checkout may remain on
`main` and may remain dirty: the installer is extracted directly from the exact reviewed remote SHA
into a temporary file, then the candidate itself is staged with `git archive`.

```bash
set -euo pipefail

REPO=/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild
BRANCH=agent/moomoo-l2-gateway-ipc-v1
cd "$REPO"

git fetch origin "$BRANCH:refs/remotes/origin/$BRANCH"
EXPECTED_SHA="$(git rev-parse "origin/$BRANCH")"
INSTALLER="$(mktemp)"
trap 'rm -f "$INSTALLER"' EXIT

git show "$EXPECTED_SHA:scripts/moomoo/install_gateway_user_proof.sh" >"$INSTALLER"
chmod 0700 "$INSTALLER"
TRADEAI_REPO_ROOT="$REPO" bash "$INSTALLER" "$EXPECTED_SHA" "$BRANCH"
```

Expected results:

- the candidate is archived from the exact remote SHA;
- the release tree is read-only;
- `current` points to that exact release;
- the copied YAML remains `enabled: false`;
- the activation marker is absent;
- the user service is disabled and inactive;
- no OpenD or gateway process is started;
- the production checkout branch, index, and working tree are not changed.

## 2. Inspect before activation

```bash
EXPECTED_SHA="$(git rev-parse origin/agent/moomoo-l2-gateway-ipc-v1)"

readlink -f ~/.local/share/tradeai/runtime/moomoo-l2-gateway/current
cat ~/.config/tradeai/moomoo_l2_gateway_proof.env
grep -Fx 'enabled: false' ~/.config/tradeai/moomoo_l2_gateway_proof.yaml
systemctl --user cat tradeai-moomoo-l2-gateway-proof.service
systemctl --user show tradeai-moomoo-l2-gateway-proof.service \
  -p ActiveState -p SubState -p NRestarts

test "$(basename "$(readlink -f ~/.local/share/tradeai/runtime/moomoo-l2-gateway/current)")" = "$EXPECTED_SHA"
test ! -e ~/.config/tradeai/ENABLE_MOOMOO_L2_GATEWAY_PROOF
```

## 3. Explicit data-only activation

Activation remains a separate operator act tied to the reviewed SHA.
It starts the quote gateway only.

```bash
set -euo pipefail

EXPECTED_SHA="$(git rev-parse origin/agent/moomoo-l2-gateway-ipc-v1)"
test "$(basename "$(readlink -f ~/.local/share/tradeai/runtime/moomoo-l2-gateway/current)")" = "$EXPECTED_SHA"
grep -Fx "TRADEAI_SOURCE_COMMIT=$EXPECTED_SHA" ~/.config/tradeai/moomoo_l2_gateway_proof.env

sed -i 's/^enabled: false$/enabled: true/' ~/.config/tradeai/moomoo_l2_gateway_proof.yaml
grep -Fx 'enabled: true' ~/.config/tradeai/moomoo_l2_gateway_proof.yaml
install -m 0600 /dev/null ~/.config/tradeai/ENABLE_MOOMOO_L2_GATEWAY_PROOF

systemctl --user enable --now tradeai-moomoo-l2-gateway-proof.service
systemctl --user status tradeai-moomoo-l2-gateway-proof.service --no-pager
```

## 4. Prove real data

Select a symbol that already exists in canonical desired intent. Do not create a new trading
candidate from the proof command.

```bash
RUNTIME=~/.local/share/tradeai/runtime/moomoo-l2-gateway/current
PYTHON=/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild/.venv/bin/python

"$PYTHON" "$RUNTIME/scripts/moomoo_l2_gateway_probe.py" \
  --symbol AAPL --require-t2 \
  | tee /tmp/moomoo-l2-gateway-user-proof.json
```

A valid proof requires:

- one exclusive owner lock;
- OpenD connected and real-time entitled;
- provider-reconciled quota;
- provider subscriptions for quote, order book, and ticker;
- observed subtype confirmation;
- fresh quote, book, and tape receive timestamps;
- labeled sequence provenance;
- a current mark;
- a durable journal;
- exact `source_commit` equality;
- zero order, trade-unlock, session, 2FA, database-write, or LLM authority.

## 5. Roll back

```bash
set -euo pipefail

systemctl --user disable --now tradeai-moomoo-l2-gateway-proof.service
rm -f ~/.config/tradeai/ENABLE_MOOMOO_L2_GATEWAY_PROOF
sed -i 's/^enabled: true$/enabled: false/' ~/.config/tradeai/moomoo_l2_gateway_proof.yaml

PREVIOUS="$(cat ~/.config/tradeai/moomoo_l2_gateway_proof.previous 2>/dev/null || true)"
if [ -n "$PREVIOUS" ] && [ -d "$PREVIOUS" ]; then
  ln -sfn "$PREVIOUS" ~/.local/share/tradeai/runtime/moomoo-l2-gateway/current.next
  mv -Tf \
    ~/.local/share/tradeai/runtime/moomoo-l2-gateway/current.next \
    ~/.local/share/tradeai/runtime/moomoo-l2-gateway/current
fi
```

Preserve the journal and failed release for replay and audit.
