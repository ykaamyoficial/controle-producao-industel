import { useQuery } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { listProposalAttachments, fetchAttachmentBlob, type ProposalAttachment } from '../api/attachments'
import type { ProposalActivityItem } from '../api/proposalDetail'
import { BottomSheet } from './BottomSheet'

/**
 * Eventos gerados automaticamente por item dentro de uma acao em lote
 * (ex: registrar producao de 6 itens de uma vez). Nunca viram o card
 * representante do grupo — ficam disponiveis so dentro do detalhe.
 */
const NOISE_EVENT_TYPES = new Set([
  'PRODUCTION_ITEM_FLOW_UPDATED',
  'PRODUCTION_ITEM_WEIGHT_UPDATED',
  'PRODUCTION_ITEM_COMPLETED',
  'REALLOCATED_PRODUCTION_COMPLETED',
  'GALVANIZATION_ITEM_SENT',
  'GALVANIZATION_ITEM_RETURNED',
  'EXPEDITION_ITEM_SEPARATED',
  'EXPEDITION_ITEM_DELIVERED',
  'EXPEDITION_ITEM_REMANAGED',
  'EXPEDITION_ITEM_REMANAGED_TO_EARLY_DELIVERY',
  'PROPOSAL_PARTIAL_CHILD_CREATED',
  'PROPOSAL_PARTIAL_CHILD_MERGED',
  'PROPOSAL_PARTIAL_CHILD_GROUPED',
  'PARENT_PROPOSAL_REBORN',
  'PARENT_PROPOSAL_OPERATIONAL_DEATH',
  'GALVANIZATION_PROPOSAL_RETURN_RECALCULATED',
])

interface TimelineGroup {
  key: string
  representative: ProposalActivityItem
  events: ProposalActivityItem[]
}

/** Agrupa eventos da mesma acao humana (mesmo correlation_id = mesma requisicao). */
function groupActivities(activities: ProposalActivityItem[]): TimelineGroup[] {
  const groups = new Map<string, ProposalActivityItem[]>()
  for (const activity of activities) {
    const key = activity.correlation_id ?? `single-${activity.id}`
    const list = groups.get(key)
    if (list) list.push(activity)
    else groups.set(key, [activity])
  }

  return Array.from(groups.entries()).map(([key, events]) => {
    const primary = events.filter((event) => !NOISE_EVENT_TYPES.has(event.event_type))
    const representative = (primary[0] ?? events[0])!
    return { key, representative, events }
  })
}

function formatRelative(value: string): string {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return '-'
  const diffMs = Date.now() - date.getTime()
  const diffMin = Math.round(diffMs / 60000)
  if (diffMin < 1) return 'agora'
  if (diffMin < 60) return `ha ${diffMin} min`
  const diffHours = Math.round(diffMin / 60)
  if (diffHours < 24) return `ha ${diffHours}h`
  const diffDays = Math.round(diffHours / 24)
  if (diffDays === 1) return 'ha 1 dia'
  if (diffDays < 30) return `ha ${diffDays} dias`
  return date.toLocaleDateString('pt-BR')
}

