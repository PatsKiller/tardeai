import { useState } from 'react'
import PageHeader from '../components/PageHeader'
import Card from '../components/Card'
import SectionHeader from '../components/SectionHeader'
import MetricTile from '../components/MetricTile'
import { useFetch } from '../hooks/useFetch'

interface ReportItem {
  name: string
  path: string
  size_kb: number
  modified?: string
  date?: string
  time?: string
  type?: string
  category?: string
}

interface Catalog {
  live: ReportItem[]
  trade_ai_daily: ReportItem[]
  portfolio_daily: ReportItem[]
  weekly: ReportItem[]
  monthly: ReportItem[]
  docx: ReportItem[]
}

interface CatalogResp { ok: boolean; catalog: Catalog }

function safeArray(arr: unknown): ReportItem[] {
  return Array.isArray(arr) ? arr.filter((x): x is ReportItem => x != null && typeof x === 'object' && typeof (x as ReportItem).name === 'string') : []
}

function ReportRow({ item, showPreview }: { item: ReportItem; showPreview?: (url: string) => void }) {
  const name = item.name || ''
  const path = item.path || ''
  const isDocx = name.endsWith('.docx')
  const isHtml = name.endsWith('.html')
  if (!name || !path) return null
  return (
    <div style={{
      display: 'flex', alignItems: 'center', gap: 8, padding: '5px 0',
      borderBottom: '1px solid var(--border)',
    }}>
      <span style={{ fontSize: 10, width: 16, color: isDocx ? 'var(--accent)' : 'var(--green)', fontWeight: 700 }}>
        {isDocx ? 'W' : 'H'}
      </span>
      <span style={{ flex: 1, fontSize: 11, color: 'var(--text1)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
        {name}
      </span>
      {item.date && <span style={{ fontSize: 9, color: 'var(--text3)', width: 70 }}>{item.date}</span>}
      {item.time && <span style={{ fontSize: 9, color: 'var(--text3)', width: 35 }}>{item.time}</span>}
      <span style={{ fontSize: 9, color: 'var(--text3)', width: 45, textAlign: 'right' }}>{item.size_kb ?? 0} KB</span>
      <div style={{ display: 'flex', gap: 4 }}>
        {isHtml && showPreview && (
          <button onClick={() => showPreview(path)} style={{
            fontSize: 9, padding: '2px 7px', border: '1px solid var(--border)', borderRadius: 3,
            background: 'var(--bg3)', color: 'var(--text2)', cursor: 'pointer', fontFamily: 'var(--mono)',
          }}>Preview</button>
        )}
        <a href={path} target="_blank" rel="noreferrer" style={{
          fontSize: 9, padding: '2px 7px', border: '1px solid var(--border)', borderRadius: 3,
          background: 'var(--bg3)', color: 'var(--accent)', textDecoration: 'none', fontFamily: 'var(--mono)',
        }}>{isDocx ? 'Download' : 'Open'}</a>
      </div>
    </div>
  )
}

export default function Reports() {
  const { data: resp, error } = useFetch<CatalogResp>('/api/reports/catalog')
  const [previewUrl, setPreviewUrl] = useState<string | null>(null)

  // Defensive normalization — any missing section becomes []
  const cat = resp?.catalog
  const live = safeArray(cat?.live)
  const tradeAiDaily = safeArray(cat?.trade_ai_daily)
  const portfolioDaily = safeArray(cat?.portfolio_daily)
  const weekly = safeArray(cat?.weekly)
  const monthly = safeArray(cat?.monthly)
  const docx = safeArray(cat?.docx)
  const totalFiles = live.length + tradeAiDaily.length + portfolioDaily.length + weekly.length + monthly.length + docx.length

  if (error) {
    return (
      <>
        <PageHeader title="Reports" subtitle="Error loading catalog" />
        <Card><div style={{ color: 'var(--red)', padding: 20, fontSize: 11 }}>Failed to load report catalog: {error}</div></Card>
      </>
    )
  }

  return (
    <>
      <PageHeader title="Reports & Intelligence" subtitle={cat ? `${totalFiles} outputs cataloged` : 'Loading...'} />

      {/* G14: Latest Report — sticky at top, first thing visible */}
      {(() => {
        const latest = [...portfolioDaily, ...tradeAiDaily, ...live].sort((a, b) => (b.modified || b.date || '').localeCompare(a.modified || a.date || ''))[0]
        return latest ? (
          <div style={{ position: 'sticky', top: 0, zIndex: 10, padding: '12px 16px', marginBottom: 14, background: 'rgba(14,203,129,0.08)', border: '2px solid rgba(14,203,129,0.3)', borderRadius: 12, display: 'flex', alignItems: 'center', gap: 12, backdropFilter: 'blur(12px)' }}>
            <span style={{ fontSize: 11, fontWeight: 800, padding: '3px 10px', borderRadius: 4, background: 'var(--green)', color: '#000' }}>LATEST</span>
            <span style={{ fontSize: 13, color: 'var(--text0)', fontWeight: 700, flex: 1 }}>{latest.name}</span>
            <span style={{ fontSize: 10, color: 'var(--text2)' }}>{latest.date || latest.modified?.slice(0, 16)} · {latest.size_kb}KB</span>
            <button onClick={() => setPreviewUrl(latest.path)} style={{ fontSize: 10, padding: '5px 14px', border: '1px solid var(--green)', borderRadius: 6, background: 'var(--green-dim)', color: 'var(--green)', cursor: 'pointer', fontFamily: 'var(--mono)', fontWeight: 700 }}>Preview</button>
            <a href={latest.path} target="_blank" rel="noreferrer" style={{ fontSize: 10, padding: '5px 14px', border: '1px solid var(--accent)', borderRadius: 6, background: 'var(--accent-dim)', color: 'var(--accent)', textDecoration: 'none', fontFamily: 'var(--mono)', fontWeight: 700 }}>Open</a>
          </div>
        ) : null
      })()}

      {/* Preview iframe */}
      {previewUrl && (
        <div style={{
          marginBottom: 12, border: '1px solid var(--border)', borderRadius: 'var(--radius-lg)',
          overflow: 'hidden', position: 'relative',
        }}>
          <div style={{
            display: 'flex', justifyContent: 'space-between', alignItems: 'center',
            padding: '6px 12px', background: 'var(--bg1)', borderBottom: '1px solid var(--border)',
          }}>
            <span style={{ fontSize: 10, color: 'var(--text2)' }}>Preview: {previewUrl.split('/').pop()}</span>
            <button onClick={() => setPreviewUrl(null)} style={{
              fontSize: 10, padding: '2px 8px', border: '1px solid var(--border)', borderRadius: 3,
              background: 'var(--bg3)', color: 'var(--text2)', cursor: 'pointer', fontFamily: 'var(--mono)',
            }}>Close</button>
          </div>
          <iframe src={previewUrl} style={{ width: '100%', height: 500, border: 'none', background: '#fff' }} />
        </div>
      )}

      {!cat ? (
        <Card><div style={{ color: 'var(--text3)', padding: 20 }}>Loading catalog...</div></Card>
      ) : (
        <>
          {/* Stats strip */}
          <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', marginBottom: 16 }}>
            <MetricTile label="Live Dashboards" value={String(live.length)} />
            <MetricTile label="Trade AI Daily" value={String(tradeAiDaily.length)} />
            <MetricTile label="Portfolio Daily" value={String(portfolioDaily.length)} />
            <MetricTile label="Weekly" value={String(weekly.length)} />
            <MetricTile label="Monthly" value={String(monthly.length)} />
            <MetricTile label="DOCX Exports" value={String(docx.length)} />
          </div>

          {/* Live Dashboards */}
          {live.length > 0 && (
            <>
              <SectionHeader title="Live Dashboards" count={live.length} />
              <Card>
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(250px, 1fr))', gap: 10 }}>
                  {live.map(item => (
                    <div key={item.name} style={{
                      padding: '10px 14px', background: 'var(--bg1)', border: '1px solid var(--border)',
                      borderRadius: 'var(--radius)', display: 'flex', flexDirection: 'column', gap: 4,
                    }}>
                      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                        <span style={{ fontWeight: 600, color: 'var(--text0)', fontSize: 12 }}>{item.name}</span>
                        <span style={{ fontSize: 8, color: 'var(--green)', fontWeight: 600, padding: '1px 5px', background: 'var(--green-dim)', borderRadius: 3 }}>LIVE</span>
                      </div>
                      <div style={{ fontSize: 9, color: 'var(--text3)' }}>
                        {item.size_kb ?? 0} KB{item.modified ? ` | Updated ${String(item.modified).slice(0, 16)}` : ''}
                      </div>
                      <div style={{ display: 'flex', gap: 4, marginTop: 4 }}>
                        <button onClick={() => setPreviewUrl(item.path)} style={{
                          fontSize: 9, padding: '3px 10px', border: '1px solid var(--border)', borderRadius: 3,
                          background: 'var(--bg3)', color: 'var(--text2)', cursor: 'pointer', fontFamily: 'var(--mono)', flex: 1,
                        }}>Preview</button>
                        <a href={item.path} target="_blank" rel="noreferrer" style={{
                          fontSize: 9, padding: '3px 10px', border: '1px solid var(--accent)', borderRadius: 3,
                          background: 'var(--accent-dim)', color: 'var(--accent)', textDecoration: 'none',
                          fontFamily: 'var(--mono)', flex: 1, textAlign: 'center',
                        }}>Open</a>
                      </div>
                    </div>
                  ))}
                </div>
              </Card>
            </>
          )}

          {/* Trade AI Daily — latest inline + list */}
          {tradeAiDaily.length > 0 && (
            <>
              <SectionHeader title="Trade AI Daily Dashboards" count={tradeAiDaily.length} />
              <Card title={`Today's Latest: ${tradeAiDaily[0]?.name || ''}`}>
                <iframe
                  src={tradeAiDaily[0]?.path}
                  style={{ width: '100%', height: 400, border: 'none', borderRadius: 6, background: '#fff' }}
                />
              </Card>
              <Card compact>
                {tradeAiDaily.map(item => (
                  <ReportRow key={item.path || item.name} item={item} showPreview={setPreviewUrl} />
                ))}
              </Card>
            </>
          )}

          {/* Portfolio Daily */}
          {portfolioDaily.length > 0 && (
            <>
              <SectionHeader title="Portfolio Daily Dashboards" count={portfolioDaily.length} />
              <Card>
                {portfolioDaily.map(item => (
                  <ReportRow key={item.path || item.name} item={item} showPreview={setPreviewUrl} />
                ))}
              </Card>
            </>
          )}

          {/* Latest Weekly + Monthly — inline previews */}
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
            <div>
              <SectionHeader title="Weekly Reports" count={weekly.length} />
              {weekly.filter(w => w.name.endsWith('.html')).length > 0 && (
                <Card title={`Latest: ${weekly.filter(w => w.name.endsWith('.html'))[0]?.name}`}>
                  <iframe
                    src={weekly.filter(w => w.name.endsWith('.html'))[0]?.path}
                    style={{ width: '100%', height: 300, border: 'none', borderRadius: 6, background: '#fff' }}
                  />
                </Card>
              )}
              <Card compact>
                {weekly.length > 0 ? weekly.map(item => (
                  <ReportRow key={item.path || item.name} item={item} showPreview={item.name.endsWith('.html') ? setPreviewUrl : undefined} />
                )) : <div style={{ color: 'var(--text3)', fontSize: 10, padding: 8 }}>No weekly reports yet.</div>}
              </Card>
            </div>
            <div>
              <SectionHeader title="Monthly Reports" count={monthly.length} />
              {monthly.filter(m => m.name.endsWith('.html')).length > 0 && (
                <Card title={`Latest: ${monthly.filter(m => m.name.endsWith('.html'))[0]?.name}`}>
                  <iframe
                    src={monthly.filter(m => m.name.endsWith('.html'))[0]?.path}
                    style={{ width: '100%', height: 300, border: 'none', borderRadius: 6, background: '#fff' }}
                  />
                </Card>
              )}
              <Card compact>
                {monthly.length > 0 ? monthly.map(item => (
                  <ReportRow key={item.path || item.name} item={item} showPreview={item.name.endsWith('.html') ? setPreviewUrl : undefined} />
                )) : <div style={{ color: 'var(--text3)', fontSize: 10, padding: 8 }}>No monthly reports yet.</div>}
              </Card>
            </div>
          </div>

          {/* DOCX Exports */}
          {docx.length > 0 && (
            <>
              <SectionHeader title="Document Exports (DOCX)" count={docx.length} />
              <Card>
                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 0 }}>
                  <div>
                    <div style={{ fontSize: 10, color: 'var(--text3)', fontWeight: 600, padding: '4px 0', marginBottom: 4 }}>Portfolio Briefs</div>
                    {docx.filter(d => d.category === 'portfolio_brief').length > 0
                      ? docx.filter(d => d.category === 'portfolio_brief').map(item => <ReportRow key={item.path || item.name} item={item} />)
                      : <div style={{ fontSize: 9, color: 'var(--text3)', padding: 4 }}>None</div>}
                  </div>
                  <div>
                    <div style={{ fontSize: 10, color: 'var(--text3)', fontWeight: 600, padding: '4px 0', marginBottom: 4 }}>Trade AI Reports</div>
                    {docx.filter(d => d.category === 'trade_ai').length > 0
                      ? docx.filter(d => d.category === 'trade_ai').map(item => <ReportRow key={item.path || item.name} item={item} />)
                      : <div style={{ fontSize: 9, color: 'var(--text3)', padding: 4 }}>None</div>}
                  </div>
                </div>
              </Card>
            </>
          )}

          {totalFiles === 0 && (
            <Card><div style={{ color: 'var(--text3)', padding: 20, textAlign: 'center' }}>No reports found. Run the portfolio pipeline to generate reports.</div></Card>
          )}
        </>
      )}
    </>
  )
}
