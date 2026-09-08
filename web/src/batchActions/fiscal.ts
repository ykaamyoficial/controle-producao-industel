import { uploadProposalAttachment } from '../api/attachments'
import { listFiscalRecords, markFiscalInvoiceWithdrawn, type FiscalRecordSummary } from '../api/fiscal'
import type { BatchActionDefinition, BatchCandidate } from './types'

function toCandidate(record: FiscalRecordSummary, actionId: string): BatchCandidate {
  const action = record.actions.find((candidate) => candidate.id === actionId)
  return {
    id: record.id,
    version: record.version,
    proposalId: record.proposal_id,
    primaryLeft: record.customer_name,
    primaryRight: record.proposal_number,
    statusLabel: record.fiscal_situation,
    enabled: action?.enabled ?? false,
    disabledReason: action ? action.reason : 'Acao nao disponivel para esta proposta.',
  }
}

function fetchCandidates(actionId: string) {
  return async (search: string): Promise<BatchCandidate[]> => {
    const response = await listFiscalRecords({ search: search || undefined, limit: 100 })
    return response.items
      .filter((record) => record.actions.some((action) => action.id === actionId))
      .map((record) => toCandidate(record, actionId))
  }
}

export const FISCAL_BATCH_ACTIONS: BatchActionDefinition[] = [
  {
    id: 'MARK_INVOICE_WITHDRAWN',
    label: 'Marcar NF retirada',
    fetchCandidates: fetchCandidates('MARK_INVOICE_WITHDRAWN'),
    execute: async (candidate, ctx) => {
      await markFiscalInvoiceWithdrawn(candidate.id, candidate.version, ctx.note, ctx.requestId)
      if (ctx.photo) {
        await uploadProposalAttachment(candidate.proposalId, ctx.photo, {
          area: 'FISCAL',
          actionId: 'MARK_INVOICE_WITHDRAWN',
          note: ctx.note || undefined,
          requestId: ctx.requestId,
        })
      }
    },
  },
]
