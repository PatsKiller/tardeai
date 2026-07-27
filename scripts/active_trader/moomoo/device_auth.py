"""Stage 5 — ONE-TIME Moomoo OpenD device authorization (console=1, PTY).

OpenD only accepts the SMS `input_phone_verify_code` command via its interactive
console (a real terminal), so this helper runs OpenD inside a pseudo-terminal, waits
for the phone-verify prompt (Moomoo sends the SMS), then reads the operator's code
from `$RUNTIME/verify_code` (0600, written out-of-band — never on a command line or in
logs) and types it into the console. On success the device becomes trusted and the
PERSISTENT runtime reverts to console=0.

console=1 here is a documented one-time deviation from the console=0 runtime ruling,
solely for the operator-present device-authorization ceremony.
"""
from __future__ import annotations

import os
import pty
import select
import sys
import termios
import time
import tty
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from active_trader.moomoo import secret_render


def _runtime() -> Path:
    base = os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")
    return Path(base) / "trade-ai-lab/moomoo"


def main() -> int:
    rt = _runtime()
    status = rt / "device_auth_status"
    code_file = rt / "verify_code"
    console_out = rt / "device_auth.console"
    status.write_text("STARTING")

    secrets = secret_render.load_data_secrets()
    cfg = secret_render.render_opend_config(secrets, console=1)
    opend = Path.home() / ".local/opt/trade-ai-lab/moomoo/opend/current/OpenD"

    pid, fd = pty.fork()
    if pid == 0:  # child → OpenD in the PTY
        os.chdir(str(opend.parent))
        os.execv(str(opend), [str(opend), f"-cfg_file={cfg}"])
        os._exit(127)

    # parent: make the master raw so we control exactly what OpenD's line
    # discipline receives (avoid ICRNL surprises); type the command char-by-char.
    cfh = open(console_out, "a")
    buf = ""
    prompted = False
    submitted = False
    result = "TIMEOUT"
    deadline = time.time() + 300
    try:
        while time.time() < deadline:
            r, _, _ = select.select([fd], [], [], 1.0)
            if r:
                try:
                    chunk = os.read(fd, 4096).decode(errors="ignore")
                except OSError:
                    break
                if not chunk:
                    break
                buf += chunk
                cfh.write(chunk); cfh.flush()
                low = buf.lower()
                if not prompted and "input_phone_verify_code" in low:
                    prompted = True
                    status.write_text("AWAITING_CODE")
                comp = low.replace("_", "").replace(" ", "")
                if "loginissuccessful" in comp or "loginsuccess" in comp or "loginsucc" in comp:
                    result = "LOGIN_OK"
                    break
                if submitted and ("invalid" in low or "incorrect" in low or "expired" in low
                                  or ("verification code" in low and "err" in low)):
                    result = "INVALID_CODE"
                    break
                if "password does not match" in low or "don't match" in low:
                    result = "PASSWORD_MISMATCH"
                    break
                if "has exited" in low:
                    result = "EXITED_AFTER_SUBMIT" if submitted else "OPEND_EXITED"
                    break
            if prompted and not submitted and code_file.exists():
                code = code_file.read_text().strip()
                if code.isdigit() and 4 <= len(code) <= 8:
                    cmd = f"input_phone_verify_code -code={code}"
                    for ch in cmd:                       # type it, char by char
                        os.write(fd, ch.encode())
                        time.sleep(0.01)
                    os.write(fd, b"\n")                  # single Enter
                    submitted = True
                    status.write_text("CODE_SUBMITTED")
                    cfh.write(f"\n[HELPER submitted input_phone_verify_code -code=<{len(code)}digits>]\n")
                    cfh.flush()
                    try:
                        with open(code_file, "r+b") as f:
                            f.write(b"\0" * len(code))
                        code_file.unlink()
                    except Exception:
                        pass
        status.write_text(result)
        if result == "LOGIN_OK":
            (rt / "opend.pid").write_text(str(pid))       # leave OpenD running (authenticated)
            print("DEVICE_AUTH: LOGIN_OK")
            return 0
        try:
            os.kill(pid, 15); time.sleep(3); os.kill(pid, 9)
        except ProcessLookupError:
            pass
        print(f"DEVICE_AUTH: {result}")
        return 0
    finally:
        try:
            os.close(fd)
        except OSError:
            pass


if __name__ == "__main__":
    raise SystemExit(main())
