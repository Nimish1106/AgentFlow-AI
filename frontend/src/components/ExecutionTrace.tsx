/**
 * Live Execution Trace & Timeline.
 *
 * Renders the SRS §37 pipeline (Supervisor -> Planner -> Domain Agents ->
 * Policy -> Aggregator -> Risk Engine -> Response -> Dispatcher) and overlays
 * the steps that actually executed, so a viewer sees both what happened and
 * what is still ahead.
 *
 * Only nodes that ran produce a trace row. A stage with no matching row is
 * either pending or was skipped - the planner fans out to just the domain
 * agents a ticket needs, and human approval only runs when risk demands it.
 */

import {
  AlertTriangle,
  Bot,
  CheckCircle2,
  ChevronRight,
  Circle,
  Cpu,
  GitBranch,
  Loader2,
  Wrench,
} from 'lucide-react'
import type { TraceStep, WorkflowTrace } from '../api/types'
import { formatConfidence, formatDuration, humanizeNode } from '../lib/format'
import {
  PIPELINE,
  REASONING_NODES,
  riskToneFromScore,
  tone,
  WORKFLOW_STATUS_LABEL,
  WORKFLOW_STATUS_TONE,
} from '../lib/status'
import { Badge, Card, EmptyState, ErrorNote, SectionHeader } from './ui'

type StageState = 'done' | 'failed' | 'active' | 'pending'

interface RenderedStage {
  label: string
  parallel: boolean
  state: StageState
  steps: TraceStep[]
}

/**
 * Zip the executed steps onto the canonical pipeline.
 *
 * A stage is `active` when it is the workflow's current node, `done`/`failed`
 * from its steps' statuses, and `pending` when nothing has run yet.
 */
function buildStages(trace: WorkflowTrace | null): RenderedStage[] {
  const byNode = new Map<string, TraceStep[]>()
  for (const step of trace?.steps ?? []) {
    const existing = byNode.get(step.agent_name)
    if (existing) existing.push(step)
    else byNode.set(step.agent_name, [step])
  }

  return PIPELINE.map((stage) => {
    const steps = stage.nodes.flatMap((node) => byNode.get(node) ?? [])
    const isCurrent =
      trace?.current_node !== null &&
      trace?.current_node !== undefined &&
      stage.nodes.includes(trace.current_node)

    let state: StageState = 'pending'
    if (steps.some((step) => step.status !== 'completed')) state = 'failed'
    else if (steps.length > 0) state = 'done'
    // A running workflow sitting on this node outranks "done": the node may be
    // re-entered, as human_approval is on resume.
    if (isCurrent && trace?.workflow_status === 'running') state = 'active'
    if (isCurrent && trace?.workflow_status === 'waiting_for_hitl') state = 'active'

    return { label: stage.label, parallel: stage.parallel ?? false, state, steps }
  })
}

function StageIcon({ state }: { state: StageState }) {
  if (state === 'done') return <CheckCircle2 size={15} className="text-ok" />
  if (state === 'failed') return <AlertTriangle size={15} className="text-danger" />
  if (state === 'active')
    return <Loader2 size={15} className="animate-spin text-info" />
  return <Circle size={15} className="text-ink-faint" />
}

function StepDetail({ step }: { step: TraceStep }) {
  const isReasoning = REASONING_NODES.has(step.agent_name)
  const failed = step.status !== 'completed'

  return (
    <div
      className={`rounded-lg border px-3 py-2 ${
        failed ? 'border-danger/30 bg-danger-soft' : 'border-edge bg-surface-raised'
      }`}
    >
      <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
        <span className="inline-flex items-center gap-1.5 text-xs font-medium text-ink">
          {isReasoning ? (
            <Bot size={12} className="text-accent" />
          ) : (
            <Cpu size={12} className="text-ink-faint" />
          )}
          {humanizeNode(step.agent_name)}
        </span>

        <span className="tnum text-xs text-ink-faint">
          {formatDuration(step.execution_time_ms)}
        </span>

        {step.tool_calls > 0 ? (
          <span className="tnum inline-flex items-center gap-1 text-xs text-ink-muted">
            <Wrench size={11} />
            {step.tool_calls} tool call{step.tool_calls === 1 ? '' : 's'}
          </span>
        ) : null}

        {step.confidence !== null ? (
          <span
            className={`tnum text-xs font-medium ${
              step.confidence < 0.6 ? 'text-warn' : 'text-ok'
            }`}
            title="LLM confidence"
          >
            {formatConfidence(step.confidence)} confidence
          </span>
        ) : null}

        {failed ? <Badge toneName="danger">failed</Badge> : null}
      </div>

      {step.summary ? (
        <p className="mt-1.5 text-xs leading-relaxed text-ink-muted">{step.summary}</p>
      ) : null}
    </div>
  )
}

