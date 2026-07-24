// All /v3-next panels. Read-only: every action control is disabled and issues no
// write request. Unavailable values render explicitly (never fabricated).
import React from 'react';
import { fixtures, MOOMOO_STATUS, type WarningCategory, type ScannerData, type ScannerTicker } from '../fixtures/readApi';

export function Unavailable({ label }: { label?: string }) {
  return <span data-testid="unavailable" style={{ color: '#8a8a8a', fontStyle: 'italic' }}>{label ?? 'UNAVAILABLE'}</span>;
}

export function Warnings({ items }: { items: { category: WarningCategory; detail: string }[] }) {
  if (!items.length) return null;
  return (
    <ul data-testid="warnings" aria-label="data warnings">
      {items.map((w, i) => (<li key={i}><b>{w.category}</b>: {w.detail}</li>))}
    </ul>
  );
}

/** A read-only action button: always disabled, never fires a request. */
export function ReadOnlyAction({ label }: { label: string }) {
  return (
    <button type="button" disabled aria-disabled="true" data-testid={`action-${label}`}
      title="read-only workspace (Stage 6): actions are disabled">
      {label}
    </button>
  );
}

export function SessionStrip() {
  const { data, warnings } = fixtures.session();
  return (
    <header data-testid="session-strip" role="banner" aria-label="session status">
      <span>mode: <b>{data.mode}</b></span> · <span>2FA: {data.authorization_short_hash}</span> ·{' '}
      <span>accounts: {data.selected_accounts.join(', ')}</span> ·{' '}
      <span>daily-loss cap: {data.risk_limits.max_daily_loss}</span> ·{' '}
      <span>cutoff: {data.entry_cutoff}</span> ·{' '}
      <span data-testid="kill-switch">KILL: {data.kill_switch}</span>
      <Warnings items={warnings} />
    </header>
  );
}

export function MoomooBadge() {
  return (
    <div data-testid="moomoo-badge" role="status" aria-label="moomoo status">
      {MOOMOO_STATUS.workspace_badges.map((b) => (
        <span key={b} data-testid={`moomoo-${b}`} style={{ background: '#3a2f2f', padding: '2px 6px', marginRight: 4 }}>{b}</span>
      ))}
      {/* no green/live badge by construction */}
    </div>
  );
}

