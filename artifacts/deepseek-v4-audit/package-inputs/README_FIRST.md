# Trade AI DeepSeek V4 Implementation Package v2

Created: 2026-08-03T13:12:30.147930+00:00
Package date: 2026-08-03

## Contents

1. `EXECUTE_TRADE_AI_DEEPSEEK_V4_RECONCILIATION_AND_MATURITY_PROMPT.md`
   - The staged, evidence-gated execution contract for Cursor/developer use.

2. `TRADE_AI_DEEPSEEK_V4_ROUTING_AND_SITE_MATURITY_AUDIT_2026-08-03.md`
   - The due-diligence findings, routing recommendations, maturity gaps, and acceptance gates.

3. `TRADE_AI_LLM_MODEL_REGISTRY_PROPOSED.json`
   - Proposed canonical provider/model registry using explicit Flash and Pro policies.

4. `TRADE_AI_LLM_PROCESS_POLICY_PROPOSED.json`
   - Proposed process-level routing, escalation, schema, and cost-governance policy.

5. `UPLOAD_FROM_POWERSHELL.ps1`
   - Uploads this package to the server and verifies extraction/checksums.

6. `SHA256SUMS.txt`
   - SHA-256 checksums for every payload file in the archive.

7. `PACKAGE_AUDIT.json`
   - Machine-readable package inventory and verification status.

## Intended server directory

`/home/johnclaw/implementation-inputs/deepseek-v4-2026-08-03`

## Verification after extraction

```bash
cd /home/johnclaw/implementation-inputs/deepseek-v4-2026-08-03
sha256sum -c SHA256SUMS.txt
```

Do not place the package directly inside an existing Git worktree.
