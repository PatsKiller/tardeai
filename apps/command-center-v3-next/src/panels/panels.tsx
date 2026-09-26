// /v3-next panels. Read-only by construction: action controls are disabled and
// issue no request. Fixture and unavailable values are explicit and never styled
// as live broker truth.
import React from 'react';
import { fixtures, MOOMOO_STATUS, type WarningCategory, type ScannerData, type ScannerTicker } from '../fixtures/readApi';

export function Unavailable({ label }: { label?: string }) {
  return <span data-testid="unavailable" className="at-unavailable">{label ?? 'UNAVAILABLE'}</span>;
}

export function Warnings({ items }: { items: { category: WarningCategory; detail: string }[] }) {
  if (!items.length) return null;
  return (
    <ul data-testid="warnings" aria-label="data warnings" className="at-warning">
      {items.map((warning, index) => <li key={`${warning.category}-${index}`}><b>{warning.category}</b>: {warning.detail}</li>)}
    </ul>
  );
}

export function ReadOnlyAction({ label, reason }: { label: string; reason?: string }) {
  return (
    <button type="button" disabled aria-disabled="true" data-testid={`action-${label}`}
      className="at-disabled-action" title={reason ?? 'read-only workspace: action is disabled'}>
      {label}
    </button>
  );
}

function Metric({ label, value, tone }: { label: string; value: React.ReactNode; tone?: string }) {
  return <div className="at-metric"><div className="at-label">{label}</div><strong className={tone}>{value}</strong></div>;
}

export function SessionStrip() {
  const { data } = fixtures.session();
  const items = [
    ['Mode', data.mode],
    ['Session', data.session_state],
    ['Accounts', data.selected_accounts.join(', ')],
    ['Authorization', data.authorization_short_hash],
    ['Daily loss cap', `$${data.risk_limits.max_daily_loss}`],
    ['Stage gate', data.stage_gate],
    ['Kill switch', data.kill_switch],
  ];
  return (
    <header data-testid="session-strip" role="banner" aria-label="session status" className="at-session">
      {items.map(([label, value]) => <div className="at-session__item" key={label}><div className="at-label">{label}</div><div className={`at-value ${label === 'Stage gate' ? 'at-value--amber' : label === 'Kill switch' ? 'at-value--red' : ''}`}>{value}</div></div>)}
    </header>
  );
}

export function MoomooBadge() {
  return (
    <div data-testid="moomoo-badge" role="status" aria-label="moomoo status" className="at-statusbar">
      {MOOMOO_STATUS.workspace_badges.map((badge) => (
        <span key={badge} data-testid={`moomoo-${badge}`} className={`at-chip ${badge === 'DATA_AGREEMENT_CLEARED' ? 'at-chip--green' : badge === 'SESSION_1_ARMED' ? 'at-chip--blue' : 'at-chip--red'}`}>{badge.replace(/_/g, ' ')}</span>
      ))}
      <span className="at-chip at-chip--amber">OBSERVATIONS {MOOMOO_STATUS.observation_sessions_completed}/{MOOMOO_STATUS.observation_sessions_required}</span>
      <span className="at-statusbar__note">Data-only observation · no trade context · no account query · no unlock</span>
    </div>
  );
}

export function PrimeQueue({ selectedSymbol, onSelect }: { selectedSymbol: string; onSelect: (symbol: string) => void }) {
  const { data, warnings } = fixtures.candidates();
  return (
    <section data-testid="prime-queue" aria-label="prime queue" className="at-panel">
      <div className="at-panel__header"><span className="at-panel__title">Prime Queue</span><span className="at-panel__meta">fixture candidates · read only</span></div>
      <div className="at-panel__body at-panel__body--flush">
        <div className="at-queue-row" aria-hidden="true" style={{ cursor: 'default', minHeight: 34 }}><span className="at-label">Symbol</span><span className="at-label">State</span><span className="at-label">Price</span><span className="at-label">RVOL</span><span className="at-label">Why</span></div>
        {data.items.map(candidate => {
          const selected = candidate.symbol === selectedSymbol;
          const tone = candidate.state === 'IN_SCOPE' ? 'at-state--good' : candidate.state === 'BLOCKED' ? 'at-state--bad' : 'at-state--warn';
          return <button key={candidate.symbol} data-testid={`candidate-${candidate.symbol}`} className="at-queue-row" aria-selected={selected} onClick={() => onSelect(candidate.symbol)}><span><span className="at-symbol">{candidate.symbol}</span><br /><span className="at-source">{candidate.company}</span></span><span className={`at-state ${tone}`}>{candidate.state}</span><span className="at-number">${candidate.price.toFixed(2)}</span><span className="at-number">{candidate.rvol ?? <Unavailable />}</span><span className="at-muted at-small">{candidate.reason}</span></button>;
        })}
        <div style={{ padding: '0 10px 10px' }}><Warnings items={warnings} /></div>
      </div>
    </section>
  );
}

