import clsx from 'clsx'
import { AlertTriangle, Check, Info, Loader2, ShieldCheck, ShieldX, X } from 'lucide-react'
import type { ReactNode } from 'react'

export function Panel({
  title,
  subtitle,
  actions,
  children,
  className,
  bodyClassName,
}: {
  title?: ReactNode
  subtitle?: ReactNode
  actions?: ReactNode
  children: ReactNode
  className?: string
  bodyClassName?: string
}) {
  return (
    <section className={clsx('panel flex flex-col min-h-0', className)}>
      {(title || actions) && (
        <header className="panel-hd shrink-0">
          <div className="min-w-0">
            {title && <h2 className="text-sm font-semibold text-mute-200 truncate">{title}</h2>}
            {subtitle && <p className="text-2xs text-mute-400 mt-0.5 truncate">{subtitle}</p>}
          </div>
          {actions && <div className="flex items-center gap-2 shrink-0">{actions}</div>}
        </header>
      )}
      <div className={clsx('min-h-0 flex-1', bodyClassName ?? 'p-4')}>{children}</div>
    </section>
  )
}

export function StatTile({
  label,
  value,
  unit,
  hint,
  tone = 'neutral',
}: {
  label: string
  value: ReactNode
  unit?: string
  hint?: string
  tone?: 'neutral' | 'legal' | 'breach' | 'caution' | 'signal'
}) {
  const toneClass = {
    neutral: 'text-mute-200',
    legal: 'text-legal',
    breach: 'text-breach',
    caution: 'text-caution',
    signal: 'text-signal',
  }[tone]
  return (
    <div className="panel px-3 py-2.5">
      <div className="label">{label}</div>
      <div className={clsx('num text-xl font-semibold mt-1 leading-none', toneClass)}>
        {value}
        {unit && <span className="text-xs font-normal text-mute-400 ml-1">{unit}</span>}
      </div>
      {hint && <div className="text-2xs text-mute-400 mt-1.5 leading-snug">{hint}</div>}
    </div>
  )
}

export function LegalityBadge({ legal, size = 'sm' }: { legal: boolean; size?: 'sm' | 'md' }) {
  const Icon = legal ? ShieldCheck : ShieldX
  return (
    <span className={legal ? 'chip-legal' : 'chip-breach'}>
      <Icon size={size === 'md' ? 14 : 11} aria-hidden />
      {legal ? 'Legal' : 'Illegal'}
    </span>
  )
}

export function VerificationBadge({
  verification,
}: {
  verification: { passed: boolean; summary: string; violations: unknown[]; downgraded: boolean } | null
}) {
  if (!verification) return null
  const { passed, summary, downgraded } = verification
  return (
    <span
      className={passed ? 'chip-legal' : 'chip-caution'}
      title={
        passed
          ? 'Every number, id and rule in the answer was found in this run’s fact ledger.'
          : 'The narration referenced values the tools did not produce; the answer was replaced with the engine’s own figures.'
      }
    >
      {passed ? <ShieldCheck size={11} aria-hidden /> : <AlertTriangle size={11} aria-hidden />}
      {passed ? `Verified · ${summary}` : downgraded ? 'Unverified — showing engine output' : summary}
    </span>
  )
}

export function RuleChip({
  ruleId,
  onClick,
  tone = 'neutral',
}: {
  ruleId: string
  onClick?: () => void
  tone?: 'neutral' | 'breach' | 'legal' | 'advisory'
}) {
  const cls = {
    neutral: 'chip-neutral',
    breach: 'chip-breach',
    legal: 'chip-legal',
    advisory: 'chip-advisory',
  }[tone]
  const Tag = onClick ? 'button' : 'span'
  return (
    <Tag className={clsx(cls, onClick && 'hover:brightness-125 cursor-pointer')} onClick={onClick}>
      {ruleId}
    </Tag>
  )
}

export function Spinner({ label }: { label?: string }) {
  return (
    <div className="flex items-center gap-2 text-2xs text-mute-400">
      <Loader2 size={13} className="animate-spin" aria-hidden />
      {label ?? 'Working…'}
    </div>
  )
}

