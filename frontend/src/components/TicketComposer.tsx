/**
 * Ticket composer.
 *
 * Replaces the previous simulator, whose customer field required pasting a raw
 * UUID copied from a table — a broken workflow papered over with a hint label.
 * Customers are derived from the ticket list already being polled, so this
 * needs no new endpoint and no backend change: the POST body is identical.
 *
 * Scenario presets exist because the realistic use is exercising a known path
 * (duplicate charge, lockout) rather than composing prose.
 */

import { useEffect, useMemo, useRef, useState } from 'react'
import { Check, X } from 'lucide-react'

import { api } from '../api/client'
import type { TicketSummary } from '../api/types'
import { Button, ErrorNote, FIELD } from './primitives'

interface Scenario {
  id: string
  name: string
  subject: string
  description: string
  /** What this exercises, shown so the choice is informed rather than blind. */
  exercises: string
}

const SCENARIOS: Scenario[] = [
  {
    id: 'duplicate',
    name: 'Duplicate charge',
    subject: 'Charged twice for my subscription',
    description:
      'I was billed twice for my subscription this month. Please refund the duplicate charge.',
    exercises: 'Billing agent · refund policy · risk engine',
  },
  {
    id: 'lockout',
    name: 'Account lockout',
    subject: 'My dashboard is locked',
    description:
      'I cannot sign in — the dashboard says my account is locked. Please unlock it so my team can work.',
    exercises: 'Account agent · unlock path',
  },
  {
    id: 'combined',
    name: 'Billing + lockout',
    subject: 'Double billed and locked out',
    description:
      'I was charged twice for my enterprise subscription and my dashboard is locked. I need both fixed.',
    exercises: 'Parallel fan-out · conflict resolution',
  },
  {
    id: 'technical',
    name: 'API failures',
    subject: 'API returning 401 on every request',
    description:
      'Since this morning every API call fails with a 401. Nothing changed on our side. What is going on?',
    exercises: 'Technical agent · knowledge retrieval',
  },
]

/** One entry per distinct customer seen in the ticket list. */
interface Customer {
  id: string
  name: string
  company: string
}

function deriveCustomers(tickets: TicketSummary[]): Customer[] {
  const seen = new Map<string, Customer>()
  for (const ticket of tickets) {
    if (!seen.has(ticket.customer_id)) {
      seen.set(ticket.customer_id, {
        id: ticket.customer_id,
        name: ticket.customer_name,
        company: ticket.company_name,
      })
    }
  }
  return [...seen.values()].sort((a, b) => a.name.localeCompare(b.name))
}

