import { apiFetch, requestIdHeader } from './client'
import type { ProposalListItem } from './proposals'

export interface ProductionProgress {
  total_items: number
  internal_items: number
  produced_items: number
  pending_items: number
  total_weight: string
  produced_weight: string
  pending_weight: string
}

export interface ProductionAction {
  id: string
  label: string
  enabled: boolean
  reason: string | null
}

export interface ProductionProposalListItem extends ProposalListItem {
  production_status: string | null
  general_status: string | null
  progress: ProductionProgress
  actions: ProductionAction[]
}

export interface PaginatedProductionResponse {
  items: ProductionProposalListItem[]
  total: number
  limit: number
  offset: number
}

export interface ProductionItemSummary {
  id: number
  item_number: string
  product_code: string | null
  description: string | null
  quantity: string
  unit: string | null
  produce_internally: 'SIM' | 'NAO' | 'INDEFINIDO'
  requires_galvanization: 'SIM' | 'NAO' | 'INDEFINIDO'
  flow_defined: boolean
  flow_editable: boolean
  flow_lock_reason: string | null
  produced: boolean
  active: boolean
  version: number
}

export interface ProductionProposalDetail {
  id: number
  version: number
  proposal_number: string
  customer_name: string
  items: ProductionItemSummary[]
}

export async function getProductionProposal(proposalId: number) {
  return apiFetch<ProductionProposalDetail>(`/production/proposals/${proposalId}`)
}

export interface ItemFlowUpdate {
  item_id: number
  version: number
  produce_internally?: boolean
  non_production_reason?: string
  requires_galvanization?: boolean
}

export async function updateProductionItemFlow(proposalId: number, version: number, items: ItemFlowUpdate[]) {
  return apiFetch(`/production/proposals/${proposalId}/item-flow`, {
    method: 'PATCH',
    body: JSON.stringify({ version, origin: 'Producao', items }),
  })
}

export async function listProductionProposals(params: { search?: string; limit?: number } = {}) {
  const query = new URLSearchParams()
  if (params.search) query.set('search', params.search)
  query.set('limit', String(params.limit ?? 50))
  return apiFetch<PaginatedProductionResponse>(`/production/proposals?${query.toString()}`)
}

export async function startProduction(proposalId: number, version: number, observation?: string, requestId?: string) {
  return apiFetch(`/production/proposals/${proposalId}/start`, {
    method: 'POST',
    headers: requestIdHeader(requestId),
    body: JSON.stringify({ version, observation: observation || null }),
  })
}

export async function pauseProduction(proposalId: number, version: number, reason: string, requestId?: string) {
  return apiFetch(`/production/proposals/${proposalId}/pause`, {
    method: 'POST',
    headers: requestIdHeader(requestId),
    body: JSON.stringify({ version, reason }),
  })
}

export async function resumeProduction(proposalId: number, version: number, observation?: string, requestId?: string) {
  return apiFetch(`/production/proposals/${proposalId}/resume`, {
    method: 'POST',
    headers: requestIdHeader(requestId),
    body: JSON.stringify({ version, observation: observation || null }),
  })
}

/** item_ids omitido = registra producao de todos os itens internos pendentes. */
export async function completeProductionItems(
  proposalId: number,
  version: number,
  itemIds: number[] | null,
  observation?: string,
  requestId?: string,
) {
  return apiFetch(`/production/proposals/${proposalId}/complete-items`, {
    method: 'POST',
    headers: requestIdHeader(requestId),
    body: JSON.stringify({ version, item_ids: itemIds, observation: observation || null }),
  })
}

