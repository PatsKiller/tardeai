# Moomoo Device Authorization Status — Stage 5 (operator-present ceremony)

## Progress (2026-07-23, operator-present)
1. Credential gate GREEN (token/project/3 secrets).
2. Data login PASSWORD: **CORRECT** (after operator corrected MOOMOO_DATA_LOGIN_PASSWORD;
   login_account = the operator's moomoo email).
3. SMS device verification: **COMPLETE** — code accepted over OpenD's loopback telnet
   interface (documented headless method). OpenD reached full login
   (Crypto LV1, US trade connection, account confirmed). This machine/OpenD client is now
   a trusted device (future logins should not re-prompt for SMS within moomoo's window).

## NEW BLOCKER — moomoo OpenAPI regulatory agreement (operator action)
Immediately after login, OpenD reported `ProgramStatusType_UnAgreeDisclaimer` and exited:
> "To meet regulatory requirements, API users must complete a relevant questionnaire
>  evaluation and agreement confirmation. Please go to complete it first:
>  https://api.moomoo.com/v2/webview/jump?user_id=<REDACTED>&...clientver=10.09.6908..."
This is a one-time moomoo compliance step: the account must complete the OpenAPI user
questionnaire + agreement before any API (even data) will run. Codex cannot complete it.

## Operator action to unblock
Complete the moomoo OpenAPI user questionnaire/agreement, via ONE of:
- the moomoo app / desktop: **Me → (Settings/Help) → OpenAPI** and finish the API-user
  agreement + questionnaire; OR
- open the URL OpenD logged (it embeds your user_id) while signed in to moomoo and
  complete the evaluation + agree.
Then reply "moomoo agreement done — retry" and Codex will re-attempt login (no SMS
expected — device already trusted). On success: data-only smoke → ≥30-min capture during
an OPEN US RTH session → five-RTH observation.

## One-time deviations recorded (revert for runtime)
- console=1 was tried first (OpenD ignores stdin commands in 10.9.6908 — abandoned).
- A loopback-only telnet port (127.0.0.1:22222) was opened SOLELY for this one-time
  device-auth ceremony (documented headless method). The persistent runtime reverts to
  console=0 and NO telnet (secret_render defaults: console=0, telnet_port=None).
- Helpers: scripts/active_trader/moomoo/device_auth.py (console/PTY, deprecated) and
  device_auth_telnet.py (telnet, working). AST guard still proves 0 trade methods reachable.

## Safety (unchanged)
No trade context/unlock/order/2FA. auto_hold_quote_right=0 (quote rights never grabbed).
Post-ceremony: 0 OpenD processes, 0 listeners (11112/22222), tmpfs config shredded.
Password/verify values never displayed or logged (log values redacted).
