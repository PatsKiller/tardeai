"""Stage 5 — Moomoo credential wrapper and OpenD config renderer (DATA ONLY).

Compensating controls for MACHINE_ACCOUNT_REUSE_WITH_PROJECT_ALLOWLIST:
  * authenticates ONLY with the dedicated moomoo-data-stage5 token file;
  * pins the exact trade-ai-moomoo-data project ID (suffix-verified + recorded);
  * allowlists exactly three secret names; rejects extras, duplicates, other
    projects (including trade-ai-lab), sentinels, and empty values;
  * read-only: exposes no list/create/update/delete surface beyond the pinned read;
  * renders OpenD XML into tmpfs (0600) with login_pwd_md5 computed in-memory —
    the plaintext password never touches disk and never appears in argv/env of
    OpenD or logs;
  * refuses non-loopback binds; disables telnet/websocket/auto-grab.
"""
from __future__ import annotations

import hashlib
import json
import os
import stat
import subprocess
from pathlib import Path

TOKEN_PATH = Path.home() / ".openclaw/credentials/bws_moomoo_data_token"
PROJECT_NAME = "trade-ai-moomoo-data"
PROJECT_ID_SUFFIX = "00375f2c"          # recorded at credential bootstrap (GREEN)
FORBIDDEN_PROJECT_NAMES = ("trade-ai-lab", "trade-ai-prod")
ALLOWED_SECRETS = ("MOOMOO_DATA_LOGIN_ACCOUNT", "MOOMOO_DATA_LOGIN_PASSWORD",
                   "MOOMOO_DATA_TEST_SYMBOLS")
SENTINEL = "UNSET__OPERATOR_REQUIRED"
API_PORT = 11112                         # lab data port; 11111 reserved
LOOPBACK = "127.0.0.1"


class CredentialGateError(RuntimeError):
    pass


def _runtime_dir() -> Path:
    base = os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")
    d = Path(base) / "trade-ai-lab/moomoo"
    d.mkdir(parents=True, exist_ok=True)
    os.chmod(d, 0o700)
    return d


def _bws(args: list[str], token: str) -> str:
    out = subprocess.run(["bws", *args], capture_output=True, text=True,
                         env={**os.environ, "BWS_ACCESS_TOKEN": token}, timeout=30)
    if out.returncode != 0:
        raise CredentialGateError(f"bws {' '.join(args[:2])} failed (stderr redacted)")
    return out.stdout


def load_data_secrets(token_path: Path = TOKEN_PATH,
                      bws_call=None) -> dict:
    """Return exactly the three allowlisted secrets. Fail closed on anything else."""
    if not token_path.exists() or token_path.stat().st_size == 0:
        raise CredentialGateError("dedicated moomoo data token missing (BLOCKED_CREDENTIAL_GATE)")
    mode = stat.S_IMODE(token_path.stat().st_mode)
    if mode != 0o600:
        raise CredentialGateError(f"token file mode {oct(mode)} != 0600")
    token = token_path.read_text().strip()
    call = bws_call or (lambda args: _bws(args, token))

    projects = json.loads(call(["project", "list"]))
    names = [p.get("name") for p in projects]
    for forbidden in ("trade-ai-prod",):
        if forbidden in names:
            raise CredentialGateError(f"token unexpectedly exposes {forbidden}")
    matches = [p for p in projects if p.get("name") == PROJECT_NAME]
    if len(matches) != 1:
        raise CredentialGateError(f"expected exactly one {PROJECT_NAME} project, saw {len(matches)}")
    project_id = matches[0]["id"]
    if not project_id.endswith(PROJECT_ID_SUFFIX):
        raise CredentialGateError("project ID does not match the pinned bootstrap suffix")
    lab_ids = {p["id"] for p in projects if p.get("name") in FORBIDDEN_PROJECT_NAMES}

    rows = json.loads(call(["secret", "list", project_id]))
    secrets: dict[str, str] = {}
    for row in rows:
        key, pid = row.get("key"), row.get("projectId")
        if pid != project_id or pid in lab_ids:
            raise CredentialGateError(f"secret {key!r} belongs to a non-pinned project — rejected")
        if key not in ALLOWED_SECRETS:
            raise CredentialGateError(f"non-allowlisted secret name {key!r} in data project — rejected")
        if key in secrets:
            raise CredentialGateError(f"duplicate secret name {key!r}")
        value = row.get("value") or ""
        if not value.strip() or value.strip() == SENTINEL:
            raise CredentialGateError(f"secret {key!r} empty or sentinel — operator provisioning required")
        secrets[key] = value
    missing = [k for k in ALLOWED_SECRETS if k not in secrets]
    if missing:
        raise CredentialGateError(f"missing required secrets: {missing}")
    return secrets


