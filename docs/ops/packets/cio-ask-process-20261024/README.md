# Ask-CIO process: source and operator handoff

Design-Task: `DSN-20261024-cio-ask-process-P1-T1`

Status: local source verification; not a deployment or live model test.
Base: `9228634873392073f5849aaa77ec9b9121eb6094`.
Main report: [governed registration](../../CIO_ASK_PROCESS_REGISTRATION_20261024.md).

The bridge and `governed_process_routes` both map the two exact tasks below to
one process ID, `cio_ask_deep_research`. No second cap bucket is created.

| Existing client API | Value / interpretation |
| --- | --- |
| Function | `lib.n8n_model_job.bridge_governed_call(messages, *, process_id, response_format=None, request_id=None, timeout_s=60.0, task_type="model_job", routing_policy=None, caller="n8n_model_job", max_tokens=2048, context_id=None, manual_trigger=False)` |
| Caller/process | `caller="advisory_desk"`, `process_id="cio_ask_deep_research"` |
| Standard task | `task_type="cio_ask_deep_research"` |
| Depth task | `task_type="cio_ask_deep_research_depth"` |
| Request identity | Stable bounded question/answer-version identifier, retained in `request_id`; actual provider journal replay protection remains intact. |
| Operator intent | Ask requires `manual_trigger is True`, set only by an authenticated real operator entry path. The helper sends `X-TradeAI-Manual-Trigger: 1`; the server requires that exact marker after caller auth. Default/automated/re-answer attempts stop before transport or cost. Body origin/depth/manual flags do not authorize it. |
| Research context | Explicit `context_id` becomes `X-TradeAI-Context-Id`; omitted uses only the existing current context. No ID is generated. Missing context is omitted so Ring2 still decides; unsafe IDs/current-reader failure refuse before transport. |
| Policy | Omit `routing_policy` for the registered default. No arbitrary provider/model/tier parameter is added. |
| Success | Require `_tradeai.governance_pass is True`, matching `_tradeai.process_id`, valid reservation/provenance, and a non-mock result before claiming a real run. Content is `choices[0].message.content`. |
| Provenance | `_tradeai.provider`, `model_id`, `requested_policy`, `request_id`, `reservation_id`, `route_receipts`, `reasoning_tier`, `cost_estimate`, `cost_basis`; top-level `model` mirrors the served model. Preserve actual serving identity. |
| Refusal | `error.code`, `error.status`, retry classification and returned route receipts. A refused call is not success or a cue for an ungoverned provider fallback. |

The existing client helper returns the envelope; the caller must validate it.
It does not turn a cost estimate into independently proven settled spend.
The intent header carries the trusted host caller's explicit assertion; actual
operator-turn validation belongs to the authenticated Ask entry path, not an
inferred origin string or this header alone.
Question-wide accounting and operator intent are implemented by the separate
Ask quality fix. An in-process non-bridge generation call must carry explicit
manual intent only for an operator-origin CC/Telegram question. Re-answer
configuration is unchanged and remains shadow.

After coordinator publication, the operator first reviews this exact dry run:

```bash
cd /home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild
.venv/bin/python scripts/sync_cio_process_caps.py --dry-run --process-id cio_ask_deep_research
```

Expected source preview (executed locally without database import):

```text
  [dry-run] would upsert cio_ask_deep_research: cost=5.0 soft=30
  [dry-run] Ask-CIO new-row mode=manual; existing-row mode unchanged
```

Operator only, after reviewing that preview and the accepted source:

```bash
cd /home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild
.venv/bin/python scripts/sync_cio_process_caps.py --process-id cio_ask_deep_research
```

This command writes only the selected process's cap/count row and reads back
that selected row. It preserves an existing row's mode. It has not been run
against a real database by this worker. Bridge restart/release procedures are
owned by the coordinator; this packet does not execute or grant them. The
operator re-asks only after the combined quality fix is actually served.

Private receipts live under
`/home/johnclaw/.cache/rtc/codex-cio-ask-process-20261024/`.
`verification.json` records current source/test hashes and all qualification.