export function SymbolWorkspace({ symbol }: { symbol: string }) {
  const { data, warnings } = fixtures.symbol(symbol);
  const technical = data.technical;
  return (
    <section data-testid="symbol-workspace" aria-label={`symbol ${symbol}`} className="at-panel">
      <div className="at-panel__header"><span className="at-panel__title">Symbol Workspace</span><span className="at-panel__meta">source: fixture · no live market claim</span></div>
      <div className="at-panel__body">
        <div className="at-symbol-head"><div><h2>{symbol}</h2><div className="at-symbol-head__meta">{data.identity.company} · {data.identity.instrument_type} · {data.eligibility}</div></div><div className="at-symbol-head__score"><div className="at-label">Prime score</div><strong>{technical.score ?? '—'}</strong></div></div>
        <div data-testid="chart" className="at-chart"><div className="at-chart__message"><strong>Chart projection unavailable</strong><span>The visual grid is a shell only. A chart will render after read-API quote parity and timestamp freshness are proven.</span></div></div>
        <div className="at-metrics"><Metric label="Price" value={`$${data.quote.price.toFixed(2)}`} /><Metric label="RVOL" value={technical.rvol ?? <Unavailable />} /><Metric label="RES" value={technical.res ?? <Unavailable />} /><Metric label="RRS" value={technical.rrs ?? <Unavailable />} /></div>
        <div className="at-metrics"><Metric label="Support" value={data.price_structure.support == null ? <Unavailable /> : `$${data.price_structure.support.toFixed(2)}`} /><Metric label="Resistance" value={data.price_structure.resistance == null ? <Unavailable /> : `$${data.price_structure.resistance.toFixed(2)}`} /><Metric label="Book" value={<span data-testid="level2"><Unavailable label="awaiting accepted Stage 5 evidence" /></span>} /><Metric label="Tape" value={<span data-testid="time-and-sales"><Unavailable label="awaiting accepted Stage 5 evidence" /></span>} /></div>
        <div className="at-small at-muted" style={{ marginTop: 9 }}><b style={{ color: 'var(--at-text)' }}>Eligibility reason:</b> {data.reason}</div>
        <Warnings items={warnings} />
      </div>
    </section>
  );
}

export function TicketPanels({ symbol }: { symbol: string }) {
  const { data, warnings } = fixtures.orders(symbol);
  const ticket = data.items[0];
  return (
    <section data-testid="tickets" aria-label="tickets" className="at-panel">
      <div className="at-panel__header"><span className="at-panel__title">Ticket Preview</span><span className="at-panel__meta">simulation fixture · zero writes</span></div>
      <div className="at-panel__body at-stack">
        <div data-testid="pretrade-ticket" className="at-ticket"><div className="at-ticket__head"><b>Pre-Trade Ticket</b><span className={`at-chip ${ticket.validation === 'PASS_FIXTURE' ? 'at-chip--green' : 'at-chip--red'}`}>{ticket.validation.replace(/_/g, ' ')}</span></div><div className="at-ticket__body"><div className="at-ticket-grid"><div className="at-ticket-field"><div className="at-label">Symbol / side</div><strong>{ticket.symbol} · {ticket.side}</strong></div><div className="at-ticket-field"><div className="at-label">Account</div><strong>{ticket.broker}/{ticket.account_label}</strong></div><div className="at-ticket-field"><div className="at-label">Quantity</div><strong>{ticket.quantity}</strong></div><div className="at-ticket-field"><div className="at-label">Limit</div><strong>{ticket.limit_price == null ? '—' : `$${ticket.limit_price.toFixed(2)}`}</strong></div></div><ReadOnlyAction label="stage" reason="session builder is preview-only and no authorization envelope exists" /></div></div>
        <div data-testid="working-order-ticket" className="at-ticket"><div className="at-ticket__head"><b>Working Order</b><span className="at-chip">NONE</span></div><div className="at-ticket__body at-muted at-small">No order is queued, submitted, acknowledged, or working.</div></div>
        <div data-testid="intrade-ticket" className="at-ticket"><div className="at-ticket__head"><b>In-Trade Controls</b><span className="at-chip at-chip--red">DISABLED</span></div><div className="at-ticket__body"><div className="at-muted at-small">Management controls remain visible for parity planning but cannot issue a request.</div><div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 7 }}><ReadOnlyAction label="sell-smart" reason="read-only workspace" /><ReadOnlyAction label="flatten" reason="read-only workspace" /></div></div></div>
        <Warnings items={warnings} />
      </div>
    </section>
  );
}