export function ExecutionTrace({
  trace,
  ticketTitle,
  loading,
  error,
}: {
  trace: WorkflowTrace | null
  ticketTitle: string | null
  loading: boolean
  error: string | null
}) {
  if (!trace && !loading) {
    return (
      <Card className="h-full">
        <SectionHeader
          icon={<GitBranch size={15} />}
          title="Execution trace"
          subtitle="Select a ticket to inspect its workflow"
        />
        <EmptyState
          icon={<GitBranch size={22} />}
          title="No workflow selected"
          hint="Pick a row in the operations hub to watch its agents execute step by step."
        />
      </Card>
    )
  }

  const stages = buildStages(trace)
  const totalMs = (trace?.steps ?? []).reduce(
    (sum, step) => sum + step.execution_time_ms,
    0,
  )

  return (
    <Card className="flex h-full flex-col">
      <SectionHeader
        icon={<GitBranch size={15} />}
        title="Execution trace"
        subtitle={ticketTitle ?? undefined}
        actions={
          trace ? (
            <div className="flex items-center gap-2">
              {trace.risk_score !== null ? (
                <Badge toneName={riskToneFromScore(trace.risk_score)}>
                  risk {trace.risk_score.toFixed(2)}
                </Badge>
              ) : null}
              <Badge toneName={WORKFLOW_STATUS_TONE[trace.workflow_status] ?? 'neutral'}>
                {WORKFLOW_STATUS_LABEL[trace.workflow_status] ?? trace.workflow_status}
              </Badge>
            </div>
          ) : null
        }
      />

      <div className="flex-1 overflow-y-auto px-5 py-4">
        {error ? (
          <div className="mb-3">
            <ErrorNote message={error} />
          </div>
        ) : null}

        {loading && !trace ? (
          <div className="space-y-3">
            {Array.from({ length: 6 }).map((_, index) => (
              <div key={index} className="skeleton h-12 rounded-lg" />
            ))}
          </div>
        ) : (
          <ol className="relative space-y-1">
            {stages.map((stage, index) => {
              const isLast = index === stages.length - 1
              return (
                <li key={stage.label} className="animate-fade-rise flex gap-3">
                  {/* Rail: icon plus the connector down to the next stage. */}
                  <div className="flex flex-col items-center">
                    <span
                      className={`flex size-6 shrink-0 items-center justify-center rounded-full bg-surface ring-1 ${
                        stage.state === 'active'
                          ? 'animate-pulse-ring ring-info/50'
                          : 'ring-edge-strong'
                      }`}
                    >
                      <StageIcon state={stage.state} />
                    </span>
                    {!isLast ? (
                      <span
                        className={`w-px flex-1 ${
                          stage.state === 'done' ? 'bg-ok/30' : 'bg-edge-strong'
                        }`}
                      />
                    ) : null}
                  </div>

                  <div className={`min-w-0 flex-1 ${isLast ? 'pb-0' : 'pb-4'}`}>
                    <div className="flex items-center gap-2">
                      <span
                        className={`text-xs font-semibold ${
                          stage.state === 'pending' ? 'text-ink-faint' : 'text-ink'
                        }`}
                      >
                        {stage.label}
                      </span>
                      {stage.parallel && stage.steps.length > 1 ? (
                        <Badge toneName="accent">
                          {stage.steps.length} in parallel
                        </Badge>
                      ) : null}
                      {stage.state === 'pending' ? (
                        <span className="text-xs text-ink-faint">pending</span>
                      ) : null}
                    </div>

                    {stage.steps.length > 0 ? (
                      <div className="mt-1.5 space-y-1.5">
                        {stage.steps.map((step) => (
                          <StepDetail key={`${step.agent_name}-${step.sequence}`} step={step} />
                        ))}
                      </div>
                    ) : null}
                  </div>
                </li>
              )
            })}
          </ol>
        )}
      </div>

      {trace && trace.steps.length > 0 ? (
        <div className="flex items-center justify-between border-t border-edge px-5 py-2.5 text-xs text-ink-faint">
          <span className="inline-flex items-center gap-1">
            <ChevronRight size={12} />
            {trace.steps.length} node{trace.steps.length === 1 ? '' : 's'} executed
          </span>
          <span className={`tnum ${tone('neutral').text}`}>
            total {formatDuration(totalMs)}
          </span>
        </div>
      ) : null}
    </Card>
  )
}
