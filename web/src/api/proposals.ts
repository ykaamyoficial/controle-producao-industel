import { apiFetch, requestIdHeader } from './client'

export interface ProposalListItem {
  id: number
  legacy_id: number | null
  proposal_number: string
  customer_name: string
  project_name: string | null
  order_reference: string | null
  lot: string | null
  proposal_date: string | null
  deadline_date: string | null
  current_area: string | null
  current_status: string | null
  is_partial: boolean
  parent_proposal_id: number | null
  is_cancelled: boolean
  is_completed: boolean
  legacy_updated_at: string | null
  synced_at: string
  version: number
  active: boolean
}

export interface PaginatedProposalResponse {
  items: ProposalListItem[]
  total: number
  limit: number
  offset: number
}

export interface ListProposalsParams {
  proposal_number?: string
  customer?: string
  current_area?: string
  current_status?: string
  is_cancelled?: boolean
  is_completed?: boolean
  limit?: number
  offset?: number
}

export async function listProposals(params: ListProposalsParams = {}): Promise<PaginatedProposalResponse> {
  const query = new URLSearchParams()
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== '') query.set(key, String(value))
  }
  const suffix = query.toString() ? `?${query.toString()}` : ''
  return apiFetch<PaginatedProposalResponse>(`/proposals${suffix}`)
}

/** Libera a proposta de Controle Geral para Producao (AGUARDANDO_LIBERACAO -> LIBERADO_PRODUCAO). */
export async function releaseProposalToProduction(proposalId: number, version: number, reason?: string, requestId?: string) {
  return apiFetch(`/proposals/${proposalId}/status`, {
    method: 'POST',
    headers: requestIdHeader(requestId),
    body: JSON.stringify({ version, to_area: 'PRODUCAO', to_status: 'LIBERADO_PRODUCAO', reason: reason || null }),
  })
}

export async function cancelProposal(proposalId: number, version: number, reason: string, requestId?: string) {
  return apiFetch(`/proposals/${proposalId}/cancel`, {
    method: 'POST',
    headers: requestIdHeader(requestId),
    body: JSON.stringify({ version, reason }),
  })
}
