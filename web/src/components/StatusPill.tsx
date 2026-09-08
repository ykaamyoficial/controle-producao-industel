import type { ProposalListItem } from '../api/proposals'
import { classifyStatus, type StatusTone } from './StatusBadge'

const PILL_CLASSES: Record<StatusTone, string> = {
  success: 'bg-emerald-500/15 text-emerald-400',
  progress: 'bg-sky-500/15 text-sky-400',
  warning: 'bg-amber-500/15 text-amber-400',
  critical: 'bg-red-500/15 text-red-400',
  neutral: 'bg-slate-500/15 text-slate-400',
}

export function proposalStatusTone(proposal: ProposalListItem): StatusTone {
  return pillTone(proposal).tone
}

function pillTone(proposal: ProposalListItem): { label: string; tone: StatusTone } {
  if (proposal.is_cancelled) {
    return { label: 'Cancelada', tone: 'critical' }
  }
  if (proposal.is_completed) {
    return { label: 'Concluida', tone: 'success' }
  }
  const label = proposal.current_status ?? 'Em andamento'
  return { label, tone: classifyStatus(label) }
}

export function StatusPill({ proposal }: { proposal: ProposalListItem }) {
  const { label, tone } = pillTone(proposal)
  return (
    <span className={`inline-flex items-center rounded-full px-2.5 py-1 text-xs font-medium ${PILL_CLASSES[tone]}`}>
      {label}
    </span>
  )
}
