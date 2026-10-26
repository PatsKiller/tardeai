/** Offline synthetic evidence only: the actual Rulebook page (with Policy versions) and the Approvals reader route. */
import React from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter, Route, Routes } from 'react-router-dom'
import PolicyHub from '../src/pages/PolicyHub'
import ApprovalsHub from '../src/pages/ApprovalsHub'
import '../src/index.css'

createRoot(document.getElementById('root')!).render(<BrowserRouter><main style={{ padding: 16, minWidth: 0 }}>
  <Routes><Route path="/policy" element={<PolicyHub />} /><Route path="/approvals/:id" element={<ApprovalsHub />} /></Routes>
</main></BrowserRouter>)
