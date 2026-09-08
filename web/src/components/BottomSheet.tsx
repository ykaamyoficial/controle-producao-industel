import { X } from 'lucide-react'
import type { ReactNode } from 'react'

interface BottomSheetProps {
  open: boolean
  title: string
  onClose: () => void
  children: ReactNode
}

export function BottomSheet({ open, title, onClose, children }: BottomSheetProps) {
  if (!open) return null

  return (
    <div className="fixed inset-0 z-50 flex flex-col justify-end">
      <button
        type="button"
        aria-label="Fechar"
        onClick={onClose}
        className="absolute inset-0 bg-slate-950/70"
      />
      <div className="relative max-h-[80svh] overflow-y-auto rounded-t-2xl border-t border-slate-800 bg-slate-900 pb-[env(safe-area-inset-bottom)]">
        <div className="sticky top-0 flex items-center justify-between border-b border-slate-800 bg-slate-900 px-4 py-3">
          <h2 className="text-sm font-semibold text-slate-100">{title}</h2>
          <button type="button" onClick={onClose} className="rounded-full p-1 text-slate-400">
            <X size={20} />
          </button>
        </div>
        <div className="px-4 py-3">{children}</div>
      </div>
    </div>
  )
}
