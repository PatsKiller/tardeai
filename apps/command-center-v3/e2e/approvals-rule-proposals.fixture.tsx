/** Offline synthetic evidence only: the actual Approvals Center queue and Conflict rules page, side by side. */
import React from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter, Route, Routes } from 'react-router-dom'
import ApprovalsHub from '../src/pages/ApprovalsHub'
import ConflictRules from '../src/pages/ConflictRules'
import '../src/index.css'

createRoot(document.getElementById('root')!).render(<BrowserRouter><main style={{ padding: 16, minWidth: 0 }}>
  <Routes><Route path="/approvals" element={<ApprovalsHub />} /><Route path="/approvals/:id" element={<ApprovalsHub />} />
    <Route path="/conflicts/rules" element={<ConflictRules />} /></Routes>
</main></BrowserRouter>)
