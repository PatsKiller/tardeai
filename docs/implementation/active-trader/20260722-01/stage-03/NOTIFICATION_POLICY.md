# Notification Policy — Stage 3

Code: `scripts/active_trader/notifications.py` · TEST SINKS ONLY — no real alert can be
sent from this module (production Telegram/email lanes are never imported).

## Severity model and DB mapping
Launcher model: INFO / WARNING / ACTION_REQUIRED / CRITICAL.
Stage 1 DB CHECK stores INFO / WARN / BLOCKING / CRITICAL — explicit mapping:
WARNING→WARN · ACTION_REQUIRED→BLOCKING (documented here; enforced in LabDbSink).

severity_for(): broker-call-required or UNKNOWN → ACTION_REQUIRED; transient
(MARKET_CLOSED/RATE_LIMITED/STALE_ACCOUNT_STATE) → WARNING; other operator-required →
ACTION_REQUIRED; else INFO. Escalation promotes to CRITICAL.

## Channel routing (deterministic; no send occurs)
| Channel | Rule |
|---|---|
| COMMAND_CENTER | always for material rejection |
| JOURNAL | always |
| AUDIBLE_UI | operator preference AND severity ≥ ACTION_REQUIRED |
| TELEGRAM | ACTION_REQUIRED/CRITICAL when configured |
| EMAIL | broker-call-required-and-unresolved OR CRITICAL |

## Lifecycle
create → (identical repeat: counted, NOT re-emitted — no flooding) →
(changed fill/remaining: UPDATED + one re-emit) → ESCALATED (promotes CRITICAL,
adds EMAIL) → ACKNOWLEDGED → RESOLVED; OPEN/UPDATED past expires_at → EXPIRED.
Dedupe key = sha256(broker|account|symbol|normalized_code); lab-DB unique partial
index enforces one active row per dedupe key.

## Operator message content (rendered; tested)
broker · masked account label/ID · symbol · requested/filled/remaining quantities ·
redacted raw broker message · normalized reason · retry-allowed · broker-call-required ·
protection state · authorized fallback accounts (or "none in envelope") · required
operator action. The renderer never claims an alternate order was submitted
(constructor-enforced), and redaction strips tokens/keys/8+-digit runs.

## Sinks
InMemorySink (assertions) · MockTelegramSink (captures would-be payload, chat
"[TEST-SINK]") · MockGmailSink (captures would-be MIME fields) · LabDbSink (guarded lab
DSN; severity-mapped rows with dedupe upsert). Wiring real sinks is a later,
separately-authorized stage; the ONLY real email this stage is the Stage 3 completion
email via gog gmail send, which is not a rejection alert.
