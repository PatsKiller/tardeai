import { NavLink, Outlet } from 'react-router-dom'
import { FAMILIES } from '../routes/families'

// STRUCTURAL SHELL ONLY. The accepted visual design (reference sha256 9bafaac1…) has not been
// transferred to this server; no visual treatment is invented here. Plain semantic markup.
export function Shell() {
  return (
    <div>
      <header>
        <strong>Trade-AI Wealth</strong>{' '}
        <small><em>build {__WEALTH_APP_VERSION__} · source {__WEALTH_SOURCE_SHA__?.slice(0, 9) ?? 'unknown'} · not accepted</em></small>
        <nav aria-label="Wealth sections">
          <ul>
            {FAMILIES.filter(f => !f.path.includes(':')).map(f => (
              <li key={f.id}><NavLink to={f.path} end={f.path === '/'}>{f.title}</NavLink></li>
            ))}
            <li><a href="/v3/">Command Center (classic)</a></li>
          </ul>
        </nav>
      </header>
      <main><Outlet /></main>
    </div>
  )
}