def render_opend_config(secrets: dict, api_port: int = API_PORT,
                        ip: str = LOOPBACK, runtime_dir: Path | None = None,
                        console: int = 0, telnet_port: int | None = None) -> Path:
    """Render OpenD XML into tmpfs (0600). Password only as in-memory MD5.

    console defaults to 0 (background — the ruled runtime posture).
    telnet_port defaults to None (telnet OFF — the ruled runtime posture).
    console=1 / a loopback telnet_port are used ONLY for the one-time operator-present
    device-authorization ceremony, because OpenD accepts the SMS verify-code command
    solely over its interactive console or its (loopback) telnet interface — the
    documented headless method. The persistent runtime reverts to console=0 / no telnet.
    """
    if ip not in ("127.0.0.1", "::1", "localhost"):
        raise CredentialGateError(f"non-loopback OpenD bind {ip!r} refused")
    if console not in (0, 1):
        raise CredentialGateError("console must be 0 (runtime) or 1 (one-time device auth)")
    rt = runtime_dir or _runtime_dir()
    pwd_md5 = hashlib.md5(secrets["MOOMOO_DATA_LOGIN_PASSWORD"].encode()).hexdigest()
    log_dir = rt / "log"
    log_dir.mkdir(mode=0o700, exist_ok=True)
    telnet_xml = ""
    if telnet_port is not None:
        telnet_xml = f"\t<telnet_ip>127.0.0.1</telnet_ip>\n\t<telnet_port>{int(telnet_port)}</telnet_port>\n"
    xml = f"""<moomoo_opend>
\t<ip>{ip}</ip>
\t<api_port>{api_port}</api_port>
\t<login_account>{secrets['MOOMOO_DATA_LOGIN_ACCOUNT']}</login_account>
\t<login_pwd_md5>{pwd_md5}</login_pwd_md5>
\t<lang>en</lang>
\t<log_level>info</log_level>
\t<log_path>{log_dir}</log_path>
\t<push_proto_type>0</push_proto_type>
\t<console>{console}</console>
{telnet_xml}\t<price_reminder_push>0</price_reminder_push>
\t<auto_hold_quote_right>0</auto_hold_quote_right>
</moomoo_opend>
"""
    cfg = rt / "OpenD.xml"
    fd = os.open(cfg, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as fh:
        fh.write(xml)
    return cfg


def start_opend(cfg_path: Path, opend_dir: Path | None = None) -> subprocess.Popen:
    """Start command-line OpenD with the rendered config. No credential in argv."""
    base = opend_dir or Path.home() / ".local/opt/trade-ai-lab/moomoo/opend/current"
    binary = base / "OpenD"
    if not binary.exists():
        raise CredentialGateError("OpenD binary not installed")
    return subprocess.Popen([str(binary), f"-cfg_file={cfg_path}"], cwd=str(base),
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                            start_new_session=True)


def cleanup(runtime_dir: Path | None = None) -> None:
    rt = runtime_dir or _runtime_dir()
    cfg = rt / "OpenD.xml"
    if cfg.exists():
        try:
            size = cfg.stat().st_size
            with open(cfg, "r+b") as fh:      # truncate-in-place then unlink (tmpfs)
                fh.write(b"\0" * size)
        finally:
            cfg.unlink(missing_ok=True)


def test_symbols(secrets: dict, maximum: int = 2) -> list[str]:
    syms = [s.strip().upper() for s in
            secrets["MOOMOO_DATA_TEST_SYMBOLS"].replace(";", ",").split(",") if s.strip()]
    return syms[:maximum] or ["US.AAPL"]
