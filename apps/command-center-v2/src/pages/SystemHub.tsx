import PageHeader from '../components/PageHeader'
import Card from '../components/Card'
import SectionHeader from '../components/SectionHeader'
import { Link } from 'react-router-dom'

const sections = [
  {
    title: 'Portfolio Intelligence',
    links: [
      { to: '/', label: 'Overview', desc: 'Portfolio summary, returns, top movers' },
      { to: '/portfolio', label: 'Holdings', desc: '46 positions across 4 accounts' },
      { to: '/watchlist', label: 'Watchlist Workbench', desc: '53 symbols, strategy cards, agent analysis, synthesis' },
      { to: '/cio', label: 'CIO Dashboard', desc: 'CIO decisions, rotations, rebalance plans, MARL' },
      { to: '/risk', label: 'Risk Management', desc: 'Stops, risk levels, position sizing' },
      { to: '/retirement', label: 'Retirement', desc: 'Income goals, golden window, 401k loan tracker' },
    ],
  },
  {
    title: 'Analysis & Research',
    links: [
      { to: '/ai-analyst', label: 'AI Analyst', desc: 'AI-generated portfolio analysis' },
      { to: '/research', label: 'Research', desc: 'Ticker research cards' },
      { to: '/technical', label: 'Technical', desc: 'Technical signals, SMA, RSI' },
      { to: '/attribution', label: 'Attribution', desc: 'Performance attribution vs benchmark' },
      { to: '/correlation', label: 'Correlation', desc: 'Cross-asset correlation matrix' },
      { to: '/forecast', label: 'Forecast', desc: 'Forward projections' },
    ],
  },
  {
    title: 'Income & Tax',
    links: [
      { to: '/dividends', label: 'Dividends', desc: 'Dividend calendar, yield tracking' },
      { to: '/tax', label: 'Tax & Lots', desc: 'Tax lot detail, harvest opportunities' },
      { to: '/rebalance', label: 'Rebalance', desc: 'Rebalance suggestions' },
      { to: '/returns', label: 'Returns', desc: 'Period returns by account' },
    ],
  },
  {
    title: 'Operations & System',
    links: [
      { to: '/system-health', label: 'System Health', desc: 'LLM router, screeners, DB state, budget' },
      { to: '/approvals', label: 'Approvals', desc: 'Pending decisions, human review queue' },
      { to: '/actions', label: 'Action Center', desc: 'Queued actions and alerts' },
      { to: '/alerts', label: 'Alerts', desc: 'Alert timeline' },
      { to: '/reports', label: 'Reports', desc: 'Generated reports' },
      { to: '/ops', label: 'Ops', desc: 'Pipeline operations, orchestration' },
      { to: '/recovery', label: 'Recovery Watch', desc: 'Stopped-out recovery tracking' },
    ],
  },
  {
    title: 'Journal',
    links: [
      { to: '/journal', label: 'Trade Journal', desc: 'Trade log and reviews' },
      { to: '/journal-analytics', label: 'Journal Analytics', desc: 'Win rate, P&L analysis' },
      { to: '/morning-brief', label: 'Morning Brief', desc: 'Daily portfolio brief' },
    ],
  },
]

export default function SystemHub() {
  return (
    <>
      <PageHeader title="Trade AI Command Center" subtitle="Master system hub — all pages, APIs, and tools" />

      {sections.map(sec => (
        <Card key={sec.title}>
          <SectionHeader title={sec.title} count={sec.links.length} />
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 8, padding: '8px 12px' }}>
            {sec.links.map(l => (
              <Link key={l.to} to={l.to} style={{ textDecoration: 'none', padding: '10px 12px', borderRadius: 8, background: 'rgba(255,255,255,0.02)', border: '1px solid var(--border-subtle)', display: 'block' }}>
                <div style={{ fontWeight: 700, color: 'var(--accent)', fontSize: 12 }}>{l.label}</div>
                <div style={{ color: 'var(--text3)', fontSize: 9, marginTop: 2 }}>{l.desc}</div>
              </Link>
            ))}
          </div>
        </Card>
      ))}

      <Card>
        <SectionHeader title="External Links" />
        <div style={{ padding: 12, display: 'flex', gap: 12, flexWrap: 'wrap' }}>
          {[
            { href: 'https://finviz.com/screener.ashx', label: 'Finviz Screener' },
            { href: 'https://console.x.ai', label: 'Grok Console (xAI)' },
            { href: 'https://console.anthropic.com', label: 'Anthropic Console' },
            { href: 'https://platform.openai.com', label: 'OpenAI Platform' },
          ].map(l => (
            <a key={l.href} href={l.href} target="_blank" rel="noreferrer"
               style={{ fontSize: 10, color: 'var(--accent)', padding: '6px 12px', border: '1px solid rgba(255,255,255,0.08)', borderRadius: 8, textDecoration: 'none' }}>
              {l.label}
            </a>
          ))}
        </div>
      </Card>
    </>
  )
}