export function EmptyState({
  icon: Icon = Info,
  title,
  body,
  action,
}: {
  icon?: typeof Info
  title: string
  body?: string
  action?: ReactNode
}) {
  return (
    <div className="flex flex-col items-center justify-center text-center py-10 px-6 gap-2">
      <Icon size={22} className="text-mute-400/60" aria-hidden />
      <p className="text-sm font-medium text-mute-300">{title}</p>
      {body && <p className="text-xs text-mute-400 max-w-sm leading-relaxed">{body}</p>}
      {action}
    </div>
  )
}

export function ErrorBox({ error }: { error: unknown }) {
  const message = error instanceof Error ? error.message : String(error)
  return (
    <div className="panel border-breach/30 bg-breach/5 p-3 flex items-start gap-2">
      <X size={14} className="text-breach mt-0.5 shrink-0" aria-hidden />
      <div className="text-xs text-mute-300">
        <p className="font-medium text-breach">Request failed</p>
        <p className="mt-0.5 text-mute-400">{message}</p>
      </div>
    </div>
  )
}

export function Skeleton({ rows = 3 }: { rows?: number }) {
  return (
    <div className="space-y-2" aria-busy>
      {Array.from({ length: rows }).map((_, i) => (
        <div key={i} className="skeleton h-6" style={{ opacity: 1 - i * 0.12 }} />
      ))}
    </div>
  )
}

export function Toggle({
  options,
  value,
  onChange,
}: {
  options: { value: string; label: string; title?: string }[]
  value: string
  onChange: (v: string) => void
}) {
  return (
    <div className="inline-flex rounded-lg border border-ink-600 bg-ink-850 p-0.5" role="tablist">
      {options.map((o) => (
        <button
          key={o.value}
          role="tab"
          aria-selected={value === o.value}
          title={o.title}
          onClick={() => onChange(o.value)}
          className={clsx(
            'px-2.5 py-1 rounded-md text-2xs font-semibold transition-colors',
            value === o.value ? 'bg-signal/15 text-signal' : 'text-mute-400 hover:text-mute-300',
          )}
        >
          {o.label}
        </button>
      ))}
    </div>
  )
}

/** A legend. Present whenever two or more series share a chart. */
export function Legend({
  items,
  className,
}: {
  items: { color: string; label: string; note?: string }[]
  className?: string
}) {
  return (
    <ul className={clsx('flex flex-wrap items-center gap-x-4 gap-y-1', className)}>
      {items.map((item) => (
        <li key={item.label} className="flex items-center gap-1.5 text-2xs text-mute-400">
          <span
            className="w-2.5 h-2.5 rounded-sm shrink-0"
            style={{ background: item.color }}
            aria-hidden
          />
          <span className="text-mute-300">{item.label}</span>
          {item.note && <span className="text-mute-400/70">{item.note}</span>}
        </li>
      ))}
    </ul>
  )
}

export function Pass({ ok }: { ok: boolean }) {
  return ok ? (
    <Check size={13} className="text-legal" aria-label="pass" />
  ) : (
    <X size={13} className="text-breach" aria-label="fail" />
  )
}

/**
 * Hover tooltip.
 *
 * The wrapper is the positioned element, so `className`/`style` are forwarded
 * onto it: an absolutely-placed mark (a Gantt bar, a scatter dot) must position
 * the *wrapper*, not the child, or it collapses inside this span.
 *
 * When `className` is supplied it must include its own positioning utility.
 * The default `relative` is only applied without one — Tailwind emits
 * `.relative` after `.absolute`, so keeping both would silently win and undo
 * the caller's placement.
 */
export function Tip({
  text,
  children,
  className,
  style,
}: {
  text: string
  children: ReactNode
  /** Must include a positioning utility (e.g. `absolute inset-y-0`). */
  className?: string
  style?: React.CSSProperties
}) {
  return (
    <span className={clsx('group inline-flex', className ?? 'relative')} style={style}>
      {children}
      <span
        role="tooltip"
        className="pointer-events-none absolute left-1/2 -translate-x-1/2 bottom-full mb-1.5 z-50
                   hidden group-hover:block w-max max-w-xs px-2 py-1 rounded-md
                   bg-ink-700 border border-ink-600 text-2xs text-mute-200 shadow-xl leading-snug"
      >
        {text}
      </span>
    </span>
  )
}
