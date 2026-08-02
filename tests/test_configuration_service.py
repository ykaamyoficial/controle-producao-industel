from __future__ import annotations

import json
import os
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from app.services import configuration_service
from app.services.configuration_service import ConfigurationService, get_configuration_service


class LoadTests(unittest.TestCase):
    def test_reads_existing_valid_file(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "config.json"
            path.write_text(json.dumps({"company": "Industel"}), encoding="utf-8")
            service = ConfigurationService(path)

            self.assertEqual(service.load(), {"company": "Industel"})

    def test_missing_file_is_created_automatically_with_defaults(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "subdir" / "config.json"
            service = ConfigurationService(path)

            data = service.load()

            self.assertEqual(data, {})
            self.assertTrue(path.exists(), "o arquivo deveria ter sido criado automaticamente ao carregar")
            self.assertEqual(json.loads(path.read_text(encoding="utf-8")), {})

    def test_corrupted_json_returns_defaults_and_preserves_original_file(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "config.json"
            path.write_text("{ isto nao e json valido", encoding="utf-8")
            service = ConfigurationService(path)

            data = service.load()

            self.assertEqual(data, {})
            self.assertEqual(path.read_text(encoding="utf-8"), "{ isto nao e json valido", "o arquivo corrompido original nao pode ser sobrescrito so por uma leitura")

    def test_non_dict_json_root_is_treated_as_invalid(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "config.json"
            path.write_text(json.dumps([1, 2, 3]), encoding="utf-8")
            service = ConfigurationService(path)

            data = service.load()

            self.assertEqual(data, {})
            self.assertEqual(json.loads(path.read_text(encoding="utf-8")), [1, 2, 3], "arquivo com raiz invalida (lista) nao pode ser sobrescrito so por uma leitura")

    def test_load_returns_independent_copy_not_internal_cache(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "config.json"
            path.write_text(json.dumps({"nested": {"value": 1}}), encoding="utf-8")
            service = ConfigurationService(path)

            first = service.load()
            first["nested"]["value"] = 999
            second = service.load()

            self.assertEqual(second["nested"]["value"], 1, "mutar o dict retornado por load() nao pode corromper o cache interno")

    def test_second_load_uses_cache_instead_of_reopening_file(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "config.json"
            path.write_text(json.dumps({"company": "Industel"}), encoding="utf-8")
            service = ConfigurationService(path)
            service.load()

            with patch.object(Path, "open", side_effect=AssertionError("nao deveria reabrir o arquivo com cache quente")):
                data = service.load()

            self.assertEqual(data, {"company": "Industel"})


class SaveTests(unittest.TestCase):
    def test_save_writes_file_and_updates_cache(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "config.json"
            service = ConfigurationService(path)

            result = service.save({"company": "Industel", "color_palette": "escuro"})

            self.assertEqual(result, {"company": "Industel", "color_palette": "escuro"})
            self.assertEqual(json.loads(path.read_text(encoding="utf-8")), {"company": "Industel", "color_palette": "escuro"})
            self.assertEqual(service.load(), {"company": "Industel", "color_palette": "escuro"})

    def test_save_rejects_non_dict_payload(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            service = ConfigurationService(Path(temp_dir) / "config.json")
            with self.assertRaises(TypeError):
                service.save(["not", "a", "dict"])

    def test_write_is_atomic_no_leftover_temp_files(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "config.json"
            service = ConfigurationService(path)

            service.save({"a": 1})

            leftover = [entry for entry in os.listdir(temp_dir) if entry != "config.json"]
            self.assertEqual(leftover, [], "nenhum arquivo temporario deveria sobrar apos uma gravacao bem-sucedida")

    def test_write_failure_leaves_original_file_intact(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "config.json"
            path.write_text(json.dumps({"company": "Industel"}), encoding="utf-8")
            service = ConfigurationService(path)
            service.load()

            with patch("app.services.configuration_service.os.replace", side_effect=OSError("disco cheio")):
                with self.assertRaises(OSError):
                    service.save({"company": "Outra"})

            self.assertEqual(json.loads(path.read_text(encoding="utf-8")), {"company": "Industel"}, "o arquivo original nao pode ser perdido se a gravacao falhar")
            self.assertEqual(service.load(), {"company": "Industel"}, "o cache tambem nao pode refletir uma gravacao que falhou")
            leftover = [entry for entry in os.listdir(temp_dir) if entry != "config.json"]
            self.assertEqual(leftover, [], "o arquivo temporario deveria ser limpo mesmo apos falha no replace")


class UpdateTests(unittest.TestCase):
    def test_update_changes_only_targeted_keys(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "config.json"
            service = ConfigurationService(path)
            service.save({"company": "Industel", "color_palette": "claro", "saved_reports": [1, 2, 3]})

            service.update(lambda cfg: cfg.update({"color_palette": "escuro"}))

            data = service.load()
            self.assertEqual(data["color_palette"], "escuro")
            self.assertEqual(data["company"], "Industel", "atualizacao parcial nao pode perder outras chaves existentes")
            self.assertEqual(data["saved_reports"], [1, 2, 3])

    def test_update_mutator_can_return_replacement_dict(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            service = ConfigurationService(Path(temp_dir) / "config.json")
            service.save({"a": 1})

            service.update(lambda cfg: {"b": 2})

            self.assertEqual(service.load(), {"b": 2})

    def test_update_rejects_non_dict_result(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            service = ConfigurationService(Path(temp_dir) / "config.json")
            with self.assertRaises(TypeError):
                service.update(lambda cfg: ["nope"])

    def test_failed_mutator_does_not_partially_persist(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "config.json"
            service = ConfigurationService(path)
            service.save({"desktop_api": {"enabled": False}})

            def _boom(cfg):
                cfg["desktop_api"]["enabled"] = True
                raise RuntimeError("falha no meio da mutacao")

            with self.assertRaises(RuntimeError):
                service.update(_boom)

            self.assertEqual(service.load(), {"desktop_api": {"enabled": False}}, "uma mutacao que falha no meio nao pode gravar estado parcial")


class ConcurrencyTests(unittest.TestCase):
    def test_concurrent_updates_to_the_same_counter_are_not_lost(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            service = ConfigurationService(Path(temp_dir) / "config.json")
            service.save({"counter": 0})

            def _increment(cfg):
                # atraso deliberado entre ler e escrever o contador: sem o lock
                # do update(), duas threads leriam o mesmo valor e uma
                # incrementacao se perderia.
                current = cfg.get("counter", 0)
                threading.Event().wait(0.002)
                cfg["counter"] = current + 1

            threads = [threading.Thread(target=lambda: service.update(_increment)) for _ in range(30)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()

            self.assertEqual(service.load()["counter"], 30, "nenhuma atualizacao concorrente pode se perder")

    def test_concurrent_writes_to_different_keys_all_survive(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            service = ConfigurationService(Path(temp_dir) / "config.json")
            service.save({})

            def _write_key(key, value):
                def _apply(cfg):
                    threading.Event().wait(0.002)
                    cfg[key] = value
                service.update(_apply)

            keys = {f"key_{i}": i for i in range(20)}
            threads = [threading.Thread(target=_write_key, args=(key, value)) for key, value in keys.items()]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()

            self.assertEqual(service.load(), keys, "gravacoes concorrentes em chaves diferentes nao podem se sobrescrever")

    def test_concurrent_save_and_update_never_corrupt_the_file(self):
        # Mistura deliberada de save() (sobrescrita completa) com update()
        # (parcial atomica) na mesma instancia. save() NAO protege contra um
        # chamador que leu um snapshot desatualizado (ver docstring de
        # ConfigurationService.save) — entao aqui so garantimos a invariante
        # que save() de fato oferece sob concorrencia: o arquivo nunca fica
        # com JSON invalido/corrompido (gravacao truncada, mistura de duas
        # gravacoes), mesmo quando dois tipos de escrita competem. A
        # invariante "nenhuma atualizacao se perde" e testada separadamente
        # acima, apenas com update() — o unico metodo que promete isso.
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "config.json"
            service = ConfigurationService(path)
            service.save({"hits": 0})

            errors = []

            def _saver():
                for _ in range(15):
                    try:
                        current = service.load()
                        current["last_saver"] = threading.get_ident()
                        service.save(current)
                    except Exception as exc:  # pragma: no cover - defensivo
                        errors.append(exc)

            def _updater():
                for _ in range(15):
                    try:
                        service.update(lambda cfg: cfg.__setitem__("hits", cfg.get("hits", 0) + 1))
                    except Exception as exc:  # pragma: no cover - defensivo
                        errors.append(exc)

            threads = [threading.Thread(target=_saver) for _ in range(3)] + [threading.Thread(target=_updater) for _ in range(3)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()

            self.assertEqual(errors, [])
            # o arquivo no disco precisa continuar sendo um JSON valido a
            # qualquer momento apos escritas concorrentes — nunca truncado
            # nem misturado entre duas gravacoes.
            on_disk = json.loads(path.read_text(encoding="utf-8"))
            self.assertIsInstance(on_disk, dict)
            self.assertIn("hits", on_disk)
            leftover = [entry for entry in os.listdir(temp_dir) if entry != "config.json"]
            self.assertEqual(leftover, [], "nenhum arquivo temporario deveria sobrar apos a corrida de escritas")

    def test_concurrent_updates_survive_interleaved_saves_of_unrelated_keys(self):
        # Aqui SIM exigimos que nenhum incremento se perca, porque as duas
        # threads usam update() em chaves diferentes — o cenario real que a
        # ETAPA 2 corrige (ex.: tema sendo salvo enquanto a API desktop e
        # testada em outra tela).
        with tempfile.TemporaryDirectory() as temp_dir:
            service = ConfigurationService(Path(temp_dir) / "config.json")
            service.save({"hits": 0, "pings": 0})

            def _bump(key):
                for _ in range(15):
                    service.update(lambda cfg, k=key: cfg.__setitem__(k, cfg.get(k, 0) + 1))

            threads = [threading.Thread(target=_bump, args=("hits",)) for _ in range(3)] + [
                threading.Thread(target=_bump, args=("pings",)) for _ in range(3)
            ]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()

            data = service.load()
            self.assertEqual(data["hits"], 45)
            self.assertEqual(data["pings"], 45)


class RegistryTests(unittest.TestCase):
    def test_same_path_returns_the_same_instance(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "config.json"
            self.assertIs(get_configuration_service(path), get_configuration_service(path))

    def test_equivalent_paths_share_the_same_instance(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            direct = Path(temp_dir) / "config.json"
            with_dotdot = Path(temp_dir) / "sub" / ".." / "config.json"
            self.assertIs(get_configuration_service(direct), get_configuration_service(with_dotdot))

    def test_different_paths_get_independent_instances(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            service_a = get_configuration_service(Path(temp_dir) / "a.json")
            service_b = get_configuration_service(Path(temp_dir) / "b.json")
            self.assertIsNot(service_a, service_b)

            service_a.save({"only": "a"})
            service_b.save({"only": "b"})

            self.assertEqual(service_a.load(), {"only": "a"})
            self.assertEqual(service_b.load(), {"only": "b"})

    def tearDown(self):
        # evita que instancias de outros testes desta classe (paths dentro de
        # tempdirs ja removidos) se acumulem indefinidamente no registro
        # global durante a execucao da suite.
        stale = [key for key, service in configuration_service._registry.items() if not service.path.parent.exists()]
        for key in stale:
            configuration_service._registry.pop(key, None)


if __name__ == "__main__":
    unittest.main()
