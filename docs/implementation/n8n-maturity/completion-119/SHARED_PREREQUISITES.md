# Shared prerequisites for the 119-lane source completion train

Evidence class: SOURCE_ONLY; validation: TEST_ONLY. Runtime, deployment and scheduler acceptance are NOT_MEASURED.

The train starts from main `65337da5366b469c8478b198187201bd37671bc2`. It keeps operational lane-registry, allowlist and health-contract entries unchanged. Admission candidates live beside this document and are not executor configuration.

## Implemented shared corrections

- Integrate the hermetic-bootstrap branch selectively: empty fixture roots and loader inputs, opt-in M2 setup, production-path/DSN refusal, and test failures for swallowed refusals. Preserve newer main notification and broker-name audit changes.
- Normalize guarded paths through realpath; negative guard tests use synthetic protected roots rather than attempting real host reads. The external pre-import launcher additionally guards child processes, credentials, sockets and host commands and reaps children on refusal.
- Defer Session 13 and pipeline heartbeat credential loading until an actual connection request and declare only the DB names each helper uses. Importing either helper loads no secrets or database driver.
- Resolve named model requests to existing server-approved caller/task pairs, validate returned process identity/governance/cost proof, and bind the executor's validated route metadata into the child environment. No new process registrations, model choices, provider calls or credentials are added.
- Agent-runtime `--dry-run` describes an invocation before backend import and authorization-consuming work; actual authorization and default-disabled behavior stay intact.

## Preserved authority and refusal

The server bridge remains the authoritative caller/task map. Its source has inherited mixed line endings, so `safe_text_edit` refused map extraction. That file was not edited and the refused action was not retried. The client route snapshot is checked for exact equality with the server's static maps; it cannot invent routes. Unmapped processes remain owner-blocked.

The shared test bootstrap is reused from local commit `13c9919eb766273dc23658c9629e0708a302a6fb`; only reviewed source changes needed by this train are retained. G8/G9 entrypoint changes belong to lane owners; their presence on a separate branch does not establish main integration.

## Initial verification

The isolated shared regression command covers bootstrap, route identity, executor environment policy and existing model-job/executor behavior: 87 tests passed, zero external capability refusals, all owned descendants reaped. This tests the modified worktree; final-head full PR-profile proof is recorded separately after lane integration.

Source-only work never authorizes push, REVIEWED contract state, runtime execution, model egress, activation, release or scheduler cutover.
