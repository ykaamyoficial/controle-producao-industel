import { apiFetch, requestIdHeader } from './client'

export interface GalvanizationLoadSummary {
  id: number
  code: string | null
  driver_name: string
  max_weight: string | null
  load_weight: string | null
  total_weight: string
  status: string
  expected_return_date: string | null
  sent_at: string | null
  closed_at: string | null
  version: number
}

export interface PaginatedGalvanizationLoadResponse {
  items: GalvanizationLoadSummary[]
  total: number
  limit: number
  offset: number
}

const RELEASABLE_STATUSES = new Set(['AGUARDANDO_LIBERACAO'])
const RETURNABLE_STATUSES = new Set(['LIBERADA_PARA_ENVIO', 'RETORNO_PARCIAL'])
const CLOSABLE_STATUSES = new Set(['RETORNADA_GALVANIZACAO'])

export type GalvanizationTransitionKind = 'release' | 'return' | 'close'

export function nextGalvanizationTransition(
  status: string,
  closedAt: string | null,
): { kind: GalvanizationTransitionKind; label: string } | null {
  if (closedAt) return null
  if (RELEASABLE_STATUSES.has(status)) return { kind: 'release', label: 'Liberar para envio' }
  if (RETURNABLE_STATUSES.has(status)) return { kind: 'return', label: 'Registrar retorno' }
  if (CLOSABLE_STATUSES.has(status)) return { kind: 'close', label: 'Encerrar carga' }
  return null
}

export interface GalvanizationCandidateItem {
  proposal_id: number
  proposal_number: string
  customer_name: string
  project_name: string | null
  current_status: string | null
  item_id: number
  item_number: string
  product_code: string | null
  description: string
  quantity: string
  available_quantity: string
  unit_weight: string | null
  situation: 'DISPONIVEL' | 'EM_GALVANIZACAO'
  version: number
}

export interface PaginatedGalvanizationCandidateResponse {
  items: GalvanizationCandidateItem[]
  total: number
  limit: number
  offset: number
}

export interface CreateGalvanizationLoadItem {
  proposalItemId: number
  version: number
}

/** sent_quantity omitido = envia todo o saldo disponivel do item. */
export async function createGalvanizationLoad(
  driverName: string,
  items: CreateGalvanizationLoadItem[],
  notes?: string,
  requestId?: string,
) {
  return apiFetch<GalvanizationLoadDetail>('/galvanization/loads', {
    method: 'POST',
    headers: requestIdHeader(requestId),
    body: JSON.stringify({
      driver_name: driverName,
      notes: notes || null,
      items: items.map((item) => ({ proposal_item_id: item.proposalItemId, version: item.version })),
    }),
  })
}

export async function listGalvanizationCandidates(params: { search?: string; limit?: number } = {}) {
  const query = new URLSearchParams()
  if (params.search) query.set('search', params.search)
  query.set('limit', String(params.limit ?? 100))
  return apiFetch<PaginatedGalvanizationCandidateResponse>(`/galvanization/candidates?${query.toString()}`)
}

export interface GalvanizationLoadProposalSummary {
  proposal_id: number
  proposal_number: string
  customer_name: string
  pending_item_count: number
}

export interface GalvanizationLoadItemSummary {
  id: number
  proposal_item_id: number
  proposal_id: number
  proposal_number: string
  item_number: string
  description: string
  sent_quantity: string
  version: number
}

export interface GalvanizationLoadDetail extends GalvanizationLoadSummary {
  proposals: GalvanizationLoadProposalSummary[]
  items: GalvanizationLoadItemSummary[]
}

export async function getGalvanizationLoad(loadId: number) {
  return apiFetch<GalvanizationLoadDetail>(`/galvanization/loads/${loadId}`)
}

/**
 * Adiciona itens a uma carga ainda aberta (AGUARDANDO_LIBERACAO), preservando
 * os itens ja existentes - o endpoint de update substitui a lista inteira,
 * entao reenviamos os atuais junto dos novos.
 */
export async function addItemsToGalvanizationLoad(
  loadId: number,
  loadVersion: number,
  existingItems: GalvanizationLoadItemSummary[],
  newItems: CreateGalvanizationLoadItem[],
  notes?: string,
  requestId?: string,
) {
  const items = [
    // Sem `version`: o campo se refere a versao do ProposalItem (nao do
    // GalvanizationLoadItem, que e o que temos aqui) - omitir pula a checagem
    // de conflito para os itens que ja estavam na carga e nao mudaram.
    ...existingItems.map((item) => ({
      proposal_item_id: item.proposal_item_id,
      sent_quantity: item.sent_quantity,
    })),
    ...newItems.map((item) => ({ proposal_item_id: item.proposalItemId, version: item.version })),
  ]
  return apiFetch<GalvanizationLoadDetail>(`/galvanization/loads/${loadId}`, {
    method: 'PATCH',
    headers: requestIdHeader(requestId),
    body: JSON.stringify({ version: loadVersion, notes: notes || null, items }),
  })
}

export async function listGalvanizationLoads(params: { status?: string; search?: string; limit?: number } = {}) {
  const query = new URLSearchParams()
  if (params.status) query.set('status', params.status)
  if (params.search) query.set('search', params.search)
  query.set('limit', String(params.limit ?? 50))
  return apiFetch<PaginatedGalvanizationLoadResponse>(`/galvanization/loads?${query.toString()}`)
}

export async function releaseGalvanizationLoad(loadId: number, version: number, observation?: string, requestId?: string) {
  return apiFetch(`/galvanization/loads/${loadId}/release`, {
    method: 'POST',
    headers: requestIdHeader(requestId),
    body: JSON.stringify({ version, observation: observation || null }),
  })
}

export async function closeGalvanizationLoad(loadId: number, version: number, observation?: string, requestId?: string) {
  return apiFetch(`/galvanization/loads/${loadId}/close`, {
    method: 'POST',
    headers: requestIdHeader(requestId),
    body: JSON.stringify({ version, observation: observation || null }),
  })
}

/** Registra retorno total: devolve todo o saldo pendente das propostas informadas. */
export async function registerGalvanizationReturn(
  loadId: number,
  version: number,
  proposalIds: number[],
  observation?: string,
  requestId?: string,
) {
  return apiFetch(`/galvanization/loads/${loadId}/returns`, {
    method: 'POST',
    headers: requestIdHeader(requestId),
    body: JSON.stringify({ version, proposal_ids: proposalIds, observation: observation || null }),
  })
}
