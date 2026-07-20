from __future__ import annotations

import colorsys
import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter


ROOT = Path(__file__).resolve().parents[1]
ICON_DIR = ROOT / "app" / "assets" / "icons"
SIZES = (512, 256, 128, 64, 48, 32, 24, 16)


BASE_COLORS = {
    "control": "#2196F3",
    "production": "#22C55E",
    "galvanization": "#8B5CF6",
    "expedition": "#F97316",
    "stock": "#E2E8F0",
    "fiscal": "#EF4444",
    "reports": "#06B6D4",
    "settings": "#A855F7",
    "backup": "#16A34A",
    "database": "#2563EB",
    "history": "#38BDF8",
    "users": "#3B82F6",
    "audit": "#22D3EE",
    "waiting": "#FACC15",
    "success": "#22C55E",
    "error": "#EF4444",
    "attention": "#FB923C",
    "neutral": "#94A3B8",
    "whiteblue": "#E2E8F0",
}


ICON_SPECS = {
    "area_controle_geral": ("radar", BASE_COLORS["control"]),
    "area_painel": ("bars", BASE_COLORS["control"]),
    "area_producao": ("factory", BASE_COLORS["production"]),
    "area_galvanizacao": ("tank", BASE_COLORS["galvanization"]),
    "area_expedicao": ("truck", BASE_COLORS["expedition"]),
    "area_almoxarifado": ("shelf", BASE_COLORS["stock"]),
    "sistema_fiscal": ("fiscal", BASE_COLORS["fiscal"]),
    "sistema_relatorios": ("chart", BASE_COLORS["reports"]),
    "sistema_configuracoes": ("settings", BASE_COLORS["settings"]),
    "sistema_backup": ("backup", BASE_COLORS["backup"]),
    "sistema_banco_sqlite": ("database", BASE_COLORS["database"]),
    "sistema_historico": ("clock", BASE_COLORS["history"]),
    "sistema_usuarios": ("users", BASE_COLORS["users"]),
    "sistema_auditoria": ("audit", BASE_COLORS["audit"]),
    "sistema_restaurar": ("restore", BASE_COLORS["backup"]),
    "acao_pesquisar": ("search", BASE_COLORS["database"]),
    "acao_novo": ("add", BASE_COLORS["production"]),
    "acao_remover": ("delete", BASE_COLORS["error"]),
    "acao_editar": ("edit", BASE_COLORS["settings"]),
    "acao_salvar": ("confirm", BASE_COLORS["success"]),
    "acao_proximo": ("next", BASE_COLORS["control"]),
    "acao_anterior": ("back", BASE_COLORS["control"]),
    "acao_limpar": ("cancel", BASE_COLORS["neutral"]),
    "acao_atualizar": ("refresh", BASE_COLORS["reports"]),
    "acao_cargas": ("truck", BASE_COLORS["expedition"]),
    "acao_lote": ("list", BASE_COLORS["reports"]),
    "acao_pdf": ("document", BASE_COLORS["fiscal"]),
    "acao_excel": ("table", BASE_COLORS["success"]),
    "acao_entrega_remanejada": ("transfer", BASE_COLORS["attention"]),
}


STATUS_RULES = {
    "aguardando": ("hourglass", BASE_COLORS["waiting"]),
    "nao": ("pause", BASE_COLORS["neutral"]),
    "pendente": ("warning", BASE_COLORS["waiting"]),
    "pending": ("warning", BASE_COLORS["waiting"]),
    "iniciado": ("play", BASE_COLORS["control"]),
    "andamento": ("play", BASE_COLORS["control"]),
    "parado": ("stop", BASE_COLORS["error"]),
    "cancel": ("cancel", BASE_COLORS["error"]),
    "finalizado": ("confirm", BASE_COLORS["success"]),
    "finished": ("confirm", BASE_COLORS["success"]),
    "entregue": ("confirm", "#0F766E"),
    "parcial": ("partial", BASE_COLORS["attention"]),
    "galvanizacao": ("tank", BASE_COLORS["galvanization"]),
    "expedicao": ("truck", BASE_COLORS["expedition"]),
    "separacao": ("shelf", BASE_COLORS["stock"]),
    "carga": ("truck", BASE_COLORS["expedition"]),
    "liberado": ("next", BASE_COLORS["control"]),
    "em_producao": ("factory", BASE_COLORS["production"]),
    "sem_parafusos": ("minus", BASE_COLORS["neutral"]),
    "unificada": ("link", "#0F766E"),
    "cp_em_processamento": ("factory", BASE_COLORS["control"]),
    "disponivel_para_emissao": ("document", BASE_COLORS["waiting"]),
    "pendencia_fiscal_critica": ("warning", BASE_COLORS["error"]),
    "nota_fiscal_parcial": ("partial", BASE_COLORS["attention"]),
    "nota_fiscal_emitida": ("fiscal", BASE_COLORS["success"]),
    "nf_emitida": ("fiscal", BASE_COLORS["success"]),
    "nf_retirada_cliente": ("truck", "#0F766E"),
}

