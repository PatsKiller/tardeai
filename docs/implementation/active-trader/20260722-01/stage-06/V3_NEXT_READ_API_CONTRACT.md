# /v3-next Read API Contract Consumption — Stage 6

/v3-next consumes exactly the Stage 4 envelope shape (see stage-04 READ_API_SCHEMA.md):
`api_version, service, environment(SHADOW|SIMULATION), request_id, generated_at, data_as_of,
source_sha, sources[{source_name,source_type,freshness_state}], warnings[{category,detail}],
data`. Warning categories rendered: STALE, UNAVAILABLE, PARTIAL, CONFLICT, NOT_INSTALLED,
NOT_CONFIGURED, UNVERIFIED, REDACTED. The fixtures module returns these envelopes; swapping to
the live read client (a later, separately-authorized step) is a one-line source change per panel
because panels read `{data, warnings}` only. LIVE environment is never rendered by this bundle.
