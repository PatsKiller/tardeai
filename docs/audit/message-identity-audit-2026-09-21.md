# Message audit — 60 days, channels and identity

Measured 2026-09-21 against the live database. Every number below is a query result,
not an estimate. `AUTHORITY: READ_ONLY_ADVISORY` — nothing in this document was changed.

## 1. Volume: where messages actually live

| store | total | last 60d | time column |
|---|---:|---:|---|
| `communication_events` | — | **51,771** | `created_at` |
| `communication_deliveries` | 51,755 | **51,755** | `reserved_at` |
| `telegram_outbox` | 7,112 | **4,716** | `sent_at` |
| `alert_events` | 7,883 | 59 *(stamped)* | `telegram_sent_at` |
| `alert_occurrences` | 935 | 935 | `observed_at` |
| `notification_log` | 177 | 177 | `created_at` |
| `alert_dispatch_log` | 189 | 92 | `created_at` |
| `alert_notification_deliveries` | 8 | **0** | `claimed_at` |
| `hermes_alerts` · `options_lifecycle_alerts` | 0 | 0 | — |

## 2. Channels — are the right ones used?

**Code-level discipline is clean.** `check_telegram_chokepoint.py` reports
`producers bypassing the chokepoint: 0` against 23 declared boundaries. Exit 0.
This is *not* where the problem is.

**Routing metadata is absent.** `communication_deliveries.destination_policy_id`
is **NULL on all 51,755 rows**. The column exists to record which policy chose the
channel; it is referenced in exactly **one** file (`lib/comms/delivery.py`) and
never written. The system cannot currently answer "which policy routed this".

### 2.1 Delivery status is dominated by suppression

| channel | status | rows |
|---|---|---:|
| telegram | **SUPPRESSED** | **50,253** (97.1%) |
| telegram | LEGACY_DELIVERED | 1,053 |
| telegram | RESERVED | 343 |
| telegram | SENT | 88 |
| telegram | FAILED | 8 |
| slack | RESERVED | 4 |
| email | RESERVED / SENT | 3 / 1 |
| whatsapp_meta · whatsapp_twilio | SENT | 1 · 1 |

Of 51,745 telegram rows: `completed_at` on **51,402**, `sent_at` on **88**.
The ledger records *completion* for messages that were never sent. Suppression
is a legitimate terminal state, but a 97.1% suppression rate is the single
largest fact about this system's outbound traffic and nothing reports it.

Weekly: 7 → 557 → **43,143** → 6,547. The volume arrived in the week of 09-14.

### 2.2 One channel fails 100% of the time

`telegram_outbox.channel='reports_archive'`: **5,214 rows, `ok=False` on every
one**, 2026-07-02 through 2026-09-21 15:45. Never once true.

Top `report_type` by failure: `escalations` 1,010/1,098 · `siem_p1` 829/905 ·
`hermes_alerts` 701/764 · `topic_curator` **740/740** · `trade_ai_live` 439/478.

Per `report_capture.py:121`, `ch = "reports_archive" if suppressed else "telegram"` —
so this is the *archive* of suppressed messages, and `ok=False` is recording the
suppression, not a transport failure. **But it is indistinguishable from failure
in every query**, which is why it reads as the largest outage in the system.
Recommend a distinct status rather than overloading `ok`.

### 2.3 `notification_log` routes sensibly

`alert_fatigue_meta`→telegram (27) · `recovery_escalation`→dashboard (26) ·
`stop_confirmation_reminder`→telegram (21) · `daily_digest`→**gmail** (20) ·
`aegis_morning_brief`→`telegram+export` (6). Auto-downgrade works: 
`paper_trade_monitor` was moved ALERT→INFO (dashboard only) after 4 consecutive days.

**Defect:** `stop_confirmation_reminder` lists **SPCX twice** in one message
(two accounts, same $45,813) and is at **reminder #69**. A capital-protection
prompt asked 69 times is not a reminder, it is furniture.

