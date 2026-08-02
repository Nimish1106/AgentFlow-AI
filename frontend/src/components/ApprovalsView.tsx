/**
 * Approvals: the review queue and the decision pane.
 *
 * Promoted from a drawer to a first-class destination. Previously a reviewer
 * reached a paused workflow by noticing a badge on a table row; a queue that
 * people are accountable for clearing deserves its own place.
 *
 * Layout is deliberate for the stakes involved: the risk assessment and the
 * money at issue sit directly above the decision controls, so nothing that
 * matters is below the fold at the moment of clicking Approve. Approve and
 * Reject carry equal visual weight and neither is autofocused — releasing a
 * refund should require aim, not reflex.
 */

import { useMemo, useState } from 'react'
import { ArrowLeft, ShieldCheck } from 'lucide-react'

import { ApiError, api } from '../api/client'
import type { ApprovalDetail, WorkflowSummary } from '../api/types'
import {
  formatConfidence,
  formatDate,
  formatMoney,
  formatRelative,
  humanizeNode,
} from '../lib/format'
import {
  LOW_CONFIDENCE,
  PRIORITY_LABEL,
  PRIORITY_STYLE,
  TIER_STYLE,
  riskSemantic,
} from '../lib/status'
import {
  Button,
  Empty,
  ErrorNote,
  FIELD,
  Field,
  Panel,
  PanelHead,
  Pill,
} from './primitives'

/** Left column: the queue of workflows parked for review. */
function Queue({
  items,
  selectedId,
  onSelect,
}: {
  items: WorkflowSummary[]
  selectedId: string | null
  onSelect: (workflowId: string) => void
}) {
  return (
    <Panel className="flex h-full min-h-0 flex-col">
      <PanelHead title="Review queue" meta={`${items.length} pending`} />
      {items.length === 0 ? (
        <Empty
          icon={ShieldCheck}
          title="Queue clear"
          hint="No workflows are waiting on a human decision."
        />
      ) : (
        <ul className="min-h-0 flex-1 overflow-y-auto">
          {items.map((workflow) => {
            const selected = workflow.workflow_id === selectedId
            return (
              <li key={workflow.workflow_id}>
                <button
                  type="button"
                  onClick={() => onSelect(workflow.workflow_id)}
                  aria-current={selected ? 'true' : undefined}
                  className={`flex w-full flex-col items-start gap-0.5 border-b border-line px-3 py-2 text-left transition-colors duration-100 last:border-0 ${
                    selected
                      ? 'bg-accent-dim shadow-[inset_2px_0_0_var(--color-accent)]'
                      : 'hover:bg-hover'
                  }`}
                >
                  <span className="w-full truncate text-data text-fg">
                    {workflow.ticket_title}
                  </span>
                  <span className="text-meta text-fg-subtle">
                    {workflow.customer_name}
                    <span className="text-fg-faint">
                      {' · '}
                      {formatRelative(workflow.started_at)}
                    </span>
                  </span>
                </button>
              </li>
            )
          })}
        </ul>
      )}
    </Panel>
  )
}

