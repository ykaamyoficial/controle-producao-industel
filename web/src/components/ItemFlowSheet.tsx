import { useMutation, useQueries, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { getProductionProposal, updateProductionItemFlow, type ItemFlowUpdate, type ProductionItemSummary } from '../api/production'
import { BottomSheet } from './BottomSheet'

interface ItemOverride {
  produceInternally?: boolean
  requiresGalvanization?: boolean
  reason?: string
}

interface AggregatedItem extends ProductionItemSummary {
  proposalId: number
  proposalNumber: string
  proposalVersion: number
}

function ToggleGroup({
  label,
  value,
  onChange,
}: {
  label: string
  value: boolean | undefined
  onChange: (value: boolean) => void
}) {
  return (
    <div className="flex items-center justify-between gap-2">
      <span className="text-sm text-slate-300">{label}</span>
      <div className="flex overflow-hidden rounded-lg border border-slate-700">
        <button
          type="button"
          onClick={() => onChange(true)}
          className={`px-3 py-1.5 text-xs font-medium ${
            value === true ? 'bg-sky-500 text-slate-950' : 'bg-slate-950 text-slate-400'
          }`}
        >
          Sim
        </button>
        <button
          type="button"
          onClick={() => onChange(false)}
          className={`px-3 py-1.5 text-xs font-medium ${
            value === false ? 'bg-sky-500 text-slate-950' : 'bg-slate-950 text-slate-400'
          }`}
        >
          Nao
        </button>
      </div>
    </div>
  )
}

export function ItemFlowSheet({
  proposalIds,
  onClose,
}: {
  proposalIds: number[]
  onClose: () => void
}) {
  const queryClient = useQueryClient()
  const [overrides, setOverrides] = useState<Record<number, ItemOverride>>({})
  const [bulkProduce, setBulkProduce] = useState<boolean | undefined>(undefined)
  const [bulkGalvanize, setBulkGalvanize] = useState<boolean | undefined>(undefined)
  const [bulkReason, setBulkReason] = useState('')

  const detailQueries = useQueries({
    queries: proposalIds.map((id) => ({
      queryKey: ['production-proposal-detail', id],
      queryFn: () => getProductionProposal(id),
      enabled: proposalIds.length > 0,
    })),
  })

  const isLoading = detailQueries.some((query) => query.isLoading)
  const failedCount = detailQueries.filter((query) => query.isError).length
  const details = detailQueries.map((query) => query.data).filter((data): data is NonNullable<typeof data> => !!data)

  const items: AggregatedItem[] = details.flatMap((detail) =>
    detail.items.map((item) => ({
      ...item,
      proposalId: detail.id,
      proposalNumber: detail.proposal_number,
      proposalVersion: detail.version,
    })),
  )

  const mutation = useMutation({
    mutationFn: async () => {
      const dirtyByProposal = new Map<number, ItemFlowUpdate[]>()
      for (const item of items) {
        const override = overrides[item.id]
        if (!override || (override.produceInternally === undefined && override.requiresGalvanization === undefined)) continue
        const list = dirtyByProposal.get(item.proposalId) ?? []
        list.push({
          item_id: item.id,
          version: item.version,
          produce_internally: override.produceInternally,
          requires_galvanization: override.requiresGalvanization,
          non_production_reason: override.produceInternally === false ? override.reason : undefined,
        })
        dirtyByProposal.set(item.proposalId, list)
      }
      for (const [proposalId, list] of dirtyByProposal) {
        const proposalVersion = details.find((detail) => detail.id === proposalId)!.version
        await updateProductionItemFlow(proposalId, proposalVersion, list)
      }
    },
    onSuccess: () => {
      setOverrides({})
      setBulkProduce(undefined)
      setBulkGalvanize(undefined)
      setBulkReason('')
      queryClient.invalidateQueries({ queryKey: ['production-proposals'] })
      for (const id of proposalIds) {
        queryClient.invalidateQueries({ queryKey: ['production-proposal-detail', id] })
      }
      onClose()
    },
  })

  function handleClose() {
    setOverrides({})
    setBulkProduce(undefined)
    setBulkGalvanize(undefined)
    setBulkReason('')
    onClose()
  }

  function setOverride(itemId: number, patch: Partial<ItemOverride>) {
    setOverrides((prev) => ({ ...prev, [itemId]: { ...prev[itemId], ...patch } }))
  }

  function applyToAll() {
    setOverrides((prev) => {
      const next = { ...prev }
      for (const item of items) {
        if (!item.flow_editable) continue
        next[item.id] = {
          ...next[item.id],
          produceInternally: bulkProduce,
          requiresGalvanization: bulkGalvanize,
          reason: bulkProduce === false ? bulkReason : next[item.id]?.reason,
        }
      }
      return next
    })
  }

  const dirtyCount = Object.values(overrides).filter(
    (override) => override.produceInternally !== undefined || override.requiresGalvanization !== undefined,
  ).length

  const hasMissingReason = Object.values(overrides).some(
    (override) => override.produceInternally === false && !override.reason?.trim(),
  )

  const title =
    proposalIds.length === 1 && details[0] ? `Definir fluxo — ${details[0].proposal_number}` : `Definir fluxo — ${proposalIds.length} propostas`

  return (
    <BottomSheet open={proposalIds.length > 0} title={title} onClose={handleClose}>
      {isLoading && <p className="py-3 text-sm text-slate-500">Carregando itens...</p>}
      {failedCount > 0 && (
        <p className="py-3 text-sm text-red-400">
          {failedCount} de {proposalIds.length} proposta{proposalIds.length > 1 ? 's' : ''} nao pode{failedCount > 1 ? 'ram' : ''} ser
          carregada{failedCount > 1 ? 's' : ''}. As demais continuam disponiveis abaixo.
        </p>
      )}

      {items.length > 0 && (
        <div className="rounded-lg border border-sky-900 bg-sky-950/30 px-3 py-3">
          <p className="text-sm font-medium text-slate-100">Aplicar a todos os itens</p>
          <p className="mt-0.5 text-xs text-slate-500">
            Define o mesmo fluxo para todos de uma vez, em todas as propostas selecionadas. Ajuste itens individuais depois, se algum for diferente.
          </p>
          <div className="mt-3 flex flex-col gap-2">
            <ToggleGroup label="Produzir internamente?" value={bulkProduce} onChange={setBulkProduce} />
            {bulkProduce === false && (
              <input
                value={bulkReason}
                onChange={(event) => setBulkReason(event.target.value)}
                placeholder="Motivo (obrigatorio)"
                className="rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-100 placeholder:text-slate-500"
              />
            )}
            <ToggleGroup label="Requer galvanizacao?" value={bulkGalvanize} onChange={setBulkGalvanize} />
          </div>
          <button
            type="button"
            disabled={
              bulkProduce === undefined && bulkGalvanize === undefined
                ? true
                : bulkProduce === false && !bulkReason.trim()
            }
            onClick={applyToAll}
            className="mt-3 w-full rounded-lg bg-sky-500 py-2 text-xs font-medium text-slate-950 disabled:opacity-50"
          >
            Aplicar a todos
          </button>
        </div>
      )}

      <div className="mt-3 flex flex-col gap-3 py-2">
        {items.map((item) => {
          const override = overrides[item.id] ?? {}
          const currentProduce =
            override.produceInternally ?? (item.produce_internally === 'SIM' ? true : item.produce_internally === 'NAO' ? false : undefined)
          const currentGalvanize =
            override.requiresGalvanization ??
            (item.requires_galvanization === 'SIM' ? true : item.requires_galvanization === 'NAO' ? false : undefined)

          return (
            <div key={item.id} className="rounded-lg border border-slate-800 px-3 py-3">
              {proposalIds.length > 1 && (
                <p className="mb-1 text-xs font-medium uppercase tracking-wide text-sky-400">{item.proposalNumber}</p>
              )}
              <p className="text-sm text-slate-100">
                {item.item_number} — {item.description ?? item.product_code ?? 'Sem descricao'}
              </p>
              <p className="text-xs text-slate-500">
                {item.quantity} {item.unit ?? ''}
              </p>

              {!item.flow_editable ? (
                <p className="mt-2 text-xs text-amber-500">{item.flow_lock_reason}</p>
              ) : (
                <div className="mt-2 flex flex-col gap-2">
                  <ToggleGroup
                    label="Produzir internamente?"
                    value={currentProduce}
                    onChange={(value) => setOverride(item.id, { produceInternally: value })}
                  />
                  {currentProduce === false && (
                    <input
                      value={override.reason ?? ''}
                      onChange={(event) => setOverride(item.id, { reason: event.target.value })}
                      placeholder="Motivo (obrigatorio)"
                      className="rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-100 placeholder:text-slate-500"
                    />
                  )}
                  <ToggleGroup
                    label="Requer galvanizacao?"
                    value={currentGalvanize}
                    onChange={(value) => setOverride(item.id, { requiresGalvanization: value })}
                  />
                </div>
              )}
            </div>
          )
        })}
      </div>

      {mutation.isError && <p className="text-xs text-red-400">{mutation.error.message}</p>}

      {dirtyCount > 0 && (
        <button
          type="button"
          disabled={mutation.isPending || hasMissingReason}
          onClick={() => mutation.mutate()}
          className="sticky bottom-0 mt-2 w-full rounded-lg bg-sky-500 py-2.5 text-sm font-medium text-slate-950 disabled:opacity-50"
        >
          {mutation.isPending ? 'Salvando...' : `Salvar fluxo (${dirtyCount} item${dirtyCount > 1 ? 's' : ''})`}
        </button>
      )}
    </BottomSheet>
  )
}
