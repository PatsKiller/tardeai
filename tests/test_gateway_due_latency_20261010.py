"""Gateway `coordination/due` latency (W0 re-run incident, 2026-10-10 ~17:14 ET).

Incident: the relay logged GET /due REFUSED `relay_gateway_unreachable` whenever 2-4 /due calls arrived together
(n8n fires the dispatcher, event-router, incident-router and digest-scheduler on the same `* * * * *` minute), and
the gateway journal showed BrokenPipeError in _send: the gateway answered after the relay's urlopen(timeout=5) gave
up. Measured on the served registry (619 rows) with a read-only copy of the ledger: one due call cost ~0.5 s of
CPU, 99% of it in lane_dispatch.forbidden_text_hits (the whole-word matcher rebuilt ~160 word-form sets and scanned
every form for compounds, for each of ~560 command texts, on every request), and the unit runs with
CPUQuota=20%, so one call took ~2.3 s wall and three or four concurrent calls (GIL-serialized) passed 5 s.

Fix (scripts/lib/lane_dispatch.py): the per-phrase word forms are built once per matcher, the compound test
splits the word instead of scanning every form, and results are memoized per text. The matcher is keyed on its
inputs, so the word-boundary mutation tests still mutate it. Nothing in compute_due or the gateway changed.

Here: (1) the new matcher against a verbatim copy of the old one, over every command text of the served registry
and a synthetic compound corpus; (2) DueResponse@v1 byte-equality, new matcher vs old, over many timestamps
including catch-up/retry windows and the DST fold, on a synthetic ledger; (3) a latency budget: three and four
concurrent due calls through the real gateway HTTP server on the served registry, cold matcher, < 2 s wall and a
CPU budget that keeps them under the relay's 5 s timeout at the unit's CPUQuota=20%.

Hermetic: tmp_path ledger, keys that are not live secrets, 127.0.0.1 port 0, repo config files read only.
"""
from __future__ import annotations

import functools
import hashlib
import hmac
import json
import random
import threading
import time
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from scripts import n8n_coordination_gateway as SRV
from scripts.lib import lane_dispatch as LD
from scripts.lib import n8n_coordination_gateway as G
from scripts.lib import n8n_due as D
from scripts.lib.n8n_coordination_ledger import CoordinationLedger, LedgerRunStore

ROOT = Path(__file__).resolve().parents[1]
REGISTRY = ROOT / "config" / "lane_registry.json"
KEY = b"dispatch-key-not-a-live-secret-0123456"
N8N = b"relay-key-not-a-live-secret-9876543210"
SHA = "a" * 40
INCIDENT_FILTER = ["n8n-incident-fanin", "incident-notifier"]
#: The four workflows that fire together each minute (docs/implementation/n8n-maturity/workflows/*.json).
WORKFLOW_DUE = {
    "dispatcher": {"source": "schedule", "limit": 40},
    "event-router": {"source": "event", "limit": 40},
    "incident-router": {"source": "schedule", "limit": 40, "lane_filter": INCIDENT_FILTER},
    "digest-scheduler": {"source": "digest", "limit": 40},
}
#: scripts/n8n_run_relay.py Relay._transport urlopen(timeout=5); the unit's CPUQuota=20%.
RELAY_TIMEOUT_S = 5.0
UNIT_CPU_QUOTA = 0.20


# ── the matcher before 2026-10-10, verbatim (reference) ─────────────────────────────────────────────

def _ref_compound_hit(word: str, forms: frozenset) -> bool:
    for f in forms:
        if len(f) < 3 or len(word) <= len(f):
            continue
        if word.startswith(f) and word[len(f):] in LD.COMPOUND_PARTNERS:
            return True
        if word.endswith(f) and word[: -len(f)] in LD.COMPOUND_PARTNERS:
            return True
    return False


