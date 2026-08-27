# Phase 3 — Workflow Discovery

**Date:** 2026-05-14

## Discovered Media/Content/Prose Scripts

| Script | Purpose | Uses LLM | Safe for Phase 3 | Status |
|--------|---------|----------|-------------------|--------|
| `youtube_transcript_ingest.py` | YouTube video transcript ingestion | Yes (cleanup/summary) | SAFE_FOR_PHASE3_PILOT | Candidate |
| `transcript_slow_processor.py` | Clean + summarize + sub-tag transcripts | Yes (LLM summary) | SAFE_FOR_PHASE3_PILOT | Candidate |
| `content_scoring.py` | Unified content scoring + tagging | Yes (classification) | SAFE_FOR_PHASE3_PILOT | Candidate |
| `news_ingestion.py` | News article ingestion | Minimal LLM | DEFER | Low LLM usage |
| `social_ingest.py` | Social/scalp content ingestion | Minimal LLM | DEFER | Low LLM usage |
| `topic_ingestion.py` | Topic data ingestion | Optional LLM | SAFE_FOR_PHASE3_PILOT | Candidate |
| `topic_curator.py` | Quality rating, entity extraction | Yes (LLM curation) | SAFE_FOR_PHASE3_PILOT | Candidate |
| `aegis_morning_brief_delivery.py` | Morning brief prose | Yes (narrative) | SAFE_FOR_PHASE3_PILOT | Candidate |
| `aegis_transcript_discovery.py` | Transcript discovery | Minimal | DEFER | Low LLM usage |
| `agent_curation_hooks.py` | Content curation hooks | Yes | SAFE_FOR_PHASE3_PILOT | Candidate |

## Blocked Scripts (Trading/Execution)

| Script | Reason |
|--------|--------|
| `risk_gate.py` | Trading execution gate |
| `alpaca_paper_adapter.py` | Broker order submission |
| `open_trade_monitor.py` | Active trade monitoring |
| `paper_execution_revalidator.py` | Execution revalidation |
| `proposal_paper_submitter.py` | Order submission |

## Summary

- **7 scripts** identified as SAFE_FOR_PHASE3_PILOT
- **3 scripts** deferred (low LLM usage)
- **5+ scripts** blocked (trading/execution)
