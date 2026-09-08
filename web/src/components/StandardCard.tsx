import type { ReactNode } from 'react'
import { Link } from 'react-router-dom'
import type { StatusTone } from './StatusBadge'

const ACCENT_CLASSES: Record<StatusTone, string> = {
  success: 'border-l-emerald-500',
  progress: 'border-l-sky-500',
  warning: 'border-l-amber-500',
  critical: 'border-l-red-500',
  neutral: 'border-l-slate-600',
}

interface StandardCardProps {
  /** Nome do cliente — mesmo destaque visual do numero da proposta. */
  primaryLeft: string
  /** Numero da proposta/carga — mesmo destaque visual do cliente. */
  primaryRight: string
  status: ReactNode
  itemsLabel: ReactNode
  href?: string
  /** Pinta uma faixa colorida na borda esquerda do card, conforme o status. */
  accentTone?: StatusTone
}

function HeaderRow({ primaryLeft, primaryRight, status }: Pick<StandardCardProps, 'primaryLeft' | 'primaryRight' | 'status'>) {
  return (
    <div className="flex items-start justify-between gap-2">
      <div className="flex min-w-0 flex-col">
        <span className="truncate text-sm font-semibold text-slate-100">{primaryLeft}</span>
        <span className="truncate text-sm font-semibold text-slate-100">{primaryRight}</span>
      </div>
      <div className="shrink-0">{status}</div>
    </div>
  )
}

export function StandardCard({ primaryLeft, primaryRight, status, itemsLabel, href, accentTone }: StandardCardProps) {
  const accentClass = accentTone ? ACCENT_CLASSES[accentTone] : 'border-l-transparent'
  const baseClass = `rounded-xl border border-l-4 border-slate-800 ${accentClass} bg-slate-900 px-4 py-3`

  const content = (
    <>
      <HeaderRow primaryLeft={primaryLeft} primaryRight={primaryRight} status={status} />
      <p className="mt-2 truncate text-xs text-slate-500">{itemsLabel}</p>
    </>
  )

  if (href) {
    return (
      <Link to={href} className={`block ${baseClass} active:bg-slate-800`}>
        {content}
      </Link>
    )
  }

  return <div className={baseClass}>{content}</div>
}
