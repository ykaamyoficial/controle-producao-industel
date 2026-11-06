import json
import os
import re
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app import edition
from app.integrations.api.config import DesktopApiConfigError, DesktopApiConfigStore, normalize_api_base_url
from app.services import app_paths, update_checker, update_distribution_client
from app.services.update_coordinator import UpdateCoordinator
from app.version import APP_VERSION

ROOT = Path(__file__).resolve().parent.parent
TEST_ENV = {edition.EDITION_ENV: "teste"}
PROD_ENV = {edition.EDITION_ENV: "producao"}

NAME_FUNCS = (
    edition.app_name, edition.launcher_exe_name, edition.app_exe_name, edition.updater_exe_name,
    edition.data_dir_name, edition.chat_cache_dir_name, edition.main_app_mutex_name,
    edition.notifier_mutex_name, edition.toast_app_id, edition.startup_run_value_name,
    edition.app_user_model_id, edition.default_install_dir,
)


def names(env):
    with patch.dict(os.environ, env):
        return [f() for f in NAME_FUNCS]


class EditionProductionTests(unittest.TestCase):
    def test_production_values_are_the_original_ones(self):
        self.assertEqual(
            names(PROD_ENV),
            ["Controle de Producao Industel", "ControleProducao.exe", "ControleProducaoApp.exe", "Updater.exe",
             "ControleProducao", "ControleProducaoIndustel", "Global\\ControleProducaoIndustel_MainAppRunning",
             "Global\\ControleProducaoIndustel_NotifierInstance", "Controle de Producao Industel",
             "ControleProducaoIndustelNotificacoes", "Industel.ControleProducao.2",
             r"C:\Program Files\Industel\Controle de Producao"],
        )

    def test_production_paths_unchanged(self):
        with patch.dict(os.environ, {**PROD_ENV, "ProgramData": r"C:\PD", "APPDATA": r"C:\AD"}), \
                patch.object(app_paths.sys, "frozen", True, create=True), \
                patch.dict(os.environ, {"CONTROLE_PRODUCAO_LOG_DIR": ""}):
            os.environ.pop("CONTROLE_PRODUCAO_DATA_DIR", None)
            os.environ.pop("CONTROLE_PRODUCAO_LOG_DIR", None)
            self.assertEqual(app_paths.get_app_data_dir(), Path(r"C:\PD") / "Industel" / "ControleProducao")
            self.assertEqual(app_paths.get_logs_dir(), Path(r"C:\AD") / "ControleProducao" / "logs")

    def test_default_edition_is_production(self):
        with patch.dict(os.environ):
            os.environ.pop(edition.EDITION_ENV, None)
            with patch.object(edition, "_edition_from_file", return_value=""):
                self.assertFalse(edition.is_test())
                self.assertTrue(edition.updates_enabled())


