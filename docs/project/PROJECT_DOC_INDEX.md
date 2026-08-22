## Research lifecycle standard (2026-08-21)
| Document | Purpose |
|----------|---------|
| `docs/ops/RESEARCH_LIFECYCLE_STANDARD.md` | Canonical: research only on new/changed/stale/triggered content; reuse unchanged; log EXECUTED / SKIP_UNCHANGED / SKIP_FRESH |
| `docs/RESEARCH_PRIORITIZATION.md` | Lane/tier SLA; due is a candidate, not a re-analyze-all |
| `docs/ops/RESEARCH_TIER_LLM_CADENCE.md` | Five universe tiers; T1-WATCH is the only watchlist research tier; S0–S3 / hygiene 1–3 are not LLM queues; 2026-08-22 confirm-run |
| `docs/ops/TELEGRAM_FEED_REMEDIATION_2026-08-22.md` | P0 T1/T2 Telegram suppress/edit; T3–T7 after 8/27 |

## Alpaca Multi-Account Taxonomy R1–R5 (2026-07-21)
| Document | Purpose |
|----------|---------|
| `docs/sessions/ALPACA_TAXONOMY_BUILD_2026-07-21.md` | **Build handoff** — commits, proofs, next sessions |
| `docs/_findings/alpaca_taxonomy_audit_2026-07-21.md` | Ground-truth audit + P0 remediations |
| `docs/brokers/trading-environments.md` | D1 keys: `tradeai_automated` / `alpaca_taxable_live` / `alpaca_ira_live` |
| `docs/brokers/alpaca-live-accounts.md` | Live scaffolds roadmap (DISABLED) |
| `docs/brokers/tradingview-lanes.md` | TV manual + dormant webhook design |
| `docs/brokers/paper-trading.md` | Path A operator procedures |
| `docs/brokers/paca-accounts.md` | **Pointer only** — superseded naming |

## Decision Packet Operator Card + RTH Refresh (2026-07-21)
| Document | Purpose |
|----------|---------|
| `docs/architecture/DECISION_PACKET_OPERATOR_CARD_AND_RTH_REFRESH.md` | **Canonical** operator card + `should_be_stale` / RTH 4h TTL / shadow-batch freshness / material technical hash |
| `docs/COMMAND_CENTER_V3_WATCHLIST.md` | Watchlist hub — operator band states + link to architecture |
| `docs/CHANGELOG.md` | 2026-07-21 entry · commit `b2fbcd90` |

## Analyst Prospectus RC1 — Full Coverage, Card Links, Urgent Cadence (2026-06-24)
| Document | Purpose |
|----------|---------|
| `docs/reporting/REPORTING_ENGINE.md` | **Reporting module** (updated): RC1 batch tiers (`engine`/`oversight`), card icon-links + tooltip, refresh cadence table (weekly Grok+ChatGPT / urgent-email / monthly Claude / prewarm) |
| `scripts/analyst_urgent_refresh.py` | Off-cycle urgent-change detector — regenerates rec-flipped holdings + emails operator the PDFs (cron 07:35 weekdays) |
| `apps/command-center-v3/src/components/HoldingReportLinks.tsx` | Card icon-links (PDF/Word/regenerate) + rich date-created hover tooltip on Portfolio + Watchlist hubs |

## Analyst Prospectus v4 — Sell-Side Design Re-platform + Depth (2026-06-24)
| Document | Purpose |
|----------|---------|
| `docs/reporting/REPORTING_ENGINE.md` | **Reporting module** (updated): v4 rendering stack (Playwright PDF + python-docx + mplfinance), `--engine` flag, oversight enforcement, install/flag-back |
| `scripts/report_render.py` | HTML/CSS single-source renderer (Jinja2 → Playwright PDF + styled DOCX); `templates/analyst_report.html.j2`, `assets/analyst_report.css`; new Options & Income + Analyst Commentary sections; `tests/test_report_render.py` |
| `scripts/report_visuals.py` | `chart_technical` — mplfinance candlestick + vol + RSI + MACD + Bollinger + SMA w/ drawn entry/stop/target/support |

## Analyst Prospectus v3.1 — Synthesis Quality + Claude Oversight (2026-06-24)
| Document | Purpose |
|----------|---------|
| `docs/reporting/REPORTING_ENGINE.md` | **Reporting module** (updated): Claude cloud-oversight pipeline + cost gate + `--claude-oversight`/`oversight-only` flags; v3.1 section schema incl. `analyst_predictions`, `hermes_research`; continuity/volatility/agent/thesis-band/peer/Finviz-rating fixes |
| `scripts/report_oversight.py` | Advisory free dual-lane critique + cost-gated Claude arbiter; `meta.claude_oversight` stamp; `tests/test_report_oversight.py` |

## Documentation Consolidation (2026-06-22)
| Document | Purpose |
|----------|---------|
| `docs/LIVE_SYSTEM_FACTS.md` | **Canonical live scale counts** — tables/crons/scripts/strategies; regenerate via `generate_system_facts.py` |
| `docs/project/DOCS_CONSOLIDATION_2026_06_22.md` | A1A closeout: purge hard-coded counts, drift detector fix, runtime commit |
| `docs/_audit/drift_report.md` | Drift audit log (2026-06-02 + 2026-06-22 entries) |

## Stabilization + Maturity Audit (2026-06-22)
| Document | Purpose |
|----------|---------|
| `docs/project/STABILIZATION_SESSION_2026_06_22.md` | Track-1 stabilize: agent backlog, screener upsert fix, SIEM triage, overnight LLM queue root cause |
| `docs/project/MATURITY_AUDIT_2026_06_22.md` | Area maturity scores (≈7.1/10) from live health/DB probe |

| `docs/project/STRATEGY_SCOREBOARD_RR_EXPECTANCY_20260608.md` | Scoreboard R:R + Expectancy columns, ∞ for no-loss, expectancy-aware status (display), self-healing freshness |
## Portfolio Lookthrough Cadence Migration — ALL CADENCES COMPLETE (Phase 210, 2026-06-07)
| Document | Purpose |
|----------|---------|
| `docs/project/PHASE210_LOOKTHROUGH_CADENCE_MIGRATION_CLOSEOUT.md` | lookthrough (READ_ONLY_SNAPSHOT) migrated + legacy retired; ALL report cadences now controller-owned (backup/daily/weekly/monthly/lookthrough); only db_retention/price_cache excluded; dry-run/apply/diff/systemd-cycle PASS |

## Portfolio Monthly Report Cadence Migration (Phase 209, 2026-06-07)
| Document | Purpose |
|----------|---------|
| `docs/project/PHASE209_MONTHLY_PORTFOLIO_REPORT_CADENCE_MIGRATION_CLOSEOUT.md` | monthly report migrated to controller (advisory-draft review-only) + legacy portfolio-monthly.timer retired (operator-approved); cadence timer day-1 07:35; dry-run/apply/diff/systemd-cycle PASS; no broker/proposal/protection/strategy-YAML; only lookthrough remains |

## Portfolio Weekly Report Cadence Migration (Phase 208, 2026-06-07)
| Document | Purpose |
|----------|---------|
| `docs/project/PHASE208_WEEKLY_PORTFOLIO_REPORT_CADENCE_MIGRATION_CLOSEOUT.md` | weekly report migrated to controller (advisory-draft review-only) + legacy portfolio-weekly.timer retired (operator-approved); cadence timer Sun 20:30; dry-run/apply/diff/systemd-cycle PASS; no broker/proposal/protection/strategy-YAML changes; monthly/lookthrough not migrated |

## Portfolio Daily Report Cadence Migration (Phase 207, 2026-06-07)
| Document | Purpose |
|----------|---------|
| `docs/project/PHASE207_DAILY_PORTFOLIO_REPORT_CADENCE_MIGRATION_CLOSEOUT.md` | daily report cadence migrated to controller (advisory-draft review-only) + scheduled parallel (tradeai-portfolio-daily-cadence.timer Mon-Fri 07:30); dry-run/apply/diff/systemd-cycle all PASS; legacy kept active (retired=0, deferred to Phase 208); /api/v2/system/portfolio-cadence-status added; no broker/proposal/protection/GO-WAIT/strategy changes |

## Hermes Legacy/Retired Agent Visibility (Phase 206, 2026-06-07)
| Document | Purpose |
|----------|---------|
| `docs/project/PHASE206_HERMES_LEGACY_AGENT_VISIBILITY_CLOSEOUT.md` | read-only "Legacy / Retired Agents" audit section in v3 System→Hermes: inventory script (24 items, redacted, no exec) + GET /api/v2/hermes/legacy-agents + HermesPanel card; gateway stays disabled, no wrapper exec, retired dirs unchanged; 206A–H evidence + mapping plan |

