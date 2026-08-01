/** Small shared presentation primitives. */

import type { ReactNode } from 'react'
import { tone, type ToneName } from '../lib/status'

export function Badge({
  toneName = 'neutral',
  children,
  icon,
}: {
  toneName?: ToneName
  children: ReactNode
  icon?: ReactNode
}) {
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-xs font-medium whitespace-nowrap ${tone(toneName).chip}`}
    >
      {icon}
      {children}
    </span>
  )
}

export function Card({
  children,
  className = '',
}: {
  children: ReactNode
  className?: string
}) {
  return (
    <div
      className={`rounded-xl border border-edge bg-surface shadow-sm shadow-black/20 ${className}`}
    >
      {children}
    </div>
  )
}

export function SectionHeader({
  title,
  subtitle,
  actions,
  icon,
}: {
  title: string
  subtitle?: string
  actions?: ReactNode
  icon?: ReactNode
}) {
  return (
    <div className="flex items-start justify-between gap-4 border-b border-edge px-5 py-4">
      <div className="flex items-start gap-3">
        {icon ? <span className="mt-0.5 text-ink-muted">{icon}</span> : null}
        <div>
          <h2 className="text-sm font-semibold tracking-tight text-ink">{title}</h2>
          {subtitle ? (
            <p className="mt-0.5 text-xs text-ink-faint">{subtitle}</p>
          ) : null}
        </div>
      </div>
      {actions ? <div className="flex items-center gap-2">{actions}</div> : null}
    </div>
  )
}

export function EmptyState({
  icon,
  title,
  hint,
}: {
  icon?: ReactNode
  title: string
  hint?: string
}) {
  return (
    <div className="flex flex-col items-center justify-center gap-2 px-6 py-14 text-center">
      {icon ? <span className="text-ink-faint">{icon}</span> : null}
      <p className="text-sm font-medium text-ink-muted">{title}</p>
      {hint ? <p className="max-w-sm text-xs text-ink-faint">{hint}</p> : null}
    </div>
  )
}

export function SkeletonRows({ rows = 5, columns = 6 }: { rows?: number; columns?: number }) {
  return (
    <>
      {Array.from({ length: rows }).map((_, rowIndex) => (
        <tr key={rowIndex} className="border-t border-edge">
          {Array.from({ length: columns }).map((__, columnIndex) => (
            <td key={columnIndex} className="px-4 py-3.5">
              <div className="skeleton h-3.5 rounded" />
            </td>
          ))}
        </tr>
      ))}
    </>
  )
}

export function ErrorNote({ message }: { message: string }) {
  return (
    <div className="flex items-start gap-2 rounded-lg border border-danger/25 bg-danger-soft px-3 py-2 text-xs text-danger">
      <span className="font-medium">Error</span>
      <span className="text-danger/85">{message}</span>
    </div>
  )
}

export function Button({
  children,
  onClick,
  variant = 'secondary',
  type = 'button',
  disabled = false,
  className = '',
  icon,
}: {
  children: ReactNode
  onClick?: () => void
  variant?: 'primary' | 'secondary' | 'ghost' | 'danger' | 'success'
  type?: 'button' | 'submit'
  disabled?: boolean
  className?: string
  icon?: ReactNode
}) {
  const variants: Record<string, string> = {
    primary: 'bg-accent text-white hover:bg-accent/90 disabled:bg-accent/40',
    secondary:
      'bg-surface-raised text-ink ring-1 ring-edge-strong hover:bg-surface-hover',
    ghost: 'text-ink-muted hover:bg-surface-raised hover:text-ink',
    danger: 'bg-danger/90 text-white hover:bg-danger disabled:bg-danger/40',
    success: 'bg-ok/90 text-[#04140d] hover:bg-ok disabled:bg-ok/40',
  }
  return (
    <button
      type={type}
      onClick={onClick}
      disabled={disabled}
      className={`inline-flex items-center justify-center gap-1.5 rounded-lg px-3 py-1.5 text-xs font-medium transition-colors duration-150 disabled:cursor-not-allowed disabled:opacity-70 ${variants[variant]} ${className}`}
    >
      {icon}
      {children}
    </button>
  )
}
