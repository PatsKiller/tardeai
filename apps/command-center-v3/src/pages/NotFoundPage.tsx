/**
 * NotFoundPage — the surface the shell renders when a path matches no route.
 *
 * Why this exists (LQ-20261107-175): the Reports → System rollup "Research & reports" panel drilled to
 * `/v3/research-intel`, which no route declares (the surface is `/v3/research-intelligence`). The inner
 * router had no catch-all, so the outlet rendered nothing and the page came up as a header plus the build
 * stamp — the sweep logged "page text len 161". A blank page is indistinguishable from "no data", "still
 * loading" and "everything is fine" (the same argument as RouteErrorBoundary), so an unknown path now says
 * which path it could not resolve and where the neighbouring surfaces live.
 */
import { Link, useLocation } from 'react-router-dom'
import { BB, TYPE } from '../lib/watchTokens'

const ELSEWHERE: Array<[string, string]> = [
  ['/v3', 'Home'],
  ['/v3/reports', 'Reports'],
  ['/v3/research-intelligence', 'Research Intelligence'],
  ['/v3/health', 'Health'],
]

export default function NotFoundPage() {
  const { pathname } = useLocation()

  return (
    <div
      data-testid="route-not-found"
      data-path={pathname}
      role="alert"
      style={{
        maxWidth: 720,
        display: 'grid',
        gap: 8,
        padding: '12px 14px',
        background: BB.amberDim,
        borderLeft: `3px solid ${BB.amber}`,
        lineHeight: 1.5,
      }}
    >
      <div style={{ fontSize: TYPE.md, fontWeight: 800, letterSpacing: 0.3, color: BB.amber }}>
        THIS PAGE DOES NOT EXIST
      </div>
      <div style={{ fontSize: TYPE.base, color: BB.text1 }}>
        No route is registered for <span style={{ fontFamily: 'var(--mono)' }}>{pathname}</span>. Nothing is
        missing and nothing is still loading — the link that brought you here is dead.
      </div>
      <div style={{ fontSize: TYPE.sm, color: BB.text2 }}>
        Somewhere else:{' '}
        {ELSEWHERE.map(([to, label], i) => (
          <span key={to}>
            {i > 0 && ' · '}
            <Link to={to} style={{ color: BB.text1 }}>{label}</Link>
          </span>
        ))}
      </div>
    </div>
  )
}
