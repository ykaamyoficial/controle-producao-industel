"""Formatacao compartilhada do contador numerico usado nos badges de chat e
de notificacoes (PDF secao 13: "badge de chat e badge do sino devem usar o
mesmo componente base", "mostrar 1-99 e usar 99+ acima disso", "quando
contador for zero, ocultar o badge")."""

from __future__ import annotations


def format_count_badge(count: int) -> str:
    if not count:
        return ""
    return "99+" if count >= 100 else str(count)
