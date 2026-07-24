// All /v3-next panels. Read-only: every action control is disabled and issues no
// write request. Unavailable values render explicitly (never fabricated).
import React from 'react';
import { fixtures, MOOMOO_STATUS, type WarningCategory } from '../fixtures/readApi';

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

type Decision = {
  symbol: string; verdict: 'GO' | 'WAIT' | 'NO_GO'; near_entry: boolean; price: number; entry: string;
  rvol: string; vwap: string; macd: string; momentum: string; volume: string;
  prime_state: string; fire_state: string; runner_state: string;
  res: number | null; rrs: number | null; confidence: string; freshness: string; reason: string;
};

const verdictLabel = (v: string) => (v === 'NO_GO' ? 'NO-GO' : v);

export function DecisionDeck() {
  const { data, warnings } = fixtures.decisions();
  const items = data.items as Decision[];
  const near = items.filter((d) => d.near_entry);
  const hidden = items.length - near.length;
  return (
    <section data-testid="decision-deck" aria-label="near-entry decisions" className="span-all">
      <h3>Near-Entry · GO / WAIT</h3>
      <Warnings items={warnings} />
      <table className="decision-rows">
        <thead><tr>
          <th>call</th><th>sym</th><th>price</th><th>entry — candle after reversal-break</th>
          <th>RVOL</th><th>VWAP</th><th>MACD</th><th>mom</th><th>vol</th><th>conf</th>
        </tr></thead>
        <tbody>
          {near.map((d) => (
            <tr key={d.symbol} className={`v-${d.verdict}`} data-testid={`decision-row-${d.symbol}`}>
              <td className="verdict">{verdictLabel(d.verdict)}</td>
              <td className="sym">{d.symbol}</td>
              <td className="mono">${d.price.toFixed(2)}</td>
              <td className="entry">{d.entry}</td>
              <td className="mono">{d.rvol}</td>
              <td className="mono">{d.vwap}</td>
              <td className="mono">{d.macd}</td>
              <td className="mono">{d.momentum}</td>
              <td className="mono">{d.volume}</td>
              <td className="conf">{d.confidence}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {near.length === 0 && <div data-testid="no-near-entry"><Unavailable label="no symbols near entry" /></div>}
      <div className="dc-foot" data-testid="decision-note">
        Surfacing near-entry names only{hidden > 0 ? ` · ${hidden} not near entry` : ''}. Level 2 / tape / OFI feed these calls — not displayed.
      </div>
    </section>
  );
}

export function SymbolDecision({ symbol }: { symbol: string }) {
  const { data } = fixtures.decisions();
  const d = (data.items as Decision[]).find((x) => x.symbol === symbol);
  return (
    <section data-testid="symbol-decision" aria-label={`decision ${symbol}`}>
      <h3>{symbol} · Decision</h3>
      {d ? (
        <div className={`decision-detail v-${d.verdict}`} data-testid={`decision-detail-${symbol}`}>
          <div className="dd-head">
            <span className="verdict">{verdictLabel(d.verdict)}</span>
            <span className="dd-entry">{d.entry}</span>
          </div>
          <div className="dd-signals">
            <span>RVOL <b>{d.rvol}</b></span><span>VWAP <b>{d.vwap}</b></span>
            <span>MACD <b>{d.macd}</b></span><span>mom <b>{d.momentum}</b></span>
            <span>vol <b>{d.volume}</b></span>
            <span>RES <b>{d.res ?? '—'}</b> / RRS <b>{d.rrs ?? '—'}</b></span>
            <span>{d.prime_state}·{d.fire_state}</span>
          </div>
          <div className="dc-reason">{d.reason}</div>
        </div>
      ) : <Unavailable label="no active decision for this symbol" />}
      <div data-testid="eligibility">eligibility: {fixtures.symbol(symbol).data.eligibility}</div>
    </section>
  );
}
