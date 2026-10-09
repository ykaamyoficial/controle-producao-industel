"""Modelo em memoria do SIMULADOR de remanejamento parcial (prototipo isolado).

Nao importa nada de `app/` nem de `api/` e nao toca em banco: serve so para o Henrique
testar na pratica, antes de implementar, como o remanejamento deveria se comportar quando so
parte dos itens de uma proposta e remanejada (plano em
docs/architecture/REMANEJAMENTO_PARCIAIS_PLANO.md).

Dois modos, para comparar o mesmo cenario:

* HOJE     - como o sistema funciona hoje: a proposta que cede/recebe continua UMA proposta so,
             com a linha do item guardando pecas em estagios diferentes (ex.: 6 prontas + 4 a
             fabricar) e aparecendo em varias listas ao mesmo tempo.
* PROPOSTO - como o plano propoe: cada linha vira "lotes" com uma situacao so, e a proposta se
             divide em filhas (P1, P2...) seguindo a logica de parciais que o sistema ja tem:
             a mae vira referencia, as filhas iguais se juntam e a mae renasce quando tudo
             chega na Expedicao.

Pecas (estagios): A_FABRICAR -> AGUARDANDO (fabricada, esperando carga; so linha galvanizada)
-> EM_CARGA (na galvanizacao, numa carga) -> PRONTA (na Expedicao) -> ENTREGUE.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field

A_FABRICAR = "A_FABRICAR"
AGUARDANDO = "AGUARDANDO"
EM_CARGA = "EM_CARGA"
PRONTA = "PRONTA"
ENTREGUE = "ENTREGUE"
ESTAGIOS = (A_FABRICAR, AGUARDANDO, EM_CARGA, PRONTA, ENTREGUE)
EM_ANDAMENTO = (A_FABRICAR, AGUARDANDO, EM_CARGA)
# Decisao D1 do plano de logistica: ao remanejar, as pecas do destino que vao para a origem
# sao as mais adiantadas primeiro.
ORDEM_TOMADA = (EM_CARGA, AGUARDANDO, A_FABRICAR)

NOME_ESTAGIO = {
    A_FABRICAR: "a fabricar",
    AGUARDANDO: "aguardando carga",
    EM_CARGA: "em carga",
    PRONTA: "prontas",
    ENTREGUE: "entregues",
}

HOJE = "HOJE"
PROPOSTO = "PROPOSTO"

# Grupo = "lugar" de um lote de pecas. Chave: (prioridade, nome, carga).
G_EXPEDICAO = (0, "EXPEDICAO", 0)
G_ENTREGUE = (1, "ENTREGUE", 0)


def g_carga(carga: int) -> tuple:
    return (2, "EM_CARGA", carga)


G_AGUARDANDO = (3, "AGUARDANDO", 0)
G_FABRICAR = (4, "A_FABRICAR", 0)

LUGAR_DO_GRUPO = {
    "EXPEDICAO": "Expedição",
    "ENTREGUE": "Entregue",
    "EM_CARGA": "Galvanização",
    "AGUARDANDO": "Galvanização",
    "A_FABRICAR": "Produção",
}


class ErroSimulacao(Exception):
    """Erro de regra (mensagem ja em portugues, para mostrar ao usuario)."""


@dataclass
class Linha:
    """Uma linha de item (ou um lote dela). `numero` e o numero do item no pedido."""

    id: int
    proposta_id: int
    numero: str
    codigo: str
    descricao: str
    fluxo: str  # "GALVANIZADO" | "SIMPLES"
    pecas: dict = field(default_factory=lambda: {estagio: 0 for estagio in ESTAGIOS})
    cargas: dict = field(default_factory=dict)  # carga -> qtd (soma = pecas[EM_CARGA])
    cedidas: int = 0  # (modo HOJE) pecas prontas que esta linha cedeu
    recebidas: int = 0  # (modo HOJE) pecas prontas que esta linha recebeu

    def total(self) -> int:
        return sum(self.pecas.values())

    def em_andamento(self) -> int:
        return sum(self.pecas[estagio] for estagio in EM_ANDAMENTO)

    def grupos(self) -> list[tuple]:
        """Lugares em que ha pecas desta linha, do mais adiantado para o menos."""
        grupos: list[tuple] = []
        if self.pecas[PRONTA] > 0:
            grupos.append(G_EXPEDICAO)
        elif self.pecas[ENTREGUE] > 0:
            grupos.append(G_ENTREGUE)
        for carga in sorted(self.cargas):
            if self.cargas[carga] > 0:
                grupos.append(g_carga(carga))
        if self.pecas[AGUARDANDO] > 0:
            grupos.append(G_AGUARDANDO)
        if self.pecas[A_FABRICAR] > 0:
            grupos.append(G_FABRICAR)
        return grupos

    def pecas_do_grupo(self, grupo: tuple) -> tuple[dict, dict]:
        """(pecas, cargas) desta linha que pertencem ao grupo."""
        pecas = {estagio: 0 for estagio in ESTAGIOS}
        cargas: dict = {}
        nome = grupo[1]
        if nome == "EXPEDICAO":
            pecas[PRONTA] = self.pecas[PRONTA]
            pecas[ENTREGUE] = self.pecas[ENTREGUE]
        elif nome == "ENTREGUE":
            pecas[ENTREGUE] = self.pecas[ENTREGUE]
        elif nome == "EM_CARGA":
            pecas[EM_CARGA] = self.cargas.get(grupo[2], 0)
            cargas[grupo[2]] = pecas[EM_CARGA]
        elif nome == "AGUARDANDO":
            pecas[AGUARDANDO] = self.pecas[AGUARDANDO]
        elif nome == "A_FABRICAR":
            pecas[A_FABRICAR] = self.pecas[A_FABRICAR]
        return pecas, cargas

    def retirar_grupo(self, grupo: tuple) -> None:
        nome = grupo[1]
        if nome == "EXPEDICAO":
            self.pecas[PRONTA] = 0
            self.pecas[ENTREGUE] = 0
        elif nome == "ENTREGUE":
            self.pecas[ENTREGUE] = 0
        elif nome == "EM_CARGA":
            self.pecas[EM_CARGA] -= self.cargas.pop(grupo[2], 0)
        elif nome == "AGUARDANDO":
            self.pecas[AGUARDANDO] = 0
        elif nome == "A_FABRICAR":
            self.pecas[A_FABRICAR] = 0

    def somar(self, outra: "Linha") -> None:
        for estagio in ESTAGIOS:
            self.pecas[estagio] += outra.pecas[estagio]
        for carga, qtd in outra.cargas.items():
            self.cargas[carga] = self.cargas.get(carga, 0) + qtd
        self.cedidas += outra.cedidas
        self.recebidas += outra.recebidas


@dataclass
class Proposta:
    id: int
    numero: str
    cliente: str
    mae_id: int | None = None
    parcial: int | None = None
    origem: str = "NORMAL"  # NORMAL | PRODUCAO | REMANEJAMENTO
    ativa: bool = True


@dataclass
class Remanejamento:
    codigo: str
    origem_raiz: int
    destino_raiz: int
    origem_numero: str
    destino_numero: str
    item_origem: str
    item_destino: str
    produto: str
    quantidade: int
    tomadas: list = field(default_factory=list)  # (estagio, carga, qtd)


class Estado:
    def __init__(self, modo: str = PROPOSTO):
        self.modo = modo
        self.propostas: dict[int, Proposta] = {}
        self.linhas: dict[int, Linha] = {}
        self.seq = {"proposta": 1, "linha": 1, "carga": 1, "rm": 1}
        self.pedido: dict[tuple[int, str], int] = {}
        self.base_produto: dict[str, int] = {}
        self.remanejamentos: list[Remanejamento] = []
        self.log: list[str] = []
        # Variante para testar: o destino tambem se divide por lugar (uma filha por lugar), em vez de
        # so o que chegou pronto virar filha e o resto continuar na proposta (R-P3 do plano).
        self.destino_por_lugar = False

    # ---- montagem de cenario ------------------------------------------------------------------
    def nova_proposta(self, numero: str, cliente: str, **extra) -> Proposta:
        proposta = Proposta(id=self.seq["proposta"], numero=numero, cliente=cliente, **extra)
        self.seq["proposta"] += 1
        self.propostas[proposta.id] = proposta
        return proposta

    def nova_linha(self, proposta_id: int, numero: str, codigo: str, descricao: str, fluxo: str, pecas: dict, cargas: dict | None = None) -> Linha:
        linha = Linha(id=self.seq["linha"], proposta_id=proposta_id, numero=numero, codigo=codigo, descricao=descricao, fluxo=fluxo)
        self.seq["linha"] += 1
        for estagio, qtd in pecas.items():
            linha.pecas[estagio] = qtd
        linha.cargas = dict(cargas or {})
        self.linhas[linha.id] = linha
        self.seq["carga"] = max(self.seq["carga"], max(linha.cargas, default=0) + 1)
        return linha

    def fechar_cenario(self) -> None:
        """Guarda os totais de referencia da conferencia (pedido por item e pecas por produto)."""
        self.pedido.clear()
        self.base_produto.clear()
        for linha in self.linhas.values():
            raiz = self.raiz_id(linha.proposta_id)
            self.pedido[(raiz, linha.numero)] = self.pedido.get((raiz, linha.numero), 0) + linha.total()
            self.base_produto[linha.codigo] = self.base_produto.get(linha.codigo, 0) + linha.total()

    # ---- consultas ----------------------------------------------------------------------------
    def raiz_id(self, proposta_id: int) -> int:
        proposta = self.propostas[proposta_id]
        return proposta.mae_id or proposta.id

    def linhas_de(self, proposta_id: int) -> list[Linha]:
        return sorted((l for l in self.linhas.values() if l.proposta_id == proposta_id), key=lambda l: (_chave_numero(l.numero), l.id))

    def filhas(self, raiz_id: int, *, ativas: bool = True) -> list[Proposta]:
        filhas = [p for p in self.propostas.values() if p.mae_id == raiz_id and (p.ativa or not ativas)]
        return sorted(filhas, key=lambda p: (p.parcial or 0, p.id))

    def tem_filhas(self, proposta_id: int) -> bool:
        return bool(self.filhas(proposta_id))

    def familia(self, raiz_id: int) -> list[Proposta]:
        raiz = self.propostas[raiz_id]
        return [raiz, *self.filhas(raiz_id)]

    def soma(self, proposta_id: int, estagio: str) -> int:
        return sum(l.pecas[estagio] for l in self.linhas_de(proposta_id))

    def eh_mae_referencia(self, proposta_id: int) -> bool:
        """Mae que so existe como referencia: tem filhas ativas e nenhuma linha propria."""
        return self.tem_filhas(proposta_id) and not self.linhas_de(proposta_id)

    def aparece_em(self, proposta_id: int) -> list[str]:
        """Listas (Producao/Galvanizacao/Expedicao) em que a proposta aparece agora."""
        lugares = []
        if self.soma(proposta_id, A_FABRICAR) > 0:
            lugares.append("Produção")
        if self.soma(proposta_id, AGUARDANDO) + self.soma(proposta_id, EM_CARGA) > 0:
            lugares.append("Galvanização")
        if self.soma(proposta_id, PRONTA) > 0:
            lugares.append("Expedição")
        return lugares

    def visiveis_controle_geral(self) -> list[Proposta]:
        return sorted((p for p in self.propostas.values() if p.ativa and p.mae_id is None), key=lambda p: p.numero)

    def ativas(self) -> list[Proposta]:
        return sorted((p for p in self.propostas.values() if p.ativa), key=lambda p: p.numero)

    def entregue(self, proposta_id: int) -> bool:
        linhas = self.linhas_de(proposta_id)
        if self.eh_mae_referencia(proposta_id):
            return all(self.entregue(f.id) for f in self.filhas(proposta_id))
        return bool(linhas) and all(l.total() == l.pecas[ENTREGUE] for l in linhas)

    def situacao(self, proposta_id: int) -> str:
        proposta = self.propostas[proposta_id]
        if self.eh_mae_referencia(proposta_id):
            if self.entregue(proposta_id):
                return "Entregue (todas as partes)"
            partes = [f"-{f.parcial} {', '.join(self.aparece_em(f.id)) or 'Entregue'}" for f in self.filhas(proposta_id)]
            return "Referência · partes: " + " · ".join(partes)
        if self.entregue(proposta_id):
            return "Entregue"
        partes = []
        for nome, estagio in (("Produção", A_FABRICAR), ("Aguardando carga", AGUARDANDO), ("Em carga", EM_CARGA), ("Expedição", PRONTA)):
            qtd = self.soma(proposta_id, estagio)
            if qtd:
                partes.append(f"{nome} {qtd}")
        texto = " · ".join(partes) if partes else "Sem peças"
        if proposta.mae_id is not None:
            return f"Parte {proposta.parcial} · {texto}"
        return texto

    def cargas_em_transito(self) -> dict[int, int]:
        cargas: dict[int, int] = {}
        for linha in self.linhas.values():
            if not self.propostas[linha.proposta_id].ativa:
                continue
            for carga, qtd in linha.cargas.items():
                cargas[carga] = cargas.get(carga, 0) + qtd
        return dict(sorted(cargas.items()))

    # ---- marca de remanejamento (fase D) -----------------------------------------------------------
    def tem_marca(self, proposta_id: int) -> bool:
        proposta = self.propostas[proposta_id]
        if not proposta.ativa:
            return False
        if self.modo == HOJE:
            return any(
                (l.cedidas > 0 or l.recebidas > 0) and l.em_andamento() > 0
                for l in self.linhas_de(proposta_id)
            )
        raiz = self.raiz_id(proposta_id)
        participou = any(raiz in (rm.origem_raiz, rm.destino_raiz) for rm in self.remanejamentos)
        faz_parte_de_familia = proposta.mae_id is not None or self.tem_filhas(proposta_id)
        return participou and faz_parte_de_familia

    def detalhes_marca(self, proposta_id: int) -> list[str]:
        raiz = self.raiz_id(proposta_id)
        linhas = []
        for rm in self.remanejamentos:
            if rm.origem_raiz == raiz:
                linhas.append(f"{rm.codigo}: cedeu {rm.quantidade} un de {rm.produto} (item {rm.item_origem}) prontas para a {rm.destino_numero}.")
            if rm.destino_raiz == raiz:
                linhas.append(f"{rm.codigo}: recebeu {rm.quantidade} un de {rm.produto} (item {rm.item_destino}) prontas da {rm.origem_numero}.")
        return linhas

    # ---- acoes -------------------------------------------------------------------------------------
    def concluir_producao(self, proposta_id: int, linha_id: int | None = None) -> None:
        proposta = self.propostas[proposta_id]
        todas = [l for l in self.linhas_de(proposta_id) if l.pecas[A_FABRICAR] > 0]
        selecionadas = [l for l in todas if linha_id is None or l.id == linha_id]
        if not selecionadas:
            raise ErroSimulacao("Não há peças a fabricar nesta seleção.")
        for linha in selecionadas:
            qtd = linha.pecas[A_FABRICAR]
            linha.pecas[A_FABRICAR] = 0
            linha.pecas[AGUARDANDO if linha.fluxo == "GALVANIZADO" else PRONTA] += qtd
        faltam = [l for l in todas if l not in selecionadas]
        # Logica de parciais que o sistema ja tem: concluir so parte dos itens (ou concluir quando a
        # proposta ja tem filhas) leva os itens concluidos para uma filha.
        if faltam or self.tem_filhas(proposta_id):
            mae = self._mae_de(proposta)
            filha = self._nova_filha(mae, "PRODUCAO")
            self._mover(selecionadas, filha)
            self._anotar(f"Produção parcial: a {mae.numero} criou a parte {filha.numero} com {self._itens_txt(selecionadas)}.")
        nomes = ", ".join(l.numero for l in selecionadas)
        self._anotar(f"Produção concluída na {proposta.numero} (item {nomes}).")
        self._pos_acao({self.raiz_id(proposta_id)})

    def enviar_carga(self, proposta_ids: list[int]) -> int:
        linhas = [l for pid in proposta_ids for l in self.linhas_de(pid) if l.pecas[AGUARDANDO] > 0]
        if not linhas:
            raise ErroSimulacao("Não há peças aguardando carga nas propostas escolhidas.")
        carga = self.seq["carga"]
        self.seq["carga"] += 1
        raizes = set()
        total = 0
        for linha in linhas:
            qtd = linha.pecas[AGUARDANDO]
            linha.pecas[AGUARDANDO] = 0
            linha.pecas[EM_CARGA] += qtd
            linha.cargas[carga] = linha.cargas.get(carga, 0) + qtd
            raizes.add(self.raiz_id(linha.proposta_id))
            total += qtd
        self._anotar(f"Carga {carga} enviada para a galvanização com {total} un.")
        self._pos_acao(raizes)
        return carga

    def retornar_carga(self, carga: int) -> None:
        linhas = [l for l in self.linhas.values() if self.propostas[l.proposta_id].ativa and l.cargas.get(carga, 0) > 0]
        if not linhas:
            raise ErroSimulacao("Essa carga não tem peças na galvanização.")
        raizes = set()
        total = 0
        for linha in linhas:
            qtd = linha.cargas.pop(carga)
            linha.pecas[EM_CARGA] -= qtd
            linha.pecas[PRONTA] += qtd
            raizes.add(self.raiz_id(linha.proposta_id))
            total += qtd
        self._anotar(f"Carga {carga} voltou da galvanização: {total} un ficaram prontas na Expedição.")
        self._pos_acao(raizes)

    def entregar(self, proposta_id: int, linha_id: int | None = None) -> None:
        linhas = [l for l in self.linhas_de(proposta_id) if l.pecas[PRONTA] > 0 and (linha_id is None or l.id == linha_id)]
        if not linhas:
            raise ErroSimulacao("Não há peças prontas na Expedição nesta seleção.")
        total = 0
        for linha in linhas:
            total += linha.pecas[PRONTA]
            linha.pecas[ENTREGUE] += linha.pecas[PRONTA]
            linha.pecas[PRONTA] = 0
        self._anotar(f"Entrega registrada na {self.propostas[proposta_id].numero}: {total} un.")
        self._pos_acao({self.raiz_id(proposta_id)})

    # ---- remanejamento ------------------------------------------------------------------------------
    def candidatas_origem(self, destino_linha_id: int) -> list[Linha]:
        """Linhas de OUTRAS familias, do mesmo produto, com pecas prontas na Expedicao."""
        destino = self.linhas[destino_linha_id]
        raiz = self.raiz_id(destino.proposta_id)
        return [
            l for l in sorted(self.linhas.values(), key=lambda l: l.id)
            if self.propostas[l.proposta_id].ativa and l.codigo == destino.codigo and l.pecas[PRONTA] > 0 and self.raiz_id(l.proposta_id) != raiz
        ]

    def plano_tomada(self, destino: Linha, qtd: int) -> list[tuple[str, int, int]]:
        """Quais pecas em andamento do destino passam para a origem (as mais adiantadas primeiro)."""
        falta = qtd
        plano: list[tuple[str, int, int]] = []
        for estagio in ORDEM_TOMADA:
            if estagio == EM_CARGA:
                for carga in sorted(destino.cargas):
                    tomar = min(falta, destino.cargas[carga])
                    if tomar > 0:
                        plano.append((EM_CARGA, carga, tomar))
                        falta -= tomar
            else:
                tomar = min(falta, destino.pecas[estagio])
                if tomar > 0:
                    plano.append((estagio, 0, tomar))
                    falta -= tomar
        return plano

    def remanejar(self, destino_linha_id: int, origem_linha_id: int, qtd: int) -> None:
        self.remanejar_lote([(destino_linha_id, origem_linha_id, qtd)])

    def remanejar_lote(self, operacoes: list[tuple[int, int, int]]) -> None:
        """Varias linhas de uma vez (como o assistente real): troca as pecas de cada uma e so depois
        reorganiza as propostas. Se qualquer linha for invalida, nada muda."""
        if not operacoes:
            raise ErroSimulacao("Escolha pelo menos um item para remanejar.")
        backup = self.copia()
        try:
            origens: list[int] = []
            destinos: list[int] = []
            for destino_linha_id, origem_linha_id, qtd in operacoes:
                p_origem, p_destino = self._trocar_pecas(destino_linha_id, origem_linha_id, qtd)
                origens.append(p_origem)
                destinos.append(p_destino)
            raizes = {self.raiz_id(p) for p in (*origens, *destinos)}
            if self.modo == PROPOSTO:
                for proposta_id in dict.fromkeys(origens):
                    self._juntar_linhas_iguais(proposta_id)
                    self._dividir_origem(proposta_id)
                for proposta_id in dict.fromkeys(destinos):
                    self._juntar_linhas_iguais(proposta_id)
                    self._dividir_destino(proposta_id)
            else:
                for proposta_id in dict.fromkeys((*origens, *destinos)):
                    self._anotar(f"A {self.propostas[proposta_id].numero} continua uma proposta só: {self.situacao(proposta_id)}.")
            self._pos_acao(raizes)
        except ErroSimulacao:
            self.__dict__.update(backup.__dict__)
            raise

    def _trocar_pecas(self, destino_linha_id: int, origem_linha_id: int, qtd: int) -> tuple[int, int]:
        destino = self.linhas.get(destino_linha_id)
        origem = self.linhas.get(origem_linha_id)
        if destino is None or origem is None:
            raise ErroSimulacao("Escolha o item que recebe e o item de onde vem o material.")
        p_destino, p_origem = self.propostas[destino.proposta_id], self.propostas[origem.proposta_id]
        if self.raiz_id(p_destino.id) == self.raiz_id(p_origem.id):
            raise ErroSimulacao("Origem e destino precisam ser propostas diferentes (e de famílias diferentes).")
        if destino.codigo != origem.codigo:
            raise ErroSimulacao("Os itens precisam ter o mesmo código de produto.")
        if qtd < 1:
            raise ErroSimulacao("A quantidade precisa ser maior que zero.")
        if qtd > origem.pecas[PRONTA]:
            raise ErroSimulacao(f"A origem só tem {origem.pecas[PRONTA]} un prontas na Expedição.")
        if qtd > destino.em_andamento():
            raise ErroSimulacao(f"O destino só tem {destino.em_andamento()} un em andamento para dar em troca.")
        tomadas = self.plano_tomada(destino, qtd)
        codigo = f"RM-{self.seq['rm']:03d}"
        self.seq["rm"] += 1
        self.remanejamentos.append(Remanejamento(
            codigo=codigo, origem_raiz=self.raiz_id(p_origem.id), destino_raiz=self.raiz_id(p_destino.id),
            origem_numero=p_origem.numero, destino_numero=p_destino.numero, item_origem=origem.numero,
            item_destino=destino.numero, produto=origem.codigo, quantidade=qtd, tomadas=list(tomadas),
        ))
        em_troca = ", ".join(f"{n} un {NOME_ESTAGIO[e]}" + (f" (carga {c})" if e == EM_CARGA else "") for e, c, n in tomadas)
        self._anotar(f"{codigo}: a {p_destino.numero} recebeu {qtd} un de {origem.codigo} prontas da {p_origem.numero}; em troca a {p_origem.numero} ficou com {em_troca} que eram da {p_destino.numero}.")
        if self.modo == HOJE:
            for estagio, carga, n in tomadas:
                destino.pecas[estagio] -= n
                if estagio == EM_CARGA:
                    destino.cargas[carga] -= n
                    if destino.cargas[carga] == 0:
                        del destino.cargas[carga]
                origem.pecas[estagio] += n
                if estagio == EM_CARGA:
                    origem.cargas[carga] = origem.cargas.get(carga, 0) + n
            destino.pecas[PRONTA] += qtd
            destino.recebidas += qtd
            origem.pecas[PRONTA] -= qtd
            origem.cedidas += qtd
        else:
            # Lotes fisicos: cada lote vira uma linha com uma situacao so, com o numero do item do
            # pedido a que serve.
            origem.pecas[PRONTA] -= qtd
            self.nova_linha(p_destino.id, destino.numero, destino.codigo, destino.descricao, destino.fluxo, {PRONTA: qtd})
            for estagio, carga, n in tomadas:
                destino.pecas[estagio] -= n
                if estagio == EM_CARGA:
                    destino.cargas[carga] -= n
                    if destino.cargas[carga] == 0:
                        del destino.cargas[carga]
                self.nova_linha(p_origem.id, origem.numero, origem.codigo, origem.descricao, origem.fluxo, {estagio: n}, {carga: n} if estagio == EM_CARGA else None)
            for linha in (origem, destino):
                if linha.total() == 0:
                    del self.linhas[linha.id]
        return p_origem.id, p_destino.id

    # ---- familias (parciais) ------------------------------------------------------------------------
    def _mae_de(self, proposta: Proposta) -> Proposta:
        return self.propostas[proposta.mae_id] if proposta.mae_id else proposta

    def _nova_filha(self, mae: Proposta, origem: str) -> Proposta:
        usados = [p.parcial or 0 for p in self.propostas.values() if p.mae_id == mae.id]
        numero = max(usados, default=0) + 1
        return self.nova_proposta(f"{mae.numero}-{numero}", mae.cliente, mae_id=mae.id, parcial=numero, origem=origem)

    def _mover(self, linhas: list[Linha], proposta: Proposta) -> None:
        for linha in linhas:
            linha.proposta_id = proposta.id

    def _itens_txt(self, linhas: list[Linha]) -> str:
        numeros = sorted({l.numero for l in linhas}, key=_chave_numero)
        return ("o item " if len(numeros) == 1 else "os itens ") + ", ".join(numeros)

    def _partir_linhas(self, proposta_id: int) -> None:
        """Divide cada linha mista em lotes de uma situacao so (um por grupo)."""
        for linha in list(self.linhas_de(proposta_id)):
            grupos = linha.grupos()
            for grupo in grupos[1:]:
                pecas, cargas = linha.pecas_do_grupo(grupo)
                novo = Linha(id=self.seq["linha"], proposta_id=proposta_id, numero=linha.numero, codigo=linha.codigo, descricao=linha.descricao, fluxo=linha.fluxo, pecas=pecas, cargas=cargas)
                self.seq["linha"] += 1
                self.linhas[novo.id] = novo
                linha.retirar_grupo(grupo)

    def _juntar_linhas_iguais(self, proposta_id: int) -> None:
        """Duas linhas com o mesmo numero de item na mesma proposta e no mesmo lugar viram uma so."""
        vistas: dict[tuple, Linha] = {}
        for linha in self.linhas_de(proposta_id):
            chave = (linha.numero, tuple(linha.grupos()))
            if chave in vistas:
                vistas[chave].somar(linha)
                del self.linhas[linha.id]
            else:
                vistas[chave] = linha

    def _grupos_da(self, proposta_id: int) -> dict[tuple, list[Linha]]:
        grupos: dict[tuple, list[Linha]] = {}
        for linha in self.linhas_de(proposta_id):
            for grupo in linha.grupos():
                grupos.setdefault(grupo, []).append(linha)
        return dict(sorted(grupos.items()))

    def _dividir_origem(self, proposta_id: int) -> None:
        """Origem: uma filha por lugar. A mae vira referencia (R-P1/R-P2)."""
        proposta = self.propostas[proposta_id]
        self._partir_linhas(proposta_id)
        grupos = self._grupos_da(proposta_id)
        if len(grupos) <= 1:
            return
        mae = self._mae_de(proposta)
        chaves = list(grupos)
        novas = []
        for chave in (chaves if proposta.mae_id is None else chaves[1:]):
            filha = self._nova_filha(mae, "REMANEJAMENTO")
            self._mover(grupos[chave], filha)
            novas.append(filha)
        self._juntar_linhas_iguais(proposta_id)
        for filha in novas:
            self._juntar_linhas_iguais(filha.id)
        partes = "; ".join(f"{f.numero} ({', '.join(self.aparece_em(f.id)) or 'Entregue'}, {self._itens_txt(self.linhas_de(f.id))})" for f in self.filhas(mae.id) if self.linhas_de(f.id))
        self._anotar(f"A {mae.numero} foi dividida em partes (lógica de parciais): {partes}.")

    def _dividir_destino(self, proposta_id: int) -> None:
        """Destino: so o que chegou pronto vira filha na Expedicao; o resto continua na proposta (R-P3)."""
        if self.destino_por_lugar:
            self._dividir_origem(proposta_id)
            return
        proposta = self.propostas[proposta_id]
        prontas = [l for l in self.linhas_de(proposta_id) if l.pecas[PRONTA] > 0 and l.em_andamento() == 0]
        outras = [l for l in self.linhas_de(proposta_id) if l not in prontas]
        if not prontas or not outras:
            return
        mae = self._mae_de(proposta)
        filha = self._nova_filha(mae, "REMANEJAMENTO")
        self._mover(prontas, filha)
        self._juntar_linhas_iguais(filha.id)
        self._anotar(f"A {proposta.numero} recebeu material pronto: {filha.numero} ({self._itens_txt(prontas)}) vai para a Expedição e o resto continua na {proposta.numero}.")

    def _realinhar_filha(self, filha: Proposta) -> None:
        """Depois de uma acao, uma filha que ficou com linhas em lugares diferentes se divide de novo."""
        self._partir_linhas(filha.id)
        grupos = self._grupos_da(filha.id)
        if len(grupos) <= 1:
            return
        mae = self._mae_de(filha)
        for chave in list(grupos)[1:]:
            nova = self._nova_filha(mae, filha.origem)
            self._mover(grupos[chave], nova)
        self._juntar_linhas_iguais(filha.id)

    def _chave_filha(self, filha: Proposta) -> tuple:
        return tuple(self._grupos_da(filha.id))

    def _unir_filhas_iguais(self, raiz_id: int) -> None:
        grupos: dict[tuple, list[Proposta]] = {}
        for filha in self.filhas(raiz_id):
            grupos.setdefault(self._chave_filha(filha), []).append(filha)
        for chave, filhas in grupos.items():
            if len(filhas) < 2 or not chave:
                continue
            sobrevivente, resto = filhas[0], filhas[1:]
            for filha in resto:
                self._mover(self.linhas_de(filha.id), sobrevivente)
                filha.ativa = False
            self._juntar_linhas_iguais(sobrevivente.id)
            nomes = ", ".join(f.numero for f in resto)
            self._anotar(f"{nomes} e {sobrevivente.numero} estavam no mesmo lugar e se juntaram em {sobrevivente.numero}.")

    def _renascer(self, raiz_id: int) -> None:
        mae = self.propostas[raiz_id]
        filhas = self.filhas(raiz_id)
        if not filhas:
            return
        todas = [*filhas, mae]
        grupos = {g for p in todas for g in self._grupos_da(p.id)}
        if grupos != {G_EXPEDICAO}:
            return
        for filha in filhas:
            self._mover(self.linhas_de(filha.id), mae)
            filha.ativa = False
        self._juntar_linhas_iguais(mae.id)
        self._anotar(f"Tudo chegou na Expedição: a {mae.numero} voltou a ser uma proposta só (as partes se juntaram).")

    def _pos_acao(self, raizes: set[int]) -> None:
        for raiz in sorted(raizes):
            if self.modo == PROPOSTO:
                for filha in self.filhas(raiz):
                    self._realinhar_filha(filha)
            self._unir_filhas_iguais(raiz)
            self._renascer(raiz)

    def _anotar(self, texto: str) -> None:
        self.log.append(texto)

    # ---- descricao e conferencia ---------------------------------------------------------------------
    def descrever_familia(self, raiz_id: int) -> list[str]:
        """Frase por proposta ativa da familia: onde ela esta e com quais itens."""
        frases = []
        for proposta in self.familia(raiz_id):
            if not proposta.ativa:
                continue
            if self.eh_mae_referencia(proposta.id):
                frases.append(f"{proposta.numero}: só referência no Controle Geral (as partes abaixo seguem sozinhas)")
                continue
            linhas = self.linhas_de(proposta.id)
            if not linhas:
                continue
            lugares = self.aparece_em(proposta.id)
            onde = " e ".join(lugares) if lugares else "Entregue"
            aviso = " (aparece nas duas listas ao mesmo tempo)" if len(lugares) > 1 else ""
            frases.append(f"{proposta.numero}: {onde}{aviso} — {self._itens_txt(linhas)} ({self._pecas_txt(proposta.id)})")
        return frases

    def _pecas_txt(self, proposta_id: int) -> str:
        partes = [f"{self.soma(proposta_id, e)} un {NOME_ESTAGIO[e]}" for e in (PRONTA, EM_CARGA, AGUARDANDO, A_FABRICAR, ENTREGUE) if self.soma(proposta_id, e)]
        return ", ".join(partes) or "sem peças"

    def conferir(self) -> list[str]:
        """Problemas encontrados (lista vazia = nenhuma peca nasceu ou sumiu e o pedido nao mudou)."""
        problemas = []
        por_produto: dict[str, int] = {}
        por_item: dict[tuple[int, str], int] = {}
        for linha in self.linhas.values():
            if linha.total() < 0 or any(v < 0 for v in linha.pecas.values()):
                problemas.append(f"Linha {linha.numero} da {self.propostas[linha.proposta_id].numero} ficou com quantidade negativa.")
            if sum(linha.cargas.values()) != linha.pecas[EM_CARGA]:
                problemas.append(f"Cargas da linha {linha.numero} da {self.propostas[linha.proposta_id].numero} não batem com as peças em carga.")
            por_produto[linha.codigo] = por_produto.get(linha.codigo, 0) + linha.total()
            chave = (self.raiz_id(linha.proposta_id), linha.numero)
            por_item[chave] = por_item.get(chave, 0) + linha.total()
        for codigo, base in self.base_produto.items():
            if por_produto.get(codigo, 0) != base:
                problemas.append(f"Produto {codigo}: eram {base} peças e agora são {por_produto.get(codigo, 0)}.")
        for chave, base in self.pedido.items():
            if por_item.get(chave, 0) != base:
                raiz = self.propostas[chave[0]].numero
                problemas.append(f"Item {chave[1]} da {raiz}: o pedido era {base} e agora soma {por_item.get(chave, 0)}.")
        for proposta in self.propostas.values():
            if not proposta.ativa:
                if self.linhas_de(proposta.id):
                    problemas.append(f"A {proposta.numero} está desativada mas ainda tem linhas.")
                continue
            numeros = [l.numero for l in self.linhas_de(proposta.id)]
            if len(numeros) != len(set(numeros)):
                problemas.append(f"A {proposta.numero} tem dois itens com o mesmo número.")
        return problemas

    def copia(self) -> "Estado":
        return copy.deepcopy(self)


def _chave_numero(numero: str):
    try:
        return (0, int(numero))
    except ValueError:
        return (1, numero)


# ---- cenarios prontos -----------------------------------------------------------------------------------
CENARIOS = {
    "1": "Itens inteiros (como a CP 05493 e a CP 05640)",
    "2": "Parte da quantidade (4 de 10) e peças em lugares diferentes",
    "3": "Cedeu tudo",
    "4": "Livre (várias propostas para você testar)",
}


def montar_cenario(chave: str, modo: str = PROPOSTO) -> Estado:
    estado = Estado(modo)
    G, S = "GALVANIZADO", "SIMPLES"
    if chave == "1":
        origem = estado.nova_proposta("CP 05493", "Torres Norte Telecom")
        destino = estado.nova_proposta("CP 05640", "Rede Sul Energia")
        for numero, codigo, descricao, qtd in (("1", "450.400", "Quadro de comando", 2), ("2", "450.398", "Suporte lateral", 1), ("3", "450.830", "Base de fixação", 1), ("4", "450.3", "Cantoneira", 1)):
            estado.nova_linha(origem.id, numero, codigo, descricao, G, {PRONTA: qtd})
            estado.nova_linha(destino.id, numero, codigo, descricao, G, {A_FABRICAR: qtd})
    elif chave == "2":
        origem = estado.nova_proposta("CP 05700", "Vale Verde Transmissão")
        segunda = estado.nova_proposta("CP 05720", "Conecta Infra")
        destino = estado.nova_proposta("CP 05710", "Atlas Estruturas")
        estado.nova_linha(origem.id, "1", "450.400", "Quadro de comando", G, {PRONTA: 10})
        estado.nova_linha(origem.id, "2", "450.8", "Painel frontal", G, {PRONTA: 4})
        estado.nova_linha(segunda.id, "1", "450.400", "Quadro de comando", G, {PRONTA: 6})
        # Linha mista de proposito: 4 em carga (carga 1), 3 aguardando carga e 3 a fabricar.
        estado.nova_linha(destino.id, "1", "450.400", "Quadro de comando", G, {EM_CARGA: 4, AGUARDANDO: 3, A_FABRICAR: 3}, {1: 4})
        estado.nova_linha(destino.id, "2", "450.8", "Painel frontal", G, {A_FABRICAR: 4})
    elif chave == "3":
        origem = estado.nova_proposta("CP 05800", "Torres Norte Telecom")
        destino = estado.nova_proposta("CP 05810", "Rede Sul Energia")
        for numero, codigo, descricao, qtd in (("1", "450.7", "Travessa", 3), ("2", "450.32", "Abraçadeira", 2)):
            estado.nova_linha(origem.id, numero, codigo, descricao, G, {PRONTA: qtd})
            estado.nova_linha(destino.id, numero, codigo, descricao, G, {A_FABRICAR: qtd})
    else:
        a = estado.nova_proposta("CP 05900", "Torres Norte Telecom")
        b = estado.nova_proposta("CP 05910", "Rede Sul Energia")
        c = estado.nova_proposta("CP 05920", "Vale Verde Transmissão")
        d = estado.nova_proposta("CP 05930", "Conecta Infra")
        for numero, codigo, descricao, qtd in (("1", "450.400", "Quadro de comando", 6), ("2", "450.398", "Suporte lateral", 3), ("3", "450.830", "Base de fixação", 2)):
            estado.nova_linha(a.id, numero, codigo, descricao, G, {PRONTA: qtd})
            estado.nova_linha(b.id, numero, codigo, descricao, S, {PRONTA: qtd})
        estado.nova_linha(c.id, "1", "450.400", "Quadro de comando", G, {A_FABRICAR: 5, AGUARDANDO: 3, EM_CARGA: 2}, {1: 2})
        estado.nova_linha(c.id, "2", "450.398", "Suporte lateral", G, {A_FABRICAR: 3})
        estado.nova_linha(c.id, "3", "450.830", "Base de fixação", S, {A_FABRICAR: 2})
        estado.nova_linha(d.id, "1", "450.400", "Quadro de comando", S, {A_FABRICAR: 4})
        estado.nova_linha(d.id, "2", "450.830", "Base de fixação", G, {AGUARDANDO: 2})
    estado.fechar_cenario()
    return estado