export function TicketComposer({
  tickets,
  onClose,
  onSubmitted,
}: {
  tickets: TicketSummary[]
  onClose: () => void
  onSubmitted: () => void
}) {
  const customers = useMemo(() => deriveCustomers(tickets), [tickets])

  // Null means "not yet chosen"; the effective value falls back to the first
  // known customer. Deriving it during render avoids a reset-state effect and
  // the cascading render it would cause.
  const [chosenCustomerId, setChosenCustomerId] = useState<string | null>(null)
  const customerId = chosenCustomerId ?? customers[0]?.id ?? ''

  const [scenarioId, setScenarioId] = useState(SCENARIOS[0]?.id ?? '')
  const [subject, setSubject] = useState(SCENARIOS[0]?.subject ?? '')
  const [description, setDescription] = useState(SCENARIOS[0]?.description ?? '')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [accepted, setAccepted] = useState<string | null>(null)
  const dialogRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose()
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [onClose])

  const applyScenario = (scenario: Scenario) => {
    setScenarioId(scenario.id)
    setSubject(scenario.subject)
    setDescription(scenario.description)
  }

  const submit = async () => {
    if (!customerId || !subject.trim() || !description.trim()) {
      setError('Choose a customer and provide a subject and description.')
      return
    }
    setSubmitting(true)
    setError(null)
    try {
      const response = await api.createTicket({
        customer_id: customerId,
        subject: subject.trim(),
        description: description.trim(),
      })
      setAccepted(response.workflow_id)
      onSubmitted()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not submit the ticket.')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center p-4 pt-[12vh]">
      <button
        type="button"
        aria-label="Close"
        onClick={onClose}
        className="absolute inset-0 bg-scrim"
      />

      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-label="Submit a ticket"
        // The one place shadow is used: the modal genuinely floats. Kept soft
        // and neutral-tinted — a black drop shadow on a white page reads dirty.
        className="animate-fade-in relative w-full max-w-lg overflow-hidden rounded-md border border-line bg-raised shadow-[0_12px_32px_-8px_rgb(30_41_59/0.18),0_2px_6px_-1px_rgb(30_41_59/0.08)]"
      >
        <div className="flex h-9 items-center justify-between border-b border-line px-3">
          <h2 className="label-micro text-fg-muted">New ticket</h2>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close"
            className="rounded-xs p-1 text-fg-subtle hover:bg-hover hover:text-fg"
          >
            <X size={13} />
          </button>
        </div>

        {accepted ? (
          <div className="p-4">
            <div className="flex items-start gap-2.5 rounded-sm border border-ok/25 bg-ok-dim px-3 py-2.5">
              <Check size={14} className="mt-0.5 shrink-0 text-ok" strokeWidth={2.5} />
              <div className="min-w-0">
                <p className="text-data font-medium text-ok">Accepted</p>
                <p className="mt-0.5 text-meta text-fg-muted">
                  The dispatcher will pick it up shortly. Run{' '}
                  <span className="font-mono text-fg">{accepted.slice(0, 8)}</span>
                </p>
              </div>
            </div>
            <div className="mt-3 flex justify-end gap-2">
              <Button
                onClick={() => {
                  setAccepted(null)
                  setError(null)
                }}
              >
                Submit another
              </Button>
              <Button variant="primary" onClick={onClose}>
                Done
              </Button>
            </div>
          </div>
        ) : (
          <div className="space-y-3 p-4">
            <div>
              <span className="label-micro">Scenario</span>
              <div className="mt-1.5 grid grid-cols-2 gap-1.5">
                {SCENARIOS.map((scenario) => {
                  const selected = scenario.id === scenarioId
                  return (
                    <button
                      key={scenario.id}
                      type="button"
                      onClick={() => applyScenario(scenario)}
                      // Unselected is white with a hairline; hover darkens.
                      // The dark-mode original filled unselected cards gray and
                      // lightened on hover, which inverts wrongly here.
                      className={`rounded-sm border px-2.5 py-2 text-left transition-colors duration-100 ${
                        selected
                          ? 'border-accent bg-accent-dim'
                          : 'border-line bg-raised hover:border-line-strong hover:bg-hover'
                      }`}
                    >
                      <div
                        className={`text-data font-medium ${
                          selected ? 'text-fg' : 'text-fg-muted'
                        }`}
                      >
                        {scenario.name}
                      </div>
                      <div className="mt-0.5 text-meta leading-[0.95rem] text-fg-faint">
                        {scenario.exercises}
                      </div>
                    </button>
                  )
                })}
              </div>
            </div>

            <label className="block">
              <span className="label-micro">Customer</span>
              {customers.length > 0 ? (
                <select
                  value={customerId}
                  onChange={(event) => setChosenCustomerId(event.target.value)}
                  className={`${FIELD} mt-1 h-7 px-2 text-data`}
                >
                  {customers.map((customer) => (
                    <option key={customer.id} value={customer.id}>
                      {customer.name} — {customer.company}
                    </option>
                  ))}
                </select>
              ) : (
                <>
                  <input
                    value={customerId}
                    onChange={(event) => setChosenCustomerId(event.target.value)}
                    placeholder="Customer UUID"
                    className={`${FIELD} mt-1 h-7 px-2 font-mono text-meta placeholder:font-sans`}
                  />
                  <span className="mt-1 block text-meta text-fg-faint">
                    No customers loaded yet — seed the database, or paste an id.
                  </span>
                </>
              )}
            </label>

            <label className="block">
              <span className="label-micro">Subject</span>
              <input
                value={subject}
                onChange={(event) => setSubject(event.target.value)}
                maxLength={500}
                className={`${FIELD} mt-1 h-7 px-2 text-data`}
              />
            </label>

            <label className="block">
              <span className="label-micro">Description</span>
              <textarea
                value={description}
                onChange={(event) => setDescription(event.target.value)}
                rows={3}
                className={`${FIELD} mt-1 resize-none px-2 py-1.5 text-data leading-[1.15rem]`}
              />
            </label>

            {error ? <ErrorNote message={error} /> : null}

            <div className="flex justify-end gap-2 pt-0.5">
              <Button variant="quiet" onClick={onClose}>
                Cancel
              </Button>
              <Button variant="primary" disabled={submitting} onClick={() => void submit()}>
                {submitting ? 'Submitting…' : 'Submit ticket'}
              </Button>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
