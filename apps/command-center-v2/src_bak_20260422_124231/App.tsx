import { lazy, Suspense } from 'react'
import { BrowserRouter, Routes, Route } from 'react-router-dom'
import Shell from './components/Shell'

const Overview = lazy(() => import('./pages/Overview'))
const TradeAI = lazy(() => import('./pages/TradeAI'))
const Portfolio = lazy(() => import('./pages/Portfolio'))
const Journal = lazy(() => import('./pages/Journal'))
const Risk = lazy(() => import('./pages/Risk'))
const TaxLots = lazy(() => import('./pages/TaxLots'))
const Correlation = lazy(() => import('./pages/Correlation'))
const Rebalance = lazy(() => import('./pages/Rebalance'))
const Dividends = lazy(() => import('./pages/Dividends'))
const Retirement = lazy(() => import('./pages/Retirement'))
const Attribution = lazy(() => import('./pages/Attribution'))
const Forecast = lazy(() => import('./pages/Forecast'))
const Research = lazy(() => import('./pages/Research'))
const Notifications = lazy(() => import('./pages/Notifications'))
const AlertsActions = lazy(() => import('./pages/AlertsActions'))
const Watchlist = lazy(() => import('./pages/Watchlist'))
const Approvals = lazy(() => import('./pages/Approvals'))
const Reports = lazy(() => import('./pages/Reports'))
const Ops = lazy(() => import('./pages/Ops'))

function Loading() {
  return <div style={{ color: 'var(--text3)', padding: 20 }}>Loading...</div>
}

export default function App() {
  return (
    <BrowserRouter basename="/v2">
      <Routes>
        <Route element={<Shell />}>
          <Route index element={<Suspense fallback={<Loading />}><Overview /></Suspense>} />
          <Route path="trade-ai" element={<Suspense fallback={<Loading />}><TradeAI /></Suspense>} />
          <Route path="portfolio" element={<Suspense fallback={<Loading />}><Portfolio /></Suspense>} />
          <Route path="journal" element={<Suspense fallback={<Loading />}><Journal /></Suspense>} />
          <Route path="risk" element={<Suspense fallback={<Loading />}><Risk /></Suspense>} />
          <Route path="tax" element={<Suspense fallback={<Loading />}><TaxLots /></Suspense>} />
          <Route path="correlation" element={<Suspense fallback={<Loading />}><Correlation /></Suspense>} />
          <Route path="rebalance" element={<Suspense fallback={<Loading />}><Rebalance /></Suspense>} />
          <Route path="dividends" element={<Suspense fallback={<Loading />}><Dividends /></Suspense>} />
          <Route path="retirement" element={<Suspense fallback={<Loading />}><Retirement /></Suspense>} />
          <Route path="attribution" element={<Suspense fallback={<Loading />}><Attribution /></Suspense>} />
          <Route path="forecast" element={<Suspense fallback={<Loading />}><Forecast /></Suspense>} />
          <Route path="research" element={<Suspense fallback={<Loading />}><Research /></Suspense>} />
          <Route path="alerts" element={<Suspense fallback={<Loading />}><AlertsActions /></Suspense>} />
          <Route path="notifications" element={<Suspense fallback={<Loading />}><Notifications /></Suspense>} />
          <Route path="watchlist" element={<Suspense fallback={<Loading />}><Watchlist /></Suspense>} />
          <Route path="approvals" element={<Suspense fallback={<Loading />}><Approvals /></Suspense>} />
          <Route path="reports" element={<Suspense fallback={<Loading />}><Reports /></Suspense>} />
          <Route path="ops" element={<Suspense fallback={<Loading />}><Ops /></Suspense>} />
        </Route>
      </Routes>
    </BrowserRouter>
  )
}
