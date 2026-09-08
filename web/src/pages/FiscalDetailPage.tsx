import { useQuery } from '@tanstack/react-query'
import { ChevronLeft } from 'lucide-react'
import { Link, useParams } from 'react-router-dom'
import { getFiscalRecord } from '../api/fiscal'

function formatDateTime(value: string | null): string {
  if (!value) return '-'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return '-'
  return date.toLocaleString('pt-BR', { day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit' })
}

function formatDate(value: string | null): string {
  if (!value) return '-'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return '-'
  return date.toLocaleDateString('pt-BR')
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <>
      <h2 className="mt-6 text-sm font-semibold uppercase tracking-wide text-slate-400">{title}</h2>
      <div className="mt-2 flex flex-col gap-2">{children}</div>
    </>
  )
}

export function FiscalDetailPage() {
  const { id } = useParams()
  const fiscalId = Number(id)

  const { data: record, isLoading, isError } = useQuery({
    queryKey: ['fiscal-record', fiscalId],
    queryFn: () => getFiscalRecord(fiscalId),
    enabled: Number.isFinite(fiscalId),
  })

  return (
    <div className="flex-1 px-4 pb-24 pt-6">
      <Link to="/fiscal" className="mb-3 inline-flex items-center gap-1 text-sm text-slate-400">
        <ChevronLeft size={16} />
        Fiscal
      </Link>

      {isLoading && <p className="text-sm text-slate-500">Carregando...</p>}
      {isError && <p className="text-sm text-red-400">Nao foi possivel carregar o registro fiscal.</p>}

      {record && (
        <>
          <div className="flex items-start justify-between gap-3">
            <div className="min-w-0">
              <h1 className="truncate text-xl font-semibold text-slate-100">{record.proposal_number}</h1>
              <p className="truncate text-sm text-slate-400">{record.customer_name}</p>
            </div>
            <span className={`shrink-0 text-xs ${record.critical_pending ? 'text-red-400' : 'text-slate-500'}`}>
              {record.fiscal_situation}
            </span>
          </div>

          <dl className="mt-4 grid grid-cols-2 gap-x-4 gap-y-2 rounded-xl border border-slate-800 bg-slate-900 px-4 py-3 text-sm">
            <dt className="text-slate-500">Status fiscal</dt>
            <dd className="text-right text-slate-200">{record.status_fiscal}</dd>
            <dt className="text-slate-500">Entrada fiscal</dt>
            <dd className="text-right text-slate-200">{formatDate(record.entry_date)}</dd>
            <dt className="text-slate-500">Itens</dt>
            <dd className="text-right text-slate-200">
              {record.billed_items}/{record.item_count} faturados
            </dd>
            <dt className="text-slate-500">NF retirada</dt>
            <dd className="text-right text-slate-200">{formatDateTime(record.invoice_withdrawn_at)}</dd>
          </dl>

          <Section title={`Itens (${record.items.length})`}>
            {record.items.length === 0 && <p className="text-sm text-slate-500">Sem itens.</p>}
            {record.items.map((item) => (
              <div key={item.id} className="rounded-lg border border-slate-800 bg-slate-900 px-3 py-2">
                <p className="text-sm text-slate-100">
                  {item.item_number} — {item.description}
                </p>
                <p className="text-xs text-slate-500">
                  Total {item.total_quantity} · Faturado {item.billed_quantity} · Pendente {item.pending_quantity} ·{' '}
                  {item.status}
                </p>
              </div>
            ))}
          </Section>

          <Section title={`Emissoes (${record.invoices.length})`}>
            {record.invoices.length === 0 && <p className="text-sm text-slate-500">Nenhuma nota fiscal emitida.</p>}
            {record.invoices.map((invoice) => (
              <div key={invoice.id} className="rounded-lg border border-slate-800 bg-slate-900 px-3 py-2">
                <p className="text-sm text-slate-100">
                  NF {invoice.invoice_number}
                  {invoice.series && ` / serie ${invoice.series}`}
                </p>
                <p className="text-xs text-slate-500">
                  {formatDateTime(invoice.issued_at)} · {invoice.item_count} itens · {invoice.quantity} un ·{' '}
                  {invoice.weight} kg · {invoice.status}
                </p>
                {invoice.observation && <p className="mt-1 text-xs text-slate-400">{invoice.observation}</p>}
              </div>
            ))}
          </Section>

          <Section title={`Historico fiscal (${record.events.length})`}>
            {record.events.length === 0 && <p className="text-sm text-slate-500">Sem eventos registrados.</p>}
            {record.events.map((event) => (
              <div key={event.id} className="flex gap-3 border-l-2 border-slate-800 pl-3">
                <div className="flex-1">
                  <p className="text-sm text-slate-200">
                    {event.event_type}
                    {event.to_status && ` → ${event.to_status}`}
                  </p>
                  <p className="text-xs text-slate-500">{formatDateTime(event.created_at)}</p>
                </div>
              </div>
            ))}
          </Section>
        </>
      )}
    </div>
  )
}
