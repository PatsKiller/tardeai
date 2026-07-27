# Session Authorization Architecture — Stage 8
`scripts/active_trader/authorization.py`. Providers: AuthorizationProvider (abstract),
TestAuthorizationProvider (deterministic double — one VERIFIED_TEST → one bounded session),
UnavailableProductionAuthorizationProvider (LIVE_INACTIVE, never real). `issue_test_authorization`
refuses LIVE and any non-VERIFIED_TEST result. SessionAuthorization binds draft_hash+operator+time;
check_active (not-before/expiry/revoked), check_account, check_symbol (explicit or __UNIVERSE__),
binds(draft_hash). `requires_reauthorization` true on changed hash / new account / larger quantity /
env change. No real 2FA integration exists.
