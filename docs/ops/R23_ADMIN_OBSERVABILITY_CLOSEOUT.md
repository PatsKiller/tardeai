# R23 Research, Data, Identity, and Notification Observability

**Status:** DESIGN_BASELINE_ONLY  
**Evidence class:** SOURCE_ONLY  
**Authority:** READ_ONLY_ADVISORY

R23 will expose research attention, CanonicalStoreRegistry health, identity resolution,
and the notification funnel as read-only projections. It will preserve explicit states
for stale, conflicted, unresolved, blocked, and unavailable data. No UI may manufacture
identity or decide research materiality.

Planned side-by-side routes are `/control-plane/research`, `/control-plane/data`,
`/control-plane/identity`, and `/control-plane/notifications`. They depend on the R21
contract and remain unimplemented until the Integrator wires canonical readers.
