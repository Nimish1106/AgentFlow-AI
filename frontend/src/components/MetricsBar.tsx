/** Status metric cards across the top of the dashboard. */

import { Activity, CheckCircle2, Clock, Inbox, ShieldAlert, XCircle } from 'lucide-react'
import type { ReactNode } from 'react'
import type { Metrics } from '../api/types'
import { formatDuration } from '../lib/format'
import { tone, type ToneName } from '../lib/status'

function MetricCard({
  label,
  value,
  icon,
  toneName = 'neutral',
  hint,
  emphasise = false,
}: {
  label: string
  value: string
  icon: ReactNode
  toneName?: ToneName
  hint?: string
  emphasise?: boolean
}) {
  return (
    <div
      className={`animate-fade-rise rounded-xl border bg-surface px-4 py-3.5 transition-colors duration-200 ${
        emphasise ? 'border-warn/40 bg-warn-soft/40' : 'border-edge hover:border-edge-strong'
      }`}
    >
      <div className="flex items-center justify-between">
        <span className="text-xs font-medium text-ink-faint">{label}</span>
        <span className={tone(toneName).text}>{icon}</span>
      </div>
      <p className="tnum mt-2 text-2xl font-semibold tracking-tight text-ink">{value}</p>
      {hint ? <p className="mt-1 text-xs text-ink-faint">{hint}</p> : null}
    </div>
  )
}

export function MetricsBar({
  metrics,
  loading,
}: {
  metrics: Metrics | null
  loading: boolean
}) {
  if (loading && !metrics) {
    return (
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-3 xl:grid-cols-6">
        {Array.from({ length: 6 }).map((_, index) => (
          <div key={index} className="skeleton h-[92px] rounded-xl" />
        ))}
      </div>
    )
  }

  const data: Metrics = metrics ?? {
    active_workflows: 0,
    pending_hitl_approvals: 0,
    avg_execution_time_ms: null,
    completed_workflows: 0,
    failed_workflows: 0,
    open_tickets: 0,
  }

  return (
    <div className="grid grid-cols-2 gap-3 lg:grid-cols-3 xl:grid-cols-6">
      <MetricCard
        label="Active workflows"
        value={String(data.active_workflows)}
        icon={<Activity size={15} />}
        toneName={data.active_workflows > 0 ? 'info' : 'neutral'}
        hint="Queued or running"
      />
      <MetricCard
        label="Pending approvals"
        value={String(data.pending_hitl_approvals)}
        icon={<ShieldAlert size={15} />}
        toneName={data.pending_hitl_approvals > 0 ? 'warn' : 'neutral'}
        hint="Blocked on a reviewer"
        emphasise={data.pending_hitl_approvals > 0}
      />
      <MetricCard
        label="Avg execution"
        value={formatDuration(data.avg_execution_time_ms)}
        icon={<Clock size={15} />}
        hint="Per completed run"
      />
      <MetricCard
        label="Open tickets"
        value={String(data.open_tickets)}
        icon={<Inbox size={15} />}
        hint="Open or in progress"
      />
      <MetricCard
        label="Completed"
        value={String(data.completed_workflows)}
        icon={<CheckCircle2 size={15} />}
        toneName="ok"
        hint="Resolved end to end"
      />
      <MetricCard
        label="Failed"
        value={String(data.failed_workflows)}
        icon={<XCircle size={15} />}
        toneName={data.failed_workflows > 0 ? 'danger' : 'neutral'}
        hint="Needs investigation"
      />
    </div>
  )
}
