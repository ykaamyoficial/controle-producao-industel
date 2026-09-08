from __future__ import annotations

import unittest

from api.app.modules.chat.service import extract_links


class ExtractLinksTests(unittest.TestCase):
    def test_extracts_http_and_https_urls(self):
        body = "Segue o link http://industeltelecom.com.br/relatorio e tambem https://exemplo.com/doc?x=1"
        self.assertEqual(
            extract_links(body),
            ["http://industeltelecom.com.br/relatorio", "https://exemplo.com/doc?x=1"],
        )

    def test_ignores_text_without_scheme(self):
        self.assertEqual(extract_links("visite www.industeltelecom.com.br para saber mais"), [])

    def test_ignores_broken_text_that_only_mentions_http(self):
        self.assertEqual(extract_links("o protocolo http nao e uma URL sozinho"), [])

    def test_stops_url_at_whitespace_and_quotes(self):
        body = 'Confira: "https://exemplo.com/pagina" e depois volte'
        self.assertEqual(extract_links(body), ["https://exemplo.com/pagina"])

    def test_empty_or_none_body_returns_empty_list(self):
        self.assertEqual(extract_links(""), [])
        self.assertEqual(extract_links(None), [])

    def test_multiple_links_preserve_order(self):
        body = "https://a.com depois https://b.com e por fim https://c.com"
        self.assertEqual(extract_links(body), ["https://a.com", "https://b.com", "https://c.com"])


if __name__ == "__main__":
    unittest.main()
