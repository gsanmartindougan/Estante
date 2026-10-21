from unittest import TestCase
from unittest.mock import patch
from estante import blur_radius


class BlurDiagnosticsTests(TestCase):
    def test_default_preserves_all_existing_blur_radii(self):
        with patch.dict('os.environ', {'ESTANTE_DISABLE_BLUR': '0'}):
            self.assertEqual([blur_radius(value) for value in (18, 32, 38)], [18, 32, 38])

    def test_comparison_disables_all_blur_without_changing_settings(self):
        with patch.dict('os.environ', {'ESTANTE_DISABLE_BLUR': '1'}):
            self.assertEqual([blur_radius(value) for value in (18, 32, 38)], [0, 0, 0])
