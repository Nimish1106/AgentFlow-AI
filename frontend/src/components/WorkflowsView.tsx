/**
 * Workflow monitor: every run, with the trace alongside.
 *
 * Split view rather than a drawer. Watching a workflow execute means switching
 * between runs repeatedly, and a modal that must be dismissed each time turns a
 * scanning task into a clicking task.
 */

import type { WorkflowStatus, WorkflowSummary, WorkflowTrace } from '../api/types'
import { formatCompactTime, formatDurationTerse } from '../lib/format'
import { WORKFLOW_LABEL, WORKFLOW_SEMANTIC } from '../lib/status'
import { ExecutionTrace } from './ExecutionTrace'
import {
  Empty,
  ErrorNote,
  MonoId,
  Panel,
  PanelHead,
  SegmentedControl,
  SkeletonRows,
  Status,
  Th,
} from './primitives'

const FILTERS: Array<{ value: WorkflowStatus | 'all'; label: string }> = [
  { value: 'all', label: 'All' },
  { value: 'running', label: 'Running' },
  { value: 'waiting_for_hitl', label: 'Review' },
  { value: 'completed', label: 'Completed' },
  { value: 'failed', label: 'Failed' },
]

export function WorkflowsView({
  workflows,
  total,
  loading,
  error,
  filter,
  onFilterChange,
  selectedId,
  onSelect,
  trace,
  traceLoading,
  traceError,
}: {
  workflows: WorkflowSummary[]
  total: number
  loading: boolean
  error: string | null
  filter: WorkflowStatus | 'all'
  onFilterChange: (value: WorkflowStatus | 'all') => void
  selectedId: string | null
  onSelect: (workflowId: string) => void
  trace: WorkflowTrace | null
  traceLoading: boolean
  traceError: string | null
}) {
  const selected = workflows.find((w) => w.workflow_id === selectedId) ?? null

  return (
    <div className="grid h-full min-h-0 grid-cols-1 gap-3 p-4 xl:grid-cols-[1fr_25rem]">
      <div className="flex min-h-0 flex-col">
        {error && workflows.length === 0 ? <ErrorNote message={error} /> : null}

        <Panel className="flex min-h-0 flex-1 flex-col">
          <PanelHead
            title="Workflow runs"
            meta={`${total} total`}
            actions={
              <SegmentedControl
                options={FILTERS}
                value={filter}
                onChange={onFilterChange}
                ariaLabel="Filter workflows by status"
              />
            }
          />

          <div className="min-h-0 flex-1 overflow-auto">
            <table className="w-full border-collapse">
              {/* Solid, not translucent: a sticky header must fully occlude the
                  rows scrolling beneath it. Matches the tickets table. */}
              <thead className="sticky top-0 z-10 bg-sunken">
                <tr className="border-b border-line">
                  <Th className="w-16 pl-3">Run</Th>
                  <Th>Ticket</Th>
                  <Th className="w-40">Customer</Th>
                  <Th className="w-32">Status</Th>
                  <Th className="w-28">Node</Th>
                  <Th className="w-20" align="right">
                    Duration
                  </Th>
                  <Th className="w-16" align="right">
                    Started
                  </Th>
                </tr>
              </thead>
              <tbody>
                {loading && workflows.length === 0 ? (
                  <SkeletonRows rows={12} cols={7} />
                ) : (
                  workflows.map((workflow) => {
                    const isSelected = workflow.workflow_id === selectedId
                    return (
                      <tr
                        key={workflow.workflow_id}
                        onClick={() => onSelect(workflow.workflow_id)}
                        onKeyDown={(event) => {
                          if (event.key === 'Enter' || event.key === ' ') {
                            event.preventDefault()
                            onSelect(workflow.workflow_id)
                          }
                        }}
                        tabIndex={0}
                        className={`h-row cursor-pointer border-b border-line last:border-0 ${
                          isSelected
                            ? 'bg-accent-dim shadow-[inset_2px_0_0_var(--color-accent)]'
                            : 'hover:bg-hover'
                        }`}
                      >
                        <td className="pl-3">
                          <MonoId id={workflow.workflow_id} />
                        </td>
                        <td className="max-w-0 pr-4">
                          <span className="block truncate text-data text-fg">
                            {workflow.ticket_title}
                          </span>
                        </td>
                        <td className="pr-4">
                          <span className="block truncate text-data text-fg-muted">
                            {workflow.customer_name}
                          </span>
                        </td>
                        <td className="pr-4">
                          <Status
                            semantic={WORKFLOW_SEMANTIC[workflow.workflow_status]}
                            label={WORKFLOW_LABEL[workflow.workflow_status]}
                            pulse={workflow.workflow_status === 'running'}
                          />
                        </td>
                        <td className="pr-4 text-meta text-fg-subtle">
                          {workflow.current_node ?? '—'}
                        </td>
                        <td className="tnum pr-4 text-right text-data text-fg-muted">
                          {formatDurationTerse(workflow.duration_ms)}
                        </td>
                        <td className="tnum pr-3 text-right text-meta text-fg-faint">
                          {formatCompactTime(workflow.started_at)}
                        </td>
                      </tr>
                    )
                  })
                )}
              </tbody>
            </table>

            {!loading && workflows.length === 0 ? (
              <Empty
                title="No workflow runs match this filter"
                hint="Submit a ticket to start one."
              />
            ) : null}
          </div>
        </Panel>
      </div>

      <div className="hidden min-h-0 xl:block">
        <ExecutionTrace
          trace={trace}
          title={selected?.ticket_title ?? null}
          loading={traceLoading}
          error={traceError}
        />
      </div>
    </div>
  )
}
