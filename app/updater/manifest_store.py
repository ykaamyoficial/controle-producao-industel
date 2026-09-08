"""Ultimo manifesto validado, guardado apenas para diagnostico (Fase 11,
Secao 26): "manifesto invalido nao deve substituir o ultimo manifesto
validado usado apenas para diagnostico". Nunca e uma fonte de confianca --
somente exibicao/log; toda decisao real usa o manifesto recem-buscado e
recem-validado.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from app.updater.manifest import ReleaseManifest, validate_manifest_dict

_FILENAME = "last_valid_manifest.json"


class LastKnownGoodManifestStore:
    def __init__(self, directory: Path):
        self._path = directory / _FILENAME

    def save(self, manifest: ReleaseManifest) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(dir=str(self._path.parent), prefix=".manifest-tmp-", suffix=".json")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(manifest.to_canonical_json())
            os.replace(tmp_name, self._path)
        except Exception:
            Path(tmp_name).unlink(missing_ok=True)
            raise

    def load(self) -> ReleaseManifest | None:
        if not self._path.exists():
            return None
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
            return validate_manifest_dict(data)
        except (OSError, json.JSONDecodeError, ValueError):
            return None
