import { useEffect, useMemo, useRef, useState } from 'react';
import type { ActiveTraderDataState, BrokerAccount, RoutingDraft, ScalpSignal } from './activeTrader.types';
import { MOCK_ACCOUNTS, MOCK_QUEUE, MOCK_SIGNAL } from './activeTrader.mock';
import './activeTrader.css';

type Props = {
  signals?: ScalpSignal[];              // undefined = loading; [] = empty live queue
  accounts?: BrokerAccount[];
  onOpenStrategies?: () => void;
  dataState?: ActiveTraderDataState;    // honest state from the API (LIVE_DATA/EMPTY_LIVE_QUEUE/DATA_STALE/API_UNAVAILABLE)
  actionableCount?: number;
  sourceSessionDate?: string | null;
  lastEventAt?: string | null;
  registryHash?: string | null;
  registryVersion?: string | null;
};

const usd = new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 0 });
const money2 = new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', minimumFractionDigits: 2 });

function Chip({ children, tone = 'context', title }: { children: React.ReactNode; tone?: 'pass' | 'fail' | 'context' | 'warning' | 'lane'; title?: string }) {
  return <span className={`at-chip at-chip--${tone}`} title={title}>{children}</span>;
}

const BANNER: Record<ActiveTraderDataState, { text: string; tone: 'pass' | 'warning' | 'fail' | 'context' }> = {
  LIVE_DATA: { text: 'LIVE DATA CONNECTED', tone: 'pass' },
  DATA_STALE: { text: 'DATA STALE', tone: 'warning' },
  EMPTY_LIVE_QUEUE: { text: 'LIVE QUEUE EMPTY', tone: 'context' },
  API_UNAVAILABLE: { text: 'API UNAVAILABLE', tone: 'fail' },
  REFERENCE_SAMPLE: { text: 'REFERENCE SAMPLE · 0 ACTIONABLE', tone: 'warning' },
  LOADING: { text: 'LOADING…', tone: 'context' },
};

function PermissionQueue({ signals, selectedId, onSelect, actionable, reference }: {
  signals: ScalpSignal[]; selectedId: string | null; onSelect: (s: ScalpSignal) => void; actionable: number; reference: boolean;
}) {
  return (
    <section className="at-panel" aria-labelledby="permission-queue-title">
      <header className="at-panel__header">
        <h2 id="permission-queue-title">Permission queue</h2>
        <Chip tone="warning">{reference ? 'REFERENCE SAMPLE · 0 ACTIONABLE' : `manual paper · ${actionable} actionable`}</Chip>
      </header>
      <div className="at-queue">
        {signals.length === 0 && <div className="at-queue-empty">No signals in the live queue.</div>}
        {signals.map(signal => (
          <button key={signal.id} type="button" aria-pressed={signal.id === selectedId}
            className={`at-queue-row at-queue-row--${signal.state.toLowerCase()}${signal.id === selectedId ? ' is-selected' : ''}`}
            onClick={() => onSelect(signal)}>
            <span className="at-queue-row__symbol">{signal.symbol}<small>{signal.last.toFixed(2)}</small></span>
            <span className="at-queue-row__score">{signal.ign}<small>Δ+{signal.ignDelta}</small></span>
            <span className="at-queue-row__body">
              <strong>{signal.state === 'VETOED' ? `VETOED — ${signal.vetoReason ?? 'gate veto'}` : `${signal.state} · ${signal.cohort}`}</strong>
              <small>{signal.primarySetupLabel} · lane {signal.lane} · R {signal.riskPerShare} / {signal.stopBps}bp</small>
            </span>
            <span className="at-queue-row__action">{(signal.state === 'ARMED' || signal.state === 'TRIGGERED') && !reference ? 'Review' : 'no action'}</span>
          </button>
        ))}
      </div>
    </section>
  );
}

