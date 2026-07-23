# Moomoo OpenD Configuration — Stage 5 (data-only)

Rendered by `secret_render.render_opend_config` into tmpfs
`$XDG_RUNTIME_DIR/trade-ai-lab/moomoo/OpenD.xml` at mode **0600**, immediately before
startup, and shredded on stop. The plaintext login password NEVER touches disk or argv:
only `login_pwd_md5` (computed in-memory) is written; OpenD is launched as
`OpenD -cfg_file=<tmpfs path>` (no credential in the process arguments).

## Effective settings (verified in the rendered XML and in the OpenD startup log)
```text
console = 0
ip / api_ip = 127.0.0.1          (loopback ONLY; 0.0.0.0/:: refused by the renderer)
api_port = 11112                 (lab data port; 11111 reserved for future prod topology)
lang = en
log_level = info
push_proto_type = 0
price_reminder_push = 0
auto_hold_quote_right = 0        (MANDATORY — never auto-grabs quote rights)
telnet = not enabled
WebSocket = not enabled
```
The OpenD log confirmed it consumed exactly these values (login_account shown, login_pwd_md5
masked, auto_hold_quote_right 0, api_ip 127.0.0.1, api_port 11112).

## Startup mechanics — PROVEN WORKING
OpenD started, bound its control plane, connected to Moomoo servers, and processed the
rendered config. The only failure was Moomoo rejecting the login credential value (see
MOOMOO_CREDENTIAL_REQUIREMENTS.md). On login failure OpenD self-exits; the wrapper's
cleanup shreds the tmpfs XML. Post-run: 0 OpenD processes, 0 listeners on 11111/11112.
