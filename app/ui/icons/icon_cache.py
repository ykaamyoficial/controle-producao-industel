"""Cache simples (chave -> QPixmap) para nao reler/rasterizar o mesmo SVG a
cada repaint. Chave recomendada: (nome_lucide, size, cor, devicePixelRatio).
Capado em tamanho para nao acumular copias indefinidamente em memoria;
`clear()` e chamado uma unica vez na troca de tema, ja que a cor faz parte da
chave - itens do tema anterior simplesmente saem de uso e sao descartados.
"""

from __future__ import annotations

from collections import OrderedDict
from typing import Any

_MAX_ENTRIES = 512
_cache: "OrderedDict[tuple, Any]" = OrderedDict()


def get(key: tuple) -> Any | None:
    value = _cache.get(key)
    if value is not None:
        _cache.move_to_end(key)
    return value


def put(key: tuple, value: Any) -> None:
    _cache[key] = value
    _cache.move_to_end(key)
    while len(_cache) > _MAX_ENTRIES:
        _cache.popitem(last=False)


def clear() -> None:
    _cache.clear()


def size() -> int:
    return len(_cache)
