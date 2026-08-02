/**
 * Execution trace.
 *
 * The single most valuable diagnostic surface in the product, and the one the
 * previous design wasted: it printed timings as text, so a 12-second agent and
 * a 0ms deterministic node looked identical.
 *
 * Here every executed node gets a bar proportional to its share of total
 * wall-clock. "Where did the time go" becomes answerable at a glance, which is
 * the only question anyone opens this panel to ask.
 *
 * The full SRS §37 topology is always rendered, so stages that have not run yet
 * read as pending rather than being invisible.
 */

import { Bot, Cpu } from 'lucide-react'
import type { TraceStep, WorkflowTrace } from '../api/types'
import { formatConfidence, formatDurationTerse, humanizeNode } from '../lib/format'
import {
  LOW_CONFIDENCE,
  PIPELINE,
  REASONING_NODES,
  WORKFLOW_LABEL,
  WORKFLOW_SEMANTIC,
  riskSemanticFromScore,
} from '../lib/status'
import { Empty, Panel, PanelHead, Pill, Status } from './primitives'

type StageState = 'done' | 'failed' | 'active' | 'skipped' | 'pending'

interface RenderedStage {
  label: string
  parallel: boolean
  conditional: boolean
  state: StageState
  steps: TraceStep[]
}

function buildStages(trace: WorkflowTrace | null): RenderedStage[] {
  const byNode = new Map<string, TraceStep[]>()
  for (const step of trace?.steps ?? []) {
    const existing = byNode.get(step.agent_name)
    if (existing) existing.push(step)
    else byNode.set(step.agent_name, [step])
  }

  const terminal =
    trace?.workflow_status === 'completed' || trace?.workflow_status === 'failed'

  return PIPELINE.map((stage) => {
    const steps = stage.nodes.flatMap((node) => byNode.get(node) ?? [])
    const isCurrent =
      !!trace?.current_node && stage.nodes.includes(trace.current_node)

    let state: StageState = 'pending'
    if (steps.some((s) => s.status !== 'completed')) state = 'failed'
    else if (steps.length > 0) state = 'done'
    // A conditional stage that never ran on a finished workflow was skipped by
    // design (no human was needed), not left pending.
    else if (stage.conditional && terminal) state = 'skipped'
    else if (terminal) state = 'skipped'

    if (isCurrent && trace?.workflow_status === 'running') state = 'active'
    if (isCurrent && trace?.workflow_status === 'waiting_for_hitl') state = 'active'

    return {
      label: stage.label,
      parallel: stage.parallel ?? false,
      conditional: stage.conditional ?? false,
      state,
      steps,
    }
  })
}

/**
 * Rail and label colours per stage state.
 *
 * The rail is a graphic, so it uses the `-solid` hues: the text-safe hues are
 * tuned for legibility as words on white and read muddy as a 3px spine.
 */
const STATE_STYLE: Record<StageState, { rail: string; text: string }> = {
  done: { rail: 'bg-ok-solid', text: 'text-fg' },
  failed: { rail: 'bg-failed-solid', text: 'text-failed' },
  active: { rail: 'bg-running-solid', text: 'text-running' },
  skipped: { rail: 'bg-line-strong', text: 'text-fg-faint' },
  pending: { rail: 'bg-line-strong', text: 'text-fg-faint' },
}

/**
 * One executed node.
 *
 * The bar is the component's reason for existing: width is the node's share of
 * total run time, so the expensive step is visually obvious without reading a
 * single number.
 */
function StepRow({ step, totalMs }: { step: TraceStep; totalMs: number }) {
  const reasoning = REASONING_NODES.has(step.agent_name)
  const failed = step.status !== 'completed'
  const share = totalMs > 0 ? step.execution_time_ms / totalMs : 0
  const lowConfidence =
    step.confidence !== null && step.confidence < LOW_CONFIDENCE

  return (
    <div className="group py-1">
      <div className="flex items-center gap-2">
        {reasoning ? (
          <Bot size={11} className="shrink-0 text-fg-subtle" strokeWidth={2} />
        ) : (
          <Cpu size={11} className="shrink-0 text-fg-faint" strokeWidth={2} />
        )}

        <span
          className={`min-w-0 flex-1 truncate text-data ${
            failed ? 'text-failed' : 'text-fg-muted'
          }`}
        >
          {humanizeNode(step.agent_name)}
        </span>

        {step.tool_calls > 0 ? (
          <span
            className="tnum shrink-0 text-meta text-fg-subtle"
            title={`${step.tool_calls} MCP tool call${step.tool_calls === 1 ? '' : 's'}`}
          >
            {step.tool_calls}&thinsp;<span className="text-fg-faint">tools</span>
          </span>
        ) : null}

        {step.confidence !== null ? (
          <span
            className={`tnum shrink-0 text-meta ${
              lowConfidence ? 'text-attention' : 'text-fg-subtle'
            }`}
            title={
              lowConfidence
                ? 'Below the confidence threshold that routes to human review'
                : 'Model confidence'
            }
          >
            {formatConfidence(step.confidence)}
          </span>
        ) : null}

        <span className="tnum w-14 shrink-0 text-right text-meta text-fg-muted">
          {formatDurationTerse(step.execution_time_ms)}
        </span>
      </div>

      {/* Proportional duration bar. Sub-1% durations still render a hairline so
          a fast node reads as "ran, instantly" rather than "did not run".
          Solid fills, not 70% alpha: a translucent bar over a light gray track
          loses almost all of its contrast. */}
      <div className="mt-1 ml-[19px] h-[3px] overflow-hidden rounded-full bg-sunken">
        <div
          className={`h-full rounded-full ${failed ? 'bg-failed-solid' : 'bg-accent'}`}
          style={{ width: `${Math.max(share * 100, share > 0 ? 1.5 : 0)}%` }}
        />
      </div>

      {step.summary ? (
        <p className="mt-1 ml-[19px] line-clamp-2 text-meta leading-[1.05rem] text-fg-subtle">
          {step.summary}
        </p>
      ) : null}
    </div>
  )
}

