"""Gera o INSTALADOR DE TESTE do Desktop (edicao "teste", em paralelo ao oficial).

Um comando:  scripts\build_test_installer.bat   (ou: python scripts/build_test_installer.py)

Saida: release/teste/ControleProducaoTesteSetup-<versao>.exe (+ .sha256).
Usa build_teste/ e dist_teste/: NUNCA toca dist/, build/ nem os arquivos
oficiais de release/. Ver docs/architecture/EDICAO_TESTE.md."""

from __future__ import annotations

import colorsys
import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BUILD = ROOT / "build_teste"
DIST = ROOT / "dist_teste"
OUT = ROOT / "release" / "teste"
ISCC = Path(os.environ.get("ISCC_PATH", r"C:\Users\Industel\AppData\Local\Programs\Inno Setup 6\ISCC.exe"))
TEST_API = "https://producaodev.ykora.com.br"
TEST_HUE_DEGREES = 28  # laranja/ambar, bem distinto do azul oficial
IMAGES = ("Logo_Industel_Icone.ico", "Logo_Industel_Icone_256.png", "logo.png")
ICO_SIZES = [(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]


def recolor(image):
    """Troca so o matiz (mantem brilho, saturacao e transparencia)."""
    from PIL import Image

    rgba = image.convert("RGBA")
    hue = TEST_HUE_DEGREES / 360
    px = rgba.load()
    for y in range(rgba.height):
        for x in range(rgba.width):
            r, g, b, a = px[x, y]
            if a == 0:
                continue
            _, s, v = colorsys.rgb_to_hsv(r / 255, g / 255, b / 255)
            nr, ng, nb = colorsys.hsv_to_rgb(hue, s, v)
            px[x, y] = (round(nr * 255), round(ng * 255), round(nb * 255), a)
    return rgba


def build_assets() -> Path:
    from PIL import Image

    assets = BUILD / "assets"
    if assets.exists():
        shutil.rmtree(assets)
    shutil.copytree(ROOT / "app" / "assets", assets)
    images = assets / "images"
    for name in IMAGES:
        src = ROOT / "app" / "assets" / "images" / name
        with Image.open(src) as im:
            im.load()
            if name.endswith(".ico"):
                biggest = max(im.ico.sizes()) if hasattr(im, "ico") else im.size
                im.size = biggest
                im.load()
            out = recolor(im)
        if name.endswith(".ico"):
            out.save(images / name, format="ICO", sizes=ICO_SIZES)
        else:
            out.save(images / name)
    return assets


def write_edition_files() -> Path:
    BUILD.mkdir(parents=True, exist_ok=True)
    edition_file = BUILD / "edition.json"
    edition_file.write_text(json.dumps({"edition": "teste"}), encoding="utf-8")
    config = {
        "company": "Industel",
        "color_palette": "claro",
        "desktop_api": {"enabled": True, "base_url": TEST_API, "connect_timeout": 3.0, "read_timeout": 10.0},
        "saved_reports": [],
    }
    (BUILD / "controle_producao_config.json").write_text(json.dumps(config, indent=2), encoding="utf-8")
    return edition_file


def app_version() -> str:
    ns: dict = {}
    exec((ROOT / "app" / "version.py").read_text(encoding="utf-8"), ns)
    return ns["APP_VERSION"]


def run(cmd: list[str], env: dict) -> None:
    print(">", " ".join(cmd), flush=True)
    subprocess.run(cmd, cwd=ROOT, env=env, check=True)


def main() -> int:
    if not ISCC.is_file():
        print(f"ISCC nao encontrado: {ISCC} (defina ISCC_PATH)", file=sys.stderr)
        return 1
    version = app_version()
    iss = (ROOT / "installer" / "ControleProducaoTeste.iss").read_text(encoding="utf-8")
    if f'#define MyAppVersion "{version}"' not in iss:
        print(f"MyAppVersion de ControleProducaoTeste.iss difere de app/version.py ({version}).", file=sys.stderr)
        return 1

    assets = build_assets()
    edition_file = write_edition_files()
    env = dict(os.environ)
    env.update(
        CONTROLE_PRODUCAO_EDITION="teste",
        CONTROLE_PRODUCAO_EDITION_FILE=str(edition_file),
        CONTROLE_PRODUCAO_ASSETS_DIR=str(assets),
    )
    if DIST.exists():
        shutil.rmtree(DIST)
    for spec in ("Updater", "ControleProducao", "Launcher"):
        run(
            [sys.executable, "-m", "PyInstaller", f"{spec}.spec", "--noconfirm", "--clean",
             "--distpath", str(DIST), "--workpath", str(BUILD / f"work_{spec}")],
            env,
        )
    OUT.mkdir(parents=True, exist_ok=True)
    run([str(ISCC), str(ROOT / "installer" / "ControleProducaoTeste.iss")], env)
    setup = OUT / f"ControleProducaoTesteSetup-{version}.exe"
    digest = hashlib.sha256(setup.read_bytes()).hexdigest()
    (OUT / f"ControleProducaoTesteSetup-{version}.sha256").write_text(f"{digest} *{setup.name}\n", encoding="utf-8")
    print(f"\nInstalador de teste: {setup} ({setup.stat().st_size / 1_048_576:.1f} MB)\nSHA-256: {digest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
