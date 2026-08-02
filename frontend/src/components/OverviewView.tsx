/**
 * Overview: the state of the system in one screen.
 *
 * Hierarchy is the point. The previous version showed six identical cards, so
 * nothing was more important than anything else and the eye had no entry point.
 * Here three figures carry the operational question — is work flowing, is
 * anyone blocked on me, how long is it taking — and the rest is a compact strip
 * of counters underneath.
 */

import { ArrowRight } from 'lucide-react'
import type { Metrics, WorkflowSummary } from '../api/types'
import { formatDurationTerse, formatCompactTime, formatRelative } from '../lib/format'
import {
  WORKFLOW_LABEL,
  WORKFLOW_SEMANTIC,
  SEMANTIC_FG,
} from '../lib/status'
import { Button, Empty, Panel, PanelHead, Status } from './primitives'
import type { View } from './Shell'

/**
 * A headline figure.
 *
 * `emphasis` is what makes the layout hierarchical rather than uniform: the
 * pending-approval count is the only figure that ever demands action, so it is
 * the only one that can change colour.
 */
function Figure({
  label,
  value,
  unit,
  note,
  tone = 'neutral',
  onClick,
}: {
  label: string
  value: string
  unit?: string
  note?: string
  tone?: 'neutral' | 'attention'
  onClick?: () => void
}) {
  const interactive = onClick !== undefined
  return (
    <div
      className={`relative flex flex-col justify-between px-4 py-3 ${
        interactive ? 'group cursor-pointer' : ''
      }`}
      onClick={onClick}
      role={interactive ? 'button' : undefined}
      tabIndex={interactive ? 0 : undefined}
      onKeyDown={
        interactive
          ? (event) => {
              if (event.key === 'Enter' || event.key === ' ') {
                event.preventDefault()
                onClick?.()
              }
            }
          : undefined
      }
    >
      <div className="flex items-center justify-between">
        <span className="label-micro">{label}</span>
        {interactive ? (
          <ArrowRight
            size={12}
            className="text-fg-faint opacity-0 transition-opacity group-hover:opacity-100"
          />
        ) : null}
      </div>
      <div className="mt-2 flex items-baseline gap-1">
        <span
          className={`tnum text-figure-lg font-semibold tracking-tight ${
            tone === 'attention' ? 'text-attention' : 'text-fg'
          }`}
        >
          {value}
        </span>
        {unit ? <span className="text-data text-fg-subtle">{unit}</span> : null}
      </div>
      <div className="mt-0.5 text-meta text-fg-faint">{note ?? ' '}</div>
    </div>
  )
}

/** Secondary counter in the strip beneath the headline figures. */
function Counter({ label, value, tone }: { label: string; value: number; tone?: string }) {
  return (
    <div className="flex items-baseline justify-between gap-3 px-3 py-2">
      <span className="text-data text-fg-subtle">{label}</span>
      <span className={`tnum text-data font-medium ${tone ?? 'text-fg'}`}>{value}</span>
    </div>
  )
}

