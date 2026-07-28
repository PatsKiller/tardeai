import { useMemo, useState } from 'react';
import type { BrokerAccount, RoutingDraft, ScalpSignal } from './activeTrader.types';
import { MOCK_ACCOUNTS, MOCK_QUEUE, MOCK_SIGNAL } from './activeTrader.mock';
import './activeTrader.css';

type Props = {
  signals?: ScalpSignal[];
  accounts?: BrokerAccount[];
  onOpenStrategies?: () => void;
};

const usd = new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 0 });
const money2 = new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', minimumFractionDigits: 2 });

function Chip({ children, tone = 'context' }: { children: React.ReactNode; tone?: 'pass' | 'fail' | 'context' | 'warning' }) {
  return <span className={`at-chip at-chip--${tone}`}>{children}</span>;
}

function PermissionQueue({ signals, onSelect }: { signals: ScalpSignal[]; onSelect: (signal: ScalpSignal) => void }) {
  return (
    <section className="at-panel" aria-labelledby="permission-queue-title">
      <header className="at-panel__header">
        <h2 id="permission-queue-title">Permission queue</h2>
        <Chip tone="warning">manual paper / {signals.filter(s => s.state === 'ARMED').length} reviewable</Chip>
      </header>
      <div className="at-queue">
        {signals.map(signal => (
          <button key={signal.id} type="button" className={`at-queue-row at-queue-row--${signal.state.toLowerCase()}`} onClick={() => onSelect(signal)}>
            <span className="at-queue-row__symbol">{signal.symbol}<small>{signal.last.toFixed(2)}</small></span>
            <span className="at-queue-row__score">{signal.ign}<small>delta +{signal.ignDelta}</small></span>
            <span className="at-queue-row__body">
              <strong>{signal.state === 'VETOED' ? `VETOED — ${signal.vetoReason}` : `${signal.state} / ${signal.cohort} / ${signal.dataTier}`}</strong>
              <small>{signal.primarySetupLabel} · R {signal.riskPerShare} / {signal.stopBps}bp · leg {signal.legToR}x</small>
            </span>
            <span className="at-queue-row__action">{signal.state === 'ARMED' ? 'Review' : 'no action'}</span>
          </button>
        ))}
      </div>
    </section>
  );
}

function ActiveTradeCard({ signal, onRoute, onOpenStrategies }: { signal: ScalpSignal; onRoute: () => void; onOpenStrategies?: () => void }) {
  const presets = [100, 300, 500, 1000, 2000, 2500];
  return (
    <section className="at-panel at-trade-card" aria-labelledby="active-trade-title">
      <header className="at-panel__header at-trade-card__title-row">
        <div><h2 id="active-trade-title">{signal.symbol} <span>{signal.last.toFixed(2)}</span> <em>+{signal.changePct.toFixed(1)}%</em></h2></div>
        <div className="at-inline"><Chip>{signal.lane} lane</Chip><Chip tone="warning">{signal.mode.replaceAll('_', ' ').toLowerCase()}</Chip></div>
      </header>

      <div className="at-evidence-grid">
        <div className="at-ign"><small>IGN</small><strong>{signal.ign}</strong><span>delta +{signal.ignDelta} / {signal.ignDeltaMinutes}m</span></div>
        <div className="at-subscore-area">
          <div className="at-inline at-wrap">
            <Chip tone="pass">ACCEL</Chip><Chip>{signal.primarySetupLabel}</Chip><Chip>{signal.cohort} cohort</Chip><Chip>{signal.dataTier} {signal.tierMultiplier.toFixed(2)}x</Chip>
            <button type="button" className="at-link-button" onClick={onOpenStrategies}>Setups & strategy rules</button>
          </div>
          <div className="at-subscore-grid">
            {Object.entries(signal.subscores).map(([name, value]) => (
              <div key={name} className="at-subscore"><small>{name}</small><div><span style={{ width: `${value}%` }} /></div><b>{value}</b></div>
            ))}
          </div>
        </div>
      </div>

      <div className="at-fsm" aria-label="Trigger state machine">
        {signal.fsm.map((state, i) => <span key={state} className={state === signal.fsmCurrent ? 'is-current' : ''}>{state}{i < signal.fsm.length - 1 ? '  >' : ''}</span>)}
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

      <div className="at-chip-rail">{signal.evidence.map(e => <Chip key={e.id} tone={e.tone}>{e.label}</Chip>)}</div>

      <div className="at-order-grid" aria-label="Display-only order controls">
        {['Buy Bid', 'Sell Ask', 'Buy Ask', 'Sell Bid', 'Buy MKT', 'Sell MKT', 'Cancel All', 'Cancel', 'Reverse', 'Flatten'].map(label => (
          <button key={label} type="button" disabled className={label.startsWith('Buy') ? 'is-buy' : label.startsWith('Sell') ? 'is-sell' : ''}>{label}</button>
        ))}
        <div className="at-state"><small>POS</small><strong>flat</strong></div><div className="at-state"><small>ORD</small><strong>none</strong></div>
      </div>

      <div className="at-quantity-row"><label>Qty <input value={signal.operatorQuantity} readOnly aria-label="Operator quantity" /></label>
        <div className="at-inline at-wrap">{presets.map(p => <button key={p} type="button" disabled>{p >= 1000 ? `${p / 1000}k` : p}</button>)}</div>
        <div className="at-tier-size"><small>tier-derived size {signal.tierMultiplier.toFixed(2)}x</small><strong>{signal.tierDerivedQuantity}</strong></div>
      </div>

      <footer className="at-trade-card__footer">
        <div><strong>Manual paper account only</strong><small>No automatic order path. Schwab, Moomoo, and Alpaca Live remain non-routable.</small></div>
        <div className="at-inline"><button type="button" onClick={onRoute}>Prepare paper route</button><button type="button" className="at-secondary">Dismiss</button></div>
      </footer>
    </section>
  );
}

