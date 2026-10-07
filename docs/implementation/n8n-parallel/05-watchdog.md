# n8n lab watchdog

Dated 2026-10-07. The checker is local code. The timer is not installed.

## What a healthz 200 is

`scripts/n8n_lab_watchdog.py` GETs a URL, checks the status and a small body, and writes `N8nLabWatchdogReceipt@v1` by temp file and replace. HTTP 200 with `{"status":"ok"}` sets `ok` true. The receipt still says the check does not prove workers, queue, database, webhook, producer, or consumer. Those need their own probes. The request sends no `Authorization` header. A closed port, DNS failure, timeout, non-200, or unexpected body is a failure with `sends` false and `failure_state` `NO_SEND`. URLs with userinfo are redacted. A failed replace leaves the previous file. A stale `checked_at` is detectable without sending.

On 2026-10-07T01:46:08Z the lab `GET /healthz` returned `{"status":"ok"}`. That observation was not written to the persistent receipt path. The earlier `/tmp` receipt was removed. It is not a timer fire.

## Unit proposal

`config/systemd/user/tradeai-n8n-lab-watchdog.service` and `.timer` are marked PROPOSAL ONLY. They are not in the user systemd directory. `systemctl --user is-enabled tradeai-n8n-lab-watchdog.timer` returned `not-found`. The timer is every 5 minutes, outside the n8n process, with a 128M memory cap and a 10% CPU quota. Do not enable it without a production scheduler grant. Enabling it before this script is in the served tree would fail on a missing file, which is the intended closed failure, not a reason to enable it early.

## Host-failure limit

A probe on ms01 cannot see ms01 being entirely down. The receipt states that. A second host, or an external probe that does not depend on this machine, is a separate proposal and was not built.

## After a future enablement

Observe two natural fires on the served release and a reader that is not the watchdog process. Until then the schedule status is NOT_INSTALLED and the next fire does not exist.