## 3. Identity — GUIDs on message, ticker, sector, industry, thesis

### 3.1 What exists and works

`communication_events` has a full envelope: `event_id` (uuid7), `idempotency_key`,
`subject_key`, `subject_guid`, `thread_id`, `correlation_id`, `causation_id`,
`parent_event_id`, `reply_to_event_id`, `supersedes_event_id`, `entity_refs`,
`incident_id`. `narrative_subjects` holds **77,573** rows sourced from
`communication_events` — its single largest source.

### 3.2 Coverage, by field

| identity | state | evidence |
|---|---|---|
| **message GUID** | ✅ 100% | `event_id` + `idempotency_key` on all 51,771 |
| **thread / correlation** | ✅ 100% | `thread_id`, `correlation_id` on all rows |
| **ticker GUID** | ⚠️ 88% overall, **0% on every alert class** | below |
| **reply lineage** | ❌ **0 of 51,772** | `reply_to_event_id` null everywhere |
| **causation** | ❌ 0 | `causation_id` null everywhere |
| **sector GUID** | ❌ none exists | no sector-guid column anywhere in 721 tables |
| **industry GUID** | ❌ none exists | same |
| **thesis GUID** | ❌ no first-class id | `thesis` is free text on 8+ tables |

`entity_refs` is non-null on 51,519 rows but **only 61 rows carry any key at all**,
and the only key ever present is `symbol`. The rest are empty `{}`.

### 3.3 Ticker GUID by producer — the work list

| producer | events (60d) | with GUID | % |
|---|---:|---:|---:|
| `telegram_alert.send_telegram` | 51,341 | 45,219 | **88%** |
| `notify_material_change` | 76 | 0 | **0%** |
| `send_watchpool_maturity_alerts` | 61 | 0 | **0%** |
| `agent:cio` | 16 | 2 | 13% |
| `ops.test` / `ops.health` / `ops.watchdog` | 18 | 0 | 0% |
| `comms_live_cutover_smoke` / `comms_shadow_soak` | 4 | 0 | 0% |

### 3.4 Root cause — the tagger is bolted to the old path

`_tag_outbound` lives at `telegram_alert.py:370`, inside
`_best_effort_comms_publish`. That is the **legacy chokepoint**.

`publish_communication` (`lib/comms/client.py:253`) is the new primitive. Its
docstring says "Mint identity", but `mint_identity()` mints `event_id` and
`idempotency_key` only — `lib/comms/event.py:103` states plainly:

> `subject_guid: str | None = None  # read-only from identity spine; never minted here`

**43 files import `publish_communication` directly. Exactly 1 also tags.**

`notify_material_change.py:70` is explicit about having migrated:
*"Route this notice through the comms gateway instead of the legacy chokepoint."*
It is one of the two 0% producers. The traffic moved; the tagger did not.

Eliminated by direct test: `_db_conn()` returns a live connection, and
`cio_outbound_identity.tag_outbound_event` imports cleanly. Neither is the cause.

### 3.5 Why CI never caught it

`tests/test_outbound_identity.py` **is** registered in the hardening runner — and
it asserts only on `subjects_from_tag(tag_text(...))`. Pure extraction. Zero
cursor, zero DB. The tagging *logic* is proven; the `subject_guid` **write** is
exercised by nothing. Green gate over a 0% production condition.

Contrast: `tests/test_inbound_identity_tagger.py` has 10 DB-touching lines and
exercises real persistence — and inbound's table has correct rows.

### 3.6 Inbound is built, proven, and dormant

`inbound_operator_questions` has the right model (`subject_guid`, `issuer_guid`,
`identity_status`, `matched_via`, `matched_text`, `topics`, `unresolved_mentions`)
and 4 of 5 rows are `CONFIRMED`.

**It holds 5 rows, all dated 2026-09-06** — the day it was built — against
**252 inbound events in 60 days**. Written once, nothing since.