class EditionTestTests(unittest.TestCase):
    def test_test_values(self):
        self.assertEqual(
            names(TEST_ENV),
            ["Controle de Producao Industel TESTE", "ControleProducaoTeste.exe", "ControleProducaoTesteApp.exe",
             "UpdaterTeste.exe", "ControleProducaoTeste", "ControleProducaoIndustelTeste",
             "Global\\ControleProducaoIndustelTeste_MainAppRunning",
             "Global\\ControleProducaoIndustelTeste_NotifierInstance", "Controle de Producao Industel TESTE",
             "ControleProducaoIndustelTesteNotificacoes", "Industel.ControleProducaoTeste.2",
             r"C:\Program Files\Industel\Controle de Producao TESTE"],
        )

    def test_no_test_name_collides_with_production(self):
        for prod, test in zip(names(PROD_ENV), names(TEST_ENV)):
            self.assertNotEqual(prod.lower(), test.lower())

    def test_test_paths_are_separate(self):
        with patch.dict(os.environ, {**TEST_ENV, "ProgramData": r"C:\PD", "APPDATA": r"C:\AD"}), \
                patch.object(app_paths.sys, "frozen", True, create=True):
            os.environ.pop("CONTROLE_PRODUCAO_DATA_DIR", None)
            os.environ.pop("CONTROLE_PRODUCAO_LOG_DIR", None)
            self.assertEqual(app_paths.get_app_data_dir(), Path(r"C:\PD") / "Industel" / "ControleProducaoTeste")
            self.assertEqual(app_paths.get_logs_dir(), Path(r"C:\AD") / "ControleProducaoTeste" / "logs")

    def test_display_and_banner(self):
        with patch.dict(os.environ, TEST_ENV):
            self.assertIn("[TESTE]", edition.display_name())
            self.assertEqual(edition.test_banner_text(), "AMBIENTE DE TESTE · API dev producaodev.ykora.com.br")
            self.assertEqual(edition.test_banner_text("http://192.168.0.7:8001"), "AMBIENTE DE TESTE · API dev 192.168.0.7:8001")

    def _store(self, tmp, saved=None):
        path = Path(tmp) / "controle_producao_config.json"
        if saved is not None:
            path.write_text(json.dumps({"desktop_api": {"enabled": True, "base_url": saved}}), encoding="utf-8")
        return DesktopApiConfigStore(config_path=path)

    def test_default_api_is_dev_8001(self):
        with patch.dict(os.environ, {**TEST_ENV, "DESKTOP_API_BASE_URL": "http://127.0.0.1:8000"}), tempfile.TemporaryDirectory() as tmp:
            store = self._store(tmp)
            settings = store.load_settings()
            self.assertEqual(settings.base_url, "https://producaodev.ykora.com.br")
            self.assertTrue(settings.enabled)
            self.assertTrue(store.is_configured())

    def test_saved_url_from_other_host_is_honored_and_env_ignored(self):
        with patch.dict(os.environ, {**TEST_ENV, "DESKTOP_API_BASE_URL": "http://10.0.0.1:9999"}), tempfile.TemporaryDirectory() as tmp:
            store = self._store(tmp, "http://192.168.0.7:8001")
            self.assertEqual(store.load_settings().base_url, "http://192.168.0.7:8001")
            store.save_settings(enabled=True, base_url="http://servidor-dev:8002/")
            self.assertEqual(store.load_settings().base_url, "http://servidor-dev:8002")

    def test_official_port_and_invalid_urls_are_refused(self):
        with patch.dict(os.environ, TEST_ENV), tempfile.TemporaryDirectory() as tmp:
            store = self._store(tmp)
            for bad in ("http://127.0.0.1:8000", "http://192.168.0.7:8000/api", "ftp://x:8001", "sem-esquema:8001", "http://", ""):
                with self.assertRaises(DesktopApiConfigError, msg=bad):
                    normalize_api_base_url(bad)
                with self.assertRaises(DesktopApiConfigError, msg=bad):
                    store.save_settings(enabled=True, base_url=bad)
            with self.assertRaisesRegex(DesktopApiConfigError, "oficial"):
                normalize_api_base_url("http://127.0.0.1:8000")
            # config salva com a porta oficial (ex.: editada a mao) cai no padrao de dev
            self.assertEqual(self._store(tmp, "http://127.0.0.1:8000").load_settings().base_url, "https://producaodev.ykora.com.br")

    def test_production_is_unchanged(self):
        with patch.dict(os.environ, {**PROD_ENV, "DESKTOP_API_BASE_URL": "http://10.0.0.1:8000"}), tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(normalize_api_base_url("http://127.0.0.1:8000"), "http://127.0.0.1:8000")
            settings = self._store(tmp, "http://192.168.0.7:8000").load_settings()
            self.assertEqual(settings.base_url, "http://10.0.0.1:8000")
            self.assertFalse(self._store(tmp + "x").is_configured())

    def test_updates_are_disabled(self):
        with patch.dict(os.environ, TEST_ENV):
            def boom(*a, **k):
                raise AssertionError("nao pode consultar release")

            dist = update_distribution_client.check_for_updates(client_factory=boom, config_store_factory=boom)
            self.assertFalse(dist["update_available"])
            self.assertFalse(update_checker.check_for_updates(fetch_json=boom)["update_available"])
            for call in (lambda c: c.start_required_update(), lambda c: c.start_update(manifest_url="/m", package_url="/p")):
                result = call(UpdateCoordinator(config_store_factory=boom, client_factory=boom))
                self.assertFalse(result.launched)

    def test_version_suffix_does_not_touch_version_parsing(self):
        self.assertRegex(APP_VERSION, r"^\d+\.\d+\.\d+$")


class TestInstallerFileTests(unittest.TestCase):
    prod = (ROOT / "installer" / "ControleProducao.iss").read_text(encoding="utf-8")
    test = (ROOT / "installer" / "ControleProducaoTeste.iss").read_text(encoding="utf-8")

    def test_version_matches_app_version(self):
        self.assertIn(f'#define MyAppVersion "{APP_VERSION}"', self.test)
        self.assertIn(f"OutputBaseFilename=ControleProducaoTesteSetup-{APP_VERSION}", self.test)

    def test_identity_is_not_shared(self):
        guid = lambda s: re.search(r"AppId=\{\{([0-9A-F-]+)\}", s).group(1)
        self.assertNotEqual(guid(self.prod), guid(self.test))
        for forbidden in ("ControleProducao.exe", "ControleProducaoApp.exe", "Updater.exe", "dist\\", "ControleProducao\\"):
            self.assertNotIn(forbidden, self.test)
        self.assertNotIn(re.search(r"AppId=\{\{([0-9A-F-]+)\}", self.prod).group(1), self.test)

    def test_taskkill_targets_only_test_images(self):
        images = re.findall(r"KillByImageName\('([^']+)'\);", self.test)
        self.assertEqual(sorted(images), ["ControleProducaoTeste.exe", "ControleProducaoTesteApp.exe", "UpdaterTeste.exe"])

    def test_specs_default_to_production_names(self):
        main = (ROOT / "ControleProducao.spec").read_text(encoding="utf-8")
        self.assertIn("_S = 'Teste' if _EDITION == 'teste' else ''", main)
        self.assertIn("name='ControleProducao' + _S + 'App'", main)


if __name__ == "__main__":
    unittest.main()
