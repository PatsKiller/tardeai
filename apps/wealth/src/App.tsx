import { BrowserRouter, Route, Routes } from 'react-router-dom'
import { Shell } from './shell/Shell'
import { FamilyPage } from './pages/FamilyPage'
import { FAMILIES } from './routes/families'

export default function App() {
  return (
    <BrowserRouter basename="/wealth">
      <Routes>
        <Route element={<Shell />}>
          {FAMILIES.map(f => (
            f.path === '/'
              ? <Route key={f.id} index element={<FamilyPage family={f} />} />
              : <Route key={f.id} path={f.path.slice(1)} element={<FamilyPage family={f} />} />
          ))}
          <Route path="*" element={<p><strong>Unknown Wealth route.</strong> <a href="/wealth/">Wealth home</a> · <a href="/v3/">Command Center</a></p>} />
        </Route>
      </Routes>
    </BrowserRouter>
  )
}
