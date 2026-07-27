# Stage 10 Plan — Multi-Broker Simulation
Run 20260722-01. NO live/paper broker calls — deterministic in-process simulation for Alpaca,
Schwab, Moomoo-future-adapter (SnapTrade/Fidelity/Tastytrade excluded). Lifecycle, translation,
bounded smart-limit (no 750ms loop; >=1.9s reprice), multi-account primary/fallback with
duplicate-exposure prevention, protection, P&L. Promotion BLOCKED (Stage 5 + Stage 9 gates).
Terminal: GREEN_IMPLEMENTED_PROMOTION_BLOCKED.
