from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


ZERO = Decimal("0.0000")

# Plano de logistica do remanejamento: item galvanizado como ORIGEM/DESTINO so e liberado na
# Fase E (assistente). Ate la a chave fica desligada e os testes da Fase C a ligam por patch.
GALVANIZED_REMANAGEMENT_ENABLED = False


def galvanized_remanagement_blocked(requires_galvanization: str | None) -> bool:
    """True quando o item e galvanizado e o remanejamento de galvanizados ainda esta desligado."""
    return requires_galvanization == "SIM" and not GALVANIZED_REMANAGEMENT_ENABLED


def quantity(value) -> Decimal:
    return Decimal(str(value or "0")).quantize(Decimal("0.0001"))


@dataclass(frozen=True)
class ItemAllocationBalance:
    requested: Decimal
    ready_available: Decimal
    delivered: Decimal
    remanaged_out: Decimal
    native_production_pending: Decimal
    production_reallocated_out: Decimal
    production_reallocated_in_pending: Decimal
    production_reallocated_in_completed: Decimal

    @property
    def destination_need(self) -> Decimal:
        return max(ZERO, self.requested - self.delivered - self.ready_available).quantize(Decimal("0.0001"))

    @property
    def reallocatable_production(self) -> Decimal:
        return max(ZERO, self.native_production_pending - self.production_reallocated_out).quantize(Decimal("0.0001"))

    @property
    def production_pending(self) -> Decimal:
        return (self.reallocatable_production + self.production_reallocated_in_pending).quantize(Decimal("0.0001"))


def calculate_item_balance(
    *,
    requested,
    produced: bool,
    produce_internally: str,
    expedition_available=ZERO,
    delivered=ZERO,
    remanaged_out=ZERO,
    production_reallocated_out=ZERO,
    production_reallocated_in_pending=ZERO,
    production_reallocated_in_completed=ZERO,
) -> ItemAllocationBalance:
    requested_qty = quantity(requested)
    available_qty = quantity(expedition_available)
    delivered_qty = quantity(delivered)
    remanaged_qty = quantity(remanaged_out)
    ready = max(ZERO, available_qty - delivered_qty - remanaged_qty).quantize(Decimal("0.0001"))
    # A disponibilidade oficial pode ser parcial, enquanto ``produced`` e apenas
    # um marcador historico do item inteiro. O saldo quantitativo prevalece.
    if produce_internally != "SIM":
        native_pending = ZERO
    elif available_qty > ZERO or remanaged_qty > ZERO:
        native_pending = max(
            ZERO,
            requested_qty
            - available_qty
            + remanaged_qty
            + quantity(production_reallocated_out)
            - quantity(production_reallocated_in_pending)
            - quantity(production_reallocated_in_completed),
        )
    else:
        native_pending = ZERO if produced else requested_qty
    return ItemAllocationBalance(
        requested=requested_qty,
        ready_available=ready,
        delivered=delivered_qty,
        remanaged_out=remanaged_qty,
        native_production_pending=native_pending,
        production_reallocated_out=quantity(production_reallocated_out),
        production_reallocated_in_pending=quantity(production_reallocated_in_pending),
        production_reallocated_in_completed=quantity(production_reallocated_in_completed),
    )


def galvanization_pipeline_quantity(
    *,
    requested,
    production_out=ZERO,
    production_in_completed=ZERO,
    fabricated_in=ZERO,
    fabricated_out=ZERO,
) -> Decimal:
    """Quantas pecas de um item GALVANIZADO passam pela galvanizacao ("esteira").

    esteira = pedido - obrigacao de fabricar cedida + reposicao concluida recebida
              + pecas ja fabricadas recebidas - pecas ja fabricadas cedidas

    Sem nenhuma troca por remanejamento a esteira e igual ao pedido. E esta quantidade (e nao
    mais `item.quantity`) que diz quanto o item ainda pode mandar em carga e quando ele
    voltou inteiro da galvanizacao (plano de logistica do remanejamento, Fase C)."""
    return (
        quantity(requested) - quantity(production_out) + quantity(production_in_completed)
        + quantity(fabricated_in) - quantity(fabricated_out)
    ).quantize(Decimal("0.0001"))


def items_are_compatible(source_item, destination_item) -> tuple[bool, str | None]:
    source_code = str(source_item.product_code or "").strip().upper()
    destination_code = str(destination_item.product_code or "").strip().upper()
    if not source_code or not destination_code or source_code != destination_code:
        return False, "Os itens precisam possuir o mesmo codigo de produto."
    source_unit = str(source_item.unit or "").strip().upper()
    destination_unit = str(destination_item.unit or "").strip().upper()
    if source_unit != destination_unit:
        return False, "Os itens precisam possuir a mesma unidade."
    if source_item.requires_galvanization != destination_item.requires_galvanization:
        return False, "Os itens possuem fluxos de galvanizacao diferentes."
    if source_item.produce_internally != destination_item.produce_internally:
        return False, "Os itens possuem fluxos produtivos diferentes."
    if not source_item.flow_defined or not destination_item.flow_defined:
        return False, "Os dois itens precisam possuir fluxo operacional definido."
    return True, None


def max_remanageable(source: ItemAllocationBalance, destination: ItemAllocationBalance) -> Decimal:
    return min(source.ready_available, destination.destination_need, destination.reallocatable_production).quantize(Decimal("0.0001"))
