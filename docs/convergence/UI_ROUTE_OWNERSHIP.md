# UI Route Ownership

Status:      ACTIVE
as_of:       2026-08-26T12:31:47-04:00
Measured at: efcc51365 / not measured

| Route family | Owner | Initial mode |
|---|---|---|
| `/control-plane/agents`, `/control-plane/workflows` | R22 | side-by-side preview |
| `/control-plane/research`, `/control-plane/data`, `/control-plane/identity`, `/control-plane/notifications` | R23 | side-by-side preview |
| `/control-plane/learning`, `/control-plane/maturity`, `/control-plane/audit` | R24 | side-by-side preview |
| shell, navigation, shared components, API registration | Integrator | feature-flagged |

Existing production routes remain untouched until parity, audit, and rollback gates pass.
