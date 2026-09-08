import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { listFiscalRecords, type FiscalRecordSummary } from '../api/fiscal'
import { areasVisibleFor } from '../areas/areaPermissionMap'
import { useAuth } from '../auth/AuthContext'
import { FISCAL_BATCH_ACTIONS } from '../batchActions/fiscal'
import type { BatchActionDefinition } from '../batchActions/types'
import { ActionLauncherFab } from '../components/ActionLauncherFab'
import { AreaActionMenuSheet } from '../components/AreaActionMenuSheet'
import { ProposalPickerSheet } from '../components/ProposalPickerSheet'
import { StandardCard } from '../components/StandardCard'
import { classifyStatus, StatusBadge } from '../components/StatusBadge'

function FiscalCard({ record }: { record: FiscalRecordSummary }) {
  const tone = record.critical_pending ? 'critical' : classifyStatus(record.fiscal_situation)
  return (
    <StandardCard
      primaryLeft={record.customer_name}
      primaryRight={record.proposal_number}
      status={<StatusBadge status={record.fiscal_situation} tone={tone} />}
      itemsLabel={
        <>
          {record.billed_items}/{record.item_count} itens faturados
          {record.older_than_7_days && <span className="ml-2 text-amber-400">+7 dias sem emissao</span>}
        </>
      }
      href={`/fiscal/${record.id}`}
      accentTone={tone}
    />
  )
}

export function FiscalAreaPage() {
  const { user } = useAuth()
  const visible = areasVisibleFor(user?.permissions ?? []).some((area) => area.key === 'fiscal')

  const { data, isLoading, isError } = useQuery({
    queryKey: ['fiscal-records'],
    queryFn: () => listFiscalRecords({ limit: 50 }),
    enabled: visible,
  })

  const [menuOpen, setMenuOpen] = useState(false)
  const [activeAction, setActiveAction] = useState<BatchActionDefinition | null>(null)

  if (!visible) {
    return (
      <div className="flex-1 px-4 pb-20 pt-6">
        <p className="text-sm text-slate-400">Voce nao tem permissao para acessar Fiscal.</p>
      </div>
    )
  }

  return (
    <div className="flex-1 px-4 pb-24 pt-6">
      <h1 className="text-xl font-semibold text-slate-100">Fiscal</h1>

      <div className="mt-4 flex flex-col gap-3">
        {isLoading && <p className="text-sm text-slate-500">Carregando...</p>}
        {isError && <p className="text-sm text-red-400">Nao foi possivel carregar o fiscal.</p>}
        {data && data.items.length === 0 && <p className="text-sm text-slate-500">Nenhum registro fiscal.</p>}
        {data?.items.map((record) => (
          <FiscalCard key={record.id} record={record} />
        ))}
      </div>

      <ActionLauncherFab onClick={() => setMenuOpen(true)} />

      <AreaActionMenuSheet
        open={menuOpen}
        title="Acoes em Fiscal"
        actions={FISCAL_BATCH_ACTIONS}
        onSelect={(action) => {
          setMenuOpen(false)
          setActiveAction(action)
        }}
        onClose={() => setMenuOpen(false)}
      />

      <ProposalPickerSheet
        action={activeAction}
        onClose={() => setActiveAction(null)}
        invalidateQueryKeys={[['fiscal-records']]}
      />
    </div>
  )
}
