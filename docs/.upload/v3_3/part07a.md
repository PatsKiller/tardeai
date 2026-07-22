- **ADR-026:** Automatic broker failover requires a pre-authorized fallback account and confirmed source-order state — ACCEPTED.
- **ADR-027:** Cancel-all preserves protection by default; flatten verifies broker and local zero — ACCEPTED.
- **ADR-028:** Quick-add presets are configurable and use the original smart-limit manager — ACCEPTED.
- **ADR-029:** `/v3-next` includes a server-side feature-control modal; `/v3` remains unchanged during development — ACCEPTED.
- **ADR-030:** A second architect performs a read-only litmus review and cannot alter implementation — ACCEPTED.
- **ADR-031:** Non-live Codex implementation may run unattended with stage commits, Drive sync, checkpointing, and operator email — ACCEPTED.
- **ADR-032:** Credential scaffolding creates names and lab placeholders, never real secret values — ACCEPTED.

---

# 26. ANTI-PATTERNS

Do not build:

- agents debating until one sounds convincing;
- a general runtime before the MVL proves value;
- LLM arithmetic as truth;
- an agent validating or scoring itself;
- model consensus from correlated routes;
- vector-only institutional memory;
- self-promoting lessons;
- online mutation of production thresholds;
- hidden fallback from local to cloud;
- paid review without cost preview;
- OpenClaw as broker authority;
- Hermes as final decision-maker;
- unrestricted shell tools;
- raw secrets in prompts;
- raw Level 2 in the OLTP database;
- full-universe L2 subscriptions;
- live scalp with client-only stops;
- a live auto-execute rule that is not bound to a signed, bounded, active session authorization;
- a candidate package installed over production;
- a second OpenD session fighting for ownership;
- a new orchestration framework without an ADR;
- a UI state that hides backend contradiction instead of logging it;
- an architecture phase that requires all existing consumers to migrate first;
- a fixed sub-second Moomoo modify loop that violates account rate limits;
- using a static Level 2 wall as an entry or exit by itself;
- storing authorization only in browser state;
- changing selected accounts or quantities after 2FA;
- treating a profitable scalp as a swing without an explicit state transition;
- replacing `/v3` before `/v3-next` proves parity and rollback;
- assuming a broker supports flatten because another broker does;
- retrying a broker-assisted or electronic-entry rejection indefinitely;
- failing over to an account that was not present in the signed session;
- using cancel-all to remove protection silently;
- reporting flat before broker reconciliation;
- a one-click add without projected risk confirmation;
- allowing feature flags to mutate current `/v3` behavior;
- letting the litmus reviewer edit the architecture;
- an overnight run that continues after a failed stage;
- commits without matching Drive evidence;
- emailing credentials or secret values;
- fabricating credential values for Bitwarden.

---

# 27. REQUIRED LIVE BASELINE COMMANDS

Read-only verification only:

```bash
cd /home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild

git rev-parse HEAD
git status --short

.venv/bin/python - <<'PY'
import sys
print("python", sys.version)
try:
    import openai
    print("openai", openai.__version__)
except Exception as exc:
    print("openai unavailable", exc)
PY

~/.local/bin/hermes --version || true
~/.local/share/hermes-agent-venv/bin/python --version || true
~/.local/share/hermes-agent-venv/bin/pip show hermes-agent || true

openclaw --version || true
node --version
npm --version
ollama list

psql -Atc "SELECT version();"
psql -Atc "SELECT extname, extversion FROM pg_extension WHERE extname='vector';"

systemctl --user status openclaw-gateway --no-pager || true
systemctl status moomoo-opend --no-pager || true
systemctl status moomoo-gateway --no-pager || true
chronyc tracking || timedatectl status
```

Do not upgrade packages in the baseline session.

---

# 28. END-STATE WORKFLOWS

## 28.1 Watch decision

```text
facts
→ compiler
→ validator
→ Sentinel kernel
→ research card
→ reflective review by policy
→ reconciler
→ verified proposal or quarantine
→ operator
```

## 28.2 Moomoo evidence

```text
OpenD
→ gateway
→ sequence/freshness
→ WAL/replay
→ deterministic features
→ Pulse/Watch/scalp evidence
```

## 28.3 Live order

```text
verified released ticket
→ account/risk/capability
→ immutable order intent
→ per-order authorization
   OR active momentum-scalp session authorization
→ deterministic adapter
→ broker acknowledgment
→ reconciliation
```

## 28.4 Learning

```text
artifact/outcome
→ case
→ Darwin score
→ nightly reflection
→ Iris lesson candidate
→ Hermes preregistered hypothesis
→ evaluation
→ human adjudication
→ versioned proposal
→ reversible promotion
```

---

## 28.5 Active Trader session

```text
candidate enters scope
→ prime queue displays float, participation, catalyst, structure and microstructure
→ operator selects accounts and quantities
→ SAVE SESSION
→ server validates and freezes draft version
→ operator reviews complete envelope
→ one session 2FA
→ ACTIVATE AUTO-TRADE
→ deterministic engine primes/fires/executes within envelope
→ Level 2/tape-informed bounded order management
→ broker-native protection
→ resilience/resistance management
→ scale, runner, or exit state
→ account and broker reconciliation
→ journal and replay
→ Darwin scoring and governed learning
```

## 28.6 Broker rejection and fallback

```text
order intent
→ broker capability check
→ submit
→ broker accepts
   OR typed rejection
→ classify and notify
→ if pre-authorized fallback exists:
     prove source not filled
     revalidate market and risk
     submit fallback
→ otherwise:
     pause symbol
     operator amends session
     new 2FA
```

## 28.7 Operator actions

```text
QUICK ADD
→ confirmation
→ envelope and risk check
→ same smart-limit entry manager

CANCEL
→ selected order only

CANCEL ALL ENTRIES
→ remove unfilled entry/add orders
→ preserve protection

SELL SMART
→ price-seeking bounded exit
→ deterministic escalation

FLATTEN
→ cancel conflicts
→ broker-specific close
→ verify zero
```

## 28.8 Unattended implementation

```text
night-run preflight
→ stage plan
→ implementation
→ tests
→ closeout
→ commit and push
→ Drive sync and hash verification
→ checkpoint
→ next stage
→ final litmus review
→ final Drive sync
→ operator email and TODO
→ stop before production/live activation
```

# 29. FINAL POSITION

Trade AI becomes agentic by adding durable reflection, institutional memory, scored outcomes, and evidence-governed improvement.

It does not become agentic by allowing an LLM to improvise inside execution.

The Active Trader system may execute automatically during an operator-authorized session, but every action remains deterministic, bounded, rate-governed, protected, reconciled, and journaled.

The canonical standard is:

> **The system may become more intelligent every day, but it may never become less governed.**

---

# APPENDIX A — SOURCE DOCUMENTS AND HASHES

| Source | SHA-256 |
|---|---|
| `AGENTIC_FINANCIAL_SYSTEM_ARCHITECTURE_v2_0(1).md` | `4d1b395eee0f992e958fb9593b0fff383d9e4ac225ae9e79b131975b4b1e6498` |
| `MOOMOO_REFERENCE_ARCHITECTURE_v2_2.md` | `735d51b2d0e5aa4d56a482e4eeebf42ee47b285a2c585772cfbe022a453d0f65` |
| `MOMENTUM_SCALP_ARCHITECTURE_V1.3.md` | `ee87bafc585d78947b1a4a30f512b88119500246d13d9689c1bef56e08e3a2f6` |
