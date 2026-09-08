from __future__ import annotations

import unittest

from api.app.audit.sanitizer import sanitize_audit_metadata


class SensitiveKeyMaskingTests(unittest.TestCase):
    def test_password_and_ordinary_keys(self):
        result = sanitize_audit_metadata({"password": "abc123", "ok": "fine"})
        self.assertEqual(result, {"password": "***REDACTED***", "ok": "fine"})

    def test_case_insensitive_and_substring_match(self):
        result = sanitize_audit_metadata({"Authorization": "Bearer xyz", "user_api_key": "k1", "reason": "manual"})
        self.assertEqual(result["Authorization"], "***REDACTED***")
        self.assertEqual(result["user_api_key"], "***REDACTED***")
        self.assertEqual(result["reason"], "manual")

    def test_all_documented_markers_are_masked(self):
        keys = [
            "password", "senha", "token", "secret", "authorization", "cookie", "api_key", "apikey",
            "database_url", "connection_string", "jwt", "credential", "pat", "private_key", "access_key",
        ]
        payload = {key: "sensitive-value" for key in keys}
        result = sanitize_audit_metadata(payload)
        for key in keys:
            self.assertEqual(result[key], "***REDACTED***", key)

    def test_jwt_value_is_never_persisted_verbatim(self):
        token = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0.signature"
        result = sanitize_audit_metadata({"jwt": token, "refresh_token": token})
        self.assertNotIn(token, str(result))

    def test_masking_applies_inside_nested_dicts(self):
        result = sanitize_audit_metadata({"request": {"headers": {"authorization": "Bearer abc"}}})
        self.assertEqual(result["request"]["headers"]["authorization"], "***REDACTED***")


class LimitsTests(unittest.TestCase):
    def test_long_string_is_truncated(self):
        result = sanitize_audit_metadata({"note": "x" * 1000}, max_string_length=50)
        self.assertLessEqual(len(result["note"]), 50)
        self.assertTrue(result["note"].endswith("...<truncated>"))

    def test_too_many_keys_are_capped_with_marker(self):
        payload = {f"k{i}": i for i in range(100)}
        result = sanitize_audit_metadata(payload, max_keys=10)
        self.assertEqual(len(result) - 1, 10)  # 10 keys + _truncated_keys marker
        self.assertEqual(result["_truncated_keys"], 90)

    def test_depth_beyond_limit_is_replaced_with_placeholder(self):
        deep = {"a": {"b": {"c": {"d": "too deep"}}}}
        result = sanitize_audit_metadata(deep, max_depth=1)
        self.assertEqual(result["a"]["b"], "<profundidade maxima excedida>")

    def test_unsupported_type_is_replaced_not_raised(self):
        class Weird:
            pass

        result = sanitize_audit_metadata({"obj": Weird()})
        self.assertEqual(result["obj"], "<tipo nao suportado>")

    def test_lists_are_sanitized_and_capped(self):
        result = sanitize_audit_metadata({"items": list(range(50))}, max_keys=5)
        self.assertEqual(len(result["items"]), 5)


class InputShapeTests(unittest.TestCase):
    def test_none_input_returns_empty_dict(self):
        self.assertEqual(sanitize_audit_metadata(None), {})

    def test_non_dict_input_is_wrapped_in_value_key(self):
        result = sanitize_audit_metadata("just a string")
        self.assertEqual(result, {"value": "just a string"})

    def test_never_raises_for_arbitrary_garbage(self):
        class Cyclic(dict):
            pass

        garbage = Cyclic()
        garbage["self"] = garbage
        try:
            sanitize_audit_metadata(garbage, max_depth=2)
        except Exception as exc:  # pragma: no cover - only fails the test
            self.fail(f"sanitize_audit_metadata levantou excecao inesperada: {exc}")


if __name__ == "__main__":
    unittest.main()
