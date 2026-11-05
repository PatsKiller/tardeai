#!/usr/bin/env python3
"""OPERATOR-RUN: write ``~/.config/tradeai/release_train/github-app.json`` for the release train's GitHub App (D2).

ANCHOR: RELEASE_TRAIN_GITHUB_APP_CONFIG_20261023. Agents write and test this script; they never run it against the
real key (AGENTS §24.7: agents never read the App key). The operator runs it once at the host, from CURRENT:

    .venv/bin/python scripts/ops/release_train_github_app_config.py \\
        --app-id <app id> --repository PatsKiller/tardeai --dry-run      # then again without --dry-run

What it does, in order (docs/ops/RELEASE_TRAIN_GITHUB_APP.md §5a):

1. Reads the App private key locally (``github-app.pem``: a regular file owned by this user, mode 600; else refused)
   and signs a 9-minute RS256 JWT with ``iss`` = the client id or app id. The signer is the controller's own
   ``GitHubAppTokenMinter.jwt`` (scripts/lib/release_train_controller.py), not a copy.
2. ``GET /app/installations`` (JWT auth) and picks the one installation whose account login matches the repository
   owner. None, more than one, or a suspended one is refused.
3. Confirms repository access with ``GitHubAppTokenMinter.mint`` (``POST /app/installations/<id>/access_tokens``,
   narrowed to the one repository and the train's permission set) and ``GET /installation/repositories`` with that
   token. The token is dropped immediately and never printed, written or put in an exception.
4. Writes ``github-app.json`` atomically (temp file in the same directory, mode 600, fsync, rename) with exactly the
   keys the controller reads: ``app_id`` (int), optional ``client_id``, ``installation_id`` (int), ``repository``.
   An existing different file is archived beside it with a UTC suffix first, never deleted (§0 rule 6).

``--dry-run`` does steps 1-3 (read-only on GitHub; the verification token is minted and discarded) and prints what it
would write; it writes nothing. Output is a JSON summary with no key, JWT or token in it. Exit 0 = written (or would
be / unchanged), 2 = refused, with the reason on stderr.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import stat
import sys
import tempfile
import time
from pathlib import Path
from typing import Callable, Optional

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.lib import release_train_controller as T  # noqa: E402

SCHEMA = "ReleaseTrainGitHubAppConfigRun@v1"
REPO_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})/[A-Za-z0-9._-]{1,100}$")
VERIFY_ACTION = "app_config_verify"
MAX_PAGES = 10


class Refused(RuntimeError):
    """A reason to stop. Messages carry identifiers and HTTP statuses only, never the key, the JWT or a token."""


def _headers(bearer: str) -> dict:
    return {"Authorization": f"Bearer {bearer}", "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28"}


def _get_json(http: T.HttpFn, path: str, bearer: str, what: str):
    try:
        status, raw = http("GET", f"{T.GITHUB_API}{path}", _headers(bearer), None)
    except OSError as exc:
        raise Refused(f"{what}: network error {type(exc).__name__}") from None
    if status != 200:
        raise Refused(f"{what}: HTTP {status}")
    try:
        return json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        raise Refused(f"{what}: response unreadable") from None


def find_installation(http: T.HttpFn, jwt: str, owner: str) -> dict:
    """The single, unsuspended installation of this App on ``owner``'s account."""
    seen: list[dict] = []
    for page in range(1, MAX_PAGES + 1):
        batch = _get_json(http, f"/app/installations?per_page=100&page={page}", jwt, "GET /app/installations")
        if not isinstance(batch, list):
            raise Refused("GET /app/installations: expected a list")
        seen.extend(i for i in batch if isinstance(i, dict))
        if len(batch) < 100:
            break
    logins = sorted({str((i.get("account") or {}).get("login") or "?") for i in seen})
    mine = [i for i in seen if str((i.get("account") or {}).get("login") or "").lower() == owner.lower()]
    if not mine:
        raise Refused(f"the App has no installation on account {owner!r} (installed on: {logins or 'nothing'}); "
                      "install it on the repository first (App doc §3)")
    if len(mine) > 1:
        raise Refused(f"ambiguous: {len(mine)} installations on account {owner!r} "
                      f"(ids {sorted(i.get('id') for i in mine)})")
    inst = mine[0]
    if not isinstance(inst.get("id"), int) or isinstance(inst.get("id"), bool):
        raise Refused("installation id is not an integer")
    if inst.get("suspended_at"):
        raise Refused(f"installation {inst['id']} is suspended (since {inst['suspended_at']})")
    return inst


def verify_access(minter: T.GitHubAppTokenMinter, http: T.HttpFn, repository: str) -> dict:
    """Mint one narrowed installation token, list its repositories, drop the token. Returns non-secret facts."""
    try:
        token = minter.mint(VERIFY_ACTION)
    except T.AppTokenError as exc:
        raise Refused(f"installation token for {repository}: {exc}") from None
    try:
        doc = _get_json(http, "/installation/repositories?per_page=100", token.value,
                        "GET /installation/repositories")
    finally:
        expires_at, permissions = token.expires_at, dict(token.permissions)
        del token
    repos = doc.get("repositories") if isinstance(doc, dict) else None
    if not isinstance(repos, list):
        raise Refused("GET /installation/repositories: no repositories list")
    names = sorted(str(r.get("full_name")) for r in repos if isinstance(r, dict))
    if repository.lower() not in {n.lower() for n in names}:
        raise Refused(f"the installation token cannot see {repository} (it sees {names or 'nothing'})")
    return {"repositories_total_count": doc.get("total_count", len(names)), "repositories": names,
            "token_expires_at": expires_at, "token_permissions": permissions, "token_discarded": True}


