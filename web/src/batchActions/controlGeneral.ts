import { uploadProposalAttachment } from '../api/attachments'
import { cancelProposal, listProposals, releaseProposalToProduction, type ProposalListItem } from '../api/proposals'
import type { BatchActionDefinition, BatchCandidate } from './types'

function hasPermission(permissions: string[], required: string): boolean {
  return permissions.includes('*') || permissions.includes(required)
}

function toCandidate(proposal: ProposalListItem): BatchCandidate {
  return {
    id: proposal.id,
    version: proposal.version,
    proposalId: proposal.id,
    primaryLeft: proposal.customer_name,
    primaryRight: proposal.proposal_number,
    statusLabel: proposal.current_status ?? '-',
    enabled: true,
  }
}

export function buildControlGeneralBatchActions(permissions: string[]): BatchActionDefinition[] {
  const actions: BatchActionDefinition[] = []

  if (hasPermission(permissions, 'proposals.change_status')) {
    actions.push({
      id: 'RELEASE_TO_PRODUCTION',
      label: 'Liberar para producao',
      fetchCandidates: async (search) => {
        const response = await listProposals({
          proposal_number: search || undefined,
          current_status: 'AGUARDANDO_LIBERACAO',
          limit: 100,
        })
        return response.items.map(toCandidate)
      },
      execute: async (candidate, ctx) => {
        await releaseProposalToProduction(candidate.id, candidate.version, ctx.note, ctx.requestId)
        if (ctx.photo) {
          await uploadProposalAttachment(candidate.proposalId, ctx.photo, {
            area: 'CONTROLE_GERAL',
            actionId: 'RELEASE_TO_PRODUCTION',
            note: ctx.note || undefined,
            requestId: ctx.requestId,
          })
        }
      },
    })
  }

  if (hasPermission(permissions, 'proposals.cancel')) {
    actions.push({
      id: 'CANCEL_PROPOSAL',
      label: 'Cancelar proposta',
      noteRequired: true,
      noteLabel: 'Motivo do cancelamento (obrigatorio)',
      fetchCandidates: async (search) => {
        const response = await listProposals({
          proposal_number: search || undefined,
          is_cancelled: false,
          is_completed: false,
          limit: 100,
        })
        return response.items.map(toCandidate)
      },
      execute: async (candidate, ctx) => {
        await cancelProposal(candidate.id, candidate.version, ctx.note, ctx.requestId)
        if (ctx.photo) {
          await uploadProposalAttachment(candidate.proposalId, ctx.photo, {
            area: 'CONTROLE_GERAL',
            actionId: 'CANCEL_PROPOSAL',
            note: ctx.note || undefined,
            requestId: ctx.requestId,
          })
        }
      },
    })
  }

  return actions
}
