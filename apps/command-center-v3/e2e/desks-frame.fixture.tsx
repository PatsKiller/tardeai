/** Synthetic evidence only. No production route or server. */
import React from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter, Routes, Route } from 'react-router-dom'
import DeskPage, { DeskGap } from '../src/components/DeskPage'
import NavRail from '../src/components/NavRail'
import '../src/index.css'
createRoot(document.getElementById('root')!).render(<BrowserRouter><div style={{ display: 'flex', height: '100vh' }}>
  <NavRail /><main className="app-main" style={{ flex: 1, minWidth: 0, padding: 20, overflowY: 'auto' }}>
    <Routes><Route path="/system/ops-controls" element={<h1>Decision destination</h1>} /><Route path="*" element={<DeskPage title="Restored desk" purpose="Review the evidence, identify the gaps, and choose what needs attention."
      tabs={[{ id: 'overview', label: 'Overview' }, { id: 'history', label: 'History' }]} tabAliases={{ legacy: 'history' }} sources={[
        { id: 'posture', label: 'Posture', asOf: '2026-10-24T23:30:00Z', laneIds: ['posture'], maxAgeHours: 1 },
        { id: 'options', label: 'Options lifecycle', asOf: '2026-10-14T00:00:00Z', laneIds: ['options'], maxAgeHours: 48 },
        { id: 'cash', label: 'Cash alternatives', laneIds: ['cash'], gap: 'No updated cash-alternatives evidence has been supplied.' },
        { id: 'regime', label: 'Regime', asOf: '2026-10-24', laneIds: ['regime'] },
        { id: 'future', label: 'Unverified clock', asOf: '2026-10-26T00:00:00Z' },
      ]} decisions={[{ id: 'cash-writer', title: 'Review the cash-alternatives gap', detail: 'Decide whether this source still belongs on the desk.', href: '/system/ops-controls?tab=jobs' }]}>
      {active => <section aria-label="Selected content"><h2 style={{ fontSize: 18 }}>{active === 'history' ? 'History evidence' : 'Overview evidence'}</h2>
        <DeskGap title="Panel evidence missing" reason="No result was supplied for this fixture panel." /></section>}
    </DeskPage>} /></Routes>
  </main>
</div></BrowserRouter>)
