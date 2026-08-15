# R3/R4 Build Baseline

Isolated additive workstream on top of merged R1+R2.

- worktree: `/home/johnclaw/tradeai-wt-research-r3r4`
- branch: `feature/research-r3-r4`
- BASE_SHA: `f1cc17e50e0eec657aa47f8f9bdeb0b455bdb08e`
- REMOTE_MAIN_AT_START: `f1cc17e50e0eec657aa47f8f9bdeb0b455bdb08e`
- R1_MERGE_SHA: `c005551a1e5da5a8d3f46d9e3018bff9bd516e7c`
- R2_MERGE_SHA: `f1cc17e50e0eec657aa47f8f9bdeb0b455bdb08e`

Authority: `READ_ONLY_ADVISORY`

R3 = Almanac reproduction (RGA-15). Public STA alert citations only. No full text.
R4 = retrieval adapter + decision-use audit + degradation (RGA-16). Dry-testable.
No broker/order/stop/2FA. No Telegram sends. No RELEASE_MANIFEST / deploy edits.
Does not rewrite `cio_acceptance_v4.py` or live report pipelines.
Existing `cio_seasonality_analytics` / `cio_research_retriever` remain; R3/R4
govern and audit them through adapters.
