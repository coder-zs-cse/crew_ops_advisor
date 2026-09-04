import { X } from 'lucide-react'
import { useEffect } from 'react'
import { createPortal } from 'react-dom'

/**
 * A plain overlay modal — no external dependency, just a portal to <body>
 * so it escapes any `overflow-x: auto` ancestor (the workbench forms sit
 * inside several of those).
 */
export function Modal({
  title,
  subtitle,
  onClose,
  children,
  width = 720,
}: {
  title: React.ReactNode
  subtitle?: React.ReactNode
  onClose: () => void
  children: React.ReactNode
  width?: number
}) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKey)
    document.body.style.overflow = 'hidden'
    return () => {
      window.removeEventListener('keydown', onKey)
      document.body.style.overflow = ''
    }
  }, [onClose])

  return createPortal(
    <div
      className="fixed inset-0 z-[100] flex items-start justify-center overflow-y-auto bg-ink-950/70 backdrop-blur-sm p-4 sm:p-8 animate-fade-in"
      onClick={onClose}
      role="presentation"
    >
      <div
        className="panel w-full shadow-2xl my-auto animate-slide-up"
        style={{ maxWidth: width }}
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-modal="true"
        aria-label={typeof title === 'string' ? title : undefined}
      >
        <header className="panel-hd sticky top-0 bg-ink-900 z-10 rounded-t-xl">
          <div className="min-w-0">
            <h2 className="text-sm font-semibold text-mute-200 truncate">{title}</h2>
            {subtitle && <p className="text-2xs text-mute-400 mt-0.5 truncate">{subtitle}</p>}
          </div>
          <button
            onClick={onClose}
            className="p-1.5 rounded-lg text-mute-400 hover:text-mute-200 hover:bg-ink-800 shrink-0"
            aria-label="Close"
          >
            <X size={15} />
          </button>
        </header>
        <div className="p-4 max-h-[75vh] overflow-y-auto">{children}</div>
      </div>
    </div>,
    document.body,
  )
}
