import { uploadProposalAttachment } from '../api/attachments'
import {
  listProductionProposals,
  pauseProduction,
  resumeProduction,
  startProduction,
  type ProductionProposalListItem,
} from '../api/production'
import type { BatchActionDefinition, BatchCandidate } from './types'

function toCandidate(proposal: ProductionProposalListItem, actionId: string): BatchCandidate {
  const action = proposal.actions.find((candidate) => candidate.id === actionId)
  return {
    id: proposal.id,
    version: proposal.version,
    proposalId: proposal.id,
    primaryLeft: proposal.customer_name,
    primaryRight: proposal.proposal_number,
    statusLabel: proposal.production_status ?? 'NAO_INICIADO',
    enabled: action?.enabled ?? false,
    disabledReason: action ? action.reason : 'Acao nao disponivel para esta proposta.',
  }
}

function fetchCandidates(actionId: string) {
  return async (search: string): Promise<BatchCandidate[]> => {
    const response = await listProductionProposals({ search: search || undefined, limit: 100 })
    return response.items
      .filter((proposal) => proposal.actions.some((action) => action.id === actionId))
      .map((proposal) => toCandidate(proposal, actionId))
  }
}

async function attachIfPhoto(candidate: BatchCandidate, actionId: string, ctx: { note: string; photo: File | null; requestId: string }) {
  if (!ctx.photo) return
  await uploadProposalAttachment(candidate.proposalId, ctx.photo, {
    area: 'PRODUCAO',
    actionId,
    note: ctx.note || undefined,
    requestId: ctx.requestId,
  })
}

export const PRODUCTION_BATCH_ACTIONS: BatchActionDefinition[] = [
  {
    id: 'START_PRODUCTION',
    label: 'Iniciar producao',
    fetchCandidates: fetchCandidates('START_PRODUCTION'),
    execute: async (candidate, ctx) => {
      await startProduction(candidate.id, candidate.version, ctx.note, ctx.requestId)
      await attachIfPhoto(candidate, 'START_PRODUCTION', ctx)
    },
  },
  {
    id: 'PAUSE_PRODUCTION',
    label: 'Pausar producao',
    noteRequired: true,
    noteLabel: 'Motivo da pausa (obrigatorio)',
    fetchCandidates: fetchCandidates('PAUSE_PRODUCTION'),
    execute: async (candidate, ctx) => {
      await pauseProduction(candidate.id, candidate.version, ctx.note, ctx.requestId)
      await attachIfPhoto(candidate, 'PAUSE_PRODUCTION', ctx)
    },
  },
  {
    id: 'RESUME_PRODUCTION',
    label: 'Retomar producao',
    fetchCandidates: fetchCandidates('RESUME_PRODUCTION'),
    execute: async (candidate, ctx) => {
      await resumeProduction(candidate.id, candidate.version, ctx.note, ctx.requestId)
      await attachIfPhoto(candidate, 'RESUME_PRODUCTION', ctx)
    },
  },
  {
    id: 'DEFINE_ITEM_FLOW',
    label: 'Definir fluxo dos itens',
    kind: 'items',
    fetchCandidates: fetchCandidates('DEFINE_ITEM_FLOW'),
  },
  {
    id: 'COMPLETE_ITEMS',
    label: 'Registrar producao',
    kind: 'items',
    fetchCandidates: fetchCandidates('COMPLETE_ITEMS'),
  },
]
