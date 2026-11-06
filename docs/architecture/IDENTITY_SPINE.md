# Identity Spine

```
Status:  ACTIVE
as_of:   2026-10-27
Source:  AGENTS.md 25.0.1 (moved by 26.0.0)
```

Reference material for the rules in AGENTS.md. The binding rules stay in AGENTS.md; this document holds the detail they point to.

<!-- moved from AGENTS.md 25.0.1 lines 811-946,1025-1036,1123-1172 -->
## Moved from AGENTS.md (25.0.1 lines 811-946,1025-1036,1123-1172)

*Moved here by AGENTS.md 26.0.0, which keeps the binding rule and a pointer; the 25.0.1 text is preserved at `tests/fixtures/agents_pre_26_0_0/AGENTS.md`. This is reference, not instruction: where it mentions Telegram `/approve`, `bin/guard request`, a push budget of 5 or a coordinator override, `gh pr merge`, a `release-write` grant for a deploy, or shipping with no operator input, those paths are retired or not implemented, and AGENTS.md governs.*

# The identity and tagging spine — reference

Moved from AGENTS.md §7 (25.0.1) by 26.0.0. The binding rules stay in AGENTS.md §7; this is the reference behind them. Counts are dated 2026-09-06.

### What it is for

An agent deciding anything about a security must be able to see everything the system knows about
it — the earnings, the analyst notes, the news, the sector-wide catalysts — and to know that they
all refer to the *same* company. That requires a durable identifier on every artifact. `symbol` is
not one: **a ticker is an alias, not an identity.** Tickers are reassigned after delisting, so two
companies can collide on one symbol years apart, and a share-class change silently splits one
issuer's history in two.

Worked example, `V`:

```
issuer_guid   8dfc96ee-…   Visa the ISSUER — survives ticker change, re-listing, share-class split
security_guid d1871bc6-…   this specific security   (identity_basis: cusip, status: CONFIRMED)
listing_guid  fc9e4477-…   this listing
gics_sector   Financial    sector fan-out: a catalyst on one financial reaches agents reasoning
                           about another
event_guid(issuer, EARNINGS, 2026Q3)   the earnings event, stable across every mention of it
                           SCHEDULED → OCCURRED → POST_EVENT → SUPERSEDED
```

`issuer_guid` — not `subject_guid` — is the join for "everything about this company". Prefer it.

### Company names and CUSIPs — WHERE THEY COME FROM. Do not build a map.

**Read this before writing anything that turns a name or a ticker into an identity.
I nearly hand-rolled a ticker-to-name table on 2026-09-06; the operator stopped it, and the
data was already on disk.**

| you need | source | how |
|---|---|---|
| CUSIP | Schwab `/marketdata/v1/instruments?projection=fundamental` | `scripts/sweep_schwab_instruments.py` |
| company name | **the same record** — its `description` field | `lib/schwab_instrument_evidence.load()` |
| name → symbol | index over that feed | `lib/company_name_index.resolve_name("Visa")` |
| symbol → identity | the registry | `lib/research_identity.resolve(doc, "V")` |

Already swept and on disk: **4,997 instruments, 4,997 with a description.**

```json
"V":   {"description": "VISA INC A",           "identifiers": {"cusip": "92826C839"}}
"NOC": {"description": "NORTHROP GRUMMAN COR", "identifiers": {"cusip": "666807102"}}
"NSC": {"description": "NORFOLK SOUTHN CORP",  "identifiers": {"cusip": "655844108"}}
```

**Alpaca has no `cusip` field.** Schwab `instruments` is the source, and it carries the name in
the same record — so the name and the identifier never disagree. That is the point: one feed, one
truth.

**Never hardcode a symbol-to-name pair.** If the broker does not carry a name, neither do we, and
"unresolved" is the correct answer. `tests/test_company_name_index.py` fails if a mapping is
hardcoded.

#### The three traps in that feed

1. **It CONTRACTS, it does not merely truncate.** `NORFOLK SOUTHN CORP`, `NORTHROP GRUMMAN COR`.
   `SOUTHN` is not a prefix of `SOUTHERN` and vice versa, so no token rule matches them and fuzzy
   matching would be a guess. Resolution narrows by **leading tokens** until exactly one instrument
   matches: `NORFOLK SOUTHERN` → `NORFOLK` → NSC.
2. **Ambiguity must return nothing.** `JPMorgan` alone matches seven instruments — the bank plus
   six ETFs. `Apple` is APPLE INC; `Apple Hospitality` is APLE. A wrong symbol on a financial
   question is worse than no symbol: it attaches the operator's intent to the wrong issuer and
   every join downstream inherits the error.
3. **Similar names are different companies.** `Norfolk` resolves to Norfolk Southern (NSC) and
   **must not** resolve to Northrop Grumman (NOC). Do not add "helpful" fuzziness across issuers.

