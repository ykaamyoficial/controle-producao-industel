import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import {
  listGalvanizationCandidates,
  listGalvanizationLoads,
  type GalvanizationCandidateItem,
  type GalvanizationLoadSummary,
} from '../api/galvanization'
import { areasVisibleFor } from '../areas/areaPermissionMap'
import { useAuth } from '../auth/AuthContext'
import { GALVANIZATION_BATCH_ACTIONS } from '../batchActions/galvanization'
import type { BatchActionDefinition, BatchCandidate } from '../batchActions/types'
import { ActionLauncherFab } from '../components/ActionLauncherFab'
import { AreaActionMenuSheet } from '../components/AreaActionMenuSheet'
import { ProposalMultiPickerSheet } from '../components/ProposalMultiPickerSheet'
import { ProposalPickerSheet } from '../components/ProposalPickerSheet'
import { SendToGalvanizationSheet } from '../components/SendToGalvanizationSheet'
import { StandardCard } from '../components/StandardCard'
import { classifyStatus, StatusBadge } from '../components/StatusBadge'

type Tab = 'propostas' | 'cargas'

function TabButton({ label, active, onClick }: { label: string; active: boolean; onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`flex-1 rounded-lg py-2 text-sm font-medium ${
        active ? 'bg-sky-500 text-slate-950' : 'bg-slate-900 text-slate-400'
      }`}
    >
      {label}
    </button>
  )
}

function LoadCard({ load }: { load: GalvanizationLoadSummary }) {
  const status = load.closed_at ? 'ENCERRADA' : load.status
  return (
    <StandardCard
      primaryLeft={load.driver_name}
      primaryRight={`Carga ${load.code ?? `#${load.id}`}`}
      status={<StatusBadge status={status} />}
      itemsLabel={`Peso total: ${load.total_weight} kg`}
      accentTone={classifyStatus(status)}
    />
  )
}

interface ProposalCandidateGroup {
  proposal_id: number
  proposal_number: string
  customer_name: string
  currentStatus: string | null
  items: GalvanizationCandidateItem[]
}

function groupCandidatesByProposal(items: GalvanizationCandidateItem[]): ProposalCandidateGroup[] {
  const groups = new Map<number, ProposalCandidateGroup>()
  for (const item of items) {
    const existing = groups.get(item.proposal_id)
    if (existing) {
      existing.items.push(item)
    } else {
      groups.set(item.proposal_id, {
        proposal_id: item.proposal_id,
        proposal_number: item.proposal_number,
        customer_name: item.customer_name,
        currentStatus: item.current_status,
        items: [item],
      })
    }
  }
  return Array.from(groups.values())
}

function CandidateCard({ group }: { group: ProposalCandidateGroup }) {
  const inLoad = group.items.filter((item) => item.situation === 'EM_GALVANIZACAO').length
  const available = group.items.length - inLoad
  return (
    <StandardCard
      primaryLeft={group.customer_name}
      primaryRight={group.proposal_number}
      status={<StatusBadge status={group.currentStatus ?? '-'} variant="pill" />}
      itemsLabel={`${available} disponivel${available > 1 ? 'is' : ''} de ${group.items.length} item${group.items.length > 1 ? 's' : ''} para galvanizacao`}
      href={`/propostas/${group.proposal_id}`}
      accentTone={classifyStatus(group.currentStatus)}
    />
  )
}

export function GalvanizationAreaPage() {
  const { user } = useAuth()
  const visible = areasVisibleFor(user?.permissions ?? []).some((area) => area.key === 'galvanization')

  const [tab, setTab] = useState<Tab>('propostas')

  const loadsQuery = useQuery({
    queryKey: ['galvanization-loads'],
    queryFn: () => listGalvanizationLoads({ limit: 50 }),
    enabled: visible && tab === 'cargas',
  })

  const candidatesQuery = useQuery({
    queryKey: ['galvanization-candidates'],
    queryFn: () => listGalvanizationCandidates({ limit: 200 }),
    enabled: visible && tab === 'propostas',
  })

  const [menuOpen, setMenuOpen] = useState(false)
  const [simpleAction, setSimpleAction] = useState<BatchActionDefinition | null>(null)
  const [itemsAction, setItemsAction] = useState<BatchActionDefinition | null>(null)
  const [sendToGalvanizationIds, setSendToGalvanizationIds] = useState<number[]>([])

  if (!visible) {
    return (
      <div className="flex-1 px-4 pb-20 pt-6">
        <p className="text-sm text-slate-400">Voce nao tem permissao para acessar Galvanizacao.</p>
      </div>
    )
  }

  const candidateGroups = candidatesQuery.data ? groupCandidatesByProposal(candidatesQuery.data.items) : []

  function handleMultiPickerConfirm(candidates: BatchCandidate[]) {
    if (itemsAction?.id === 'SEND_TO_GALVANIZATION') setSendToGalvanizationIds(candidates.map((candidate) => candidate.id))
    setItemsAction(null)
  }

  return (
    <div className="flex-1 px-4 pb-24 pt-6">
      <h1 className="text-xl font-semibold text-slate-100">Galvanizacao</h1>

      <div className="mt-4 flex gap-2">
        <TabButton label="Propostas" active={tab === 'propostas'} onClick={() => setTab('propostas')} />
        <TabButton label="Cargas" active={tab === 'cargas'} onClick={() => setTab('cargas')} />
      </div>

      {tab === 'propostas' && (
        <div className="mt-4 flex flex-col gap-3">
          {candidatesQuery.isLoading && <p className="text-sm text-slate-500">Carregando...</p>}
          {candidatesQuery.isError && <p className="text-sm text-red-400">Nao foi possivel carregar as propostas.</p>}
          {candidateGroups.length === 0 && !candidatesQuery.isLoading && (
            <p className="text-sm text-slate-500">Nenhuma proposta com itens para galvanizacao.</p>
          )}
          {candidateGroups.map((group) => (
            <CandidateCard key={group.proposal_id} group={group} />
          ))}
        </div>
      )}

      {tab === 'cargas' && (
        <div className="mt-4 flex flex-col gap-3">
          {loadsQuery.isLoading && <p className="text-sm text-slate-500">Carregando...</p>}
          {loadsQuery.isError && <p className="text-sm text-red-400">Nao foi possivel carregar as cargas.</p>}
          {loadsQuery.data && loadsQuery.data.items.length === 0 && (
            <p className="text-sm text-slate-500">Nenhuma carga encontrada.</p>
          )}
          {loadsQuery.data?.items.map((load) => (
            <LoadCard key={load.id} load={load} />
          ))}
        </div>
      )}

      <ActionLauncherFab onClick={() => setMenuOpen(true)} />

      <AreaActionMenuSheet
        open={menuOpen}
        title={tab === 'propostas' ? 'Acoes em Propostas' : 'Acoes em Cargas'}
        actions={GALVANIZATION_BATCH_ACTIONS.filter((action) => action.scope === (tab === 'propostas' ? 'proposals' : 'loads'))}
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
        invalidateQueryKeys={[['galvanization-loads'], ['galvanization-candidates']]}
      />

      <ProposalMultiPickerSheet action={itemsAction} onClose={() => setItemsAction(null)} onConfirm={handleMultiPickerConfirm} />

      <SendToGalvanizationSheet proposalIds={sendToGalvanizationIds} onClose={() => setSendToGalvanizationIds([])} />
    </div>
  )
}
