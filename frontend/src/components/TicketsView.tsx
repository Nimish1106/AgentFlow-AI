/**
 * Ticket operations hub.
 *
 * The density target is the point of this view: 34px rows, one line per cell,
 * no wrapping. An operator triaging a queue needs to see ~22 tickets at once,
 * not 8. Secondary detail (full id, company, timestamps) lives in the detail
 * pane rather than being stacked inside the row.
 */

import { useCallback, useMemo, useState } from 'react'
import { AlertTriangle, Inbox } from 'lucide-react'

import { api } from '../api/client'
import type { TicketStatus, TicketSummary } from '../api/types'
import { usePolling } from '../hooks/usePolling'
import { formatRelative, shortId, truncate } from '../lib/format'
import {
  PRIORITY_LABEL,
  PRIORITY_STYLE,
  TICKET_LABEL,
  TICKET_SEMANTIC,
  TIER_STYLE,
  WORKFLOW_LABEL,
  WORKFLOW_SEMANTIC,
} from '../lib/status'
import {
  Empty,
  ErrorNote,
  Panel,
  PanelHead,
  SegmentedControl,
  SkeletonRows,
  Status,
  Th,
} from './primitives'

const FILTERS: { value: TicketStatus | 'all'; label: string }[] = [
  { value: 'all', label: 'All' },
  { value: 'open', label: 'Open' },
  { value: 'in_progress', label: 'Active' },
  { value: 'resolved', label: 'Resolved' },
  { value: 'closed', label: 'Closed' },
]

interface Props {
  onSelectWorkflow: (workflowId: string) => void
  selectedWorkflowId: string | null
}

export function TicketsView({ onSelectWorkflow, selectedWorkflowId }: Props) {
  const [filter, setFilter] = useState<TicketStatus | 'all'>('all')

  const fetchTickets = useCallback(
    (signal: AbortSignal) => api.listTickets({ status: filter, limit: 100, signal }),
    [filter],
  )
  const { data, error, loading } = usePolling(fetchTickets, 4000, [filter])

  const tickets = useMemo(() => data?.items ?? [], [data])
  const needsReview = useMemo(
    () => tickets.filter((t) => t.requires_hitl).length,
    [tickets],
  )

  return (
    <div className="flex h-full flex-col">
      <div className="flex shrink-0 items-center gap-3 border-b border-line px-5 py-3">
        <div>
          <h1 className="text-title font-semibold">Tickets</h1>
          <p className="text-meta text-fg-subtle">
            {data ? `${data.total} total` : 'Loading…'}
            {needsReview > 0 && (
              <>
                {' · '}
                <span className="text-attention">{needsReview} awaiting review</span>
              </>
            )}
          </p>
        </div>
        <div className="ml-auto">
          <SegmentedControl options={FILTERS} value={filter} onChange={setFilter} />
        </div>
      </div>

      <div className="min-h-0 flex-1 overflow-auto p-5">
        {error && !data && (
          <ErrorNote message={`Could not load tickets — ${error}`} />
        )}

        <Panel>
          <PanelHead title="Queue" />
          {loading && !data ? (
            <SkeletonRows rows={12} />
          ) : tickets.length === 0 ? (
            <Empty
              icon={Inbox}
              title="No tickets match this filter"
              hint="Submit one from the New ticket action to exercise the pipeline."
            />
          ) : (
            <table className="w-full border-collapse">
              <thead>
                <tr className="border-b border-line bg-sunken">
                  <Th className="w-[3rem] pl-4">ID</Th>
                  <Th>Subject</Th>
                  <Th className="w-[11rem]">Customer</Th>
                  <Th className="w-[6rem]">Tier</Th>
                  <Th className="w-[5.5rem]">Priority</Th>
                  <Th className="w-[7rem]">Ticket</Th>
                  <Th className="w-[9rem]">Workflow</Th>
                  <Th className="w-[6rem]" align="right">
                    Age
                  </Th>
                </tr>
              </thead>
              <tbody>
                {tickets.map((ticket) => (
                  <Row
                    key={ticket.id}
                    ticket={ticket}
                    selected={
                      ticket.workflow_id !== null &&
                      ticket.workflow_id === selectedWorkflowId
                    }
                    onSelect={onSelectWorkflow}
                  />
                ))}
              </tbody>
            </table>
          )}
        </Panel>
      </div>
    </div>
  )
}

function Row({
  ticket,
  selected,
  onSelect,
}: {
  ticket: TicketSummary
  selected: boolean
  onSelect: (workflowId: string) => void
}) {
  const clickable = ticket.workflow_id !== null

  const activate = () => {
    if (ticket.workflow_id) onSelect(ticket.workflow_id)
  }

  return (
    <tr
      onClick={clickable ? activate : undefined}
      onKeyDown={
        clickable
          ? (event) => {
              if (event.key === 'Enter' || event.key === ' ') {
                event.preventDefault()
                activate()
              }
            }
          : undefined
      }
      tabIndex={clickable ? 0 : undefined}
      role={clickable ? 'button' : undefined}
      aria-label={clickable ? `Open trace for ${ticket.title}` : undefined}
      className={[
        'h-row border-b border-line last:border-0',
        clickable ? 'cursor-pointer hover:bg-hover' : '',
        // A 2px inset left edge marks selection without shifting layout.
        selected ? 'bg-accent-dim shadow-[inset_2px_0_0_var(--color-accent)]' : '',
      ].join(' ')}
    >
      <td className="pl-4 font-mono text-meta text-fg-faint">{shortId(ticket.id)}</td>
      <td className="max-w-0 pr-4">
        <span className="flex items-center gap-1.5">
          {ticket.requires_hitl && (
            <AlertTriangle
              size={11}
              className="shrink-0 text-attention"
              aria-label="Awaiting human review"
            />
          )}
          <span className="truncate text-data" title={ticket.title}>
            {truncate(ticket.title, 70)}
          </span>
        </span>
      </td>
      <td className="pr-4">
        <span className="block truncate text-data text-fg-muted" title={ticket.company_name}>
          {ticket.customer_name}
        </span>
      </td>
      <td className={`pr-4 text-data capitalize ${TIER_STYLE[ticket.customer_tier]}`}>
        {ticket.customer_tier}
      </td>
      <td className={`pr-4 text-data ${PRIORITY_STYLE[ticket.priority]}`}>
        {PRIORITY_LABEL[ticket.priority]}
      </td>
      <td className="pr-4">
        <Status
          semantic={TICKET_SEMANTIC[ticket.status]}
          label={TICKET_LABEL[ticket.status]}
        />
      </td>
      <td className="pr-4">
        {ticket.workflow_status ? (
          <Status
            semantic={WORKFLOW_SEMANTIC[ticket.workflow_status]}
            label={WORKFLOW_LABEL[ticket.workflow_status]}
            pulse={ticket.workflow_status === 'running'}
          />
        ) : (
          <span className="text-data text-fg-faint">—</span>
        )}
      </td>
      <td className="pr-4 text-right text-meta text-fg-subtle tnum">
        {formatRelative(ticket.created_at)}
      </td>
    </tr>
  )
}
