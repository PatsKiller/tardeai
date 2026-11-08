# Self-heal runbook workbook

The operator's 2026-11-08 order (16:44 ET): before any non-code failure is escalated, a deterministic runbook must
try what a code change cannot — and the set of runbooks must be **catalogued, tested, and readable by a human under
pressure**. This directory is that workbook. One page per catalog entry, one index, and the 14-day coverage replay
that proves every real failure signature reaches an entry.

**Freeze in force.** Until the operator approves this catalog, no self-heal fixer runs with `--apply`, no manual
fixer cycle runs, and no Claude/DeepSeek-backed fix attempt is made. Dry/shadow cycles (no model call) are unaffected.
The replay in this directory is dry: it calls no action, writes no receipt and touches no lane.

## What is here

| file | kind | owner of the text |
| --- | --- | --- |
| `<id>.md` (50 files) | generated | `scripts/lib/self_heal_runbook_docs.py` |
| `INDEX.md` | generated | same |
| `COVERAGE.md` | generated | same |
| `COVERAGE.json` | snapshot | `scripts/ops/self_heal_runbook_replay.py` |
| `RULINGS.md` | hand-written | the reviewed decisions behind each disputed cell |
| `README.md` | hand-written | this page |

A generated page is never edited by hand: `python3 scripts/gen_self_heal_runbook_docs.py --check` exits 1 if any page
differs from what the catalog and the snapshot render, and `tests/test_self_heal_runbook_docs_20261108.py` runs that
check in CI. That is the mechanism that keeps the workbook from drifting away from the JSON it describes.

## The source of truth

1. **`config/self_heal_runbook_catalog.json`** (`SelfHealRunbookCatalog@v1`) — the entries: id, category, tier,
   explicit priority, match patterns, preconditions, one whitelisted action, attempts, cooldown, verify contract,
   escalation title, human steps, test labels.
2. **`scripts/lib/self_heal_runbooks.py`** — the engine: `load_catalog` (validates, fails closed), `match_entry`
   (lowest priority wins), `plan_runbook` (pure: attempts -> cooldown -> lane rate limit -> execution-lane rail ->
   preconditions), `apply_runbook` (dry by default; the only host write is archiving a stale existence lock).
3. **`tests/fixtures/self_heal_runbooks/`** — the replay corpus: one synthetic fixture per real signature, with the
   entry it must reach. `tests/test_self_heal_runbook_coverage_20261108.py` **asserts** 22/22 match.
4. **`COVERAGE.json`** — the live replay: every failure in the receipts and the dead-letter store for the window,
   normalized to a signature and planned through the engine.

## How a reader uses it

Find the signature in [COVERAGE.md](COVERAGE.md) -> open the entry page -> follow §3 (diagnosis), §5 (verification),
§6 (rollback). If the tier is `human_only`, the action is the **human's** to run; the engine will only escalate.

## How to regenerate

Both steps are dry except the file writes they name.

```bash
# 1. the replay (reads the receipts + the dead-letter store read-only; plans nothing live)
python3 scripts/ops/self_heal_runbook_replay.py --as-of <UTC instant> --window-days 14 \
    --out docs/runbooks/self_heal/COVERAGE.json --check-gate

# 2. the pages (renders the catalog + the snapshot + the corpus index)
python3 scripts/gen_self_heal_runbook_docs.py --write
python3 scripts/gen_self_heal_runbook_docs.py --check      # must exit 0
```

`--check-gate` exits **3** when a failure signature reaches `K05-unclassified-catch-all` and has no written reason in
the replay's `GATE_REASONS`. That is the catalog's hard requirement ("every mined signature with >= 2 occurrences maps
to an entry — zero unclassified"), enforced rather than asserted.

## How to add or amend an entry

1. Add or edit the entry in the catalog, at its priority position (do not re-sort the file).
2. Add a synthetic fixture under `tests/fixtures/self_heal_runbooks/` (or update the existing one's `expect`), and
   add the entry's synthetic sample to `MATCH_SAMPLE` in `tests/test_self_heal_runbooks_lq1231_20261108.py`.
3. Record the decision in [RULINGS.md](RULINGS.md): the evidence (signature, count, lanes) and what the alternative
   would have done.
4. Re-run the replay, regenerate the pages, run the three test modules, and commit all of it together.

A new action, verify kind, precondition, tier or category has no paragraph in the renderer and **fails the docs
test** until one is written: the closed maps in `scripts/lib/self_heal_runbook_docs.py` are deliberate, so a new entry
cannot ship a page with an empty section.

## Limits a reader should know

- The replay sees **only** what the n8n receipts and the dead-letter store recorded. A lane that failed before it
  wrote a receipt is invisible to the coverage table (the 30-day mining taxonomy is the wider source).
- The signature is the **last stderr line** (or the receipt's reason when there is none). A failure whose
  distinguishing text is an earlier line is counted under the last one.
- Coverage proves an entry **answers** a signature. It does not prove the entry's action would have **worked**: only a
  graded live run does that, and none may run under the freeze.
- An entry at 0 hits is **unexercised**, not dead; the 30-day taxonomy is the evidence for its existence.
- Symbols, paths, tokens, timestamps and digits are collapsed to placeholders (`<SYM>`, `<PATH>`, `<TOKEN>`, `<TS>`,
  `<N>`). This repository is public; a page may not carry a ticker, a host or a credential.

## Tests that hold this workbook

```bash
python3 -m pytest \
  tests/test_self_heal_runbooks_lq1231_20261108.py \
  tests/test_self_heal_runbook_coverage_20261108.py \
  tests/test_self_heal_runbook_docs_20261108.py -q
```

- the engine's own contract (schema, whitelist, priorities, match, precondition refusal, rate limit, dry-run default);
- the replay corpus (22/22 fixtures resolve **and match**, catch-all ceiling empty);
- the workbook (regenerating equals the committed pages, every entry has a page and no page is orphaned, every page
  carries its ten sections, the snapshot is consistent with the pages, no forbidden pattern in a generated page).
