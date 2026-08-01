/**
 * API contract types.
 *
 * These mirror the Pydantic models in `app/api/schemas.py`. When a backend
 * schema changes, change it here too - there is no code generation step.
 */

export type TicketStatus = 'open' | 'in_progress' | 'resolved' | 'closed'

export type WorkflowStatus =
  | 'pending'
  | 'running'
  | 'waiting_for_hitl'
  | 'completed'
  | 'failed'

export type TicketPriority = 'low' | 'medium' | 'high' | 'critical'

export type CustomerTier = 'basic' | 'premium' | 'enterprise'

export interface TicketSummary {
  id: string
  customer_id: string
  customer_name: string
  company_name: string
  customer_tier: CustomerTier
  title: string
  priority: TicketPriority
  status: TicketStatus
  created_at: string
  workflow_id: string | null
  workflow_status: WorkflowStatus | null
  current_node: string | null
  requires_hitl: boolean
}

export interface TicketListResponse {
  items: TicketSummary[]
  total: number
}

export interface WorkflowSummary {
  workflow_id: string
  ticket_id: string
  ticket_title: string
  customer_id: string
  customer_name: string
  workflow_status: WorkflowStatus
  current_node: string | null
  requires_hitl: boolean
  started_at: string
  completed_at: string | null
  duration_ms: number | null
}

export interface WorkflowListResponse {
  items: WorkflowSummary[]
  total: number
}

export interface TraceStep {
  sequence: number
  agent_name: string
  status: string
  execution_time_ms: number
  tool_calls: number
  confidence: number | null
  summary: string | null
  created_at: string
}

export interface WorkflowTrace {
  workflow_id: string
  workflow_status: WorkflowStatus
  current_node: string | null
  requires_hitl: boolean
  risk_score: number | null
  steps: TraceStep[]
}

export interface InvoiceSummary {
  id: string
  amount: number
  currency: string
  payment_status: 'paid' | 'pending' | 'duplicate' | 'refunded'
  created_at: string
}

export interface SubscriptionSummary {
  plan: CustomerTier
  monthly_price: number
  renewal_date: string
  subscription_status: 'active' | 'cancelled' | 'expired'
}

export interface ApprovalDetail {
  workflow_id: string
  ticket_id: string
  ticket_title: string
  issue_text: string
  customer_id: string
  customer_name: string
  company_name: string
  customer_tier: CustomerTier
  priority: TicketPriority
  workflow_status: WorkflowStatus
  risk_score: number | null
  risk_level: 'low' | 'medium' | 'high' | null
  reasons: string[]
  agent_summaries: TraceStep[]
  subscription: SubscriptionSummary | null
  invoices: InvoiceSummary[]
}

export interface Metrics {
  active_workflows: number
  pending_hitl_approvals: number
  avg_execution_time_ms: number | null
  completed_workflows: number
  failed_workflows: number
  open_tickets: number
}

export interface TicketRequest {
  customer_id: string
  /** The backend field is `subject`, not `title` (SRS §26). */
  subject: string
  description: string
}

export interface TicketAccepted {
  workflow_id: string
  status: string
  estimated_wait_time: number
}

export interface ApprovalRequest {
  approved: boolean
  reviewer_name: string
  comments: string
}

export interface ApprovalAccepted {
  workflow_id: string
  approval_status: string
  workflow_status: WorkflowStatus
}
