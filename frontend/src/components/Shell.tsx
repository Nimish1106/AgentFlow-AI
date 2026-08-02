/**
 * Application shell: the left rail and the contextual top bar.
 *
 * The rail exists because an operations tool needs a sense of place. The
 * previous single-screen layout made "the approvals I have to action" something
 * you found by luck; here it is a destination with a live count.
 *
 * Four sections, each mapping to an endpoint that already exists. No invented
 * navigation.
 */

import type { ReactNode } from 'react'
import {
  Activity,
  GitBranch,
  Inbox,
  LayoutGrid,
  ShieldCheck,
} from 'lucide-react'

export type View = 'overview' | 'tickets' | 'workflows' | 'approvals'

const NAV: Array<{ id: View; label: string; icon: typeof Inbox }> = [
  { id: 'overview', label: 'Overview', icon: LayoutGrid },
  { id: 'tickets', label: 'Tickets', icon: Inbox },
  { id: 'workflows', label: 'Workflows', icon: GitBranch },
  { id: 'approvals', label: 'Approvals', icon: ShieldCheck },
]

export function Rail({
  view,
  onNavigate,
  pendingApprovals,
}: {
  view: View
  onNavigate: (view: View) => void
  pendingApprovals: number
}) {
  return (
    <nav
      aria-label="Sections"
      className="flex w-rail shrink-0 flex-col border-r border-line bg-sunken"
    >
      {/* Wordmark. The mark is a plain geometric glyph rather than a gradient
          logo - restraint here sets the tone for the whole product. */}
      <div className="flex h-topbar items-center gap-2 border-b border-line px-3">
        <span className="flex size-5 items-center justify-center rounded-xs bg-accent">
          <span className="size-1.5 rounded-full bg-white" />
        </span>
        <span className="text-data font-semibold tracking-tight text-fg">
          AgentFlow
        </span>
      </div>

      <div className="flex-1 overflow-y-auto py-2">
        <ul className="space-y-px px-2">
          {NAV.map((item) => {
            const Icon = item.icon
            const active = item.id === view
            const badge = item.id === 'approvals' ? pendingApprovals : 0
            return (
              <li key={item.id}>
                <button
                  type="button"
                  onClick={() => onNavigate(item.id)}
                  aria-current={active ? 'page' : undefined}
                  // Active lifts out of the gray rail as white with a hairline
                  // ring. A tinted fill was only a 3% step off the rail itself
                  // and did not read as selected.
                  className={`group flex h-7 w-full items-center gap-2 rounded-sm px-2 text-data transition-colors duration-100 ${
                    active
                      ? 'bg-raised font-medium text-fg ring-1 ring-line-strong/70'
                      : 'text-fg-muted hover:bg-hover hover:text-fg'
                  }`}
                >
                  <Icon
                    size={14}
                    className={active ? 'text-accent' : 'text-fg-faint'}
                    strokeWidth={2}
                  />
                  <span className="flex-1 text-left">{item.label}</span>
                  {badge > 0 ? (
                    <span className="tnum rounded-xs bg-attention-dim px-1 text-meta font-medium text-attention">
                      {badge}
                    </span>
                  ) : null}
                </button>
              </li>
            )
          })}
        </ul>
      </div>

      <EnvironmentFooter />
    </nav>
  )
}

/**
 * Names the environment being operated on.
 *
 * Deliberate: this UI has no authentication (SRS §43 specifies JWT and RBAC;
 * neither is implemented). Showing a fake user avatar would imply an identity
 * model that does not exist, so the footer states the environment instead.
 */
function EnvironmentFooter() {
  return (
    <div className="border-t border-line px-3 py-2">
      <div className="label-micro">Environment</div>
      <div className="mt-0.5 flex items-center gap-1.5">
        <span className="size-[5px] rounded-full bg-ok-solid" aria-hidden />
        <span className="text-meta text-fg-muted">Local · unauthenticated</span>
      </div>
    </div>
  )
}

/**
 * Top bar: page title, live-poll indicator, and the page's primary action.
 *
 * Fixed 52px so the rail header and content head align to the same baseline.
 */
export function TopBar({
  title,
  subtitle,
  live,
  actions,
}: {
  title: string
  subtitle?: string
  live?: { updatedAt: Date | null; refreshing: boolean; stale: boolean }
  actions?: ReactNode
}) {
  return (
    // The top bar is white, matching the panels rather than the gray canvas:
    // in light mode the chrome should read as a solid surface the content
    // scrolls beneath, not as more background.
    <header className="flex h-topbar shrink-0 items-center justify-between gap-4 border-b border-line bg-raised px-4">
      <div className="flex min-w-0 items-baseline gap-2.5">
        <h1 className="text-title font-semibold tracking-tight text-fg">{title}</h1>
        {subtitle ? (
          <span className="truncate text-data text-fg-subtle">{subtitle}</span>
        ) : null}
      </div>

      <div className="flex shrink-0 items-center gap-2">
        {live ? <LiveIndicator {...live} /> : null}
        {actions}
      </div>
    </header>
  )
}

/**
 * Poll status.
 *
 * Shows a real fault, not a decorative spinner: when a poll fails the data on
 * screen is stale, and the operator needs to know that before they act on it.
 */
function LiveIndicator({
  updatedAt,
  refreshing,
  stale,
}: {
  updatedAt: Date | null
  refreshing: boolean
  stale: boolean
}) {
  if (stale) {
    return (
      <span className="flex items-center gap-1.5 rounded-sm bg-failed-dim px-2 py-1 text-meta text-failed">
        <Activity size={11} strokeWidth={2.5} />
        Connection lost — data may be stale
      </span>
    )
  }
  return (
    <span className="flex items-center gap-1.5 text-meta text-fg-faint">
      <span
        className={`size-[5px] rounded-full ${refreshing ? 'bg-accent' : 'bg-ok-solid'}`}
        aria-hidden
      />
      {updatedAt
        ? `Updated ${updatedAt.toLocaleTimeString(undefined, {
            hour: '2-digit',
            minute: '2-digit',
            second: '2-digit',
          })}`
        : 'Connecting…'}
    </span>
  )
}