def _ref_forbidden_text_hits(text: str) -> list:
    words = LD._words(text or "")
    if not words:
        return []
    squashed = "".join(words)
    hits: list = []
    for tok, phrase in LD._PHRASES:
        last = LD._word_forms(phrase[-1])
        joined = LD._word_forms("".join(phrase))
        n = len(phrase)
        found = any(w in joined or _ref_compound_hit(w, joined) for w in words)
        if not found and n > 1:
            found = any(tuple(words[i:i + n - 1]) == phrase[:-1] and words[i + n - 1] in last
                        for i in range(len(words) - n + 1))
        if found and tok not in hits:
            hits.append(tok)
    for tok, sub in LD._SCRIPT_SUBSTRINGS:
        if sub in squashed and tok not in hits:
            hits.append(tok)
    for sub in LD.DISTINCTIVE_SUBSTRINGS:
        if sub in squashed and sub not in hits:
            hits.append(sub)
    return hits


def _registry_rows() -> list:
    return json.loads(REGISTRY.read_text(encoding="utf-8"))["lanes"]


def _synthetic_texts(seed: int = 20261010, n_random: int = 1500) -> list:
    """Compounds (form+partner, partner+form, with and without separators) for every phrase, plus random glue."""
    rng = random.Random(seed)
    partners = sorted(LD.COMPOUND_PARTNERS)
    out = []
    for _tok, phrase in LD._PHRASES:
        forms = sorted(LD._word_forms("".join(phrase)))
        for f in rng.sample(forms, min(4, len(forms))):
            p = rng.choice(partners)
            out += [f + p, p + f, f"{f}_{p}", f"scripts/{p}{f}.py --x", f"re{f}", f"{f}lights", f[:2] + p,
                    " ".join(phrase), "_".join(phrase) + ".py", "".join(phrase) + p]
    alphabet = sorted({c for tok, _ in LD._PHRASES for c in tok if c.isalnum()}) + ["_", "-", "/", " ", "."]
    for _ in range(n_random):
        pieces = [rng.choice(partners + [t for t, _ in LD._PHRASES] + ["x", "topic", "redeploy", "recorder"])
                  for _ in range(rng.randint(1, 4))]
        glue = "".join(rng.choice(["", "_", " ", "-", "/"]) + p for p in pieces)
        noise = "".join(rng.choice(alphabet) for _ in range(rng.randint(0, 6)))
        out.append((glue + noise).lower())
    return out


# ── (1) matcher equivalence ─────────────────────────────────────────────────────────────────────────

def test_matcher_equals_reference_on_every_served_registry_text():
    texts = sorted({t for row in _registry_rows() for _f, t in LD._command_fields(row)})
    assert len(texts) > 1000                                   # served-size registry, not a toy
    diffs = [(t, LD.forbidden_text_hits(t), _ref_forbidden_text_hits(t)) for t in texts
             if LD.forbidden_text_hits(t) != _ref_forbidden_text_hits(t)]
    assert diffs == []


def test_matcher_equals_reference_on_synthetic_compounds():
    texts = _synthetic_texts()
    hit = 0
    for t in texts:
        new, ref = LD.forbidden_text_hits(t), _ref_forbidden_text_hits(t)
        assert new == ref, t
        hit += bool(ref)
    assert hit > len(texts) // 4                               # the corpus exercises hits, not only clean text


def test_compound_hit_and_candidates_equal_the_reference_loop():
    rng = random.Random(7)
    partners = sorted(LD.COMPOUND_PARTNERS)
    all_forms = sorted({f for _t, ph in LD._PHRASES for f in LD._word_forms("".join(ph))})
    for _ in range(4000):
        forms = frozenset(rng.sample(all_forms, rng.randint(1, 30)))
        f = rng.choice(sorted(forms))
        p = rng.choice(partners)
        word = rng.choice([f + p, p + f, f, p, f[:-1] + p, p + f[1:], f + p + "x", "ab" + f, rng.choice(all_forms)])
        ref = _ref_compound_hit(word, forms)
        assert LD._compound_hit(word, forms) is ref, (word, sorted(forms))
        assert (not forms.isdisjoint(LD._compound_candidates(word, LD.COMPOUND_PARTNERS))) is ref, word


