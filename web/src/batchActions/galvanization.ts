import { uploadProposalAttachment } from '../api/attachments'
import {
  closeGalvanizationLoad,
  getGalvanizationLoad,
  listGalvanizationCandidates,
  listGalvanizationLoads,
  registerGalvanizationReturn,
  releaseGalvanizationLoad,
  type GalvanizationLoadSummary,
} from '../api/galvanization'
import { listProposals } from '../api/proposals'
import type { BatchActionDefinition, BatchCandidate } from './types'

async function fetchProposalsWithAvailableItems(search: string): Promise<BatchCandidate[]> {
  const response = await listGalvanizationCandidates({ search: search || undefined, limit: 500 })
  const byProposal = new Map<number, { primaryLeft: string; primaryRight: string; available: number }>()
  for (const item of response.items) {
    const entry = byProposal.get(item.proposal_id) ?? { primaryLeft: item.customer_name, primaryRight: item.proposal_number, available: 0 }
    if (item.situation === 'DISPONIVEL') entry.available += 1
    byProposal.set(item.proposal_id, entry)
  }
  return Array.from(byProposal.entries()).map(([proposalId, entry]) => ({
    id: proposalId,
    version: 0,
    proposalId,
    primaryLeft: entry.primaryLeft,
    primaryRight: entry.primaryRight,
    statusLabel: entry.available > 0 ? `${entry.available} disponivel${entry.available > 1 ? 'is' : ''}` : 'Sem itens disponiveis',
    enabled: entry.available > 0,
    disabledReason: entry.available > 0 ? null : 'Todos os itens desta proposta ja estao em carga.',
  }))
}

/** Espelha app/services/backend_adapter.py:process_actions area == 'GALVANIZACAO': proposta ja
 * enviada, com carga ativa pendente de retorno. */
const RETURN_FROM_PROPOSAL_STATUSES = new Set(['ENVIADO_GALVANIZACAO', 'RETORNOU_PARCIAL'])
const RETURNABLE_LOAD_STATUSES = new Set(['LIBERADA_PARA_ENVIO', 'RETORNO_PARCIAL'])

async function fetchProposalsAwaitingReturn(search: string): Promise<BatchCandidate[]> {
  const response = await listProposals({ proposal_number: search || undefined, current_area: 'GALVANIZACAO', limit: 200 })
  return response.items
    .filter((proposal) => proposal.current_status && RETURN_FROM_PROPOSAL_STATUSES.has(proposal.current_status))
    .map((proposal) => ({
      id: proposal.id,
      version: proposal.version,
      proposalId: proposal.id,
      primaryLeft: proposal.customer_name,
      primaryRight: proposal.proposal_number,
      statusLabel: proposal.current_status ?? '-',
      enabled: true,
    }))
}

/** Resolve, igual ao desktop (resolve_return_load_ids), todas as cargas retornaveis
 * que contem a proposta - uma proposta pode ter itens em mais de uma carga ativa. */
async function resolveReturnableLoadsForProposal(proposalId: number) {
  const loadsResponse = await listGalvanizationLoads({ limit: 200 })
  const candidates = loadsResponse.items.filter((load) => !load.closed_at && RETURNABLE_LOAD_STATUSES.has(load.status))
  const matches = []
  for (const load of candidates) {
    const detail = await getGalvanizationLoad(load.id)
    if (detail.proposals.some((proposal) => proposal.proposal_id === proposalId)) matches.push(detail)
  }
  return matches
}

function toCandidate(load: GalvanizationLoadSummary): BatchCandidate {
  return {
    id: load.id,
    version: load.version,
    proposalId: 0,
    primaryLeft: load.driver_name,
    primaryRight: `Carga ${load.code ?? `#${load.id}`}`,
    statusLabel: load.closed_at ? 'ENCERRADA' : load.status,
    enabled: true,
  }
}

function fetchCandidatesByStatus(statuses: Set<string>) {
  return async (search: string): Promise<BatchCandidate[]> => {
    const response = await listGalvanizationLoads({ search: search || undefined, limit: 100 })
    return response.items
      .filter((load) => !load.closed_at && statuses.has(load.status))
      .map(toCandidate)
  }
}

async function attachToLoadProposals(loadId: number, actionId: string, ctx: { note: string; photo: File | null; requestId: string }) {
  if (!ctx.photo) return
  const detail = await getGalvanizationLoad(loadId)
  for (const proposal of detail.proposals) {
    await uploadProposalAttachment(proposal.proposal_id, ctx.photo, {
      area: 'GALVANIZACAO',
      actionId,
      note: ctx.note || undefined,
      requestId: ctx.requestId,
    })
  }
}

export const GALVANIZATION_BATCH_ACTIONS: BatchActionDefinition[] = [
  {
    id: 'SEND_TO_GALVANIZATION',
    label: 'Enviar para galvanizacao',
    kind: 'items',
    scope: 'proposals',
    fetchCandidates: fetchProposalsWithAvailableItems,
  },
  {
    id: 'REGISTER_RETURN_FROM_PROPOSAL',
    label: 'Registrar retorno',
    scope: 'proposals',
    fetchCandidates: fetchProposalsAwaitingReturn,
    execute: async (candidate, ctx) => {
      const loads = await resolveReturnableLoadsForProposal(candidate.proposalId)
      if (loads.length === 0) {
        throw new Error('Nao ha carga ativa com saldo pendente para esta proposta.')
      }
      for (const load of loads) {
        await registerGalvanizationReturn(load.id, load.version, [candidate.proposalId], ctx.note, ctx.requestId)
      }
      if (ctx.photo) {
        await uploadProposalAttachment(candidate.proposalId, ctx.photo, {
          area: 'GALVANIZACAO',
          actionId: 'REGISTER_RETURN_FROM_PROPOSAL',
          note: ctx.note || undefined,
          requestId: ctx.requestId,
        })
      }
    },
  },
  {
    id: 'release',
    label: 'Liberar carga para envio',
    scope: 'loads',
    fetchCandidates: fetchCandidatesByStatus(new Set(['AGUARDANDO_LIBERACAO'])),
    execute: async (candidate, ctx) => {
      await releaseGalvanizationLoad(candidate.id, candidate.version, ctx.note, ctx.requestId)
      await attachToLoadProposals(candidate.id, 'release', ctx)
    },
  },
  {
    id: 'return',
    label: 'Registrar retorno',
    scope: 'loads',
    fetchCandidates: fetchCandidatesByStatus(new Set(['LIBERADA_PARA_ENVIO', 'RETORNO_PARCIAL'])),
    execute: async (candidate, ctx) => {
      const detail = await getGalvanizationLoad(candidate.id)
      const proposalIds = detail.proposals.map((proposal) => proposal.proposal_id)
      await registerGalvanizationReturn(candidate.id, candidate.version, proposalIds, ctx.note, ctx.requestId)
      if (ctx.photo) {
        for (const proposalId of proposalIds) {
          await uploadProposalAttachment(proposalId, ctx.photo, {
            area: 'GALVANIZACAO',
            actionId: 'return',
            note: ctx.note || undefined,
            requestId: ctx.requestId,
          })
        }
      }
    },
  },
  {
    id: 'close',
    label: 'Encerrar carga',
    scope: 'loads',
    fetchCandidates: fetchCandidatesByStatus(new Set(['RETORNADA_GALVANIZACAO'])),
    execute: async (candidate, ctx) => {
      await closeGalvanizationLoad(candidate.id, candidate.version, ctx.note, ctx.requestId)
      await attachToLoadProposals(candidate.id, 'close', ctx)
    },
  },
]
