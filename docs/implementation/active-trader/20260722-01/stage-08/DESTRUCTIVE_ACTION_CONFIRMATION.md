# Destructive Action Confirmation — Stage 8
Destructive set: cancel_all_symbol, cancel_all_account, flatten_symbol, flatten_account,
overnight_convert. Each requires an explicit confirmation_token equal to
`CONFIRM:<action>:<symbol|account_label>`; absent/wrong token → BLOCKED. Tested for all destructive
actions (blocked without token; validated-inactive with the correct token). Confirmation is NOT a
2FA and issues no execution.
