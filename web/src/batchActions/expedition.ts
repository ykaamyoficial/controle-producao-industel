import { uploadProposalAttachment } from '../api/attachments'
import {
  deliverExpeditionItems,
  listExpeditionProposals,
  separateExpeditionItems,
  startExpeditionSeparation,
  type ExpeditionProposalSummary,
} from '../api/expedition'
import type { BatchActionDefinition, BatchCandidate } from './types'

function toCandidate(proposal: ExpeditionProposalSummary, actionId: string): BatchCandidate {
  const action = proposal.actions.find((candidate) => candidate.id === actionId)
  return {
    id: proposal.id,
    version: proposal.version,
    proposalId: proposal.id,
    primaryLeft: proposal.customer_name,
    primaryRight: proposal.proposal_number,
    statusLabel: proposal.shipping_status ?? 'EM_SEPARACAO',
    enabled: action?.enabled ?? false,
    disabledReason: action ? action.reason : 'Acao nao disponivel para esta proposta.',
  }
}

function fetchCandidates(actionId: string) {
  return async (search: string): Promise<BatchCandidate[]> => {
    const response = await listExpeditionProposals({ search: search || undefined, limit: 100 })
    return response.items
      .filter((proposal) => proposal.actions.some((action) => action.id === actionId))
      .map((proposal) => toCandidate(proposal, actionId))
  }
}

async function attachIfPhoto(candidate: BatchCandidate, actionId: string, ctx: { note: string; photo: File | null; requestId: string }) {
  if (!ctx.photo) return
  await uploadProposalAttachment(candidate.proposalId, ctx.photo, {
    area: 'EXPEDICAO',
    actionId,
    note: ctx.note || undefined,
    requestId: ctx.requestId,
  })
}

export const EXPEDITION_BATCH_ACTIONS: BatchActionDefinition[] = [
  {
    id: 'START_SEPARATION',
    label: 'Iniciar separacao',
    fetchCandidates: fetchCandidates('START_SEPARATION'),
    execute: async (candidate, ctx) => {
      await startExpeditionSeparation(candidate.id, candidate.version, ctx.note, ctx.requestId)
      await attachIfPhoto(candidate, 'START_SEPARATION', ctx)
    },
  },
  {
    id: 'SEPARATE_ITEMS',
    label: 'Registrar separacao',
    fetchCandidates: fetchCandidates('SEPARATE_ITEMS'),
    execute: async (candidate, ctx) => {
      await separateExpeditionItems(candidate.id, candidate.version, ctx.note, ctx.requestId)
      await attachIfPhoto(candidate, 'SEPARATE_ITEMS', ctx)
    },
  },
  {
    id: 'REGISTER_DELIVERY',
    label: 'Registrar entrega',
    fetchCandidates: fetchCandidates('REGISTER_DELIVERY'),
    execute: async (candidate, ctx) => {
      await deliverExpeditionItems(candidate.id, candidate.version, ctx.note, ctx.requestId)
      await attachIfPhoto(candidate, 'REGISTER_DELIVERY', ctx)
    },
  },
]
