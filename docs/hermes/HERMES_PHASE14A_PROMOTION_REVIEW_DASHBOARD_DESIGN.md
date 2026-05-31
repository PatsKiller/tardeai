# Phase 14A — Promotion Review Dashboard Design

**Status:** COMPLETE

## Design
- Add "Promotion Review" section to existing Hermes Intelligence page
- Read-only: displays Phase 13 dry-run candidate recommendations
- API: `GET /api/v2/hermes/promotion-review` reads dry-run JSON files
- Labels: "Dry-Run Only", "Advisory Only", "Auto-Promotion Prohibited"
- No action buttons (no promote/approve/reject/trade)
- No write endpoints
