from pathlib import Path
import unittest

from PIL import Image

from app.ui.icons import ICON_FILES


ROOT = Path(__file__).resolve().parents[1]
ICON_DIR = ROOT / "app" / "assets" / "icons"
SIZES = (512, 256, 128, 64, 48, 32, 24, 16)
REPRESENTATIVE_ICONS = (
    "area_controle_geral.png",
    "area_producao.png",
    "area_galvanizacao.png",
    "area_expedicao.png",
    "area_almoxarifado.png",
    "sistema_fiscal.png",
    "sistema_relatorios.png",
    "sistema_configuracoes.png",
    "sistema_backup.png",
    "sistema_banco_postgresql.png",
    "sistema_historico.png",
    "sistema_usuarios.png",
    "sistema_auditoria.png",
    "acao_pesquisar.png",
    "acao_novo.png",
    "acao_remover.png",
    "acao_editar.png",
    "acao_salvar.png",
    "status_aguardando.png",
    "status_finalizado.png",
    "status_cancelado.png",
    "status_parcial.png",
    "status_cp_em_processamento.png",
    "status_disponivel_para_emissao.png",
    "status_pendencia_fiscal_critica.png",
    "status_nf_retirada_cliente.png",
)


class PremiumIconTests(unittest.TestCase):
    def test_premium_icon_pack_has_all_required_sizes(self):
        for filename in REPRESENTATIVE_ICONS:
            root_icon = ICON_DIR / filename
            self.assertTrue(root_icon.exists(), filename)
            for size in SIZES:
                sized_icon = ICON_DIR / "premium" / str(size) / filename
                self.assertTrue(sized_icon.exists(), f"{size}/{filename}")
                with Image.open(sized_icon) as image:
                    self.assertEqual(image.size, (size, size))
                    self.assertEqual(image.mode, "RGBA")

    def test_premium_icons_keep_transparent_background(self):
        for filename in REPRESENTATIVE_ICONS:
            with Image.open(ICON_DIR / filename) as image:
                self.assertEqual(image.mode, "RGBA")
                alpha = image.getchannel("A")
                self.assertEqual(alpha.getpixel((0, 0)), 0)
                self.assertEqual(alpha.getpixel((image.width - 1, image.height - 1)), 0)

    def test_fiscal_uses_dedicated_fiscal_icon(self):
        self.assertEqual(ICON_FILES["fiscal"], "sistema_fiscal.png")


if __name__ == "__main__":
    unittest.main()
