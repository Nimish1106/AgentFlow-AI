/**
 * HITL Approval Management drawer (SRS §38).
 *
 * Shows the full review packet - risk score and the Risk Engine's own reasons,
 * the customer's subscription and invoices, and each agent's judgement - then
 * submits the reviewer's decision to POST /approvals/{workflow_id}.
 *
 * The risk fields come from `workflow_runs.risk_assessment`, which the
 * dispatcher writes straight from the Risk Engine's output. Nothing shown here
 * is re-derived from log text.
 *
 * Deliberate UX choice: approve and reject are equally prominent and neither is
 * the default focus. A reviewer releasing a refund should have to aim.
 */

import { useEffect, useRef, useState } from 'react'
import {
  Bot,
  Building2,
  CreditCard,
  FileText,
  ShieldAlert,
  ThumbsDown,
  ThumbsUp,
  X,
} from 'lucide-react'
import { ApiError, api } from '../api/client'
import type { ApprovalDetail } from '../api/types'
import { formatConfidence, formatDate, formatMoney, humanizeNode } from '../lib/format'
import { PRIORITY_TONE, riskTone, TIER_TONE } from '../lib/status'
import { Badge, Button, ErrorNote } from './ui'

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <p className="text-xs font-medium text-ink-faint">{label}</p>
      <div className="mt-1 text-sm text-ink">{children}</div>
    </div>
  )
}

function Panel({ title, icon, children }: {
  title: string
  icon: React.ReactNode
  children: React.ReactNode
}) {
  return (
    <section className="rounded-lg border border-edge bg-surface-raised p-3.5">
      <h3 className="mb-2.5 inline-flex items-center gap-1.5 text-xs font-semibold tracking-wide text-ink-muted uppercase">
        {icon}
        {title}
      </h3>
      {children}
    </section>
  )
}

