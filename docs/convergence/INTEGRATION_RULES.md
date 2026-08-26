# Integration Rules

- One canonical source of truth per concept; extend existing contracts instead of cloning.
- No concurrent edits to shared files.
- No frontend business logic for runtime, materiality, notification, or maturity decisions.
- Every claim has implementation reference, test, evidence class, and reproduction command.
- Read-only by default. No broker, order, stop, risk-policy, 2FA, or financial-policy mutation.
- Agents commit locally and hand off SHA; Integrator reviews before merge.