/** Right column: everything needed to decide, then the decision itself. */
function ReviewPane({
  detail,
  loading,
  error,
  onDecided,
  onBack,
}: {
  detail: ApprovalDetail | null
  loading: boolean
  error: string | null
  onDecided: () => void
  onBack?: () => void
}) {
  const [reviewer, setReviewer] = useState('')
  const [comments, setComments] = useState('')
  const [submitting, setSubmitting] = useState<'approve' | 'reject' | null>(null)
  const [submitError, setSubmitError] = useState<string | null>(null)

  const awaiting = detail?.workflow_status === 'waiting_for_hitl'

  /** The invoice most likely at issue: the duplicate one, else the newest. */
  const focusInvoice = useMemo(() => {
    if (!detail?.invoices.length) return null
    return detail.invoices.find((i) => i.payment_status === 'duplicate') ?? detail.invoices[0]
  }, [detail])

  if (!detail && !loading) {
    return (
      <Panel className="flex h-full items-center justify-center">
        <Empty
          title="Select an item to review"
          hint="Each item shows the risk assessment, the customer's billing context and the agents' reasoning."
        />
      </Panel>
    )
  }

  const submit = async (approved: boolean) => {
    if (!detail) return
    if (!reviewer.trim()) {
      setSubmitError('Enter your name — approvals are recorded against a reviewer.')
      return
    }
    setSubmitting(approved ? 'approve' : 'reject')
    setSubmitError(null)
    try {
      await api.submitApproval(detail.workflow_id, {
        approved,
        reviewer_name: reviewer.trim(),
        comments: comments.trim(),
      })
      setComments('')
      onDecided()
    } catch (err) {
      setSubmitError(
        err instanceof ApiError && err.status === 409
          ? 'This workflow is no longer awaiting approval — someone may have decided it already.'
          : err instanceof Error
            ? err.message
            : 'Could not submit the decision.',
      )
    } finally {
      setSubmitting(null)
    }
  }

  return (
    <Panel className="flex h-full min-h-0 flex-col">
      <PanelHead
        title="Review"
        meta={detail?.ticket_title}
        actions={
          onBack ? (
            <Button size="sm" variant="quiet" icon={<ArrowLeft size={12} />} onClick={onBack}>
              Queue
            </Button>
          ) : undefined
        }
      />

      {loading && !detail ? (
        <div className="space-y-2 p-3">
          {Array.from({ length: 6 }).map((_, i) => (
            <div key={i} className="skeleton h-14 rounded-sm" />
          ))}
        </div>
      ) : detail ? (
        <>
          <div className="min-h-0 flex-1 overflow-y-auto">
            {error ? (
              <div className="p-3">
                <ErrorNote message={error} />
              </div>
            ) : null}

            {/* Risk first: it is why this workflow stopped. */}
            <section className="border-b border-line px-3 py-3">
              <div className="flex items-center gap-2">
                <span className="label-micro">Risk assessment</span>
                {detail.risk_level ? (
                  <Pill semantic={riskSemantic(detail.risk_level)}>
                    {detail.risk_level}
                  </Pill>
                ) : (
                  <span className="text-meta text-fg-faint">not assessed</span>
                )}
                {detail.risk_score !== null ? (
                  <span className="tnum ml-auto text-data font-medium text-fg">
                    {detail.risk_score.toFixed(2)}
                  </span>
                ) : null}
              </div>

              {detail.reasons.length > 0 ? (
                <ul className="mt-2 space-y-1">
                  {detail.reasons.map((reason, index) => (
                    <li key={index} className="flex gap-2 text-meta leading-4 text-fg-muted">
                      <span className="mt-1.5 size-1 shrink-0 rounded-full bg-attention-solid" />
                      {reason}
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="mt-2 text-meta text-fg-faint">
                  No risk factors were recorded for this workflow.
                </p>
              )}
            </section>

            {/* The money at issue, stated plainly — the single most consequential
                fact on this screen. */}
            {focusInvoice ? (
              <section className="border-b border-line px-3 py-3">
                <div className="label-micro">Amount in question</div>
                <div className="mt-1 flex items-baseline gap-2">
                  <span className="tnum text-figure font-semibold tracking-tight text-fg">
                    {formatMoney(focusInvoice.amount, focusInvoice.currency)}
                  </span>
                  <span
                    className={`text-data ${
                      focusInvoice.payment_status === 'duplicate'
                        ? 'text-failed'
                        : 'text-fg-subtle'
                    }`}
                  >
                    {focusInvoice.payment_status}
                  </span>
                </div>
                <div className="mt-0.5 text-meta text-fg-faint">
                  Invoiced {formatDate(focusInvoice.created_at)}
                  {detail.invoices.length > 1
                    ? ` · ${detail.invoices.length} invoices on file`
                    : ''}
                </div>
              </section>
            ) : null}

            <section className="border-b border-line px-3 py-2.5">
              <div className="label-micro mb-1">Customer</div>
              <Field label="Contact">{detail.customer_name}</Field>
              <Field label="Company">{detail.company_name}</Field>
              <Field label="Tier">
                <span className={`capitalize ${TIER_STYLE[detail.customer_tier]}`}>
                  {detail.customer_tier}
                </span>
              </Field>
              <Field label="Priority">
                <span className={PRIORITY_STYLE[detail.priority]}>
                  {PRIORITY_LABEL[detail.priority]}
                </span>
              </Field>
              {detail.subscription ? (
                <Field label="Subscription">
                  {formatMoney(detail.subscription.monthly_price)}/mo ·{' '}
                  {detail.subscription.subscription_status}
                </Field>
              ) : null}
            </section>

            <section className="border-b border-line px-3 py-2.5">
              <div className="label-micro mb-1.5">Customer's report</div>
              <p className="max-h-28 overflow-y-auto rounded-sm bg-sunken px-2.5 py-2 text-meta leading-[1.1rem] whitespace-pre-wrap text-fg-muted">
                {detail.issue_text}
              </p>
            </section>

            {detail.agent_summaries.length > 0 ? (
              <section className="px-3 py-2.5">
                <div className="label-micro mb-1.5">Agent findings</div>
                <ul className="space-y-2">
                  {detail.agent_summaries.map((step) => {
                    const low =
                      step.confidence !== null && step.confidence < LOW_CONFIDENCE
                    return (
                      <li key={`${step.agent_name}-${step.sequence}`}>
                        <div className="flex items-baseline gap-2">
                          <span className="text-data font-medium text-fg">
                            {humanizeNode(step.agent_name)}
                          </span>
                          {step.confidence !== null ? (
                            <span
                              className={`tnum text-meta ${
                                low ? 'text-attention' : 'text-fg-subtle'
                              }`}
                            >
                              {formatConfidence(step.confidence)}
                              {low ? ' · low' : ''}
                            </span>
                          ) : null}
                        </div>
                        {step.summary ? (
                          <p className="mt-0.5 text-meta leading-[1.05rem] text-fg-subtle">
                            {step.summary}
                          </p>
                        ) : null}
                      </li>
                    )
                  })}
                </ul>
              </section>
            ) : null}
          </div>

          {/* Decision. Anchored to the bottom of the pane so it is always
              reachable without scrolling back. */}
          <div className="shrink-0 space-y-2 border-t border-line bg-overlay px-3 py-2.5">
            {submitError ? <ErrorNote message={submitError} /> : null}

            {!awaiting ? (
              <p className="rounded-sm border border-line bg-raised px-2.5 py-1.5 text-meta text-fg-muted">
                This workflow is <span className="text-fg">{detail.workflow_status}</span>{' '}
                and is not awaiting a decision. Shown for reference.
              </p>
            ) : null}

            <div className="grid grid-cols-2 gap-2">
              <label className="block">
                <span className="label-micro">Reviewer</span>
                <input
                  value={reviewer}
                  onChange={(event) => setReviewer(event.target.value)}
                  disabled={!awaiting}
                  placeholder="Your name"
                  className={`${FIELD} mt-1 h-7 px-2 text-data`}
                />
              </label>
              <label className="block">
                <span className="label-micro">Note (optional)</span>
                <input
                  value={comments}
                  onChange={(event) => setComments(event.target.value)}
                  disabled={!awaiting}
                  placeholder="Recorded in the audit log"
                  className={`${FIELD} mt-1 h-7 px-2 text-data`}
                />
              </label>
            </div>

            <div className="flex gap-2">
              <Button
                variant="reject"
                className="h-8 flex-1"
                disabled={!awaiting || submitting !== null}
                onClick={() => void submit(false)}
              >
                {submitting === 'reject' ? 'Rejecting…' : 'Reject'}
              </Button>
              <Button
                variant="approve"
                className="h-8 flex-1"
                disabled={!awaiting || submitting !== null}
                onClick={() => void submit(true)}
              >
                {submitting === 'approve' ? 'Approving…' : 'Approve'}
              </Button>
            </div>
          </div>
        </>
      ) : null}
    </Panel>
  )
}

export function ApprovalsView({
  queue,
  selectedId,
  detail,
  detailLoading,
  detailError,
  onSelect,
  onDecided,
}: {
  queue: WorkflowSummary[]
  selectedId: string | null
  detail: ApprovalDetail | null
  detailLoading: boolean
  detailError: string | null
  onSelect: (workflowId: string) => void
  onDecided: () => void
}) {
  return (
    <div className="grid h-full min-h-0 grid-cols-1 gap-3 p-4 lg:grid-cols-[20rem_1fr]">
      <Queue items={queue} selectedId={selectedId} onSelect={onSelect} />
      {/*
        Keyed on the workflow id so React remounts the pane when the reviewer
        moves to a different item. That resets the comment box and any error
        without a reset-state effect, and guarantees one item's note can never
        be submitted against another.
      */}
      <ReviewPane
        key={selectedId ?? 'none'}
        detail={detail}
        loading={detailLoading}
        error={detailError}
        onDecided={onDecided}
      />
    </div>
  )
}
