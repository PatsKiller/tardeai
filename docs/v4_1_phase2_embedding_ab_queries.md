# Phase 2A — Embedding A/B Retrieval Query Set

40 representative queries across 20 categories for embedding quality comparison.

## Queries

| # | Category | Query |
|---|----------|-------|
| 1 | Portfolio holdings | Show current portfolio composition and allocation |
| 2 | Portfolio holdings | What are the largest positions by market value? |
| 3 | Watchlist | Find recent analysis for AVAV |
| 4 | Watchlist | What is the current watchlist thesis for RKLB? |
| 5 | Recovery/re-entry | Find recovery watch evidence for TDG |
| 6 | Recovery/re-entry | What changed in RTX after stop-out? |
| 7 | Closed trades | Show recent closed trades with bad exits |
| 8 | Closed trades | Find failed breakout trades in the journal |
| 9 | Auto journal | What patterns exist in automated journal entries? |
| 10 | Auto journal | Show journal evidence for early exits |
| 11 | Manual journal | Find latest journal review for manual trades |
| 12 | Manual journal | Show journal entries mentioning stop placement |
| 13 | Risk synthesis | Show risk synthesis evidence for unprotected positions |
| 14 | Risk synthesis | Find portfolio concentration risk warnings |
| 15 | Proposals | Why did BLBD become a proposal? |
| 16 | Proposals | Find prior reasoning for swing trade proposals |
| 17 | RAG curation | Show recent RAG curation approvals |
| 18 | RAG curation | Find RAG content rejected with reasons |
| 19 | News/catalysts | Find defense sector rotation evidence |
| 20 | News/catalysts | Show recent catalyst news for LMT |
| 21 | CIO decisions | Show prior CIO HOLD decisions with correct outcomes |
| 22 | CIO decisions | Find CIO recommendations that were wrong |
| 23 | Fused signals | What fused signals exist for SCHD? |
| 24 | Fused signals | Find strong convergent signals across agents |
| 25 | SEC/Form 4 | Show insider or Form 4 evidence for defense stocks |
| 26 | SEC/Form 4 | Find recent insider buying activity |
| 27 | YouTube | Find YouTube transcript intelligence for dividend investing |
| 28 | YouTube | Show YouTube evidence about market conditions |
| 29 | Strategy classification | Find strategy classifications with low confidence |
| 30 | Strategy classification | Show positions flagged for reclassification |
| 31 | Deep overnight | Find deep overnight results about risk management |
| 32 | Deep overnight | Show gemma3 analysis of recovery watch symbols |
| 33 | Agent rules | Find agent intelligence rules for income strategies |
| 34 | Agent rules | Show Maria research findings for growth stocks |
| 35 | Paper outcomes | Find examples where MFE was high but realized profit was low |
| 36 | Paper outcomes | Show paper trades that hit targets |
| 37 | Covered calls | Show covered call candidates that need review |
| 38 | Covered calls | Find covered call scoring evidence for V |
| 39 | Stop/recovery | Find stop-triggered analysis for defense positions |
| 40 | Stop/recovery | Show recovery watch evidence for IRDM |

## Query Design Notes

- Queries span all 14 source types in content_embeddings
- Mix of symbol-specific and thematic queries
- Include both high-signal (trade outcomes, CIO decisions) and broad (news, social) sources
- Representative of actual operator questions during morning briefing
