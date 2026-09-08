"""Empacota a atualizacao do Desktop no formato que o Updater (Fase 10)
espera: um ZIP cujo conteudo na raiz e exatamente a arvore de install_dir.

O Updater NUNCA roda o instalador Inno -- ele valida o pacote como ZIP
(`app/updater/validation.py::verify_package`), extrai
(`safe_extract_zip`) e faz swap de diretorio (`app/updater/swap.py`). O
`.exe` do Inno Setup continua existindo, mas so para instalacao nova
(primeira vez); a atualizacao assistida usa este ZIP.

Conteudo do ZIP (raiz) = `dist/ControleProducao/*` + `dist/Updater/*`
mesclados (o mesmo que `installer/ControleProducao.iss` copia para {app}),
mais um arquivo `VERSION` = APP_VERSION.

Uso:
    python -m PyInstaller Updater.spec --clean --noconfirm
    python -m PyInstaller ControleProducao.spec --clean --noconfirm
    python scripts/build_update_package.py
    # -> release/ControleProducao-<versao>-update.zip
    python scripts/generate_release_manifest.py \
        --artifact release/ControleProducao-<versao>-update.zip \
        --content-type application/zip \
        --minimum-server-version <X.Y.Z> --api-contract-version v1
"""

from __future__ import annotations

import hashlib
import importlib.util
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "dist"
RELEASE_DIR = ROOT / "release"
SOURCE_DIRS = (DIST / "ControleProducao", DIST / "Updater")


def _app_version() -> str:
    spec = importlib.util.spec_from_file_location("app_version", ROOT / "app" / "version.py")
    if spec is None or spec.loader is None:  # pragma: no cover
        raise RuntimeError("Nao foi possivel carregar app/version.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return str(module.APP_VERSION)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_update_package() -> Path:
    version = _app_version()
    for source in SOURCE_DIRS:
        if not source.is_dir():
            raise FileNotFoundError(
                f"'{source}' nao existe. Rode os PyInstaller (Updater.spec e ControleProducao.spec) antes."
            )

    RELEASE_DIR.mkdir(parents=True, exist_ok=True)
    output = RELEASE_DIR / f"ControleProducao-{version}-update.zip"
    output.unlink(missing_ok=True)

    # Ordena as entradas para o ZIP ser deterministico (mesmo bytes -> mesmo
    # sha256) entre builds do mesmo dist.
    # Mesma regra do installer/ControleProducao.iss: ControleProducao e
    # copiado primeiro, Updater depois com `ignoreversion` -> em conflito no
    # `_internal/` compartilhado, o arquivo do Updater prevalece (last wins).
    # O unico conflito real hoje e `_internal/base_library.zip`.
    entries: dict[str, Path] = {}
    for source in SOURCE_DIRS:
        for path in sorted(source.rglob("*")):
            if not path.is_file():
                continue
            arcname = path.relative_to(source).as_posix()
            if arcname in entries and _sha256(entries[arcname]) != _sha256(path):
                print(f"  aviso: '{arcname}' difere entre os bundles -- usando {source.name} (mesma regra do .iss)")
            entries[arcname] = path

    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for arcname in sorted(entries):
            archive.write(entries[arcname], arcname)
        # Marcador de versao (app/updater/install_validation.py o confere se presente).
        archive.writestr("VERSION", version + "\n")

    print(f"Pacote de atualizacao: {output}")
    print(f"Versao: {version}")
    print(f"Tamanho: {output.stat().st_size} bytes")
    print(f"SHA-256: {_sha256(output)}")
    print(f"Entradas: {len(entries) + 1}")
    return output


if __name__ == "__main__":
    build_update_package()
