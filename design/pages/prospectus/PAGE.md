# Prospectus

- **Page id:** `prospectus`
- **Route:** `/v3/prospectus`, `/v3/prospectus/:symbol`
- **Nav group:** Intel (appended after Communications)
- **Component:** `apps/command-center-v3/src/pages/ProspectusPage.tsx`
- **Owner:** coordinator (builds) · operator (approves)
- **Approved version:** none yet
- **Current (verified) version:** none yet — becomes CURRENT only after the post-release visual check passes

## Purpose

One written research prospectus per holding and Watch ticker, versioned: colored sections with citations, charts,
PDF / Word / HTML downloads, and an operator-only rewrite.

## Data sources

- `/api/v2/prospectus/index`
- `/api/v2/prospectus/{symbol}`
- `/api/v2/prospectus/{symbol}/file/{pdf|docx|html}`
- `/api/v2/prospectus/{symbol}/refresh` (POST, operator only)

## Versions

| Version | State | Approved | Notes |
|---|---|---|---|
| v001 | DRAFT | — | First build on fixtures; awaiting the operator mockup approval |

How to change this page: design/README.md (propose a new version; never edit an approved one).
