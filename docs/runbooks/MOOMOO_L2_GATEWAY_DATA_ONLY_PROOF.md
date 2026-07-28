# Moomoo L2 Gateway — Data-Only Host Proof

## Status and authority

This runbook is the operator-controlled proof plan for the dedicated, read-only OpenD owner.
It does not authorize an order route, trading session, schedule, database write, credential read,
trade unlock, 2FA ceremony, paper order, or live order.

The gateway candidate is staged from an exact reviewed Git SHA into a versioned runtime under:

```text
/opt/trade-ai/runtime/moomoo-l2-gateway/<full-sha>/
```

The service runs through the atomic pointer:

```text
/opt/trade-ai/runtime/moomoo-l2-gateway/current
```

It never executes gateway code from the mutable production Git worktree.

The committed systemd unit is inert unless all of these explicit operator facts exist:

1. `/etc/tradeai/moomoo_l2_gateway.yaml` has `enabled: true`;
2. `/etc/tradeai/ENABLE_MOOMOO_L2_GATEWAY` exists;
3. `/etc/tradeai/moomoo_l2_gateway.env` exists and pins `TRADEAI_SOURCE_COMMIT`;
4. the `current` pointer contains `scripts/moomoo/gateway_service.py`.

No repository code creates these activation facts.

## Required provenance

Record before any host action:

```bash
git rev-parse HEAD
git status --short
systemctl show portfolio-server -p ActiveState -p NRestarts
systemctl show tradeai-moomoo-l2-gateway -p ActiveState -p NRestarts 2>/dev/null || true
readlink -f /opt/trade-ai/runtime/moomoo-l2-gateway/current 2>/dev/null || true
```

Preserve unrelated host drift. Do not reset, clean, or check out over runtime-modified files in
the production worktree.

## Pre-deployment gates

Run in an isolated checkout at the exact reviewed SHA:

```bash
python -m pytest -q \
  tests/test_moomoo_gateway_ipc.py \
  tests/test_moomoo_futu_normalizer.py \
  tests/test_moomoo_gateway_service.py \
  tests/test_active_trader_gateway_ipc.py \
  tests/test_active_trader_fire_replay.py \
  tests/test_moomoo_gateway_authority.py

cd apps/command-center-v3
npm ci
npm run build
npx playwright install chromium

npm run preview -- --host 127.0.0.1 --port 4173 --strictPort \
  >/tmp/cc-v3-preview.log 2>&1 &
PREVIEW_PID=$!
trap 'kill "$PREVIEW_PID" 2>/dev/null || true' EXIT

for attempt in $(seq 1 60); do
  if curl -fsS http://127.0.0.1:4173/v3/trading >/dev/null; then
    break
  fi
  sleep 1
done

curl -fsS http://127.0.0.1:4173/v3/trading >/dev/null
PLAYWRIGHT_BASE_URL=http://127.0.0.1:4173 \
  npx playwright test e2e/active-trader-l2-gateway.spec.ts --reporter=line \
  | tee /tmp/active-trader-gateway-playwright.log
```

Do not treat `net::ERR_CONNECTION_REFUSED` as an application assertion failure. It means the
preview server was not started or did not become ready. The required local browser gate is the
focused gateway spec above; the full repository Playwright suite is a separate broader regression
exercise and may require additional backend fixtures.

## Stage the exact-ref candidate without touching main

Set `EXPECTED_SHA` to the reviewed PR head. The shell assignment for
`ALLOW_MAINTREE_GIT` keeps the installed Git wrapper nounset-safe while preserving its normal
primary-tree protections.

