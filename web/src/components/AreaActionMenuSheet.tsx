import type { BatchActionDefinition } from '../batchActions/types'
import { BottomSheet } from './BottomSheet'

export function AreaActionMenuSheet({
  open,
  title,
  actions,
  onSelect,
  onClose,
}: {
  open: boolean
  title: string
  actions: BatchActionDefinition[]
  onSelect: (action: BatchActionDefinition) => void
  onClose: () => void
}) {
  return (
    <BottomSheet open={open} title={title} onClose={onClose}>
      {actions.length === 0 ? (
        <p className="py-4 text-sm text-slate-500">Nenhuma acao disponivel para o seu usuario nesta area.</p>
      ) : (
        <div className="flex flex-col gap-2 py-1">
          {actions.map((action) => (
            <button
              key={action.id}
              type="button"
              onClick={() => onSelect(action)}
              className="rounded-lg border border-slate-800 px-4 py-3 text-left text-sm text-slate-100 active:bg-slate-800"
            >
              {action.label}
            </button>
          ))}
        </div>
      )}
    </BottomSheet>
  )
}
