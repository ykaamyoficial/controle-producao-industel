"""Confere o contraste (WCAG 2.x) dos pares de cor do Desktop em todas as
paletas oficiais. Falha (exit 1) se algum par ficar abaixo do minimo.

Minimos: 4.5:1 para texto; 3.0:1 para borda de campo, icone e anel de foco.

Uso:
    python scripts/check_contrast.py
    python scripts/check_contrast.py --verbose
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.backend_adapter import OFFICIAL_COLOR_PALETTES  # noqa: E402
from app.ui.styles import STATUS_BADGE_COLORS, _contrast_text, _is_dark, chrome_bg_color  # noqa: E402
from app.ui.theme_tokens import contrast_ratio, ui_tokens  # noqa: E402

TEXT = 4.5
GRAPHIC = 3.0


def palette_pairs(name: str, palette: dict) -> list[tuple[str, str, str, float]]:
    t = ui_tokens(palette)
    chrome = chrome_bg_color(palette)
    pairs = [
        ("texto / fundo", t["text"], t["bg"], TEXT),
        ("texto / superficie", t["text"], t["surface"], TEXT),
        ("texto / superficie alternativa", t["text"], t["surface_alt"], TEXT),
        ("texto / linha zebrada", t["text"], t["zebra"], TEXT),
        ("texto / linha em hover", t["text"], t["surface_hover"], TEXT),
        ("texto / linha selecionada", t["text"], t["selected"], TEXT),
        ("texto / cabecalho de tabela", t["text"], t["table_header"], TEXT),
        ("texto / moldura (barra lateral)", t["text"], chrome, TEXT),
        ("muted / superficie", t["muted"], t["surface"], TEXT),
        ("muted / fundo", t["muted"], t["bg"], TEXT),
        ("muted / moldura (barra lateral)", t["muted"], chrome, TEXT),
        ("sutil / superficie", t["subtle"], t["surface"], TEXT),
        ("texto do botao primario", t["accent_text"], t["accent"], TEXT),
        ("texto do botao primario (hover)", t["accent_text"], t["accent_hover"], TEXT),
        ("destaque como texto / superficie", t["accent"], t["surface"], TEXT),
        ("perigo como texto / superficie", t["danger"], t["surface"], TEXT),
        ("aviso como texto / superficie", t["warning"], t["surface"], TEXT),
        ("icone de destaque / botao secundario", t["accent"], t["surface_alt"], GRAPHIC),
        ("icone de destaque / moldura", t["accent"], chrome, GRAPHIC),
        ("borda de campo / superficie", t["input_border"], t["surface"], GRAPHIC),
        ("anel de foco / superficie", t["ring"], t["surface"], GRAPHIC),
        ("anel de foco / fundo", t["ring"], t["bg"], GRAPHIC),
    ]
    theme_key = "escuro" if _is_dark(palette.get("bg", "#ffffff")) else "claro"
    for category, color in STATUS_BADGE_COLORS[theme_key].items():
        pairs.append((f"texto do selo {category}", _contrast_text(color), color, TEXT))
        pairs.append((f"icone de status {category} / superficie", color, t["surface"], GRAPHIC))
    return pairs


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--verbose", action="store_true", help="mostra tambem os pares aprovados")
    args = parser.parse_args()

    failures = 0
    checked = 0
    for name, palette in OFFICIAL_COLOR_PALETTES.items():
        print(f"Paleta {name}")
        for label, foreground, background, minimum in palette_pairs(name, palette):
            ratio = contrast_ratio(foreground, background)
            checked += 1
            ok = ratio >= minimum
            failures += 0 if ok else 1
            if args.verbose or not ok:
                print(f"  {'ok   ' if ok else 'FALHA'} {ratio:5.2f} (min {minimum})  {label}  [{foreground} sobre {background}]")
    print(f"{checked} pares conferidos, {failures} falha(s)")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
