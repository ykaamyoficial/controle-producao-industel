import { useQuery } from '@tanstack/react-query'
import { ChevronLeft } from 'lucide-react'
import { Link, useParams } from 'react-router-dom'
import { getProposal, getProposalActivities, type ProposalItemSummary } from '../api/proposalDetail'
import { AttachmentGallery } from '../components/AttachmentGallery'
import { ProposalTimeline } from '../components/ProposalTimeline'
import { StatusPill } from '../components/StatusPill'

function formatDate(value: string | null): string {
  if (!value) return '-'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return '-'
  return date.toLocaleDateString('pt-BR')
}

function ItemRow({ item }: { item: ProposalItemSummary }) {
  const flags = [
    item.produced && 'Produzido',
    item.sent_to_galvanization && 'Galvanizacao',
    item.delivered && 'Entregue',
  ].filter(Boolean) as string[]

  return (
    <div className="flex items-center justify-between gap-3 border-b border-slate-800 py-2 last:border-0">
      <div className="min-w-0">
        <p className="truncate text-sm text-slate-100">
          {item.item_number} — {item.description ?? item.product_code ?? 'Sem descricao'}
        </p>
        <p className="text-xs text-slate-500">
          {item.quantity} {item.unit ?? ''}
          {flags.length > 0 && <span className="ml-2 text-emerald-500">{flags.join(' · ')}</span>}
        </p>
      </div>
    </div>
  )
}

export function ProposalDetailPage() {
  const { id } = useParams()
  const proposalId = Number(id)

  const proposalQuery = useQuery({
    queryKey: ['proposal', proposalId],
    queryFn: () => getProposal(proposalId),
    enabled: Number.isFinite(proposalId),
  })

  const activitiesQuery = useQuery({
    queryKey: ['proposal-activities', proposalId],
    queryFn: () => getProposalActivities(proposalId),
    enabled: Number.isFinite(proposalId),
  })

  const proposal = proposalQuery.data

  return (
    <div className="flex-1 px-4 pb-24 pt-6">
      <Link to="/" className="mb-3 inline-flex items-center gap-1 text-sm text-slate-400">
        <ChevronLeft size={16} />
        Propostas
      </Link>

      {proposalQuery.isLoading && <p className="text-sm text-slate-500">Carregando...</p>}
      {proposalQuery.isError && <p className="text-sm text-red-400">Nao foi possivel carregar a proposta.</p>}

      {proposal && (
        <>
          <div className="flex items-start justify-between gap-3">
            <div className="min-w-0">
              <h1 className="truncate text-xl font-semibold text-slate-100">{proposal.proposal_number}</h1>
              <p className="truncate text-sm text-slate-400">{proposal.customer_name}</p>
            </div>
            <StatusPill proposal={proposal} />
          </div>

          <dl className="mt-4 grid grid-cols-2 gap-x-4 gap-y-2 rounded-xl border border-slate-800 bg-slate-900 px-4 py-3 text-sm">
            <dt className="text-slate-500">Area atual</dt>
            <dd className="text-right text-slate-200">{proposal.current_area ?? '-'}</dd>
            <dt className="text-slate-500">Status</dt>
            <dd className="text-right text-slate-200">{proposal.current_status ?? '-'}</dd>
            <dt className="text-slate-500">Projeto</dt>
            <dd className="truncate text-right text-slate-200">{proposal.project_name ?? '-'}</dd>
            <dt className="text-slate-500">Prazo</dt>
            <dd className="text-right text-slate-200">{formatDate(proposal.deadline_date)}</dd>
            {proposal.notes && (
              <>
                <dt className="text-slate-500">Observacoes</dt>
                <dd className="col-span-2 text-slate-200">{proposal.notes}</dd>
              </>
            )}
          </dl>

          <h2 className="mt-6 text-sm font-semibold uppercase tracking-wide text-slate-400">
            Itens ({proposal.items.length})
          </h2>
          <div className="mt-2 rounded-xl border border-slate-800 bg-slate-900 px-4 py-1">
            {proposal.items.map((item) => (
              <ItemRow key={item.id} item={item} />
            ))}
            {proposal.items.length === 0 && <p className="py-3 text-sm text-slate-500">Sem itens.</p>}
          </div>

          <h2 className="mt-6 text-sm font-semibold uppercase tracking-wide text-slate-400">Fotos</h2>
          <div className="mt-2">
            <AttachmentGallery proposalId={proposal.id} />
          </div>

          <h2 className="mt-6 text-sm font-semibold uppercase tracking-wide text-slate-400">Historico</h2>
          <div className="mt-3">
            {activitiesQuery.isLoading && <p className="text-sm text-slate-500">Carregando historico...</p>}
            {activitiesQuery.isError && <p className="text-sm text-red-400">Nao foi possivel carregar o historico.</p>}
            {activitiesQuery.data && <ProposalTimeline proposalId={proposal.id} activities={activitiesQuery.data} />}
          </div>
        </>
      )}
    </div>
  )
}