EXTRA_STATUS_KEYS = (
    "CP_EM_PROCESSAMENTO",
    "DISPONIVEL_PARA_EMISSAO",
    "PENDENCIA_FISCAL_CRITICA",
    "FALTA_EMITIR_NOTA_FISCAL",
    "NOTA_FISCAL_PARCIAL",
    "NOTA_FISCAL_EMITIDA",
    "NF_EMITIDA",
    "NF_RETIRADA_CLIENTE",
    "FISCAL_CANCELADO",
)


def hex_to_rgba(value: str, alpha: int = 255) -> tuple[int, int, int, int]:
    value = value.strip().lstrip("#")
    return tuple(int(value[i : i + 2], 16) for i in (0, 2, 4)) + (alpha,)


def adjust(hex_color: str, lightness: float = 0.0, saturation: float = 0.0) -> str:
    r, g, b, _ = hex_to_rgba(hex_color)
    h, l, s = colorsys.rgb_to_hls(r / 255, g / 255, b / 255)
    l = max(0, min(1, l + lightness))
    s = max(0, min(1, s + saturation))
    rr, gg, bb = colorsys.hls_to_rgb(h, l, s)
    return f"#{int(rr*255):02X}{int(gg*255):02X}{int(bb*255):02X}"


def draw_gradient_rounded(draw: ImageDraw.ImageDraw, box, radius, top, bottom):
    x1, y1, x2, y2 = map(int, box)
    w, h = max(1, x2 - x1), max(1, y2 - y1)
    gradient = Image.new("RGBA", (w, h))
    top_rgba = hex_to_rgba(top, 245)
    bottom_rgba = hex_to_rgba(bottom, 245)
    gd = ImageDraw.Draw(gradient)
    for y in range(h):
        t = y / max(1, h - 1)
        col = tuple(int(top_rgba[i] * (1 - t) + bottom_rgba[i] * t) for i in range(4))
        gd.line((0, y, w, y), fill=col)
    mask = Image.new("L", (w, h), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, w - 1, h - 1), radius=radius, fill=255)
    draw._image.paste(gradient, (x1, y1), mask)


