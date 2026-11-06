# Design proposals (DRAFT)

Work in progress before it becomes a page version. One folder per proposal: `design/proposals/<DSN-id>/` with a
`SPEC.md` (text only: what changes, what stays, every removal / hide / move). Mockups are built from
`design/system/tokens.json` at 1440, 412 and 390 and saved only in the private store
(`persistent-state/data/design/pages/<page-id>/vNNN/mockups/`), never here.

When the proposal is ready, add `design/pages/<page-id>/versions/vNNN/` with `SPEC.md` and a `status.json` in state
`PROPOSED` (fingerprints of the private mockups). It then appears in Approvals → Designs for the operator's one-tap
decision. See `design/README.md`.
