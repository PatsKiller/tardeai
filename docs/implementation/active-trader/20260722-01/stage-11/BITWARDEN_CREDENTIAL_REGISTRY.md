# Bitwarden Credential Registry — Stage 11 (METADATA ONLY)
BITWARDEN_REGISTRY records: secret_name, project-id SUFFIX (<=12 chars; never full id/value),
required/optional, present, sentinel-rejected-by-runtime. Entries: ACTIVE_TRADER_TEST_DATABASE_DSN,
ACTIVE_TRADER_READ_API_DSN (project 1b0a478d = trade-ai-lab), MOOMOO_DATA_LOGIN_ACCOUNT/PASSWORD/
TEST_SYMBOLS (project 00375f2c = trade-ai-moomoo-data), GMAIL_NOTIFICATION_CREDENTIAL_SLOT (optional,
operator TODO). NO values, NO full ids, NO trade-unlock/live-order secret. No Moomoo login retried;
no new machine account; no production access. Runtime rejects UNSET__OPERATOR_REQUIRED sentinels.
