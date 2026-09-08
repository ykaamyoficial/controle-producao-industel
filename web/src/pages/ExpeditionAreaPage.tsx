import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { listExpeditionProposals, type ExpeditionProposalSummary } from '../api/expedition'
import { areasVisibleFor } from '../areas/areaPermissionMap'
import { useAuth } from '../auth/AuthContext'
import { EXPEDITION_BATCH_ACTIONS } from '../batchActions/expedition'
import type { BatchActionDefinition } from '../batchActions/types'
import { ActionLauncherFab } from '../components/ActionLauncherFab'
import { AreaActionMenuSheet } from '../components/AreaActionMenuSheet'
import { ProposalPickerSheet } from '../components/ProposalPickerSheet'
import { StandardCard } from '../components/StandardCard'
import { classifyStatus, StatusBadge } from '../components/StatusBadge'

function ProposalCard({ proposal }: { proposal: ExpeditionProposalSummary }) {
  const status = proposal.shipping_status ?? 'EM_SEPARACAO'
  return (
    <StandardCard
      primaryLeft={proposal.customer_name}
      primaryRight={proposal.proposal_number}
      status={<StatusBadge status={status} />}
      itemsLabel={`Separado ${proposal.separated_quantity} / Entregue ${proposal.delivered_quantity} / Pendente ${proposal.pending_quantity}`}
      href={`/propostas/${proposal.id}`}
      accentTone={classifyStatus(status)}
    />
  )
}

export function ExpeditionAreaPage() {
  const { user } = useAuth()
  const visible = areasVisibleFor(user?.permissions ?? []).some((area) => area.key === 'expedition')

  const { data, isLoading, isError } = useQuery({
    queryKey: ['expedition-proposals'],
    queryFn: () => listExpeditionProposals({ limit: 50 }),
    enabled: visible,
  })

  const [menuOpen, setMenuOpen] = useState(false)
  const [activeAction, setActiveAction] = useState<BatchActionDefinition | null>(null)

  if (!visible) {
    return (
      <div className="flex-1 px-4 pb-20 pt-6">
        <p className="text-sm text-slate-400">Voce nao tem permissao para acessar Expedicao.</p>
      </div>
    )
  }

  return (
    <div className="flex-1 px-4 pb-24 pt-6">
      <h1 className="text-xl font-semibold text-slate-100">Expedicao</h1>

      <div className="mt-4 flex flex-col gap-3">
        {isLoading && <p className="text-sm text-slate-500">Carregando...</p>}
        {isError && <p className="text-sm text-red-400">Nao foi possivel carregar a expedicao.</p>}
        {data && data.items.length === 0 && <p className="text-sm text-slate-500">Nenhuma proposta em expedicao.</p>}
        {data?.items.map((proposal) => (
          <ProposalCard key={proposal.id} proposal={proposal} />
        ))}
      </div>

      <ActionLauncherFab onClick={() => setMenuOpen(true)} />

      <AreaActionMenuSheet
        open={menuOpen}
        title="Acoes em Expedicao"
        actions={EXPEDITION_BATCH_ACTIONS}
        onSelect={(action) => {
          setMenuOpen(false)
          setActiveAction(action)
        }}
        onClose={() => setMenuOpen(false)}
      />

      <ProposalPickerSheet
        action={activeAction}
        onClose={() => setActiveAction(null)}
        invalidateQueryKeys={[['expedition-proposals']]}
      />
    </div>
  )
}
