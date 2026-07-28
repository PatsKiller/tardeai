# Moomoo L2 Gateway — Data-Only Host Proof

## Status and authority

This runbook is **not** deployment authorization. It is the post-review proof plan for the
dedicated, read-only OpenD owner. It must not be run from an unmerged draft branch and must
not change an order route, trading session, schedule, database, credential, or 2FA state.

The committed systemd unit is inert unless both of these explicit operator facts exist:

1. `/etc/tradeai/moomoo_l2_gateway.yaml` has `enabled: true`;
2. `/etc/tradeai/ENABLE_MOOMOO_L2_GATEWAY` exists.

No repository code creates either fact.

## Required provenance

Record before any host action:

```bash
git rev-parse HEAD
git status --short
systemctl show portfolio-server -p ActiveState -p NRestarts
systemctl show tradeai-moomoo-l2-gateway -p ActiveState -p NRestarts 2>/dev/null || true
```

The expected source SHA must be the reviewed gateway PR head. Preserve unrelated host drift;
do not reset or checkout over runtime-modified files.

## Pre-deployment gates

Run in an isolated checkout:

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
npx playwright install --with-deps chromium
npm run preview -- --host 127.0.0.1 --port 4173 &
PLAYWRIGHT_BASE_URL=http://127.0.0.1:4173 npx playwright test e2e/active-trader-l2-gateway.spec.ts
```

## Configuration review

Copy the example outside the repository and review every path. The file contains no secret.
Keep the service disabled while reviewing:

```bash
sudo install -m 0600 config/moomoo_l2_gateway.example.yaml /etc/tradeai/moomoo_l2_gateway.yaml
sudo install -m 0644 config/systemd/tradeai-moomoo-l2-gateway.service /etc/systemd/system/tradeai-moomoo-l2-gateway.service
sudo systemctl daemon-reload
```

Confirm:

- the desired symbol already exists in `data/scalp/moomoo_armed_state.json` or the reviewed
  operator-intent file;
- OpenD is logged in and entitled;
- no other service or cron process constructs `OpenQuoteContext`;
- the snapshot, state, lock, and journal directories are writable only by the service user;
- `portfolio-server` is not restarted for this proof.

## Explicit activation boundary

Activation requires a separate operator go/no-go. Only then:

```bash
sudo sed -i 's/^enabled: false$/enabled: true/' /etc/tradeai/moomoo_l2_gateway.yaml
sudo install -m 0600 /dev/null /etc/tradeai/ENABLE_MOOMOO_L2_GATEWAY
sudo systemctl enable --now tradeai-moomoo-l2-gateway.service
```

This starts market-data ownership only. It does not enable an ActiveTrader session or any
paper/live order path.

## Data-only proof

Do not arm a new symbol from the probe. Select one already present in desired intent:

```bash
python scripts/moomoo_l2_gateway_probe.py --symbol AAPL --require-t2 \
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
- zero order/trade-unlock/session authority.

Keep the service under observation for at least one reconnect or controlled OpenD restart in
a maintenance window. Confirm the reconnect epoch increments, subscriptions reconcile without
duplication, and no stale snapshot is shown as connected.

## Browser proof

Against the running read-only server, confirm:

- `/api/v3/active-trader/l2-status` identifies the gateway owner and exact source SHA;
- `/api/v3/active-trader/current-marks?symbols=<SYMBOL>` returns fresh timestamps;
- scanner cards retain the immutable scan snapshot while **Current scanner marks** updates;
- stale gateway snapshots display disconnected/unavailable, not live;
- every ActiveTrader order control remains disabled and session authorization remains off.

## Rollback

```bash
sudo systemctl disable --now tradeai-moomoo-l2-gateway.service
sudo rm -f /etc/tradeai/ENABLE_MOOMOO_L2_GATEWAY
```

Do not delete the journal during rollback; preserve it for audit/replay. The HTTP read plane
fails closed when the snapshot heartbeat becomes stale. No portfolio-server restart is needed.
