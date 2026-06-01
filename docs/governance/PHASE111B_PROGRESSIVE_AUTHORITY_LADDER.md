# Phase 111B — Progressive Hermes Authority Ladder

| Level | Name | Allowed | Prohibited |
|-------|------|---------|-----------|
| 6A | Advisory Only | Advisory cache, embeddings, recommendations | All execution writes |
| 6B | Proposal Draft Recommendations | Recommend draft proposals (file/report only) | Proposal rows |
| 6C | Proposal Draft Staging | Isolated hermes_proposal_drafts table, operator approval | Real proposal table |
| 6D | Journal Append-Only Insights | Append insight annotations, never rewrite | Journal row overwrite |
| 6E | Holdings Discrepancy Recommendations | Recommend discrepancies (file only) | Holdings writes |
| 7 | Execution Authority | Separate governance track | Default PROHIBITED |

**Current level: 6A**
