"""
test_setup_config.py — Test unitari per SetupConfig e il toggle reducer_active.
"""
from __future__ import annotations

import unittest

from phd2_agent.config import SetupConfig


class TestSetupConfig(unittest.TestCase):

    def test_pixel_scale_native(self):
        """reducer_active=False → ritorna il valore native"""
        s = SetupConfig(
            profile_name="rc8",
            guide_pixel_scale_arcsec_native=0.51,
            guide_pixel_scale_arcsec_reduced=0.68,
            reducer_active=False,
        )
        self.assertAlmostEqual(s.guide_pixel_scale_arcsec, 0.51)

    def test_pixel_scale_reduced(self):
        """reducer_active=True → ritorna il valore reduced"""
        s = SetupConfig(
            profile_name="rc8",
            guide_pixel_scale_arcsec_native=0.51,
            guide_pixel_scale_arcsec_reduced=0.68,
            reducer_active=True,
        )
        self.assertAlmostEqual(s.guide_pixel_scale_arcsec, 0.68)

    def test_default_values_safe(self):
        """SetupConfig() di default non deve causare divisioni per zero"""
        s = SetupConfig()
        self.assertGreater(s.guide_pixel_scale_arcsec, 0.0)
        self.assertEqual(s.reducer_active, False)
        # Override runtime di default disattivo
        self.assertIsNone(s.pixel_scale_override)

    def test_pixel_scale_override_wins(self):
        """pixel_scale_override valorizzato ha priorità su native/reduced."""
        s = SetupConfig(
            guide_pixel_scale_arcsec_native=0.51,
            guide_pixel_scale_arcsec_reduced=0.68,
            reducer_active=True,   # ignorato quando c'è override
        )
        s.pixel_scale_override = 1.03
        self.assertAlmostEqual(s.guide_pixel_scale_arcsec, 1.03)
        # Rimosso l'override → torna al comportamento TOML (reduced)
        s.pixel_scale_override = None
        self.assertAlmostEqual(s.guide_pixel_scale_arcsec, 0.68)


if __name__ == "__main__":
    unittest.main()
