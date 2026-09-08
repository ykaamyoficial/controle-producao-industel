import { apiFetch, requestIdHeader } from './client'

export interface FiscalAction {
  id: string
  label: string
  enabled: boolean
  reason: string | null
}

export interface FiscalRecordSummary {
  id: number
  proposal_id: number
  proposal_number: string
  customer_name: string
  status_fiscal: string
  fiscal_situation: string
  entry_date: string
  invoice_withdrawn_at: string | null
  version: number
  item_count: number
  pending_items: number
  billed_items: number
  critical_pending: boolean
  older_than_7_days: boolean
  actions: FiscalAction[]
}

export interface PaginatedFiscalResponse {
  items: FiscalRecordSummary[]
  total: number
  limit: number
  offset: number
}

export interface FiscalItemSummary {
  id: number
  item_number: string
  product_code: string | null
  description: string
  total_quantity: string
  billed_quantity: string
  pending_quantity: string
  billed_weight: string
  pending_weight: string | null
  status: string
}

export interface FiscalInvoiceItemSummary {
  id: number
  item_number: string
  description: string
  quantity: string
}

export interface FiscalInvoiceSummary {
  id: number
  invoice_number: string
  series: string | null
  access_key: string | null
  issued_at: string
  emission_type: string
  status: string
  source: string
  observation: string | null
  item_count: number
  quantity: string
  weight: string
  items: FiscalInvoiceItemSummary[]
}

export interface FiscalEventSummary {
  id: number
  event_type: string
  from_status: string | null
  to_status: string | null
  created_at: string
}

export interface FiscalRecordDetail extends FiscalRecordSummary {
  items: FiscalItemSummary[]
  invoices: FiscalInvoiceSummary[]
  events: FiscalEventSummary[]
}

export async function getFiscalRecord(fiscalRecordId: number) {
  return apiFetch<FiscalRecordDetail>(`/fiscal/records/${fiscalRecordId}`)
}

export async function listFiscalRecords(params: { search?: string; limit?: number } = {}) {
  const query = new URLSearchParams()
  if (params.search) query.set('search', params.search)
  query.set('limit', String(params.limit ?? 50))
  return apiFetch<PaginatedFiscalResponse>(`/fiscal/records?${query.toString()}`)
}

export async function markFiscalInvoiceWithdrawn(fiscalRecordId: number, version: number, observation?: string, requestId?: string) {
  return apiFetch(`/fiscal/records/${fiscalRecordId}/withdrawal`, {
    method: 'POST',
    headers: requestIdHeader(requestId),
    body: JSON.stringify({ version, observation: observation || null }),
  })
}