Suffix stripping (INC, CORP/COR, CO, LTD, PLC, class letters) happens from the **end only**, so
`CO` inside `COCA COLA` survives.

**A name the feed does not carry is genuine ambiguity, and that is the one identity job a model
may do** — `lib/identity_resolution_advisor` proposes `CANDIDATE`, never CONFIRMED. See the
custodian section.

### Tagging is TWO-WAY — inbound questions carry identity too

Until 2026-09-06 it was discovery-only: `cio_telegram_bot`, `telegram_callback_handler` and
`run_telegram_callback_poller` all had `identity_registry=0`, and inbound messages were not stored
at all — only `communication_inbound_checkpoint` with the last `update_id`.

`lib/inbound_identity_tagger.tag_inbound(text)` resolves an operator question by **ticker or
company name** onto the same `issuer_guid`, records the **topics** asked (analyst_target,
support_resistance, earnings, valuation, position, risk), and keeps unresolved mentions as a
measured gap. Persisted to `inbound_operator_questions`, one row per (question, resolved entity),
and **one row with null guids when nothing resolved** — an unanswerable question is the
measurement of what the spine cannot reach.

    "analyst target for Visa, support and resistance"  -> V   issuer 8dfc96ee  via=company_name
    "analyst target for $V and support resistance"     -> V   issuer 8dfc96ee  via=ticker

Both spellings land on one issuer. `matched_via` and `matched_text` are recorded on both paths.

### The identifier model — what each ID is, and which one to join on

Audited 2026-09-06. `identity_registry` holds **10,279 entities**: 5,014 CONFIRMED (all
CUSIP-based), 22 CANDIDATE, 5,243 `UNRESOLVED_WITH_REASON`. The only external identifier in
the registry today is **CUSIP** — Alpaca exposes none; Schwab `instruments` is the source.

| id | scope | stability | join on it when |
|---|---|---|---|
| `issuer_guid` | the **company** | survives ticker change, re-listing, share-class split | "everything about this company" — **the default** |
| `security_guid` | one security of that issuer | survives a ticker change | you mean this specific instrument, not the issuer |
| `listing_guid` | one listing of that security | changes on re-listing | venue-specific facts |
| `ticker_alias_guid` | the **symbol string** | *unstable by design* | almost never — it is the alias, not the identity |
| `subject_guid` | what a row is *about* | = `security_guid` today | tagging a document, article or finding |
| `event_guid` | `(issuer, event_type, period)` | stable across every mention | earnings, ratings, catalysts — `SecurityEvent@v1` |
| `cusip` | external, issuer+issue | the registry's `identity_basis` | reconciling against a broker or filing |

**Prefer `issuer_guid`.** It is the join that answers the question an agent actually asks, and
the one that does not break when a ticker is reassigned.

**Which stores must carry identity, and which must not.** A GUID belongs on anything carrying
**judgment or narrative** about a security — research, news, catalysts, decisions,
recommendations, scores — because that is what an agent reasons over and what has to survive a
symbol change. It does **not** belong on raw market data keyed by symbol+timestamp
(`market_quotes` at 28.6M rows, `ticker_prices`, `schwab_stream_*`): the cost is real and the
symbol is sufficient for a price at an instant.

Coverage as of 2026-09-06 — `hermes_research_intelligence` and `news_articles` carry
`subject_guid` + `issuer_guid` + `gics_sector`. **Not yet tagged, in priority order:**
`catalyst_events` (135,919 — the lifecycle spine, and the highest-value gap),
`agent_recommendation_registry` (454,058), `fused_signals` (750,739),
`hermes_score_history` (166,367). Four other tables carry a bare `cusip` and no GUID:
`econfirm_evidence`, `fund_expense_rate_history`, `investment_cost_events`.

**Before adding a store to that list**, re-read the additive-only and no-downgrade rules below.
Tag with `lib/research_identity.resolve()`; do not hand-roll a lookup.

### The modules — none of these is new, all of them are load-bearing

| module | role | do not |
|---|---|---|
| `lib/identity_registry.py` | `IdentityRegistry@v1`, the minted entity store (10,279 entities) | re-mint, rewrite or delete a GUID; supersession is one-way by rank CONFIRMED>CANDIDATE>UNRESOLVED |
| `lib/security_identity.py` | ROOT GUID AUTHORITY — issuer→security→listing→ticker_alias, UUIDv5 | recompute a ticker-alias GUID locally; delegate to `memory_fact.subject_from_security` or the registry and the substrate drift onto two GUIDs for one ticker |
| `lib/event_identity.py` | `SecurityEvent@v1` — the event lifecycle above | invent a parallel event id; earnings is not a timeless catalyst |
| `lib/research_identity.py` | the adapter: symbol → identity tag for research rows | write a tag with a null `subject_guid` — indistinguishable downstream from untagged, and it inflates apparent coverage |
| `lib/catalyst_graph.py` | binds events to entities (452 nodes / 1,110 edges live) | — |
| `taxonomy_tagger.py` | the 3-axis taxonomy (content / sector / lifecycle) | see the sentinel rule below |

