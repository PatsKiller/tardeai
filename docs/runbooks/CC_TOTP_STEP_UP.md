# Command Center TOTP step-up — operator enrollment runbook

2026-10-16. Code: `scripts/lib/cc_totp.py`, `scripts/lib/cc_auth.py`, `scripts/cc_totp_enroll.py`.
Config: `config/cc_auth.yaml` → `cc_auth.step_up.totp`. Tests: `tests/test_cc_totp_step_up_20261016.py`.

**Operator only.** Agents never run enrollment, never open the secret file and never see a code
(AGENTS §0, §24.7). The only command an agent may run is `scripts/cc_totp_enroll.py --status`, which
checks file metadata and never opens the secret.

## What it does

The Command Center refuses the dangerous route classes in `step_up.routes` (orders, stops, Schwab
re-auth, credentials, risk controls). Before this change, every one of those requests was refused.

TOTP step-up lets you unlock **one action class** for **10 minutes** with a 6-digit authenticator code.
The unlock has these limits:

- **One login.** It is bound to your tailnet login, which is the `Tailscale-User-Login` header set by
  `tailscale serve` on the serve_proxy socket.
- **Command Center only.** It works only through `tailscale serve`. The service-token listener
  (127.0.0.1:7777, used by cron, agents and n8n) never satisfies step-up.
- **Schwab re-auth only, at first.** `totp.actions` lists the classes a code may unlock, and it starts as
  `[schwab_reauth]`. The order, stop and risk classes stay refused until you widen that list in a config
  PR.
- **One use per code.** A code works once. Replay protection records the last accepted time step and
  survives a restart.
- **Lockout.** 5 wrong or replayed codes within 5 minutes lock verification for 15 minutes. During the
  lockout even a correct code is refused. Every attempt is written to
  `~/.local/state/tradeai/cc_auth_decisions.jsonl` with the kind `step_up_verify`. The code itself is
  never written there.
- **Restart clears unlocks.** Unlocks live only in server memory, so a restart ends every unlock.

Step-up stays **off** until both of the following are true:

- `step_up.totp.enabled: true` is set in config;
- an activated secret file exists at `step_up.totp.secret_file`.

If either is missing, the routes refuse exactly as before ("step-up required — TOTP unlock not yet
enabled") and no code prompt appears.

## Enroll (once, on the host, in your own terminal)

1. Check the current state. This prints no secret.
   ```
   python3 scripts/cc_totp_enroll.py --status
   ```
2. Enroll. You need an interactive terminal: the CLI refuses when stdin or stdout is not a TTY.
   ```
   python3 scripts/cc_totp_enroll.py
   ```
   - The CLI writes `~/.config/tradeai/cc_totp_secret.json.pending` (mode 0600, in a 0700 directory,
     outside the repo).
   - It prints an `otpauth://` URI. If `qrencode` is installed (`sudo apt install qrencode`), it also
     draws a terminal QR code. The URI is passed to qrencode on stdin, never on the command line.
   - Scan the QR code, or type the secret into your authenticator: Google Authenticator, 1Password,
     Aegis, or any other TOTP app (SHA1, 6 digits, 30 s).
   - Do not screenshot it, paste it anywhere, or send it to an agent.
   - Enter the 6-digit code the app shows. Only a correct code activates enrollment. The CLI then writes
     the activated `~/.config/tradeai/cc_totp_secret.json` (0600) and removes the pending file. It also
     records the code's time step, so that same code can never be replayed on the web.
   - Three wrong codes leave the `.pending` file in place. Remove it with
     `shred -u ~/.config/tradeai/cc_totp_secret.json.pending` and start again.
3. Confirm the files. You should see the secret file `present, 0600, owned by you`.
   ```
   python3 scripts/cc_totp_enroll.py --status
   ```
4. Turn step-up on. This is a config PR, approved by you:
   - set `cc_auth.step_up.totp.enabled: true` in `config/cc_auth.yaml`;
   - promote the PR;
   - restart the Command Center.

   `python3 scripts/lib/cc_auth.py --describe` → `step_up_totp` then shows `enabled_in_config: true`.

## Use

1. Open **System → Schwab Reauth** and press **Request renewal URL**.
2. The page shows a **Step-up required** box. Enter the current code and press **Verify & retry**. The
   page unlocks `schwab_reauth` for 10 minutes and repeats the request.
3. **Submit & renew token** is covered by the same unlock. If the unlock has expired, the page asks for a
   new code.

You can query the unlock state at `GET /api/v2/auth/step-up/status?action=schwab_reauth`.

## Rotate, revoke, recover

| Goal | What to do |
| --- | --- |
| **Revoke all unlocks now** | Restart the Command Center. Unlocks are held in memory only. |
| **Turn step-up off** | Set `enabled: false`, or move the secret file aside. Either one restores the refuse-all behaviour on the next request; no restart is needed for the file move. |
| **Rotate the secret** | `mv ~/.config/tradeai/cc_totp_secret.json ~/.config/tradeai/cc_totp_secret.json.retired-$(date +%Y%m%d)`, then enroll again. Shred the retired file once the new one works. |
| **Lost phone** | Move the secret file aside, which disables step-up immediately. Then enroll a new device. |
| **Locked out by wrong codes** | Wait 15 minutes. The lockout is stored in `~/.local/state/tradeai/cc_totp_state.json` (0600). |
| **State file corrupt** | Verification fails closed with HTTP 503 and nothing is unlocked. Move the state file aside. The next verify creates a fresh one, and replay protection restarts from the next code. |

## Residual risk

A process running as the service user, or as root, can read the secret file. That level of access is a
host compromise, and the same residual risk already applies to the service token (see `cc_auth.py`).
The Schwab app control and the trading read-only lock remain the backstops. TOTP protects against
someone holding only a tailnet device or only a loopback socket.
