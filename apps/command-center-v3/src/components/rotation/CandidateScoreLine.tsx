/**
 * One candidate's score line — Trim score / Add score / Confidence (RR-004).
 *
 * The values and their states come from lib/rotationScores.scoreView: a real 0 renders as 0, a
 * missing number renders as "unavailable" with the reason in the title, and the stop-driven note
 * sits *beside* the zero instead of replacing it. This component exists so the rendered contract
 * can be proven hermetically without booting the whole page.
 */
import { scoreView, scoreTitle } from '../../lib/rotationScores'
import { BB } from '../../lib/holdingsTerminalTokens'

export function CandidateScoreLine({ candidate }: { candidate: unknown }) {
  const sv = scoreView(candidate)
  return (
    <>
      {sv.parts.map(part => (
        <span key={part.key} data-score={part.key} data-score-state={part.state} title={scoreTitle(part)}
          style={{ color: part.state === 'unavailable' ? 'var(--text3)'
            : part.state === 'zero' ? 'var(--text3)'
            : part.key === 'add' ? BB.green : undefined }}>
          {part.text}
        </span>
      ))}
      {sv.stopDriven && <span data-score-note="stop-driven" style={{ color: BB.red }}
        title="The valuation trim score is 0; the rotate-out signal is the Aegis stop/thesis status, not the valuation engine">stop-driven</span>}
    </>
  )
}

export default CandidateScoreLine
