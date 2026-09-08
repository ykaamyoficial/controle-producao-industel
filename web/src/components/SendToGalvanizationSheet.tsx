import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { PackagePlus, Truck } from 'lucide-react'
import { useEffect, useState } from 'react'
import { uploadProposalAttachment } from '../api/attachments'
import { newRequestId } from '../api/client'
import {
  addItemsToGalvanizationLoad,
  createGalvanizationLoad,
  getGalvanizationLoad,
  listGalvanizationCandidates,
  listGalvanizationLoads,
  type GalvanizationLoadSummary,
} from '../api/galvanization'
import { BottomSheet } from './BottomSheet'
import { MediaPicker } from './MediaPicker'

type Mode = 'choose' | 'new' | 'existing'

export function SendToGalvanizationSheet({
  proposalIds,
  onClose,
}: {
  proposalIds: number[]
  onClose: () => void
}) {
  const queryClient = useQueryClient()

  const candidatesQuery = useQuery({
    queryKey: ['galvanization-candidates'],
    queryFn: () => listGalvanizationCandidates({ limit: 500 }),
    enabled: proposalIds.length > 0,
  })

  const openLoadsQuery = useQuery({
    queryKey: ['galvanization-loads', 'AGUARDANDO_LIBERACAO'],
    queryFn: () => listGalvanizationLoads({ status: 'AGUARDANDO_LIBERACAO', limit: 100 }),
    enabled: proposalIds.length > 0,
  })

  const proposalIdSet = new Set(proposalIds)
  const availableItems = (candidatesQuery.data?.items ?? []).filter(
    (item) => proposalIdSet.has(item.proposal_id) && item.situation === 'DISPONIVEL',
  )

  const [selectedIds, setSelectedIds] = useState<Set<number>>(new Set())
  const [mode, setMode] = useState<Mode>('choose')
  const [targetLoad, setTargetLoad] = useState<GalvanizationLoadSummary | null>(null)
  const [driverName, setDriverName] = useState('')
  const [note, setNote] = useState('')
  const [photo, setPhoto] = useState<File | null>(null)

  useEffect(() => {
    if (candidatesQuery.data) {
      setSelectedIds(new Set(availableItems.map((item) => item.item_id)))
    }
    setMode('choose')
    setTargetLoad(null)
    setDriverName('')
    setNote('')
    setPhoto(null)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [candidatesQuery.data, proposalIds.join(',')])

  const mutation = useMutation({
    mutationFn: async () => {
      if (selectedIds.size === 0) return
      const requestId = newRequestId()
      const selected = availableItems.filter((item) => selectedIds.has(item.item_id))
      const items = selected.map((item) => ({ proposalItemId: item.item_id, version: item.version }))

      let load
      if (mode === 'existing' && targetLoad) {
        const loadDetail = await getGalvanizationLoad(targetLoad.id)
        load = await addItemsToGalvanizationLoad(targetLoad.id, loadDetail.version, loadDetail.items, items, note || undefined, requestId)
      } else {
        load = await createGalvanizationLoad(driverName.trim(), items, note || undefined, requestId)
      }

      if (photo) {
        const affectedProposalIds = new Set(selected.map((item) => item.proposal_id))
        for (const proposalId of affectedProposalIds) {
          await uploadProposalAttachment(proposalId, photo, {
            area: 'GALVANIZACAO',
            actionId: mode === 'existing' ? 'GALVANIZATION_LOAD_UPDATED' : 'GALVANIZATION_LOAD_CREATED',
            note: note || undefined,
            requestId,
          })
        }
      }
      return load
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['galvanization-candidates'] })
      queryClient.invalidateQueries({ queryKey: ['galvanization-loads'] })
      onClose()
    },
  })

  function toggleItem(itemId: number) {
    setSelectedIds((prev) => {
      const next = new Set(prev)
      if (next.has(itemId)) next.delete(itemId)
      else next.add(itemId)
      return next
    })
  }

  function toggleAll() {
    setSelectedIds((prev) => (prev.size === availableItems.length ? new Set() : new Set(availableItems.map((item) => item.item_id))))
  }

  function handleClose() {
    setMode('choose')
    setTargetLoad(null)
    onClose()
  }

  const allChecked = availableItems.length > 0 && selectedIds.size === availableItems.length
  const proposalCount = proposalIds.length
  const title = proposalCount === 1 ? 'Enviar para galvanizacao' : `Enviar para galvanizacao — ${proposalCount} propostas`
  const canConfirm = mode === 'existing' ? !!targetLoad : driverName.trim().length > 0

  return (
    <BottomSheet open={proposalIds.length > 0} title={title} onClose={handleClose}>
      {candidatesQuery.isLoading && <p className="py-3 text-sm text-slate-500">Carregando itens...</p>}
      {candidatesQuery.isError && <p className="py-3 text-sm text-red-400">Nao foi possivel carregar os itens.</p>}

      {!candidatesQuery.isLoading && availableItems.length === 0 ? (
        <p className="py-3 text-sm text-slate-500">Nenhum item disponivel para enviar.</p>
      ) : (
        availableItems.length > 0 && (
          <div className="flex flex-col gap-2 py-1">
            <label className="flex items-center gap-2 rounded-lg border border-slate-800 px-3 py-2.5">
              <input type="checkbox" checked={allChecked} onChange={toggleAll} className="h-4 w-4" />
              <span className="text-sm font-medium text-slate-200">
                Selecionar todos ({availableItems.length} disponivel{availableItems.length > 1 ? 'is' : ''})
              </span>
            </label>

            {availableItems.map((item) => (
              <label key={item.item_id} className="flex items-center gap-2 rounded-lg border border-slate-800 px-3 py-2.5">
                <input
                  type="checkbox"
                  checked={selectedIds.has(item.item_id)}
                  onChange={() => toggleItem(item.item_id)}
                  className="h-4 w-4"
                />
                <div className="min-w-0 flex-1">
                  {proposalCount > 1 && (
                    <p className="text-xs font-medium uppercase tracking-wide text-sky-400">{item.proposal_number}</p>
                  )}
                  <p className="truncate text-sm text-slate-100">
                    {item.item_number} — {item.description ?? item.product_code ?? 'Sem descricao'}
                  </p>
                  <p className="text-xs text-slate-500">{item.available_quantity} disponivel</p>
                </div>
              </label>
            ))}

            {selectedIds.size > 0 && mode === 'choose' && (
              <div className="mt-2 grid grid-cols-2 gap-2">
                <button
                  type="button"
                  onClick={() => setMode('existing')}
                  className="flex flex-col items-center gap-1.5 rounded-lg border border-slate-800 px-3 py-4 text-center active:bg-slate-800"
                >
                  <Truck size={22} className="text-sky-400" />
                  <span className="text-sm font-medium text-slate-100">Carga existente</span>
                  <span className="text-xs text-slate-500">Adicionar a uma carga aberta</span>
                </button>
                <button
                  type="button"
                  onClick={() => setMode('new')}
                  className="flex flex-col items-center gap-1.5 rounded-lg border border-slate-800 px-3 py-4 text-center active:bg-slate-800"
                >
                  <PackagePlus size={22} className="text-sky-400" />
                  <span className="text-sm font-medium text-slate-100">Nova carga</span>
                  <span className="text-xs text-slate-500">Criar carga so com estes itens</span>
                </button>
              </div>
            )}

            {mode === 'existing' && (
              <div className="mt-1 flex flex-col gap-2">
                <button type="button" onClick={() => setMode('choose')} className="self-start text-xs text-slate-400 underline">
                  Voltar
                </button>
                {openLoadsQuery.isLoading && <p className="text-sm text-slate-500">Carregando cargas abertas...</p>}
                {openLoadsQuery.data?.items.length === 0 && (
                  <p className="text-sm text-slate-500">Nenhuma carga aberta no momento.</p>
                )}
                {openLoadsQuery.data?.items.map((load) => (
                  <label key={load.id} className="flex items-center gap-2 rounded-lg border border-slate-800 px-3 py-2.5">
                    <input
                      type="radio"
                      name="target-load"
                      checked={targetLoad?.id === load.id}
                      onChange={() => setTargetLoad(load)}
                      className="h-4 w-4"
                    />
                    <div className="min-w-0 flex-1">
                      <p className="truncate text-sm text-slate-100">Carga {load.code ?? `#${load.id}`}</p>
                      <p className="text-xs text-slate-500">Motorista: {load.driver_name}</p>
                    </div>
                  </label>
                ))}
              </div>
            )}

            {mode === 'new' && (
              <div className="mt-1 flex flex-col gap-2">
                <button type="button" onClick={() => setMode('choose')} className="self-start text-xs text-slate-400 underline">
                  Voltar
                </button>
                <input
                  value={driverName}
                  onChange={(event) => setDriverName(event.target.value)}
                  placeholder="Motorista (obrigatorio)"
                  className="rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-100 placeholder:text-slate-500"
                />
              </div>
            )}

            {(mode === 'existing' || mode === 'new') && (
              <>
                <textarea
                  value={note}
                  onChange={(event) => setNote(event.target.value)}
                  placeholder="Observacao (opcional)"
                  className="rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-100 placeholder:text-slate-500"
                  rows={2}
                />
                <MediaPicker file={photo} onChange={setPhoto} label="Vale para todas as propostas" />

                {mutation.isError && <p className="text-xs text-red-400">{mutation.error.message}</p>}

                <button
                  type="button"
                  disabled={selectedIds.size === 0 || !canConfirm || mutation.isPending}
                  onClick={() => mutation.mutate()}
                  className="sticky bottom-0 mt-1 w-full rounded-lg bg-sky-500 py-2.5 text-sm font-medium text-slate-950 disabled:opacity-50"
                >
                  {mutation.isPending
                    ? 'Enviando...'
                    : `Enviar para galvanizacao (${selectedIds.size} item${selectedIds.size === 1 ? '' : 's'})`}
                </button>
              </>
            )}
          </div>
        )
      )}
    </BottomSheet>
  )
}