function AccountAllocationModal({ signal, accounts, onClose }: { signal: ScalpSignal; accounts: BrokerAccount[]; onClose: () => void }) {
  const [draft, setDraft] = useState<RoutingDraft>({ signalId: signal.id, selectedAccountIds: ['alpaca-paper'], accountShares: { 'alpaca-paper': signal.operatorQuantity } });
  const selected = accounts.filter(a => draft.selectedAccountIds.includes(a.id));
  const totalShares = selected.reduce((n, a) => n + (draft.accountShares[a.id] || 0), 0);
  const totalNotional = totalShares * signal.entryRef;
  const risk = totalShares * signal.riskPerShare;
  const setSelected = (account: BrokerAccount, checked: boolean) => {
    if (!account.eligible) return;
    setDraft(prev => ({ ...prev, selectedAccountIds: checked ? [...prev.selectedAccountIds, account.id] : prev.selectedAccountIds.filter(x => x !== account.id) }));
  };
  return (
    <div className="at-modal-backdrop" role="presentation" onMouseDown={e => e.target === e.currentTarget && onClose()}>
      <section className="at-modal" role="dialog" aria-modal="true" aria-labelledby="route-title">
        <header className="at-panel__header"><div><h2 id="route-title">Prepare manual paper order <small>{signal.symbol} long</small></h2><p>entry {signal.entryRef} · stop {signal.stopRef} · R {signal.riskPerShare} · IGN {signal.ign}</p></div><Chip tone="pass">paper account verified</Chip></header>
        <div className="at-account-table">
          <div className="at-account-table__head"><span>Account</span><span>Permissions</span><span>Buying power</span><span>Shares</span><span>Notional</span><span>Risk</span></div>
          {accounts.map(account => {
            const shares = draft.accountShares[account.id] || 0;
            return <div key={account.id} className={`at-account-row ${!account.eligible ? 'is-disabled' : ''}`}>
              <label><input type="checkbox" checked={draft.selectedAccountIds.includes(account.id)} disabled={!account.eligible} onChange={e => setSelected(account, e.target.checked)} /><span><strong>{account.label}</strong><small>{account.maskedNumber}</small></span></label>
              <span><strong>{account.permissionLabel}</strong>{account.eligibilityReason && <small>{account.eligibilityReason}</small>}</span>
              <span>{usd.format(account.buyingPower)}</span>
              <span><input type="number" min={0} max={account.maxShares} value={shares} disabled={!account.eligible} onChange={e => setDraft(prev => ({ ...prev, accountShares: { ...prev.accountShares, [account.id]: Math.min(account.maxShares, Number(e.target.value || 0)) } }))} /></span>
              <span>{shares ? usd.format(shares * signal.entryRef) : '—'}</span><span>{shares ? money2.format(shares * signal.riskPerShare) : '—'}</span>
            </div>;
          })}
        </div>
        <div className="at-modal-note">Moomoo is represented as L2/tape data-plane only. Thinkorswim remains a manual export/entry workflow and is not an API-routable account.</div>
        <dl className="at-summary-grid"><div><dt>Accounts</dt><dd>{selected.length} selected</dd></div><div><dt>Total shares</dt><dd>{totalShares.toLocaleString()}</dd></div><div><dt>Total notional</dt><dd>{usd.format(totalNotional)}</dd></div><div><dt>Paper risk at stop</dt><dd>{money2.format(risk)}</dd></div></dl>
        <footer className="at-modal__footer"><p>Final submission is intentionally absent from this reference build. The operator must complete a separate manual paper confirmation ceremony.</p><div className="at-inline"><button type="button" className="at-secondary" onClick={onClose}>Cancel</button><button type="button" disabled>Confirm paper order</button></div></footer>
      </section>
    </div>
  );
}

export default function ActiveTraderPage({ signals = MOCK_QUEUE, accounts = MOCK_ACCOUNTS, onOpenStrategies }: Props) {
  const [selected, setSelected] = useState<ScalpSignal>(signals[0] || MOCK_SIGNAL);
  const [routing, setRouting] = useState(false);
  const sorted = useMemo(() => [...signals].sort((a, b) => b.ign - a.ign), [signals]);
  return <main className="active-trader-page">
    <div className="active-trader-page__intro"><div><h1>ActiveTrader</h1><p>Evidence-first momentum-scalp review. Manual paper testing only; no automatic or live order path.</p></div><div className="at-inline"><Chip>{selected.session}</Chip><Chip tone="warning">NO LIVE ROUTING</Chip></div></div>
    <div className="active-trader-page__layout"><aside><PermissionQueue signals={sorted} onSelect={setSelected} /></aside><div><ActiveTradeCard signal={selected} onRoute={() => setRouting(true)} onOpenStrategies={onOpenStrategies} /></div></div>
    {routing && <AccountAllocationModal signal={selected} accounts={accounts} onClose={() => setRouting(false)} />}
  </main>;
}
