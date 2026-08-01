/**
 * AgentFlow operations control center.
 *
 * Composes the four Phase 7 views: the ticket/workflow hub, the live execution
 * trace, the HITL approval drawer and the ingestion simulator. All data arrives
 * by polling - the backend has no push channel.
 */

import { useCallback, useMemo, useState } from 'react'
import { Activity, PlusCircle, RefreshCw, ShieldAlert, Workflow } from 'lucide-react'
import { api } from './api/client'
import type { TicketStatus, TicketSummary } from './api/types'
import { ApprovalDrawer } from './components/ApprovalDrawer'
import { ExecutionTrace } from './components/ExecutionTrace'
import { MetricsBar } from './components/MetricsBar'
import { TicketSimulator } from './components/TicketSimulator'
import { TicketsTable } from './components/TicketsTable'
import { Button, ErrorNote } from './components/ui'
import { usePolling } from './hooks/usePolling'
import { formatTime } from './lib/format'

const POLL_INTERVAL_MS = Number(import.meta.env.VITE_POLL_INTERVAL_MS ?? 4000)
/** The trace refreshes faster: it is what someone watches a run through. */
const TRACE_POLL_INTERVAL_MS = 2000

export default function App() {
  const [statusFilter, setStatusFilter] = useState<TicketStatus | 'all'>('all')
  const [selected, setSelected] = useState<TicketSummary | null>(null)
  const [reviewWorkflowId, setReviewWorkflowId] = useState<string | null>(null)
  const [simulatorOpen, setSimulatorOpen] = useState(false)

  const metrics = usePolling((signal) => api.getMetrics(signal), POLL_INTERVAL_MS)

  const tickets = usePolling(
    (signal) => api.listTickets({ status: statusFilter, limit: 100, signal }),
    POLL_INTERVAL_MS,
    [statusFilter],
  )

  const selectedWorkflowId = selected?.workflow_id ?? null
  const trace = usePolling(
    (signal) =>
      selectedWorkflowId
        ? api.getWorkflowTrace(selectedWorkflowId, signal)
        : Promise.resolve(null),
    TRACE_POLL_INTERVAL_MS,
    [selectedWorkflowId],
  )

  const approval = usePolling(
    (signal) =>
      reviewWorkflowId
        ? api.getApprovalDetail(reviewWorkflowId, signal)
        : Promise.resolve(null),
    POLL_INTERVAL_MS,
    [reviewWorkflowId],
  )

  // Memoised so the fallback `[]` does not produce a new array identity on
  // every render and invalidate the selection lookup below.
  const items = useMemo(() => tickets.data?.items ?? [], [tickets.data])

  /**
   * Keep the selected row in sync with each poll so its badges stay live, and
   * fall back to the last known row if it drops out of the current filter.
   */
  const selectedTicket = useMemo(() => {
    if (!selected) return null
    return items.find((ticket) => ticket.id === selected.id) ?? selected
  }, [items, selected])

  const refreshAll = useCallback(() => {
    metrics.refetch()
    tickets.refetch()
    trace.refetch()
  }, [metrics, tickets, trace])

  const pendingApprovals = metrics.data?.pending_hitl_approvals ?? 0
  const firstPending = items.find((ticket) => ticket.requires_hitl && ticket.workflow_id)

  return (
    <div className="min-h-screen bg-canvas">
      <header className="sticky top-0 z-30 border-b border-edge bg-canvas/85 backdrop-blur-md">
        <div className="mx-auto flex max-w-[110rem] items-center justify-between gap-4 px-6 py-3.5">
          <div className="flex items-center gap-3">
            <span className="flex size-8 items-center justify-center rounded-lg bg-accent-soft text-accent ring-1 ring-accent/25">
              <Workflow size={17} />
            </span>
            <div>
              <h1 className="text-sm font-semibold tracking-tight text-ink">
                AgentFlow AI
              </h1>
              <p className="text-xs text-ink-faint">Operations control center</p>
            </div>
          </div>

          <div className="flex items-center gap-2">
            <span className="hidden items-center gap-1.5 text-xs text-ink-faint sm:inline-flex">
              <Activity
                size={12}
                className={metrics.refreshing ? 'text-info' : 'text-ink-faint'}
              />
              {metrics.lastUpdated
                ? `updated ${formatTime(metrics.lastUpdated.toISOString())}`
                : 'connecting…'}
            </span>

            {pendingApprovals > 0 && firstPending?.workflow_id ? (
              <Button
                variant="secondary"
                icon={<ShieldAlert size={13} className="text-warn" />}
                onClick={() => setReviewWorkflowId(firstPending.workflow_id as string)}
              >
                {pendingApprovals} awaiting review
              </Button>
            ) : null}

            <Button
              variant="ghost"
              icon={
                <RefreshCw
                  size={13}
                  className={tickets.refreshing ? 'animate-spin' : undefined}
                />
              }
              onClick={refreshAll}
            >
              Refresh
            </Button>

            <Button
              variant="primary"
              icon={<PlusCircle size={13} />}
              onClick={() => setSimulatorOpen(true)}
            >
              Simulate ticket
            </Button>
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-[110rem] space-y-4 px-6 py-5">
        <MetricsBar metrics={metrics.data} loading={metrics.loading} />

        {tickets.error ? <ErrorNote message={tickets.error} /> : null}
        {metrics.error && !tickets.error ? <ErrorNote message={metrics.error} /> : null}

        <div className="grid grid-cols-1 items-start gap-4 xl:grid-cols-[1.55fr_1fr]">
          <TicketsTable
            tickets={items}
            total={tickets.data?.total ?? 0}
            loading={tickets.loading}
            selectedTicketId={selectedTicket?.id ?? null}
            statusFilter={statusFilter}
            onStatusFilterChange={(status) => setStatusFilter(status)}
            onSelect={(ticket) => setSelected(ticket)}
            onReview={(workflowId) => setReviewWorkflowId(workflowId)}
          />

          <div className="xl:sticky xl:top-[4.75rem]">
            <ExecutionTrace
              trace={trace.data}
              ticketTitle={selectedTicket?.title ?? null}
              loading={trace.loading && selectedWorkflowId !== null}
              error={trace.error}
            />
          </div>
        </div>
      </main>

      {reviewWorkflowId ? (
        <ApprovalDrawer
          detail={approval.data}
          loading={approval.loading}
          error={approval.error}
          onClose={() => setReviewWorkflowId(null)}
          onDecided={refreshAll}
        />
      ) : null}

      {simulatorOpen ? (
        <TicketSimulator
          onClose={() => setSimulatorOpen(false)}
          onSubmitted={refreshAll}
        />
      ) : null}
    </div>
  )
}
