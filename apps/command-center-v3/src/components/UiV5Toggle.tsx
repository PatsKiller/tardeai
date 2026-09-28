/** ui_v5 toggle (PR4, 2026-09-28) — the operator's switch for the redesigned surfaces.
 *  Writes the same pref uiV5.ts reads (localStorage + /api/v2/ui/prefs key ui.v5), so turning
 *  it off restores the v4 cards everywhere without a release (rollback layer 1). */
import { useUiV5 } from '../lib/uiV5'
import { RADIUS, TOKENS, TYPE, toneVars } from '../lib/designTokens'

export default function UiV5Toggle({ label = 'Redesigned cards' }: { label?: string }) {
  const [on, setOn] = useUiV5()
  const t = toneVars(on ? 'ai' : 'neutral')
  return (
    <button type="button" onClick={() => setOn(!on)} aria-pressed={on} title="Switch between the v5 (redesign) and v4 cards; ?ui=v4 / ?ui=v5 in the URL overrides per tab"
      style={{ fontFamily: 'inherit', fontSize: TYPE.xs, fontWeight: 800, letterSpacing: '.04em', padding: '2px 8px', borderRadius: RADIUS.pill, cursor: 'pointer',
        background: t.bg, color: t.color, border: `1px solid ${t.border}`, display: 'inline-flex', gap: 6, alignItems: 'center' }}>
      <span aria-hidden style={{ width: 8, height: 8, borderRadius: RADIUS.pill, background: on ? t.color : TOKENS.text[3] }} />
      {label}: {on ? 'v5' : 'v4'}
    </button>
  )
}