def test_matcher_returns_a_fresh_list_and_follows_its_inputs(monkeypatch):
    a = LD.forbidden_text_hits("scripts/liveorders.py")
    a.append("mutated")
    assert LD.forbidden_text_hits("scripts/liveorders.py") == _ref_forbidden_text_hits("scripts/liveorders.py")
    assert LD.forbidden_text_hits("liveorders")
    monkeypatch.setattr(LD, "COMPOUND_PARTNERS", frozenset())   # a replaced input builds a fresh matcher
    assert not LD.forbidden_text_hits("liveorders")
    monkeypatch.undo()
    assert LD.forbidden_text_hits("liveorders")


def test_dispatch_eligibility_equals_reference_on_every_served_row(monkeypatch):
    rows = _registry_rows()
    new = [LD.dispatch_eligible(r) for r in rows]
    monkeypatch.setattr(LD, "forbidden_text_hits", _ref_forbidden_text_hits)
    assert [LD.dispatch_eligible(r) for r in rows] == new


# ── (2) DueResponse@v1 byte-equality, new matcher vs reference ──────────────────────────────────────

BASE = datetime(2026, 10, 9, 13, 0, tzinfo=timezone.utc)
_FINISHED = ("RUN_DONE", "RUN_FAILED", "RUN_TIMEOUT", "RUN_SKIPPED_LOCK", "RUN_REFUSED")


def _seed_ledger(path: Path, rows, entries, policies) -> LedgerRunStore:
    """A ledger whose runs cover the due items of a day at mixed outcomes: done, failed (retryable or not),
    timed out, still requested / running, and a second attempt — so later timestamps see RETRY_DUE, RETRY_WAIT,
    IN_FLIGHT, DONE, DEAD_LETTER and catch-up slots."""
    ledger = CoordinationLedger(path)
    store = LedgerRunStore(ledger)
    conn = ledger._conn
    seen = set()
    for step in range(0, 24 * 60, 37):
        now = BASE + timedelta(minutes=step)
        due = D.compute_due(rows, entries, policies, store, now, limit=100)
        for i, item in enumerate(due["items"]):
            key = item["idempotency_key"]
            if key in seen:
                continue
            seen.add(key)
            h = int(hashlib.sha256(key.encode()).hexdigest(), 16)
            if h % 5 == 0:
                continue                                       # left un-requested: a catch-up / MISSED slot later
            state = ("REQUESTED", "RUNNING", *_FINISHED)[h % 7]
            finished = (now + timedelta(minutes=h % 9)).isoformat() if state in _FINISHED else None
            exit_code = {"RUN_DONE": 0, "RUN_FAILED": (1, 2, 75)[h % 3], "RUN_TIMEOUT": None}.get(state)
            conn.execute(
                "INSERT INTO runs (run_id, lane_id, mode, state, requested_at, finished_at, exit_code, slot_key,"
                ' attempt, "class", priority) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
                (key, item["lane_id"], item["mode"], state, now.isoformat(), finished, exit_code,
                 key.rsplit(":a", 1)[0], item["attempt"], None, item["priority"]))
    return store


def _stamps() -> list:
    out = [BASE + timedelta(minutes=m, seconds=(m * 13) % 60) for m in range(0, 36 * 60, 23)]   # 36 h, odd seconds
    out += [BASE + timedelta(hours=h) for h in (2, 6, 12, 26, 49, 97)]                          # widening catch-up
    fold = datetime(2026, 11, 1, 5, 0, tzinfo=timezone.utc)                                      # 01:00 EDT -> EST
    out += [fold + timedelta(minutes=m) for m in range(0, 150, 10)]
    return out


