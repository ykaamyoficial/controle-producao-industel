import { apiFetch } from './client'
import type { ProposalListItem } from './proposals'

export interface ProposalItemSummary {
  id: number
  item_number: string
  product_code: string | null
  description: string | null
  quantity: string
  unit: string | null
  produced: boolean
  galvanized: boolean
  sent_to_galvanization: boolean
  delivered: boolean
  active: boolean
}

export interface ProposalDetail extends ProposalListItem {
  general_status: string | null
  production_status: string | null
  galvanization_status: string | null
  shipping_status: string | null
  warehouse_status: string | null
  flow_situation: string | null
  process_type: string | null
  notes: string | null
  cancellation_reason: string | null
  created_at: string | null
  updated_at: string | null
  items: ProposalItemSummary[]
}

export interface ProposalActivityItem {
  id: number
  proposal_id: number
  event_type: string
  area: string | null
  actor_name: string | null
  headline: string
  item_code: string | null
  correlation_id: string | null
  occurred_at: string
}

export async function getProposal(proposalId: number) {
  return apiFetch<ProposalDetail>(`/proposals/${proposalId}`)
}

export async function getProposalActivities(proposalId: number) {
  return apiFetch<ProposalActivityItem[]>(`/proposals/${proposalId}/activities`)
}
