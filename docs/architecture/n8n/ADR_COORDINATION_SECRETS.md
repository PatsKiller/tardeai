# ADR: coordination secrets for the n8n lab

Status: proposed. Not installed. The pilot stays BLOCKED_POLICY until an operator accepts a bootstrap that never places a seed in n8n.

## Threat model

The caller is an untrusted process that can reach 127.0.0.1. Loopback is not an identity. Headers `X-Forwarded-For`, `X-Real-Ip`, and `Forwarded` are ignored. A stolen bearer must not place an order, mint a grant, satisfy 2FA, promote a release, bid, or open a DOF SQL path. Logs and execution records must not contain the HMAC seed, a provider key, a broker credential, a database URL, or a TOTP secret.

## Key handling

The seed lives in Bitwarden. The source-side process reads it from the environment at start. It is not an n8n credential. Rotation keeps the previous key on `TRADEAI_N8N_GATEWAY_HMAC_KEY_PREVIOUS` only for the overlap window. A claim lives at most 300 seconds with 5 seconds of clock skew. The nonce is consumed only after the MAC matches. Scope is `coordination_read`. Project is `trade-ai` or `nyc-dof-auction` and must match the event. The lane must be on the allowlist. The method and path allowlist is `GET /healthz` and `POST /v1/coordination`. The event carries the source SHA the server expects.

## Bootstrap that stays inside the policy

The source-side dispatcher signs the claim and does not hand the seed to n8n. If n8n must correlate an event, the dispatcher issues an opaque reference. The ledger stores only the hash. The reference is bound to one project, one lane, one idempotency key, and an expiry. Redeeming it cannot mint a broader claim and cannot call a forbidden route; those routes are refused before the claim is treated as authority.

This is still not an install. n8n stores execution input. Putting the reference into a workflow would copy a bearer into that store. Until a reviewed design shows the execution record does not retain it, no workflow is created and no secret-bearing node is added.

## Tests that exist

Unknown method, encoded path, proxy header without a signature, oversized body, invalid UTF-8, old and new key overlap, crash before commit, two connections racing one nonce, and a reference that cannot change lane. All of those are local. None of them ran inside n8n.

## What remains false

`durable=false` on the gateway receipt. No claim of exactly-once delivery outside the sqlite file. No n8n credential. No DOF role.
