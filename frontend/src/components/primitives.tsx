/**
 * Shared presentation primitives.
 *
 * Deliberately few. Each exists because the pattern appears in three or more
 * places; anything used once is written inline where it is used, so this file
 * stays a vocabulary rather than a framework.
 */

import type { ReactNode } from 'react'
import type { LucideIcon } from 'lucide-react'
import { SEMANTIC_DOT, SEMANTIC_FG, SEMANTIC_TINT, type Semantic } from '../lib/status'

/**
 * Status = dot + word. Replaces the filled pill everywhere except risk level.
 *
 * A row carrying four filled pills makes nothing look urgent; a row of quiet
 * words with one coloured dot each lets a genuine alert stand out.
 *
 * `pulse` marks a genuinely live state (a workflow mid-execution). It is the
 * only ambient animation in the product, which is what keeps it meaningful.
 */
export function Status({
  semantic,
  label,
  children,
  pulse = false,
  className = '',
}: {
  semantic: Semantic
  label?: ReactNode
  children?: ReactNode
  pulse?: boolean
  className?: string
}) {
  return (
    <span className={`inline-flex items-center gap-1.5 whitespace-nowrap ${className}`}>
      <span className="relative flex size-[5px] shrink-0" aria-hidden>
        {pulse ? (
          <span
            className={`absolute inline-flex size-full animate-ping rounded-full opacity-60 ${SEMANTIC_DOT[semantic]}`}
          />
        ) : null}
        <span
          className={`relative inline-flex size-full rounded-full ${SEMANTIC_DOT[semantic]}`}
        />
      </span>
      <span className={`text-data ${SEMANTIC_FG[semantic]}`}>{label ?? children}</span>
    </span>
  )
}

/** Column header cell. Centralised so every table shares one header treatment. */
export function Th({
  children,
  className = '',
  align = 'left',
}: {
  children?: ReactNode
  className?: string
  align?: 'left' | 'right'
}) {
  return (
    <th
      scope="col"
      className={`label-micro h-7 font-medium ${
        align === 'right' ? 'pr-4 text-right' : 'pr-4 text-left'
      } ${className}`}
    >
      {children}
    </th>
  )
}

/**
 * Tinted pill. Reserved for risk level and nothing else — its scarcity is what
 * makes it read as significant.
 */
export function Pill({
  semantic,
  children,
}: {
  semantic: Semantic
  children: ReactNode
}) {
  return (
    <span
      className={`inline-flex items-center rounded-xs px-1.5 py-px text-meta font-medium whitespace-nowrap ${SEMANTIC_TINT[semantic]}`}
    >
      {children}
    </span>
  )
}

/** Monospaced short id with the full value on hover. */
export function MonoId({ id, className = '' }: { id: string | null; className?: string }) {
  if (!id) return <span className="text-fg-faint">—</span>
  return (
    <span
      title={id}
      className={`font-mono text-meta text-fg-subtle ${className}`}
    >
      {id.slice(0, 8)}
    </span>
  )
}

export function Button({
  children,
  onClick,
  variant = 'default',
  size = 'md',
  type = 'button',
  disabled = false,
  icon,
  className = '',
}: {
  children?: ReactNode
  onClick?: () => void
  variant?: 'default' | 'primary' | 'quiet' | 'approve' | 'reject'
  size?: 'sm' | 'md'
  type?: 'button' | 'submit'
  disabled?: boolean
  icon?: ReactNode
  className?: string
}) {
  const variants: Record<string, string> = {
    default:
      'border border-line-strong bg-raised text-fg hover:bg-hover hover:border-fg-faint/50',
    // Solid accent with white text: the accent is dark enough (#2563eb) to
    // clear 4.5:1 behind white, which a lighter azure would not.
    primary:
      'border border-transparent bg-accent text-white hover:bg-accent-hover',
    quiet: 'border border-transparent text-fg-muted hover:bg-hover hover:text-fg',
    // Decision buttons: tinted wash, text-safe ink, hover deepens the wash.
    approve: 'border border-ok/30 bg-ok-dim text-ok hover:bg-ok/12',
    reject: 'border border-failed/30 bg-failed-dim text-failed hover:bg-failed/12',
  }
  const sizes: Record<string, string> = {
    sm: 'h-6 gap-1 px-2 text-meta',
    md: 'h-7 gap-1.5 px-2.5 text-data',
  }
  return (
    <button
      type={type}
      onClick={onClick}
      disabled={disabled}
      className={`inline-flex shrink-0 items-center justify-center rounded-sm font-medium transition-colors duration-100 disabled:cursor-not-allowed disabled:opacity-45 ${variants[variant]} ${sizes[size]} ${className}`}
    >
      {icon}
      {children}
    </button>
  )
}

/**
 * Shared form-field surface.
 *
 * White on white with a strong border, rather than a filled gray well. In light
 * mode a gray-filled input reads as *disabled*; the border is what says
 * "editable". Focus deepens the border and adds a soft ring instead of an
 * outline, so the field does not jump by a pixel when focused.
 */
