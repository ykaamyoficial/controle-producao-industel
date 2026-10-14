"""Guardas do refinamento visual: a acentuacao e so para texto EXIBIDO.

Valores de dado, chaves compostas e codigos (ex.: "situacao:CP_EM_PROCESSAMENTO",
"status_producao") precisam continuar exatamente como o servico/API espera.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

APP_DIR = Path(__file__).resolve().parents[1] / "app"
STRING_RE = re.compile(r"""'((?:[^'\\\n]|\\.)*)'|"((?:[^"\\\n]|\\.)*)\"""")
ACCENTED = re.compile(r"[áàâãéêíóôõúçÁÀÂÃÉÊÍÓÔÕÚÇ]")
SEPARATOR = re.compile(r"[_:=@#]")
# Texto exibido que legitimamente nao tem espaco mas tem separador.
ALLOWED = {
    "Número/Controle",
}


class DisplayOnlyAccentGuardTests(unittest.TestCase):
    def test_no_accent_inside_identifier_like_literals(self):
        offenders: list[str] = []
        for path in sorted((APP_DIR / "ui").rglob("*.py")):
            for number, line in enumerate(path.read_text(encoding="utf-8").split("\n"), start=1):
                for match in STRING_RE.finditer(line):
                    body = match.group(1) if match.group(1) is not None else match.group(2)
                    if body in ALLOWED or re.search(r"\s", body) or "\\" in body:
                        continue
                    if ACCENTED.search(body) and SEPARATOR.search(body):
                        offenders.append(f"{path.relative_to(APP_DIR.parent)}:{number}: {body}")
        self.assertEqual(offenders, [], "literal com cara de dado/chave ganhou acento")

    def test_fiscal_status_filter_values_are_untouched(self):
        source = (APP_DIR / "ui" / "fiscal_page.py").read_text(encoding="utf-8")
        for code in ("CP_EM_PROCESSAMENTO", "NF_EM_PROCESSAMENTO", "DISPONIVEL_PARA_EMISSAO", "PENDENCIA_FISCAL_CRITICA"):
            self.assertIn(f'"situacao:{code}"', source)
        self.assertIn('raw_status.startswith("situacao:")', source)

    def test_reliability_filter_sends_data_value_not_the_accented_label(self):
        # O filtro mandava `currentText().lower()`; com o rotulo "Média" isso
        # viraria "média" e deixaria de casar com a confiabilidade "media".
        source = (APP_DIR / "ui" / "executive_dashboard_page.py").read_text(encoding="utf-8")
        self.assertIn('("Confiabilidade média", "media")', source)
        self.assertIn("self.reliability_filter.currentData()", source)
        self.assertNotIn("reliability_filter.currentText()", source)

    def test_no_combo_text_is_lowercased_into_a_filter_value(self):
        offenders = [
            str(path.relative_to(APP_DIR.parent))
            for path in sorted((APP_DIR / "ui").rglob("*.py"))
            if re.search(r"currentText\(\)\.(lower|upper|casefold)\(\)", path.read_text(encoding="utf-8"))
        ]
        self.assertEqual(offenders, [], "use itemData/currentData para o valor do filtro")

    def test_status_label_keys_stay_ascii(self):
        from app.models.fiscal_table_model import FISCAL_STATUS_LABELS
        from app.services import backend_adapter as backend

        dictionaries = [backend.STATUS_LABELS, backend.LOAD_STATUS_LABELS, FISCAL_STATUS_LABELS]
        dictionaries.extend(backend.AREA_STATUS_LABEL_OVERRIDES.values())
        for mapping in dictionaries:
            for key in mapping:
                self.assertTrue(str(key).isascii(), key)
        for permission_key, _label, nav_key in backend.PERMISSION_AREAS:
            self.assertTrue(permission_key.isascii() and nav_key.isascii(), (permission_key, nav_key))


if __name__ == "__main__":
    unittest.main()
