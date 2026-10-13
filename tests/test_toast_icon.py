from __future__ import annotations

import unittest

from PIL import Image

from app.ui.app_icon import app_icon_path, toast_icon_path


class ToastIconTests(unittest.TestCase):
    def test_toast_icon_is_a_high_resolution_png_not_the_multi_size_ico(self):
        """O .ico faz o Windows usar o menor quadro e o logo do balao fica borrado."""
        path = toast_icon_path()
        self.assertEqual(path.suffix.lower(), ".png")
        self.assertNotEqual(path, app_icon_path())
        with Image.open(path) as image:
            self.assertGreaterEqual(min(image.size), 128)
            self.assertIn("A", image.mode)  # mantem a transparencia


if __name__ == "__main__":
    unittest.main()