Meanwhile `communication_events` INBOUND: 252 rows, **0** with `subject_guid`,
from `telegram_inbound` (`callback_query` 168, `telegram_command` 82) and
`telegram_command_handler` (2).

This violates `AGENTS.md:835` — *"Tagging is TWO-WAY — inbound questions carry
identity too."*

### 3.7 Agent memory does not receive identity

`communication_agent_consumption_receipts`: **199 rows, `subject_guid` on 0**.
By agent: cio 195, advisory 2, darwin 1, nova 1.
`communication_knowledge_candidates`: **12 rows, last written 2026-09-05** (16 days stale).

So even where an outbound GUID exists, nothing carries it into memory.

## 4. Message content defect — cross-contaminated identity

Observed live 2026-09-21 15:10 and 15:40:

```
🟢 CIO entry — BUY READY: CBC   …  🆔 03331155 · CBC:d29a24f2 TROW:69403c08
🟡 CIO entry — getting close: DFVE …  🆔 7da963a3 · DFVE:039abd63 REFR:1e0ac88e
🟡 CIO entry — getting close: LOMA …  🆔 866f1a70 · LOMA:c0a63d61 TROW:69403c08
```

A card about CBC is tagged with TROW's GUID and carries TROW's links.

`comms_editor.py:573` builds one list — `subs = subjects(body, resolve=resolve)` —
and both the links (`:605`, `subs[:3]`) and the ID tags (`:629`, `subs[:4]`) slice
it. So the second symbol is genuinely being **extracted from the message body**.

`subjects()` is registry-backed and documented "Never a guessed ticker", so the
over-match is inside `operator_subject_resolver.resolve_subjects`. This is a
correctness bug in exactly the field you asked to validate: **the message is
tagged with another security's identity.**

**Follow-up status `[VERIFIED]` 2026-09-22 — still not live.** Draft PR #1187
(`ed957509d…`, branch `cursor/fix-single-letter-ticker-s-667c`) scopes outbound
link chrome to turn `primary_symbols` and hardens single-letter extract / research-gap
auto-enqueue. Lifecycle = **PR_ONLY**: not merged to `main`, served pin remains
`466c781d0…`. Full note: `docs/audits/SINGLE_LETTER_TICKER_S_FIX_2026-09-22.md`.
Do not mark §4 closed until observed from CURRENT.

## 5. Recommendations, in dependency order

1. **Move tagging into `publish_communication`.** One change closes all 43 direct
   publishers at once. Keep `_tag_outbound` for the legacy path until it retires.
2. **Give the outbound test a DB.** A `subject_guid` write must be asserted
   against a real cursor, or §3.5 recurs. Mirror the inbound test's shape.
3. **Fix the resolver over-match** (§4) before backfilling — a backfill would
   otherwise persist the wrong GUIDs at scale.
4. **Populate `reply_to_event_id` and `causation_id`** — currently 0/51,772, so
   no reply can be traced to what it answers.
5. **Wire inbound tagging into the live path** so `inbound_operator_questions`
   receives more than its 5 founding rows.
6. **Carry `subject_guid` into `communication_agent_consumption_receipts`**, or
   memory stays unjoinable.
7. **Then backfill 30 days**: **433 events** need GUIDs (252 inbound + 181
   outbound non-`operator_message`), plus 6,134 `operator_message` gaps.
   Idempotent, re-runnable, `--dry-run` first per AGENTS §0 rule 7.
8. **Write `destination_policy_id`** so the channel question is answerable.
9. **Separate suppression from failure** in `telegram_outbox.ok` (§2.2).
10. **Cap `stop_confirmation_reminder`** and de-duplicate SPCX (§2.3).

## 6. Correction to an earlier draft of this document

An earlier draft of §5 stated that "sector, industry and thesis GUIDs do not exist
and cannot be attached today" and that minting them was an §17 operator decision.
**That was wrong.** `narrative_subjects.entity_type` is already a live namespace:

| entity_type | rows |
|---|---:|
| SECURITY | 75,274 |
| **THEME** | **3,514** |
| **SECTOR** | **60** |
| STRATEGY | 27 |

and `cio_outbound_identity.py:102-105` already emits both `SECURITY` and `THEME`
with `relationship` of `subject` / `mentioned`. So SECTOR and THEME require
**population, not creation** — a much smaller change, and not an §17 decision.
**INDUSTRY is the only genuinely absent namespace.** Sector/industry values are
available to attach (`symbol_profiles`: 3,137 rows, 2,854 sector, 2,844 industry).

## 7. AGENTS.md describes a table that does not exist

`AGENTS.md:857` states `identity_registry` "holds **10,279 entities**: 5,014
CONFIRMED (all CUSIP-based), 22 CANDIDATE, 5,243 UNRESOLVED_WITH_REASON."

**There is no `identity_registry` table in any schema.** `issuer_guid` is instead
spread across 12 tables (`memory_identity`, `material_changes`, `news_articles`,
`research_insights`, `catalyst_events`, `document_mentions`,
`due_diligence_questions`, `hermes_external_research`,
`hermes_research_intelligence`, `inbound_operator_questions`,
`operator_conversation_turns`, `subject_state_narratives`).

Reported per §0 rule 10 (the finding wins). Not remediated here.

## 8. ⚠️ The backfill must not run yet — root cause, reproduced

The identity spine's `SECURITY` links are substantially false. Top
`semantic_subject` values tagged SECURITY:

| value | rows | actually |
|---|---:|---|
| **AFTER** | **36,752** | the word "after" |
| RSI | 4,993 | the indicator |
| DB | 4,463 | "DB" the database |
| ET | 3,305 | Eastern Time |
| QUOTE | 2,327 | the word "quote" |
| LIVE / ALERT / MOVE / B | 4,268 | ordinary words that are also tickers |

### 8.1 Reproduced byte-identically to the operator's screenshots

From the message text alone, no database state involved:

```
CBC  -> ('R', guid=None) ('CBC','d29a24f2') (None) (None) ('TROW','69403c08')
DFVE -> ('DFVE','039abd63') ('R', guid=None) (None) ('REFR','1e0ac88e')
```

matching the delivered cards `CBC:d29a24f2 TROW:69403c08` and
`DFVE:039abd63 REFR:1e0ac88e` exactly.

### 8.2 The alert's own chrome is being resolved as company names

```
extract_name_mentions(<CBC card>)
  -> ['CIO', 'BUY READY', 'CBC Mid', 'Price', 'Zone', 'Advisory']
```

Each is passed to `company_name_index.resolve_name`:

| harvested phrase | resolves to | matched_on | conf |
|---|---|---|---:|
| `"Price"` | **PRICE T ROWE GROUP I** (TROW) | exact | 0.85 |
| `"Research More Advisory"` | **RESEARCH FRONTIERS I** (REFR) | name_prefix | 0.70 |
| `"Mid cap"` | **Mid-America Apartment** (MAA) | — | — |

**"Price" is in the template of every entry card.** So is "Mid cap". This is not
an occasional mis-hit; the template guarantees it.

### 8.3 Why the existing guard does not fire

`_is_generic_term` is applied in `_companies()`, but against the **whole harvested
phrase**:

```
_is_generic_term('Research')               = True    <- guard works
_is_generic_term('Research More')          = False   <- bypassed
_is_generic_term('Research More Advisory') = False   <- bypassed
_is_generic_term('Price')                  = False
_is_generic_term('Mid cap')                = False
```

So the documented "REFR incident" guard catches the bare word and is walked
straight past by the longer phrase, which then `name_prefix`-matches. A longer
stopword list does not fix this — **the guard must apply per-token, and
`name_prefix` matching must not bind an issuer from a single generic leading
word.**

