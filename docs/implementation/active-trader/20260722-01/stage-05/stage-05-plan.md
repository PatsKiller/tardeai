# Stage 5 Plan — Isolated Moomoo OpenD Data Gateway (v1.2 launcher)

**Run ID:** 20260722-01 · **Start HEAD:** f070288ed77ff9c88f52e29523ff9d8fddcd5a1c
**Branch:** feat/active-trader-next · PR #150 (draft) · **Market-data ONLY** — no trade
context, no unlock, no order operation of any kind.

## Host gate (verified before this plan)
Ubuntu 26.04 LTS · x86_64 · glibc 2.43 · Python interpreters installed: 3.14.4 only
(highest and only candidate — SDK+PyArrow import test is part of acceptance) · disk
265G free (≫ 10 GiB minimum; replay budget 20 GiB) · RAM 61 GiB · chrony synced
(stratum 3) · ports 11111/11112 free · production services untouched throughout.

## Official sources and pins (verified before this plan)
| Component | Pin | Source | Hash status |
|---|---|---|---|
| moomoo-api | 10.9.6908 (PyPI latest — no newer candidate) | PyPI sdist `moomoo_api-10.9.6908.tar.gz` | sha256 verified equal to launcher pin `6df0370e…0304` |
| OpenD | 10.9.6908 Ubuntu command-line | `https://softwaredownload.futustatic.com/moomoo_OpenD_10.9.6908_Ubuntu18.04.tar.gz` (resolved from the official `www.moomoo.com/download/fetch-lasted-link` endpoint pattern; Moomoo/Futu-controlled CDN; ~445 MiB) | OFFICIAL_CHECKSUM_STATUS: UNAVAILABLE (none published) → LOCAL_ARCHIVE_SHA256 recorded at download |
| pyarrow | 25.0.0 | PyPI wheel | pip hash-checked install |
| OpenD newer release | 10.9.6918 observed at the official endpoint | — | CANDIDATE ONLY, not installed (no silent upgrade) |

## Install paths (isolated; §3.4 exactly)
OpenD releases `~/.local/opt/trade-ai-lab/moomoo/opend/<ver>/` (+`current` symlink,
atomic) · venvs `~/.local/venvs/trade-ai-lab/moomoo-api/<ver>/` (+`current`) · state
`~/.local/state/trade-ai-lab/moomoo/` · replay `~/.local/share/trade-ai-lab/moomoo/replay/`
(0700) · downloads `~/.cache/trade-ai-lab/moomoo/downloads/` · user units
`~/.config/systemd/user/` (disabled) · runtime tmpfs `${XDG_RUNTIME_DIR}/trade-ai-lab/moomoo/` (0700).
No repository .venv / requirements.txt / system-Python change. Lockfiles:
requirements-stage5.lock + pip-freeze-stage5.txt + INSTALL_MANIFEST.json.

## Process/port map (no collision)
OpenD data API 127.0.0.1:11112 (11111 reserved for future production topology; both
currently free) · production portfolio server :7777/:7776 untouched · Stage 4 read API
:8134 remains manual/off · telnet/WebSocket/push extensions disabled in config.

## Credential state (bootstrap GREEN, 2026-07-22)
Machine account: vault displays **trade-ai-lab-code** (launcher §3.7 writes
"trade-ai-lab-codex" — display-name mismatch DOCUMENTED; bws CLI does not expose the
machine-account ID, so the stable-ID rule is recorded as verified-by-operator-vault;
no new account created — 3/3 plan limit respected: MACHINE_ACCOUNT_REUSE_WITH_PROJECT_ALLOWLIST).
Dedicated token `moomoo-data-stage5` at `~/.openclaw/credentials/bws_moomoo_data_token`
(0600). Token sees exactly trade-ai-lab + trade-ai-moomoo-data; trade-ai-prod NOT LISTED.
Project `trade-ai-moomoo-data` (id suffix 00375f2c): 3/3 data secrets present, no
sentinels, no forbidden trade keys. Wrapper compensating controls: pinned project ID,
exact 3-name allowlist, read-only, rejects trade-ai-lab project id and non-allowlisted
names. Runtime never receives the lab or org token.

## Entitlement risk
Personal moomoo account entitlements unknown until the authenticated query; possible
QUOTE_RIGHT_CONFLICT with the operator's own moomoo terminal — auto_hold_quote_right=0
is mandatory, so on conflict we record + degrade, never grab. US market session at
execution time is evening (closed/after-hours) — the 30-minute capture will run against
whatever session data is available and any shortfall is documented per §3.9/§22.

## Implementation inventory (all additive)
`scripts/active_trader/moomoo/`: secret_render.py (pinned-project wrapper + tmpfs XML +
OpenD launcher) · gateway.py (single subscription owner, states, priorities, envelope,
bounded queues) · replay.py (WAL append/checksum → zstd Parquet + manifest + verify) ·
features.py (deterministic features, versioned, no lookahead) · quality.py ·
governor.py (PLACE 15/12/3, MODIFY_CANCEL 20/16/4, SNAPSHOT 60/48/12 per 30 s; bucket +
exact sliding window) · ast_guard.py (static trade-API prohibition) · opend_install.sh ·
smoke.py (authorized live-data ops only) · observation.py (5-RTH checkpoint) · 5 disabled
user units. Migration 0007 (10 md_* tables, paired down, trade_ai_test only). Stage 4
read projections extended additively (health/brokers fields), API not deployed.

## Tests
Pure: governors (boundaries/concurrency/restart), features (formulas/null/replay
equality), queue bounds/shedding/markers, envelope, AST guard (0 trade constructors/
methods reachable), wrapper allowlist (mocked bws: wrong-project and extra-name
rejection, sentinel rejection), config render (no 0.0.0.0, no password in argv).
Lab DB: migration cycle + tables. Integration: WAL→Parquet round-trip + crash recovery.
Live smoke (§21) only after all gates: login → entitlement/quota → snapshot → subscribe
QUOTE→K_1M→ORDER_BOOK→TICKER (≤2 symbols from MOOMOO_DATA_TEST_SYMBOLS) → unsubscribe →
close. Then capture window + resumable observation checkpoint.

## Rollback (MOOMOO_ROLLBACK.md will carry the full procedure)
stop user units → restore previous `current` symlinks → remove tmpfs runtime dir →
verify no 1111x listener → quarantine failed release dir → re-verify production
unchanged (schema hash + checkout inventory + validators).

## BF-1 evidence plan
Official moomoo API docs + installed SDK surface inspection only (no trade context):
enumerate order-type/protection support for US equities, broker-residency and
disconnect-survival statements; produce BF1_BROKER_RESIDENT_PROTECTION_EVIDENCE.md with
verdict (expected UNPROVEN → live moomoo scalping stays BLOCKED).

## Five-session observation plan
Resumable checkpoint (RTH_OBSERVATION_CHECKPOINT.md + md_observation_session rows in
lab DB): 5 distinct RTH dates, per-session integrity metrics, hard Stage 9 gate.
Stage 5 exit state selected honestly per §26.