### Macro data has NO issuer, and must never be given one

`NO_ISSUER_BY_DESIGN` — FRED series, CPI, unemployment, `topic_monitor`. These belong to no
company. Forcing a security GUID onto them would be the same invented-mapping error as a
hand-rolled ticker table, and every join through it would be false. Macro needs its own identity
axis (series id); that is a separate design and not yet built.

A test asserts no `NO_ISSUER_BY_DESIGN` table can appear in `SOURCES`, so the extractor cannot be
pointed at macro data by accident.

*(`fred_economic_data` also does not exist as a table at all — `fred_data_ingest` declares it as
output and it was never created. The integrity sweep reports that as `declared_output_missing`.)*

### Who keeps identity fresh — and why no model may

**A deterministic custodian, `lib/identity_health.py`, lane `identity-spine`.** It alarms on
`registry_stale` (80h grace, so a weekday-only minter does not page on a Sunday),
`coverage_regressed` (CONFIRMED falling — the rank is one-way, so a fall means a feed stopped
publishing identifiers), `producer_unscheduled`, and `registry_unreadable`. Coverage is reported
even when nothing fires, so a slow decline is visible before it becomes an alarm.

**No model runs in that lane, and none may.** `uuid5` is a pure function of (namespace, name):
the same input yields the same GUID forever. That determinism *is* the value of the spine, and a
model in the path destroys auditability while adding nothing — every identity failure found on
2026-09-06 was a count, a clock or a scheduler lookup, and an LLM would have caught none of them.

**The one legitimate model role is proposal, never commitment.** 5,243 of 10,279 entities are
`UNRESOLVED_WITH_REASON` (no CUSIP), and `catalyst_graph` skips 35,928 rows as
`symbol_not_registered`. Deciding whether a symbol in a filing is the same issuer as one in the
registry — across name variants, share classes and corporate actions — is genuine ambiguity, and
that is what a model is for. Its output is written **`CANDIDATE` only**; deterministic evidence
(a CUSIP from Schwab `instruments`) is the sole thing that promotes to `CONFIRMED`. The one-way
rank means a model can never downgrade a confirmed entity or invent a spine. Run it on a **free
OAuth lane** — this is batch reconciliation, not latency-sensitive, and there is no reason to pay.

### Rules that must hold

- **Identity status travels with the tag.** A CUSIP-confirmed tag and a bare-ticker-alias tag are
  not equal evidence. Carry `identity_status` so an agent can weigh it, and **never downgrade** an
  existing tag — a feed that stops publishing CUSIPs must not be able to degrade the corpus.
- **GICS and the thesis vocabulary are different axes and get different columns.** `category_sector`
  holds `ai_chips`, `ai_datacenter`, `defense` — a thesis vocabulary that does not map onto GICS
  (`ai_chips` has no GICS equivalent; GICS `Technology` has no thesis slug). GICS lives in
  `gics_sector`. Merging them collides two vocabularies in one field.
- **Every "unclassifiable" marker needs a shelf life.** A sentinel says *today's classifier could
  not do it*, which expires; it is not a fact about the row. `taxonomy_tagger` selects
  `WHERE category_content IS NULL`, so a `no_match` written there was permanent — measured
  2026-09-06, a bounded 20-row run produced 17 sentinels, 1 usable tag and 0 sectors, and running
  it hourly would have foreclosed ~85% of a 32,060-row backlog in ~64 hours, including against any
  better classifier later. `NO_MATCH_TTL_DAYS` (default 30) re-admits them.
  **Adding a sentinel without a TTL is how you destroy a corpus while reporting success.**
- **Schema changes here are additive.** Add columns; never drop, rename or repurpose one. Downstream
  agents are told to trust these tags.
- **`ADD COLUMN IF NOT EXISTS` still takes ACCESS EXCLUSIVE.** Run DDL once, off-peak, never from a
  recurring job — nine recorded `LockNotAvailable` failures against live readers say so.

### Before changing anything here

Run `ls scripts/lib/ | grep -E 'identity|memory|catalyst'` first. Every one of these already
existed and was dark before it was wired; the constraint on this system has never been build
capacity, it is that built capacity goes unused. `tests/test_identity_memory_module_wiring.py` is
the structural guard — every identity/memory module must have a production consumer or be declared
`KNOWN_DARK`. **That list may shrink and must never grow.**