function ActiveTradeCard({ signal, reference, canRoute, onRoute, onDismiss, onOpenStrategies }: {
  signal: ScalpSignal; reference: boolean; canRoute: boolean; onRoute: () => void; onDismiss: () => void; onOpenStrategies?: () => void;
}) {
  const matched = signal.matchedSetupLabels ?? [signal.primarySetupLabel];
  const multi = matched.filter(Boolean).length > 1;
  const t2NeedsBook = signal.dataTier === 'T2';
  const gate = signal.gateDecision ?? (signal.state === 'VETOED' ? 'VETO' : 'PASS');
  const orderControls = ['Buy Bid', 'Sell Ask', 'Buy Ask', 'Sell Bid', 'Buy MKT', 'Sell MKT', 'Cancel All', 'Cancel', 'Reverse', 'Flatten'];
  return (
    <section className="at-panel at-trade-card" aria-labelledby="active-trade-title">
      <header className="at-panel__header at-trade-card__title-row">
        <div><h2 id="active-trade-title">{signal.symbol} <span>{signal.last.toFixed(2)}</span> <em>+{signal.changePct.toFixed(1)}%</em></h2></div>
        <div className="at-inline"><Chip tone="warning">{signal.mode.replace(/_/g, ' ').toLowerCase()}</Chip></div>
      </header>

      {/* separated identity/evidence chips — lane ≠ setup ≠ data-tier ≠ size ≠ gate */}
      <div className="at-inline at-wrap at-identity-rail">
        <Chip tone="lane" title="Alert lane / event class — NOT a setup">LANE: {signal.lane}</Chip>
        <Chip title="Named deterministic setup">SETUP: {signal.primarySetupLabel}</Chip>
        {multi && <Chip tone="warning" title={`Also matched: ${matched.filter(l => l !== signal.primarySetupLabel).join(', ')}`}>MULTI-SETUP</Chip>}
        <Chip title={t2NeedsBook ? 'Order-book/tape tier — fails closed without entitled fresh L2' : 'Data tier'}>
          DATA: {signal.dataTier}{t2NeedsBook ? ' · L2+TAPE' : ''} · {signal.dataFreshness ?? 'FRESH'}
        </Chip>
        <Chip title="Position-size multiplier (separate from data tier)">SIZE TIER: {signal.tierMultiplier.toFixed(2)}x</Chip>
        <Chip title="Market session">SESSION: {signal.session}</Chip>
        <Chip tone={gate === 'PASS' ? 'pass' : gate === 'VETO' ? 'fail' : 'warning'} title="Deterministic execution-gate decision">GATE: {gate}</Chip>
        <button type="button" className="at-link-button" onClick={onOpenStrategies}>Setups &amp; strategy rules</button>
      </div>
      {multi && <div className="at-multi">PRIMARY: <b>{signal.primarySetupLabel}</b> · ALSO MATCHED: {matched.filter(l => l !== signal.primarySetupLabel).join(', ')}</div>}

      <div className="at-evidence-grid">
        <div className="at-ign"><small>IGN</small><strong>{signal.ign}</strong><span>Δ+{signal.ignDelta} / {signal.ignDeltaMinutes}m</span></div>
        <div className="at-subscore-area">
          <div className="at-subscore-grid">
            {Object.entries(signal.subscores).map(([name, value]) => (
              <div key={name} className="at-subscore"><small>{name}</small><div><span style={{ width: `${value}%` }} /></div><b>{value}</b></div>
            ))}
          </div>
        </div>
      </div>

      <div className="at-fsm" aria-label="Trigger state machine">
        {signal.fsm.map((s, i) => <span key={s} className={s === signal.fsmCurrent ? 'is-current' : ''}>{s}{i < signal.fsm.length - 1 ? '  ›' : ''}</span>)}
        <time>t+00:{String(signal.expiresInSeconds).padStart(2, '0')}</time>
      </div>

      <dl className="at-level-grid">
        <div><dt>entry ref</dt><dd>{signal.entryRef.toFixed(2)}</dd></div>
        <div><dt>stop ref</dt><dd>{signal.stopRef.toFixed(2)}</dd></div>
        <div><dt>R</dt><dd>{signal.riskPerShare.toFixed(2)} / {signal.stopBps}bp</dd></div>
        <div><dt>leg / R</dt><dd>{signal.legToR.toFixed(1)}x</dd></div>
        <div><dt>float</dt><dd>{signal.floatM.toFixed(1)}M</dd></div>
        <div><dt>RVOL_tod</dt><dd>{signal.rvolTod.toFixed(1)}x</dd></div>
      </dl>

      {signal.evidence.length > 0 && <div className="at-chip-rail">{signal.evidence.map(e => <Chip key={e.id} tone={e.tone}>{e.label}</Chip>)}</div>}

      {/* order controls: display-only, semantically + visually disabled with capability tooltips */}
      <div className="at-order-grid" aria-label="Order controls (disabled)">
        {orderControls.map(label => (
          <button key={label} type="button" disabled className="at-order-btn"
            title={label.includes('MKT') ? 'Market entry unavailable — price-controlled entry only' : 'Order routing off in ActiveTrader (manual paper only)'}>
            <span aria-hidden="true">🔒</span> {label}
          </button>
        ))}
        <div className="at-state"><small>POS</small><strong>flat</strong></div><div className="at-state"><small>ORD</small><strong>none</strong></div>
      </div>

      <div className="at-drill"><small>setup {signal.primarySetupId ?? '—'} · v{signal.setupVersion ?? '—'} · registry {(signal.registryHash ?? '—').replace('sha256:', '').slice(0, 12)} · fsm {signal.fsmState ?? signal.fsmCurrent} · setup_state {signal.setupState ?? '—'}</small></div>

      <footer className="at-trade-card__footer">
        <div><strong>Manual paper testing only</strong><small>No automatic order path. Schwab, Moomoo, and Alpaca Live remain non-routable. ActiveTrader session not authorized.</small></div>
        <div className="at-inline">
          <button type="button" onClick={onRoute} disabled={!canRoute}
            title={reference ? 'Reference sample — preview only' : !canRoute ? 'Only an actionable live signal can be routed' : undefined}>
            {reference ? 'Preview allocation example' : 'Prepare paper route'}
          </button>
          <button type="button" className="at-secondary" onClick={onDismiss}>Dismiss</button>
        </div>
      </footer>
    </section>
  );
}

