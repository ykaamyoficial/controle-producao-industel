import { useQuery } from '@tanstack/react-query'
import { Play } from 'lucide-react'
import { useEffect, useState } from 'react'
import { fetchAttachmentBlob, listProposalAttachments, type ProposalAttachment } from '../api/attachments'

function AttachmentThumbnail({ attachment }: { attachment: ProposalAttachment }) {
  const [url, setUrl] = useState<string | null>(null)
  const isVideo = attachment.mime_type.startsWith('video/')

  useEffect(() => {
    let objectUrl: string | null = null
    let cancelled = false
    fetchAttachmentBlob(attachment.id).then((blob) => {
      if (cancelled) return
      objectUrl = URL.createObjectURL(blob)
      setUrl(objectUrl)
    })
    return () => {
      cancelled = true
      if (objectUrl) URL.revokeObjectURL(objectUrl)
    }
  }, [attachment.id])

  return (
    <a href={url ?? undefined} target="_blank" rel="noreferrer" className="block">
      <div className="relative aspect-square overflow-hidden rounded-lg bg-slate-800">
        {url ? (
          isVideo ? (
            <>
              <video src={url} className="h-full w-full object-cover" muted />
              <div className="absolute inset-0 flex items-center justify-center bg-black/20">
                <Play size={22} className="text-white" fill="white" />
              </div>
            </>
          ) : (
            <img src={url} alt={attachment.note ?? attachment.original_filename} className="h-full w-full object-cover" />
          )
        ) : (
          <div className="h-full w-full animate-pulse" />
        )}
      </div>
      {(attachment.action_id || attachment.note) && (
        <p className="mt-1 truncate text-xs text-slate-500">{attachment.note ?? attachment.action_id}</p>
      )}
    </a>
  )
}

export function AttachmentGallery({ proposalId }: { proposalId: number }) {
  const { data, isLoading } = useQuery({
    queryKey: ['proposal-attachments', proposalId],
    queryFn: () => listProposalAttachments(proposalId),
  })

  if (isLoading) return <p className="text-sm text-slate-500">Carregando anexos...</p>
  if (!data || data.items.length === 0) return <p className="text-sm text-slate-500">Nenhum anexo.</p>

  return (
    <div className="grid grid-cols-3 gap-2">
      {data.items.map((attachment) => (
        <AttachmentThumbnail key={attachment.id} attachment={attachment} />
      ))}
    </div>
  )
}
