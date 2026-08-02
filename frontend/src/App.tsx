/**
 * AgentFlow operations console.
 *
 * Owns view routing, the polled data every view shares, and the cross-view
 * navigation that makes the product feel like one tool: clicking a ticket that
 * needs review lands you in the Approvals queue with that item already open,
 * rather than opening a disconnected drawer.
 *
 * All data arrives by polling — the backend exposes no push channel.
 */

import { useCallback, useMemo, useState } from 'react'
import { Plus, RefreshCw } from 'lucide-react'

import { api } from './api/client'
import type { WorkflowStatus } from './api/types'
import { ApprovalsView } from './components/ApprovalsView'
import { ExecutionTrace } from './components/ExecutionTrace'
import { OverviewView } from './components/OverviewView'
import { Rail, TopBar, type View } from './components/Shell'
import { TicketComposer } from './components/TicketComposer'
import { TicketsView } from './components/TicketsView'
import { WorkflowsView } from './components/WorkflowsView'
import { Button } from './components/primitives'
import { usePolling } from './hooks/usePolling'

const POLL_MS = Number(import.meta.env.VITE_POLL_INTERVAL_MS ?? 4000)
/** The trace is what someone watches a run through, so it refreshes faster. */
const TRACE_POLL_MS = 2000

const TITLES: Record<View, { title: string; subtitle: string }> = {
  overview: { title: 'Overview', subtitle: 'System state at a glance' },
  tickets: { title: 'Tickets', subtitle: 'Every ticket and its workflow' },
  workflows: { title: 'Workflows', subtitle: 'Execution monitor' },
  approvals: { title: 'Approvals', subtitle: 'Decisions blocking a workflow' },
}

