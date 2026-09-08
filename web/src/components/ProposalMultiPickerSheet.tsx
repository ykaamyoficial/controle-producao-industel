import { useQuery } from '@tanstack/react-query'
import { Search } from 'lucide-react'
import { useDeferredValue, useEffect, useState } from 'react'
import type { BatchActionDefinition, BatchCandidate } from '../batchActions/types'
import { BottomSheet } from './BottomSheet'

export function ProposalMultiPickerSheet({
  action,
  onClose,
  onConfirm,
}: {
  action: BatchActionDefinition | null
  onClose: () => void
  onConfirm: (candidates: BatchCandidate[]) => void
}) {
  const [search, setSearch] = useState('')
  const deferredSearch = useDeferredValue(search)
  const [selectedIds, setSelectedIds] = useState<Set<number>>(new Set())

  const candidatesQuery = useQuery({
    queryKey: ['batch-candidates', action?.id, deferredSearch],
    queryFn: () => action!.fetchCandidates(deferredSearch),
    enabled: !!action,
  })

  useEffect(() => {
    setSearch('')
    setSelectedIds(new Set())
  }, [action?.id])

  function toggle(id: number) {
    setSelectedIds((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  const candidates = candidatesQuery.data ?? []
  const enabledCandidates = candidates.filter((candidate) => candidate.enabled)
  const allChecked = enabledCandidates.length > 0 && enabledCandidates.every((candidate) => selectedIds.has(candidate.id))

  function toggleAll() {
    setSelectedIds(allChecked ? new Set() : new Set(enabledCandidates.map((candidate) => candidate.id)))
  }

  return (
    <BottomSheet open={!!action} title={action?.label ?? ''} onClose={onClose}>
      <div className="flex flex-col gap-3 py-1">
        <div className="flex items-center gap-2 rounded-lg border border-slate-800 bg-slate-900 px-3 py-2.5">
          <Search size={18} className="shrink-0 text-slate-500" />
          <input
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            placeholder="Buscar proposta..."
            className="w-full bg-transparent text-sm text-slate-100 outline-none placeholder:text-slate-500"
            inputMode="search"
          />
        </div>

        {candidatesQuery.isLoading && <p className="text-sm text-slate-500">Carregando...</p>}
        {candidatesQuery.isError && <p className="text-sm text-red-400">Nao foi possivel carregar as propostas.</p>}
        {!candidatesQuery.isLoading && candidates.length === 0 && (
          <p className="text-sm text-slate-500">Nenhuma proposta elegivel encontrada.</p>
        )}

        {enabledCandidates.length > 0 && (
          <label className="flex items-center gap-2 rounded-lg border border-slate-800 px-3 py-2.5">
            <input type="checkbox" checked={allChecked} onChange={toggleAll} className="h-4 w-4" />
            <span className="text-sm font-medium text-slate-200">
              Selecionar todas ({enabledCandidates.length} eleg{enabledCandidates.length > 1 ? 'iveis' : 'ivel'})
            </span>
          </label>
        )}

        {candidates.map((candidate) => (
          <label
            key={candidate.id}
            className={`flex items-center gap-2 rounded-lg border border-slate-800 px-3 py-2.5 ${
              !candidate.enabled ? 'opacity-50' : ''
            }`}
          >
            <input
              type="checkbox"
              disabled={!candidate.enabled}
              checked={selectedIds.has(candidate.id)}
              onChange={() => toggle(candidate.id)}
              className="h-4 w-4"
            />
            <div className="min-w-0 flex-1">
              <p className="truncate text-sm text-slate-100">{candidate.primaryLeft}</p>
              <p className="truncate text-sm text-slate-100">{candidate.primaryRight}</p>
              <p className="text-xs text-slate-500">
                {candidate.statusLabel}
                {!candidate.enabled && candidate.disabledReason && ` · ${candidate.disabledReason}`}
              </p>
            </div>
          </label>
        ))}

        {selectedIds.size > 0 && (
          <button
            type="button"
            onClick={() => onConfirm(candidates.filter((candidate) => selectedIds.has(candidate.id)))}
            className="sticky bottom-0 mt-1 w-full rounded-lg bg-sky-500 py-2.5 text-sm font-medium text-slate-950"
          >
            {`Continuar com ${selectedIds.size} proposta${selectedIds.size > 1 ? 's' : ''}`}
          </button>
        )}
      </div>
    </BottomSheet>
  )
}