export function ApprovalDrawer({
  detail,
  loading,
  error,
  onClose,
  onDecided,
}: {
  detail: ApprovalDetail | null
  loading: boolean
  error: string | null
  onClose: () => void
  onDecided: () => void
}) {
  const [reviewerName, setReviewerName] = useState('')
  const [comments, setComments] = useState('')
  const [submitting, setSubmitting] = useState<'approve' | 'reject' | null>(null)
  const [submitError, setSubmitError] = useState<string | null>(null)
  const closeRef = useRef<HTMLButtonElement>(null)

  // Escape closes, matching the overlay click. Focus starts on the close
  // button rather than a decision control.
  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose()
    }
    document.addEventListener('keydown', onKeyDown)
    closeRef.current?.focus()
    return () => document.removeEventListener('keydown', onKeyDown)
  }, [onClose])

  const awaitingReview = detail?.workflow_status === 'waiting_for_hitl'

  const submit = async (approved: boolean) => {
    if (!detail || !reviewerName.trim()) {
      setSubmitError('Reviewer name is required.')
      return
    }
    setSubmitting(approved ? 'approve' : 'reject')
    setSubmitError(null)
    try {
      await api.submitApproval(detail.workflow_id, {
        approved,
        reviewer_name: reviewerName.trim(),
        comments: comments.trim(),
      })
      onDecided()
      onClose()
    } catch (err) {
      // A 409 means someone else already decided it; say so plainly.
      const message =
        err instanceof ApiError && err.status === 409
          ? 'This workflow is no longer awaiting approval - it may have been decided already.'
          : err instanceof Error
            ? err.message
            : 'Failed to submit the decision.'
      setSubmitError(message)
    } finally {
      setSubmitting(null)
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex justify-end">
      <button
        type="button"
        aria-label="Close review drawer"
        onClick={onClose}
        className="absolute inset-0 bg-black/60 backdrop-blur-[2px]"
      />

      <aside
        role="dialog"
        aria-modal="true"
        aria-label="Workflow approval review"
        className="animate-slide-in-right relative flex h-full w-full max-w-xl flex-col border-l border-edge-strong bg-surface shadow-2xl"
      >
        <header className="flex items-start justify-between gap-4 border-b border-edge px-5 py-4">
          <div className="flex items-start gap-3">
            <span className="mt-0.5 text-warn">
              <ShieldAlert size={18} />
            </span>
            <div>
              <h2 className="text-sm font-semibold text-ink">Human approval required</h2>
              <p className="mt-0.5 text-xs text-ink-faint">
                {detail ? detail.ticket_title : 'Loading review packet…'}
              </p>
            </div>
          </div>
          <button
            ref={closeRef}
            type="button"
            onClick={onClose}
            aria-label="Close"
            className="rounded-lg p-1.5 text-ink-muted transition-colors hover:bg-surface-raised hover:text-ink"
          >
            <X size={16} />
          </button>
        </header>

        <div className="flex-1 space-y-3.5 overflow-y-auto px-5 py-4">
          {error ? <ErrorNote message={error} /> : null}

          {loading && !detail ? (
            <div className="space-y-3">
              {Array.from({ length: 5 }).map((_, index) => (
                <div key={index} className="skeleton h-20 rounded-lg" />
              ))}
            </div>
          ) : detail ? (
            <>
              <Panel title="Risk assessment" icon={<ShieldAlert size={12} />}>
                <div className="flex flex-wrap items-center gap-2">
                  <Badge toneName={riskTone(detail.risk_level)}>
                    {detail.risk_level ? `${detail.risk_level} risk` : 'not assessed'}
                  </Badge>
                  {detail.risk_score !== null ? (
                    <span className="tnum text-sm font-semibold text-ink">
                      score {detail.risk_score.toFixed(2)}
                    </span>
                  ) : null}
                </div>

                {detail.reasons.length > 0 ? (
                  <ul className="mt-2.5 space-y-1.5">
                    {detail.reasons.map((reason, index) => (
                      <li
                        key={index}
                        className="flex gap-2 text-xs leading-relaxed text-ink-muted"
                      >
                        <span className="mt-1.5 size-1 shrink-0 rounded-full bg-warn" />
                        {reason}
                      </li>
                    ))}
                  </ul>
                ) : (
                  <p className="mt-2 text-xs text-ink-faint">
                    No risk reasons were recorded for this workflow.
                  </p>
                )}
              </Panel>

              <Panel title="Ticket" icon={<FileText size={12} />}>
                <div className="grid grid-cols-2 gap-3">
                  <Field label="Priority">
                    <Badge toneName={PRIORITY_TONE[detail.priority] ?? 'neutral'}>
                      {detail.priority}
                    </Badge>
                  </Field>
                  <Field label="Workflow status">
                    <span className="text-xs text-ink-muted">
                      {detail.workflow_status}
                    </span>
                  </Field>
                </div>
                <div className="mt-3">
                  <Field label="Customer issue">
                    <p className="max-h-32 overflow-y-auto rounded-md bg-surface px-2.5 py-2 text-xs leading-relaxed whitespace-pre-wrap text-ink-muted">
                      {detail.issue_text}
                    </p>
                  </Field>
                </div>
              </Panel>

              <Panel title="Customer" icon={<Building2 size={12} />}>
                <div className="grid grid-cols-2 gap-3">
                  <Field label="Contact">{detail.customer_name}</Field>
                  <Field label="Company">{detail.company_name}</Field>
                  <Field label="Tier">
                    <Badge toneName={TIER_TONE[detail.customer_tier] ?? 'neutral'}>
                      {detail.customer_tier}
                    </Badge>
                  </Field>
                  {detail.subscription ? (
                    <Field label="Subscription">
                      <span className="tnum text-xs text-ink-muted">
                        {formatMoney(detail.subscription.monthly_price)}/mo ·{' '}
                        {detail.subscription.subscription_status} · renews{' '}
                        {formatDate(detail.subscription.renewal_date)}
                      </span>
                    </Field>
                  ) : null}
                </div>
              </Panel>

              {detail.invoices.length > 0 ? (
                <Panel title="Recent invoices" icon={<CreditCard size={12} />}>
                  <ul className="space-y-1.5">
                    {detail.invoices.map((invoice) => (
                      <li
                        key={invoice.id}
                        className="flex items-center justify-between rounded-md bg-surface px-2.5 py-1.5"
                      >
                        <span className="tnum text-sm font-medium text-ink">
                          {formatMoney(invoice.amount, invoice.currency)}
                        </span>
                        <div className="flex items-center gap-2">
                          <Badge
                            toneName={
                              invoice.payment_status === 'duplicate'
                                ? 'danger'
                                : invoice.payment_status === 'refunded'
                                  ? 'info'
                                  : 'neutral'
                            }
                          >
                            {invoice.payment_status}
                          </Badge>
                          <span className="text-xs text-ink-faint">
                            {formatDate(invoice.created_at)}
                          </span>
                        </div>
                      </li>
                    ))}
                  </ul>
                </Panel>
              ) : null}

              {detail.agent_summaries.length > 0 ? (
                <Panel title="Agent judgements" icon={<Bot size={12} />}>
                  <ul className="space-y-2">
                    {detail.agent_summaries.map((step) => (
                      <li key={`${step.agent_name}-${step.sequence}`}>
                        <div className="flex items-center gap-2">
                          <span className="text-xs font-medium text-ink">
                            {humanizeNode(step.agent_name)}
                          </span>
                          {step.confidence !== null ? (
                            <span
                              className={`tnum text-xs ${
                                step.confidence < 0.6 ? 'text-warn' : 'text-ok'
                              }`}
                            >
                              {formatConfidence(step.confidence)}
                            </span>
                          ) : null}
                        </div>
                        {step.summary ? (
                          <p className="mt-0.5 text-xs leading-relaxed text-ink-muted">
                            {step.summary}
                          </p>
                        ) : null}
                      </li>
                    ))}
                  </ul>
                </Panel>
              ) : null}
            </>
          ) : null}
        </div>

        <footer className="space-y-3 border-t border-edge bg-surface px-5 py-4">
          {submitError ? <ErrorNote message={submitError} /> : null}

          {!awaitingReview && detail ? (
            <p className="rounded-lg border border-edge bg-surface-raised px-3 py-2 text-xs text-ink-muted">
              This workflow is <strong className="text-ink">{detail.workflow_status}</strong>{' '}
              and is not awaiting a decision. The packet is shown for reference.
            </p>
          ) : null}

          <div className="grid grid-cols-2 gap-3">
            <label className="block">
              <span className="text-xs font-medium text-ink-faint">
                Reviewer name <span className="text-danger">*</span>
              </span>
              <input
                value={reviewerName}
                onChange={(event) => setReviewerName(event.target.value)}
                disabled={!awaitingReview}
                placeholder="e.g. Support Manager"
                className="mt-1 w-full rounded-lg border border-edge-strong bg-surface-raised px-2.5 py-1.5 text-sm text-ink placeholder:text-ink-faint focus:border-accent focus:outline-none disabled:opacity-50"
              />
            </label>
            <label className="block">
              <span className="text-xs font-medium text-ink-faint">Comments</span>
              <input
                value={comments}
                onChange={(event) => setComments(event.target.value)}
                disabled={!awaitingReview}
                placeholder="Optional context for the audit log"
                className="mt-1 w-full rounded-lg border border-edge-strong bg-surface-raised px-2.5 py-1.5 text-sm text-ink placeholder:text-ink-faint focus:border-accent focus:outline-none disabled:opacity-50"
              />
            </label>
          </div>

          <div className="flex gap-3">
            <Button
              variant="danger"
              className="flex-1 py-2"
              icon={<ThumbsDown size={14} />}
              disabled={!awaitingReview || submitting !== null}
              onClick={() => void submit(false)}
            >
              {submitting === 'reject' ? 'Rejecting…' : 'Reject'}
            </Button>
            <Button
              variant="success"
              className="flex-1 py-2"
              icon={<ThumbsUp size={14} />}
              disabled={!awaitingReview || submitting !== null}
              onClick={() => void submit(true)}
            >
              {submitting === 'approve' ? 'Approving…' : 'Approve'}
            </Button>
          </div>
        </footer>
      </aside>
    </div>
  )
}
