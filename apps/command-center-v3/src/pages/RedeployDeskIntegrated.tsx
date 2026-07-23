import { useMemo, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import AuthoritativeExitUniverse from '../components/reentry/AuthoritativeExitUniverse'
import ReEntryAnalystEvidence from '../components/reentry/ReEntryAnalystEvidence'
import ReEntryAnalystLookthroughBoard from '../components/reentry/ReEntryAnalystLookthroughBoard'
import ReEntryExitDetailLedger from '../components/reentry/ReEntryExitDetailLedger'
import ReEntryHelpGuide from '../components/reentry/ReEntryHelpGuide'
import ReEntryResistanceBoard from '../components/reentry/ReEntryResistanceBoard'
import ReEntryRotationWorkspace from '../components/reentry/ReEntryRotationWorkspace'
import { BB } from '../lib/holdingsTerminalTokens'
import RedeployDesk from './RedeployDesk'

export default function RedeployDeskIntegrated() {
  const [params] = useSearchParams()
  const eventId = useMemo(() => {
    const raw = Number(params.get('event') || 0)
    return Number.isFinite(raw) && raw > 0 ? raw : null
  }, [params])
  const [open, setOpen] = useState(false)

  return (
    <>
      <RedeployDesk />
      <button
        type="button"
        onClick={() => setOpen(true)}
        title={eventId ? `Open shared Re-Entry / Rotation workflow for event #${eventId}` : 'Select a Redeploy event, then open the shared Re-Entry / Rotation workflow'}
        style={{
          position: 'fixed', right: 24, bottom: 24, zIndex: 900,
          border: `1px solid ${eventId ? BB.amber : BB.text3}`,
          background: BB.bgRowAlt, color: eventId ? BB.amber : BB.text3,
          borderRadius: 6, padding: '9px 14px', fontSize: 11, fontWeight: 900,
          cursor: 'pointer', boxShadow: '0 10px 30px rgba(0,0,0,.35)',
        }}
      >
        RE-ENTRY / ROTATION{eventId ? ` · EVENT #${eventId}` : ''}
      </button>
      {open && (
        <div
          role="dialog"
          aria-modal="true"
          onMouseDown={() => setOpen(false)}
          style={{ position: 'fixed', inset: 0, zIndex: 1100, background: 'rgba(2,6,23,.86)', padding: 18, overflowY: 'auto' }}
        >
          <div onMouseDown={event => event.stopPropagation()} style={{ maxWidth: 1700, margin: '0 auto', background: 'var(--bg0)', border: '1px solid var(--border)', borderRadius: 8, padding: 16 }}>
            <div style={{ display: 'flex', justifyContent: 'flex-end', marginBottom: 8 }}>
              <button onClick={() => setOpen(false)} style={{ fontSize: 10.5, fontWeight: 800, padding: '6px 10px', borderRadius: 5, cursor: 'pointer', border: '1px solid var(--border)', background: 'var(--bg2)', color: 'var(--text2)' }}>CLOSE</button>
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
              <ReEntryHelpGuide compact />
              <AuthoritativeExitUniverse />
              <ReEntryExitDetailLedger />
              <ReEntryAnalystEvidence />
              <ReEntryResistanceBoard />
              <ReEntryAnalystLookthroughBoard />
              <ReEntryRotationWorkspace mode="bridge" eventId={eventId} />
            </div>
          </div>
        </div>
      )}
    </>
  )
}