export default function App() {
  const [view, setView] = useState<View>('overview')
  const [composerOpen, setComposerOpen] = useState(false)
  const [workflowFilter, setWorkflowFilter] = useState<WorkflowStatus | 'all'>('all')
  const [selectedWorkflowId, setSelectedWorkflowId] = useState<string | null>(null)
  const [approvalId, setApprovalId] = useState<string | null>(null)

  const metrics = usePolling((signal) => api.getMetrics(signal), POLL_MS)

  // Tickets are polled at the app level: the composer derives its customer list
  // from them, and the overview counts against them.
  const tickets = usePolling(
    (signal) => api.listTickets({ limit: 100, signal }),
    POLL_MS,
  )

  const workflows = usePolling(
    (signal) =>
      api.listWorkflows({ status: workflowFilter, limit: 100, signal }),
    POLL_MS,
    [workflowFilter],
  )

  // The approvals queue is its own query so it stays correct regardless of the
  // filter the workflows table happens to be on.
  const approvalQueue = usePolling(
    (signal) =>
      api.listWorkflows({ status: 'waiting_for_hitl', limit: 50, signal }),
    POLL_MS,
  )

  const trace = usePolling(
    (signal) =>
      selectedWorkflowId
        ? api.getWorkflowTrace(selectedWorkflowId, signal)
        : Promise.resolve(null),
    TRACE_POLL_MS,
    [selectedWorkflowId],
  )

  const approvalDetail = usePolling(
    (signal) =>
      approvalId ? api.getApprovalDetail(approvalId, signal) : Promise.resolve(null),
    POLL_MS,
    [approvalId],
  )

  const ticketItems = useMemo(() => tickets.data?.items ?? [], [tickets.data])
  const workflowItems = useMemo(() => workflows.data?.items ?? [], [workflows.data])
  const queueItems = useMemo(
    () => approvalQueue.data?.items ?? [],
    [approvalQueue.data],
  )

  const pendingApprovals =
    metrics.data?.pending_hitl_approvals ?? queueItems.length

  const refreshAll = useCallback(() => {
    metrics.refetch()
    tickets.refetch()
    workflows.refetch()
    approvalQueue.refetch()
    trace.refetch()
    approvalDetail.refetch()
  }, [metrics, tickets, workflows, approvalQueue, trace, approvalDetail])

  /**
   * Open a workflow in the most useful place: a run awaiting a decision belongs
   * in the review queue, anything else in the execution monitor.
   */
  const openWorkflow = useCallback(
    (workflowId: string) => {
      const inQueue = queueItems.some((w) => w.workflow_id === workflowId)
      if (inQueue) {
        setApprovalId(workflowId)
        setView('approvals')
        return
      }
      setSelectedWorkflowId(workflowId)
      setView('workflows')
    },
    [queueItems],
  )

  const selectApproval = useCallback((workflowId: string) => {
    setApprovalId(workflowId)
  }, [])

  const onDecided = useCallback(() => {
    refreshAll()
    // The item leaves the queue once decided; drop the selection so the pane
    // does not sit on a workflow that is no longer actionable.
    setApprovalId(null)
  }, [refreshAll])

  // A poll that has failed while data is on screen means what is displayed is
  // stale — surfaced in the top bar rather than silently left to age.
  const stale = Boolean(
    (metrics.error && metrics.data) || (tickets.error && tickets.data),
  )

  const header = TITLES[view]

  return (
    <div className="flex h-screen overflow-hidden bg-base">
      <Rail view={view} onNavigate={setView} pendingApprovals={pendingApprovals} />

      <div className="flex min-w-0 flex-1 flex-col">
        <TopBar
          title={header.title}
          subtitle={header.subtitle}
          live={{
            updatedAt: metrics.lastUpdated,
            refreshing: metrics.refreshing || tickets.refreshing,
            stale,
          }}
          actions={
            <>
              <Button
                variant="quiet"
                icon={
                  <RefreshCw
                    size={12}
                    className={tickets.refreshing ? 'animate-spin' : undefined}
                  />
                }
                onClick={refreshAll}
              >
                Refresh
              </Button>
              <Button
                variant="primary"
                icon={<Plus size={12} strokeWidth={2.5} />}
                onClick={() => setComposerOpen(true)}
              >
                New ticket
              </Button>
            </>
          }
        />

        <main className="min-h-0 flex-1 overflow-auto">
          {view === 'overview' ? (
            <OverviewView
              metrics={metrics.data}
              workflows={workflowItems}
              loading={metrics.loading}
              onNavigate={setView}
              onOpenWorkflow={openWorkflow}
            />
          ) : null}

          {view === 'tickets' ? (
            <div className="grid h-full min-h-0 grid-cols-1 gap-3 p-4 xl:grid-cols-[1fr_25rem]">
              <div className="min-h-0">
                <TicketsView
                  onSelectWorkflow={openWorkflow}
                  selectedWorkflowId={selectedWorkflowId}
                />
              </div>
              <div className="hidden min-h-0 xl:block">
                <ExecutionTrace
                  trace={trace.data}
                  title={
                    ticketItems.find((t) => t.workflow_id === selectedWorkflowId)
                      ?.title ?? null
                  }
                  loading={trace.loading && selectedWorkflowId !== null}
                  error={trace.error}
                />
              </div>
            </div>
          ) : null}

          {view === 'workflows' ? (
            <WorkflowsView
              workflows={workflowItems}
              total={workflows.data?.total ?? 0}
              loading={workflows.loading}
              error={workflows.error}
              filter={workflowFilter}
              onFilterChange={setWorkflowFilter}
              selectedId={selectedWorkflowId}
              onSelect={setSelectedWorkflowId}
              trace={trace.data}
              traceLoading={trace.loading && selectedWorkflowId !== null}
              traceError={trace.error}
            />
          ) : null}

          {view === 'approvals' ? (
            <ApprovalsView
              queue={queueItems}
              selectedId={approvalId}
              detail={approvalDetail.data}
              detailLoading={approvalDetail.loading && approvalId !== null}
              detailError={approvalDetail.error}
              onSelect={selectApproval}
              onDecided={onDecided}
            />
          ) : null}
        </main>
      </div>

      {composerOpen ? (
        <TicketComposer
          tickets={ticketItems}
          onClose={() => setComposerOpen(false)}
          onSubmitted={refreshAll}
        />
      ) : null}
    </div>
  )
}