function formatDateTime(value: string): string {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return '-'
  return date.toLocaleString('pt-BR', { day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit' })
}

function AttachmentPreview({ attachment }: { attachment: ProposalAttachment }) {
  const [url, setUrl] = useState<string | null>(null)

  useEffect(() => {
    let objectUrl: string | null = null
    let cancelled = false
    fetchAttachmentBlob(attachment.id).then((blob) => {
      if (cancelled) return
      objectUrl = URL.createObjectURL(blob)
      setUrl(objectUrl)
    })
    return () => {
      cancelled = true
      if (objectUrl) URL.revokeObjectURL(objectUrl)
    }
  }, [attachment.id])

  if (!url) return <div className="h-40 w-full animate-pulse rounded-lg bg-slate-800" />

  if (attachment.mime_type.startsWith('video/')) {
    return <video src={url} controls className="w-full rounded-lg" />
  }

  return (
    <a href={url} target="_blank" rel="noreferrer">
      <img src={url} alt={attachment.note ?? attachment.original_filename} className="w-full rounded-lg object-cover" />
    </a>
  )
}

function TimelineDetailSheet({
  group,
  attachment,
  onClose,
}: {
  group: TimelineGroup | null
  attachment: ProposalAttachment | undefined
  onClose: () => void
}) {
  const extraEvents = group ? group.events.filter((event) => event.id !== group.representative.id) : []

  return (
    <BottomSheet open={!!group} title="Detalhe do registro" onClose={onClose}>
      {group && (
        <div className="flex flex-col gap-3 py-1">
          <p className="text-sm text-slate-100">{group.representative.headline}</p>

          <dl className="grid grid-cols-2 gap-x-4 gap-y-2 rounded-lg border border-slate-800 bg-slate-900 px-3 py-3 text-sm">
            <dt className="text-slate-500">Quando</dt>
            <dd className="text-right text-slate-200">{formatDateTime(group.representative.occurred_at)}</dd>
            <dt className="text-slate-500">Quem</dt>
            <dd className="text-right text-slate-200">{group.representative.actor_name ?? '-'}</dd>
            <dt className="text-slate-500">Area</dt>
            <dd className="text-right text-slate-200">{group.representative.area ?? '-'}</dd>
          </dl>

          {attachment && (
            <div>
              <p className="mb-1 text-xs uppercase tracking-wide text-slate-500">Foto anexada</p>
              <AttachmentPreview attachment={attachment} />
              {attachment.note && <p className="mt-1 text-xs text-slate-400">{attachment.note}</p>}
            </div>
          )}

          {extraEvents.length > 0 && (
            <div>
              <p className="mb-1 text-xs uppercase tracking-wide text-slate-500">
                Itens afetados ({extraEvents.length})
              </p>
              <div className="flex flex-col gap-1 rounded-lg border border-slate-800 bg-slate-900 px-3 py-2">
                {extraEvents.map((event) => (
                  <p key={event.id} className="text-xs text-slate-400">
                    {event.headline}
                  </p>
                ))}
              </div>
            </div>
          )}
        </div>
      )}
    </BottomSheet>
  )
}

export function ProposalTimeline({ proposalId, activities }: { proposalId: number; activities: ProposalActivityItem[] }) {
  const [selected, setSelected] = useState<TimelineGroup | null>(null)

  const attachmentsQuery = useQuery({
    queryKey: ['proposal-attachments', proposalId],
    queryFn: () => listProposalAttachments(proposalId),
  })

  const attachmentByRequestId = new Map(
    (attachmentsQuery.data?.items ?? []).filter((item) => item.request_id).map((item) => [item.request_id, item]),
  )

  // Mais antigo primeiro (a API retorna mais recente primeiro).
  const groups = groupActivities(activities).reverse()

  if (groups.length === 0) {
    return <p className="text-sm text-slate-500">Sem eventos registrados.</p>
  }

  return (
    <>
      <div className="flex flex-col">
        {groups.map((group, index) => {
          const attachment = group.representative.correlation_id
            ? attachmentByRequestId.get(group.representative.correlation_id)
            : undefined
          const isLast = index === groups.length - 1

          return (
            <div key={group.key} className="flex gap-3">
              <div className="flex flex-col items-center">
                <div className="mt-4 h-2.5 w-2.5 shrink-0 rounded-full bg-sky-500" />
                {!isLast && <div className="w-px flex-1 bg-slate-800" />}
              </div>
              <button
                type="button"
                onClick={() => setSelected(group)}
                className="mb-3 flex-1 rounded-xl border border-slate-800 bg-slate-900 px-4 py-3 text-left active:bg-slate-800"
              >
                <p className="text-sm text-slate-100">{group.representative.headline}</p>
                <p className="mt-1 text-xs text-slate-500">
                  {formatRelative(group.representative.occurred_at)}
                  {group.representative.actor_name && ` · ${group.representative.actor_name}`}
                  {attachment && ' · 📷'}
                </p>
              </button>
            </div>
          )
        })}
      </div>

      <TimelineDetailSheet
        group={selected}
        attachment={
          selected?.representative.correlation_id
            ? attachmentByRequestId.get(selected.representative.correlation_id)
            : undefined
        }
        onClose={() => setSelected(null)}
      />
    </>
  )
}
