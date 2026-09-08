export interface BatchCandidate {
  /** id usado na chamada de execucao (proposal_id, load_id ou fiscal_record_id conforme a acao) */
  id: number
  version: number
  primaryLeft: string
  primaryRight: string
  statusLabel: string
  enabled: boolean
  disabledReason?: string | null
  /** id da proposta para anexar foto - so difere de `id` quando `id` e load/fiscal_record. */
  proposalId: number
}

export interface BatchExecutionContext {
  note: string
  photo: File | null
  requestId: string
}

export interface BatchActionDefinition {
  id: string
  label: string
  /**
   * 'simple' (padrao): ProposalPickerSheet seleciona propostas e executa `execute`
   * em cada uma, em loop, com nota/foto compartilhadas.
   * 'items': a acao depende de itens especificos de cada proposta (ex: definir
   * fluxo, registrar producao) - apos selecionar as propostas, quem abre a tela
   * agregada de itens e a pagina da area, nao o picker. `execute` fica sem uso.
   */
  kind?: 'simple' | 'items'
  /** Usado quando uma area tem abas com contextos diferentes (ex: Galvanizacao
   * Propostas vs Cargas) - filtra quais acoes aparecem em cada aba. */
  scope?: string
  noteRequired?: boolean
  noteLabel?: string
  fetchCandidates: (search: string) => Promise<BatchCandidate[]>
  execute?: (candidate: BatchCandidate, ctx: BatchExecutionContext) => Promise<void>
}
