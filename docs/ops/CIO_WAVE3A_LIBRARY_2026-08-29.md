# Wave 3A — institutional library home + seasonality off fixtures (2026-08-29)

Companion: `CIO_LIBRARY_CENSUS_2026-08-29.md`.

## Headline: the series backing every `grade=B` label is synthetic

Moving the file was the task. What the move surfaced matters more.

`tests/fixtures/us_equity_monthly_sample.csv` is **not market data**. Two repo
docs already said so — `PHASE11_16_RESEARCH_BRAIN.md` ("synthetic but
statistically usable") and `R3_ALMANAC_REPRODUCTION.md` ("deterministic, not a
vendor print") — and the data confirms it:

| month | this series | actual |
|---|---:|---:|
| 1987-10 | **+3.27%** | ≈ −21.5% |
| 2008-10 | −0.88% | ≈ −16.9% |
| 2020-03 | +2.84% | ≈ −12.5% |
| worst month, 75 years | **−7.88%** | far worse |

The series has never experienced a crash.

**Consequence.** The operator product currently shows
`August all_years: n=75 mean=-0.07% win_rate=45.3% grade=B`, and the registry
defines grade B as *"independently reproduced with usable N and consistent
direction."* Against a synthetic file, that reproduction is a **determinism
check of the pipeline**, not empirical support for a calendar claim. The
number is real arithmetic over unreal data.

I also got this wrong in yesterday's corpus map, where I described the file as
"901 rows of real monthly US equity returns from 1950". It is not. Corrected
here and in the manifest.

Nothing was re-graded in this pass — the operator asked for a number-neutral
move, and re-grading changes operator-visible output. Flagged for decision.
The census proposes Ken French's data library as the lawful replacement that
would let a `B` mean what it says.

## 1) The move

| | |
|---|---|
| from | `tests/fixtures/us_equity_monthly_sample.csv` |
| to | `reference/library/us_equity_monthly_synthetic_1950_2024.csv` |
| md5 | `490569829861df12ca5f63fa1ca9f36c` — **unchanged** |
| manifest | `…/us_equity_monthly_synthetic_1950_2024.manifest.json` |

Renamed because the old name said "sample" and nothing said "synthetic", while
the file backs operator-visible `grade=B` labels.

**Why not `data/cio/library/` as specified.** `cio_phase2_exact_main_deploy.sh`
rsyncs each release with `--exclude='data/'` (line ~312), and `CURRENT/data/cio`
is a symlink to mutable host state. A tracked file under `data/` is therefore
shadowed on the host and never promoted — verified: the 4 tracked files under
repo `data/` do not exist in CURRENT. `reference/` is a normal repo path:
version-controlled, copied into every release, identical across hosts. A test
pins this and will fail if `data/` stops being excluded.

Single resolver in `scripts/lib/cio_library_paths.py`; both consumers
(`cio_seasonality_analytics`, `research_governance/almanac`) repointed. There is
deliberately **no fallback to `tests/`** — a missing library file should surface
as a deployment problem, not silently resolve to test data.

### Number-neutral, as required

| stat | before | after |
|---|---|---|
| `august_general` | n=75 mean=−0.07% win=45.3% **B** | identical |
| `august_midterm` | n=19 mean=−0.69% win=31.6% **C** | identical |
| `september_general` | n=75 **B** | identical |
| `best_six_months` | n=450 **B** | identical |

106 seasonality-dependent tests green after the move.

> **Split into two PRs.** `almanac.py` holds the series path as a live default
> (`p = path or DEFAULT_FIXTURE`), so the move and the repoint cannot be
> separated — which pulls the PR into the R1 scope guard, whose allowlist then
> demands every changed file be named. Rather than widen that boundary to cover
> unrelated work, the move ships alone (this PR, with three tightly-scoped
> allowlist patterns for the library home) and the registry + wiring of
> sections 3–4 ship in the follow-up. This is the "two if the seasonality move
> is cleaner alone" branch of the brief.

## 2–3) Census and registry

The 20–30 publications were never missing — they are catalogued in
`config/cio_research_source_catalog.json` (34 sources). Yesterday's
`CORPUS_UNLOCATED` was my search failure: I swept `data/` and filename globs,
never `config/`.

All 34 carry `full_text_status=NOT_FOUND_IN_FILE_LIBRARY`,
`claim_status=SOURCE_CLAIM_INCOMPLETE`, `license_class=COPYRIGHT`. So the
honest label is not "unlocated" but **catalogued, citation-only, no lawful full
text** — and the catalog says so itself.

`cio_corpus_index.registry()` is now one index over both populations:

    library_facts   11   (3 can corpus_hit — grade A/B, context dimensions)
    catalog         34   (0 on disk, 0 can corpus_hit — all grade D)

No second store was created. Fields per the brief: `source_id`, `family`,
`title`, `path`, `content_hash`, `as_of`, `evidence_grade`, `application_law`,
`dimension_scope`. Freshness remains `research_source_index.decide()` only —
this module keeps no TTL of its own.

## 4) Decision wiring

`corpus_hit` now requires all three: reproduced **A/B** grade, a **context-level**
dimension, and the source index **not stale**.

The third is new. Previously a source whose hash had moved or whose SLA had
lapsed could still be closed by an almanac fact — answering new information with
old context and skipping the research that would have caught it. A
`RESEARCH_EXECUTED` verdict now blocks the corpus branch.

Host dry, unchanged from #636: **445 considered → 8 eligible**, collapse intact,
S5 did not re-expand into 36 Flash jobs, 0 paid calls.

## 5) Discovery

3 candidates proposed dry, full weekly budget, `CANDIDATE` status, no grade, no
ingest, no download. See the census.

## Verification

- 78 tests (Wave 3A + gate v2), 106 seasonality-dependent tests green
- live after promote: `/api/v2/health` and `/api/v3/cio` 200,
  `telegram_sent` false, `cio_run` `DETERMINISTIC_PRODUCT`, cash surfaces agree

## Not done

No cap raised, no notify, no ROTATE, no book merge, no second freshness table,
no second corpus store, no re-grading, no full text ingested. Wave 3B not
started.
