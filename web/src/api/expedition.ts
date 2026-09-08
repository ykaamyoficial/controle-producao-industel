import { apiFetch, requestIdHeader } from './client'

export interface ExpeditionAction {
  id: string
  label: string
  enabled: boolean
  reason: string | null
}

export interface ExpeditionProposalSummary {
  id: number
  proposal_number: string
  customer_name: string
  shipping_status: string | null
  general_status: string | null
  version: number
  item_count: number
  available_quantity: string
  separated_quantity: string
  delivered_quantity: string
  pending_quantity: string
  actions: ExpeditionAction[]
}

export interface PaginatedExpeditionResponse {
  items: ExpeditionProposalSummary[]
  total: number
  limit: number
  offset: number
}

export async function listExpeditionProposals(params: { search?: string; limit?: number } = {}) {
  const query = new URLSearchParams()
  if (params.search) query.set('search', params.search)
  query.set('limit', String(params.limit ?? 50))
  return apiFetch<PaginatedExpeditionResponse>(`/shipping/proposals?${query.toString()}`)
}

export async function startExpeditionSeparation(proposalId: number, version: number, observation?: string, requestId?: string) {
  return apiFetch(`/shipping/proposals/${proposalId}/start-separation`, {
    method: 'POST',
    headers: requestIdHeader(requestId),
    body: JSON.stringify({ version, observation: observation || null }),
  })
}

/** items omitido = registra automaticamente todo o saldo pendente. */
export async function separateExpeditionItems(proposalId: number, version: number, observation?: string, requestId?: string) {
  return apiFetch(`/shipping/proposals/${proposalId}/separate-items`, {
    method: 'POST',
    headers: requestIdHeader(requestId),
    body: JSON.stringify({ version, items: null, observation: observation || null }),
  })
}

/** items omitido = entrega automaticamente todo o saldo ja separado. */
export async function deliverExpeditionItems(proposalId: number, version: number, observation?: string, requestId?: string) {
  return apiFetch(`/shipping/proposals/${proposalId}/deliver-items`, {
    method: 'POST',
    headers: requestIdHeader(requestId),
    body: JSON.stringify({ version, items: null, observation: observation || null }),
  })
}

