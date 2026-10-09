# Installed n8n security audit

Status: OBSERVED_N8N
Owner: platform
as_of: 2026-10-08
Measured at: m8m-n8n, n8n 2.43.0 (see 06-n8n-container.json)

Command: `docker exec m8m-n8n n8n audit`, exit 0. Redacted stdout excerpts (no credentials or execution payloads):

```text
Postgres 16 is outside the supported range and receives compatibility support only. Upgrade to Postgres 17 or newer.
Acquiring database migration lock...
```

```json
{
  "features": {
    "communityPackagesEnabled": false,
    "versionNotificationsEnabled": false,
    "templatesEnabled": false,
    "publicApiEnabled": true
  },
  "telemetry": {"diagnosticsEnabled": false}
}
```

The Nodes Risk Report lists the HTTP Request and Code nodes, including inactive legacy/bench workflows. These capabilities are used by the scoped relay request and acceptance assertion; they need network confinement and reviewed node parameters. The instance excludes executeCommand, executeCommandTool, ssh, ftp, emailSend and emailSend variants, localFileTrigger, e2eTest and dynamicCredentialCheck.

The CLI initializes the database and acquires its migration lock; it is not a pure SQL SELECT. No workflow, credential or scheduler change was requested. The report did not assess owner MFA or DB role privileges; those are independently observed in `06-n8n-db.json` (MFA false; role superuser). Absence of those warnings is not a security pass.

Public API is enabled despite zero API keys. Propose `N8N_PUBLIC_API_DISABLED=true`; do not change it without the operator's config/runtime grant. Schedule periodic audit only under the scheduler grant, after verifying initialization has no pending migrations.
