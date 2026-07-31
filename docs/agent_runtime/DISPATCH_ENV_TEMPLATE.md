# Dispatch environment template

Copy variables into your LAB host environment. Use Bitwarden for real DSN values.

| Variable | Purpose |
|---|---|
| `AGENT_RUNTIME_READ_API` | Set to `1` on portfolio server |
| `AGENT_RUNTIME_READ_DSN` | Read-only LAB role DSN |
| `AGENT_RUNTIME_OPERATOR_AUTH` | Set to `1` for dispatch |
| `AGENT_RUNTIME_QUEUE_MODULE` | `agent_runtime_dispatch_boot` |
| `AGENT_RUNTIME_DISPATCH_DSN` | LAB shadow writer DSN |
| `AGENT_RUNTIME_PROVIDER_MODULE` | `agent_runtime.providers.lab_watch_provider` |
| `AGENT_RUNTIME_ENABLED_FILE` | `/etc/tradeai/agent_runtime_enabled` |

Kill switch: `sudo install -m0644 /dev/null /etc/tradeai/agent_runtime_enabled`

Wave-1 timers: `systemctl enable --now tradeai-agent-runtime@{sentinel,darwin,iris,reflection,argus}.timer`

See [SHADOW_ACTIVATION_RUNBOOK.md](SHADOW_ACTIVATION_RUNBOOK.md).