export const FIELD =
  'w-full rounded-sm border border-line-strong bg-raised text-fg ' +
  'placeholder:text-fg-faint transition-colors duration-100 ' +
  'focus:border-accent focus:ring-2 focus:ring-accent/15 focus:outline-none ' +
  'disabled:bg-sunken disabled:text-fg-faint disabled:cursor-not-allowed'

/** Panel: a bordered region. No shadow — elevation is borders (see index.css). */
export function Panel({
  children,
  className = '',
}: {
  children: ReactNode
  className?: string
}) {
  return (
    <div className={`rounded-md border border-line bg-raised ${className}`}>
      {children}
    </div>
  )
}

/** Section head inside a panel. Fixed 36px so stacked panels align. */
export function PanelHead({
  title,
  meta,
  actions,
}: {
  title: string
  meta?: ReactNode
  actions?: ReactNode
}) {
  return (
    <div className="flex h-9 items-center justify-between gap-3 border-b border-line px-3">
      <div className="flex min-w-0 items-baseline gap-2">
        <h2 className="label-micro text-fg-muted">{title}</h2>
        {meta ? <span className="truncate text-meta text-fg-faint">{meta}</span> : null}
      </div>
      {actions ? <div className="flex shrink-0 items-center gap-1">{actions}</div> : null}
    </div>
  )
}

/** Label + value row, used throughout the detail panels. */
export function Field({
  label,
  children,
  align = 'row',
}: {
  label: string
  children: ReactNode
  align?: 'row' | 'stack'
}) {
  if (align === 'stack') {
    return (
      <div>
        <div className="label-micro">{label}</div>
        <div className="mt-1 text-data text-fg">{children}</div>
      </div>
    )
  }
  return (
    <div className="flex items-baseline justify-between gap-3 py-1">
      <span className="shrink-0 text-data text-fg-subtle">{label}</span>
      <span className="min-w-0 truncate text-right text-data text-fg">{children}</span>
    </div>
  )
}

export function Empty({
  icon: Icon,
  title,
  hint,
  action,
}: {
  icon?: LucideIcon
  title: string
  hint?: string
  action?: ReactNode
}) {
  return (
    <div className="flex flex-col items-center justify-center gap-1.5 px-6 py-16 text-center">
      {Icon ? <Icon size={18} className="mb-1 text-fg-faint" strokeWidth={1.75} /> : null}
      <p className="text-data font-medium text-fg-muted">{title}</p>
      {hint ? <p className="max-w-xs text-meta text-fg-faint">{hint}</p> : null}
      {action ? <div className="mt-2">{action}</div> : null}
    </div>
  )
}

/** Inline failure note. Used above content that is stale rather than absent. */
export function ErrorNote({ message }: { message: string }) {
  return (
    <div className="mb-3 flex items-start gap-2 rounded-sm border border-failed/30 bg-failed-dim px-2.5 py-1.5">
      <span className="shrink-0 text-meta font-medium text-failed">Error</span>
      <span className="min-w-0 text-meta text-failed/85">{message}</span>
    </div>
  )
}

/** Backwards-compatible alias: some views import the banner form. */
export const ErrorBanner = ErrorNote

/** Table skeleton matching real row height, so loading does not shift layout. */
export function SkeletonRows({ rows = 8, cols = 6 }: { rows?: number; cols?: number }) {
  return (
    <>
      {Array.from({ length: rows }).map((_, r) => (
        <tr key={r} className="border-b border-line">
          {Array.from({ length: cols }).map((__, c) => (
            <td key={c} className="h-row px-3">
              <div
                className="skeleton h-2 rounded-xs"
                style={{ width: c === 0 ? '70%' : c === cols - 1 ? '40%' : '55%' }}
              />
            </td>
          ))}
        </tr>
      ))}
    </>
  )
}

/**
 * Segmented filter control. Used for the status filters on both list views.
 */
export function Segmented<T extends string>({
  options,
  value,
  onChange,
  ariaLabel = 'Filter',
}: {
  options: Array<{ value: T; label: string; count?: number }>
  value: T
  onChange: (value: T) => void
  ariaLabel?: string
}) {
  return (
    <div
      role="group"
      aria-label={ariaLabel}
      className="flex items-center gap-px rounded-sm border border-line bg-sunken p-px"
    >
      {options.map((option) => {
        const selected = option.value === value
        return (
          <button
            key={option.value}
            type="button"
            aria-pressed={selected}
            onClick={() => onChange(option.value)}
            // Light-mode segmented controls invert the dark convention: the
            // selected segment is white and lifts *out* of the inset gray
            // track, rather than being a brighter fill on a dark one.
            className={`inline-flex h-5.5 items-center gap-1.5 rounded-xs px-2 text-meta font-medium transition-colors duration-100 ${
              selected
                ? 'bg-raised text-fg ring-1 ring-line-strong/70'
                : 'text-fg-subtle hover:bg-line hover:text-fg-muted'
            }`}
          >
            {option.label}
            {option.count !== undefined && option.count > 0 ? (
              <span className={selected ? 'text-fg-muted' : 'text-fg-faint'}>
                {option.count}
              </span>
            ) : null}
          </button>
        )
      })}
    </div>
  )
}

/** Alias: views import the control under its fuller name. */
export const SegmentedControl = Segmented
