export type StatusTone = 'success' | 'progress' | 'warning' | 'critical' | 'neutral'

const TONE_CLASSES: Record<StatusTone, string> = {
  success: 'text-emerald-400',
  progress: 'text-sky-400',
  warning: 'text-amber-400',
  critical: 'text-red-400',
  neutral: 'text-slate-500',
}

const TONE_PILL_CLASSES: Record<StatusTone, string> = {
  success: 'border-emerald-500/40 bg-emerald-500/10 text-emerald-400',
  progress: 'border-sky-500/40 bg-sky-500/10 text-sky-400',
  warning: 'border-amber-500/40 bg-amber-500/10 text-amber-400',
  critical: 'border-red-500/40 bg-red-500/10 text-red-400',
  neutral: 'border-slate-600/40 bg-slate-500/10 text-slate-400',
}

/**
 * Classifica um status operacional (producao/galvanizacao/expedicao/fiscal/
 * controle geral) por palavras-chave do vocabulario ja usado no backend.
 * Prioridade: critico > sucesso/concluido > atencao > em andamento > neutro.
 */
export function classifyStatus(status: string | null | undefined): StatusTone {
  const value = (status || '').toUpperCase()
  if (!value) return 'neutral'

  if (value.includes('CANCEL') || value.includes('CRITIC') || value.includes('BLOQUE')) {
    return 'critical'
  }
  // Checado antes de "sucesso": um estado parcial/pendente continua exigindo
  // atencao mesmo quando o texto tambem contem uma palavra como FINALIZADO
  // (ex: FINALIZADO_PARCIAL nao e a mesma coisa que FINALIZADO).
  if (
    value.includes('PARCIAL') ||
    value.includes('PARADO') ||
    value.includes('PENDENTE') ||
    value.includes('PENDENCIA') ||
    value.includes('AGUARDANDO') ||
    value.includes('NAO_INICIADO') ||
    value.includes('FALTA')
  ) {
    return 'warning'
  }
  if (
    value.includes('FINALIZADO') ||
    value.includes('ENTREGUE') ||
    value.includes('CONCLU') ||
    value.includes('RETORNADO') ||
    value.includes('RETIRADA') ||
    value.includes('EMITIDA') ||
    value.includes('ENCERRADA') ||
    value.includes('SEPARADO')
  ) {
    return 'success'
  }
  if (
    value.includes('INICIADO') ||
    value.includes('SEPARACAO') ||
    value.includes('LIBERAD') ||
    value.includes('EM_') ||
    value.includes('DISPONIVEL')
  ) {
    return 'progress'
  }
  return 'neutral'
}

export function StatusBadge({
  status,
  tone,
  variant = 'text',
}: {
  status: string
  tone?: StatusTone
  /** 'pill' desenha um badge com borda/fundo (status "rodeado" pela cor) em vez de so texto colorido. */
  variant?: 'text' | 'pill'
}) {
  const resolvedTone = tone ?? classifyStatus(status)
  if (variant === 'pill') {
    return (
      <span
        className={`inline-flex items-center rounded-full border px-2 py-0.5 text-xs font-medium ${TONE_PILL_CLASSES[resolvedTone]}`}
      >
        {status}
      </span>
    )
  }
  return <span className={`text-xs font-medium ${TONE_CLASSES[resolvedTone]}`}>{status}</span>
}
