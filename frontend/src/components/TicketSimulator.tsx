/**
 * Ticket Ingestion Simulator.
 *
 * Submits a test ticket to POST /tickets to trigger a real backend workflow.
 * The customer_id must be an existing user UUID (the API 404s otherwise), so
 * the field is free-text and the scenario presets only fill subject/description.
 *
 * Scenarios mirror the seeded corpus so a demo can reliably reach the billing,
 * account and technical agents.
 */

import { useEffect, useRef, useState } from 'react'
import { Send, Sparkles, X } from 'lucide-react'
import { api } from '../api/client'
import { Button, ErrorNote } from './ui'

interface Scenario {
  name: string
  subject: string
  description: string
}

const SCENARIOS: Scenario[] = [
  {
    name: 'Duplicate charge',
    subject: 'Charged twice for my subscription',
    description:
      'I was billed twice for my enterprise subscription this month. Please refund the duplicate charge.',
  },
  {
    name: 'Locked dashboard',
    subject: 'My dashboard is locked',
    description:
      'I cannot sign in - the dashboard says my account is locked. Please unlock it so my team can work.',
  },
  {
    name: 'Duplicate + lockout',
    subject: 'Double billed and locked out',
    description:
      'I was charged twice for my enterprise subscription and my dashboard is locked. I need both fixed.',
  },
  {
    name: 'API errors',
    subject: 'API returning 401 on every request',
    description:
      'Since this morning every API call fails with a 401. Nothing changed on our side. What is going on?',
  },
]

export function TicketSimulator({
  onClose,
  onSubmitted,
}: {
  onClose: () => void
  onSubmitted: () => void
}) {
  const [customerId, setCustomerId] = useState('')
  const [subject, setSubject] = useState(SCENARIOS[0]?.subject ?? '')
  const [description, setDescription] = useState(SCENARIOS[0]?.description ?? '')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [accepted, setAccepted] = useState<string | null>(null)
  const firstFieldRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose()
    }
    document.addEventListener('keydown', onKeyDown)
    firstFieldRef.current?.focus()
    return () => document.removeEventListener('keydown', onKeyDown)
  }, [onClose])

  const applyScenario = (scenario: Scenario) => {
    setSubject(scenario.subject)
    setDescription(scenario.description)
  }

  const submit = async () => {
    if (!customerId.trim() || !subject.trim() || !description.trim()) {
      setError('Customer ID, subject and description are all required.')
      return
    }
    setSubmitting(true)
    setError(null)
    try {
      const response = await api.createTicket({
        customer_id: customerId.trim(),
        subject: subject.trim(),
        description: description.trim(),
      })
      setAccepted(response.workflow_id)
      onSubmitted()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to submit the ticket.')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      <button
        type="button"
        aria-label="Close simulator"
        onClick={onClose}
        className="absolute inset-0 bg-black/60 backdrop-blur-[2px]"
      />

      <div
        role="dialog"
        aria-modal="true"
        aria-label="Submit a test ticket"
        className="animate-fade-rise relative w-full max-w-lg rounded-xl border border-edge-strong bg-surface shadow-2xl"
      >
        <header className="flex items-start justify-between gap-4 border-b border-edge px-5 py-4">
          <div className="flex items-start gap-3">
            <span className="mt-0.5 text-accent">
              <Sparkles size={17} />
            </span>
            <div>
              <h2 className="text-sm font-semibold text-ink">Ticket ingestion simulator</h2>
              <p className="mt-0.5 text-xs text-ink-faint">
                Submits a real ticket and triggers the workflow pipeline.
              </p>
            </div>
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close"
            className="rounded-lg p-1.5 text-ink-muted transition-colors hover:bg-surface-raised hover:text-ink"
          >
            <X size={16} />
          </button>
        </header>

        {accepted ? (
          <div className="space-y-4 px-5 py-6">
            <div className="rounded-lg border border-ok/30 bg-ok-soft px-3.5 py-3">
              <p className="text-sm font-medium text-ok">Ticket accepted</p>
              <p className="mt-1 text-xs text-ink-muted">
                The dispatcher will pick it up shortly. Workflow{' '}
                <span className="font-mono text-ink">{accepted}</span>
              </p>
            </div>
            <div className="flex justify-end gap-2">
              <Button
                variant="secondary"
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
          <div className="space-y-4 px-5 py-4">
            <div>
              <span className="text-xs font-medium text-ink-faint">Scenario presets</span>
              <div className="mt-1.5 flex flex-wrap gap-1.5">
                {SCENARIOS.map((scenario) => (
                  <button
                    key={scenario.name}
                    type="button"
                    onClick={() => applyScenario(scenario)}
                    className={`rounded-lg px-2.5 py-1 text-xs font-medium transition-colors duration-150 ${
                      subject === scenario.subject
                        ? 'bg-accent text-white'
                        : 'bg-surface-raised text-ink-muted ring-1 ring-edge-strong hover:bg-surface-hover hover:text-ink'
                    }`}
                  >
                    {scenario.name}
                  </button>
                ))}
              </div>
            </div>

            <label className="block">
              <span className="text-xs font-medium text-ink-faint">
                Customer ID <span className="text-danger">*</span>
              </span>
              <input
                ref={firstFieldRef}
                value={customerId}
                onChange={(event) => setCustomerId(event.target.value)}
                placeholder="UUID of an existing seeded customer"
                className="mt-1 w-full rounded-lg border border-edge-strong bg-surface-raised px-2.5 py-1.5 font-mono text-xs text-ink placeholder:font-sans placeholder:text-ink-faint focus:border-accent focus:outline-none"
              />
              <span className="mt-1 block text-xs text-ink-faint">
                Copy one from the operations hub - the API rejects unknown customers.
              </span>
            </label>

            <label className="block">
              <span className="text-xs font-medium text-ink-faint">
                Subject <span className="text-danger">*</span>
              </span>
              <input
                value={subject}
                onChange={(event) => setSubject(event.target.value)}
                maxLength={500}
                className="mt-1 w-full rounded-lg border border-edge-strong bg-surface-raised px-2.5 py-1.5 text-sm text-ink placeholder:text-ink-faint focus:border-accent focus:outline-none"
              />
            </label>

            <label className="block">
              <span className="text-xs font-medium text-ink-faint">
                Description <span className="text-danger">*</span>
              </span>
              <textarea
                value={description}
                onChange={(event) => setDescription(event.target.value)}
                rows={4}
                className="mt-1 w-full resize-none rounded-lg border border-edge-strong bg-surface-raised px-2.5 py-1.5 text-sm leading-relaxed text-ink placeholder:text-ink-faint focus:border-accent focus:outline-none"
              />
            </label>

            {error ? <ErrorNote message={error} /> : null}

            <div className="flex justify-end gap-2 pt-1">
              <Button variant="ghost" onClick={onClose}>
                Cancel
              </Button>
              <Button
                variant="primary"
                icon={<Send size={13} />}
                disabled={submitting}
                onClick={() => void submit()}
              >
                {submitting ? 'Submitting…' : 'Submit ticket'}
              </Button>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
