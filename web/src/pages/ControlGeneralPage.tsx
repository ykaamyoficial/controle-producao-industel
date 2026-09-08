import { useQuery } from '@tanstack/react-query'
import { Search } from 'lucide-react'
import { useDeferredValue, useMemo, useState } from 'react'
import { listProposals } from '../api/proposals'
import { AREA_DEFINITIONS } from '../areas/areaPermissionMap'
import { useAuth } from '../auth/AuthContext'
import { buildControlGeneralBatchActions } from '../batchActions/controlGeneral'
import type { BatchActionDefinition } from '../batchActions/types'
import { ActionLauncherFab } from '../components/ActionLauncherFab'
import { AreaActionMenuSheet } from '../components/AreaActionMenuSheet'
import { ProposalPickerSheet } from '../components/ProposalPickerSheet'
import { StandardCard } from '../components/StandardCard'
import { StatusPill, proposalStatusTone } from '../components/StatusPill'

const CONTROL_GENERAL_AREA = AREA_DEFINITIONS.find((area) => area.key === 'proposals')!

export function ControlGeneralPage() {
  const { user } = useAuth()
  const [search, setSearch] = useState('')
  const deferredSearch = useDeferredValue(search)

  const { data, isLoading, isError, refetch, isFetching } = useQuery({
    queryKey: ['proposals', { search: deferredSearch }],
    queryFn: () => listProposals({ proposal_number: deferredSearch || undefined, limit: 50 }),
  })

  const batchActions = useMemo(() => buildControlGeneralBatchActions(user?.permissions ?? []), [user?.permissions])
  const [menuOpen, setMenuOpen] = useState(false)
  const [activeAction, setActiveAction] = useState<BatchActionDefinition | null>(null)

  return (
    <div className="flex-1 px-4 pb-24 pt-6">
      <h1 className="text-xl font-semibold text-slate-100">{CONTROL_GENERAL_AREA.label}</h1>

      <div className="mt-4 flex items-center gap-2 rounded-lg border border-slate-800 bg-slate-900 px-3 py-2.5">
        <Search size={18} className="shrink-0 text-slate-500" />
        <input
          value={search}
          onChange={(event) => setSearch(event.target.value)}
          placeholder="Buscar por numero da proposta"
          className="w-full bg-transparent text-sm text-slate-100 outline-none placeholder:text-slate-500"
          inputMode="search"
        />
      </div>

      <div className="mt-4 flex flex-col gap-3">
        {isLoading && <p className="text-sm text-slate-500">Carregando propostas...</p>}

        {isError && (
          <div className="flex flex-col gap-2 rounded-lg border border-red-900 bg-red-950/40 px-4 py-3 text-sm text-red-300">
            <span>Nao foi possivel carregar as propostas.</span>
            <button type="button" onClick={() => refetch()} className="self-start underline">
              Tentar novamente
            </button>
          </div>
        )}

        {data && data.items.length === 0 && <p className="text-sm text-slate-500">Nenhuma proposta encontrada.</p>}

        {data?.items.map((proposal) => (
          <StandardCard
            key={proposal.id}
            primaryLeft={proposal.customer_name}
            primaryRight={proposal.proposal_number}
            status={<StatusPill proposal={proposal} />}
            itemsLabel={proposal.current_area ?? 'Sem area definida'}
            href={`/propostas/${proposal.id}`}
            accentTone={proposalStatusTone(proposal)}
          />
        ))}

        {isFetching && !isLoading && <p className="text-xs text-slate-600">Atualizando...</p>}
      </div>

      {batchActions.length > 0 && <ActionLauncherFab onClick={() => setMenuOpen(true)} />}

      <AreaActionMenuSheet
        open={menuOpen}
        title="Acoes em Controle Geral"
        actions={batchActions}
        onSelect={(action) => {
          setMenuOpen(false)
          setActiveAction(action)
        }}
        onClose={() => setMenuOpen(false)}
      />

      <ProposalPickerSheet
        action={activeAction}
        onClose={() => setActiveAction(null)}
        invalidateQueryKeys={[['proposals']]}
      />
    </div>
  )
}
