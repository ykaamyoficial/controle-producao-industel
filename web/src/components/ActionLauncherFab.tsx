import { Zap } from 'lucide-react'

export function ActionLauncherFab({ onClick }: { onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-label="Acoes"
      className="fixed bottom-20 right-4 z-40 flex h-14 w-14 items-center justify-center rounded-full bg-sky-500 text-slate-950 shadow-lg shadow-sky-500/30 active:scale-95"
    >
      <Zap size={24} fill="currentColor" />
    </button>
  )
}
