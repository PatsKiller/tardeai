import React, { useState } from 'react';
import { BrowserRouter, Routes, Route, Link, Navigate } from 'react-router-dom';
import {
  SessionStrip, MoomooBadge, PrimeQueue, SymbolWorkspace, TicketPanels, PnlPanel,
  AccountsPanel, BrokersPanel, CapabilitiesPanel, RejectionsPanel, NotificationsPanel,
  JournalPanel, FeatureModal, ParityPanel,
} from './panels/panels';

/** Classic/Next navigation — a link back to the untouched /v3, not a client replacement. */
function ClassicNextNav() {
  return (
    <nav data-testid="classic-next-nav" aria-label="workspace switch">
      <a href="/v3/" data-testid="nav-classic">CLASSIC (/v3)</a>
      {' · '}
      <Link to="/" data-testid="nav-next"><b>ACTIVE TRADER NEXT (/v3-next)</b></Link>
    </nav>
  );
}

function Workspace() {
  const [symbol, setSymbol] = useState('TESTA');
  return (
    <div data-testid="v3next-workspace">
      <ClassicNextNav />
      <SessionStrip />
      <MoomooBadge />
      <div data-testid="symbol-selector">
        <label>Symbol:{' '}
          <select value={symbol} onChange={(e) => setSymbol(e.target.value)} data-testid="symbol-select">
            <option value="TESTA">TESTA</option>
            <option value="TESTB">TESTB</option>
          </select>
        </label>
      </div>
      <main style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 12 }}>
        <PrimeQueue />
        <SymbolWorkspace symbol={symbol} />
        <div><TicketPanels /><PnlPanel /></div>
        <AccountsPanel />
        <BrokersPanel />
        <CapabilitiesPanel />
        <RejectionsPanel />
        <NotificationsPanel />
        <JournalPanel />
        <FeatureModal />
        <ParityPanel />
      </main>
      <footer data-testid="build-marker">command-center-v3-next · read-only · Stage 6</footer>
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