function AccountAllocationModal({ signal, accounts, reference, onClose }: {
  signal: ScalpSignal; accounts: BrokerAccount[]; reference: boolean; onClose: () => void;
}) {
  const dialogRef = useRef<HTMLElement>(null);
  const openerRef = useRef<Element | null>(null);
  // NO account is preselected — the operator must choose (server verification is required for real routing).
  const [draft, setDraft] = useState<RoutingDraft>({ signalId: signal.id, selectedAccountIds: [], accountShares: {} });
  const selected = accounts.filter(a => draft.selectedAccountIds.includes(a.id));
  const totalShares = selected.reduce((n, a) => n + (draft.accountShares[a.id] || 0), 0);
  const totalNotional = totalShares * signal.entryRef;
  const risk = totalShares * signal.riskPerShare;

  useEffect(() => {
    openerRef.current = document.activeElement;
    const el = dialogRef.current; el?.focus();
    function onKey(e: KeyboardEvent) {
      if (e.key === 'Escape') { e.stopPropagation(); onClose(); return; }
      if (e.key === 'Tab' && el) {
        const f = el.querySelectorAll<HTMLElement>('button, input, [href], [tabindex]:not([tabindex="-1"])');
        const list = Array.from(f).filter(n => !n.hasAttribute('disabled'));
        if (!list.length) return;
        const first = list[0], last = list[list.length - 1];
        if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
        else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
      }
    }
    document.addEventListener('keydown', onKey, true);
    return () => { document.removeEventListener('keydown', onKey, true); (openerRef.current as HTMLElement | null)?.focus?.(); };
  }, [onClose]);

  const setSel = (account: BrokerAccount, checked: boolean) =>
    setDraft(prev => ({ ...prev, selectedAccountIds: checked ? [...prev.selectedAccountIds, account.id] : prev.selectedAccountIds.filter(x => x !== account.id) }));

  return (
    <div className="at-modal-backdrop" role="presentation" onMouseDown={e => e.target === e.currentTarget && onClose()}>
      <section className="at-modal" role="dialog" aria-modal="true" aria-labelledby="route-title" tabIndex={-1} ref={dialogRef}>
        <header className="at-panel__header">
          <div><h2 id="route-title">{reference ? 'Allocation example (reference)' : 'Prepare manual paper order'} <small>{signal.symbol} long</small></h2>
            <p>entry {signal.entryRef} · stop {signal.stopRef} · R {signal.riskPerShare} · IGN {signal.ign}</p></div>
          <Chip tone="warning">environment: server-verify pending</Chip>
        </header>
        <div className="at-account-table">
          <div className="at-account-table__head"><span>Account</span><span>Permissions</span><span>Buying power</span><span>Shares</span><span>Notional</span><span>Risk</span></div>
          {accounts.map(account => {
            const shares = draft.accountShares[account.id] || 0;
            return <div key={account.id} className={`at-account-row ${!account.eligible ? 'is-disabled' : ''}`}>
              <label><input type="checkbox" checked={draft.selectedAccountIds.includes(account.id)} disabled={!account.eligible}
                onChange={e => setSel(account, e.target.checked)} /><span><strong>{account.label}</strong><small>{account.maskedNumber}</small></span></label>
              <span><strong>{account.permissionLabel}</strong>{account.eligibilityReason && <small>{account.eligibilityReason}</small>}</span>
              <span>{account.buyingPower ? usd.format(account.buyingPower) : '—'}</span>
              <span><input type="number" min={0} max={account.maxShares} value={shares} disabled={!account.eligible}
                onChange={e => setDraft(prev => ({ ...prev, accountShares: { ...prev.accountShares, [account.id]: Math.min(account.maxShares, Number(e.target.value || 0)) } }))} /></span>
              <span>{shares ? usd.format(shares * signal.entryRef) : '—'}</span><span>{shares ? money2.format(shares * signal.riskPerShare) : '—'}</span>
            </div>;
          })}
        </div>
        <div className="at-modal-note">No account is preselected. Quantities and risk shown are a client-side preview — a real workflow recomputes them server-side after environment verification. Moomoo is L2/tape data-plane only; Thinkorswim is a manual export/entry workflow, not an API-routable account.</div>
        <dl className="at-summary-grid"><div><dt>Accounts</dt><dd>{selected.length} selected</dd></div><div><dt>Total shares</dt><dd>{totalShares.toLocaleString()}</dd></div><div><dt>Notional (preview)</dt><dd>{usd.format(totalNotional)}</dd></div><div><dt>Risk at stop (preview)</dt><dd>{money2.format(risk)}</dd></div></dl>
        <footer className="at-modal__footer"><p>Final submission is intentionally absent. Order routing is OFF in ActiveTrader; a separate operator-signed, server-verified confirmation ceremony is required.</p>
          <div className="at-inline"><button type="button" className="at-secondary" onClick={onClose}>Cancel</button><button type="button" disabled title="Order routing off — no submit path in this build">Confirm paper order</button></div></footer>
      </section>
    </div>
  );
}