def test_due_responses_are_byte_identical_with_the_reference_matcher(tmp_path, monkeypatch):
    src = D.file_sources()                                     # the served registry / allowlist / policies
    rows, rsha = src.load_registry()
    entries, asha = src.load_allowlist()
    policies, psha = src.load_policies()
    store = _seed_ledger(tmp_path / "ledger.sqlite", rows, entries, policies)
    shapes = [WORKFLOW_DUE["dispatcher"], WORKFLOW_DUE["incident-router"], {"source": "schedule", "limit": 3},
              WORKFLOW_DUE["event-router"]]

    def run_all():
        out = []
        for t in _stamps():
            for s in shapes:
                out.append(json.dumps(D.compute_due(rows, entries, policies, store, t, source=s["source"],
                                                    lane_filter=s.get("lane_filter"), limit=s["limit"],
                                                    registry_sha=rsha, allowlist_sha=asha, policies_sha=psha),
                                      sort_keys=True))
        return out

    new = run_all()
    monkeypatch.setattr(LD, "forbidden_text_hits", functools.cache(_ref_forbidden_text_hits))
    ref = run_all()
    assert len(new) == len(ref) > 400
    assert [i for i, (a, b) in enumerate(zip(new, ref)) if a != b] == []
    docs = [json.loads(x) for x in new]
    states = {s for d in docs for s, c in d["counts"].items() if c}
    assert sum(len(d["items"]) for d in docs) > 100
    assert {"DUE", "DONE", "IN_FLIGHT", "MISSED"} <= states, states       # the windows are exercised
    assert states & {"RETRY_DUE", "RETRY_WAIT", "DEAD_LETTER"}, states


# ── (3) latency budget through the real gateway HTTP server ─────────────────────────────────────────

_NONCE = [0]


def _body(req: dict) -> bytes:
    _NONCE[0] += 1
    now = time.time()
    claim = {"v": 1, "caller_id": "n8n-relay", "project": "trade-ai", "iat": now, "exp": now + 120,
             "nonce": f"nonce-latency-{_NONCE[0]}-{now}", "scope": G.SCOPE_READ}
    sig = hmac.new(N8N, G.canonical(claim), hashlib.sha256).hexdigest()
    return json.dumps({"claim": claim, "signature": sig, "route": "coordination/due", "operation": "due",
                       **req}).encode()


@pytest.fixture
def gateway(tmp_path):
    httpd = SRV.serve("127.0.0.1", 0, key=KEY, expected_origin_sha=SHA, ledger_path=tmp_path / "ledger.sqlite",
                      n8n_key=N8N)                             # default registry / allowlist / policies = served
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield httpd.server_address[1]
    httpd.shutdown()
    httpd.server_close()
    httpd.coordination_ledger.close()


def _burst(port: int, names: list) -> tuple[float, float, dict]:
    results: dict = {}

    def call(name):
        req = urllib.request.Request(f"http://127.0.0.1:{port}/v1/coordination", data=_body(WORKFLOW_DUE[name]),
                                     method="POST", headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=30) as resp:  # hang guard only
            results[name] = (resp.status, json.loads(resp.read()))

    threads = [threading.Thread(target=call, args=(n,)) for n in names]
    cpu0, t0 = time.process_time(), time.perf_counter()
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    return time.perf_counter() - t0, time.process_time() - cpu0, results


@pytest.mark.parametrize("names", [["event-router", "incident-router", "digest-scheduler"], list(WORKFLOW_DUE)])
def test_concurrent_due_meets_the_latency_budget_cold(gateway, names):
    LD._matcher.cache_clear()                                  # cold: the first minute after a gateway restart
    wall, cpu, results = _burst(gateway, names)
    print(f"DUE_LATENCY n={len(names)} wall_s={wall:.3f} cpu_s={cpu:.3f}")
    assert sorted(results) == sorted(names)
    for name, (status, body) in results.items():
        assert status == 200 and body["schema"] == "DueResponse@v1" and body["ok"] is True, (name, body)
        assert body["source"] == WORKFLOW_DUE[name]["source"]
    assert wall < 2.0, wall
    # CPU, not wall, is what the unit's CPUQuota=20% stretches: keep the burst inside the relay timeout there
    # with 2x headroom. Before the fix this burst cost ~0.7-1.6 s of CPU (3.4-8 s at the quota).
    assert cpu / UNIT_CPU_QUOTA < RELAY_TIMEOUT_S / 2, cpu