def _archive_name(path: Path, clock: Callable[[], float]) -> Path:
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime(clock()))
    cand, n = path.with_name(f"{path.name}.{stamp}.archived"), 1
    while os.path.lexists(cand):
        n += 1
        cand = path.with_name(f"{path.name}.{stamp}.{n}.archived")
    return cand


def write_config(out: Path, cfg: dict, clock: Callable[[], float]) -> dict:
    """Atomic, mode 600. An existing different file is archived (renamed), never deleted."""
    data = (json.dumps(cfg, indent=2, sort_keys=True) + "\n").encode("utf-8")
    if not out.parent.is_dir():
        raise Refused(f"{out.parent} does not exist (App doc §5: install -d -m 700 it first)")
    archived = None
    if os.path.lexists(out):
        st = os.lstat(out)
        if not stat.S_ISREG(st.st_mode):
            raise Refused(f"{out} exists and is not a regular file (symlinks are refused)")
        with open(out, "rb") as fh:
            if fh.read() == data and (st.st_mode & 0o777) == 0o600:
                return {"result": "unchanged", "path": str(out), "archived": None}
    fd, tmp = tempfile.mkstemp(prefix=f".{out.name}.", suffix=".tmp", dir=str(out.parent))
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        if os.path.lexists(out):
            archived = _archive_name(out, clock)
            os.link(out, archived)  # the old bytes stay on disk under the archive name
        os.replace(tmp, out)
    except BaseException:
        if os.path.lexists(tmp):
            os.unlink(tmp)  # our own never-published temp file, not an archived artifact
        raise
    dfd = os.open(str(out.parent), os.O_RDONLY)
    try:
        os.fsync(dfd)
    finally:
        os.close(dfd)
    return {"result": "written", "path": str(out), "archived": str(archived) if archived else None}


def run(args: argparse.Namespace, *, http: Optional[T.HttpFn] = None,
        clock: Callable[[], float] = time.time) -> dict:
    repository = args.repository
    if not REPO_RE.match(repository):
        raise Refused(f"--repository must be owner/repo (got {repository!r})")
    if not str(args.app_id).isdigit() or int(args.app_id) <= 0:
        raise Refused("--app-id must be the App's positive integer id (GitHub -> Settings -> Developer settings)")
    app_id = int(args.app_id)
    iss = args.client_id or str(app_id)
    owner = repository.split("/")[0]
    key_path, out = Path(args.key_path).expanduser(), Path(args.out).expanduser()

    minter = T.GitHubAppTokenMinter(key_path=key_path, config_path=out, http=http, clock=clock)
    http = minter.http
    try:
        jwt = minter.jwt(iss)
    except T.AppTokenError as exc:
        raise Refused(str(exc)) from None
    try:
        inst = find_installation(http, jwt, owner)
    finally:
        del jwt

    cfg = {"app_id": app_id, "installation_id": int(inst["id"]), "repository": repository}
    if args.client_id:
        cfg["client_id"] = args.client_id
    # Verify with exactly the identifiers about to be written, before anything is written.
    minter.config = lambda: {"iss": iss, "installation_id": cfg["installation_id"], "repository": repository}
    verified = verify_access(minter, http, repository)

    summary = {
        "schema": SCHEMA,
        "dry_run": bool(args.dry_run),
        "config_path": str(out),
        "config": cfg,
        "installation": {"id": inst["id"], "account": (inst.get("account") or {}).get("login"),
                         "repository_selection": inst.get("repository_selection"),
                         "app_slug": inst.get("app_slug")},
        "verified": verified,
    }
    if args.dry_run:
        summary["write"] = {"result": "would_write", "path": str(out), "mode": "600"}
    else:
        summary["write"] = write_config(out, cfg, clock)
    return summary


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="OPERATOR-RUN: discover the release-train GitHub App installation, "
                                            "verify repository access and write github-app.json (mode 600).")
    p.add_argument("--app-id", required=True, help="GitHub -> Settings -> Developer settings -> GitHub Apps -> App ID")
    p.add_argument("--repository", required=True, help="owner/repo, e.g. PatsKiller/tardeai")
    p.add_argument("--client-id", default=None, help="optional; used as the JWT iss and written when given")
    p.add_argument("--dry-run", action="store_true", help="discover and verify, print, write nothing")
    p.add_argument("--key-path", default=str(T.APP_KEY_PATH), help=f"default {T.APP_KEY_PATH}")
    p.add_argument("--out", default=str(T.APP_CONFIG_PATH), help=f"default {T.APP_CONFIG_PATH}")
    return p


def main(argv: Optional[list[str]] = None, *, http: Optional[T.HttpFn] = None,
         clock: Callable[[], float] = time.time) -> int:
    args = build_parser().parse_args(argv)
    try:
        summary = run(args, http=http, clock=clock)
    except Refused as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
