import React, { useState, useEffect } from 'react';
import { BrowserRouter, Routes, Route, Link, Navigate } from 'react-router-dom';
import { fetchScanner, type ScannerData } from './fixtures/readApi';
import {
  SessionStrip, MoomooBadge, PrimeQueue, DecisionDeck, SymbolDecision, TicketPanels, PnlPanel,
  AccountsPanel, BrokersPanel, CapabilitiesPanel, RejectionsPanel, NotificationsPanel,
  JournalPanel, FeatureModal, ParityPanel, ObservationGatePanel,
} from './panels/panels';
import { fixtures, MOOMOO_STATUS } from './fixtures/readApi';
import './styles.css';

function ClassicNextNav() {
  return (
    <nav data-testid="classic-next-nav" aria-label="workspace switch" className="at-switch">
      <a href="/v3/" data-testid="nav-classic">Classic /v3</a>
      <Link to="/" data-testid="nav-next" aria-current="page">Active Trader Next</Link>
    </nav>
  );
}

function Workspace() {
  const session = fixtures.session().data;
  const [scanner, setScanner] = useState<ScannerData | null | undefined>(undefined);
  const [symbol, setSymbol] = useState<string>('');
  useEffect(() => {
    fetchScanner().then((s) => {
      setScanner(s);
      const act = (s?.tickers ?? []).filter((t) => /^(GO|WAIT)/i.test(String(t.decision)));
      const first = act.find((t) => String(t.decision).toUpperCase() === 'GO') ?? act[0];
      if (first) setSymbol(first.symbol);
    });
  }, []);
  const actionable = (scanner?.tickers ?? []).filter((t) => /^(GO|WAIT)/i.test(String(t.decision)));
  return (
    <div data-testid="v3next-workspace" className="at-shell">
      <div className="at-topbar">
        <div className="at-brand"><div className="at-mark">AT</div><div><div className="at-title">Active Trader Next</div><div className="at-subtitle">Read-only mirror · operator workspace iteration 2</div></div></div>
        <ClassicNextNav />
        <div className="at-safety"><span className="at-chip at-chip--blue">FIXTURE DATA</span><span className="at-chip at-chip--red">ZERO BROKER WRITES</span><span className="at-chip at-chip--amber">KILL {session.kill_switch}</span></div>
      </div>

      <SessionStrip />
      <MoomooBadge />

      <div className="at-toolbar" data-testid="symbol-selector">
        <label htmlFor="at-symbol-select">Selected symbol</label>
        <select id="at-symbol-select" value={symbol} onChange={(event) => setSymbol(event.target.value)} data-testid="symbol-select" className="at-select">
          {actionable.length === 0 && <option value="">—</option>}
          {actionable.map((t) => <option key={t.symbol} value={t.symbol}>{t.symbol} · {t.decision}</option>)}
        </select>
        <span className="at-chip at-chip--blue">{MOOMOO_STATUS.connector_state.replace(/_/g, ' ')}</span>
        <span className="at-toolbar__hint">Actionable rows come from the TradeAI scanner. All ticket and management controls remain disabled.</span>
      </div>

      <main className="at-workspace">
        <div className="at-primary-grid">
          <DecisionDeck scanner={scanner} />
          <SymbolDecision scanner={scanner} symbol={symbol} />
          <div className="at-stack"><TicketPanels symbol={symbol} /><PnlPanel /></div>
        </div>
        <div className="at-secondary-grid">
          <PrimeQueue selectedSymbol={symbol} onSelect={setSymbol} />
          <ObservationGatePanel />
          <ParityPanel />
          <JournalPanel />
          <AccountsPanel />
          <BrokersPanel />
          <CapabilitiesPanel />
          <RejectionsPanel />
          <NotificationsPanel />
          <FeatureModal />
        </div>
      </main>

      <footer data-testid="build-marker" className="at-footer"><strong>command-center-v3-next</strong><span>read-only · fixture mirror · no parity claim</span><span className="at-footer__sha">base 70a681bb3867 · sibling UI branch</span></footer>
    </div>
  );
}

export function App() {
  return (
    <BrowserRouter basename="/v3-next">
      <Routes>
        <Route path="/" element={<Workspace />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </BrowserRouter>
  );
}
