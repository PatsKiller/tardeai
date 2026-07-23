# Stage 5 Resume Requirements — run 20260722-01
Stage 5 remains BLOCKED_CREDENTIAL_GATE (offline implementation GREEN). To resume:
1. Resolve the Moomoo website/login lockout (operator via moomoo recovery/support).
2. Complete the moomoo OpenAPI regulatory questionnaire + agreement (ProgramStatusType_UnAgreeDisclaimer).
   (Device SMS verification is already COMPLETE — this machine is a trusted device.)
3. Reply "moomoo agreement done — retry"; controller runs ONE login via device_auth_telnet.py.
4. On success: data-only smoke → >=30-min RTH capture → resumable five-RTH-session observation.
Only after five RTH sessions PASS do Stage 9 acceptance and Stage 10 promotion unblock. BF-1 (UNPROVEN)
independently blocks any live scalp. Stage 14 live canary stays BLOCKED. Do NOT retry login otherwise.
Resume branch tip after Stages 6-11: feat/active-trader-next (see final closeout for exact SHA).
