import { useState } from 'react'
import PageHeader from '../components/PageHeader'
import Card from '../components/Card'
import SectionHeader from '../components/SectionHeader'
import DataGrid from '../components/DataGrid'
import { useApi } from '../hooks/useApi'
import { timeAgo } from '../lib/format'
import type { Notification } from '../lib/types'

interface NotifData { count: number; notifications: Notification[] }

const channelColors: Record<string, string> = {
  telegram: 'var(--accent)', gmail: 'var(--amber)', dashboard: 'var(--text2)',
}
const typeColors: Record<string, string> = {
  urgent_alert: 'var(--red)', draft_alert: 'var(--amber)', stale_data_alert: 'var(--amber)',
  daily_digest: 'var(--accent)', info: 'var(--text2)',
}

export default function Notifications() {
  const { data: resp } = useApi<NotifData>('/api/v2/notifications/recent')
  const [selected, setSelected] = useState<Notification | null>(null)
  const [channelFilter, setChannelFilter] = useState<string>('all')

  const notifications = resp?.notifications ?? []
  const filtered = channelFilter === 'all' ? notifications : notifications.filter(n => n.channel === channelFilter)
  const channels = ['all', ...Array.from(new Set(notifications.map(n => n.channel)))]

  // Stats
  const byChannel: Record<string, number> = {}
  const byType: Record<string, number> = {}
  for (const n of notifications) {
    byChannel[n.channel] = (byChannel[n.channel] || 0) + 1
    byType[n.notification_type] = (byType[n.notification_type] || 0) + 1
  }

  const columns = [
    { key: 'channel', label: 'Channel', width: 70, render: (r: Notification) => (
      <span style={{ fontSize: 10, fontWeight: 600, color: channelColors[r.channel] || 'var(--text2)' }}>{r.channel}</span>
    )},
    { key: 'notification_type', label: 'Type', width: 100, render: (r: Notification) => (
      <span style={{ fontSize: 9, padding: '1px 6px', borderRadius: 3, fontWeight: 600,
        background: `color-mix(in srgb, ${typeColors[r.notification_type] || 'var(--text3)'} 15%, transparent)`,
        color: typeColors[r.notification_type] || 'var(--text3)',
      }}>{r.notification_type.replace(/_/g, ' ')}</span>
    )},
    { key: 'subject', label: 'Subject', render: (r: Notification) => (
      <span style={{ color: 'var(--text0)' }}>{r.subject}</span>
    )},
    { key: 'status', label: 'Status', width: 50, render: (r: Notification) => (
      <span style={{ fontSize: 10, fontWeight: 600, color: r.status === 'sent' ? 'var(--green)' : r.status === 'failed' ? 'var(--red)' : 'var(--text3)' }}>{r.status}</span>
    )},
    { key: 'sent_at', label: 'Time', width: 65, render: (r: Notification) => (
      <span style={{ fontSize: 10, color: 'var(--text3)' }}>{r.sent_at ? timeAgo(r.sent_at) : '—'}</span>
    )},
  ]

  return (
    <>
      <PageHeader title="Notification Log" subtitle={`${notifications.length} entries · telegram+export = sent to Telegram AND exported to Word report. Draft = queued for next batch. Urgent = sent immediately.`} />

      {/* Stats strip */}
      <div style={{ display: 'flex', gap: 16, marginBottom: 14 }}>
        {Object.entries(byChannel).map(([ch, count]) => (
          <div key={ch} style={{ display: 'flex', alignItems: 'center', gap: 4, fontSize: 11 }}>
            <span style={{ width: 8, height: 8, borderRadius: '50%', background: channelColors[ch] || 'var(--text3)' }} />
            <span style={{ color: 'var(--text2)' }}>{ch}</span>
            <span style={{ fontWeight: 600, color: 'var(--text0)' }}>{count}</span>
          </div>
        ))}
      </div>

      {/* Channel filter */}
      <div style={{ display: 'flex', gap: 4, marginBottom: 10 }}>
        {channels.map(ch => (
          <button key={ch} onClick={() => setChannelFilter(ch)} style={{
            padding: '3px 10px', fontSize: 10, border: '1px solid var(--border)', borderRadius: 'var(--radius)',
            background: channelFilter === ch ? 'var(--accent-dim)' : 'var(--bg2)',
            color: channelFilter === ch ? 'var(--accent)' : 'var(--text2)',
            cursor: 'pointer', fontFamily: 'var(--mono)',
          }}>
            {ch === 'all' ? 'All' : ch}
          </button>
        ))}
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: selected ? '1fr 360px' : '1fr', gap: 12 }}>
        <DataGrid
          columns={columns}
          data={filtered}
          rowKey={(r: Notification) => r.sent_at + r.subject}
          onRowClick={(r: Notification) => setSelected(r.subject === selected?.subject ? null : r)}
          selectedKey={selected ? selected.sent_at + selected.subject : undefined}
          maxHeight={400}
        />

        {selected && (
          <Card title={selected.subject} subtitle={selected.notification_type.replace(/_/g, ' ')}>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 8, fontSize: 11 }}>
              <Row label="Channel" value={selected.channel} />
              <Row label="Type" value={selected.notification_type} />
              <Row label="Status" value={selected.status} />
              <Row label="Date" value={selected.notification_date} />
              <Row label="Sent" value={selected.sent_at || '—'} />
              {selected.body_summary && (
                <div>
                  <div style={{ fontSize: 9, color: 'var(--text3)', marginBottom: 4 }}>Summary</div>
                  <div style={{ color: 'var(--text1)', lineHeight: 1.5, whiteSpace: 'pre-wrap' }}>{selected.body_summary}</div>
                </div>
              )}
            </div>
          </Card>
        )}
      </div>

      {/* Type breakdown */}
      <SectionHeader title="By Type" />
      <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap' }}>
        {Object.entries(byType).map(([type, count]) => (
          <Card key={type} title={type.replace(/_/g, ' ')} subtitle={String(count)}>
            <div style={{ fontSize: 20, fontWeight: 700, color: typeColors[type] || 'var(--text1)' }}>{count}</div>
          </Card>
        ))}
      </div>
    </>
  )
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div style={{ display: 'flex', gap: 8 }}>
      <span style={{ width: 60, color: 'var(--text3)', fontSize: 10, flexShrink: 0 }}>{label}</span>
      <span style={{ color: 'var(--text1)' }}>{value}</span>
    </div>
  )
}
