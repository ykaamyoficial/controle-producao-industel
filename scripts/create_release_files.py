from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
RELEASE_DIR = ROOT_DIR / "release"
VERSION_FILE = ROOT_DIR / "app" / "version.py"


def load_version_module():
    spec = importlib.util.spec_from_file_location("app_version", VERSION_FILE)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Nao foi possivel carregar {VERSION_FILE}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_release_files() -> dict[str, object]:
    version = load_version_module()
    app_version = str(version.APP_VERSION)
    app_name = str(version.APP_NAME)
    channel = str(version.APP_CHANNEL)
    installer_name = f"ControleProducaoSetup-{app_version}.exe"
    installer_path = RELEASE_DIR / installer_name

    if not installer_path.exists():
        raise FileNotFoundError(f"Instalador nao encontrado: {installer_path}")

    installer_hash = sha256_file(installer_path)
    sha256_name = f"ControleProducaoSetup-{app_version}.sha256"
    sha256_path = RELEASE_DIR / sha256_name
    sha256_path.write_text(f"{installer_hash}  {installer_name}\n", encoding="utf-8")

    latest = {
        "app": app_name,
        "version": app_version,
        "tag": f"v{app_version}",
        "channel": channel,
        "installer": installer_name,
        "sha256_file": sha256_name,
        "sha256": installer_hash,
        "required": False,
        "min_supported_version": "2.0.0",
        "release_notes": [
            "Primeira versao instalavel oficial",
            "Instalacao em Program Files",
            "Banco e configuracoes em ProgramData",
            "Dashboard Executivo",
            "Modulo Fiscal",
            "Relatorios Operacionais",
        ],
    }
    latest_path = RELEASE_DIR / "latest.json"
    latest_path.write_text(
        json.dumps(latest, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    return {
        "installer": str(installer_path),
        "installer_size_bytes": installer_path.stat().st_size,
        "sha256_file": str(sha256_path),
        "latest_json": str(latest_path),
        "sha256": installer_hash,
        "version": app_version,
    }


def main() -> None:
    result = write_release_files()
    print("Arquivos de release gerados com sucesso.")
    print(f"Versao: {result['version']}")
    print(f"Instalador: {result['installer']}")
    print(f"Tamanho: {result['installer_size_bytes']} bytes")
    print(f"SHA-256: {result['sha256']}")
    print(f"Arquivo SHA-256: {result['sha256_file']}")
    print(f"latest.json: {result['latest_json']}")


if __name__ == "__main__":
    main()
