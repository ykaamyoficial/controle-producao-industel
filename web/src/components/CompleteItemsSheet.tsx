import { useMutation, useQueries, useQueryClient } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { uploadProposalAttachment } from '../api/attachments'
import { newRequestId } from '../api/client'
import { completeProductionItems, getProductionProposal, type ProductionItemSummary } from '../api/production'
import { BottomSheet } from './BottomSheet'
import { MediaPicker } from './MediaPicker'

interface AggregatedItem extends ProductionItemSummary {
  proposalId: number
  proposalNumber: string
  proposalVersion: number
}

function eligibleItems(items: ProductionItemSummary[]): ProductionItemSummary[] {
  return items.filter((item) => item.active && item.produce_internally === 'SIM' && !item.produced)
}

export function CompleteItemsSheet({
  proposalIds,
  onClose,
}: {
  proposalIds: number[]
  onClose: () => void
}) {
  const queryClient = useQueryClient()
  const [selectedIds, setSelectedIds] = useState<Set<number> | null>(null)
  const [observation, setObservation] = useState('')
  const [photo, setPhoto] = useState<File | null>(null)

  const detailQueries = useQueries({
    queries: proposalIds.map((id) => ({
      queryKey: ['production-proposal-detail', id],
      queryFn: () => getProductionProposal(id),
      enabled: proposalIds.length > 0,
    })),
  })

  const isLoading = detailQueries.some((query) => query.isLoading)
  const settledCount = detailQueries.filter((query) => !query.isLoading).length
  const failedCount = detailQueries.filter((query) => query.isError).length
  const details = detailQueries.map((query) => query.data).filter((data): data is NonNullable<typeof data> => !!data)

  const items: AggregatedItem[] = details.flatMap((detail) =>
    eligibleItems(detail.items).map((item) => ({
      ...item,
      proposalId: detail.id,
      proposalNumber: detail.proposal_number,
      proposalVersion: detail.version,
    })),
  )
  const undefinedFlowCount = details.reduce(
    (total, detail) => total + detail.items.filter((item) => item.active && !item.produced && !item.flow_defined).length,
    0,
  )

  useEffect(() => {
    if (settledCount === proposalIds.length && proposalIds.length > 0) {
      setSelectedIds(new Set(items.map((item) => item.id)))
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [settledCount, proposalIds.length])

  const mutation = useMutation({
    mutationFn: async () => {
      if (!selectedIds || selectedIds.size === 0) return
      const requestId = newRequestId()
      const selectedByProposal = new Map<number, AggregatedItem[]>()
      for (const item of items) {
        if (!selectedIds.has(item.id)) continue
        const list = selectedByProposal.get(item.proposalId) ?? []
        list.push(item)
        selectedByProposal.set(item.proposalId, list)
      }
      for (const [proposalId, selectedForProposal] of selectedByProposal) {
        const totalForProposal = items.filter((item) => item.proposalId === proposalId).length
        const allSelectedForProposal = selectedForProposal.length === totalForProposal
        await completeProductionItems(
          proposalId,
          selectedForProposal[0].proposalVersion,
          allSelectedForProposal ? null : selectedForProposal.map((item) => item.id),
          observation || undefined,
          requestId,
        )
        if (photo) {
          await uploadProposalAttachment(proposalId, photo, {
            area: 'PRODUCAO',
            actionId: 'COMPLETE_ITEMS',
            note: observation || undefined,
            requestId,
          })
        }
      }
    },
    onSuccess: () => {
      setObservation('')
      setPhoto(null)
      queryClient.invalidateQueries({ queryKey: ['production-proposals'] })
      for (const id of proposalIds) {
        queryClient.invalidateQueries({ queryKey: ['production-proposal-detail', id] })
      }
      onClose()
    },
  })

  function toggleItem(itemId: number) {
    setSelectedIds((prev) => {
      const next = new Set(prev ?? [])
      if (next.has(itemId)) next.delete(itemId)
      else next.add(itemId)
      return next
    })
  }

  function toggleAll() {
    setSelectedIds((prev) => (prev && prev.size === items.length ? new Set() : new Set(items.map((item) => item.id))))
  }

  function handleClose() {
    setObservation('')
    setPhoto(null)
    onClose()
  }

  const selectedCount = selectedIds?.size ?? 0
  const allChecked = items.length > 0 && selectedCount === items.length
  const title =
    proposalIds.length === 1 && details[0]
      ? `Registrar producao — ${details[0].proposal_number}`
      : `Registrar producao — ${proposalIds.length} propostas`

  return (
    <BottomSheet open={proposalIds.length > 0} title={title} onClose={handleClose}>
      {isLoading && <p className="py-3 text-sm text-slate-500">Carregando itens...</p>}
      {failedCount > 0 && (
        <p className="py-3 text-sm text-red-400">
          {failedCount} de {proposalIds.length} proposta{proposalIds.length > 1 ? 's' : ''} nao pode{failedCount > 1 ? 'ram' : ''} ser
          carregada{failedCount > 1 ? 's' : ''}. As demais continuam disponiveis abaixo.
        </p>
      )}

      {settledCount === proposalIds.length && proposalIds.length > 0 && (
        <>
          {undefinedFlowCount > 0 && (
            <p className="rounded-lg border border-amber-900 bg-amber-950/30 px-3 py-2 text-xs text-amber-400">
              {undefinedFlowCount} item(ns) sem fluxo definido nao aparecem aqui — defina o fluxo primeiro.
            </p>
          )}

          {items.length === 0 ? (
            <p className="py-3 text-sm text-slate-500">Nenhum item pendente de producao.</p>
          ) : (
            <div className="mt-2 flex flex-col gap-2">
              <label className="flex items-center gap-2 rounded-lg border border-slate-800 px-3 py-2.5">
                <input type="checkbox" checked={allChecked} onChange={toggleAll} className="h-4 w-4" />
                <span className="text-sm font-medium text-slate-200">
                  Selecionar todos ({items.length} pendente{items.length > 1 ? 's' : ''})
                </span>
              </label>

              {items.map((item) => (
                <label key={item.id} className="flex items-center gap-2 rounded-lg border border-slate-800 px-3 py-2.5">
                  <input
                    type="checkbox"
                    checked={selectedIds?.has(item.id) ?? false}
                    onChange={() => toggleItem(item.id)}
                    className="h-4 w-4"
                  />
                  <div className="min-w-0 flex-1">
                    {proposalIds.length > 1 && (
                      <p className="text-xs font-medium uppercase tracking-wide text-sky-400">{item.proposalNumber}</p>
                    )}
                    <p className="truncate text-sm text-slate-100">
                      {item.item_number} — {item.description ?? item.product_code ?? 'Sem descricao'}
                    </p>
                    <p className="text-xs text-slate-500">
                      {item.quantity} {item.unit ?? ''}
                    </p>
                  </div>
                </label>
              ))}

              <textarea
                value={observation}
                onChange={(event) => setObservation(event.target.value)}
                placeholder="Observacao (opcional)"
                className="rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-100 placeholder:text-slate-500"
                rows={2}
              />
              <MediaPicker file={photo} onChange={setPhoto} label="Vale para todas as propostas" />

              {mutation.isError && <p className="text-xs text-red-400">{mutation.error.message}</p>}

              <button
                type="button"
                disabled={selectedCount === 0 || mutation.isPending}
                onClick={() => mutation.mutate()}
                className="sticky bottom-0 mt-1 w-full rounded-lg bg-sky-500 py-2.5 text-sm font-medium text-slate-950 disabled:opacity-50"
              >
                {mutation.isPending ? 'Registrando...' : `Registrar producao (${selectedCount} item${selectedCount === 1 ? '' : 's'})`}
              </button>
            </div>
          )}
        </>
      )}
    </BottomSheet>
  )
}