Two further faults visible in the same output: a symbol `('R', guid=None)` from
`source: uppercase` at confidence 0.35, and two `(None, None)` unresolved-name
rows. `comms_editor.subjects()` drops rows lacking both symbol and guid, so those
never render — but `TROW`/`REFR` carry CONFIRMED GUIDs and survive into
`subs[:4]`, becoming the footer ID tags and the links.

### 8.4 Blast radius

Probing the live templates:

| template | resolves to |
|---|---|
| `cio_entry` BUY READY | ESE ✅ |
| `cio_entry` getting close | WHD ✅ **+ MAA ❌** (from "Mid") |
| STOP_HIT_CLOSE | SYF ✅ clean |
| TRAILING STOP MOVED | SYF ✅ clean |
| PLATFORM_AVAILABILITY | none ✅ |
| Stop Placement Reminder | none ✅ |

**Capital-protection alerts are clean.** The contamination is concentrated in the
CIO entry cards — the highest-value operator surface, and the one the operator is
being asked to act on.

### 8.5 The corruption is already persisted, not merely threatened

An earlier draft of this document said a backfill "would persist tens of thousands
of incorrect GUIDs." **That understated it.** They are already written. Measured
inside the 30-day backfill window, `source_table='communication_events'`:

| semantic_subject | relationship | links |
|---|---|---:|
| **AFTER** | **subject** | **28,911** |
| AFTER | mentioned | 7,841 |
| QUOTE | mentioned | 2,299 |
| LIVE | mentioned | 1,364 |
| ALERT | subject | 1,054 |
| MOVE | mentioned | 786 |
| PRICE | mentioned | 372 |
| ALERT / QUOTE / LIVE / PRICE | subject | 226 |
| **total contaminated** | | **42,853** |

against **74,205** total `SECURITY` links in that window — **58%**.

The `relationship: subject` rows are the serious ones: 28,911 messages whose
recorded *primary subject* is the word "after". `narrative_subjects` is the store
agents read, so this is what memory currently believes those messages were about.

**Revised recommendation.** This is no longer "hold the backfill". It is:

1. Fix the resolver (§8.3) — per-token generic check, and no issuer bound by
   `name_prefix` from a single generic leading word.
2. Add a test pinning the CBC/"Price"→TROW and DFVE/"Research More"→REFR shapes,
   plus "Mid cap"→MAA. None exists today.
3. **Quarantine the 42,853 existing false links** — never delete (§0 rule 6);
   mark them superseded with a tripwire, and re-tag from source text.
4. Only then backfill, `--dry-run` first, reporting rows-that-would-change and a
   sample.

Step 3 is an operator decision (§17): it rewrites identity in an authoritative
store. Proposed here, stopped here.

The resolver is registry-backed, so it never invents a ticker — it matches
**real tickers that are also ordinary English words**. That is the mechanism
behind the operator-visible defect in §4: a CBC card tagged `TROW`, a DFVE card
tagged `REFR`.

**The existing guard cannot catch these.** `operator_subject_resolver.py:23` names
"the REFR incident", and `_is_generic_term()` *is* applied — but only inside
`_companies()`, the **company-name** path, where it stops the word "Research"
binding the ticker REFR. The **ticker** path is separate and ungated. Measured
against `GENERIC_NAME_TERMS` (67 entries):

```
AFTER guarded=False   QUOTE guarded=False   LIVE guarded=False
ALERT guarded=False   MOVE  guarded=False   RSI  guarded=False
DB    guarded=False   ET    guarded=False   B    guarded=False
```

Every offender is unguarded. The fix is a guard on the uppercase-ticker path, not
an extension of the company-name one. **No test pins the REFR shape** — a grep of
`tests/` for REFR returns only unrelated `STALE_REFRESH_REQUIRED` matches.

Scope: **74,204 of the 75,274 SECURITY links originate from
`communication_events`** — the contamination is concentrated in the message spine
rather than spread across research sources.