export function OverviewView({
  metrics,
  workflows,
  loading,
  onNavigate,
  onOpenWorkflow,
}: {
  metrics: Metrics | null
  workflows: WorkflowSummary[]
  loading: boolean
  onNavigate: (view: View) => void
  onOpenWorkflow: (workflowId: string) => void
}) {
  const m: Metrics =
    metrics ?? {
      active_workflows: 0,
      pending_hitl_approvals: 0,
      avg_execution_time_ms: null,
      completed_workflows: 0,
      failed_workflows: 0,
      open_tickets: 0,
    }

  const needsReview = workflows.filter((w) => w.requires_hitl)
  const recent = workflows.slice(0, 12)

  return (
    <div className="mx-auto max-w-[92rem] space-y-3 p-4">
      {/* Headline figures. Divided by hairlines rather than gaps so they read as
          one instrument cluster instead of three floating cards. */}
      <Panel className="overflow-hidden">
        <div className="grid grid-cols-1 divide-y divide-line sm:grid-cols-3 sm:divide-x sm:divide-y-0">
          {loading && !metrics ? (
            <>
              {Array.from({ length: 3 }).map((_, i) => (
                <div key={i} className="px-4 py-3">
                  <div className="skeleton h-2 w-20 rounded-xs" />
                  <div className="skeleton mt-3 h-7 w-16 rounded-xs" />
                  <div className="skeleton mt-2 h-2 w-24 rounded-xs" />
                </div>
              ))}
            </>
          ) : (
            <>
              <Figure
                label="Active workflows"
                value={String(m.active_workflows)}
                note={
                  m.active_workflows === 0
                    ? 'Nothing executing'
                    : 'Queued or executing now'
                }
                onClick={() => onNavigate('workflows')}
              />
              <Figure
                label="Awaiting review"
                value={String(m.pending_hitl_approvals)}
                note={
                  m.pending_hitl_approvals === 0
                    ? 'No decisions pending'
                    : 'Blocked until a reviewer decides'
                }
                tone={m.pending_hitl_approvals > 0 ? 'attention' : 'neutral'}
                onClick={() => onNavigate('approvals')}
              />
              <Figure
                label="Median resolution"
                value={
                  m.avg_execution_time_ms === null
                    ? '—'
                    : formatDurationTerse(m.avg_execution_time_ms).replace(
                        /[a-z]+$/,
                        '',
                      )
                }
                unit={
                  m.avg_execution_time_ms === null
                    ? undefined
                    : (formatDurationTerse(m.avg_execution_time_ms).match(
                        /[a-z]+$/,
                      )?.[0] ?? undefined)
                }
                note="Mean across completed runs"
              />
            </>
          )}
        </div>
      </Panel>

      <div className="grid grid-cols-1 gap-3 lg:grid-cols-[1fr_18rem]">
        {/* Recent activity. A table, not cards: this is a log, and a log reads
            fastest as aligned rows. */}
        <Panel className="overflow-hidden">
          <PanelHead
            title="Recent workflows"
            meta={workflows.length ? `${workflows.length} shown` : undefined}
            actions={
              <Button size="sm" variant="quiet" onClick={() => onNavigate('workflows')}>
                View all
              </Button>
            }
          />
          {recent.length === 0 && !loading ? (
            <Empty
              title="No workflows yet"
              hint="Submit a ticket to start the first workflow."
            />
          ) : (
            <table className="w-full text-data">
              <tbody>
                {recent.map((workflow) => {
                  const semantic = WORKFLOW_SEMANTIC[workflow.workflow_status]
                  return (
                    <tr
                      key={workflow.workflow_id}
                      onClick={() => onOpenWorkflow(workflow.workflow_id)}
                      className="cursor-pointer border-b border-line last:border-0 hover:bg-hover"
                    >
                      <td className="h-row max-w-0 px-3">
                        <div className="truncate text-fg">{workflow.ticket_title}</div>
                      </td>
                      <td className="h-row w-40 px-3 text-fg-muted">
                        <div className="truncate">{workflow.customer_name}</div>
                      </td>
                      <td className="h-row w-32 px-3">
                        <Status semantic={semantic}>
                          {WORKFLOW_LABEL[workflow.workflow_status]}
                        </Status>
                      </td>
                      <td className="h-row w-20 px-3 text-right tnum text-fg-muted">
                        {formatDurationTerse(workflow.duration_ms)}
                      </td>
                      <td className="h-row w-20 px-3 text-right tnum text-fg-faint">
                        {formatCompactTime(workflow.started_at)}
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          )}
        </Panel>

        <div className="space-y-3">
          {/* Attention block. Only rendered when something actually needs a
              person — an empty "0 pending" card is noise. */}
          {needsReview.length > 0 ? (
            <Panel className="overflow-hidden border-attention/25">
              <div className="flex items-center gap-2 border-b border-attention/30 bg-attention-dim px-3 py-2">
                <span className="size-[5px] rounded-full bg-attention-solid" aria-hidden />
                <span className="text-data font-medium text-attention">
                  {needsReview.length} awaiting your decision
                </span>
              </div>
              <ul>
                {needsReview.slice(0, 5).map((workflow) => (
                  <li key={workflow.workflow_id}>
                    <button
                      type="button"
                      onClick={() => onOpenWorkflow(workflow.workflow_id)}
                      className="flex w-full flex-col items-start gap-0.5 border-b border-line px-3 py-2 text-left last:border-0 hover:bg-hover"
                    >
                      <span className="w-full truncate text-data text-fg">
                        {workflow.ticket_title}
                      </span>
                      <span className="text-meta text-fg-subtle">
                        {workflow.customer_name} · {formatRelative(workflow.started_at)}
                      </span>
                    </button>
                  </li>
                ))}
              </ul>
              {needsReview.length > 5 ? (
                <div className="border-t border-line px-3 py-1.5">
                  <Button size="sm" variant="quiet" onClick={() => onNavigate('approvals')}>
                    {needsReview.length - 5} more
                  </Button>
                </div>
              ) : null}
            </Panel>
          ) : null}

          <Panel className="overflow-hidden">
            <PanelHead title="Totals" />
            <div className="divide-y divide-line">
              <Counter label="Completed" value={m.completed_workflows} />
              <Counter
                label="Failed"
                value={m.failed_workflows}
                tone={m.failed_workflows > 0 ? SEMANTIC_FG.failed : undefined}
              />
              <Counter label="Open tickets" value={m.open_tickets} />
            </div>
          </Panel>
        </div>
      </div>
    </div>
  )
}
