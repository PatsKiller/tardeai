# /v3-next Component Matrix — Stage 6

| Panel | testid | Data source | Read-only proof |
|---|---|---|---|
| Classic/Next nav | classic-next-nav | static | nav-classic → /v3/ (untouched) |
| Session strip | session-strip | fixtures.session | display only |
| Moomoo badge | moomoo-badge | MOOMOO_STATUS | 3 blocked badges, no green/live |
| Prime queue | prime-queue | fixtures.candidates | null rvol/float → Unavailable |
| Symbol selector | symbol-selector | state | switches workspace |
| Symbol workspace | symbol-workspace | fixtures.symbol | chart/L2/tape = Unavailable |
| Pre-trade ticket | pretrade-ticket | — | ReadOnlyAction(stage) disabled |
| Working-order ticket | working-order-ticket | — | Unavailable |
| In-trade ticket | intrade-ticket | — | ReadOnlyAction(sell-smart, flatten) disabled |
| P&L panel | pnl-panel | fixtures.positions | marks/P&L = Unavailable |
| Accounts | accounts-panel | fixtures.accounts | masked ids only |
| Brokers | brokers-panel | fixtures.brokers | moomoo NOT_INSTALLED |
| Capabilities | capabilities-panel | fixtures.capabilities | effective_state incl. RESTRICTED/UNKNOWN |
| Rejections | rejections-panel | fixtures.rejections | redacted raw message |
| Notifications | notifications-panel | fixtures.notifications | ReadOnlyAction(acknowledge) disabled |
| Journal | journal-panel | fixtures.journal | replay reference only |
| Feature modal | feature-modal | fixtures.features | mutable=false; prod OFF |
| Parity/status | parity-panel | fixtures.parity | BASELINE_ONLY, no UI parity |
