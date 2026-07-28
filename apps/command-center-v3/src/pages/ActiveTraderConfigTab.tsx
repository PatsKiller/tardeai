import { useApi } from '../hooks/useApi';

// Configuration subtab — read-only reconciliation viewer for the Active Trader / momentum-scalp config.
// Basic view; the full 8-panel build renders drift/stale/posture in richer form. No write controls, no secrets.
export default function ActiveTraderConfigTab() {
  const { data, error } = useApi<any>('/api/v3/active-trader/config', 30_000);
  if (error) return <Panel><div style={{ color: 'var(--red)' }}>Config API unavailable — {String(error)}</div></Panel>;
  if (!data) return <Panel><div style={{ color: 'var(--text3)' }}>Loading configuration…</div></Panel>;
  if (data.db_available === false) return <Panel><div style={{ color: 'var(--amber)' }}>Config DB unavailable — showing nothing rather than fabricating.</div></Panel>;

  const reg = data.strategy_registry?.strategies ?? data.strategy_registry?.rows ?? [];
  const posture = data.execution_posture ?? {};
  const prov = data.provenance ?? {};
  const mono = { fontFamily: 'ui-monospace, Menlo, monospace' } as const;

  return (
    <div style={{ display: 'grid', gap: 14 }}>
      <Panel title="Strategy registry">
        <div style={{ overflowX: 'auto' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
            <thead><tr style={{ color: 'var(--text3)', textAlign: 'left' }}>
              <th style={th}>strategy</th><th style={th}>state</th><th style={th}>gate</th><th style={th}>file</th><th style={th}>drift</th>
            </tr></thead>
            <tbody>
              {reg.map((s: any) => (
                <tr key={s.key ?? s.strategy} style={{ borderTop: '1px solid var(--border)' }}>
                  <td style={{ ...td, ...mono, color: 'var(--text0)' }}>{s.key ?? s.strategy}</td>
                  <td style={td}>{s.state ?? (s.active ? 'active' : 'inactive')}</td>
                  <td style={td}>{s.review_gate?.gate_met === false ? 'not met' : s.review_gate?.gate_met === true ? 'met' : '—'}</td>
                  <td style={{ ...td, ...mono, color: 'var(--text3)' }}>{s.config_file ?? '—'}</td>
                  <td style={td}>{s.drift && (Array.isArray(s.drift) ? s.drift.length : Object.keys(s.drift).length)
                    ? <span style={{ color: 'var(--amber)', fontWeight: 700 }}>⚠ drift</span> : '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Panel>

      <Panel title="Execution posture">
        <div style={{ display: 'grid', gap: 6, fontSize: 13 }}>
          {posture.standing_db_unlock && (
            <div><b style={{ color: 'var(--text1)' }}>standing_db_unlock:</b> {posture.standing_db_unlock.scope ?? 'unknown'} · routable: {(posture.standing_db_unlock.routable_accounts ?? []).join(', ') || '—'}</div>
          )}
          {Object.entries(posture.flags ?? {}).map(([k, v]: [string, any]) => (
            <div key={k} style={mono}><span style={{ color: 'var(--text3)' }}>{k}</span> = <span style={{ color: 'var(--text0)' }}>{String(v?.value ?? v)}</span></div>
          ))}
          <div style={{ marginTop: 8, color: 'var(--text3)' }}>credential slots (name · populated — values never shown):</div>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
            {(posture.credential_slots ?? []).map((c: any) => (
              <span key={c.name} style={{ ...mono, fontSize: 12, padding: '3px 8px', borderRadius: 6, border: '1px solid var(--border)', color: c.populated ? 'var(--green)' : 'var(--text3)' }}>
                {c.name} {c.populated ? '●' : '○'}
              </span>
            ))}
          </div>
        </div>
      </Panel>

      <Panel>
        <div style={{ fontSize: 11, color: 'var(--text3)', ...mono }}>
          config {prov.config_commit_sha ?? '—'} · tree {prov.working_tree_clean === false ? 'DIRTY' : 'clean'} · fetched {prov.fetched_at ?? data.generated_at ?? '—'} · read-only, no write path, no secrets rendered
        </div>
      </Panel>
    </div>
  );
}

const th = { padding: '6px 10px', fontWeight: 600, fontSize: 12 } as const;
const td = { padding: '6px 10px', color: 'var(--text2)' } as const;

function Panel({ title, children }: { title?: string; children: React.ReactNode }) {
  return (
    <section style={{ border: '1px solid var(--border)', borderRadius: 14, padding: 18, background: 'var(--bg1)' }}>
      {title && <h2 style={{ margin: '0 0 12px', fontSize: 16, color: 'var(--text0)' }}>{title}</h2>}
      {children}
    </section>
  );
}
