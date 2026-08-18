from __future__ import annotations

from copy import deepcopy
from threading import RLock
from time import monotonic
from typing import Any, Callable


class ShortLivedCache:
    """Cache local, curto e seguro para leituras repetidas da mesma sessão."""

    def __init__(self, default_ttl: float = 2.0):
        self.default_ttl = default_ttl
        self._entries: dict[str, tuple[float, Any]] = {}
        self._lock = RLock()

    def get_or_load(self, key: str, loader: Callable[[], Any], *, ttl: float | None = None) -> Any:
        now = monotonic()
        lifetime = self.default_ttl if ttl is None else ttl
        with self._lock:
            entry = self._entries.get(key)
            if entry and now - entry[0] < lifetime:
                return deepcopy(entry[1])
        value = loader()
        with self._lock:
            self._entries[key] = (monotonic(), deepcopy(value))
        return deepcopy(value)

    def invalidate(self, prefix: str | None = None) -> None:
        with self._lock:
            if prefix is None:
                self._entries.clear()
            else:
                for key in [key for key in self._entries if key.startswith(prefix)]:
                    self._entries.pop(key, None)