export function PnlPanel() {
  const { data, warnings } = fixtures.positions();
  return (
    <section data-testid="pnl-panel" aria-label="positions and P&L" className="at-panel">
      <div className="at-panel__header"><span className="at-panel__title">Open Positions & P&amp;L</span><span className="at-panel__meta">fixture projection</span></div>
      <div className="at-panel__body">{data.items.map(position => <div key={position.symbol} data-testid={`position-${position.symbol}`} className="at-ticket"><div className="at-ticket__body"><div className="at-symbol-head"><div><b className="at-symbol">{position.symbol}</b><div className="at-small at-muted">{position.broker} · {position.masked_account_id} · {position.shares} shares</div></div><div className="at-symbol-head__score"><div className="at-label">P&amp;L</div><strong>${Number(position.total_pnl).toFixed(2)}</strong></div></div><div className="at-metrics"><Metric label="Average entry" value={`$${position.average_entry.toFixed(2)}`} /><Metric label="Mark" value={`$${Number(position.mark).toFixed(2)}`} /><Metric label="RES" value={position.res} /><Metric label="RRS" value={position.rrs} /></div></div></div>)}<Warnings items={warnings} /></div>
    </section>
  );
}

function ListPanel({ testId, title, meta, children }: { testId: string; title: string; meta?: string; children: React.ReactNode }) {
  return <section data-testid={testId} className="at-panel"><div className="at-panel__header"><span className="at-panel__title">{title}</span>{meta && <span className="at-panel__meta">{meta}</span>}</div><div className="at-panel__body">{children}</div></section>;
}

export function AccountsPanel() {
  const { data, warnings } = fixtures.accounts();
  return <ListPanel testId="accounts-panel" title="Accounts" meta="masked identifiers only"><ul className="at-list">{data.items.map(account => <li key={account.account_label}><span><b>{account.broker}/{account.account_label}</b><br /><span className="at-source">{account.masked_account_id}</span></span><span><b>{account.environment}</b> · {account.status}<br /><span className="at-muted">eligible {String(account.active_trader_eligible)} · selected {String(account.selected)}</span></span></li>)}</ul><Warnings items={warnings} /></ListPanel>;
}

export function BrokersPanel() {
  const { data, warnings } = fixtures.brokers();
  return <ListPanel testId="brokers-panel" title="Brokers" meta="effective connector state"><ul className="at-list"><li><span>Alpaca</span><span>{data.alpaca.connector_state} · {data.alpaca.write_state}</span></li><li><span>Schwab</span><span>{data.schwab.connector_state} · {data.schwab.write_state}</span></li><li data-testid="moomoo-broker"><span>Moomoo</span><span>{data.moomoo.connector_state} · {data.moomoo.write_state}</span></li></ul><Warnings items={warnings} /></ListPanel>;
}

export function CapabilitiesPanel() {
  const { data } = fixtures.capabilities();
  return <ListPanel testId="capabilities-panel" title="Broker Capabilities"><ul className="at-list">{data.items.map((capability, index) => <li key={index}><span>{capability.broker}/{capability.account_label}</span><span><b>{capability.capability}</b><br /><span className="at-muted">{capability.effective_state}</span></span></li>)}</ul></ListPanel>;
}

export function RejectionsPanel() {
  const { data, warnings } = fixtures.rejections();
  return <ListPanel testId="rejections-panel" title="Rejections" meta="normalized + redacted"><ul className="at-list">{data.items.map((rejection, index) => <li key={index}><span>{rejection.broker} · {rejection.symbol}</span><span><b>{rejection.normalized_code}</b><br /><span className="at-muted">retry {String(rejection.retryable)} · operator {String(rejection.requires_operator)}</span></span></li>)}</ul><Warnings items={warnings} /></ListPanel>;
}

