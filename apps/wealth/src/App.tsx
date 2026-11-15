import { BrowserRouter, Navigate, Route, Routes, useParams } from 'react-router-dom'
import { Shell } from './shell/Shell'
import { FamilyPage } from './pages/FamilyPage'
import { HoldingsLive } from './pages/portfolio/HoldingsLive'
import { AllocationLive } from './pages/allocation/AllocationLive'
import { FundamentalsLive } from './pages/fundamentals/FundamentalsLive'
import { PerformanceLive } from './pages/portfolio/PerformanceLive'
import { HomeLive } from './pages/home/HomeLive'
import { IncomeLive } from './pages/portfolio/income/IncomeLive'
import { FAMILIES } from './routes/families'
import { NAV } from './shell/nav'

// v02 addresses are /<group>/<view> (shell/nav.ts). Until a page slice binds a view, a group whose
// id matches a family renders that family's not-built page; any other known view says it is not
// built. Unknown addresses are handled by the shell (it shows "Unknown Wealth address").
function V02View() {
  const { group } = useParams()
  const fam = FAMILIES.find(f => f.id === group)
  if (fam) return <FamilyPage family={fam} />
  const g = NAV.find(x => x.id === group)
  return <p><strong>Not built yet.</strong> <em>{g ? g.label : 'This view'} shows no data until its reviewed batch lands.</em></p>
}

export default function App() {
  return (
    <BrowserRouter basename="/wealth">
      <Routes>
        <Route element={<Shell />}>
          <Route index element={<Navigate to="/home/today" replace />} />
          {/* The one v02 view live on served data. A static path ranks above `:group/:view`, and it renders inside
              Shell's known-address gate like every other view. */}
          <Route path="portfolio/holdings" element={<HoldingsLive />} />
          {/* Second served view. Same static-before-`:group/:view` ranking as holdings; `portfolio/allocation` is
              already a NAV view (shell/nav.ts), so the address needs no other change. */}
          <Route path="portfolio/allocation" element={<AllocationLive />} />
          <Route path="portfolio/fundamentals" element={<FundamentalsLive />} />
          <Route path="portfolio/performance" element={<PerformanceLive />} />
          <Route path="portfolio/income" element={<IncomeLive />} />
          <Route path="home/today" element={<HomeLive />} />
          <Route path="home/outlook" element={<HomeLive view="outlook" />} />
          <Route path="home/needs" element={<HomeLive view="needs" />} />
          <Route path=":group/:view" element={<V02View />} />
          {FAMILIES.filter(f => f.path !== '/').map(f => (
            <Route key={f.id} path={f.path.slice(1)} element={<FamilyPage family={f} />} />
          ))}
          <Route path="*" element={<p><strong>Unknown Wealth route.</strong> <a href="/wealth/">Wealth home</a> · <a href="/v3/">Command Center</a></p>} />
        </Route>
      </Routes>
    </BrowserRouter>
  )
}
