import { FONT, TOKENS, TYPE } from '../lib/designTokens'
import type { AnswerSource } from '../lib/askCioModel'
import { answerSourceTime } from '../lib/askCioPresentation'

/** One readable answer on both surfaces; all prose comes verbatim from the canonical backend field. */
export default function AskCioAnswer({ text, sources = [], testId }: { text: string; sources?: AnswerSource[]; testId: string }) {
  return <div style={{ minWidth: 0 }}>
    <div data-testid={testId} style={{ margin: 0, whiteSpace: 'pre-wrap', overflowWrap: 'anywhere', fontFamily: FONT.sans, fontSize: TYPE.base, color: TOKENS.text[0], lineHeight: 1.6 }}>{text}</div>
    {sources.length > 0 && <details data-testid="ask-answer-sources" style={{ marginTop: 12, fontSize: TYPE.sm }}>
      <summary style={{ cursor: 'pointer', color: TOKENS.text[2], padding: '6px 0' }}>How I know this ({sources.length})</summary>
      <ul style={{ margin: '6px 0 0', paddingLeft: 18, display: 'grid', gap: 8, overflowWrap: 'anywhere' }}>{sources.map((source, index) => <li key={index}>
        {source.url && /^https?:\/\//i.test(source.url) ? <a href={source.url} target="_blank" rel="noreferrer" style={{ color: TOKENS.info }}>{source.title}</a> : source.title}
        {source.as_of && <span style={{ color: TOKENS.text[2] }}> · observed {answerSourceTime(source.as_of)}</span>}
      </li>)}</ul>
    </details>}
  </div>
}
