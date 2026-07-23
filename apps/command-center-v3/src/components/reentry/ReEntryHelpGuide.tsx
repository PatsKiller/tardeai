import { useState, type CSSProperties } from 'react'
import { BB } from '../../lib/holdingsTerminalTokens'

const panel: CSSProperties = { background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 8 }

export function HelpTip({ text }: { text: string }) {
  return <span title={text} aria-label={text} style={{ display: 'inline-grid', placeItems: 'center', width: 16, height: 16, marginLeft: 5, borderRadius: 999, border: '1px solid var(--border)', color: BB.blue, fontSize: 10, fontWeight: 900, cursor: 'help', verticalAlign: 'middle' }}>?</span>
}

const steps = [
  {
    title: '1 · Review the exit facts',
    body: 'Shares, proceeds and average exit price are calculated automatically from all real-account exit transactions. Expand a symbol to audit the individual broker rows.',
  },
  {
    title: '2 · Decide whether it matters',
    body: 'Save/monitor long-term exits. Suppress momentum scalps or day trades that should not remain in the re-entry queue. Suppression hides the item; it does not delete broker history.',
  },
  {
    title: '3 · Classify the investment intent',
    body: 'Mandate and strategy flags are manual and persistent. The flags are multi-selectable. Event classification stays separate because one symbol can have different exit reasons over time.',
  },
  {
    title: '4 · Link and monitor a rotation',
    body: 'The system may suggest a same-account destination, but the operator must confirm the source-to-destination capital lineage. Once a confirmed link has an armed six-gate monitor, the 20-minute RTH evaluator checks it automatically and sends an advisory alert when every gate passes. It never moves capital or places the rotation-back order.',
  },
]

export default function ReEntryHelpGuide({ compact = false }: { compact?: boolean }) {
  const [open, setOpen] = useState(!compact)
  return <div style={{ ...panel, padding: 10, borderColor: BB.blue }}>
    <div style={{ display: 'flex', gap: 10, alignItems: 'center', flexWrap: 'wrap' }}>
      <div style={{ flex: 1 }}>
        <div style={{ fontSize: 13, fontWeight: 900, color: BB.blue }}>HOW TO USE RE-ENTRY + ROTATION</div>
        <div style={{ fontSize: 10, color: BB.text3 }}>Automatic evidence · manual classification and lineage · automatic advisory monitoring · manual execution</div>
      </div>
      <button onClick={() => setOpen(value => !value)} title="Open the operating guide for this page" style={{ fontSize: 10.5, fontWeight: 850, padding: '5px 10px', borderRadius: 5, cursor: 'pointer', border: `1px solid ${BB.blue}`, background: BB.blueDim, color: BB.blue }}>{open ? 'HIDE GUIDE' : 'SHOW GUIDE'}</button>
    </div>
    {open && <>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(230px,1fr))', gap: 8, marginTop: 9 }}>
        {steps.map(step => <div key={step.title} style={{ ...panel, padding: 9, background: 'var(--bg2)' }}><div style={{ fontSize: 10.5, fontWeight: 900 }}>{step.title}</div><div style={{ fontSize: 10, color: BB.text3, lineHeight: 1.45, marginTop: 4 }}>{step.body}</div></div>)}
      </div>
      <div style={{ marginTop: 8, padding: '7px 9px', border: `1px solid ${BB.amber}`, borderRadius: 5, color: BB.amber, fontSize: 10.5 }}>
        An alert means “review the rotation back now,” not “buy automatically.” Confirm tax, wash-sale, settlement, account capacity, sizing and the current entry plan before any order.
      </div>
    </>}
  </div>
}
