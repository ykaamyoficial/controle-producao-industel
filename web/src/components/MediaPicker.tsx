import { Camera, Video, X } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'

/**
 * Anexo de evidencia: foto ou video tirados na hora pela camera do celular
 * (ou escolhidos da galeria). `capture="environment"` abre a camera traseira
 * direto quando o navegador suporta; sem esse suporte, cai no seletor normal
 * de arquivos, que tambem funciona.
 */
export function MediaPicker({ file, onChange, label }: { file: File | null; onChange: (file: File | null) => void; label?: string }) {
  const photoInputRef = useRef<HTMLInputElement>(null)
  const videoInputRef = useRef<HTMLInputElement>(null)
  const [previewUrl, setPreviewUrl] = useState<string | null>(null)

  useEffect(() => {
    if (!file) {
      setPreviewUrl(null)
      return
    }
    const url = URL.createObjectURL(file)
    setPreviewUrl(url)
    return () => URL.revokeObjectURL(url)
  }, [file])

  const isVideo = file?.type.startsWith('video/')

  return (
    <div>
      <input
        ref={photoInputRef}
        type="file"
        accept="image/jpeg,image/png,image/webp"
        capture="environment"
        className="hidden"
        onChange={(event) => onChange(event.target.files?.[0] ?? null)}
      />
      <input
        ref={videoInputRef}
        type="file"
        accept="video/mp4,video/quicktime"
        capture="environment"
        className="hidden"
        onChange={(event) => onChange(event.target.files?.[0] ?? null)}
      />
      {previewUrl ? (
        <div className="flex items-center gap-2">
          {isVideo ? (
            <video src={previewUrl} className="h-14 w-14 rounded-lg object-cover" muted />
          ) : (
            <img src={previewUrl} alt="Previa do anexo" className="h-14 w-14 rounded-lg object-cover" />
          )}
          <span className="min-w-0 flex-1 truncate text-xs text-slate-400">{file?.name}</span>
          <button type="button" onClick={() => onChange(null)} className="shrink-0 rounded-full bg-slate-800 p-1.5 text-slate-300">
            <X size={14} />
          </button>
        </div>
      ) : (
        <div className="flex gap-2">
          <button
            type="button"
            onClick={() => photoInputRef.current?.click()}
            className="flex flex-1 items-center justify-center gap-2 rounded-lg border border-dashed border-slate-700 px-3 py-2 text-xs text-slate-400"
          >
            <Camera size={16} />
            Foto
          </button>
          <button
            type="button"
            onClick={() => videoInputRef.current?.click()}
            className="flex flex-1 items-center justify-center gap-2 rounded-lg border border-dashed border-slate-700 px-3 py-2 text-xs text-slate-400"
          >
            <Video size={16} />
            Video
          </button>
        </div>
      )}
      {!previewUrl && label && <p className="mt-1 text-xs text-slate-600">{label}</p>}
    </div>
  )
}
