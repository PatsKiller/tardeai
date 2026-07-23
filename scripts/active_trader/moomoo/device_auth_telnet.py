"""Stage 5 — ONE-TIME Moomoo OpenD device authorization via loopback Telnet.

The documented headless method for submitting the SMS verify code: connect to OpenD's
loopback telnet port and send `input_phone_verify_code -code=NNNNNN`. OpenD runs with
console=0 (background) but a loopback-only telnet port opened solely for this one-time
operator-present ceremony; the persistent runtime reverts to no telnet.

Flow: render config (console=0 + telnet 127.0.0.1:22222) → start OpenD → OpenD requests
the SMS → operator provides the code via `$RUNTIME/verify_code` (0600) → this helper
sends the telnet command → confirm login → leave OpenD authenticated.

The code is read from a file (never a command line / never logged).
"""
from __future__ import annotations

import os
import socket
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from active_trader.moomoo import secret_render

TELNET_PORT = 22222


def _runtime() -> Path:
    base = os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")
    return Path(base) / "trade-ai-lab/moomoo"


def _latest_log(rt: Path) -> Path | None:
    logs = sorted(rt.glob("log/**/*.log"), key=lambda p: p.stat().st_mtime if p.exists() else 0)
    return logs[-1] if logs else None


def _log_says(rt: Path, *needles: str) -> str | None:
    lg = _latest_log(rt)
    if not lg:
        return None
    txt = lg.read_text(errors="ignore").lower()
    for n in needles:
        if n in txt:
            return n
    return None


def main() -> int:
    rt = _runtime()
    status = rt / "device_auth_status"
    code_file = rt / "verify_code"
    status.write_text("STARTING")

    secrets = secret_render.load_data_secrets()
    cfg = secret_render.render_opend_config(secrets, console=0, telnet_port=TELNET_PORT)
    proc = secret_render.start_opend(cfg)
    (rt / "opend.pid").write_text(str(proc.pid))

    # wait for telnet port + verify prompt
    deadline = time.time() + 120
    prompted = False
    while time.time() < deadline:
        time.sleep(1)
        if _log_says(rt, "needphoneverifycode", "verification code required", "input_phone_verify_code"):
            prompted = True
            status.write_text("AWAITING_CODE")
            break
        if _log_says(rt, "password does not match", "don't match"):
            status.write_text("PASSWORD_MISMATCH")
            _stop(proc); return 0
        if _log_says(rt, "login is successful", "loginsuccess"):
            status.write_text("LOGIN_OK")           # already trusted (no SMS needed)
            print("DEVICE_AUTH: LOGIN_OK (no verification needed)")
            return 0
    if not prompted:
        status.write_text("NO_PROMPT")
        _stop(proc); return 0

    # wait for the operator's code, then send it over telnet
    deadline = time.time() + 300
    while time.time() < deadline:
        if code_file.exists():
            code = code_file.read_text().strip()
            if code.isdigit() and 4 <= len(code) <= 8:
                ok = _send_telnet(f"input_phone_verify_code -code={code}")
                status.write_text("CODE_SUBMITTED" if ok else "TELNET_SEND_FAILED")
                try:
                    with open(code_file, "r+b") as f:
                        f.write(b"\0" * len(code))
                    code_file.unlink()
                except Exception:
                    pass
                # confirm outcome from the log
                for _ in range(15):
                    time.sleep(2)
                    hit = _log_says(rt, "login is successful", "loginsuccess", "loginsucc",
                                    "invalid", "incorrect", "expired", "has exited")
                    if hit:
                        if "login" in hit and "succ" in hit.replace(" ", ""):
                            status.write_text("LOGIN_OK")
                            print("DEVICE_AUTH: LOGIN_OK")
                            return 0
                        if hit == "has exited":
                            status.write_text("EXITED_AFTER_SUBMIT")
                        else:
                            status.write_text("INVALID_CODE")
                        break
                # also probe the API as ground truth
                if _api_logged_in():
                    status.write_text("LOGIN_OK")
                    print("DEVICE_AUTH: LOGIN_OK (api-confirmed)")
                    return 0
                cur = status.read_text()
                if cur not in ("LOGIN_OK",):
                    _stop(proc)
                print(f"DEVICE_AUTH: {status.read_text()}")
                return 0
        time.sleep(1)
    status.write_text("TIMEOUT")
    _stop(proc)
    return 0


def _send_telnet(command: str) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", TELNET_PORT), timeout=8) as s:
            time.sleep(0.5)
            try:
                s.recv(4096)                          # drain any banner
            except socket.timeout:
                pass
            s.sendall((command + "\r\n").encode())
            time.sleep(1.0)
        return True
    except Exception:
        return False


def _api_logged_in() -> bool:
    try:
        from moomoo import OpenQuoteContext, RET_OK
        ctx = OpenQuoteContext(host="127.0.0.1", port=secret_render.API_PORT)
        r, _ = ctx.get_global_state()
        ctx.close()
        return r == RET_OK
    except Exception:
        return False


def _stop(proc):
    try:
        proc.terminate(); time.sleep(3); proc.kill()
    except Exception:
        pass


if __name__ == "__main__":
    raise SystemExit(main())