| `docs/project/PHASE208_HERMES_END_TO_END_AGENT_AUDIT_CLOSEOUT.md` | Phase 208 closeout: full Hermes identity/SOUL/job/fleet audit; retired=audit-only proof; 0 P0 risks |
| `docs/hermes/HERMES_TRADEAI_TOOL_POLICY_DECISION_20260607.md` | Operator decision: tradeai/tradeai12b stay fully tool-less (advisory-only); rationale + consequence |
| `docs/hermes/HERMES_IDENTITY_EDITOR_20260607.md` | v3 Hermes identity editor (model/provider + SOUL) with hard guards; System->Hermes + /v3/hermes graph |
| `docs/hermes/HERMES_IDENTITY_PROFILES_20260607.md` | Due diligence + seeded identities for all 5 Hermes profiles (label/purpose/description + role SOULs); scripts/seed_hermes_identities.py |
| `docs/project/PHASE209_HERMES_TRADEAI_WORKFLOW_MATRIX_CLOSEOUT.md` | Phase 209 closeout: Hermes/TradeAI workflow ownership matrix + v3 mapping; librarian owner; tradeai vs tradeai12b; 0 P0 |
| `docs/hermes/HERMES_TRADEAI_RESEARCH_AND_SELF_LEARNING_ARCHITECTURE.md` (+.docx) | Peer-review architecture: Hermes self-learning + internal/external research lanes |
| `docs/project/PHASE210_HERMES_RESEARCH_SELF_LEARNING_MATRIX_CLOSEOUT.md` | Phase 210 closeout: self-learning loops + research lane design + v3 matrix |
| `docs/hermes/HERMES_AGENT_FUNCTION_INDEX.md` | who handles X: research ideas/sources/librarian/taxonomy |
| `docs/hermes/HERMES_DEEP_RESEARCH_LOCAL_RUNNER_20260607.md` | Internal overnight deep-research runner (gemma3:27b/overnight, advisory-staging-only, manual) |
| `docs/hermes/HERMES_CLAUDE_EXTERNAL_LANE_20260607.md` | Claude external researcher lane: wired, redaction-first, advisory-only, manual; blocked by Anthropic credits |
| `docs/hermes/EXTERNAL_LLM_USAGE_POLICY_20260607.md` | External LLM governance: limited criteria, per-call operator approval, data-class restrictions, cost/privacy, escalation ladder, prohibited uses |
| `docs/hermes/HERMES_EXTERNAL_LANES_STATUS_20260607.md` | External lanes status: claude(API,credits), chatgpt(openai-codex OAuth FREE,auth_pending), grok(xAI API,live) |
| `docs/hermes/HERMES_JOURNAL_BACKTEST_INTERNAL_EXTERNAL_MAPPING_20260607.md` | Journal-review + backtesting → internal owner → external escalation lane/triggers |
| `docs/hermes/HERMES_REPORTS_WATCHLIST_FEED_AND_LLM_CURATION_20260607.md` | Audit: Hermes feeds watchlist(RAG) not reports (gap); curated-LLM+learning standard + agent mapping + next gates |
| `docs/hermes/HERMES_LLM_AUTH_STATUS_20260607.md` | LLM OAuth status + guided login (Google SSO, no creds stored); System→Hermes card |
| `docs/project/PHASE212_CODEX_HEADLESS_HERMES_BUILD_EVALUATION_CLOSEOUT.md` | Phase 212: 0.16.0 is latest Hermes; headless Codex unfixable now; Grok=free automated lane; no upgrade/promotion |
| `docs/project/PHASE213_CODEX_HEADLESS_CLOSEOUT_EXTERNAL_LANE_HARDENING.md` | Phase 213: capability cache + lane hardening; Codex headless not retried (hermes_headless_limit); Grok=free automated lane |
| `docs/hermes/PHASE213I_EXTERNAL_FEEDBACK_LOOP_AND_DRILLDOWN.md` | External-researcher feedback loop (usefulness scoring) + all-loop drill-down (steps/queue/completed/timestamps) |
| `docs/project/PHASE214_COORDINATOR_KILLSWITCH_REPOINT_CLOSEOUT.md` | Phase 214: canonical kill-switch helper; Coordinator centralized; retired .hermes/DISABLED ignored (P1 #1 closed) |
| `docs/hermes/HERMES_AGENTS_WORKFLOWS_SOULS_AND_SELF_LEARNING_MATRIX.md` | CANONICAL Hermes matrix (agents/workflows/SOULs/loops/lanes) rebuilt from live v3 portal truth (.md + .docx) |
| `docs/project/PHASE217_PORTAL_SYSTEM_DOC_ALIGNMENT_CLOSEOUT.md` | Phase 217: canonical status builder; portal/state/docs aligned from one source (deep lane built+scheduled, serverops P1) |
## Hermes Global Install Migration (2026-06-06)
| `docs/hermes/HERMES_RESEARCH_GRAPH_KILL_SWITCH_REPOINT_20260606.md` | repoint research-fleet kill-switch from retired hermes_sidecar/.hermes/DISABLED (+non-canonical ~/.hermes/DISABLED) to canonical data/runtime/HERMES_DISABLED across 7 live readers + API/UI + cron comment; OFF/ON/OFF verified; banner wording fixed (touch=halt) |
| `docs/hermes/HERMES_AGENT_GRAPH_MIGRATION_AUDIT_20260606.md` | Reconciles /v3/hermes research-agent graph vs global profiles (both kept); SearXNG UP diagnosis + ping fix |
| `docs/hermes/HERMES_DEV_CODEX_SETUP_20260606.md` | dev profile Codex readiness: verified openai-codex OAuth device-code route (operator-run); SOUL hardened; tradeai unchanged |
| `docs/hermes/HERMES_COMMAND_CENTER_PANEL_20260606.md` | Command Center System→Hermes panel: profile status, SOUL editor, terminal commands, Codex-dev readiness (read-only/guarded) |
| `docs/hermes/HERMES_GLOBAL_PROFILE_MIGRATION_V1_8_CLOSEOUT_20260606.md` | Final v1.8 closeout: global Hermes canonical, sidecar retired/dormant, Reference Architecture updated, safety state verified |

| `docs/project/Trade_AI_v12_Reference_Architecture.docx` | Canonical architecture; includes **Hermes Global Profile Architecture Update — 2026-06-06** + Migration Completion Addendum |

| Document | Purpose |
|----------|---------|
| `docs/hermes/HERMES_GLOBAL_INSTALL_MIGRATION_20260606.md` | Sidecar->global Hermes v0.16.0; verified state, canonical commands, no-delete policy, rollback |
| `docs/hermes/HERMES_PROFILE_MATRIX_20260606.md` | default/tradeai/tradeai12b/dev/serverops/sidecar matrix (path/model/tools/purpose/safety) |
| `docs/hermes/HERMES_MODEL_CANARY_STATUS_20260606.md` | gemma3:4b approved default; 12b-ctx4k experimental; qwen3:14b removed; canaries pass live |
| `docs/hermes/HERMES_SIDECAR_RETIREMENT_PLAN_20260606.md` | Staged reversible retirement (A-C done; Stage D EXECUTED 2026-06-06 (rename-retire, no deletion)) |
| `docs/hermes/HERMES_CURATED_MIGRATION_INVENTORY_20260606.md` | What migrated vs intentionally excluded (no secrets/dumps/qwen); rollback evidence |

## Profit-Capture Evidence-Floor Ceiling (2026-06-06)
| Document | Purpose |
|----------|---------|
| `docs/project/PROFIT_CAPTURE_EVIDENCE_FLOOR_CEILING_20260606.md` | determination: reliable n≥20 floor NOT reachable (Schwab winners are duplicates of paper / too old for intraday paths / stopless); true ceiling 9, clean INFU planned_stop repair → 11; shortcuts (double-count, ambiguous-stop guess) refused; DO_NOT_GRAFT upheld |

## Profit-Capture Intrabar Path + Path-Measured Premature-Exit (Phase 206c, 2026-06-06)
| Document | Purpose |
|----------|---------|
| `docs/project/PROFIT_CAPTURE_INTRABAR_PREMATURE_EXIT_20260606.md` | ingest real 5m intrabar paths (trade_intrabar_bars, 3043 bars/29 trades, all 13 winners) + path-replay pricer → premature-exit cost now PATH-MEASURED; reverses single-peak optimism (trail5 +$447→net −$266); every rule net-negative; still DO_NOT_GRAFT (reliable n=8<20); validation 14/14 |

## Profit-Capture Rule Backtest Quality + Hardening (Phase 206b, 2026-06-06)
| Document | Purpose |
|----------|---------|
| `docs/project/PROFIT_CAPTURE_BACKTEST_QUALITY_REVIEW_20260606.md` | adversarial review: raw trail5_after_2R signal NOT decision-grade (loser-dominated, 62% ≤3-bar MFE, mfe_r outliers to 48R, reliable n≈2); DO_NOT_GRAFT upheld |
| `docs/project/PROFIT_CAPTURE_RULE_BACKTEST_HARDENING_20260606.md` | data-quality gate + winners-only + reliable/effective sample reporting + reliable-n confidence + honest premature-exit (upper bound); recovery $2,728→$447 UB @ reliable n=2; all DO_NOT_GRAFT; validation 13/13 |

## Drive Sync Runtime-Dump Excludes (2026-06-06)
| Document | Purpose |
|----------|---------|
| `docs/project/DRIVE_SYNC_RUNTIME_DUMP_EXCLUDES_20260606.md` | exclude Hermes drain payloads + snapshot JSON (phase3b_dryrun, backlog_health/*.json, latest_*_summary.json) from Drive sync via is_runtime_dump_excluded() helper; SKIPPED/CLEANUP logging; 12 stale JSONs purged, curated .md preserved |

## V3 Protection Give-Back + Canonical Profit-Capture (Phase 206, 2026-06-06)
| Document | Purpose |
|----------|---------|
| `docs/project/V3_PROTECTION_GIVEBACK_ROOT_CAUSE_20260606.md` | root cause: advisory engine is paper-only + open-trade-only + started 2026-06-02; 7/9 give-back winners closed before engine, 2 ignored, 117 Schwab winners excluded; canonical $1,239.29 left |
| `docs/project/V3_PROTECTION_PROFIT_CAPTURE_ENHANCEMENT_20260606.md` | canonical `trade_profit_capture_analysis` (keyed trade_instance_id) + advisory gap diagnostic + evidence-only rule backtest (best trail5_after_2R) + shadow recs (none grafted) + enriched advisory + rebuilt v3 Protection tab; validation 10/10; no trading change |
| `docs/project/V3_JOURNAL_FIELD_COMPLETENESS_BACKFILL_20260606.md` | exact-only journal backfill: close_reason 47→100%, broker 100%, post_analyzed 12→21% (review-gated), catalyst left NULL (no exact source) |

## Hermes Summary Recovery (2026-06-06)
| Document | Purpose |
|----------|---------|
| `docs/project/HERMES_SUMMARY_RECOVERY_20260606.md` | bounded lenient summary recovery for drain residuals (alt keys/raw para; quality-gated, no fabrication); validation 10/10 |

## v3 LLM-Review Provenance Backfill + Base Data Quality (2026-06-06)
| Document | Purpose |
|----------|---------|
| `docs/project/V3_LLM_REVIEW_PROVENANCE_BACKFILL_20260606.md` | exact provenance backfill (strategy 4->2055, ti 4->28, 100% provenance) + writer-side stamping; filters 6/6 |
| `docs/project/V3_BACKTESTING_BASE_DATA_QUALITY_PLAN_20260606.md` | advisory per-tab data trust scorecard (excellent/usable/advisory/untrusted) |

## v3 Backtesting Filters — All Tabs (2026-06-06)
| Document | Purpose |
|----------|---------|
| `docs/project/V3_BACKTESTING_FILTERS_ALL_TABS_20260606.md` | account/strategy filter wired into Entry Quality + AI Trade Eval + all tab fetches (registry arity dispatch); honest upstream data gaps noted |

## v3 LLM-Review Per-Row Provenance (2026-06-06)
| Document | Purpose |
|----------|---------|
| `docs/project/V3_LLM_REVIEW_PROVENANCE_20260606.md` | provenance kind (paper/imported_backtest/simulation) + trade_instance_id lineage per review row; audit #9 RESOLVED — all 9 items done |

## v3 Backtest Last-Run Badge Fix (2026-06-06)
| Document | Purpose |
|----------|---------|
| (in `V3_JOURNAL_BACKTESTING_INTEGRITY_AUDIT_20260606.md` #1) | /backtesting/status adds last_runs per pipeline + last_run_overall; badge shows freshest (not one ambiguous stale date) |

## v3 LLM-Review Ollama Health Gate (2026-06-06)
| Document | Purpose |
|----------|---------|
| `docs/project/V3_LLM_REVIEW_OLLAMA_HEALTH_GATE_20260606.md` | Health-gated review cron (SKIPPED_LLM_UNHEALTHY, no flood) + error classification (1671 infra/60 parser) + UI categories; audit #7 RESOLVED |

## v3 Missed-Opportunities Dedupe + Verdict Fix (2026-06-06)
| Document | Purpose |
|----------|---------|
| `docs/project/V3_MISSED_OPPORTUNITIES_DEDUP_VERDICT_FIX_20260606.md` | proposal_id dedupe (1461->168) + sim_outcome_verdict (incl MIXED 99); audit #4/#5 RESOLVED |

## v3 Journal Backtesting Integrity Audit (2026-06-06)
| Document | Purpose |
|----------|---------|
| `docs/project/V3_JOURNAL_BACKTESTING_INTEGRITY_AUDIT_20260606.md` | Read-only audit: stale badge, missed-proposal dedup, 85% LLM infra errors, stale-basis pollution FIXED (10 invalidated); page = diagnostic-only until fixes land |

## Hermes All-Trades Reflection Drain (2026-06-06)
| Document | Purpose |
|----------|---------|
| `docs/project/HERMES_ALL_TRADES_REFLECTION_DRAIN_20260606.md` | Batch 1 against closed_trade_needing_reflection: +4 schwab reflections, linked 24->28, backlog 165->161 |

## Phase 205 Legacy Backup Retirement (2026-06-06)
| Document | Purpose |
|----------|---------|
| `docs/project/PHASE205_LEGACY_BACKUP_RETIREMENT_20260606.md` | Operator-approved reversible retirement: pg timer + secrets-env cron retired (cadence covers); weekly secrets-data KEPT (coverage gap) |

## Closed-Loop Structured News Linkage (2026-06-06)
| Document | Purpose |
|----------|---------|
| `docs/project/CLOSED_LOOP_NEWS_LINKAGE_20260606.md` | trade_instance_news structured FK by lifecycle window (35 links/27 instances); open-trade hold-window capped |

## Closed-Loop Imported Edge Comparison (2026-06-06)
| Document | Purpose |
|----------|---------|
| `docs/project/CLOSED_LOOP_IMPORTED_EDGE_COMPARISON_20260606.md` | trade_edge_comparison 43->101 (schwab per-trade-backtest, no fabricated proposal edge) |

## Closed-Loop ALL-TRADES Certification Re-Audit (2026-06-06)
| Document | Purpose |
|----------|---------|
| `docs/project/CLOSED_LOOP_LEARNING_CERTIFICATION_REAUDIT_ALL_TRADES_20260606.md` | Cert @db1aae3/@f188ebe/@6c3d62f/@01d3c66: STRUCTURE PASS, edge+news RESOLVED (news noise-blocked: 35 links, 0 firehose), density PARTIAL, learning SHADOW_ONLY |

## Closed-Loop All-Trades Abstraction (2026-06-06) — CANONICAL
| Document | Purpose |
|----------|---------|
| `docs/project/CLOSED_LOOP_ALL_TRADES_ABSTRACTION_20260606.md` | Broker/account-neutral trade_instances; paper is one source; trade_instance_id canonical |
| `docs/project/CLOSED_LOOP_ALL_TRADES_ABSTRACTION_DUE_DILIGENCE_20260606.md` | Evidence: paper-specific surface + ledger sources |
| `scripts/migrate_trade_instances.py` · `backfill_trade_instances.py` · `validate_all_trades_closed_loop.py` | create+backfill (353) + 14/14 validation |

# Trade AI v12 — Documentation Index

**Updated:** 2026-06-04
**Protocol:** Any documentation change must follow `/docs/A1A.md` protocol.

## v3 Open Trades — False-Positive Fix (2026-06-05)
| Document | Purpose |
|----------|---------|
| `docs/project/OPEN_TRADES_FALSE_POSITIVE_ROOT_CAUSE_20260605.md` | Root cause (trades.status=open phantom lots, AXTI) + fix (source of truth = holdings.json + paper_trades; stale excluded) |
| `scripts/validate_open_trades_intelligence.py` | Regression: no AXTI/zero-share/CUSIP/dup; current-holdings count |

## Closed-Loop Step 7 — Hermes Paper-Loop Targeting (2026-06-05)
| Document | Purpose |
|----------|---------|
| `docs/project/CLOSED_LOOP_STEP7_HERMES_PAPER_TARGETING_20260605.md` | closed_paper_trade targeting tier; related_trade_id 2->4, cron works through rest |

## Closed-Loop Certification RE-AUDIT (2026-06-05)
| Document | Purpose |
|----------|---------|
| `docs/project/CLOSED_LOOP_LEARNING_CERTIFICATION_REAUDIT_20260605.md` | Post-Steps-1-6 re-run: STRUCTURE=PASS, DATA DENSITY=PARTIAL; was->now matrix |

## Closed-Loop Step 6 — Lessons->Scoring (Shadow Evidence) (2026-06-05)
| Document | Purpose |
|----------|---------|
| `docs/project/CLOSED_LOOP_STEP6_LESSONS_TO_SCORING_SHADOW_20260605.md` | shadow-vs-outcome efficacy + graft gate (INSUFFICIENT_EVIDENCE_DO_NOT_GRAFT; n=3) |
| `scripts/evaluate_shadow_efficacy.py` | candidate_shadow_efficacy; evidence only, never alters GO/WAIT |

## Closed-Loop Step 5 — Shadow DB + Loop-Closure (2026-06-05)
| Document | Purpose |
|----------|---------|
| `docs/project/CLOSED_LOOP_STEP5_SHADOW_DB_AND_FEEDBACK_20260605.md` | candidate_shadow_scores (DB-keyed shadow) + outcome_fed_back closure (9->19) |
| `scripts/persist_shadow_scores.py` · strategy_learning_shadow_scorer.py | persist shadow to DB + set outcome_fed_back where learning derived |

## Closed-Loop Step 4 — Edge Comparison (2026-06-05)
| Document | Purpose |
|----------|---------|
| `docs/project/CLOSED_LOOP_STEP4_EDGE_COMPARISON_20260605.md` | Post-exit realized-vs-expected edge comparison (paper_trade_edge_comparison) |
| `scripts/compute_edge_comparison.py` | builds table; realized r vs proposal backtest avg_r; NO_DATA flagged not fabricated |

## Closed-Loop Step 3 — Keyspace Unification (2026-06-05)
| Document | Purpose |
|----------|---------|
| `docs/project/CLOSED_LOOP_STEP3_KEYSPACE_UNIFICATION_20260605.md` | paper_trades.trade_key + journal/backtest paper_trade_id; backtest engine UNIONs paper trades |
| `scripts/unify_trade_keyspace.py` · trade_backtest_engine.py · api_v2 journal_review_write | additive keyspace + paper-aware generators |

## Closed-Loop Step 2 — Hermes Trade Linkage (2026-06-05)
| Document | Purpose |
|----------|---------|
| `docs/project/CLOSED_LOOP_STEP2_HERMES_TRADE_LINKAGE_20260605.md` | Stamp hermes related_trade_id/related_proposal_id at write + conservative 1:1 backfill |
| `scripts/hermes_autonomous_loop.py` · `backfill_hermes_trade_links.py` | get_ticker_targets resolves ids; reflection writes stamped; backfill 0→2 (ambiguous skipped) |

## Closed-Loop Step 1 — Execution Lineage (2026-06-05)
| Document | Purpose |
|----------|---------|
| `docs/project/CLOSED_LOOP_STEP1_EXECUTION_LINEAGE_20260605.md` | Stamp signal/card/candidate + broker/account lineage on paper_trades; exact backfill; coverage |
| `docs/project/CLOSED_LOOP_STEP1_LINEAGE_DUE_DILIGENCE_20260605.md` | Submit-path + schema due diligence |
| `scripts/trade_lineage.py` · `backfill_trade_lineage.py` · `validate_trade_lineage_step1.py` | neutral lineage helper + exact backfill + 10/10 validation |

## Cost Basis — June 5 CSV + Income Repair (2026-06-05)
| Document | Purpose |
|----------|---------|
| `docs/project/COST_BASIS_JUNE5_CSV_REPAIR_20260605.md` | Latest-CSV basis reconstruction + V owner override + FCNTX candidate + income ledger ($10,543.13) |
| `scripts/patch_holdings_cost_basis.py` · `validate_holdings_cost_basis.py` | latest-file discovery + overrides + income ledger; 14/14 anchor validation |
| `data/portfolios/input/cost_basis_overrides.json` · `state/income_ledger.json` | transfer-basis overrides + income ledger (gitignored data) |

## v3 Open Trades — Actionable Position Intelligence (2026-06-05)
| Document | Purpose |
|----------|---------|
| `docs/architecture/V3_OPEN_TRADES_INTELLIGENCE_2026_06_05.md` | All-account position command surface — endpoint, data sources, card design, ownership, no-write boundary |
| `scripts/open_trades_intelligence.py` + `GET /api/v2/open-trades/intelligence` | read-only aggregate (technicals+news+Hermes+sector+protection), batched, NaN-safe |
| `apps/.../components/OpenTradesIntelligence.tsx` | summary header + filter/sort toolbar + rich cards; ProtectionPanel collapsible |

## ATM → Broker/Account Automation Console — Phase 1 (2026-06-05)
| Document | Purpose |
|----------|---------|
| `docs/architecture/ATM_BROKER_ACCOUNT_AUTOMATION_2026_06_05.md` | **Account-aware Automation Control Center** — data model, API, UI, ownership map, remaining |
| `docs/architecture/ATM_BROKER_ACCOUNT_REFACTOR_DUE_DILIGENCE.md` | Pre-build due diligence (current components/endpoints/hard-codings) |
| `scripts/migrate_broker_account_model.py` | Additive tables (broker_accounts, account_automation_policies+audit, proposal_account_routes, broker_capability_checks) seeded from accounts+atm_config |
| `apps/.../components/ATMControlPanel.tsx` | Rebuilt: API-capable account selector + per-account policy/risk/readiness + Manage-APIs modal (env paper/sandbox/live) + Edit-Automation modal (editable name); AUTO_LIVE selectable, env-gated |
| API: `/api/v2/broker-accounts[/enums\|/automation-policy\|/readiness]` + guarded `/api/v2/admin/broker-account/{api,policy}` | account-aware read + gate-interlocked writes |
| `docs/architecture/ATM_EXECUTOR_AUTOMATION_MODE_WIRING_2026_06_05.md` | Executor (atm_auto_approver) reads automation_mode (additive, interlock-preserving); verified MANUAL_REVIEW→held, AUTO_PAPER→approves |
| `docs/project/PHASE_ATM_ALPACA_PAPER_AUTOLIVE_VERIFICATION_20260605.md` · `PHASE_ATM_AUTOMATION_MODAL_E2E_TEST_20260605.md` | E2E guarded policy-write + AUTO_LIVE-on-paper verification (env stays paper) |

## Phase 204 — Portfolio Backup-Cadence Fix + Pilot (2026-06-05)
| Document | Purpose |
|----------|---------|
| `docs/project/PHASE204_PORTFOLIO_BACKUP_CADENCE_FIX_AND_PILOT_CLOSEOUT.md` | **Closeout** — secrets backup fixed (arg bug, not gog); backup cadence scheduled (daily 02:30, parallel, no retirement) |
| `docs/architecture/PHASE204A..I*.md` | secrets failure snapshot · env diff · safe repro · minimal fix · cadence-aware redesign · dry-runs · backup apply · output diff · schedule report |
| `scripts/pipelines/run_portfolio_maintenance_pipeline.sh` | cadence-aware (`--cadence backup\|daily\|weekly\|monthly\|lookthrough\|all`); backup=pg+secrets-env (daily), secrets-data→weekly; price_cache+db_retention excluded |
| `scripts/compare_portfolio_backup_outputs.py` | backup-cadence output diff (rejects dry-run summaries) |

## Phase 203 — v3 Empty Scanner Root-Cause + Fix (2026-06-05)
| Document | Purpose |
|----------|---------|
| `docs/project/PHASE203_V3_EMPTY_SCANNER_ROOT_CAUSE_CLOSEOUT.md` | **Closeout** — root cause = invalid-JSON (NaN) serialization, NOT migration |
| `docs/architecture/PHASE203A..I*.md` | symptom · runtime · schedule-diff · API source · feed · frontend mapping · root-cause · fix · validation |
| Fix: `portfolio_server.json_response` NaN/Inf→null (valid JSON, all endpoints) + `TradingHub` explicit error state |

## Phase 202 — Portfolio-Maintenance P0-Safe Migration Pilot (2026-06-05, HELD)
| Document | Purpose |
|----------|---------|
| `docs/architecture/PHASE202A..F*.md` | preflight · P0-safe selection · excluded · controller hardening · dry-run · parallel apply · output diff. **HELD at 202F:** cadence mismatch + reports generate advisory drafts via LLM → operator decision (A: backups-only / B: per-cadence redesign) before scheduling/retiring |

## Phase 201 — Governance Timer Retirement + Portfolio-Maintenance Preflight (2026-06-05)
| Document | Purpose |
|----------|---------|
| `docs/project/PHASE201_GOVERNANCE_TIMER_RETIREMENT_PORTFOLIO_PREFLIGHT_CLOSEOUT.md` | **Closeout + final checklist** |
| `docs/architecture/PHASE201A..E*.md` | auto-cycle observation · timer overlap inventory · retirement gate · 4 redundant timers retired (reversible) · post-retirement validation |
| `docs/architecture/PHASE201F..H*.md` | portfolio-maintenance preflight inventory · risk model · migration plan (design-only, 8 candidates) |
| `docs/architecture/PHASE201I_V3_CONTROL_TOWER_POST_GOVERNANCE_STATUS.md` | v3 control tower: retired timers 4/4, portfolio not-migrated, safety net untouched |

## Phase 200 — Governance Cron Migration Pilot (2026-06-04)
| Document | Purpose |
|----------|---------|
| `docs/project/PHASE200_GOVERNANCE_CRON_MIGRATION_CLOSEOUT.md` | **Closeout + final checklist** (governance-only) |
| `docs/architecture/PHASE200A..J*.md` | preflight · job selection · controller hardening · dry-run · parallel run · output diff · schedule · scheduled-cycle · cron retirement · v3 visibility |
| `scripts/pipelines/run_governance_pipeline.sh` | Hardened governance controller (real executor, DRY_RUN default) |
| `scripts/compare_governance_pipeline_outputs.py` | Legacy-vs-controller output diff |
| `~/.config/systemd/user/tradeai-governance-pipeline.{service,timer}` | Controller schedule (Mon-Fri 07:40 + Sun 18:00) |
| `/api/v2/system/governance-pipeline-status` | Read-only controller status for v3 Control Plane |

## Phase 199 — Runtime Control Plane Consolidation + v3 Governance (2026-06-04)
| Document | Purpose |
|----------|---------|
| `docs/project/PHASE199_RUNTIME_CONTROL_PLANE_V3_GOVERNANCE_CLOSEOUT.md` | **Closeout + final checklist** |
| `docs/architecture/PHASE199A..J*.md` | Preflight · inventory · ownership model · compression plan · controller skeletons · v3 QCT plan/API/impl · snapshot generator · validation |
| `scripts/inventory_runtime_jobs.py` | Runtime job inventory (211 cron/32 timers/30 svc/143 unique/31 dup) |
| `scripts/pipelines/` | 7 dry-run pipeline controllers + safety harness (no schedules wired) |
| `scripts/generate_state_of_repo_snapshot.py` | → `docs/project/STATE_OF_REPO_LATEST.md` |
| `docs/ATM_PROPOSAL_CONTROLS_2026_06_04.md` | Editable ATM + proposal controls (paper-only, gate-interlocked) |
| `docs/HERMES_POSITION_PROPOSAL_RESEARCH_2026_06_04.md` | Hermes 24/7 held-position + proposal research |

---

## Dashboard

| Version | URL | Status |
|---------|-----|--------|
| **v3 (canonical)** | `http://192.168.50.16:7777/v3/` | **Source of truth** — 11 hubs, 37/39 tabs live, all numbers from verified endpoints. Every displayed value traces to a real API field; placeholders are honest, never fabricated. |
| v2 (frozen) | `http://192.168.50.16:7777/v2/` | Legacy — frozen with banner. 63 pages, still accessible as fallback. Not maintained. |

---

## Active — Authoritative Documents

### Protocol & Architecture
| Document | Purpose |
|----------|---------|
| `docs/A1A.md` | **Documentation due-diligence protocol** — non-negotiable |
| `docs/MASTER_SYSTEM_DOCUMENTATION.md` | **Authoritative TECHNICAL reference (architects)** — 22 §, counts validated vs live DB/cron/config 2026-06-02 (426 tables+23 views, 184 crons, 26 strategies) |
| `docs/EXECUTIVE_ARCHITECTURE_OVERVIEW.md` | **High-level overview (app owners)** — non-technical capabilities/workflows/reference architecture (NEW 2026-06-02) |
| `docs/_archive/2026-06-02_doc_consolidation/ARCHITECTURE_OVERVIEW.md` | ARCHIVED + moved 2026-06-02 — superseded by MASTER + Executive overview |
| `docs/_archive/2026-06-02_doc_consolidation/SYSTEM_ARCHITECTURE_COMPLETE.md` | ARCHIVED + moved 2026-06-02 — consolidated into MASTER |
| `docs/project/MASTER_REWRITE_AND_ARCHIVE_REPORT_2026_05_31.md` | Master rewrite report — 50+ corrections, 2 docs archived |

### Operational Guides
| Document | Purpose |
|----------|---------|
| `docs/CHEAT_SHEET.md` | Operator quick reference |
| `docs/RESTORE_GUIDE.md` | Disaster recovery procedures |
| `docs/GPU_OLLAMA_SETUP.md` | Intel Arc B50 GPU setup for Ollama |
| `docs/COST_MODEL.md` | Cloud operating cost model |
| `docs/LLM_DATA_DICTIONARY.md` | LLM data dictionary — 6 context types, anti-hallucination spec |
| `docs/MONDAY_BURNIN_CHECKLIST.md` | Monday morning burn-in checklist |
| `docs/operator/ATM_RUNBOOK.md` | ATM operator runbook |
| `docs/OPERATOR_RUNBOOK_LLM_v4_1_FINAL.md` | LLM fleet operator runbook |

### Strategy & Agent
| Document | Purpose |
|----------|---------|
| `docs/project/SKILLS.md` | **Skills & capabilities reference** — agents, pipelines, LLM routing (updated 2026-05-31) |
| `docs/project/agents_bible.md` | Agent behavior rules (G1-G10) |
| `docs/project/project_openclaw.md` | OpenClaw gateway configuration |
| `docs/AGENT_ROSTER.md` | Agent roster |
| `docs/AGENT_PAGES_DETAIL.md` | Agent page details |
| `docs/COMMAND_CENTER_PAGE_MATRIX.md` | Command Center page matrix |
| `docs/DOCS_ROSTER.md` | Documentation roster |
| `docs/APPENDIX_E_SCRIPT_ROUTING_MATRIX.md` | Script routing matrix |

### LLM Fleet v4.1
| Document | Purpose |
|----------|---------|
| `docs/LLM_FLEET_STRATEGY_v4_1_FINAL.md` | LLM fleet architecture — phased rollout, model routing |
| `docs/llm_fleet/phase2_embedding_ab/` | Phase 2 embedding A/B — 25+ test reports, QWEN3_BETTER verdict |

### Execution Safety (Phase 6)
| Document | Purpose |
|----------|---------|
| `docs/execution_safety/phase6_market_revalidation/` | Phase 6A-C — market revalidation, session policy, audit trail (24+17+12 tests) |

### Governance & Maturity
| Document | Purpose |
|----------|---------|
| `docs/governance/` | GOV-1 A1A compliance + Phase 9C maturity board |
| `docs/maturity_hardening/` | Maturity reports and control board |

### Strategy Proof
| Document | Purpose |
|----------|---------|
| `docs/strategy_proof/` | SP-2, SP-2B, SP-2C — route audit, screener quality, watch horizon |

### Frontend
| Document | Purpose |
|----------|---------|
| `docs/frontend/` | PP-UX-1 (decision packet) + PP-UX-2 (trust audit) |
| `docs/COMMAND_CENTER_PAGE_MATRIX.md` | Page matrix — includes v3 Strategy → Backtest tab + Backtest Intelligence layer (2026-06-02) |

### Session 2026-06-02 — V3 Backtest Intelligence
| Document | Purpose |
|----------|---------|
| `docs/project/SESSION_2026_06_02_V3_BACKTEST_INTELLIGENCE.md` | **Session summary** — full v2 backtest port to v3, entry-quality grading (engine was unscheduled → now cron), edge decay, capture, append-only `backtest_result_history`, new `/api/v2/backtesting/result-history` endpoint, **AI Trade Eval** (engine MACD/Fib/ADX/BB/structure + structured gemma3:12b evaluator → `/api/v2/backtesting/trade-evaluations`) |

### Session 2026-05-29/30 — Classifier, Proposals, Hermes
| Document | Purpose |
|----------|---------|
| `docs/project/SESSION_2026_05_29_FINAL_SUMMARY.md` | **Session summary** — 40+21 commits, classifier 100%, proposals P0/P1, ATM audit, Hermes P0-P1D |
| `docs/project/MEMORY_NOTES_FOR_NEXT_SESSION_2026_05_29_FINAL.md` | Durable memory notes |
| `docs/project/NEXT_SESSION_RUNBOOK_2026_05_29_FINAL.md` | Runbook — preflight, visual check, remaining work |
| `docs/project/SYSTEM_HEALTH_AGENT_ARCHITECTURE.md` | System health agent architecture with Claude Code escalation |
| `docs/atm_lifecycle_v1_2026_05_29/` | Classifier completion, SHFS 860, proposal fixes, backtesting UI, ATM audit (46 files) |

### Hermes Sidecar (v4)
| Document | Purpose |
|----------|---------|
| `docs/hermes/Hermes_Sidecar_Strategy_for_Trade_AI_v4.md` | Strategic design — 6 pods, 24 agents, research desk |
| `docs/hermes/HERMES_COMPATIBILITY_AUDIT.md` | Compatibility audit — no blockers |
| `docs/hermes/HERMES_DATABASE_FIRST_INTEGRATION_ARCHITECTURE.md` | DB-first architecture — 6 hermes_* tables, roles, views |
| `docs/hermes/HERMES_PHASE_P0_FINAL_GATE.md` | P0 final gate — GO |
| `docs/hermes/HERMES_PHASE_P0_INSTALL_REPORT.md` | P0 install — v0.15.2 |
| `docs/hermes/HERMES_PHASE1_DB_STAGING_REPORT.md` | Phase 1 — 6 tables, 34 indexes |
| `docs/hermes/HERMES_PHASE1A_DB_ROLES_REPORT.md` | Phase 1A — roles, grants |
| `docs/hermes/HERMES_PHASE1B_RUNTIME_STAGING_WRITES_REPORT.md` | Phase 1B — staging ingestion |
| `docs/hermes/HERMES_PHASE1C_PRODUCTION_READ_ACCESS_MAP.md` | Phase 1C — 392 tables audited |
| `docs/hermes/HERMES_PHASE1C_SAFE_VIEW_DRAFTS.sql` | 8 safe view SQL ([Drive](https://drive.google.com/file/d/1BNdg-XOamE_reOkbrvURUfHTRF0DXTzy/view)) |
| `docs/hermes/HERMES_PHASE1C_READ_GRANT_DRAFTS.sql` | Read grant SQL ([Drive](https://drive.google.com/file/d/1AsFcrjgfBfIXYr-RlriRBWMYV_yl0QmJ/view)) |
| `docs/hermes/HERMES_PHASE1C_SECURITY_FINDINGS.md` | Security findings — 14 denied, 10 masked |
| `docs/hermes/HERMES_PHASE1D_VIEWS_AND_GRANTS_REPORT.md` | Phase 1D — 8 views, 40 grants APPLIED |
| `docs/hermes/HERMES_ROLLBACK_PLAN.md` | Rollback — `rm -rf hermes_sidecar/` |
| `docs/hermes/discovery/` | Gate 1 discovery artifacts |

### Hermes Phase 7 — Pipeline Quality Loop
| Document | Purpose |
|----------|---------|
| `docs/hermes/HERMES_PHASE7A_PIPELINE_QUALITY_DRY_RUN_REPORT.md` | Phase 7A dry-run — 3 findings |
| `docs/hermes/HERMES_PHASE7B_PIPELINE_QUALITY_STAGING_REPORT.md` | Phase 7B — 3 validation findings staged |
| `docs/hermes/HERMES_PHASE7C_PIPELINE_QUALITY_DASHBOARD_REPORT.md` | Phase 7C — dashboard section |
| `docs/hermes/HERMES_PHASE7D_PIPELINE_QUALITY_USEFULNESS_AUDIT.md` | Phase 7D — quality PASS |
| `docs/hermes/HERMES_PHASE7E_PIPELINE_QUALITY_LOOP_CLOSEOUT.md` | Phase 7E closeout |
| `docs/hermes/HERMES_PHASE7F_OLLAMA_MODEL_SAFETY_RECONCILIATION.md` | Phase 7F — model audit PASS |
| `docs/hermes/HERMES_PHASE7G_MODEL_RECONCILIATION_CLOSEOUT.md` | Phase 7G closeout |
| `docs/hermes/HERMES_PHASE8A_PORTFOLIO_REFLECTION_DRY_RUN_REPORT.md` | Phase 8A dry-run PASS |
| `docs/hermes/HERMES_PHASE8B_PORTFOLIO_REFLECTION_STAGING_REPORT.md` | Phase 8B — 3 reflections staged |
| `docs/hermes/HERMES_PHASE8C_PORTFOLIO_REFLECTION_DASHBOARD_REPORT.md` | Phase 8C — dashboard verified |
| `docs/hermes/HERMES_PHASE8D_PORTFOLIO_REFLECTION_USEFULNESS_AUDIT.md` | Phase 8D — quality PASS |
| `docs/hermes/HERMES_PHASE8E_PORTFOLIO_REFLECTION_LOOP_CLOSEOUT.md` | Phase 8E closeout |
| `docs/hermes/HERMES_PHASE9A_OBSERVATION_AND_STABILITY_AUDIT.md` | Phase 9A — stability PASS |
| `docs/hermes/HERMES_PHASE9D_OBSERVATION_AND_INFRA_PLANNING_CLOSEOUT.md` | **Phase 9D closeout** |
| `docs/infra/DOCKER_CONTAINERIZATION_ARCHITECTURE_AUDIT_2026_05_31.md` | Docker architecture — design only |
| `docs/infra/DOCKER_READINESS_CHECKLIST.md` | Docker readiness checklist |
| `docs/infra/DOCKER_ROLLBACK_RUNBOOK.md` | Docker rollback runbook |
| `docs/infra/DOCKER_PHASED_MIGRATION_PLAN.md` | 5-phase Docker migration plan |

### Session Closeout
| Document | Purpose |
|----------|---------|
| `docs/hermes/HERMES_FULL_SESSION_CLOSEOUT_2026_05_31.md` | **Full Hermes session closeout** — 101 commits, P0-P9, MASTER rewrite, Docker planning |
| `docs/project/SESSION_2026_05_31_HERMES_FULL_CLOSEOUT_SUMMARY.md` | Operator summary |
| `docs/hermes/HERMES_PHASE11A_OBSERVATION_HEALTH_CHECK.md` | Phase 11A — observation PASS |
| `docs/infra/DOCKER_PHASE11B_NONPROD_PREVIEW_PILOT_REPORT.md` | Phase 11B — Docker pilot PASS (static docs, cleaned up) |
| `docs/project/PHASE11_OBSERVATION_AND_DOCKER_PREVIEW_CLOSEOUT.md` | Phase 11 closeout |
| `docs/infra/DOCKER_PHASE12A_VERSION_CHECK_PILOT_DESIGN.md` | Phase 12A design |
| `docs/infra/DOCKER_PHASE12B_VERSION_CHECK_PILOT_RUN_REPORT.md` | Phase 12B — version-check PASS |
| `docs/infra/DOCKER_PHASE12C_VERSION_CHECK_SAFETY_AUDIT.md` | Phase 12C — safety PASS |
| `docs/project/PHASE12_DOCKER_VERSION_CHECK_CLOSEOUT.md` | Phase 12 closeout |
| `docs/hermes/HERMES_PHASE13B_PROMOTION_REVIEW_DRY_RUN_REPORT.md` | Phase 13B — review dry-run, 3 candidates |
| `docs/hermes/HERMES_PHASE13C_PROMOTION_REVIEW_USEFULNESS_AUDIT.md` | Phase 13C — quality PASS |
| `docs/project/PHASE13_PROMOTION_REVIEW_LOOP_CLOSEOUT.md` | Phase 13 closeout |
| `docs/hermes/HERMES_PHASE14B_PROMOTION_REVIEW_DASHBOARD_IMPLEMENTATION_REPORT.md` | Phase 14B — dashboard preview |
| `docs/hermes/HERMES_PHASE14C_PROMOTION_REVIEW_DASHBOARD_SAFETY_AUDIT.md` | Phase 14C — safety PASS |
| `docs/project/PHASE14_PROMOTION_REVIEW_DASHBOARD_CLOSEOUT.md` | **Phase 14 closeout** |
| `docs/hermes/HERMES_PHASE15_PROMOTION_EXECUTION_REPORT.md` | **Phase 15** — 3 candidates promoted (FJSCX, APAM, TRX) |

### SearXNG Shared Search Layer (Phase 16)
| Document | Purpose |
|----------|---------|
| `docs/infra/SEARXNG_SHARED_LAYER_ARCHITECTURE.md` | Architecture — internal-only, port plan, future gates |
| `docs/infra/SEARXNG_PHASE16_INSTALL_REPORT.md` | Phase 16B — Docker Compose standup, 127.0.0.1:18888 |
| `docs/infra/SEARXNG_PHASE16_SAFETY_AUDIT.md` | Phase 16C — safety PASS |
| `docs/infra/SEARXNG_PHASE16_COMMAND_CENTER_VISIBILITY_REPORT.md` | Phase 16D — read-only System Applications visibility |
| `docs/infra/SEARXNG_OPERATOR_RUNBOOK.md` | Operator runbook — status, logs, restart, rollback, privacy |
| `docs/project/PHASE16_SEARXNG_SHARED_LAYER_CLOSEOUT.md` | **Phase 16 closeout** |

### SearXNG Manual Query Wrapper (Phase 17)
| Document | Purpose |
|----------|---------|
| `docs/infra/SEARXNG_PHASE17A_MANUAL_WRAPPER_ARCHITECTURE.md` | Phase 17A — wrapper design |
| `docs/infra/SEARXNG_PHASE17B_MANUAL_WRAPPER_IMPLEMENTATION_REPORT.md` | Phase 17B — implementation + test |
| `docs/infra/SEARXNG_PHASE17C_MANUAL_WRAPPER_SAFETY_AUDIT.md` | Phase 17C — safety PASS |
| `docs/infra/SEARXNG_PHASE17D_COMMAND_CENTER_QUERY_VISIBILITY_DESIGN.md` | Phase 17D — CC visibility design (docs only) |
| `docs/project/PHASE17_SEARXNG_MANUAL_WRAPPER_CLOSEOUT.md` | **Phase 17 closeout** |

### SearXNG Source Discovery Dry-Run (Phase 18)
| Document | Purpose |
|----------|---------|
| `docs/infra/SEARXNG_PHASE18A_SOURCE_DISCOVERY_DRY_RUN_ARCHITECTURE.md` | Phase 18A — discovery architecture |
| `docs/infra/SEARXNG_PHASE18B_SOURCE_DISCOVERY_DRY_RUN_REPORT.md` | Phase 18B — 5 queries, 10 candidates |
| `docs/infra/SEARXNG_PHASE18C_SOURCE_DISCOVERY_QUALITY_AUDIT.md` | Phase 18C — quality PASS (4.5/5) |
| `docs/infra/SEARXNG_PHASE18D_FUTURE_INGESTION_MAPPING_DESIGN.md` | Phase 18D — ingestion mapping design |
| `docs/infra/searxng_phase18_source_discovery_dryrun/` | Dry-run output files |
| `docs/project/PHASE18_SEARXNG_SOURCE_DISCOVERY_DRY_RUN_CLOSEOUT.md` | **Phase 18 closeout** |

### SearXNG Staged Source Ingestion (Phase 19)
| Document | Purpose |
|----------|---------|
| `docs/infra/SEARXNG_PHASE19A_STAGED_INGESTION_REVALIDATION.md` | Phase 19A — 5 candidates validated |
| `docs/infra/SEARXNG_PHASE19B_STAGED_INGESTION_REPORT.md` | Phase 19B — 5 rows staged (ids 12–16) |
| `docs/infra/SEARXNG_PHASE19B_STAGED_INGESTION_ROLLBACK.sql` | Phase 19B rollback SQL |
| `docs/infra/SEARXNG_PHASE19C_STAGED_INGESTION_SAFETY_AUDIT.md` | Phase 19C — safety PASS |
| `docs/infra/SEARXNG_PHASE19D_STAGED_SOURCE_VISIBILITY_DESIGN.md` | Phase 19D — visibility design (docs only) |
| `docs/project/PHASE19_SEARXNG_STAGED_SOURCE_INGESTION_CLOSEOUT.md` | **Phase 19 closeout** |

### Hermes Agent Model and Actionability (Phase 20)
| Document | Purpose |
|----------|---------|
| `docs/hermes/HERMES_AGENT_OPERATING_MODEL.md` | Agent operating model — 7 agents, source-of-truth hierarchy |
| `docs/hermes/HERMES_AGENT_CONTRACTS_AND_PERMISSIONS.md` | Agent contracts — mission, reads, writes, forbidden, caps |
| `docs/hermes/HERMES_ADVISORY_ACTIONABILITY_STANDARD.md` | Advisory actionability — 16 fields, 11 failure classes |
| `docs/hermes/HERMES_TELEGRAM_AND_COMMUNICATION_RETENTION_AUDIT.md` | Retention audit — payloads not stored |
| `docs/hermes/HERMES_TELEGRAM_REVIEW_ACTIONABILITY_GATE.md` | Actionability gate for weekly reviews |
| `docs/hermes/HERMES_TELEGRAM_REVIEW_ACTIONABILITY_DRY_RUN.md` | Dry-run: vague_rebalance_recommendation HIGH |
| `docs/project/PHASE20_HERMES_AGENT_MODEL_AND_ACTIONABILITY_CLOSEOUT.md` | **Phase 20 closeout** |

### Hermes Librarian Dry-Run (Phase 21)
| Document | Purpose |
|----------|---------|
| `docs/hermes/HERMES_PHASE21A_LIBRARIAN_DRY_RUN_DESIGN.md` | Phase 21A — 17 check types |
| `docs/hermes/HERMES_PHASE21B_LIBRARIAN_STAGED_SOURCE_DRY_RUN_REPORT.md` | Phase 21B — 18 rows, 6 findings |
| `docs/hermes/HERMES_PHASE21C_COMMUNICATION_ACTIONABILITY_DRY_RUN_REPORT.md` | Phase 21C — Telegram FAIL |
| `docs/hermes/HERMES_PHASE21D_LIBRARIAN_USEFULNESS_AND_SAFETY_AUDIT.md` | Phase 21D — PASS (4.6/5) |
| `docs/hermes/phase21_librarian_dryrun/` | Librarian dry-run output files |
| `docs/hermes/phase21_communication_actionability_dryrun/` | Communication actionability output |
| `docs/project/PHASE21_HERMES_LIBRARIAN_DRY_RUN_CLOSEOUT.md` | **Phase 21 closeout** |

### Research Backlog Staged-Write Pilot (Phase 22)
| Document | Purpose |
|----------|---------|
| `docs/hermes/HERMES_PHASE22A_RESEARCH_BACKLOG_TARGET_REVALIDATION.md` | Phase 22A — target validated |
| `docs/hermes/HERMES_PHASE22B_RESEARCH_BACKLOG_STAGED_WRITE_REPORT.md` | Phase 22B — 5 rows staged (ids 19–23) |
| `docs/hermes/HERMES_PHASE22B_RESEARCH_BACKLOG_STAGED_WRITE_ROLLBACK.sql` | Phase 22B rollback SQL |
| `docs/hermes/HERMES_PHASE22C_RESEARCH_BACKLOG_SAFETY_AUDIT.md` | Phase 22C — safety PASS |
| `docs/hermes/HERMES_PHASE22D_RESEARCH_BACKLOG_DASHBOARD_DESIGN.md` | Phase 22D — dashboard design (docs only) |
| `docs/project/PHASE22_RESEARCH_BACKLOG_STAGED_WRITE_CLOSEOUT.md` | **Phase 22 closeout** |

### Income-Rotation Research Discovery (Phase 23)
| Document | Purpose |
|----------|---------|
| `docs/hermes/HERMES_PHASE23A_INCOME_ROTATION_RESEARCH_PLAN.md` | Phase 23A — 9 sleeves, evidence requirements |
| `docs/hermes/HERMES_PHASE23B_INCOME_ROTATION_DISCOVERY_REPORT.md` | Phase 23B — 8 queries, 55 candidates |
| `docs/hermes/HERMES_PHASE23C_INCOME_ROTATION_CANDIDATE_SCORING.md` | Phase 23C — 7 sleeves scored |
| `docs/hermes/HERMES_PHASE23D_INCOME_ROTATION_ACTIONABILITY_AUDIT.md` | Phase 23D — actionability 0.15→0.78 |
| `docs/hermes/phase23_income_rotation_discovery/` | Discovery output files |
| `docs/project/PHASE23_INCOME_ROTATION_RESEARCH_CLOSEOUT.md` | **Phase 23 closeout** |

### Research Backlog Dashboard (Phase 24)
| Document | Purpose |
|----------|---------|
| `docs/hermes/HERMES_PHASE24A_RESEARCH_BACKLOG_DASHBOARD_IMPLEMENTATION_PLAN.md` | Phase 24A — plan |
| `docs/hermes/HERMES_PHASE24B_RESEARCH_BACKLOG_DASHBOARD_IMPLEMENTATION_REPORT.md` | Phase 24B — GET endpoint + UI |
| `docs/hermes/HERMES_PHASE24C_RESEARCH_BACKLOG_DASHBOARD_SAFETY_AUDIT.md` | Phase 24C — safety PASS |
| `docs/project/PHASE24_RESEARCH_BACKLOG_DASHBOARD_CLOSEOUT.md` | **Phase 24 closeout** |

### Embedding Curator Dry-Run (Phase 25)
| Document | Purpose |
|----------|---------|
| `docs/hermes/HERMES_PHASE25A_EMBEDDING_CURATOR_DRY_RUN_DESIGN.md` | Phase 25A — 11 dimensions, rejection criteria |
| `docs/hermes/HERMES_PHASE25B_EMBEDDING_CURATOR_DRY_RUN_REPORT.md` | Phase 25B — 10 scored, 2 pilot recs |
| `docs/hermes/HERMES_PHASE25C_EMBEDDING_CURATOR_SAFETY_AUDIT.md` | Phase 25C — safety PASS |
| `docs/hermes/phase25_embedding_curator_dryrun/` | Curator output files |
| `docs/project/PHASE25_EMBEDDING_CURATOR_DRY_RUN_CLOSEOUT.md` | **Phase 25 closeout** |

### Hermes Trade AI Coverage Audit (Phase 28)
| Document | Purpose |
|----------|---------|
| `docs/hermes/HERMES_PHASE28A_TRADEAI_DATA_SURFACE_INVENTORY.md` | Phase 28A — 10 surfaces mapped |
| `docs/hermes/HERMES_PHASE28B_HERMES_COVERAGE_GAP_AUDIT.md` | Phase 28B — 6 NOT COVERED, 4 views needed |
| `docs/hermes/HERMES_PHASE28C_MOMENTUM_SCOUT_AND_CATALYST_AUDIT.md` | Phase 28C — catalyst pipeline mapped |
| `docs/hermes/HERMES_PHASE28D_JOURNAL_BACKTESTING_LIBRARIAN_DESIGN.md` | Phase 28D — 16 Librarian checks |
| `docs/hermes/HERMES_PHASE28E_TRADEAI_TO_HERMES_BACKLOG_INTEGRATION_PLAN.md` | Phase 28E — 13 backlog item types |
| `docs/project/PHASE28_HERMES_TRADEAI_COVERAGE_AUDIT_CLOSEOUT.md` | **Phase 28 closeout** |

### Hermes Safe View Coverage (Phase 29)
| Document | Purpose |
|----------|---------|
| `docs/hermes/HERMES_PHASE29A_SAFE_VIEW_SQL_DESIGN.md` | Phase 29A — 4 views designed |
| `docs/hermes/HERMES_PHASE29B_SAFE_VIEW_APPLY_REPORT.md` | Phase 29B — 4 views + grants applied |
| `docs/hermes/HERMES_PHASE29C_SAFE_VIEW_SECURITY_AUDIT.md` | Phase 29C — security PASS |
| `docs/hermes/HERMES_PHASE29D_COVERAGE_RECHECK.md` | Phase 29D — coverage 4/10 → 9/10 |
| `docs/hermes/HERMES_PHASE29E_MORNING_BRIEF_STORAGE_DESIGN.md` | Phase 29E — morning brief storage design |
| `sql/migrations/20260601_hermes_phase29_safe_views.sql` | Migration SQL |
| `sql/migrations/20260601_hermes_phase29_safe_views_rollback.sql` | Rollback SQL |
| `docs/project/PHASE29_HERMES_SAFE_VIEW_COVERAGE_CLOSEOUT.md` | **Phase 29 closeout** |

### Expanded Librarian Dry-Run (Phase 30)
| Document | Purpose |
|----------|---------|
| `docs/hermes/HERMES_PHASE30A_EXPANDED_LIBRARIAN_DRY_RUN_DESIGN.md` | Phase 30A — 14 checks |
| `docs/hermes/HERMES_PHASE30B_EXPANDED_LIBRARIAN_DRY_RUN_REPORT.md` | Phase 30B — 21 findings |
| `docs/hermes/HERMES_PHASE30C_EXPANDED_LIBRARIAN_SAFETY_AUDIT.md` | Phase 30C — PASS (4.25/5) |
| `docs/hermes/HERMES_PHASE30D_EXPANDED_BACKLOG_STAGED_WRITE_MAPPING.md` | Phase 30D — staging mapping |
| `docs/hermes/phase30_expanded_librarian_dryrun/` | Dry-run output files |
| `docs/project/PHASE30_EXPANDED_LIBRARIAN_DRY_RUN_CLOSEOUT.md` | **Phase 30 closeout** |

### Expanded Backlog Staging (Phase 32)
| Document | Purpose |
|----------|---------|
| `docs/hermes/HERMES_PHASE32A_EXPANDED_BACKLOG_REVALIDATION.md` | Phase 32A — 5 candidates validated |
| `docs/hermes/HERMES_PHASE32B_EXPANDED_BACKLOG_STAGING_REPORT.md` | Phase 32B — 5 rows staged (ids 24–28) |
| `docs/hermes/HERMES_PHASE32B_EXPANDED_BACKLOG_STAGING_ROLLBACK.sql` | Phase 32B rollback SQL |
| `docs/hermes/HERMES_PHASE32C_EXPANDED_BACKLOG_SAFETY_AUDIT.md` | Phase 32C — safety PASS |
| `docs/hermes/HERMES_PHASE32D_BACKLOG_DASHBOARD_REFRESH_VERIFICATION.md` | Phase 32D — dashboard 10 items verified |
| `docs/project/PHASE32_EXPANDED_BACKLOG_STAGING_CLOSEOUT.md` | **Phase 32 closeout** |

### Hermes Embedding Pilot (Phase 31)
| Document | Purpose |
|----------|---------|
| `docs/hermes/HERMES_PHASE31A_EMBEDDING_PILOT_PREFLIGHT.md` | Phase 31A — preflight |
| `docs/hermes/HERMES_PHASE31B_EMBEDDING_PILOT_EXECUTION_REPORT.md` | Phase 31B — 2 embeddings created |
| `docs/hermes/HERMES_PHASE31C_EMBEDDING_RETRIEVAL_AUDIT.md` | Phase 31C — retrieval PASS |
| `docs/hermes/HERMES_PHASE31D_EMBEDDING_VISIBILITY_VERIFICATION.md` | Phase 31D — dashboard verified |
| `docs/hermes/HERMES_PHASE31_EMBEDDING_PILOT_ROLLBACK.sql` | Rollback SQL |
| `docs/project/PHASE31_HERMES_EMBEDDING_PILOT_CLOSEOUT.md` | **Phase 31 closeout** |

### Hermes Automation Model (Phase 33)
| Document | Purpose |
|----------|---------|
| `docs/hermes/HERMES_PHASE33A_AUTOMATION_INVENTORY.md` | Phase 33A — 18 timers, 187 cron, 1 Docker |
| `docs/hermes/HERMES_PHASE33B_SCHEDULER_POLICY.md` | Phase 33B — systemd for Hermes, Docker for infra |
| `docs/hermes/HERMES_PHASE33C_SELF_LEARNING_BOUNDARY_MODEL.md` | Phase 33C — Level 3, 7 maturity levels |
| `docs/hermes/HERMES_PHASE33D_AUTOMATION_GAP_AND_CONVERSION_PLAN.md` | Phase 33D — 7 candidate automations |
| `docs/hermes/HERMES_PHASE33E_AUTOMATION_ROLLOUT_GATES.md` | Phase 33E — Phases 34–40 rollout |
| `docs/project/PHASE33_HERMES_AUTOMATION_MODEL_CLOSEOUT.md` | **Phase 33 closeout** |

### Observation Automation (Phase 34)
| Document | Purpose |
|----------|---------|
| `docs/hermes/HERMES_PHASE34A_OBSERVATION_AUTOMATION_DESIGN.md` | Phase 34A — 12 checks design |
| `docs/hermes/HERMES_PHASE34B_OBSERVATION_SCRIPT_REPORT.md` | Phase 34B — 12/12 PASS |
| `docs/hermes/HERMES_PHASE34C_OBSERVATION_TIMER_ENABLE_REPORT.md` | Phase 34C — timer enabled |
| `docs/hermes/HERMES_PHASE34D_OBSERVATION_AUTOMATION_SAFETY_AUDIT.md` | Phase 34D — safety PASS |
| `docs/hermes/HERMES_PHASE34E_OBSERVATION_DASHBOARD_VISIBILITY_DESIGN.md` | Phase 34E — dashboard design |
| `docs/project/PHASE34_OBSERVATION_AUTOMATION_CLOSEOUT.md` | **Phase 34 closeout** |

### Backlog Health Automation (Phase 35)
| Document | Purpose |
|----------|---------|
| `docs/hermes/HERMES_PHASE35A_BACKLOG_HEALTH_CHECK_DESIGN.md` | Phase 35A — 13 checks design |
| `docs/hermes/HERMES_PHASE35B_BACKLOG_HEALTH_SCRIPT_REPORT.md` | Phase 35B — manual run report |
| `docs/hermes/HERMES_PHASE35C_BACKLOG_HEALTH_TIMER_ENABLE_REPORT.md` | Phase 35C — timer enabled |
| `docs/hermes/HERMES_PHASE35D_BACKLOG_HEALTH_SAFETY_AUDIT.md` | Phase 35D — safety PASS |
| `docs/hermes/HERMES_PHASE35E_BACKLOG_HEALTH_DASHBOARD_VISIBILITY_DESIGN.md` | Phase 35E — dashboard design |
| `docs/project/PHASE35_BACKLOG_HEALTH_AUTOMATION_CLOSEOUT.md` | **Phase 35 closeout** |

### Scheduled Job Consolidation (Phase 36)
| Document | Purpose |
|----------|---------|
| `docs/operations/PHASE36A_CRON_RISK_AND_GROUPING_AUDIT.md` | Phase 36A — 187 jobs grouped |
| `docs/operations/PHASE36B_SCHEDULE_DUPLICATE_OVERLAP_AUDIT.md` | Phase 36B — 11+ duplicates |
| `docs/operations/PHASE36C_SCHEDULED_JOB_CONSOLIDATION_DESIGN.md` | Phase 36C — 5 categories |
| `docs/operations/PHASE36D_LOW_LATENCY_SCHEDULER_RECOMMENDATION.md` | Phase 36D — latency classification |
| `docs/operations/PHASE36E_SCHEDULED_JOB_MIGRATION_PLAN.md` | Phase 36E — Phases 41–46 plan |
| `docs/project/PHASE36_SCHEDULED_JOB_CONSOLIDATION_AUDIT_CLOSEOUT.md` | **Phase 36 closeout** |

### Low-Latency Hermes Bridge (Phase 37)
| Document | Purpose |
|----------|---------|
| `docs/hermes/HERMES_PHASE37A_CURRENT_CONTEXT_PATH_MAP.md` | Phase 37A — context paths mapped |
| `docs/hermes/HERMES_PHASE37B_LOW_LATENCY_BRIDGE_OPTIONS.md` | Phase 37B — 6 options compared |
| `docs/hermes/HERMES_PHASE37C_RECOMMENDED_LOW_LATENCY_ARCHITECTURE.md` | Phase 37C — queue table + LISTEN/NOTIFY |
| `docs/hermes/HERMES_PHASE37D_LOW_LATENCY_SAFETY_AND_SLA.md` | Phase 37D — <60s SLA |
| `docs/hermes/HERMES_PHASE37E_LOW_LATENCY_IMPLEMENTATION_GATES.md` | Phase 37E — Phases 44–46 |
| `docs/project/PHASE37_LOW_LATENCY_HERMES_BRIDGE_DESIGN_CLOSEOUT.md` | **Phase 37 closeout** |

### Systemd Migration Wave 1 (Phase 41)
| Document | Purpose |
|----------|---------|
| `docs/operations/PHASE41A_SYSTEMD_MIGRATION_CANDIDATE_SELECTION.md` | 5 candidates selected |
| `docs/project/PHASE41_SYSTEMD_MIGRATION_WAVE1_CLOSEOUT.md` | **Phase 41 closeout** — 11 cron→5 timers |

### Market Scan Consolidation Design (Phase 42)
| Document | Purpose |
|----------|---------|
| `docs/operations/PHASE42A_MARKET_SCAN_DUPLICATE_SELECTION.md` | 13 duplicates identified |
| `docs/operations/PHASE42B_MARKET_SCAN_PIPELINE_DESIGN.md` | Pipeline design (13→1) |
| `docs/project/PHASE42_MARKET_SCAN_CONSOLIDATION_DESIGN_CLOSEOUT.md` | **Phase 42 closeout** — design only |

### Scheduled Job Health Dashboard (Phase 46)
| Document | Purpose |
|----------|---------|
| `docs/operations/PHASE46A_SCHEDULED_JOB_HEALTH_DASHBOARD_DESIGN.md` | Dashboard design |
| `docs/operations/PHASE46D_SCHEDULED_JOB_HEALTH_SAFETY_AUDIT.md` | Safety PASS |
| `docs/project/PHASE46_SCHEDULED_JOB_HEALTH_DASHBOARD_CLOSEOUT.md` | **Phase 46 closeout** |

### Event Queue Pilot (Phase 44)
| `docs/project/PHASE44_HERMES_EVENT_QUEUE_PILOT_CLOSEOUT.md` | **Phase 44 closeout** — queue table + 60ms latency |

### Backlog Source Discovery (Phase 38)
| `docs/project/PHASE38_BACKLOG_SOURCE_DISCOVERY_CLOSEOUT.md` | **Phase 38 closeout** — 6 queries, 40 candidates |

### Scheduled Source Discovery Dry-Run (Phase 47)
| `docs/project/PHASE47_SCHEDULED_SOURCE_DISCOVERY_DRYRUN_CLOSEOUT.md` | **Phase 47 closeout** — daily 07:15 UTC timer |

### Scheduled Source Discovery Staged Write (Phase 48)
| `docs/project/PHASE48_SCHEDULED_SOURCE_DISCOVERY_STAGED_WRITE_CLOSEOUT.md` | **Phase 48 closeout** — 3 rows staged |

### Autonomous Librarian/Backlog Loop (Phase 49)
| `docs/project/PHASE49_AUTONOMOUS_LIBRARIAN_BACKLOG_LOOP_CLOSEOUT.md` | **Phase 49 closeout** — daily 07:45 UTC, Level 5 |

### Level 5 Governance (Phase 50)
| `docs/project/PHASE50_LEVEL5_GOVERNANCE_OBSERVATION_CLOSEOUT.md` | **Phase 50 closeout** — READY_FOR_PHASE51 |

### Advisory Cache Worker (Phase 51)
| `docs/project/PHASE51_HERMES_ADVISORY_CACHE_WORKER_CLOSEOUT.md` | **Phase 51 closeout** — hourly worker, Level 6 infra |

### Embedding/Promotion Review (Phase 52)
| `docs/project/PHASE52_EMBEDDING_PROMOTION_REVIEW_AUTOMATION_CLOSEOUT.md` | **Phase 52 closeout** — daily reviewer |

### High-LLM Priority Scheduler (Phase 53)
| `docs/llm/PHASE53A_HIGH_MODEL_USAGE_AUDIT.md` | Audit — 7+ scripts, monopoly risk |
| `docs/llm/PHASE53B_HIGH_LLM_PRIORITY_METHODOLOGY.md` | Priority formula + 5-pool quota |
| `docs/llm/PHASE53C_HIGH_LLM_QUEUE_SCHEMA_DESIGN.md` | Queue schema (not created) |
| `docs/llm/PHASE53E_HIGH_LLM_INTEGRATION_PLAN.md` | Phases 54–60 plan |
| `docs/project/PHASE53_HIGH_LLM_PRIORITY_SCHEDULER_CLOSEOUT.md` | **Phase 53 closeout** |

### High-LLM Queue Implementation (Phases 54–60)
| `docs/project/PHASE54_HIGH_LLM_QUEUE_TABLE_CLOSEOUT.md` | **Phase 54** — queue tables, 7 seed jobs |
| `docs/project/PHASE55_HERMES_HIGH_LLM_ROUTING_CLOSEOUT.md` | **Phase 55** — 5 Hermes jobs routed |
| `docs/project/PHASE56_JOURNAL_BACKTEST_HIGH_LLM_ROUTING_CLOSEOUT.md` | **Phase 56** — 5 journal/backtest jobs |
| `docs/project/PHASE57_DEEP_OVERNIGHT_HIGH_LLM_ROUTING_CLOSEOUT.md` | **Phase 57** — 5 overnight jobs, 19/22 scheduled |
| `docs/project/PHASE58_OLD_OVERNIGHT_MONOPOLY_RETIREMENT_CLOSEOUT.md` | **Phase 58** — design only, not applied |
| `docs/project/PHASE59_HIGH_LLM_QUEUE_DASHBOARD_CLOSEOUT.md` | **Phase 59** — GET /api/v2/llm/high-queue |
| `docs/project/PHASE60_GOVERNED_HIGH_LLM_EXECUTION_CLOSEOUT.md` | **Phase 60** — PASS_WITH_LIMITS, infra verified |

### Ollama Remediation + Gemma 4 + Retry + Timer + Stabilization (Phases 61–66)
| `docs/project/PHASE61_OLLAMA_CONTENTION_REMEDIATION_CLOSEOUT.md` | **Phase 61** — lock guard, warm, num_ctx=4096 |
| `docs/project/PHASE62_GEMMA4_CANARY_CLOSEOUT.md` | **Phase 62** — NOT_AVAILABLE |
| `docs/project/PHASE63_HIGH_LLM_EXECUTION_RETRY_CLOSEOUT.md` | **Phase 63** — 1/3 completed, 2/3 timeout |
| `docs/project/PHASE64_HIGH_LLM_WORKER_TIMER_CLOSEOUT.md` | **Phase 64** — daily 14:00 ET timer |
| `docs/project/PHASE65_OVERNIGHT_PARALLEL_COMPARISON_CLOSEOUT.md` | **Phase 65** — READY_WITH_LIMITS |
| `docs/project/PHASE66_LEVEL6_STABILIZATION_CLOSEOUT.md` | **Phase 66** — Level 6 STABLE |

### Incident Remediation + Certification + Feed Resilience (Phases 67–71)
| `docs/project/PHASE67_FINVIZ_STALENESS_INCIDENT_CLOSEOUT.md` | **Phase 67** — Finviz expired, true-fix gate |
| `docs/project/PHASE68_ALERT_DEDUPE_BACKLOG_INTEGRATION_CLOSEOUT.md` | **Phase 68** — 10-type taxonomy, ~80% dedupe |
| `docs/project/PHASE69_LEVEL6_MATURITY_CERTIFICATION_CLOSEOUT.md` | **Phase 69** — CERTIFIED_WITH_LIMITS |
| `docs/project/PHASE70_ALERT_TO_HERMES_BACKLOG_APPLY_CLOSEOUT.md` | **Phase 70** — 3 ops_backlog rows |
| `docs/project/PHASE71_FEED_RESILIENCE_AUTOMATION_CLOSEOUT.md` | **Phase 71** — feed health design |

### Recovery, Dedupe, Feed Dashboard (Phases 72–74)
| `docs/project/PHASE72_FINVIZ_RECOVERY_CERTIFICATION_CLOSEOUT.md` | **Phase 72** — 2/3 clean, pending upgrade |
| `docs/project/PHASE73_ALERT_DEDUPE_APPLY_CLOSEOUT.md` | **Phase 73** — dedupe + false-fixed gate |
| `docs/project/PHASE74_FEED_HEALTH_DASHBOARD_CLOSEOUT.md` | **Phase 74** — GET /api/v2/system/feed-health |

### Certification + Preflight + Self-Learning Maturity (Phases 75–77)
| `docs/project/PHASE75_LEVEL6_CERTIFICATION_UPGRADE_CLOSEOUT.md` | **Phase 75** — LEVEL6_CERTIFIED (conditional) |
| `docs/project/PHASE76_FINVIZ_PREFLIGHT_AUTOMATION_CLOSEOUT.md` | **Phase 76** — preflight script |
| `docs/project/PHASE77_FEED_FALLBACK_SELF_LEARNING_MATURITY_CLOSEOUT.md` | **Phase 77** — maturity 8.1/10 |
| `docs/project/PHASE77D_SELF_LEARNING_MATURITY_ASSESSMENT.md` | Self-learning maturity assessment |
| `docs/project/PHASE77E_NEXT_AUTOMATION_ROADMAP.md` | Phases 78–86 roadmap |

### Level 6 Stable Expansion (Phases 78–82)
| `docs/project/PHASE78_LEVEL6_CLEAN_OBSERVATION_CLOSEOUT.md` | **Phase 78** — LEVEL6_CERTIFIED_STABLE |
| `docs/project/PHASE79_EXPANDED_SOURCE_DISCOVERY_STAGED_WRITES_CLOSEOUT.md` | **Phase 79** — 5 rows staged (ids 38–42) |
| `docs/project/PHASE80_ADVISORY_CACHE_QUALITY_SCORING_CLOSEOUT.md` | **Phase 80** — 3 KEEP, 6 REFRESH, 1 RETIRE |
| `docs/project/PHASE81_HIGH_LLM_QUEUE_STABILIZATION_CLOSEOUT.md` | **Phase 81** — queue STABLE |
| `docs/project/PHASE82_SECOND_HERMES_EMBEDDING_BATCH_CLOSEOUT.md` | **Phase 82** — 3 embedded, total 12 |

### Promotion Review + Dashboard + Recertification + Governance (Phases 83–87)
| `docs/project/PHASE83_PROMOTION_REVIEW_RECOMMENDATION_CLOSEOUT.md` | **Phase 83** — 5 lanes, 16 candidates |
| `docs/project/PHASE84_SELF_LEARNING_OVERVIEW_DASHBOARD_CLOSEOUT.md` | **Phase 84** — /v2/self-learning-overview |
| `docs/project/PHASE85_LEVEL6_RECERTIFICATION_CLOSEOUT.md` | **Phase 85** — LEVEL6_RECERTIFIED |
| `docs/project/PHASE86_LEVEL7_GOVERNANCE_BOUNDARY_CLOSEOUT.md` | **Phase 86** — Level 7 PROHIBITED |
| `docs/project/PHASE87_CAPPED_ADVISORY_PROMOTION_PILOT_CLOSEOUT.md` | **Phase 87** — 2 promoted (ADBE, AGMH) |

### Auto-Promotion Policy + Pilot (Phases 88–90)
| `docs/project/PHASE88_AUTO_PROMOTION_POLICY_SHADOW_CLOSEOUT.md` | **Phase 88** — policy + shadow (3 eligible) |
| `docs/project/PHASE89_AUTO_PROMOTION_DRYRUN_VETO_CLOSEOUT.md` | **Phase 89** — veto queue (3 candidates) |
| `docs/project/PHASE90_TINY_AUTO_PROMOTION_PILOT_CLOSEOUT.md` | **Phase 90** — first auto-promotion (TRX id=16) |

### Dashboard Drill-Through (Phases 91–93)
| `docs/project/PHASE91_SELF_LEARNING_DRILLTHROUGH_ARCHITECTURE_CLOSEOUT.md` | **Phase 91** — 10 drill-throughs designed |
| `docs/project/PHASE92_SELF_LEARNING_DRILLTHROUGH_API_CLOSEOUT.md` | **Phase 92** — drilldown + timeline APIs |
| `docs/project/PHASE93_SELF_LEARNING_VISUAL_DRILLTHROUGH_UI_CLOSEOUT.md` | **Phase 93** — clickable cards, drawer, timeline |

### Auto-Promotion Monitoring + Shadow + UX Review (Phases 94–96)
| `docs/project/PHASE94_FIRST_AUTO_PROMOTION_MONITORING_CLOSEOUT.md` | **Phase 94** — STABLE_KEEP |
| `docs/project/PHASE95_EXPANDED_AUTO_PROMOTION_SHADOW_VETO_CLOSEOUT.md` | **Phase 95** — 2 eligible, 0 applied |
| `docs/project/PHASE96_DASHBOARD_OPERATOR_UX_REVIEW_CLOSEOUT.md` | **Phase 96** — UX 6.5/10, P0/P1 backlog |

### Visual Upgrade + Auto-Promotion + Milestone (Phases 97–100)
| `docs/project/PHASE97_SELF_LEARNING_P0_VISUAL_UPGRADE_CLOSEOUT.md` | **Phase 97** — UX 6.5→8.0 |
| `docs/project/PHASE98_SELF_LEARNING_FLOW_TIMELINE_CHARTS_CLOSEOUT.md` | **Phase 98** — flow, aging, timeline |
| `docs/project/PHASE99_SECOND_AUTO_PROMOTION_OR_HOLD_CLOSEOUT.md` | **Phase 99** — SCHD auto-promoted |
| `docs/project/PHASE100_SYSTEM_MILESTONE_AUDIT_CLOSEOUT.md` | **Phase 100** — LEVEL6_PRODUCTION_GRADE_WITH_LIMITS |

### Production Hardening (Phases 101–106)
| `docs/project/PHASE101_PRODUCTION_OBSERVATION_CLOSEOUT.md` | **Phase 101** — observation PASS |
| `docs/project/PHASE102_OLD_OVERNIGHT_RETIREMENT_CLOSEOUT.md` | **Phase 102** — 4 old cron retired |
| `docs/project/PHASE103_BROADER_AUTO_PROMOTION_MAX3_CLOSEOUT.md` | **Phase 103** — 3rd auto-promotion |
| `docs/project/PHASE104_RECHARTS_INTEGRATION_CLOSEOUT.md` | **Phase 104** — Recharts live |
| `docs/project/PHASE105_PROMOTION_ACTION_CONTROLS_DESIGN_CLOSEOUT.md` | **Phase 105** — action controls design |
| `docs/project/PHASE106_LEVEL7_SANDBOX_DISCUSSION_CLOSEOUT.md` | **Phase 106** — Level 7 PROHIBITED |

### Dashboard Operator Workflow Redesign (Phases 107–108)
| `docs/project/PHASE107_SELF_LEARNING_RUNTIME_INTERACTIVITY_FIX_CLOSEOUT.md` | **Phase 107+108** — attention-first, Kanban, card grid, drawer, UX 8.8 |

### Dashboard Runtime Defect Fix (Phase 109)
| `docs/project/PHASE109_DASHBOARD_RUNTIME_DEFECT_FIX_CLOSEOUT.md` | **Phase 109** — URL state, breadcrumbs, click affordance |

### Authority + SYS Actionability (Phase 111)
| `docs/governance/PHASE111A_AUTHORITY_BOUNDARY_SCORECARD.md` | Authority scorecard |
| `docs/governance/PHASE111B_PROGRESSIVE_AUTHORITY_LADDER.md` | 6A→6E→7 ladder |
| `docs/project/PHASE111_AUTHORITY_BOUNDARY_SYS_ACTIONABILITY_CLOSEOUT.md` | **Phase 111 closeout** |

### Session 2026-06-01 Continued (Phases 112–169)
| Document/Route | Purpose |
|----------------|---------|
| `/v2/alert-siem` | SIEM normalized alert dashboard — 14-day retention, 84.8% noise reduction |
| `/v2/proposal-sandbox` | File-only proposal draft sandbox — 5 packets scored |
| `/v2/dual-opinion` | TradeAI vs Hermes dual-opinion advisory — 10 candidates |
| `/v2/queue-control-tower` | Queue/timer/scheduler control tower — 30 timers, 172 crons |
| `docs/advisory/` | Dual-opinion data model, evidence, choice capture, outcome tracking |
| `docs/learning/` | Learning queue (24 candidates), shadow scorer, effectiveness, lineage |
| `docs/journal_quality/` | Exit forensics, journal completeness, stop quality guards |
| `docs/ops/alerts/` | SIEM schema, Telegram gate, dedupe policy, stop alert intelligence |
| `docs/momentum_catalysts/` | Catalyst research bridge, quality scoring, timer design |
| `docs/proposal_sandbox/` | Proposal draft scoring, sandbox readiness |
| `docs/journal_sandbox/` | Journal insight samples |
| `docs/holdings_sandbox/` | Holdings discrepancy samples |
| `docs/operations/SCHEDULED_JOBS_REFERENCE.md` | 187 crons + 4 systemd documented |

### Phases 176-178: Queue Control Tower Upgrades
| Document/Route | Purpose |
|----------------|---------|
| Queue failure drilldown | LLM queue expandable drawer, error messages, safe requeue (max 3) |
| Operator approval gate | approve/reject endpoints, worker only picks 'approved' in --apply |
| Cron compression | 172 crons / 115 scripts, 24 consolidation candidates, bar chart |

### Phases 179-182: Paper Trading Statistical Readiness
| Document | Purpose |
|----------|---------|
| `docs/paper_trading/PHASE179A_PAPER_TRADE_SOURCE_INVENTORY.md` | 44 trades, 24 closed, field completeness audit |
| `docs/paper_trading/PHASE179C_CURRENT_PAPER_TRADE_STATISTICS_REPORT.md` | Statistics: WR 45.8%, PF 6.35, P0 readiness |
| `docs/paper_trading/PHASE179D_STATISTICAL_READINESS_THRESHOLDS.md` | P0-P5 readiness levels with data quality gates |
| `docs/paper_trading/PHASE179E_PAPER_TRADING_READINESS_DASHBOARD_REPORT.md` | Dashboard widget at /paper-status |
| `scripts/paper_trade_statistics.py` | Statistics script — 30+ metrics |
| `docs/atm/PHASE180A_ATM_CURRENT_CONFIGURATION_AUDIT.md` | ATM config: 6 max concurrent, 3 max/day, $100K paper |
| `docs/atm/PHASE180B_ATM_PAPER_SCALE_UP_RISK_POLICY.md` | 4-stage ramp policy, decreasing position sizes |
| `docs/atm/PHASE180C_ATM_PAPER_VOLUME_RAMP_SCHEDULE.md` | 25→50→100→200 trades/day, stage gates |
| `docs/atm/PHASE180D_ATM_PAPER_ONLY_GUARDRAILS_REPORT.md` | Guardrails verified: ALPACA_MODE=paper, live blocked |
| `docs/learning/PHASE181A_PAPER_TRADE_CLOSED_LOOP_FIELD_MAP.md` | 10-stage field map, broken link analysis |
| `docs/learning/PHASE181C_CURRENT_PAPER_TRADE_LOOP_VALIDATION_REPORT.md` | 0/24 fully closed, 24 partial, 0 broken |
| `docs/learning/PHASE181D_HERMES_PAPER_TRADE_AUDIT_INTEGRATION.md` | Hermes trade audit design spec |
| `docs/learning/PHASE181E_PAPER_TRADE_BACKTEST_COMPARISON_INTEGRATION.md` | Backtest comparison design spec |
| `scripts/validate_paper_trade_learning_loop.py` | Closed-loop validator |
| `docs/governance/PHASE182A_LIVE_READINESS_EVIDENCE_STANDARD.md` | Evidence: 2,000+ trades, 95%+ journal, 90%+ backtest |
| `docs/governance/PHASE182B_LIVE_READINESS_SCORING_MODEL.md` | 10-dimension scoring, 100 points |
| `scripts/generate_live_readiness_report.py` | Report generator — score 42/100 (EARLY) |
| `docs/governance/LIVE_AUTOMATION_READINESS_REPORT_latest.md` | Latest readiness report |

### Close Path Fixes
| Fix | Impact |
|-----|--------|
| All 6 close paths now compute hold_time_min, pnl, pnl_pct, r_multiple | hold_time 8%→100%, pnl 75%→100%, exit_price 75%→100% |
| Hardcoded paper-api URLs replaced with ALPACA_MODE env var | Safety: blocks non-paper mode |
| 23 existing trades backfilled | 0 broken loop trades (was 4) |

### Generated Output (not authoritative)
| Path | Content |
|------|---------|
| `docs/_generated/` | Governance reports, maturity snapshots, brief archive |
| `docs/playwright/` | Playwright screenshot archives |

---

## Archived (docs/_archive/)

1,276 files. Includes superseded versions, dated audits, executed prompts, session tarballs.
Archived this pass (2026-05-31):
- 4 top-level .tgz → `_archive/tarballs/`
- 2 session files (2026-05-27/28) → `_archive/reports/`
- 1 CC execution prompt → `_archive/prompts/`
- 1 ATM build prompt → `_archive/prompts/`
- 4 one-off dirs (drive_cleanup, cleanup, sessions) → `_archive/reports/`

## Trashed (docs/_trash/)

15 files. Morning briefs >7 days old + 2 empty files. Recoverable.

## Moved Outside docs/

- `~/backups/trade_ai_backup_20260524.zip` (2.9G) — was in docs/backups/

---

## Deferred — Next Session

- **MASTER architecture rewrite**: Replace all qwen3:14b references with gemma3:12b, update counts, refresh all 22 sections against live system
- **Architecture trio consolidation**: Merge MASTER + ARCHITECTURE_OVERVIEW + SYSTEM_ARCHITECTURE_COMPLETE into single authoritative source
- **Morning brief generator output path**: Change `aegis_morning_brief_delivery.py:403` to write to `docs/_generated/aegis_daily_briefs/` instead of `docs/` root

## Change Log

| Date | Change |
|------|--------|
| 2026-06-02 | **Docs consolidation audit (Stage 1)**: counts validated vs live (426 tbl+23 views, 184 crons, 26 strategies) & corrected in MASTER; new `EXECUTIVE_ARCHITECTURE_OVERVIEW.md` (app-owner high-level); qwen3:14b-chat drift bannered in 9 docs (qwen3-embedding:8b still active); stale `ARCHITECTURE_OVERVIEW.md` + `SYSTEM_ARCHITECTURE_COMPLETE.md` moved to _archive. Audit outputs in `docs/_audit/` (inventory/summary/drift/delete/archive). Stage 2 EXECUTED (operator-approved): deleted 1,563 obsolete files (1.43 GB — backups, snapshot dumps, _generated/_trash, dups); docs/ 1.4 GB/3,743 → 25 MB/2,186. Historical markdown reports retained in dated dirs; authoritative set + canonical docx preserved; git-recoverable. |
| 2026-06-02 | Phase 198: **advisory threshold tuning framework**. `tune_advisory_thresholds.py` replays the live `score()` (globals monkeypatched) over bar-validated closed-trade MFE peaks; sweeps thresholds. 24 cases/20 give-back: current **55% capture**, recommended LOCK 8→10 cuts false positives (flag 62.5→58.3%). **NOT applied** (small/synthetic sample, advisory params). Endpoint `/api/v2/atm/advisory-threshold-tuning` + pipeline step. Docs PHASE198A + closeout. Next: re-tune as real advised trades close. |
| 2026-06-02 | Phase 197: **profit-protection outcomes in v3 Journal hub**. New `ProtectionOutcomesPanel` + **Protection tab** in `JournalHub` (v3 built RC=0, live `/v3/journal`). Shows 83% gave back, \$2,646 left on table, per-trade give-back, ANY operator-adjusted. Consumes `/api/v2/atm/protection-advisory-outcomes`. Pure additive v3 frontend (clean-tree edit, no collision with v3 session). Doc PHASE197 closeout. Next: Phase 198 threshold tuning as advised trades close. |
| 2026-06-02 | Phase 196: **intraday MFE for same-day scalps**. `fetch_intraday_bars` (Alpaca 5min over hold window) + same-day detection + analyzer `.env` load (was silently failing Alpaca calls). **Full coverage: 24/24 measurable** (was 13). Final honest learning signal: **20/24 (83%) gave back profit, \$2,646 left on table** — all bar-validated. Docs PHASE196A + closeout. Next: Phase 197 surface outcomes in v3 Journal/Learning hub + threshold tuning. |
| 2026-06-02 | Phase 195: **close-timestamp capture fix**. Close paths (`open_trade_monitor`, `paper_trade_monitor`) set closed_at but never `exit_time` → only 5/24 trades bar-analyzable. Added exit_time/entry_time COALESCE to 4 close paths + robust analyzer date derivation + backfill. Result: **24/24 timestamped**, MFE measurable **3→13**, 9/13 (69%) gave back, **\$1,176 left on table** (was \$415). Docs PHASE195A + closeout. Next: Phase 196 intraday MFE for 11 same-day scalps. |
| 2026-06-02 | Phase 194: **MFE units fix** (data-integrity) + protection pipeline scheduling. `trade_execution_analyzer.py` wrote mfe_r (R) into the percent column `max_favorable_excursion` — fixed to write %. Reconciler now sources give-back from bar-based `trade_mfe_analysis.money_left` (\$); no-bar trades honest-unknown. **Retracts Phase 193 41.7%** → 3/3 measurable gave back, **\$414.68 left on table** (ASPN \$265 closed flat after +8.9%). Orchestrator `run_protection_pipeline.sh` + cron (30m market hrs + 20:30). Docs PHASE194A-B + closeout. Next: Phase 195 fix trade-close timestamp capture (21/24 lack times). |
| 2026-06-02 | Phase 193: **profit-protection close-loop reconciler**. `reconcile_protection_advisory_outcomes.py` + table `protection_advisory_outcomes` + endpoint `/api/v2/atm/protection-advisory-outcomes`. Joins advisory+adjustment+outcome per trade. Baseline finding: **41.7% (10/24) of legacy closed trades gave back profit with no advisory**. ANY round-trip captured (accepted, giveback avoided $300). MFE units flagged inconsistent (not fabricated). Docs PHASE193A-B + closeout; migration `2026_06_02_phase193_advisory_outcomes.sql`. ANY profit-lock EXECUTED (3.07→3.56). v3 ProtectionPanel added by v3 session → v2/v3 parity complete. |
| 2026-06-02 | Phase 192: **operator-approved paper stop/TP adjustment** + Command Center **v2/v3 parity**. Both CCs real & live (`portfolio_server.py` serves `/v2/`+`/v3/`); API shared. New: `generate_paper_protection_adjustment_proposals.py`, `apply_paper_protection_adjustment.py` (guarded, dry-run default, replace-only), endpoints `/atm/protection-adjustment-proposals[/:id][/approve]`, v2 `ProtectionAdjustmentPanel` (built+live), v3 plan (deferred — v3 in-flight). ANY profit-lock dry-run 3.07→3.555 (lock $0→$201), **no order modified**. Docs PHASE192A-L; migration `2026_06_02_phase192_adjustment_proposals.sql`. |
| 2026-06-02 | Phase 191: **ATM profit-protection intelligence** (advisory-only). `profit_protection_advisory.py` (TradeAI scoring: stop quality / lock / giveback), `hermes_profit_protection_check.py` (second opinion, +5 finding types), endpoint `/api/v2/atm/profit-protection-advisory`, table `atm_profit_protection_advisories`. ANY=URGENT_PROTECTION_REVIEW, SNOW=TAKE_PROFIT_ADVISORY. Docs PHASE191A-J; migration `2026_06_02_phase191_profit_protection.sql`. Next: Phase 192 operator-approved stop/TP adjustment. |
| 2026-06-02 | Phase 188–190: market-open ELMT/SNOW review + protection root-cause + **durable guardrails**. Corrected "naked" → broker stops exist but DB-untracked; built `verify_paper_trade_broker_stops.py` (untracked 3→0), `protection_alerts.py` (SIEM/Telegram), Hermes `hermes_v_open_position_protection_context` view + 6 rules, ATM protection endpoint, adapter stop-confirmation fix, PENDING_TRADING_WINDOW design. Docs: PHASE188A-E, PHASE189A-H, PHASE190A-I; migration `2026_06_02_phase190_protection.sql` |
| 2026-05-31 | A1A hygiene pass: archive 30 files, trash 15, fix SKILLS.md model refs, add MASTER stale warning, update counts (392 tables, ~190 crons, 24 strategies), thin index from 398→~120 lines |
| 2026-05-30 | Hermes P0-P1D docs, Phase 1C SQL drafts synced to Drive |
| 2026-05-29 | Classifier 100%, proposal P0/P1, backtesting UI, ATM audit, lifecycle inspector |
| 2026-05-28 | LLM safety, classifier enrichment, Ollama upgrade, model canaries |
