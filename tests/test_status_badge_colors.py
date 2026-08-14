import unittest

from app.services.backend_adapter import OFFICIAL_COLOR_PALETTES
from app.ui.styles import status_color


class StatusBadgeColorTests(unittest.TestCase):
    def assert_status_colors(self, status: str, claro: str, escuro: str):
        self.assertEqual(status_color(status, OFFICIAL_COLOR_PALETTES["claro"])[0].upper(), claro)
        self.assertEqual(status_color(status, OFFICIAL_COLOR_PALETTES["escuro"])[0].upper(), escuro)

    def test_waiting_statuses_use_blue(self):
        self.assert_status_colors("NAO_INICIADO", "#2563EB", "#60A5FA")
        self.assert_status_colors("AGUARDANDO_ENVIO", "#2563EB", "#60A5FA")
        self.assert_status_colors("EM_SEPARACAO", "#2563EB", "#60A5FA")

    def test_in_progress_statuses_use_orange(self):
        self.assert_status_colors("INICIADO", "#EA580C", "#FB923C")
        self.assert_status_colors("EM_CARGA", "#EA580C", "#FB923C")
        self.assert_status_colors("SEPARACAO_INICIADA", "#EA580C", "#FB923C")

    def test_partial_and_pending_statuses_use_yellow(self):
        self.assert_status_colors("FINALIZADO_PARCIAL", "#CA8A04", "#FACC15")
        self.assert_status_colors("ITEM_PENDENTE_FABRICACAO", "#CA8A04", "#FACC15")
        self.assert_status_colors("NOTA_FISCAL_PARCIAL", "#CA8A04", "#FACC15")
        self.assert_status_colors("PARADO", "#CA8A04", "#FACC15")

    def test_completed_statuses_use_green(self):
        self.assert_status_colors("FINALIZADO", "#16A34A", "#4ADE80")
        self.assert_status_colors("FATURADO", "#16A34A", "#4ADE80")

    def test_final_delivered_statuses_use_teal(self):
        self.assert_status_colors("ENTREGUE", "#0F766E", "#2DD4BF")
        self.assert_status_colors("ALMOXARIFADO_ENTREGUE", "#0F766E", "#2DD4BF")

    def test_blocked_and_cancelled_statuses_use_red(self):
        self.assert_status_colors("SEM_PARAFUSOS", "#DC2626", "#FB7185")
        self.assert_status_colors("FALTA_EMITIR_NOTA_FISCAL", "#DC2626", "#FB7185")

    def test_neutral_and_unknown_statuses_use_neutral(self):
        self.assert_status_colors("NAO_LIBERADO", "#64748B", "#CBD5E1")
        self.assert_status_colors("STATUS_DESCONHECIDO", "#64748B", "#CBD5E1")

    def test_location_statuses_keep_area_identity(self):
        self.assert_status_colors("EM_PRODUCAO", "#047857", "#34D399")
        self.assert_status_colors("EM_GALVANIZACAO", "#7C3AED", "#A78BFA")
        self.assert_status_colors("EM_EXPEDICAO", "#C2410C", "#FB923C")
        self.assert_status_colors("UNIFICADA_PRINCIPAL", "#0369A1", "#38BDF8")


if __name__ == "__main__":
    unittest.main()
