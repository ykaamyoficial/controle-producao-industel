"""Sincroniza uma release Desktop ja aprovada (manifest.json da Fase 11 +
pacote) para o repositorio local do servidor (Fase 12, Secao 24).

Roda diretamente contra a camada de servico (api.app.updates.service), sem
round-trip HTTP -- pensado para rodar no mesmo host/container do servidor,
como parte do pipeline de release (mesmo padrao dos scripts da Fase 09 em
scripts/deployment/). Nunca autoriza automaticamente: por padrao a release
fica em READY; use --authorize para tambem autorizar nesta mesma chamada
(acao explicita, nunca "ultima versao" cega -- Secao 24).

Uso:
    python scripts/sync_release_to_server.py \
        --manifest release/manifest.json \
        --package release/ControleProducaoSetup-2.6.0.exe \
        --source ci-pipeline --authorize
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from api.app.core.exceptions import ApiError  # noqa: E402
from api.app.updates.service import authorize_release, sync_release  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Sincroniza uma release Desktop para o repositorio local do servidor (Fase 12).")
    parser.add_argument("--manifest", required=True, help="Caminho do manifest.json (Fase 11) ja gerado para a release.")
    parser.add_argument("--package", required=True, help="Caminho do pacote/instalador descrito pelo manifesto.")
    parser.add_argument("--source", default="manual", help="Identificador da origem (ex.: 'ci-pipeline', 'manual').")
    parser.add_argument("--authorize", action="store_true", help="Tambem autoriza a distribuicao apos a sincronizacao (acao explicita).")
    args = parser.parse_args(argv)

    try:
        record = sync_release(manifest_path=Path(args.manifest), package_path=Path(args.package), source=args.source)
        print(f"OK: release {record.version} sincronizada, estado={record.state.value}")
        if args.authorize:
            record = authorize_release(record.version)
            print(f"OK: release {record.version} autorizada, estado={record.state.value}")
    except ApiError as exc:
        print(f"ERRO [{exc.code}]: {exc.message}")
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