def rounded_layer(base, box, color, radius=64):
    shadow = Image.new("RGBA", base.size, (0, 0, 0, 0))
    sd = ImageDraw.Draw(shadow)
    x1, y1, x2, y2 = box
    sd.rounded_rectangle((x1 + 18, y1 + 28, x2 + 18, y2 + 28), radius=radius, fill=(15, 23, 42, 86))
    shadow = shadow.filter(ImageFilter.GaussianBlur(24))
    base.alpha_composite(shadow)
    d = ImageDraw.Draw(base)
    draw_gradient_rounded(d, box, radius, adjust(color, 0.18), adjust(color, -0.08))
    d.rounded_rectangle(box, radius=radius, outline=hex_to_rgba("#FFFFFF", 92), width=5)
    d.arc((x1 + 34, y1 + 22, x2 - 34, y2 - 60), 200, 328, fill=hex_to_rgba("#FFFFFF", 86), width=10)
    glow = Image.new("RGBA", base.size, (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    gd.rounded_rectangle((x1 + 18, y1 + 18, x2 - 18, y2 - 18), radius=radius - 12, outline=hex_to_rgba(color, 120), width=10)
    base.alpha_composite(glow.filter(ImageFilter.GaussianBlur(10)))


def line(draw, pts, fill, width=24):
    draw.line(pts, fill=fill, width=width, joint="curve")


def draw_symbol(base, symbol: str, color: str):
    d = ImageDraw.Draw(base)
    ink = hex_to_rgba("#FFFFFF", 238)
    ink2 = hex_to_rgba(adjust(color, 0.38, -0.1), 245)
    dark = hex_to_rgba(adjust(color, -0.28), 210)
    accent = hex_to_rgba(adjust(color, 0.12), 245)
    if symbol == "radar":
        d.ellipse((150, 150, 362, 362), outline=ink, width=22)
        d.ellipse((216, 216, 296, 296), fill=ink2)
        line(d, [(256, 256), (356, 176)], ink, 18)
        d.arc((108, 108, 404, 404), 210, 330, fill=ink2, width=16)
    elif symbol == "bars":
        for i, h in enumerate((120, 185, 245)):
            x = 142 + i * 85
            d.rounded_rectangle((x, 360 - h, x + 52, 360), radius=18, fill=ink)
        line(d, [(120, 372), (390, 372)], ink, 18)
    elif symbol == "factory":
        d.polygon([(118, 346), (118, 235), (188, 270), (188, 225), (260, 270), (260, 225), (335, 268), (335, 346)], fill=ink)
        d.rectangle((140, 170, 188, 346), fill=ink2)
        for x in (154, 218, 282):
            d.rounded_rectangle((x, 298, x + 38, 346), radius=8, fill=dark)
    elif symbol == "tank":
        line(d, [(256, 130), (256, 218)], ink, 18)
        d.rounded_rectangle((122, 232, 390, 340), radius=34, fill=ink)
        d.rounded_rectangle((158, 252, 354, 320), radius=26, fill=accent)
        d.polygon([(206, 156), (306, 156), (334, 210), (178, 210)], fill=ink2)
    elif symbol == "truck":
        d.rounded_rectangle((104, 214, 294, 318), radius=24, fill=ink)
        d.rounded_rectangle((294, 242, 386, 318), radius=20, fill=ink2)
        d.polygon([(314, 242), (362, 242), (386, 276), (314, 276)], fill=accent)
        for x in (168, 322):
            d.ellipse((x, 300, x + 58, 358), fill=dark)
            d.ellipse((x + 15, 315, x + 43, 343), fill=ink)
    elif symbol == "shelf":
        for y in (164, 248, 332):
            d.rounded_rectangle((116, y, 396, y + 24), radius=12, fill=ink)
        for x, y, c in ((136, 190, "#60A5FA"), (230, 190, "#FFFFFF"), (310, 274, "#93C5FD"), (154, 274, "#CBD5E1")):
            d.rounded_rectangle((x, y, x + 62, y + 52), radius=14, fill=hex_to_rgba(c, 238))
    elif symbol == "fiscal":
        d.rounded_rectangle((132, 116, 304, 372), radius=24, fill=ink)
        d.polygon([(270, 116), (304, 116), (304, 154)], fill=accent)
        for y in (184, 224, 264):
            line(d, [(164, y), (264, y)], dark, 12)
        d.rounded_rectangle((284, 242, 390, 370), radius=24, fill=ink2)
        for x in (306, 342):
            for y in (270, 306, 342):
                d.ellipse((x, y, x + 16, y + 16), fill=dark)
    elif symbol == "audit":
        d.rounded_rectangle((132, 126, 330, 360), radius=24, fill=ink)
        d.rounded_rectangle((184, 104, 278, 150), radius=18, fill=ink2)
        for y in (190, 236, 282):
            line(d, [(166, y), (194, y + 20), (238, y - 24)], dark, 10)
        d.ellipse((286, 252, 376, 342), outline=accent, width=20)
        line(d, [(354, 322), (396, 364)], accent, 18)
    elif symbol == "chart":
        d.rounded_rectangle((122, 320, 170, 374), radius=16, fill=ink)
        d.rounded_rectangle((204, 260, 252, 374), radius=16, fill=ink2)
        d.rounded_rectangle((286, 190, 334, 374), radius=16, fill=ink)
        line(d, [(128, 224), (208, 176), (282, 218), (376, 132)], accent, 18)
    elif symbol == "clock":
        d.ellipse((126, 126, 386, 386), fill=ink)
        d.ellipse((160, 160, 352, 352), fill=accent)
        line(d, [(256, 256), (256, 176)], dark, 20)
        line(d, [(256, 256), (318, 292)], dark, 20)
    elif symbol == "users":
        d.ellipse((128, 150, 236, 258), fill=ink)
        d.ellipse((276, 132, 398, 254), fill=ink2)
        d.rounded_rectangle((98, 282, 270, 382), radius=48, fill=ink)
        d.rounded_rectangle((244, 278, 430, 386), radius=54, fill=ink2)
    elif symbol == "database":
        for y in (140, 212, 284):
            d.ellipse((126, y - 46, 386, y + 46), fill=ink if y == 140 else accent)
            d.rectangle((126, y, 386, y + 72), fill=ink if y == 140 else accent)
            d.ellipse((126, y + 26, 386, y + 118), fill=ink2 if y == 284 else accent)
    elif symbol == "backup":
        d.rounded_rectangle((128, 168, 384, 356), radius=36, fill=ink)
        d.rounded_rectangle((172, 220, 340, 308), radius=28, fill=accent)
        d.ellipse((232, 242, 280, 290), fill=dark)
        d.arc((176, 112, 336, 260), 205, 338, fill=ink2, width=22)
    elif symbol == "settings":
        for y, x in ((168, 306), (256, 202), (344, 284)):
            line(d, [(130, y), (382, y)], ink, 22)
            d.ellipse((x - 34, y - 34, x + 34, y + 34), fill=ink2, outline=dark, width=8)
    elif symbol == "restore":
        d.arc((130, 132, 382, 384), 35, 330, fill=ink, width=28)
        d.polygon([(144, 156), (146, 248), (214, 192)], fill=ink)
    elif symbol == "search":
        d.ellipse((126, 126, 302, 302), outline=ink, width=30)
        line(d, [(276, 276), (390, 390)], ink2, 30)
    elif symbol == "add":
        d.ellipse((128, 128, 384, 384), fill=ink)
        line(d, [(256, 180), (256, 332)], dark, 28)
        line(d, [(180, 256), (332, 256)], dark, 28)
    elif symbol == "delete":
        d.rounded_rectangle((154, 178, 358, 382), radius=28, fill=ink)
        d.rounded_rectangle((184, 130, 328, 170), radius=18, fill=ink2)
        line(d, [(206, 220), (206, 336)], dark, 14)
        line(d, [(256, 220), (256, 336)], dark, 14)
        line(d, [(306, 220), (306, 336)], dark, 14)
    elif symbol == "edit":
        d.polygon([(142, 342), (166, 256), (300, 122), (388, 210), (254, 344)], fill=ink)
        d.polygon([(142, 342), (130, 394), (182, 382)], fill=accent)
        line(d, [(292, 130), (380, 218)], dark, 18)
    elif symbol == "confirm":
        line(d, [(132, 268), (218, 344), (386, 158)], ink, 36)
    elif symbol == "next":
        line(d, [(168, 146), (314, 256), (168, 366)], ink, 36)
        line(d, [(286, 146), (394, 256), (286, 366)], ink2, 26)
    elif symbol == "back":
        line(d, [(344, 146), (198, 256), (344, 366)], ink, 36)
        line(d, [(226, 146), (118, 256), (226, 366)], ink2, 26)
    elif symbol == "cancel":
        line(d, [(164, 164), (348, 348)], ink, 34)
        line(d, [(348, 164), (164, 348)], ink2, 34)
    elif symbol == "refresh":
        d.arc((132, 132, 380, 380), 40, 330, fill=ink, width=28)
        d.polygon([(338, 126), (406, 160), (338, 204)], fill=ink)
    elif symbol == "list":
        for y in (166, 256, 346):
            d.ellipse((126, y - 16, 158, y + 16), fill=ink2)
            line(d, [(188, y), (388, y)], ink, 22)
    elif symbol == "document":
        d.rounded_rectangle((146, 112, 350, 400), radius=26, fill=ink)
        d.polygon([(300, 112), (350, 112), (350, 166)], fill=accent)
        for y in (204, 250, 296):
            line(d, [(184, y), (314, y)], dark, 12)
    elif symbol == "table":
        d.rounded_rectangle((122, 144, 390, 366), radius=28, fill=ink)
        for x in (210, 300):
            line(d, [(x, 158), (x, 352)], dark, 10)
        for y in (220, 292):
            line(d, [(136, y), (376, y)], dark, 10)
    elif symbol == "transfer":
        line(d, [(138, 202), (356, 202)], ink, 24)
        d.polygon([(356, 154), (416, 202), (356, 250)], fill=ink)
        line(d, [(374, 310), (156, 310)], ink2, 24)
        d.polygon([(156, 262), (96, 310), (156, 358)], fill=ink2)
    elif symbol == "hourglass":
        d.polygon([(158, 124), (354, 124), (294, 252), (354, 388), (158, 388), (218, 252)], fill=ink)
        d.polygon([(204, 162), (308, 162), (256, 236)], fill=accent)
        d.polygon([(214, 350), (298, 350), (256, 278)], fill=accent)
    elif symbol == "warning":
        d.polygon([(256, 116), (404, 380), (108, 380)], fill=ink)
        line(d, [(256, 198), (256, 292)], dark, 22)
        d.ellipse((242, 324, 270, 352), fill=dark)
    elif symbol == "pause":
        d.rounded_rectangle((162, 142, 226, 370), radius=18, fill=ink)
        d.rounded_rectangle((286, 142, 350, 370), radius=18, fill=ink2)
    elif symbol == "play":
        d.polygon([(176, 130), (386, 256), (176, 382)], fill=ink)
    elif symbol == "stop":
        d.rounded_rectangle((154, 154, 358, 358), radius=36, fill=ink)
    elif symbol == "partial":
        d.pieslice((128, 128, 384, 384), -90, 90, fill=ink)
        d.pieslice((128, 128, 384, 384), 90, 270, fill=accent)
        d.ellipse((184, 184, 328, 328), fill=dark)
    elif symbol == "minus":
        line(d, [(154, 256), (358, 256)], ink, 38)
    elif symbol == "link":
        d.ellipse((126, 154, 286, 314), outline=ink, width=26)
        d.ellipse((226, 198, 386, 358), outline=ink2, width=26)
        line(d, [(216, 276), (296, 236)], accent, 18)


def render_icon(symbol: str, color: str, badge: bool = False) -> Image.Image:
    base = Image.new("RGBA", (512, 512), (0, 0, 0, 0))
    if badge:
        rounded_layer(base, (104, 150, 408, 362), color, 80)
    else:
        rounded_layer(base, (108, 108, 404, 404), color, 82)
    draw_symbol(base, symbol, color)
    return base


def status_spec(stem: str) -> tuple[str, str]:
    key = stem.lower()
    for marker, spec in STATUS_RULES.items():
        if marker in key:
            return spec
    return "status", BASE_COLORS["attention"]


def collect_specs() -> dict[str, tuple[str, str, bool]]:
    specs: dict[str, tuple[str, str, bool]] = {}
    for stem, (symbol, color) in ICON_SPECS.items():
        specs[stem] = (symbol, color, False)
    for path in ICON_DIR.glob("status_*.png"):
        stem = path.stem
        symbol, color = status_spec(stem)
        specs[stem] = (symbol, color, stem.endswith("_badge"))
    for key in EXTRA_STATUS_KEYS:
        stem = f"status_{key.lower()}"
        symbol, color = status_spec(stem)
        specs[stem] = (symbol, color, False)
        specs[f"{stem}_badge"] = (symbol, color, True)
    return specs


def save_icon(stem: str, image: Image.Image):
    ICON_DIR.mkdir(parents=True, exist_ok=True)
    image.save(ICON_DIR / f"{stem}.png")
    for size in SIZES:
        target_dir = ICON_DIR / "premium" / str(size)
        target_dir.mkdir(parents=True, exist_ok=True)
        resized = image.resize((size, size), Image.Resampling.LANCZOS)
        resized.save(target_dir / f"{stem}.png")


def build_previews(specs: dict[str, tuple[str, str, bool]]):
    for filename, stems in {
        "preview_icones_profissionais.png": [
            "area_controle_geral",
            "area_producao",
            "area_galvanizacao",
            "area_expedicao",
            "area_almoxarifado",
            "sistema_fiscal",
            "sistema_relatorios",
            "sistema_configuracoes",
            "sistema_backup",
            "sistema_banco_sqlite",
            "sistema_historico",
            "sistema_usuarios",
        ],
        "preview_status_badges.png": [
            "status_aguardando",
            "status_finalizado",
            "status_entregue",
            "status_cancelado",
            "status_parcial",
            "status_em_galvanizacao",
            "status_em_expedicao",
            "status_pendente",
        ],
    }.items():
        tile = 128
        cols = 4
        rows = math.ceil(len(stems) / cols)
        sheet = Image.new("RGBA", (cols * tile, rows * tile), (0, 0, 0, 0))
        for idx, stem in enumerate(stems):
            if stem not in specs:
                continue
            icon = Image.open(ICON_DIR / f"{stem}.png").resize((96, 96), Image.Resampling.LANCZOS)
            x = (idx % cols) * tile + 16
            y = (idx // cols) * tile + 16
            sheet.alpha_composite(icon, (x, y))
        sheet.save(ICON_DIR / filename)


def main() -> None:
    specs = collect_specs()
    for stem, (symbol, color, badge) in sorted(specs.items()):
        save_icon(stem, render_icon(symbol, color, badge))
    build_previews(specs)
    print(f"Generated {len(specs)} premium icons in {ICON_DIR}")
    print("Sizes:", ", ".join(str(size) for size in SIZES))


if __name__ == "__main__":
    main()
