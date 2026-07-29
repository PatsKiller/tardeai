# Sender Inventory

Source inventory was taken with repository grep plus the direct sender audit.

Current direct `sendMessage` endpoint literals:

- `scripts/telegram_transport.py` only

Central sender references:

- `send_telegram(` references found in 128 files.

Legacy direct endpoint centralization:

- Raw `https://api.telegram.org/.../sendMessage` literals were removed from application producers.
- Python legacy senders that still construct a low-level send URL now reference `telegram_transport.TELEGRAM_SEND_MESSAGE_API`.
- Shell senders `scripts/telegram_poller_watchdog.sh`, `scripts/morning_eval_check.sh`, and `scripts/cron_wrapper.sh` were changed to call `telegram_alert.send_telegram`.

Important residual risk:

- Several legacy Python producers still call `requests.post` or `urllib.request.Request` using the centralized transport constant. This removes hardcoded raw endpoints and enables static enforcement of one endpoint literal, but those call sites should be fully migrated to `publish_event()`/`send_telegram()` in a follow-up cleanup before declaring every producer semantically outbox-native.

Enforcement:

- `tests/test_telegram_notification_normalization.py::test_direct_telegram_sendmessage_guard` fails if a new direct `sendMessage` endpoint literal is introduced outside `scripts/telegram_transport.py`.
