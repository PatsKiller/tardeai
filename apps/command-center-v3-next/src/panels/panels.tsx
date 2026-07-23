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
