#!/usr/bin/env python3
"""pipeline_alert.py — Universal pipeline failure alerter.

Wraps any pipeline script. On non-zero exit: sends Telegram alert with
script name, error excerpt, and reply-to-retry command.

Usage in crontab:
    0 7 * * 1-5 cd $PROJ && $PY scripts/pipeline_alert.py sentiment_processor "$PY scripts/sentiment_processor.py"

Or call from Python:
    from pipeline_alert import run_with_alert
    run_with_alert("my_script", ["python3", "scripts/my_script.py"])
"""
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Load .env
_env_path = PROJECT_ROOT / ".env"
if _env_path.exists():
    for line in _env_path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            k, v = k.strip(), v.strip()
            if k and v and k not in os.environ:
                os.environ[k] = v


def _send_alert(message: str):
    """Send via telegram_alert.send_telegram chokepoint (no raw Bot API)."""
    try:
        scripts_dir = str(Path(__file__).resolve().parent)
        if scripts_dir not in sys.path:
            sys.path.insert(0, scripts_dir)
        from telegram_alert import send_telegram
        send_telegram(message)
        try:
            from lib.comms import CommunicationEvent, publish_communication
            publish_communication(CommunicationEvent(
                direction="OUTBOUND", event_type="alert", message_class="ops",
                producer="pipeline_alert", subject_key="ops:pipeline_alert",
                retention_class="operational", severity="urgent",
                sanitized_body=message[:500], short_summary=message[:120],
            ))
        except Exception:
            # ALARM-DELIVERY-DECLARED: shadow ledger best-effort; never blocks operator alert
            pass
    except Exception:
        # ALARM-DELIVERY-DECLARED: shadow ledger best-effort; never blocks operator alert
        pass


def run_with_alert(pipeline_name: str, command: list, timeout: int = 600) -> int:
    """Run a command and send Telegram alert on failure. Returns exit code."""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log_path = PROJECT_ROOT / "logs" / f"{pipeline_name}.log"

    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=str(PROJECT_ROOT),
        )

        # Append to log
        with open(log_path, "a") as f:
            f.write(f"\n[{timestamp}] Exit: {result.returncode}\n")
            if result.stdout:
                f.write(result.stdout)
            if result.stderr:
                f.write(result.stderr)
            f.write("\n")

        if result.returncode != 0:
            error_tail = (result.stderr or result.stdout or "No output")[-300:]
            _send_alert(
                f"PIPELINE FAILURE: {pipeline_name}\n"
                f"Exit: {result.returncode} | {timestamp}\n\n"
                f"{error_tail}\n\n"
                f"Reply to retry:\n"
                f"  run {pipeline_name}\n"
                f"  status — system health"
            )

        # Print output for any downstream capture
        if result.stdout:
            print(result.stdout, end="")
        if result.stderr:
            print(result.stderr, end="", file=sys.stderr)

        return result.returncode

    except subprocess.TimeoutExpired:
        _send_alert(
            f"PIPELINE TIMEOUT: {pipeline_name}\n"
            f"Exceeded {timeout}s | {timestamp}\n\n"
            f"Reply: run {pipeline_name}"
        )
        return 124

    except Exception as e:
        _send_alert(
            f"PIPELINE CRASH: {pipeline_name}\n"
            f"Error: {str(e)[:200]} | {timestamp}\n\n"
            f"Reply: run {pipeline_name}"
        )
        return 1


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: pipeline_alert.py <pipeline_name> <command...>")
        sys.exit(1)

    name = sys.argv[1]
    cmd = sys.argv[2:]
    sys.exit(run_with_alert(name, cmd))
