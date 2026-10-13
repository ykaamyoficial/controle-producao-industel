from __future__ import annotations

from PySide6.QtGui import QColor


def with_alpha(color: str, alpha: int) -> str:
    value = QColor(color)
    return f"rgba({value.red()}, {value.green()}, {value.blue()}, {max(0, min(alpha, 255))})"


def mix(color_a: str, color_b: str, amount: float) -> str:
    """Mistura `color_a` com `color_b`; amount=0 devolve a primeira, 1 a segunda."""
    amount = max(0.0, min(1.0, amount))
    a, b = QColor(color_a), QColor(color_b)
    return "#%02x%02x%02x" % (
        round(a.red() + (b.red() - a.red()) * amount),
        round(a.green() + (b.green() - a.green()) * amount),
        round(a.blue() + (b.blue() - a.blue()) * amount),
    )


def relative_luminance(color: str) -> float:
    value = QColor(color)
    channels = []
    for channel in (value.redF(), value.greenF(), value.blueF()):
        channels.append(channel / 12.92 if channel <= 0.03928 else ((channel + 0.055) / 1.055) ** 2.4)
    return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2]


def contrast_ratio(color_a: str, color_b: str) -> float:
    """Contraste WCAG 2.x entre duas cores opacas (1.0 a 21.0)."""
    lighter, darker = sorted((relative_luminance(color_a), relative_luminance(color_b)), reverse=True)
    return (lighter + 0.05) / (darker + 0.05)


def contrast_text(color: str) -> str:
    """Texto escuro ou branco, o que der mais contraste (WCAG) sobre `color`."""
    dark, light = "#111827", "#ffffff"
    return dark if contrast_ratio(dark, color) >= contrast_ratio(light, color) else light


def ensure_contrast(color: str, background: str, minimum: float, toward: str) -> str:
    """Aproxima `color` de `toward` em passos ate atingir `minimum` contra
    `background`. Usado para derivar tokens que funcionem em qualquer paleta
    em vez de fixar um hexadecimal por tema."""
    result = color
    for step in range(1, 21):
        if contrast_ratio(result, background) >= minimum:
            break
        result = mix(color, toward, step / 20)
    return result


def ui_tokens(palette: dict) -> dict[str, str]:
    """Paleta ativa + tokens do padrao visual refinado (skill qt-industrial-ui),
    todos derivados da propria paleta: nenhuma cor nova e escolhida a mao aqui.

    - surface_hover: hover de linha de tabela e de botao secundario
    - zebra / table_header / selected: linhas impares, cabecalho e linha selecionada
    - subtle: placeholder e valor vazio (texto, >= 4.5:1)
    - input_border: borda de campo e de caixa de marcacao (>= 3:1)
    - ring: anel de foco (>= 3:1)
    - accent_soft: fundo suave na cor de destaque (pilulas de contagem)
    - media_*, overlay*, on_overlay: visualizador de midia (excecao fixa)
    - shell_ink, shell_light: sombra e filete de luz da casca das janelas
      (excecao fixa: luz e sombra sao as mesmas nos dois temas, so a forca muda)
    """
    surface = palette["surface"]
    surface_alt = palette["surface_alt"]
    text = palette["text"]
    accent = palette["accent"]
    return {
        **palette,
        "surface_hover": mix(surface_alt, accent, 0.10),
        "zebra": mix(surface, surface_alt, 0.45),
        "table_header": mix(surface_alt, accent, 0.06),
        "selected": mix(surface_alt, accent, 0.22),
        "subtle": ensure_contrast(mix(palette["muted"], surface, 0.25), surface, 4.6, text),
        "input_border": ensure_contrast(mix(palette["border"], palette["muted"], 0.5), surface, 3.1, text),
        "ring": ensure_contrast(accent, surface, 3.0, text),
        "accent_soft": mix(surface, accent, 0.12),
        # Visualizador de foto/video e sobreposicoes sobre midia: escuros nos
        # dois temas (a midia e que manda), por isso nao derivam da paleta.
        "media_bg": "#111827",
        "media_text": "#e5e7eb",
        "media_muted": "#94a3b8",
        "overlay": "rgba(15, 23, 42, 160)",
        "overlay_strong": "rgba(15, 23, 42, 200)",
        "on_overlay": "#ffffff",
        # Casca das janelas (window_shell.py) e veu: mesmo azul quase preto do
        # veu para aro e sombras, branco para o filete de luz.
        "shell_ink": "#080f1e",
        "shell_light": "#ffffff",
    }


# Paleta ativa para componentes pintados a mao (botoes, selos, abas) que nao
# recebem `service` no construtor. `app_stylesheet()` e o ponto unico por onde
# a aplicacao aplica um tema, entao e ele quem atualiza este registro.
_FALLBACK_PALETTE = {
    "bg": "#f5f7fb",
    "surface": "#ffffff",
    "surface_alt": "#e8f1ff",
    "text": "#0f172a",
    "muted": "#475569",
    "border": "#cbd5e1",
    "accent": "#006fc9",
    "accent_hover": "#005aa3",
    "accent_text": "#ffffff",
    "secondary": "#be123c",
    "success": "#047857",
    "warning": "#b45309",
    "danger": "#b91c1c",
}
_active_tokens: dict[str, str] | None = None


def set_active_palette(palette: dict) -> None:
    global _active_tokens
    _active_tokens = ui_tokens(palette)


def active_tokens() -> dict[str, str]:
    global _active_tokens
    if _active_tokens is None:
        _active_tokens = ui_tokens(_FALLBACK_PALETTE)
    return _active_tokens


def dashboard_tokens(palette: dict) -> dict[str, str]:
    """Semantic dashboard colors derived exclusively from the active application theme."""
    return {
        **palette,
        "header_start": palette["accent"],
        "header_end": palette["accent_hover"],
        "header_text": palette["accent_text"],
        "header_muted": with_alpha(palette["accent_text"], 205),
        "shadow": with_alpha(palette["text"], 10),
        "track": palette["surface_alt"],
        "hover": with_alpha(palette["accent"], 20),
        "success_soft": with_alpha(palette["success"], 34),
        "warning_soft": with_alpha(palette["warning"], 38),
        "danger_soft": with_alpha(palette["danger"], 34),
        "accent_soft": with_alpha(palette["accent"], 32),
    }


def dashboard_chart_colors(palette: dict) -> list[str]:
    """Chart series sourced from the semantic colors of the active theme."""
    return [
        palette.get("area_control", palette["accent"]),
        palette.get("area_production", palette["success"]),
        palette.get("area_galvanization", palette["secondary"]),
        palette.get("area_expedition", palette["warning"]),
        palette.get("area_fiscal", palette["danger"]),
        palette["danger"],
        palette["accent_hover"],
        palette.get("area_stock", palette["muted"]),
    ]
