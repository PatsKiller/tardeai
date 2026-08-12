# Catalyst domain + Hermes research de-duplication

**Authority:** `READ_ONLY_ADVISORY` — severity and research never become orders.  
**Branch:** `feature/advisory-desk-v1`  
**Related:** [CLOSED_LOOP_ARCHITECTURE.md](./CLOSED_LOOP_ARCHITECTURE.md), [EVIDENCE_INVENTORY_WS0.md](./EVIDENCE_INVENTORY_WS0.md)

---

## 1. Catalyst calendar domain

### Role

Answers: **what dated events could change materiality, conviction, or revisit timing?**

Does **not** place trades. Under defensive observe it only sharpens:

- urgency / `revisit_at`
- Hermes warm / research-gap priority
- advisory wording (“observe through event” vs “wait for print”)
- Telegram elevation (medium+ ≤5d only)

### Schema (`domain=catalyst`)

```json
{
  "domain": "catalyst",
  "as_of": "…",
  "quality": "OK | DATA_UNAVAILABLE",
  "symbol": "SCHD",
  "events": [
    {
      "event_id": "cat_schd_2026-08-20_distribution",
      "kind": "distribution",
      "session_date": "2026-08-20",
      "horizon_days": 8,
      "severity": "low",
      "confirmed": true,
      "source": "…"
    }
  ],
  "next_event": { },
  "next_elevated_event": { },
  "max_severity": "low",
  "open_count_medium_plus": 0
}
```

**Kinds (controlled):** `earnings` · `ex_div` · `distribution` · `guidance` · `macro` · `index_rebalance` · `regulatory` · `product` · `other` (+ broker aliases).

**Severity:** `low | medium | high | critical` — **deterministic** from kind + metadata (not free-form LLM at ingest). Unknown → `low`. Unconfirmed → capped at `medium`.

### Modules

| Path | Role |
|------|------|
| `scripts/lib/catalyst_policy.py` | Ranks, horizons, min severity per gate, Hermes priority map |
| `scripts/lib/catalyst_domain.py` | Normalize, assign severity, pack rollups, warm/revisit/Telegram/invalidate helpers |

### Desk gates (single policy table)

| Gate | Min severity | Horizon |
|------|--------------|---------|
| Telegram elevate | medium | ≤5d |
| Revisit tighten | medium | ≤5d |
| Hermes warm | medium | ≤5d |
| Research gap | medium | ≤10d |
| Cache invalidate | medium | ≤15d |
| Materiality bump | high | ≤5d |

**Anti-pattern:** every distribution marked high; low SCHD ex-div must not spam warm or Telegram.

### Integration points

| Surface | Behavior |
|---------|----------|
| Plan enrich assembler | Always attach `domain=catalyst` (+ legacy `catalysts`) |
| Detector S1 | `calendar_catalyst_material`; snapshot path `enrich_evidence_with_catalysts` |
| Hermes enqueue | Warm priority from severity × weight/DD compound |
| TTL reuse | Blocked on `catalyst_invalidated` when medium+ event new after result `as_of` |
| Telegram notify | Elevates one line only for medium+ ≤5d |
| CC plan detail | Catalyst calendar table + Hermes research panel |

---

## 2. Hermes fingerprint de-duplication

### Identity

| Field | Meaning |
|-------|---------|
| `research_id` | Unique instance |
| `fingerprint` | Logical identity of the ask (`sha256:…` from `fp@v1`) |

### Canonical hash inputs

`fp_version`, `plan_id`, `situation_type`, `scope`, `symbol`, `thesis_version`, **normalized** questions (case/space/punct/order-invariant).

**Excluded:** `priority`, timestamps, `needed_by`, evidence snapshot numbers, provenance.

### Enqueue order

```text
1. Compute fingerprint
2. In-flight (queued|running|started) → return existing; optional priority bump
3. Fresh completed within TTL + quality gate → reuse (unless force_refresh / catalyst_invalidated)
4. Else create new queued request
```

### Modules

| Path | Role |
|------|------|
| `hermes_research_fingerprint.py` | `compute_fingerprint` / payload |
| `hermes_research_policy.py` | TTL by priority/situation, quality gate, catalyst invalidation |
| `hermes_research_queue.py` | Pure `EnqueueResult` core |
| `cio_hermes_research.py` | JSONL + projection (`by_fingerprint_open` / `by_fingerprint_completed`) |

### TTL defaults

| Priority | TTL |
|----------|-----|
| critical | 2h |
| high | 6h |
| normal | 12h |
| low | 24h |

Situation overrides: S1/S6 → 6h, S5 → 12h.

### Reasons (telemetry)

`created` · `duplicate_in_flight` · `priority_bumped` · `reused_fresh_result` · reuse misses include `ttl_expired`, `catalyst_invalidated`, `force_refresh`, …

**No Telegram** on pure de-dupe or pure reuse.

### Storage

```text
data/cio/hermes_research_requests.jsonl
data/cio/hermes_research_results.jsonl
data/cio/hermes_research_projection.json
```

---

## 3. Tests

| File | Coverage |
|------|----------|
| `tests/test_hermes_research_fingerprint.py` | Normalize, de-dupe, priority bump, TTL reuse |
| `tests/test_hermes_research_loop.py` | Worker claim/complete, TTL, force, order lint, double-claim |
| `tests/test_catalyst_severity.py` | Severity matrix + gates |
| `tests/test_catalyst_integrations.py` | Detector fire, TTL catalyst invalidate |

---

## 4. Hermes loop (worker)

| Piece | Status |
|-------|--------|
| Claim → run → complete → `on_hermes_completed` | **Live** (`hermes_worker` + `hermes_research_loop`) |
| Stub / CatalystFirst backends | **Live** (swap for full bridge later) |
| `/cio research <plan_id>` | **Live** (operator_forced, TTL bypass) |
| S1/S6 detector emit on plan create | **Live** |
| Gold-set judge freeze | Open |
| Full governed HermesBridgeBackend | Open (backend pluggable) |

```bash
PYTHONPATH=scripts python3 -m scripts.hermes_cio_worker --once
PYTHONPATH=scripts python3 -m scripts.hermes_cio_worker --drain --max 5 --backend catalyst
```

**Bottom line:** Catalyst severity is a small policy table plus `sev_at_least` at four gates. Hermes never double-queues the same ask; fresh completed results reuse until TTL expires or a material calendar change invalidates them.
