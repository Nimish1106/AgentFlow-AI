/**
 * Thin fetch client for the AgentFlow REST API.
 *
 * Responsibilities kept deliberately narrow: build the URL, send JSON, turn a
 * non-2xx into a typed error, parse the body. No caching and no retry - the
 * dashboard polls, so a failed poll is superseded by the next one a few
 * seconds later.
 */

import type {
  ApprovalAccepted,
  ApprovalDetail,
  ApprovalRequest,
  Metrics,
  TicketAccepted,
  TicketListResponse,
  TicketRequest,
  TicketStatus,
  WorkflowListResponse,
  WorkflowStatus,
  WorkflowTrace,
} from './types'

/**
 * Empty by default: the Vite dev server and the production nginx both proxy
 * the API paths, so the browser sees one origin. Set VITE_API_BASE_URL to an
 * absolute URL when the API is somewhere neither proxy can reach.
 */
const BASE_URL: string = (import.meta.env.VITE_API_BASE_URL ?? '').replace(/\/$/, '')

/** An API call that came back non-2xx. */
export class ApiError extends Error {
  readonly status: number
  readonly detail: string

  constructor(status: number, detail: string) {
    super(detail)
    this.name = 'ApiError'
    this.status = status
    this.detail = detail
  }
}

type Query = Record<string, string | number | boolean | undefined | null>

function buildUrl(path: string, query?: Query): string {
  const url = `${BASE_URL}${path}`
  if (!query) return url
  const params = new URLSearchParams()
  for (const [key, value] of Object.entries(query)) {
    if (value !== undefined && value !== null && value !== '') {
      params.append(key, String(value))
    }
  }
  const qs = params.toString()
  return qs ? `${url}?${qs}` : url
}

/**
 * Pull a human-readable message out of an error response.
 *
 * FastAPI returns `{detail: string}` for HTTPException and
 * `{detail: [{loc, msg, ...}]}` for a 422 validation failure.
 */
async function readError(response: Response): Promise<string> {
  try {
    const body = (await response.json()) as { detail?: unknown }
    const detail = body.detail
    if (typeof detail === 'string') return detail
    if (Array.isArray(detail)) {
      const messages = detail
        .map((item) => {
          if (typeof item === 'object' && item !== null && 'msg' in item) {
            const entry = item as { msg?: unknown; loc?: unknown }
            const field = Array.isArray(entry.loc) ? entry.loc.at(-1) : undefined
            return field ? `${String(field)}: ${String(entry.msg)}` : String(entry.msg)
          }
          return String(item)
        })
        .filter(Boolean)
      if (messages.length) return messages.join('; ')
    }
  } catch {
    // Body was not JSON; fall through to the status text.
  }
  return response.statusText || `Request failed with status ${response.status}`
}

async function request<T>(
  path: string,
  options: { method?: string; query?: Query; body?: unknown; signal?: AbortSignal } = {},
): Promise<T> {
  const { method = 'GET', query, body, signal } = options

  const response = await fetch(buildUrl(path, query), {
    method,
    signal,
    headers: body === undefined ? undefined : { 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  })

  if (!response.ok) {
    throw new ApiError(response.status, await readError(response))
  }
  if (response.status === 204) {
    return undefined as T
  }
  return (await response.json()) as T
}

export interface ListParams {
  limit?: number
  offset?: number
  signal?: AbortSignal
}

export const api = {
  listTickets({
    status,
    limit,
    offset,
    signal,
  }: ListParams & { status?: TicketStatus | 'all' } = {}) {
    return request<TicketListResponse>('/tickets', {
      query: { status: status === 'all' ? undefined : status, limit, offset },
      signal,
    })
  },

  listWorkflows({
    status,
    limit,
    offset,
    signal,
  }: ListParams & { status?: WorkflowStatus | 'all' } = {}) {
    return request<WorkflowListResponse>('/workflows', {
      query: { status: status === 'all' ? undefined : status, limit, offset },
      signal,
    })
  },

  getWorkflowTrace(workflowId: string, signal?: AbortSignal) {
    return request<WorkflowTrace>(`/workflows/${workflowId}/trace`, { signal })
  },

  getApprovalDetail(workflowId: string, signal?: AbortSignal) {
    return request<ApprovalDetail>(`/workflows/${workflowId}/approval`, { signal })
  },

  getMetrics(signal?: AbortSignal) {
    return request<Metrics>('/metrics', { signal })
  },

  createTicket(payload: TicketRequest) {
    return request<TicketAccepted>('/tickets', { method: 'POST', body: payload })
  },

  submitApproval(workflowId: string, payload: ApprovalRequest) {
    return request<ApprovalAccepted>(`/approvals/${workflowId}`, {
      method: 'POST',
      body: payload,
    })
  },
}
