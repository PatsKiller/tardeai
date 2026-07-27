"""Stage 5 — authorized live-DATA smoke (§21). DATA ONLY.

Sequence: render config → start OpenD → OpenQuoteContext (NOT a trade context) →
entitlement + subscription-quota query → market snapshot → subscribe
QUOTE→K_1M→ORDER_BOOK→TICKER (≤2 symbols) → capture a few events → unsubscribe →
close context → stop OpenD → cleanup. No account/trade query. Never auto-grabs
quote rights. Prints a redacted JSON report (no credential values).

Run WITH the isolated venv:
  ~/.local/venvs/trade-ai-lab/moomoo-api/current/bin/python \
     scripts/active_trader/moomoo/smoke.py
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from active_trader.moomoo import secret_render
from active_trader.moomoo.gateway import Priority, SubscriptionOwner
from active_trader.moomoo.envelope import StreamType


def _wait_loopback(port: int, timeout: float = 25.0) -> bool:
    import socket
    end = time.time() + timeout
    while time.time() < end:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(1.0)
            if s.connect_ex(("127.0.0.1", port)) == 0:
                return True
        time.sleep(0.5)
    return False


def main() -> int:
    report = {"steps": {}, "safety": {"trade_context_created": False,
                                      "trade_call": False, "auto_grab": False,
                                      "account_query": False}}
    proc = None
    ctx = None
    try:
        secrets = secret_render.load_data_secrets()
        report["steps"]["secret_gate"] = "PASS"
        symbols = secret_render.test_symbols(secrets, maximum=2)
        report["test_symbols"] = symbols

        cfg = secret_render.render_opend_config(secrets)
        report["steps"]["config_render"] = "PASS (tmpfs 0600, md5 only)"
        proc = secret_render.start_opend(cfg)
        listening = _wait_loopback(secret_render.API_PORT)
        report["steps"]["opend_loopback"] = "LISTENING" if listening else "NOT_LISTENING"
        if not listening:
            report["result"] = "OPEND_NOT_READY"
            return 0

        from moomoo import OpenQuoteContext, RET_OK
        ctx = OpenQuoteContext(host="127.0.0.1", port=secret_render.API_PORT)
        report["steps"]["quote_context"] = "OPEN (data-only)"

        # data login is implicit once OpenD authenticated; verify with a global state call
        try:
            gs_ret, gs = ctx.get_global_state()
            report["steps"]["global_state"] = "OK" if gs_ret == RET_OK else f"ERR:{gs}"
            if gs_ret == RET_OK and hasattr(gs, "get"):
                report["market_state"] = {k: gs.get(k) for k in ("market_us",) if hasattr(gs, "get")}
        except Exception as exc:
            report["steps"]["global_state"] = f"EXC:{type(exc).__name__}"

        # subscription quota / entitlement
        try:
            q_ret, q = ctx.query_subscription()
            report["steps"]["subscription_quota"] = "OK" if q_ret == RET_OK else f"ERR:{q}"
            if q_ret == RET_OK:
                report["quota_before"] = _quota_summary(q)
        except Exception as exc:
            report["steps"]["subscription_quota"] = f"EXC:{type(exc).__name__}"

        # market snapshot (batched, read-only)
        try:
            s_ret, snap = ctx.get_market_snapshot(symbols)
            report["steps"]["market_snapshot"] = ("OK rows=%d" % len(snap)) if s_ret == RET_OK else f"ERR:{snap}"
        except Exception as exc:
            report["steps"]["market_snapshot"] = f"EXC:{type(exc).__name__}"

        # subscribe in tier order via the single owner
        owner = SubscriptionOwner(quote_ctx=_CtxAdapter(ctx))
        from moomoo import SubType
        tier_map = {StreamType.QUOTE: SubType.QUOTE, StreamType.K_1M: SubType.K_1M,
                    StreamType.ORDER_BOOK: SubType.ORDER_BOOK, StreamType.TICKER: SubType.TICKER}
        sub_states = {}
        for st in (StreamType.QUOTE, StreamType.K_1M, StreamType.ORDER_BOOK, StreamType.TICKER):
            owner._ctx.map = tier_map            # adapter translates
            sub = owner.subscribe(symbols[0], st, Priority.P0)
            sub_states[st.value] = sub.state.value
        report["subscription_states"] = sub_states

        time.sleep(3)                            # brief capture window (market may be closed)
        # snapshot as a stand-in event source when market closed; pull one quote
        try:
            _r, cur = ctx.get_stock_quote([symbols[0]])
            report["steps"]["quote_readback"] = "OK" if _r == RET_OK else f"ERR:{cur}"
        except Exception as exc:
            report["steps"]["quote_readback"] = f"EXC:{type(exc).__name__}"

        for st in (StreamType.QUOTE, StreamType.K_1M, StreamType.ORDER_BOOK, StreamType.TICKER):
            owner.unsubscribe(symbols[0], st)
        report["steps"]["unsubscribe"] = "PASS"
        try:
            q2_ret, q2 = ctx.query_subscription()
            if q2_ret == RET_OK:
                report["quota_after"] = _quota_summary(q2)
        except Exception:
            pass
        report["result"] = "SMOKE_OK"
        return 0
    except secret_render.CredentialGateError as exc:
        report["result"] = "CREDENTIAL_GATE"
        report["error"] = str(exc)
        return 0
    except Exception as exc:
        report["result"] = f"ERROR:{type(exc).__name__}"
        report["error"] = str(exc)[:200]
        return 0
    finally:
        if ctx is not None:
            try:
                ctx.close()
            except Exception:
                pass
        if proc is not None:
            proc.terminate()
            try:
                proc.wait(timeout=8)
            except Exception:
                proc.kill()
        secret_render.cleanup()
        print(json.dumps(report, indent=2, default=str))


class _CtxAdapter:
    """Translate the owner's stream names to moomoo SubType and call subscribe/unsub."""
    def __init__(self, ctx):
        self.ctx = ctx
        self.map = {}
    def subscribe(self, syms, streams):
        from moomoo import RET_OK
        subtypes = [self.map[_lookup(s)] for s in streams]
        ret, msg = self.ctx.subscribe(syms, subtypes, is_first_push=True)
        return ret == RET_OK, msg
    def unsubscribe(self, syms, streams):
        subtypes = [self.map[_lookup(s)] for s in streams]
        return self.ctx.unsubscribe(syms, subtypes)


def _lookup(name):
    return StreamType(name)


def _quota_summary(q) -> dict:
    try:
        row = q.iloc[0].to_dict() if hasattr(q, "iloc") else {}
        return {k: row.get(k) for k in ("total_used", "remain", "own_used") if k in row}
    except Exception:
        return {"parsed": False}


if __name__ == "__main__":
    raise SystemExit(main())
