# Release Manifest — Latest

**Status:** Template / next-run target  
**Created:** 2026-06-16  
**Owner:** Release readiness / Command Center v3 governance

## Purpose

This manifest captures the evidence required before tagging a Command Center v3 or broker-adjacent release. It should be regenerated or updated after running the release readiness gate.

## Required commands

```bash
python3 scripts/repo_hygiene_report.py --markdown --out docs/project/repo_hygiene_latest.md
python3 scripts/validate_metric_consistency.py --strict
python3 scripts/validate_release_readiness.py --json
python3 scripts/rotation_intelligence_engine.py --input data/portfolios/state/holdings.json > docs/project/rotation_intelligence_latest.json
```

If symbol cards are exported:

```bash
curl -s http://localhost:7777/api/v2/symbol-cards > data/runtime/symbol_cards_latest.json
python3 scripts/validate_symbol_card_quality.py --input data/runtime/symbol_cards_latest.json --json
```

## Manifest fields

| Field | Value |
|---|---|
| Git SHA | TO BE FILLED BY RELEASE RUN |
| Dirty count | TO BE FILLED BY `repo_hygiene_report.py` |
| Live-adjacent dirty files | MUST BE 0 FOR RELEASE |
| Secrets/config dirty files | MUST BE 0 FOR RELEASE |
| Metric consistency | PASS REQUIRED |
| Command Center v3 build | PASS REQUIRED when UI changed |
| Schwab write-policy validator | PASS REQUIRED when present |
| A1A docs updated | REQUIRED when behavior/docs/schema/frontend changed |
| Rollback command | `git reset --hard <known-good-sha>` plus service restart |

## Current hardening baseline commits

The v3 trust-hardening baseline started with these additive commits:

- metric registry: `config/metric_registry.yaml`
- repo hygiene classifier: `scripts/repo_hygiene_report.py`
- metric consistency validator: `scripts/validate_metric_consistency.py`
- symbol-card quality validator: `scripts/validate_symbol_card_quality.py`
- release readiness gate: `scripts/validate_release_readiness.py`
- rotation advisory schema: `migrations/20260616_rotation_intelligence.sql`
- rotation advisory engine: `scripts/rotation_intelligence_engine.py`
- docs: `docs/project/METRIC_DEFINITIONS.md`
- docs: `docs/project/V3_TRUST_HARDENING_AND_ROTATION_INTELLIGENCE.md`

## Safety note

This release discipline layer is advisory/control-plane only. It does not authorize live trading, does not modify protective-stop envelopes, and does not change broker approval requirements.
