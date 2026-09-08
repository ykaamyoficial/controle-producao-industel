import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Check, Search, X } from 'lucide-react'
import { useDeferredValue, useState } from 'react'
import { newRequestId } from '../api/client'
import type { BatchActionDefinition, BatchCandidate } from '../batchActions/types'
import { BottomSheet } from './BottomSheet'
import { MediaPicker } from './MediaPicker'

type Phase = 'select' | 'running' | 'report'

interface CandidateResult {
  candidate: BatchCandidate
  success: boolean
  error?: string
}

export function ProposalPickerSheet({
  action,
  onClose,
  invalidateQueryKeys,
}: {
  action: BatchActionDefinition | null
  onClose: () => void
  /** query keys pra invalidar apos a execucao (listas que devem refletir o novo estado) */
  invalidateQueryKeys: unknown[][]
}) {
  const queryClient = useQueryClient()
  const [search, setSearch] = useState('')
  const deferredSearch = useDeferredValue(search)
  const [selectedIds, setSelectedIds] = useState<Set<number>>(new Set())
  const [note, setNote] = useState('')
  const [photo, setPhoto] = useState<File | null>(null)
  const [phase, setPhase] = useState<Phase>('select')
  const [results, setResults] = useState<CandidateResult[]>([])

  const candidatesQuery = useQuery({
    queryKey: ['batch-candidates', action?.id, deferredSearch],
    queryFn: () => action!.fetchCandidates(deferredSearch),
    enabled: !!action && phase === 'select',
  })

  function reset() {
    setSearch('')
    setSelectedIds(new Set())
    setNote('')
    setPhoto(null)
    setPhase('select')
    setResults([])
  }

  function handleClose() {
    reset()
    onClose()
  }

  function toggle(id: number) {
    setSelectedIds((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  function toggleAll() {
    const enabledCandidates = (candidatesQuery.data ?? []).filter((candidate) => candidate.enabled)
    const allChecked = enabledCandidates.length > 0 && enabledCandidates.every((candidate) => selectedIds.has(candidate.id))
    setSelectedIds(allChecked ? new Set() : new Set(enabledCandidates.map((candidate) => candidate.id)))
  }

  async function runBatch() {
    if (!action) return
    const candidates = (candidatesQuery.data ?? []).filter((candidate) => selectedIds.has(candidate.id))
    setPhase('running')
    const requestId = newRequestId()
    const collected: CandidateResult[] = []
    for (const candidate of candidates) {
      try {
        await action.execute!(candidate, { note, photo, requestId })
        collected.push({ candidate, success: true })
      } catch (error) {
        collected.push({ candidate, success: false, error: error instanceof Error ? error.message : String(error) })
      }
      setResults([...collected])
    }
    setPhase('report')
    for (const key of invalidateQueryKeys) {
      queryClient.invalidateQueries({ queryKey: key })
    }
  }

  const candidates = candidatesQuery.data ?? []
  const enabledCount = candidates.filter((candidate) => candidate.enabled).length
  const allChecked = enabledCount > 0 && candidates.filter((c) => c.enabled).every((c) => selectedIds.has(c.id))
  const successCount = results.filter((r) => r.success).length
  const failureCount = results.filter((r) => !r.success).length

  return (
    <BottomSheet open={!!action} title={action?.label ?? ''} onClose={handleClose}>
      {phase === 'select' && (
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

          {enabledCount > 0 && (
            <label className="flex items-center gap-2 rounded-lg border border-slate-800 px-3 py-2.5">
              <input type="checkbox" checked={allChecked} onChange={toggleAll} className="h-4 w-4" />
              <span className="text-sm font-medium text-slate-200">
                Selecionar todas ({enabledCount} eleg{enabledCount > 1 ? 'iveis' : 'ivel'})
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
            <>
              <textarea
                value={note}
                onChange={(event) => setNote(event.target.value)}
                placeholder={action?.noteLabel ?? 'Observacao (opcional)'}
                className="rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-100 placeholder:text-slate-500"
                rows={2}
              />
              <MediaPicker file={photo} onChange={setPhoto} label="Vale para todas as propostas selecionadas" />
              <button
                type="button"
                disabled={action?.noteRequired && !note.trim()}
                onClick={runBatch}
                className="sticky bottom-0 mt-1 w-full rounded-lg bg-sky-500 py-2.5 text-sm font-medium text-slate-950 disabled:opacity-50"
              >
                {`Aplicar a ${selectedIds.size} proposta${selectedIds.size > 1 ? 's' : ''}`}
              </button>
            </>
          )}
        </div>
      )}

      {phase === 'running' && (
        <div className="flex flex-col gap-2 py-3">
          <p className="text-sm text-slate-300">
            Processando {results.length}/{selectedIds.size}...
          </p>
          <div className="h-2 overflow-hidden rounded-full bg-slate-800">
            <div
              className="h-full bg-sky-500 transition-all"
              style={{ width: `${(results.length / Math.max(selectedIds.size, 1)) * 100}%` }}
            />
          </div>
        </div>
      )}

      {phase === 'report' && (
        <div className="flex flex-col gap-3 py-1">
          <p className="text-sm text-slate-200">
            {successCount} aplicada{successCount === 1 ? '' : 's'}
            {failureCount > 0 && `, ${failureCount} falharam`}
          </p>
          <div className="flex flex-col gap-2">
            {results.map((result) => (
              <div
                key={result.candidate.id}
                className={`flex items-start gap-2 rounded-lg border px-3 py-2 ${
                  result.success ? 'border-emerald-900 bg-emerald-950/20' : 'border-red-900 bg-red-950/20'
                }`}
              >
                {result.success ? (
                  <Check size={16} className="mt-0.5 shrink-0 text-emerald-400" />
                ) : (
                  <X size={16} className="mt-0.5 shrink-0 text-red-400" />
                )}
                <div className="min-w-0">
                  <p className="truncate text-sm text-slate-100">{result.candidate.primaryRight}</p>
                  {!result.success && <p className="text-xs text-red-400">{result.error}</p>}
                </div>
              </div>
            ))}
          </div>
          <button
            type="button"
            onClick={handleClose}
            className="mt-1 w-full rounded-lg bg-sky-500 py-2.5 text-sm font-medium text-slate-950"
          >
            Concluir
          </button>
        </div>
      )}
    </BottomSheet>
  )
}
