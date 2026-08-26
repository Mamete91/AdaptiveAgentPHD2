"""
test_client_reconnect.py — §105, la connessione caduta deve dichiararsi caduta.

Il loop principale (`main.py`) e' l'UNICO a decidere la riconnessione, e lo fa
guardando `client.connected`:

    while not stop_event.is_set() and client.connected:

Se il thread lettore muore lasciando il flag a True, l'agente resta vivo ma
inerte, in attesa di eventi che non arriveranno mai. E' successo il 24/08/2026:
la camera di guida si e' disconnessa alle 00:17, il socket e' caduto alle
00:19:37, e fino alle 01:10:58 l'agente ha scritto **due righe di log in 51
minuti** — nessun tentativo di riconnessione, nessun avviso.

La chiusura pulita (recv -> b"") il flag lo abbassava gia'. Il ramo di ERRORE no.
"""
from __future__ import annotations

import socket
import unittest
from unittest.mock import MagicMock

from phd2_agent.client import PHD2Client


def _client_agganciato(sock) -> PHD2Client:
    """Un client con il socket sostituito, senza toccare la rete."""
    c = PHD2Client(host="127.0.0.1", port=4400)
    c._sock = sock
    c._running = True
    c.connected = True
    return c


class TestConnessioneCaduta(unittest.TestCase):

    def test_errore_socket_marca_la_connessione_come_caduta(self):
        """Il caso reale: OSError dalla recv (camera persa, PHD2 che chiude male)."""
        sock = MagicMock()
        sock.recv.side_effect = OSError("[WinError 10054] connessione interrotta")
        c = _client_agganciato(sock)
        c._reader_loop()
        self.assertFalse(c.connected,
                         "senza questo flag il loop principale non riconnette mai")

    def test_chiusura_pulita_marca_la_connessione_come_caduta(self):
        """Regressione sul ramo che gia' funzionava: non deve rompersi."""
        sock = MagicMock()
        sock.recv.return_value = b""
        c = _client_agganciato(sock)
        c._reader_loop()
        self.assertFalse(c.connected)

    def test_timeout_del_socket_e_un_oserror(self):
        """`socket.timeout` eredita da OSError: anche quello e' una caduta."""
        sock = MagicMock()
        sock.recv.side_effect = socket.timeout("timed out")
        c = _client_agganciato(sock)
        c._reader_loop()
        self.assertFalse(c.connected)

    def test_disconnessione_volontaria_non_tocca_nulla(self):
        """Con `_running` gia' False la chiusura e' NOSTRA: il ciclo non parte
        (`while self._running and self._sock`) e i flag li gestisce `disconnect()`.
        Nessun ERROR nel log, nessuna lettura dal socket."""
        sock = MagicMock()
        sock.recv.side_effect = OSError("non deve mai essere chiamata")
        c = _client_agganciato(sock)
        c._running = False
        c._reader_loop()
        sock.recv.assert_not_called()

    def test_disconnect_abbassa_entrambi_i_flag(self):
        """Il percorso volontario resta di competenza di `disconnect()`."""
        sock = MagicMock()
        c = _client_agganciato(sock)
        c._reader_thread = None
        c.disconnect()
        self.assertFalse(c.connected)
        self.assertFalse(c._running)

    def test_il_loop_principale_esce_quando_la_connessione_cade(self):
        """Contratto con main.py: `while not stop_event.is_set() and client.connected`."""
        sock = MagicMock()
        sock.recv.side_effect = OSError("caduta")
        c = _client_agganciato(sock)
        giri = 0
        c._reader_loop()
        while c.connected and giri < 5:
            giri += 1
        self.assertEqual(giri, 0, "il loop principale deve uscire al primo controllo")


if __name__ == "__main__":
    unittest.main()