export function ExecutionTrace({
  trace,
  title,
  loading,
  error,
}: {
  trace: WorkflowTrace | null
  title: string | null
  loading: boolean
  error: string | null
}) {
  const stages = buildStages(trace)
  const steps = trace?.steps ?? []
  const totalMs = steps.reduce((sum, s) => sum + s.execution_time_ms, 0)
  const slowest = steps.reduce<TraceStep | null>(
    (worst, s) => (worst === null || s.execution_time_ms > worst.execution_time_ms ? s : worst),
    null,
  )

  if (!trace && !loading) {
    return (
      <Panel className="flex h-full flex-col">
        <PanelHead title="Execution trace" />
        <Empty
          title="No workflow selected"
          hint="Choose a ticket or workflow to inspect how its agents executed."
        />
      </Panel>
    )
  }

  return (
    <Panel className="flex h-full min-h-0 flex-col">
      <PanelHead
        title="Execution trace"
        meta={title ?? undefined}
        actions={
          trace ? (
            <div className="flex items-center gap-2">
              {trace.risk_score !== null ? (
                <Pill semantic={riskSemanticFromScore(trace.risk_score)}>
                  risk {trace.risk_score.toFixed(2)}
                </Pill>
              ) : null}
              <Status
                semantic={WORKFLOW_SEMANTIC[trace.workflow_status]}
                label={WORKFLOW_LABEL[trace.workflow_status]}
                pulse={trace.workflow_status === 'running'}
              />
            </div>
          ) : null
        }
      />

      {/* Run summary. Total and the dominant node answer the two questions an
          operator has before reading any individual step. */}
      {trace && steps.length > 0 ? (
        <div className="flex items-center gap-4 border-b border-line px-3 py-2">
          <div>
            <div className="label-micro">Total</div>
            <div className="tnum mt-0.5 text-data font-medium text-fg">
              {formatDurationTerse(totalMs)}
            </div>
          </div>
          <div className="min-w-0">
            <div className="label-micro">Slowest node</div>
            <div className="mt-0.5 truncate text-data text-fg-muted">
              {slowest ? (
                <>
                  {humanizeNode(slowest.agent_name)}
                  <span className="tnum ml-1.5 text-fg-subtle">
                    {formatDurationTerse(slowest.execution_time_ms)}
                  </span>
                </>
              ) : (
                '—'
              )}
            </div>
          </div>
          <div className="ml-auto text-right">
            <div className="label-micro">Nodes</div>
            <div className="tnum mt-0.5 text-data text-fg-muted">{steps.length}</div>
          </div>
        </div>
      ) : null}

      <div className="min-h-0 flex-1 overflow-y-auto px-3 py-2">
        {error ? (
          <div className="mb-2 rounded-sm border border-failed/30 bg-failed-dim px-2.5 py-1.5 text-meta text-failed">
            {error}
          </div>
        ) : null}

        {loading && !trace ? (
          <div className="space-y-2 py-1">
            {Array.from({ length: 7 }).map((_, i) => (
              <div key={i} className="skeleton h-8 rounded-sm" />
            ))}
          </div>
        ) : (
          <ol>
            {stages.map((stage, index) => {
              const last = index === stages.length - 1
              const style = STATE_STYLE[stage.state]
              return (
                <li key={stage.label} className="flex gap-2.5">
                  {/* Rail: a continuous 2px spine, filled where the workflow has
                      actually reached. Reads as progress, not decoration. */}
                  <div className="flex w-[3px] shrink-0 flex-col items-center">
                    <span className={`h-full w-[3px] rounded-full ${style.rail}`} />
                    {last ? null : <span className="h-1" />}
                  </div>

                  <div className={`min-w-0 flex-1 ${last ? 'pb-1' : 'pb-2.5'}`}>
                    <div className="flex items-center gap-2 pt-0.5">
                      <span className={`text-data font-medium ${style.text}`}>
                        {stage.label}
                      </span>
                      {stage.parallel && stage.steps.length > 1 ? (
                        <span className="text-meta text-fg-faint">
                          {stage.steps.length} in parallel
                        </span>
                      ) : null}
                      {stage.state === 'pending' ? (
                        <span className="text-meta text-fg-faint">pending</span>
                      ) : null}
                      {stage.state === 'skipped' ? (
                        <span className="text-meta text-fg-faint">
                          {stage.conditional ? 'not required' : 'skipped'}
                        </span>
                      ) : null}
                      {stage.state === 'active' ? (
                        <span className="text-meta text-running">running</span>
                      ) : null}
                    </div>

                    {stage.steps.length > 0 ? (
                      <div className="mt-0.5">
                        {stage.steps.map((step) => (
                          <StepRow
                            key={`${step.agent_name}-${step.sequence}`}
                            step={step}
                            totalMs={totalMs}
                          />
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
    </Panel>
  )
}
