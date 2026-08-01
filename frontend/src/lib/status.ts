/**
 * Shared presentation tokens and the canonical workflow pipeline.
 *
 * Status colours live here rather than inline so a badge, a table row and a
 * timeline node cannot drift apart.
 */

import type { TicketPriority, TicketStatus, WorkflowStatus, CustomerTier } from '../api/types'

export interface Tone {
  /** Tailwind classes for a filled pill. */
  chip: string
  /** Bare colour class for icons and text. */
  text: string
  /** Background for a timeline dot or an accent bar. */
  dot: string
}

const TONES = {
  neutral: {
    chip: 'bg-surface-hover text-ink-muted ring-1 ring-edge-strong',
    text: 'text-ink-muted',
    dot: 'bg-ink-faint',
  },
  info: {
    chip: 'bg-info-soft text-info ring-1 ring-info/25',
    text: 'text-info',
    dot: 'bg-info',
  },
  ok: {
    chip: 'bg-ok-soft text-ok ring-1 ring-ok/25',
    text: 'text-ok',
    dot: 'bg-ok',
  },
  warn: {
    chip: 'bg-warn-soft text-warn ring-1 ring-warn/25',
    text: 'text-warn',
    dot: 'bg-warn',
  },
  danger: {
    chip: 'bg-danger-soft text-danger ring-1 ring-danger/25',
    text: 'text-danger',
    dot: 'bg-danger',
  },
  accent: {
    chip: 'bg-accent-soft text-accent ring-1 ring-accent/25',
    text: 'text-accent',
    dot: 'bg-accent',
  },
} as const satisfies Record<string, Tone>

export type ToneName = keyof typeof TONES

export function tone(name: ToneName): Tone {
  return TONES[name]
}

export const WORKFLOW_STATUS_TONE: Record<WorkflowStatus, ToneName> = {
  pending: 'neutral',
  running: 'info',
  waiting_for_hitl: 'warn',
  completed: 'ok',
  failed: 'danger',
}

export const WORKFLOW_STATUS_LABEL: Record<WorkflowStatus, string> = {
  pending: 'Queued',
  running: 'Running',
  waiting_for_hitl: 'Awaiting approval',
  completed: 'Completed',
  failed: 'Failed',
}

export const TICKET_STATUS_TONE: Record<TicketStatus, ToneName> = {
  open: 'info',
  in_progress: 'accent',
  resolved: 'ok',
  closed: 'neutral',
}

export const TICKET_STATUS_LABEL: Record<TicketStatus, string> = {
  open: 'Open',
  in_progress: 'In progress',
  resolved: 'Resolved',
  closed: 'Closed',
}

export const PRIORITY_TONE: Record<TicketPriority, ToneName> = {
  low: 'neutral',
  medium: 'info',
  high: 'warn',
  critical: 'danger',
}

export const TIER_TONE: Record<CustomerTier, ToneName> = {
  basic: 'neutral',
  premium: 'info',
  enterprise: 'accent',
}

export function riskTone(level: string | null | undefined): ToneName {
  if (level === 'high') return 'danger'
  if (level === 'medium') return 'warn'
  if (level === 'low') return 'ok'
  return 'neutral'
}

/** Risk score thresholds match the Risk Engine's low/medium/high (0.2/0.5/0.9). */
export function riskToneFromScore(score: number | null | undefined): ToneName {
  if (score === null || score === undefined) return 'neutral'
  if (score >= 0.9) return 'danger'
  if (score >= 0.5) return 'warn'
  return 'ok'
}

/**
 * The workflow topology, in execution order (SRS §37).
 *
 * The timeline renders this as the expected path and overlays whichever steps
 * actually ran, so a viewer can see what is still ahead. Domain agents are
 * grouped: the planner fans out to whichever subset the ticket needs, and they
 * execute in parallel.
 */
export interface PipelineStage {
  /** Node ids from the backend that satisfy this stage. */
  nodes: string[]
  label: string
  /** Parallel fan-out rather than a single sequential node. */
  parallel?: boolean
}

export const PIPELINE: PipelineStage[] = [
  { nodes: ['supervisor'], label: 'Supervisor' },
  { nodes: ['task_planner'], label: 'Task Planner' },
  {
    nodes: ['billing_agent', 'account_agent', 'technical_agent'],
    label: 'Domain Agents',
    parallel: true,
  },
  { nodes: ['policy_agent'], label: 'Policy' },
  { nodes: ['results_aggregator'], label: 'Aggregator' },
  { nodes: ['risk_engine'], label: 'Risk Engine' },
  { nodes: ['human_approval'], label: 'Human Approval' },
  { nodes: ['response_agent'], label: 'Response' },
  { nodes: ['dispatcher'], label: 'Dispatcher' },
]

/** Nodes that reason with an LLM; the rest are deterministic Python. */
export const REASONING_NODES = new Set([
  'supervisor',
  'billing_agent',
  'account_agent',
  'technical_agent',
  'policy_agent',
  'response_agent',
])