```bash
set -euo pipefail
export ALLOW_MAINTREE_GIT=

REPO=/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild
BRANCH=agent/moomoo-l2-gateway-ipc-v1
EXPECTED_SHA=<FULL_REVIEWED_SHA>
RUNTIME_ROOT=/opt/trade-ai/runtime/moomoo-l2-gateway
RELEASE="$RUNTIME_ROOT/$EXPECTED_SHA"

cd "$REPO"
git fetch origin --prune
test "$(git rev-parse "origin/$BRANCH")" = "$EXPECTED_SHA"
git cat-file -e "${EXPECTED_SHA}^{commit}"

sudo install -d -m 0755 "$RUNTIME_ROOT"
sudo install -d -m 0755 /etc/tradeai

if [ ! -d "$RELEASE" ]; then
  sudo install -d -m 0755 "$RELEASE"
  git archive "$EXPECTED_SHA" | sudo tar -x -C "$RELEASE"
  sudo chown -R root:root "$RELEASE"
  sudo chmod -R a-w "$RELEASE"
fi

test -f "$RELEASE/scripts/moomoo/gateway_service.py"

PREVIOUS="$(readlink -f "$RUNTIME_ROOT/current" 2>/dev/null || true)"
printf '%s\n' "$PREVIOUS" | sudo tee /etc/tradeai/moomoo_l2_gateway.previous >/dev/null

sudo ln -sfn "$RELEASE" "$RUNTIME_ROOT/current.next"
sudo mv -Tf "$RUNTIME_ROOT/current.next" "$RUNTIME_ROOT/current"
test "$(readlink -f "$RUNTIME_ROOT/current")" = "$RELEASE"
```

The archive has no `.git` directory. The unit pins provenance through
`TRADEAI_SOURCE_COMMIT`, so the snapshot must report the exact reviewed SHA rather than trying to
infer it from the mutable production checkout.

## Install configuration and unit disabled

```bash
set -euo pipefail

RUNTIME_ROOT=/opt/trade-ai/runtime/moomoo-l2-gateway
RELEASE="$(readlink -f "$RUNTIME_ROOT/current")"
EXPECTED_SHA="$(basename "$RELEASE")"

sudo install -d -m 0755 /etc/tradeai
sudo install -m 0600 \
  "$RELEASE/config/moomoo_l2_gateway.example.yaml" \
  /etc/tradeai/moomoo_l2_gateway.yaml

printf 'TRADEAI_SOURCE_COMMIT=%s\n' "$EXPECTED_SHA" \
  | sudo tee /etc/tradeai/moomoo_l2_gateway.env >/dev/null
sudo chmod 0600 /etc/tradeai/moomoo_l2_gateway.env

sudo install -m 0644 \
  "$RELEASE/config/systemd/tradeai-moomoo-l2-gateway.service" \
  /etc/systemd/system/tradeai-moomoo-l2-gateway.service

sudo rm -f /etc/tradeai/ENABLE_MOOMOO_L2_GATEWAY
sudo systemctl daemon-reload
sudo systemctl disable --now tradeai-moomoo-l2-gateway.service 2>/dev/null || true

grep -Fx 'enabled: false' /etc/tradeai/moomoo_l2_gateway.yaml
grep -Fx "TRADEAI_SOURCE_COMMIT=$EXPECTED_SHA" /etc/tradeai/moomoo_l2_gateway.env
systemctl cat tradeai-moomoo-l2-gateway.service
systemctl show tradeai-moomoo-l2-gateway.service -p ActiveState -p SubState -p NRestarts
```

This installation is inert. It does not start OpenD, the gateway, or any trading path.

## Configuration review

Confirm before activation:

- the exact candidate path and SHA match the reviewed PR head;
- the desired symbol already exists in the canonical
  `data/scalp/moomoo_armed_state.json` or reviewed operator-intent file;
- `TRADEAI_REPO_ROOT` resolves to the canonical production repository only for desired-intent
  reads, not for executable code;
- OpenD is logged in and entitled;
- no other service, cron, probe, or interactive process constructs `OpenQuoteContext`;
- the snapshot, state, lock, and journal directory is owned by `johnclaw` and mode-restricted;
- `portfolio-server` is not restarted for this data-only proof;
- the current production browser/read API is not claimed to contain the candidate read-plane code.

## Explicit activation boundary

Activation requires an exact operator go/no-go tied to the reviewed SHA. Only then:

```bash
set -euo pipefail

EXPECTED_SHA=<FULL_REVIEWED_SHA>
test "$(basename "$(readlink -f /opt/trade-ai/runtime/moomoo-l2-gateway/current)")" = "$EXPECTED_SHA"
grep -Fx "TRADEAI_SOURCE_COMMIT=$EXPECTED_SHA" /etc/tradeai/moomoo_l2_gateway.env

sudo sed -i 's/^enabled: false$/enabled: true/' /etc/tradeai/moomoo_l2_gateway.yaml
grep -Fx 'enabled: true' /etc/tradeai/moomoo_l2_gateway.yaml
sudo install -m 0600 /dev/null /etc/tradeai/ENABLE_MOOMOO_L2_GATEWAY
sudo systemctl enable --now tradeai-moomoo-l2-gateway.service
sudo systemctl status tradeai-moomoo-l2-gateway.service --no-pager
```

This starts market-data ownership only. It does not enable an ActiveTrader session, trade unlock,
2FA, paper order, or live order path.

## Data-only proof

Do not arm a new symbol from the probe. Select one already present in desired intent:

```bash
RUNTIME_ROOT=/opt/trade-ai/runtime/moomoo-l2-gateway/current
PYTHON=/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild/.venv/bin/python

"$PYTHON" "$RUNTIME_ROOT/scripts/moomoo_l2_gateway_probe.py" \
  --symbol AAPL --require-t2 \
  | tee /tmp/moomoo-l2-gateway-proof.json
```

A passing proof must establish, from a fresh atomic snapshot:

- one exclusive owner lock;
- connected and real-time-entitled OpenD;
- provider-reconciled simultaneous quota;
- provider subscriptions for `QUOTE`, `ORDER_BOOK`, and `TICKER`;
- observed confirmation for all required subtypes;
- separate provider and receive timestamps for book, tape, and quote;
- a labeled gateway-local book sequence and provider ticker sequence;
- a fresh current mark;
- durable journal availability;
- exact `source_commit` equal to the reviewed SHA;
- zero order, trade-unlock, session, credential, database-write, and LLM authority.

Keep the service under observation for at least one reconnect or controlled OpenD restart in a
maintenance window. Confirm the reconnect epoch increments, subscriptions reconcile without
duplication, and no stale snapshot is shown as connected.

## Browser and read-plane proof

The mocked browser-capable PR test proves fresh-versus-stale presentation. The production
`portfolio-server` must not be claimed to expose the new gateway endpoints until the read-plane
branch is separately reviewed and deployed. After that deployment, confirm:

- `/api/v3/active-trader/l2-status` identifies the gateway owner and exact source SHA;
- `/api/v3/active-trader/current-marks?symbols=<SYMBOL>` returns fresh timestamps;
- scanner cards retain the immutable scan snapshot while **Current scanner marks** updates;
- stale gateway snapshots display disconnected/unavailable, not live;
- every ActiveTrader order control remains disabled and session authorization remains off.

## Rollback

```bash
set -euo pipefail

RUNTIME_ROOT=/opt/trade-ai/runtime/moomoo-l2-gateway
PREVIOUS="$(sudo cat /etc/tradeai/moomoo_l2_gateway.previous 2>/dev/null || true)"

sudo systemctl disable --now tradeai-moomoo-l2-gateway.service
sudo rm -f /etc/tradeai/ENABLE_MOOMOO_L2_GATEWAY
sudo sed -i 's/^enabled: true$/enabled: false/' /etc/tradeai/moomoo_l2_gateway.yaml

if [ -n "$PREVIOUS" ] && [ -d "$PREVIOUS" ]; then
  sudo ln -sfn "$PREVIOUS" "$RUNTIME_ROOT/current.next"
  sudo mv -Tf "$RUNTIME_ROOT/current.next" "$RUNTIME_ROOT/current"
fi
```

Do not delete the journal or the failed candidate release during rollback. Preserve both for audit
and replay. The HTTP read plane fails closed when the snapshot heartbeat becomes stale. No
`portfolio-server` restart is required for gateway rollback.
