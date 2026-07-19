"""
test_about.py — Test sulla single source of truth del branding (§26).

Verifica che il modulo `phd2_agent.__about__` esponga tutte le costanti
attese, che il banner d'avvio sia ben formato, che il payload `/about` non
contenga campi email (regressione esplicita), e che `phd2_agent/__init__.py`
ri-esporti correttamente le costanti principali.
"""
from __future__ import annotations

import re
import unittest

from phd2_agent import __about__ as about


EXPECTED_TELEGRAM = "https://t.me/+eewRNpvElSs5OWY8"


class TestConstantsExist(unittest.TestCase):
    """1. Tutte le costanti esistono, sono stringhe non vuote, NIENTE email."""

    def test_required_constants_present(self):
        for name in (
            "__project_name__",
            "__short_name__",
            "__author__",
            "__version__",
            "__copyright__",
            "__license__",
            "__contact_telegram__",
        ):
            self.assertTrue(hasattr(about, name), f"manca {name}")
            value = getattr(about, name)
            self.assertIsInstance(value, str, f"{name} non è stringa")
            self.assertGreater(len(value), 0, f"{name} è stringa vuota")

    def test_no_email_field_exists(self):
        """Anti-regressione: il campo __contact_email__ NON deve esistere."""
        self.assertFalse(
            hasattr(about, "__contact_email__"),
            "Regressione: __contact_email__ re-introdotto. "
            "L'unico canale di contatto deve essere il gruppo Telegram.",
        )


class TestVersionFormat(unittest.TestCase):
    """2. Formato di __version__ e __version_tuple__."""

    def test_version_string_format(self):
        # §63 — ammesso anche il livello patch (es. "2.8.1" per gli hotfix):
        # major.minor per le milestone, major.minor.patch per le correzioni.
        self.assertRegex(about.__version__, r"^\d+\.\d+(\.\d+)?$")

    def test_version_tuple_consistent(self):
        self.assertIsInstance(about.__version_tuple__, tuple)
        self.assertEqual(len(about.__version_tuple__), 4)
        for n in about.__version_tuple__:
            self.assertIsInstance(n, int)
        # Le componenti della stringa corrispondono alla tupla, posizione per
        # posizione (patch assente nella stringa => 0 nella tupla).
        parts = [int(p) for p in about.__version__.split(".")]
        for i, val in enumerate(parts):
            self.assertEqual(about.__version_tuple__[i], val)
        for i in range(len(parts), 3):
            self.assertEqual(about.__version_tuple__[i], 0)


class TestBannerShape(unittest.TestCase):
    """3. banner_lines() ben formato, contiene URL Telegram, niente email."""

    def setUp(self):
        self.lines = about.banner_lines()

    def test_lines_non_empty(self):
        self.assertIsInstance(self.lines, list)
        self.assertGreater(len(self.lines), 0)
        for line in self.lines:
            self.assertIsInstance(line, str)

    def test_lines_contain_identity(self):
        joined = "\n".join(self.lines)
        self.assertIn(about.__project_name__, joined)
        self.assertIn(about.__author__, joined)
        self.assertIn(about.__version__, joined)
        self.assertIn(about.__copyright__, joined)
        self.assertIn(EXPECTED_TELEGRAM, joined)

    def test_delimiters_match(self):
        """La prima e l'ultima riga (delimitatori `=...=`) devono coincidere."""
        self.assertTrue(self.lines[0].startswith("="))
        self.assertEqual(self.lines[0], self.lines[-1])

    def test_no_email_in_banner(self):
        """Anti-regressione: nessuna riga contiene '@' o 'mail' (case-insensitive)."""
        joined = "\n".join(self.lines).lower()
        self.assertNotIn("@", joined,
                         "Trovato '@' nel banner: probabile leak di email.")
        self.assertNotIn("mail", joined,
                         "Trovato 'mail' nel banner: probabile leak di email.")


class TestAboutPayloadKeys(unittest.TestCase):
    """4. about_payload() ritorna esattamente le chiavi documentate, niente email."""

    def setUp(self):
        self.payload = about.about_payload()

    def test_payload_is_dict(self):
        self.assertIsInstance(self.payload, dict)

    def test_payload_exact_keys(self):
        expected = {
            "project_name", "short_name", "author", "version",
            "copyright", "license", "contact_telegram",
        }
        self.assertEqual(set(self.payload.keys()), expected)

    def test_payload_no_email_key(self):
        """Anti-regressione esplicita."""
        self.assertNotIn("contact_email", self.payload)

    def test_payload_telegram_url(self):
        self.assertEqual(self.payload["contact_telegram"], EXPECTED_TELEGRAM)


class TestInitReexports(unittest.TestCase):
    """5. phd2_agent package ri-esporta correttamente."""

    def test_reexports(self):
        from phd2_agent import (
            __project_name__, __author__, __version__,
            __contact_telegram__,
        )
        self.assertEqual(__project_name__, about.__project_name__)
        self.assertEqual(__author__, about.__author__)
        self.assertEqual(__version__, about.__version__)
        self.assertEqual(__contact_telegram__, EXPECTED_TELEGRAM)


if __name__ == "__main__":
    unittest.main()
