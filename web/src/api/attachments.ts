import { apiFetch, apiFetchBlob, requestIdHeader } from './client'

export interface ProposalAttachment {
  id: number
  proposal_id: number
  area: string | null
  action_id: string | null
  note: string | null
  request_id: string | null
  original_filename: string
  mime_type: string
  file_size: number
  uploaded_by_name: string | null
  created_at: string
}

export interface ProposalAttachmentList {
  items: ProposalAttachment[]
  total: number
}

export async function listProposalAttachments(proposalId: number) {
  return apiFetch<ProposalAttachmentList>(`/proposals/${proposalId}/attachments`)
}

export async function uploadProposalAttachment(
  proposalId: number,
  file: File,
  options: { area?: string; actionId?: string; note?: string; requestId?: string } = {},
) {
  const form = new FormData()
  form.append('file', file)
  if (options.area) form.append('area', options.area)
  if (options.actionId) form.append('action_id', options.actionId)
  if (options.note) form.append('note', options.note)
  return apiFetch<ProposalAttachment>(`/proposals/${proposalId}/attachments`, {
    method: 'POST',
    headers: requestIdHeader(options.requestId),
    body: form,
  })
}

export async function fetchAttachmentBlob(attachmentId: number): Promise<Blob> {
  return apiFetchBlob(`/proposal-attachments/${attachmentId}/content`)
}
