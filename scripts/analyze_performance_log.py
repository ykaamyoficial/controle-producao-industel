"""Agrega os eventos `performance_api_request` do log do Desktop por endpoint.

Uso: python scripts/analyze_performance_log.py [pasta_de_logs]
Serve de linha de base para medir ganho antes/depois de mudancas de cache/sync.
"""
from __future__ import annotations

import collections
import os
import re
import sys

DEFAULT_DIR = os.path.expandvars(r"%APPDATA%\ControleProducao\logs")
SLOW_MS = 300


def _field(line: str, key: str) -> str | None:
    match = re.search(rf"\b{key}=([^ |]+)", line)
    return match.group(1) if match else None


def load_rows(log_dir: str) -> list[tuple[str, str, str, str, int]]:
    rows = []
    for name in os.listdir(log_dir):
        if not name.startswith("controle_producao.log"):
            continue
        with open(os.path.join(log_dir, name), encoding="utf8", errors="ignore") as handle:
            for line in handle:
                if "performance_api_request" not in line:
                    continue
                path = _field(line, "path") or ""
                rows.append((
                    line[:10], _field(line, "method") or "?",
                    re.sub(r"/\d+", "/{id}", path.split("?")[0]),
                    _field(line, "screen") or "?", int(_field(line, "duration_ms") or 0),
                ))
    return rows


def percentile(values: list[int], q: float) -> int:
    ordered = sorted(values)
    return ordered[int((len(ordered) - 1) * q)]


def main() -> None:
    rows = load_rows(sys.argv[1] if len(sys.argv) > 1 else DEFAULT_DIR)
    if not rows:
        print("Nenhuma requisicao medida encontrada.")
        return
    print(f"{len(rows)} requisicoes de {min(r[0] for r in rows)} a {max(r[0] for r in rows)}")
    by_endpoint: dict[tuple[str, str], list[int]] = collections.defaultdict(list)
    for _, method, path, _, duration in rows:
        by_endpoint[(method, path)].append(duration)
    print(f"{'met':<5} {'endpoint':<52} {'n':>5} {'p50':>6} {'p95':>6} {'max':>6} {'total_s':>8}")
    for (method, path), values in sorted(by_endpoint.items(), key=lambda kv: -sum(kv[1]))[:25]:
        print(f"{method:<5} {path[:52]:<52} {len(values):>5} {percentile(values, .5):>6} "
              f"{percentile(values, .95):>6} {max(values):>6} {sum(values) / 1000:>8.0f}")
    slow = sum(1 for r in rows if r[4] >= SLOW_MS)
    print(f"lentas (>={SLOW_MS}ms): {100 * slow / len(rows):.1f}% | tempo total: {sum(r[4] for r in rows) / 1000:.0f}s")


if __name__ == "__main__":
    main()
