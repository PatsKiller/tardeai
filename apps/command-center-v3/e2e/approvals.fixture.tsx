/** Offline synthetic evidence only; mounts the actual W11 pages and W5 frame. */
import React from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter, Route, Routes } from 'react-router-dom'
import ApprovalsHub from '../src/pages/ApprovalsHub'
import PolicyHub from '../src/pages/PolicyHub'
import '../src/index.css'

createRoot(document.getElementById('root')!).render(<BrowserRouter><main style={{ padding: 16, minWidth: 0 }}>
  <Routes><Route path="/approvals" element={<ApprovalsHub />} /><Route path="/approvals/:id" element={<ApprovalsHub />} />
    <Route path="/policy" element={<PolicyHub />} /><Route path="/cio/questions/*" element={<h1>Question sent to the CIO</h1>} />
    <Route path="/system/ops-controls" element={<h1>Existing operator controls</h1>} />
    <Route path="/coordination" element={<h1>Work pipeline</h1>} /></Routes>
</main></BrowserRouter>)