export default function ActiveTraderPage(props: Props) {
  const { signals, accounts, onOpenStrategies, dataState, actionableCount, sourceSessionDate, lastEventAt, registryHash, registryVersion } = props;
  const [preview, setPreview] = useState(false);   // explicit reference-sample preview (never the default)
  const derived: ActiveTraderDataState = signals === undefined ? 'LOADING' : (signals.length ? 'LIVE_DATA' : 'EMPTY_LIVE_QUEUE');
  const state: ActiveTraderDataState = preview ? 'REFERENCE_SAMPLE' : (dataState ?? derived);
  const reference = state === 'REFERENCE_SAMPLE';

  const queue = reference ? MOCK_QUEUE : (signals ?? []);
  const acct = reference ? MOCK_ACCOUNTS : (accounts ?? []);
  const actionable = reference ? 0 : (actionableCount ?? queue.filter(s => s.state === 'ARMED' || s.state === 'TRIGGERED').length);
  const sorted = useMemo(() => [...queue].sort((a, b) => b.ign - a.ign), [queue]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const selected = sorted.find(s => s.id === selectedId) ?? sorted[0] ?? null;
  const [routing, setRouting] = useState(false);
  const banner = BANNER[state];
  const canRoute = !reference && !!selected && (selected.state === 'ARMED' || selected.state === 'TRIGGERED');

  return <main className="active-trader-page">
    <div className="active-trader-page__intro">
      <div><h1>ActiveTrader</h1><p>Evidence-first momentum-scalp review. Manual paper testing only; no automatic or live order path.</p></div>
      <div className="at-inline at-wrap">
        <Chip tone={banner.tone}>{banner.text}</Chip>
        <button type="button" className="at-link-button" onClick={() => setPreview(p => !p)}>{preview ? 'Exit preview' : 'Preview example'}</button>
      </div>
    </div>

    {/* scoped authority status — never conflate a global service with this tab's authority */}
    <div className="at-authority-rail at-inline at-wrap">
      <Chip title="This tab">ACTIVE TRADER SESSION: NOT AUTHORIZED</Chip>
      <Chip tone="fail" title="No order routes wired in ActiveTrader">ACTIVE TRADER ROUTES: OFF</Chip>
      <Chip title="Any global 2FA/automation service is scoped OUTSIDE ActiveTrader">GLOBAL SERVICES: OUT OF SCOPE HERE</Chip>
      <span className="at-source">source: {reference ? 'reference sample' : 'scalp_ignition_events'}
        {sourceSessionDate ? ` · session ${sourceSessionDate}` : ''}{lastEventAt ? ` · last ${String(lastEventAt).slice(11, 19)}Z` : ''}
        {registryVersion ? ` · ${registryVersion}` : ''}{registryHash ? ` ${registryHash.replace('sha256:', '').slice(0, 8)}` : ''}</span>
    </div>

    {state === 'API_UNAVAILABLE' && <div className="at-fullstate at-fullstate--fail">Permission-queue API unavailable. This is not an empty queue — the backend did not respond.</div>}
    {state === 'LOADING' && <div className="at-fullstate">Loading permission queue…</div>}

    <div className="active-trader-page__layout">
      <aside><PermissionQueue signals={sorted} selectedId={selected?.id ?? null} onSelect={s => setSelectedId(s.id)} actionable={actionable} reference={reference} /></aside>
      <div>{selected
        ? <ActiveTradeCard signal={selected} reference={reference} canRoute={canRoute || reference}
            onRoute={() => setRouting(true)} onDismiss={() => setSelectedId(null)} onOpenStrategies={onOpenStrategies} />
        : <section className="at-panel at-empty-card">{state === 'EMPTY_LIVE_QUEUE' ? 'No live signals to review. Use “Preview example” to see the reference layout.' : 'Select a signal from the queue.'}</section>}
      </div>
    </div>
    {routing && selected && <AccountAllocationModal signal={selected} accounts={acct} reference={reference} onClose={() => setRouting(false)} />}
  </main>;
}