**Consequence:** backfilling 30 days through this resolver would persist tens of
thousands of incorrect security GUIDs into `communication_events.subject_guid` and
`narrative_subjects` — permanently, at scale, into the store agents read.

**Order of work is therefore fixed:**
1. Extend the generic-term guard to the outbound/editor path (§4).
2. Prove it with a test that pins the CBC/TROW and DFVE/REFR shapes.
3. Move tagging into `publish_communication` (§3.4).
4. Only then backfill — `--dry-run` first, reporting how many rows *would* change
   and a sample, per §0 rule 7.

---

# ADDENDUM — root cause found, fixed, and measured (2026-09-21 16:30)

Sections 4 and 8 above described the *symptom* and named the wrong mechanism
twice. This addendum supersedes them on mechanism; the measurements stand.

## R1. It is ONE message, not a diffuse problem

`44,693` of `77,798` comms identity links (57.4%) trace to a **single template**:

```
⚠️ AUTO-RETRY PAUSED (will re-arm): health:pipeline_freshness:<component>
<detail>
After <n> retries; autonomous re-arm in 30m.
```

emitted by `claude_escalation_handler.py:725`, cron `*/10`, `MAX_RETRIES=4`,
`BACKOFF_MINUTES=[0,5,15,30]`, `EXHAUST_RESET_SEC=1800`. Eleven components loop
in lockstep. **41,575 of 50,327 suppressed deliveries (82.6%) are this one alert.**

So the earlier framing — "58% of the spine is contaminated" — is true but reads
as systemic decay. It is one malfunctioning alert, repeated ~5,500×/day for ten
days.

## R2. The binding word is "After", and it took three wrong guesses to find

The closing sentence begins `After`, which is a real ticker. Earlier drafts
blamed (a) ALL-CAPS banner text, (b) `AUTO`/`RETRY`, (c) a `_STOP` wordlist gap.
All three were wrong; each was disproved by running the real body through the
real resolver. The correct trace:

```
'After 17 retries; …'  -> [('AFTER', 'ticker_alias', 'After')]
'after 17 retries'     -> []                       (lowercase: correctly ignored)
```

## R3. Two unguarded paths — and the guard already existed

**Alias path** (`inbound_identity_tagger.py:255`): `RI.resolve(doc, name)` ran
before any guard, while `_is_generic_term` protected only the company-name
fallback on the NEXT line. `extract_name_mentions` already applies
`_SENTENCE_STARTERS` + `_is_sentence_initial` to its own output — that rule was
simply never consulted on the alias branch.

**Bare-uppercase path** (`extract_candidates`): `_STOPWORDS` curates this exact
class (`UP`, `RSI` are members) and was missing the alert chrome. The EOD header
yielded `['EOD','OPEN','TRADE','REPORT','ET','DOWN','ALLE','P','L']`.

Fixed by: consulting the sentence-initial rule on the alias branch, adding
`_TEMPLATE_CHROME`, and a two-character minimum for bare tokens (`P&L` → `P`, `L`).

## R4. Measured before → after

```
storm     AFTER(subject)                        ->  []
EOD       OPEN(subject) ET DOWN ALLE P L AES    ->  ALLE(subject) AES
CBC card  CBC TROW                              ->  CBC(subject)
TLS card  TLS TROW                              ->  TLS(subject)
NVDA / AES / $V / Apple / Northrop Grumman      ->  unchanged
```

192 passed across the eight identity tests the hardening runner runs.

## R5. The backfill hold is LIFTED, with an order

§8 said "the backfill must not run yet". That still holds, but the blocker is now
removable and the sequence is concrete:

1. Land the resolver fix (done, pending CI).
2. `quarantine_template_identity_links.py` — dry run reviewed: 44,693 links /
   36,823 events, 4 real-ticker rows incidentally caught (CC, NKE, PFSI, PRIM),
   all archived and reversible. Then `--apply`.
3. Backfill the 433 genuinely-untagged events (252 inbound + 181 outbound).

