/**
 * Status vocabulary and presentation tokens.
 *
 * Every status colour in the product resolves through this module. Defining
 * them once is what keeps a table row, a rail badge and a detail header from
 * drifting apart — the most common way a design language decays.
 *
 * Naming follows the workflow's own vocabulary rather than generic
 * success/warning/error, so the code reads the way operators talk.
 */

import type {
  CustomerTier,
  TicketPriority,
  TicketStatus,
  WorkflowStatus,
} from '../api/types'

export type Semantic = 'neutral' | 'running' | 'ok' | 'attention' | 'failed'

/** Text colour for a status word. Text-safe values, >=4.5:1 on white. */
export const SEMANTIC_FG: Record<Semantic, string> = {
  neutral: 'text-fg-subtle',
  running: 'text-running',
  ok: 'text-ok',
  attention: 'text-attention',
  failed: 'text-failed',
}

/**
 * Dot colour. A 5px dot plus a word replaces the filled pill everywhere.
 *
 * Uses the `-solid` graphic hues, not the text hues: a colour dark enough to
 * read as body text on white is muddy as a 5px dot, and WCAG only asks 3:1 of
 * a non-text graphic. This split is what stops the amber status looking brown.
 */
export const SEMANTIC_DOT: Record<Semantic, string> = {
  neutral: 'bg-fg-faint',
  running: 'bg-running-solid',
  ok: 'bg-ok-solid',
  attention: 'bg-attention-solid',
  failed: 'bg-failed-solid',
}

/**
 * Tinted pill: light wash plus text-safe ink. Reserved for risk level and the
 * attention banner.
 */
export const SEMANTIC_TINT: Record<Semantic, string> = {
  neutral: 'bg-sunken text-fg-muted',
  running: 'bg-running-dim text-running',
  ok: 'bg-ok-dim text-ok',
  attention: 'bg-attention-dim text-attention',
  failed: 'bg-failed-dim text-failed',
}

export const WORKFLOW_SEMANTIC: Record<WorkflowStatus, Semantic> = {
  pending: 'neutral',
  running: 'running',
  waiting_for_hitl: 'attention',
  completed: 'ok',
  failed: 'failed',
}

/**
 * Operator-facing labels. "Queued" and "Needs review" describe what a person
 * should do about the state; "pending" and "waiting_for_hitl" describe the
 * enum. The former belongs in the UI.
 */
export const WORKFLOW_LABEL: Record<WorkflowStatus, string> = {
  pending: 'Queued',
  running: 'Running',
  waiting_for_hitl: 'Needs review',
  completed: 'Completed',
  failed: 'Failed',
}

export const TICKET_SEMANTIC: Record<TicketStatus, Semantic> = {
  open: 'running',
  in_progress: 'running',
  resolved: 'ok',
  closed: 'neutral',
}

export const TICKET_LABEL: Record<TicketStatus, string> = {
  open: 'Open',
  in_progress: 'In progress',
  resolved: 'Resolved',
  closed: 'Closed',
}

/**
 * Priority is rendered as a text weight rather than a colour, except at the top
 * two levels. If every priority is coloured, none of them reads as urgent.
 */
export const PRIORITY_STYLE: Record<TicketPriority, string> = {
  low: 'text-fg-faint',
  medium: 'text-fg-muted',
  high: 'text-attention',
  critical: 'text-failed font-medium',
}

export const PRIORITY_LABEL: Record<TicketPriority, string> = {
  low: 'Low',
  medium: 'Medium',
  high: 'High',
  critical: 'Critical',
}

/** Tier is metadata, not status — muted, and only Enterprise is emphasised. */
export const TIER_STYLE: Record<CustomerTier, string> = {
  basic: 'text-fg-subtle',
  premium: 'text-fg-muted',
  enterprise: 'text-fg font-medium',
}

export function riskSemantic(level: string | null | undefined): Semantic {
  if (level === 'high') return 'failed'
  if (level === 'medium') return 'attention'
  if (level === 'low') return 'ok'
  return 'neutral'
}

/** Thresholds mirror the Risk Engine's low/medium/high scores (0.2/0.5/0.9). */
export function riskSemanticFromScore(score: number | null | undefined): Semantic {
  if (score === null || score === undefined) return 'neutral'
  if (score >= 0.9) return 'failed'
  if (score >= 0.5) return 'attention'
  return 'ok'
}

/**
 * The workflow topology (SRS §37), in execution order.
 *
 * The trace renders this as the expected path and overlays the nodes that
 * actually ran, so an operator can see what is still ahead as well as what
 * happened. Mirrors `app/graph/workflow.py`: a node added to the graph must be
 * added here or the timeline will silently omit it.
 */
export interface Stage {
  /** Backend node ids satisfying this stage. */
  nodes: string[]
  label: string
  /** A plan-driven fan-out rather than one sequential node. */
  parallel?: boolean
  /** Runs only when the Risk Engine demands a human. */
  conditional?: boolean
}

export const PIPELINE: Stage[] = [
  { nodes: ['supervisor'], label: 'Supervisor' },
  { nodes: ['task_planner'], label: 'Planner' },
  {
    nodes: ['billing_agent', 'account_agent', 'technical_agent'],
    label: 'Domain agents',
    parallel: true,
  },
  { nodes: ['policy_agent'], label: 'Policy' },
  { nodes: ['results_aggregator'], label: 'Aggregator' },
  { nodes: ['risk_engine'], label: 'Risk engine' },
  { nodes: ['human_approval'], label: 'Human approval', conditional: true },
  { nodes: ['response_agent'], label: 'Response' },
  { nodes: ['dispatcher'], label: 'Dispatch' },
]

/**
 * Nodes that call an LLM. The rest are deterministic Python, and the trace
 * distinguishes them: a 0ms deterministic node is healthy, whereas a 0ms
 * reasoning node would be suspicious.
 */
export const REASONING_NODES = new Set([
  'supervisor',
  'billing_agent',
  'account_agent',
  'technical_agent',
  'policy_agent',
  'response_agent',
])

/** Confidence below the backend's HITL threshold (0.6) is worth flagging. */
export const LOW_CONFIDENCE = 0.6
