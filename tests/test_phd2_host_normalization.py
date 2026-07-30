"""
test_phd2_host_normalization.py — §69: "localhost" -> "127.0.0.1" verso PHD2.

Perche' e' SICURO (verificato sul sorgente PHD2 vendorizzato, event_server.cpp:2619):
il server eventi usa `wxIPV4address`, quindi ascolta SOLO su IPv4. Il tentativo IPv6
che Windows fa per primo risolvendo "localhost" non puo' MAI riuscire: e' latenza pura
(~2 s a connessione, misurati sui log del 29/7 perfino su un ECONNREFUSED).

L'invariante da non violare: normalizziamo l'INTENTO (loopback), mai la SCELTA — un
PHD2 su un'altra macchina deve restare intoccato.
"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from phd2_agent.config import PHD2Config, load_config


def _cfg_with(phd2_block: str):
    """Scrive un config.toml minimo e lo carica."""
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "config.toml"
        p.write_text(phd2_block, encoding="utf-8")
        return load_config(str(p))


class TestDefault(unittest.TestCase):

    def test_default_is_ipv4_loopback(self):
        self.assertEqual(PHD2Config().host, "127.0.0.1")

    def test_absent_section_uses_the_new_default(self):
        cfg = _cfg_with("[control]\ndry_run = true\n")
        self.assertEqual(cfg.phd2.host, "127.0.0.1")


class TestNormalization(unittest.TestCase):

    def test_localhost_is_normalized(self):
        for written in ("localhost", "LOCALHOST", "  localhost  "):
            cfg = _cfg_with(f'[phd2]\nhost = "{written}"\nport = 4400\n')
            self.assertEqual(cfg.phd2.host, "127.0.0.1",
                             f"'{written}' doveva essere normalizzato")

    def test_port_is_preserved(self):
        cfg = _cfg_with('[phd2]\nhost = "localhost"\nport = 4402\n')
        self.assertEqual(cfg.phd2.host, "127.0.0.1")
        self.assertEqual(cfg.phd2.port, 4402, "istanza PHD2 multipla: la porta resta")


class TestRemoteHostsUntouched(unittest.TestCase):
    """La regressione da evitare: rompere chi ha PHD2 su un'altra macchina."""

    def test_explicit_hosts_pass_through(self):
        for host in ("192.168.1.42", "10.0.0.7", "mini-pc.local",
                     "astro-server", "::1", "127.0.0.2"):
            cfg = _cfg_with(f'[phd2]\nhost = "{host}"\nport = 4400\n')
            self.assertEqual(cfg.phd2.host, host,
                             f"host esplicito '{host}' NON va toccato")

    def test_dashboard_bind_is_not_affected(self):
        """Il bind della dashboard e' un'ALTRA cosa: 0.0.0.0 = tutte le interfacce,
        cioe' la dashboard raggiungibile da LAN. Non deve cambiare mai."""
        cfg = _cfg_with('[phd2]\nhost = "localhost"\n[dashboard]\nhost = "0.0.0.0"\nport = 8080\n')
        self.assertEqual(cfg.phd2.host, "127.0.0.1")
        self.assertEqual(cfg.dashboard.host, "0.0.0.0",
                         "il bind della dashboard resta su tutte le interfacce")


if __name__ == "__main__":
    unittest.main()
