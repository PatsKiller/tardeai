# Watch-Directive Clutter Cleanup (2026-07-01)

Branch: `chore/watch-directive-clutter-cleanup`

## Problem
The v3 Watchlist "Watch Directives" panel had **489 directives**, dominated by **335 active
`trend` directives** with heavy near-duplication: ~10 M&A variants, ~10 power-grid variants,
8 defense-spending variants, 7 data-center, 5 semiconductor-supply-chain, plus 36 dead
`claude_challenger` themes that never surfaced anything, and 3 malformed labels
(`'trend analyst'`, `'trend industry'`, bare `'Energy'`).

Root cause: the only dedup at creation time was **exact normalized-label match**
(`hermes_think_tank._norm_label`, which just strips punctuation). So `"M&A surge"`,
`"M&A and consolidation"`, and `"event-driven M&A…"` are all distinct strings → each spawned a
separate directive that fragmented the same hit signal.

## Scope of this branch

### 1. One-time cleanup — `scripts/watch_directive_dedup.py` (read-only by default)
Three tiers; **nothing is deleted** — dups are `status='archived'` (reversible) and their hits are
re-pointed at the survivor:

| Tier | What | Action | Count |
|------|------|--------|-------|
| 1a | Malformed but working themes (`trend analyst` 367 hits, `trend industry` 118 hits) | **Relabel** (stays active, keeps hits) | 2 |
| 1b | Bare label duplicating a canonical directive (`Energy` → `sector Energy`) | **Merge** (hits reassigned) | 1 |
| 2 | `claude_challenger` themes with 0 lifetime hits | Archive | 36 |
| 3 | Near-dup trend families (think_tank / challenger only) | **Merge** onto one survivor per family, reassign hits | 60 → 7 |

**Result: 335 → 238 active trend directives (−97).** All 25,198 hit rows preserved (dup
directives had distinct `surfaced_at`, so hit reassignment hit zero unique-key collisions).

**Operator directives are NEVER family-merged (operator decision 2026-07-01).** Each operator
standing instruction stays as its own directive — only `think_tank` / `claude_challenger` /
system-generated near-dups collapse. (An earlier draft merged 9 operator directives into
survivors, including 5 distinct operator option-strategy lenses into one — the review caught that
and this rule prevents it.) Survivor among the non-operator members = author precedence
(system > think_tank > challenger), then most hits, then oldest.

Usage:
```
python3 scripts/watch_directive_dedup.py          # dry-run — print the exact plan
python3 scripts/watch_directive_dedup.py --apply  # execute (single transaction, reversible)
python3 scripts/watch_directive_dedup.py --tier 1 # limit to a tier
```

### 2. Creation-time guard — `scripts/watch_directive_canonical.py` + `hermes_think_tank.py`
The cleanup won't stick if think_tank regenerates M&A variants nightly. `_find_existing` now,
after the exact-label check, maps a new `trend` theme to a **canonical family** and — if an active
directive already covers that family — treats it as the existing directive (its keywords/seeds get
merged) instead of inserting another near-dup. Operator ticker/sector directives are never
family-collapsed.

Families live in one shared module (`watch_directive_canonical.py`) so the cleanup and the guard
can never drift apart. Families are deliberately **broad** and conservative — fine-grained intent
is still expressible via explicit operator directives.

`M&A` note: labels are normalized (`&` → space) before matching, so "M&A" arrives as the bigram
`"m a"`; the `\bm a\b` alternative is what catches bare "M&A …" labels (verified it does not
false-match `pharma`/`drama`/`karma`).

## Not in scope (intentional)
- **Not tightening the broad classifier.** Per prior work, the broad research-topic→directive
  classifier is intended; this branch only de-duplicates and prevents *near-dup* proliferation.
- `sector_universe` (one-per-industry) and `operator` directives are left as-is except where an
  operator directive is the chosen survivor of a family merge.

## Execution plan (operator decision: apply after PR review)
1. Merge/land this branch's code.
2. **Back up** `watch_directives` + `watch_directive_hits`.
3. Run the dry-run, eyeball the plan, then `--apply`.
4. Reversal if needed: `UPDATE watch_directives SET status='active' WHERE rationale LIKE '%[archived by watch_directive_dedup]%'` (hit reassignment is not auto-reversed, but no hits are lost).

## Validation done
- Dry-run plan reviewed; family survivors confirmed operator-first.
- `canonical_family` unit-checked for both true matches and false-positive safety.
- Full `--apply` statement set (149 statements) executed against the live DB inside a
  **rolled-back** transaction: clean, 335 → 226, zero hit-row loss.
- All three scripts `py_compile` clean.
