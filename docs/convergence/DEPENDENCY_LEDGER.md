# Dependency Ledger

1. Contract vocabulary is frozen at **ControlPlane@v1.0.0** before new UI logic.
2. R21 (Codex) implements GET-only APIs. R22-R24 use `fixtures/control_plane/v1.0.0` until that handoff.
3. R20 runtime evidence powers Agent Office and Workflow Trace.
4. R23 pages read CanonicalStoreRegistry and identity spine; they do not recompute truth.
5. R24 maturity uses evidence classes and proof references; replay is never natural-current.
6. Integrator owns shared route registration, schema registry, and cross-stream tests.

Blocking conditions: missing canonical source, unsafe authority boundary, schema conflict,
or any regression in existing live routes.
