/**
 * RouteErrorBoundary — a page that throws must say so, not disappear.
 *
 * Found by the browser/state matrix: `/v3/strategy` threw
 * `TypeError: m is not iterable` when one endpoint answered with an object where
 * the page assumed an array, and the ENTIRE shell rendered zero elements. A blank
 * page is the least honest possible state — it is indistinguishable from "no data",
 * from "still loading", and from "everything is fine and there is nothing to show".
 *
 * This boundary wraps each route element, so one page's failure is contained to
 * that page and is stated in words the operator can act on: which route, which
 * error, and that the data behind it was NOT read successfully.
 */

import { Component, type ErrorInfo, type ReactNode } from 'react'
import { BB, DASH } from '../../lib/watchTokens'

type Props = { route: string; children: ReactNode }
type State = { error: Error | null; info: string | null }

export default class RouteErrorBoundary extends Component<Props, State> {
  state: State = { error: null, info: null }

  static getDerivedStateFromError(error: Error): Partial<State> {
    return { error }
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    // Keep the stack in the console for the operator's own debugging; the surface
    // itself stays short and factual.
    console.error(`[route-error] ${this.props.route}:`, error, info.componentStack)
    this.setState({ info: (info.componentStack || '').split('\n').slice(0, 4).join('\n') })
  }

  render() {
    const { error, info } = this.state
    if (!error) return this.props.children

    return (
      <div
        data-route-error="true"
        data-route={this.props.route}
        role="alert"
        style={{
          display: 'grid',
          gap: 6,
          padding: '10px 12px',
          background: BB.redDim,
          borderLeft: `3px solid ${BB.red}`,
          fontSize: DASH.data,
          lineHeight: 1.5,
        }}
      >
        <div style={{ fontWeight: 800, letterSpacing: 0.4, color: BB.red }}>
          THIS PAGE FAILED TO RENDER — NO DATA ON THIS SCREEN IS TRUSTWORTHY
        </div>
        <div style={{ color: BB.text2 }}>
          Route <span style={{ fontFamily: 'var(--mono)' }}>{this.props.route}</span> threw while
          rendering. Nothing below was read successfully, so nothing is shown rather than showing a
          number whose source failed.
        </div>
        <div style={{ color: BB.text3, fontFamily: 'var(--mono)' }}>
          {error.name}: {error.message}
        </div>
        {info && (
          <div style={{ color: BB.text3, fontFamily: 'var(--mono)', whiteSpace: 'pre-wrap' }}>{info}</div>
        )}
        <div style={{ color: BB.text3 }}>
          The rest of the Command Center is unaffected — other routes still render.
        </div>
      </div>
    )
  }
}
