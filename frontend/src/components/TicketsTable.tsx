/**
 * Ticket & Workflow Operations Hub.
 *
 * One row per ticket showing its workflow state, customer tier and priority.
 * Selecting a row drives the execution trace panel; a row awaiting approval
 * offers the review action directly.
 */

import { Inbox, ShieldAlert, Table2 } from 'lucide-react'
import type { TicketStatus, TicketSummary } from '../api/types'
import { formatRelative, humanizeNode, shortId } from '../lib/format'
import {
  PRIORITY_TONE,
  TICKET_STATUS_LABEL,
  TICKET_STATUS_TONE,
  TIER_TONE,
  WORKFLOW_STATUS_LABEL,
  WORKFLOW_STATUS_TONE,
} from '../lib/status'
import { Badge, Button, Card, EmptyState, SectionHeader, SkeletonRows } from './ui'

const STATUS_FILTERS: Array<{ value: TicketStatus | 'all'; label: string }> = [
  { value: 'all', label: 'All' },
  { value: 'open', label: 'Open' },
  { value: 'in_progress', label: 'In progress' },
  { value: 'resolved', label: 'Resolved' },
  { value: 'closed', label: 'Closed' },
]

export function TicketsTable({
  tickets,
  total,
  loading,
  selectedTicketId,
  statusFilter,
  onStatusFilterChange,
  onSelect,
  onReview,
}: {
  tickets: TicketSummary[]
  total: number
  loading: boolean
  selectedTicketId: string | null
  statusFilter: TicketStatus | 'all'
  onStatusFilterChange: (status: TicketStatus | 'all') => void
  onSelect: (ticket: TicketSummary) => void
  onReview: (workflowId: string) => void
}) {
  return (
    <Card>
      <SectionHeader
        icon={<Table2 size={15} />}
        title="Ticket & workflow operations"
        subtitle={`${total} ticket${total === 1 ? '' : 's'} tracked`}
        actions={
          <div
            className="flex items-center gap-1 rounded-lg bg-surface-raised p-0.5 ring-1 ring-edge-strong"
            role="group"
            aria-label="Filter tickets by status"
          >
            {STATUS_FILTERS.map((filter) => (
              <button
                key={filter.value}
                type="button"
                onClick={() => onStatusFilterChange(filter.value)}
                aria-pressed={statusFilter === filter.value}
                className={`rounded-md px-2.5 py-1 text-xs font-medium transition-colors duration-150 ${
                  statusFilter === filter.value
                    ? 'bg-accent text-white'
                    : 'text-ink-muted hover:bg-surface-hover hover:text-ink'
                }`}
              >
                {filter.label}
              </button>
            ))}
          </div>
        }
      />

      <div className="overflow-x-auto">
        <table className="w-full min-w-[62rem] border-collapse text-left text-sm">
          <caption className="sr-only">
            Support tickets with workflow status, customer tier and priority
          </caption>
          <thead>
            <tr className="text-xs font-medium tracking-wide text-ink-faint uppercase">
              <th scope="col" className="px-4 py-2.5 font-medium">Ticket</th>
              <th scope="col" className="px-4 py-2.5 font-medium">Customer</th>
              <th scope="col" className="px-4 py-2.5 font-medium">Tier</th>
              <th scope="col" className="px-4 py-2.5 font-medium">Priority</th>
              <th scope="col" className="px-4 py-2.5 font-medium">Ticket status</th>
              <th scope="col" className="px-4 py-2.5 font-medium">Workflow</th>
              <th scope="col" className="px-4 py-2.5 font-medium">Age</th>
              <th scope="col" className="px-4 py-2.5 font-medium">
                <span className="sr-only">Actions</span>
              </th>
            </tr>
          </thead>
          <tbody>
            {loading && tickets.length === 0 ? (
              <SkeletonRows rows={6} columns={8} />
            ) : (
              tickets.map((ticket) => {
                const selected = ticket.id === selectedTicketId
                return (
                  <tr
                    key={ticket.id}
                    onClick={() => onSelect(ticket)}
                    aria-selected={selected}
                    className={`cursor-pointer border-t border-edge transition-colors duration-150 ${
                      selected ? 'bg-accent-soft' : 'hover:bg-surface-raised'
                    }`}
                  >
                    <td className="px-4 py-3">
                      <p className="font-medium text-ink">{ticket.title}</p>
                      <p className="tnum mt-0.5 font-mono text-xs text-ink-faint">
                        {shortId(ticket.id)}
                      </p>
                    </td>
                    <td className="px-4 py-3">
                      <p className="text-ink">{ticket.customer_name}</p>
                      <p className="mt-0.5 text-xs text-ink-faint">
                        {ticket.company_name}
                      </p>
                    </td>
                    <td className="px-4 py-3">
                      <Badge toneName={TIER_TONE[ticket.customer_tier] ?? 'neutral'}>
                        {ticket.customer_tier}
                      </Badge>
                    </td>
                    <td className="px-4 py-3">
                      <Badge toneName={PRIORITY_TONE[ticket.priority] ?? 'neutral'}>
                        {ticket.priority}
                      </Badge>
                    </td>
                    <td className="px-4 py-3">
                      <Badge toneName={TICKET_STATUS_TONE[ticket.status] ?? 'neutral'}>
                        {TICKET_STATUS_LABEL[ticket.status] ?? ticket.status}
                      </Badge>
                    </td>
                    <td className="px-4 py-3">
                      {ticket.workflow_status ? (
                        <div className="flex flex-col gap-1">
                          <Badge
                            toneName={
                              WORKFLOW_STATUS_TONE[ticket.workflow_status] ?? 'neutral'
                            }
                          >
                            {WORKFLOW_STATUS_LABEL[ticket.workflow_status] ??
                              ticket.workflow_status}
                          </Badge>
                          {ticket.current_node ? (
                            <span className="text-xs text-ink-faint">
                              {humanizeNode(ticket.current_node)}
                            </span>
                          ) : null}
                        </div>
                      ) : (
                        <span className="text-xs text-ink-faint">Not queued</span>
                      )}
                    </td>
                    <td className="tnum px-4 py-3 text-xs text-ink-muted">
                      {formatRelative(ticket.created_at)}
                    </td>
                    <td className="px-4 py-3 text-right">
                      {ticket.requires_hitl && ticket.workflow_id ? (
                        <Button
                          variant="primary"
                          icon={<ShieldAlert size={13} />}
                          onClick={() => onReview(ticket.workflow_id as string)}
                        >
                          Review
                        </Button>
                      ) : null}
                    </td>
                  </tr>
                )
              })
            )}
          </tbody>
        </table>
      </div>

      {!loading && tickets.length === 0 ? (
        <EmptyState
          icon={<Inbox size={22} />}
          title="No tickets match this filter"
          hint="Submit a test ticket to trigger a workflow, or clear the status filter."
        />
      ) : null}
    </Card>
  )
}