The fix makes step 2 durable: with it, the storm body produces zero subjects, so
quarantined rows do not re-accumulate.

## R6. Corrections to this document's own earlier claims

| earlier claim | corrected |
|---|---|
| "sector/industry/thesis GUIDs do not exist" | SECTOR (60) and THEME (3,514) are live `entity_type`s; only INDUSTRY is absent |
| "the guard is bypassed by the longer phrase" | the guard is real; a SECOND, unguarded path (alias) was the route |
| "backfilling would persist wrong GUIDs" | they are already persisted — 44,693 of them |
| "`CANDIDATE` is the clean discriminator" | it is not: 213 CONFIRMED-but-false, and real tickers (GRMN, COOP…) would be swept |
| "a quarantine needs a schema change" | no: the house precedent is a dated quarantine TABLE (`analyst_consensus_history_quarantine_20260913`, 130,155 rows) |

## R7. Still unfixed, and not in scope of the resolver change

`claude_escalation_handler._notify()` calls `send_telegram` **directly** — no
dedupe, no cooldown, no alert-fatigue coverage (zero `notification_log` rows
mention AUTO-RETRY). The dedupe at `:752` applies to the fixable queue, not to
this notification. That is why it has never self-silenced.

Its premise is also false *now*: `pipeline_freshness_monitor.check()` currently
returns `stale=1, missing=0, ok=9` — `ticker_snapshot_daily` 0.7d,
`morning_synthesis` 0.2d — yet the loop still fires, because `_age_days_table`
returns `None` for BOTH "table absent" and "query raised", and line 94 renders
both as *"no output / table/file absent"*.

## R8. The fix took TWO passes — the first closed the cases, not the class

§R3 above describes the fix as though it landed in one move. It did not, and the
gap between the two passes is the more useful finding.

**Pass 1** added `_TEMPLATE_CHROME` (a curated list of alert-chrome words) plus a
sentence-initial guard on the alias path. Every case I had tested went green:
storm → `[]`, EOD → `ALLE(subject)`, CBC → `CBC(subject)`. 192 tests passed. It
was pushed and entered CI.

**It was still wrong.** Found only because I fixed a defect in my own dry run:
`backfill_message_identity.py` previewed `left(sanitized_body, 300)` while
`--apply` passed the whole column, so the preview resolved a *different* subject
set than the real run. Correcting that immediately exposed:

```
01a0c5af  SUPX(subject) VNCE RS AI RSI position risk
01a0c55d  AI(subject) position
01a0c541  RMBS(subject) ROOT AI position risk
```

`RSI` and `AI` are **already in `_STOPWORDS`**. That list was consulted only in
`extract_candidates` (bare tokens); the alias path never looked at it:

```
extract_candidates('… FBRT — unusual volume. RSI 41. AI Briefing …')
  -> ['FBRT']                                            correct
extract_name_mentions(same)
  -> ['Material','FBRT','RSI','AI Briefing','Root','Position']
tag_inbound -> RSI via ticker_alias, in_STOPWORDS=True
```

**Pass 2** makes both doors enforce one policy: a *single* token refused by
either list is not a security. Multi-word runs are untouched, so "AI Briefing"
and "Northrop Grumman" still go to the company path, which keeps its own guard.

Verified on BOTH directions, because `_OUTBOUND_MATCH_KINDS` filters
`company_name` out and an outbound-only check would have hidden an inbound
regression:

```
inbound   "what about Apple?"           -> AAPL via company_name
inbound   "target for Northrop Grumman" -> NOC  via company_name
inbound   "analyst target for Visa …"   -> V    via company_name
inbound   "RSI 41 on that name"         -> []
outbound  storm / EOD / CBC / TLS       -> clean
```

**The lesson worth keeping:** a wordlist patch that makes the failing examples
pass is not a fix — it is a fix-shaped object. The class was "any token the
system already calls not-a-ticker", and the guard for it existed; it was just
never wired to the second door. The same shape as §3.4 (tagger bolted to the
legacy path while traffic moved) and §3.5 (a green gate over a 0% condition).