export function NotificationsPanel() {
  const { data } = fixtures.notifications();
  return <ListPanel testId="notifications-panel" title="Notifications"><ul className="at-list">{data.items.map((notification, index) => <li key={index}><span><b>{notification.severity}</b></span><span>{notification.title}<br /><span className="at-muted">{notification.status}</span></span></li>)}</ul><ReadOnlyAction label="acknowledge" reason="notification mutation is disabled in the read-only workspace" /></ListPanel>;
}

export function JournalPanel() {
  const { data, warnings } = fixtures.journal();
  return <ListPanel testId="journal-panel" title="Journal" meta="fixture event stream"><ul className="at-list">{data.items.map((event, index) => <li key={index}><span>{event.at} · {event.symbol}</span><span><b>{event.event_type}</b><br /><span className="at-source">{event.replay_segment_ref}</span></span></li>)}</ul><Warnings items={warnings} /></ListPanel>;
}

export function FeatureModal() {
  const { data } = fixtures.features();
  return <ListPanel testId="feature-modal" title="Feature Controls" meta="read only"><ul className="at-list">{data.items.map(flag => <li key={flag.flag_name}><span>{flag.flag_name}</span><span>prod <b>{flag.production_effective_mode}</b> · test {flag.test_effective_mode}</span></li>)}</ul><div className="at-small at-muted" style={{ marginTop: 8 }}>mutable via this UI: {String(data.mutable_via_this_api)}</div></ListPanel>;
}

export function ParityPanel() {
  const { data, warnings } = fixtures.parity();
  return <ListPanel testId="parity-panel" title="Parity / Status" meta={data.parity_state}><div className="at-small at-muted">{data.note}</div><div style={{ marginTop: 8 }}>{data.checks.map(check => <div className="at-parity-row" key={check.key}><span className={check.state === 'PASS' ? 'at-parity-pass' : 'at-parity-pending'}>{check.state}</span><span>{check.label}</span></div>)}</div><Warnings items={warnings} /></ListPanel>;
}

export function ObservationGatePanel() {
  return <ListPanel testId="observation-gate-panel" title="Stage 5 Observation Gate" meta="0 of 5 qualifying sessions"><div className="at-metrics"><Metric label="Session 1" value="ARMED" tone="at-state--warn" /><Metric label="Capture" value="07:00–10:05 ET" /><Metric label="Closeout" value="10:12 ET" /><Metric label="Stage 14" value="BLOCKED" tone="at-state--bad" /></div><div className="at-small at-muted" style={{ marginTop: 9 }}>Capture is bound to SHA <code>{MOOMOO_STATUS.capture_sha.slice(0, 12)}</code>. This UI branch does not modify the armed branch, timers, services, markers, or authorization state.</div></ListPanel>;
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
  // GO grouped first, then by RVOL descending (WAIT rows lead with the hottest names)
  const act = scanner.tickers
    .filter((t) => isGo(t) || isWait(t))
    .sort((a, b) => (isGo(a) ? 0 : 1) - (isGo(b) ? 0 : 1) || (_n(b.rvol) ?? 0) - (_n(a.rvol) ?? 0));
  const go = act.filter(isGo).length;
  return (
    <section data-testid="decision-deck" className="span-all" aria-label="actionable decisions">
      <h3>Actionable · GO {go} / WAIT {act.length - go} · VIX {scanner.vix ?? '—'} · {scanner.market_regime ?? '—'}</h3>
      {act.length === 0 ? <Unavailable label="no GO / WAIT names this run" /> : (
        <table className="decision-rows">
          <thead><tr>
            <th>call</th><th>sym</th><th>price</th><th>chg</th><th>gap</th><th>RVOL</th><th>vol</th><th>float</th><th>grd</th><th>dist→trig</th><th>catalyst</th>
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
                <td className="trig">{isGo(t)
                  ? <span className="trig-fired">fired</span>
                  : <span className="trig-na" title="scalp trigger (VWAP reclaim / candle after reversal-break) is intraday — Entry Desk layer, not carried by the discovery scan">n/a · intraday</span>}</td>
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