export function PrimeQueue() {
  const { data, warnings } = fixtures.candidates();
  return (
    <section data-testid="prime-queue" aria-label="prime queue">
      <h3>Prime Queue</h3>
      <Warnings items={warnings} />
      <table>
        <thead><tr><th>symbol</th><th>state</th><th>price</th><th>RVOL</th><th>float</th><th>book</th><th>tape</th></tr></thead>
        <tbody>
          {data.items.map((c) => (
            <tr key={c.symbol} data-testid={`candidate-${c.symbol}`}>
              <td>{c.symbol}</td><td>{c.state}</td><td>{c.price}</td>
              <td>{c.rvol ?? <Unavailable />}</td>
              <td>{c.float_shares ?? <Unavailable />}</td>
              <td>{c.book_state === 'UNAVAILABLE' ? <Unavailable /> : c.book_state}</td>
              <td>{c.tape_state === 'UNAVAILABLE' ? <Unavailable /> : c.tape_state}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}

export function SymbolWorkspace({ symbol }: { symbol: string }) {
  const { data, warnings } = fixtures.symbol(symbol);
  return (
    <section data-testid="symbol-workspace" aria-label={`symbol ${symbol}`}>
      <h3>{symbol}</h3>
      <div data-testid="chart"><b>Chart:</b> <Unavailable label="chart requires market-data stage" /></div>
      <div data-testid="level2"><b>Level 2:</b> <Unavailable label="L2 requires Moomoo data plane" /></div>
      <div data-testid="time-and-sales"><b>Time &amp; Sales:</b> <Unavailable label="tape requires Moomoo data plane" /></div>
      <div>eligibility: {data.eligibility}</div>
      <Warnings items={warnings} />
    </section>
  );
}

export function TicketPanels() {
  return (
    <section data-testid="tickets" aria-label="tickets">
      <div data-testid="pretrade-ticket"><h4>Pre-Trade Ticket</h4><Unavailable label="preview requires later stages" />
        <ReadOnlyAction label="stage" /></div>
      <div data-testid="working-order-ticket"><h4>Working-Order Ticket</h4><Unavailable /></div>
      <div data-testid="intrade-ticket"><h4>In-Trade Ticket</h4><Unavailable />
        <ReadOnlyAction label="sell-smart" /><ReadOnlyAction label="flatten" /></div>
    </section>
  );
}

export function PnlPanel() {
  const { data, warnings } = fixtures.positions();
  return (
    <section data-testid="pnl-panel" aria-label="positions and P&L">
      <h3>Open Positions &amp; P&amp;L</h3>
      <Warnings items={warnings} />
      {data.items.map((p) => (
        <div key={p.symbol} data-testid={`position-${p.symbol}`}>
          {p.symbol} · {p.masked_account_id} · shares {p.shares} · RES {p.res} / RRS {p.rrs} ·{' '}
          P&amp;L {p.total_pnl === 'UNAVAILABLE' ? <Unavailable /> : p.total_pnl}
        </div>
      ))}
    </section>
  );
}

export function AccountsPanel() {
  const { data, warnings } = fixtures.accounts();
  return (
    <section data-testid="accounts-panel" aria-label="accounts">
      <h3>Accounts</h3><Warnings items={warnings} />
      {data.items.map((a) => (
        <div key={a.account_label} data-testid={`account-${a.account_label}`}>
          {a.broker}/{a.account_label} · {a.masked_account_id} · {a.environment} · {a.status}
        </div>
      ))}
    </section>
  );
}

export function BrokersPanel() {
  const { data } = fixtures.brokers();
  return (
    <section data-testid="brokers-panel" aria-label="brokers">
      <h3>Brokers</h3>
      <div>alpaca: {data.alpaca.connector_state}</div>
      <div>schwab: {data.schwab.connector_state}</div>
      <div data-testid="moomoo-broker">moomoo: {data.moomoo.connector_state}</div>
      <div>excluded (v1): {data.excluded_from_active_trader_v1.join(', ')}</div>
    </section>
  );
}

export function CapabilitiesPanel() {
  const { data } = fixtures.capabilities();
  return (
    <section data-testid="capabilities-panel" aria-label="broker capabilities">
      <h3>Broker Capabilities</h3>
      {data.items.map((c, i) => (
        <div key={i}>{c.broker}/{c.account_label} · {c.capability} · <b>{c.effective_state}</b></div>
      ))}
    </section>
  );
}

export function RejectionsPanel() {
  const { data, warnings } = fixtures.rejections();
  return (
    <section data-testid="rejections-panel" aria-label="rejections">
      <h3>Rejections</h3><Warnings items={warnings} />
      {data.items.map((r, i) => (
        <div key={i}>{r.broker} · {r.normalized_code} · retry {String(r.retryable)} · {r.raw_message_redacted}</div>
      ))}
    </section>
  );
}

export function NotificationsPanel() {
  const { data } = fixtures.notifications();
  return (
    <section data-testid="notifications-panel" aria-label="notifications">
      <h3>Notifications</h3>
      {data.items.map((n, i) => (<div key={i}>[{n.severity}] {n.title} · {n.status}</div>))}
      {/* read-only: cannot ack/resolve/escalate */}
      <ReadOnlyAction label="acknowledge" />
    </section>
  );
}

export function JournalPanel() {
  const { data, warnings } = fixtures.journal();
  return (
    <section data-testid="journal-panel" aria-label="journal">
      <h3>Journal</h3><Warnings items={warnings} />
      {data.items.map((e, i) => (<div key={i}>{e.event_type} · {e.symbol} · {e.replay_segment_ref}</div>))}
    </section>
  );
}

export function FeatureModal() {
  const { data } = fixtures.features();
  return (
    <section data-testid="feature-modal" aria-label="feature controls (read-only)">
      <h3>Feature Controls (read-only)</h3>
      {data.items.map((f) => (
        <div key={f.flag_name}>{f.flag_name}: prod <b>{f.production_effective_mode}</b> / test {f.test_effective_mode}</div>
      ))}
      <div>mutable via this UI: {String(data.mutable_via_this_api)}</div>
    </section>
  );
}

export function ParityPanel() {
  const { data, warnings } = fixtures.parity();
  return (
    <section data-testid="parity-panel" aria-label="parity status">
      <h3>Parity / Status</h3>
      <div>state: {data.parity_state}</div><div>{data.note}</div>
      <Warnings items={warnings} />
    </section>
  );
}

/* ---- Decision surface (LIVE presents GO/WAIT/NO-GO, not charts/L2/tape) ---- */

const verdictLabel = (v: string) => (v === 'NO_GO' ? 'NO-GO' : v);
const _n = (v: unknown): number | null => {
  const n = typeof v === 'number' ? v : parseFloat(String(v ?? '').replace(/[,%×xX+]/g, ''));
  return isNaN(n) ? null : n;
};
const money = (v: unknown) => { const n = _n(v); return n == null ? '—' : `$${n.toFixed(2)}`; };
const pct = (v: unknown) => { const n = _n(v); return n == null ? '—' : `${n >= 0 ? '+' : ''}${n.toFixed(1)}%`; };
const rvolx = (v: unknown) => { const n = _n(v); return n == null ? '—' : `${n.toFixed(1)}×`; };
const volFmt = (v: unknown) => { const n = _n(v); if (n == null) return '—'; if (n >= 1e6) return `${(n / 1e6).toFixed(1)}M`; if (n >= 1e3) return `${(n / 1e3).toFixed(0)}K`; return String(n); };
const floatM = (v: unknown) => { const n = _n(v); return n == null ? '—' : `${n.toFixed(1)}M`; };
const isGo = (t: ScannerTicker) => String(t.decision).toUpperCase() === 'GO';
const isWait = (t: ScannerTicker) => /^WAIT/i.test(String(t.decision));
const vClass = (t: ScannerTicker) => (isGo(t) ? 'GO' : isWait(t) ? 'WAIT' : 'NO_GO');

export function DecisionDeck({ scanner }: { scanner: ScannerData | null | undefined }) {
  if (scanner === undefined)
    return (
      <section data-testid="decision-deck" className="span-all" aria-label="actionable decisions">
        <h3>Actionable · GO / WAIT</h3>
        <div className="dc-loading">loading live scan…</div>
      </section>
    );
  if (!scanner || !scanner.tickers?.length)
    return (
      <section data-testid="decision-deck" className="span-all" aria-label="actionable decisions">
        <h3>Actionable · GO / WAIT</h3>
        <Unavailable label="live scan unavailable — /api/v2/trade-ai/scanner" />
        <div className="dc-foot" data-testid="decision-note">Level 2 / tape feed the engine; not displayed.</div>
      </section>
    );
  const act = scanner.tickers
    .filter((t) => isGo(t) || isWait(t))
    .sort((a, b) => (isGo(a) ? 0 : 1) - (isGo(b) ? 0 : 1) || (_n(b.score) ?? 0) - (_n(a.score) ?? 0) || (_n(b.rvol) ?? 0) - (_n(a.rvol) ?? 0));
  const go = act.filter(isGo).length;
  return (
    <section data-testid="decision-deck" className="span-all" aria-label="actionable decisions">
      <h3>Actionable · GO {go} / WAIT {act.length - go} · VIX {scanner.vix ?? '—'} · {scanner.market_regime ?? '—'}</h3>
      {act.length === 0 ? <Unavailable label="no GO / WAIT names this run" /> : (
        <table className="decision-rows">
          <thead><tr>
            <th>call</th><th>sym</th><th>price</th><th>chg</th><th>gap</th><th>RVOL</th><th>vol</th><th>float</th><th>grd</th><th>catalyst</th>
          </tr></thead>
          <tbody>
            {act.map((t) => (
              <tr key={t.symbol} className={`v-${vClass(t)}`} data-testid={`decision-row-${t.symbol}`}>
                <td className="verdict">{isGo(t) ? 'GO' : 'WAIT'}</td>
                <td className="sym">{t.symbol}{t.not_tradeable ? <span className="tag">awareness</span> : null}</td>
                <td className="mono">{money(t.price)}</td>
                <td className={`mono ${(_n(t.change_pct) ?? 0) >= 0 ? 'pos' : 'neg'}`}>{pct(t.change_pct)}</td>
                <td className="mono">{pct(t.gap_pct)}</td>
                <td className="mono">{rvolx(t.rvol)}</td>
                <td className="mono">{volFmt(t.volume)}</td>
                <td className="mono">{floatM(t.float_m)}</td>
                <td className="grade">{t.grade ?? '—'}</td>
                <td className="cat" title={t.catalyst || t.critic_reasoning || ''}>{(t.catalyst || t.critic_reasoning || '—').slice(0, 72)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      <div className="dc-foot" data-testid="decision-note">
        Live · /api/v2/trade-ai/scanner{scanner.stale ? ' (stale)' : ''} {scanner.latest_run_label ?? ''} — awareness/discovery only; surfacing/copying never places, validates, or queues a trade. Entry timing (VWAP/MACD, candle after reversal-break) is the Entry Desk / intraday layer; L2/tape feed it, not displayed.
      </div>
    </section>
  );
}

export function SymbolDecision({ scanner, symbol }: { scanner: ScannerData | null | undefined; symbol: string }) {
  const t = scanner?.tickers?.find((x) => x.symbol === symbol);
  return (
    <section data-testid="symbol-decision" aria-label={`decision ${symbol || ''}`}>
      <h3>{symbol || 'Symbol'} · Decision</h3>
      {t ? (
        <div className={`decision-detail v-${vClass(t)}`} data-testid={`decision-detail-${symbol}`}>
          <div className="dd-head">
            <span className="verdict">{verdictLabel(vClass(t))}</span>
            <span className="dd-entry">{t.setup_class || t.operator_pill || ''}</span>
          </div>
          <div className="dd-signals">
            <span>price <b>{money(t.price)}</b></span><span>chg <b>{pct(t.change_pct)}</b></span>
            <span>gap <b>{pct(t.gap_pct)}</b></span><span>RVOL <b>{rvolx(t.rvol)}</b></span>
            <span>vol <b>{volFmt(t.volume)}</b></span><span>float <b>{floatM(t.float_m)}</b></span>
            <span>grade <b>{t.grade ?? '—'}</b></span><span>critic <b>{t.critic_verdict ?? '—'}</b></span>
          </div>
          <div className="dc-reason">{t.catalyst || t.critic_reasoning || '—'}</div>
        </div>
      ) : <Unavailable label={scanner === undefined ? 'loading…' : 'no live decision for this symbol'} />}
    </section>
  );
}
