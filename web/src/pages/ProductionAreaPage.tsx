import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { listProductionProposals } from '../api/production'
import { areasVisibleFor } from '../areas/areaPermissionMap'
import { useAuth } from '../auth/AuthContext'
import { PRODUCTION_BATCH_ACTIONS } from '../batchActions/production'
import type { BatchActionDefinition, BatchCandidate } from '../batchActions/types'
import { ActionLauncherFab } from '../components/ActionLauncherFab'
import { AreaActionMenuSheet } from '../components/AreaActionMenuSheet'
import { CompleteItemsSheet } from '../components/CompleteItemsSheet'
import { ItemFlowSheet } from '../components/ItemFlowSheet'
import { ProposalMultiPickerSheet } from '../components/ProposalMultiPickerSheet'
import { ProposalPickerSheet } from '../components/ProposalPickerSheet'
import { StandardCard } from '../components/StandardCard'
import { classifyStatus, StatusBadge } from '../components/StatusBadge'

export function ProductionAreaPage() {
  const { user } = useAuth()
  const visible = areasVisibleFor(user?.permissions ?? []).some((area) => area.key === 'production')

  const { data, isLoading, isError } = useQuery({
    queryKey: ['production-proposals'],
    queryFn: () => listProductionProposals({ limit: 50 }),
    enabled: visible,
  })

  const [menuOpen, setMenuOpen] = useState(false)
  const [simpleAction, setSimpleAction] = useState<BatchActionDefinition | null>(null)
  const [itemsAction, setItemsAction] = useState<BatchActionDefinition | null>(null)
  const [itemFlowProposalIds, setItemFlowProposalIds] = useState<number[]>([])
  const [completeItemsProposalIds, setCompleteItemsProposalIds] = useState<number[]>([])

  if (!visible) {
    return (
      <div className="flex-1 px-4 pb-20 pt-6">
        <p className="text-sm text-slate-400">Voce nao tem permissao para acessar Producao.</p>
      </div>
    )
  }

  function handleMultiPickerConfirm(candidates: BatchCandidate[]) {
    const ids = candidates.map((candidate) => candidate.id)
    if (itemsAction?.id === 'DEFINE_ITEM_FLOW') setItemFlowProposalIds(ids)
    else if (itemsAction?.id === 'COMPLETE_ITEMS') setCompleteItemsProposalIds(ids)
    setItemsAction(null)
  }

  return (
    <div className="flex-1 px-4 pb-24 pt-6">
      <h1 className="text-xl font-semibold text-slate-100">Producao</h1>

      <div className="mt-4 flex flex-col gap-3">
        {isLoading && <p className="text-sm text-slate-500">Carregando...</p>}
        {isError && <p className="text-sm text-red-400">Nao foi possivel carregar producao.</p>}
        {data && data.items.length === 0 && <p className="text-sm text-slate-500">Nenhuma proposta em producao.</p>}
        {data?.items.map((proposal) => (
          <StandardCard
            key={proposal.id}
            primaryLeft={proposal.customer_name}
            primaryRight={proposal.proposal_number}
            status={<StatusBadge status={proposal.production_status ?? 'NAO_INICIADO'} />}
            itemsLabel={`${proposal.progress.produced_items}/${proposal.progress.total_items} itens produzidos`}
            href={`/propostas/${proposal.id}`}
            accentTone={classifyStatus(proposal.production_status ?? 'NAO_INICIADO')}
          />
        ))}
      </div>

      <ActionLauncherFab onClick={() => setMenuOpen(true)} />

      <AreaActionMenuSheet
        open={menuOpen}
        title="Acoes em Producao"
        actions={PRODUCTION_BATCH_ACTIONS}
        onSelect={(action) => {
          setMenuOpen(false)
          if (action.kind === 'items') setItemsAction(action)
          else setSimpleAction(action)
        }}
        onClose={() => setMenuOpen(false)}
      />

      <ProposalPickerSheet
        action={simpleAction}
        onClose={() => setSimpleAction(null)}
        invalidateQueryKeys={[['production-proposals']]}
      />

      <ProposalMultiPickerSheet action={itemsAction} onClose={() => setItemsAction(null)} onConfirm={handleMultiPickerConfirm} />

      <ItemFlowSheet proposalIds={itemFlowProposalIds} onClose={() => setItemFlowProposalIds([])} />

      <CompleteItemsSheet proposalIds={completeItemsProposalIds} onClose={() => setCompleteItemsProposalIds([])} />
    </div>
  )
}
