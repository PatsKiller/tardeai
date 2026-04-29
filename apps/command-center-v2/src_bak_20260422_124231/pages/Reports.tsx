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

const BASE = 'http://192.168.50.16:7777'

function ReportRow({ item, showPreview }: { item: ReportItem; showPreview?: (url: string) => void }) {
  const isDocx = item.name.endsWith('.docx')
  const isHtml = item.name.endsWith('.html')
  return (
    <div style={{
      display: 'flex', alignItems: 'center', gap: 8, padding: '5px 0',
      borderBottom: '1px solid var(--border)',
    }}>
      <span style={{ fontSize: 10, width: 16, color: isDocx ? 'var(--accent)' : 'var(--green)', fontWeight: 700 }}>
        {isDocx ? 'W' : 'H'}
      </span>
      <span style={{ flex: 1, fontSize: 11, color: 'var(--text1)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
        {item.name}
      </span>
      {item.date && <span style={{ fontSize: 9, color: 'var(--text3)', width: 70 }}>{item.date}</span>}
      {item.time && <span style={{ fontSize: 9, color: 'var(--text3)', width: 35 }}>{item.time}</span>}
      <span style={{ fontSize: 9, color: 'var(--text3)', width: 45, textAlign: 'right' }}>{item.size_kb} KB</span>
      <div style={{ display: 'flex', gap: 4 }}>
        {isHtml && showPreview && (
          <button onClick={() => showPreview(BASE + item.path)} style={{
            fontSize: 9, padding: '2px 7px', border: '1px solid var(--border)', borderRadius: 3,
            background: 'var(--bg3)', color: 'var(--text2)', cursor: 'pointer', fontFamily: 'var(--mono)',
          }}>Preview</button>
        )}
        <a href={BASE + item.path} target="_blank" rel="noreferrer" style={{
          fontSize: 9, padding: '2px 7px', border: '1px solid var(--border)', borderRadius: 3,
          background: 'var(--bg3)', color: 'var(--accent)', textDecoration: 'none', fontFamily: 'var(--mono)',
        }}>{isDocx ? 'Download' : 'Open'}</a>
      </div>
    </div>
  )
}

export default function Reports() {
  const { data: resp } = useFetch<CatalogResp>('/api/reports/catalog')
  const [previewUrl, setPreviewUrl] = useState<string | null>(null)
  const cat = resp?.catalog

  const totalFiles = cat ? (
    cat.live.length + cat.trade_ai_daily.length + cat.portfolio_daily.length +
    cat.weekly.length + cat.monthly.length + cat.docx.length
  ) : 0

  return (
    <>
      <PageHeader title="Reports" subtitle={`${totalFiles} outputs cataloged`} />

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
            <MetricTile label="Live Dashboards" value={String(cat.live.length)} />
            <MetricTile label="Trade AI Daily" value={String(cat.trade_ai_daily.length)} />
            <MetricTile label="Portfolio Daily" value={String(cat.portfolio_daily.length)} />
            <MetricTile label="Weekly" value={String(cat.weekly.length)} />
            <MetricTile label="Monthly" value={String(cat.monthly.length)} />
            <MetricTile label="DOCX Exports" value={String(cat.docx.length)} />
          </div>

          {/* Live Dashboards */}
          <SectionHeader title="Live Dashboards" count={cat.live.length} />
          <Card>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(250px, 1fr))', gap: 10 }}>
              {cat.live.map(item => (
                <div key={item.name} style={{
                  padding: '10px 14px', background: 'var(--bg1)', border: '1px solid var(--border)',
                  borderRadius: 'var(--radius)', display: 'flex', flexDirection: 'column', gap: 4,
                }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                    <span style={{ fontWeight: 600, color: 'var(--text0)', fontSize: 12 }}>{item.name}</span>
                    <span style={{ fontSize: 8, color: 'var(--green)', fontWeight: 600, padding: '1px 5px', background: 'var(--green-dim)', borderRadius: 3 }}>LIVE</span>
                  </div>
                  <div style={{ fontSize: 9, color: 'var(--text3)' }}>
                    {item.size_kb} KB{item.modified ? ` | Updated ${item.modified.slice(0, 16)}` : ''}
                  </div>
                  <div style={{ display: 'flex', gap: 4, marginTop: 4 }}>
                    <button onClick={() => setPreviewUrl(BASE + item.path)} style={{
                      fontSize: 9, padding: '3px 10px', border: '1px solid var(--border)', borderRadius: 3,
                      background: 'var(--bg3)', color: 'var(--text2)', cursor: 'pointer', fontFamily: 'var(--mono)', flex: 1,
                    }}>Preview</button>
                    <a href={BASE + item.path} target="_blank" rel="noreferrer" style={{
                      fontSize: 9, padding: '3px 10px', border: '1px solid var(--accent)', borderRadius: 3,
                      background: 'var(--accent-dim)', color: 'var(--accent)', textDecoration: 'none',
                      fontFamily: 'var(--mono)', flex: 1, textAlign: 'center',
                    }}>Open</a>
                  </div>
                </div>
              ))}
            </div>
          </Card>

          {/* Trade AI Daily */}
          <SectionHeader title="Trade AI Daily Dashboards" count={cat.trade_ai_daily.length} />
          <Card>
            {cat.trade_ai_daily.map(item => (
              <ReportRow key={item.path} item={item} showPreview={setPreviewUrl} />
            ))}
          </Card>

          {/* Portfolio Daily */}
          <SectionHeader title="Portfolio Daily Dashboards" count={cat.portfolio_daily.length} />
          <Card>
            {cat.portfolio_daily.map(item => (
              <ReportRow key={item.path} item={item} showPreview={setPreviewUrl} />
            ))}
          </Card>

          {/* Weekly + Monthly side by side */}
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
            <div>
              <SectionHeader title="Weekly Reports" count={cat.weekly.length} />
              <Card>
                {cat.weekly.map(item => (
                  <ReportRow key={item.path} item={item} showPreview={item.type === 'html' ? setPreviewUrl : undefined} />
                ))}
              </Card>
            </div>
            <div>
              <SectionHeader title="Monthly Reports" count={cat.monthly.length} />
              <Card>
                {cat.monthly.map(item => (
                  <ReportRow key={item.path} item={item} showPreview={item.type === 'html' ? setPreviewUrl : undefined} />
                ))}
              </Card>
            </div>
          </div>

          {/* DOCX Exports */}
          <SectionHeader title="Document Exports (DOCX)" count={cat.docx.length} />
          <Card>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 0 }}>
              <div>
                <div style={{ fontSize: 10, color: 'var(--text3)', fontWeight: 600, padding: '4px 0', marginBottom: 4 }}>Portfolio Briefs</div>
                {cat.docx.filter(d => d.category === 'portfolio_brief').map(item => (
                  <ReportRow key={item.path} item={item} />
                ))}
              </div>
              <div>
                <div style={{ fontSize: 10, color: 'var(--text3)', fontWeight: 600, padding: '4px 0', marginBottom: 4 }}>Trade AI Reports</div>
                {cat.docx.filter(d => d.category === 'trade_ai').map(item => (
                  <ReportRow key={item.path} item={item} />
                ))}
              </div>
            </div>
          </Card>
        </>
      )}
    </>
  )
}