---

# R9. OUTCOME — what was actually repaired, and one near-miss (2026-09-21 ~18:00)

## R9.1 Applied

| action | result |
|---|---:|
| Quarantine (`quarantine_template_identity_links.py --apply`) | **44,987** links archived + removed |
| `communication_events.subject_guid` cleared | **37,054** events |
| Backfill (`backfill_message_identity.py --days 30 --apply`) | 432 processed, 154 tagged, **425 links**, 278 correctly resolving to no subject, 0 errors |
| Tripwire view | `narrative_template_word_tripwire` live |

Independently verified, not from the scripts' own counts: archive holds 44,987;
`still_stamped: 0`; spine went 78,275 → 33,288 comms links.

## R9.2 The fix is proven in production, not inferred

The storm fired **13 new events at 17:46:12**, after the 17:44:56 promote, and
wrote **no new `AFTER` link** (newest remained 17:40:03). Before that promote,
every cycle wrote ~11. This is the distinction silence alone cannot give: the
earlier "no new links since the deploy" reading was equally consistent with the
fix working and with the storm not having fired.

## R9.3 ⚠️ Near-miss: I nearly deleted identity for TRACKED instruments

After the backfill I flagged its output as contaminated — `NEWS(subject)`,
`DROPS`, `ABOVE`, `ODD`, `EVERY`, `AGAIN`, `FIX`, `ROOT`, `STOCK`, `OFF` — built
a 24-symbol "bad list", and scoped a **62-link removal**.

**All of them are tracked instruments.** Every one appears in BOTH
`watchlist_items` and `ticker_snapshot_daily`. `ABOVE` carries its own Command
Center link in the template (`intelligence/ABOVE`); `ODD` reads *"ODD — moved
14%, 3x its normal daily range"*; `FIX` already had **431** pre-existing spine
links. The backfill was behaving correctly and I read correct output as a defect.

Three of my claims in that stretch were wrong in sequence:

1. "pure template fragments" — they are tracked symbols
2. "`FIX` is prose" — tracked, 431 pre-existing links
3. "absent from `symbol_profiles` ⇒ not a security" — that table holds 3,137
   symbols, a **subset** of the tracked universe

What stopped the deletion was querying `watchlist_items` before acting, not the
reasoning that led there. **Nothing was removed.** A redundant checkpoint table
(`narrative_subjects_backfill_20260921`, 496 rows) was left in place as evidence.

## R9.4 Why the quarantine is still correct

The distinction that matters, and the one I should have reached for first:

```
AUTO-RETRY bodies containing a Command Center symbol link: 0  (of 41,919)
```

These messages are pipeline-health boilerplate; they name no security at all. So
**no** security link from them was ever correct — independent of whether `AFTER`,
`RSI` or `DB` are real tickers (they are). That justification is stronger than
"those words aren't securities", which is what I would have said an hour earlier
and which R9.3 shows to be unreliable.

Six real-ticker rows were swept (`NKE`, `PFSI`, `PRIM`, `CC`, `ET`, `FIX` — one
each) from bodies that name no security. All are archived and reversible.

## R9.5 Residue

The tripwire fires on **~9,500** links — `ET` 3330, `QUOTE` 2338, `LIVE` 1413,
`ALERT` 1230, `MOVE` 786, `PRICE` 375 — from templates the quarantine predicate
never covered (it keyed only on `AUTO-RETRY` bodies). Those words now re-resolve
to `[]`, so the set is **historical and not accruing**. A second pass could clear
it; after R9.3 that deserves its own measurement rather than momentum.

`claude_escalation_handler.py:725` is still unfixed: ~5,500 alerts/day, no
dedupe, no alert-fatigue coverage, and a premise that is currently false
(`pipeline_freshness_monitor.check()` now returns `missing=0`).
