"""
test_focus_telemetry.py — §102 (Stadio B): lo stato del fuoco viaggia con la posa.

La notte 21-22/8 ha mostrato che un autofocus puo' spostare `star_count` del
21,8% su un filtro. Il conteggio stelle, da solo, non distingue "il cielo e'
cambiato" da "il fuoco e' cambiato". Con `focuser_position` e
`focuser_temperature` accanto a `star_count`/`bkg`/`hfr` la riga porta le due
dimensioni causali insieme.

**Nessuna causa e' codificata a priori, ed e' deliberato.** Una variazione di
posizione NON significa "autofocus": puo' essere l'offset del filtro (e non
tutti gli utenti usano gli offset), la compensazione termica, un autofocus per
HFR, per temperatura, per tempo, o un intervento manuale. Si registra il FATTO;
sara' il replay a stabilire la probabilita' della causa.

Due cose che il compilatore ha stabilito contro l'SDK pinnato 3.2.0.9001, e che
questi test fissano perche' non vadano perse:

  1. `FocuserParameter.Position` e' `int?` e `Temperature` e' `double`;
  2. `MechanicalPosition` **non esiste** su `FocuserParameter` — la domanda "se
     aggiunge informazione" si e' risolta alla radice.

Terza, e la piu' insidiosa: la temperatura puo' essere **negativa**. A 967 m di
quota il focheggiatore sta sotto zero per buona parte dell'inverno, e l'helper
storico del plugin (`AddIfNumber`, che pretende `value >= 0`) l'avrebbe scartata
in silenzio proprio nelle notti in cui la deriva termica conta di piu'.
"""
from __future__ import annotations

import csv as _csv
import tempfile
import unittest
from types import SimpleNamespace

from phd2_agent.logger import SessionLogger, _CSV_FIELDS
from phd2_agent.nina_indices import TransparencyTracker

NUOVE = ("focuser_position", "focuser_temperature")


class _Orologio:
    def __init__(self):
        self.t = 1_700_000_000.0

    def __call__(self):
        return self.t

    def avanza(self, minuti):
        self.t += minuti * 60.0


def _posa(stelle=1400, filtro="L", pos=None, temp=None, fondo=120.0):
    img = {"star_count": stelle, "median_adu": fondo, "filter": filtro,
           "hfr": 3.0, "image_type": "LIGHT"}
    if pos is not None:
        img["focuser_position"] = pos
    if temp is not None:
        img["focuser_temperature"] = temp
    return {"image": img, "context": {"target": "NGC 6888"}}


def _snapshot(tracker=None):
    from phd2_agent.analyzer import AnalysisSnapshot, SeeingCondition
    s = AnalysisSnapshot()
    s.condition = SeeingCondition.NOMINAL
    s.rms_total = 0.7
    s.frame_count = 30
    if tracker is not None:
        b = tracker.status_block()
        s.star_count = b.get("star_count")
        s.hfr_nina = b.get("hfr")
    return s


def _riga(pose):
    c = _Orologio()
    t = TransparencyTracker(enabled=True, now_fn=c)
    for p in pose:
        t.ingest(p)
        c.avanza(3.0)
    with tempfile.TemporaryDirectory() as d:
        lg = SessionLogger(csv_dir=d)
        lg.bind_controller(SimpleNamespace(
            transparency_tracker=t, diagnostic_engine=None,
            cfg=SimpleNamespace(thresholds=SimpleNamespace(rms_high=0.8, rms_low=0.35))))
        lg.log_snapshot(_snapshot(t), [])
        lg.close()
        with open(lg._csv_path, encoding="utf-8") as fh:
            return t.status_block(), list(_csv.DictReader(fh))[-1]


class TestColonne(unittest.TestCase):

    def test_esistono_e_stanno_col_gruppo_in_ombra(self):
        for c in NUOVE:
            self.assertIn(c, _CSV_FIELDS)
        self.assertLess(_CSV_FIELDS.index("focuser_temperature"),
                        _CSV_FIELDS.index("diag_state"))

    def test_mechanical_position_non_esiste(self):
        """Il compilatore ha stabilito che `FocuserParameter` non la espone.
        Se un giorno ricomparisse in questa lista sarebbe per un'assunzione,
        non per una verifica."""
        self.assertNotIn("mechanical_position", _CSV_FIELDS)

    def test_i_valori_arrivano_dal_tracker(self):
        b, r = _riga([_posa(pos=35435, temp=11.4)])
        self.assertEqual(float(r["focuser_position"]), 35435.0)
        self.assertEqual(float(r["focuser_temperature"]), 11.4)
        self.assertEqual(b["focuser_position"], 35435.0)


class TestTemperaturaNegativa(unittest.TestCase):
    """Il difetto piu' insidioso: a 967 m si va sotto zero, e l'helper storico
    del plugin scarta i valori negativi."""

    def test_sotto_zero_viene_registrata(self):
        _, r = _riga([_posa(pos=35400, temp=-4.2)])
        self.assertEqual(float(r["focuser_temperature"]), -4.2,
                         "una notte fredda non deve perdere la temperatura")

    def test_zero_e_un_valore_valido_non_un_assente(self):
        _, r = _riga([_posa(pos=35400, temp=0.0)])
        self.assertEqual(r["focuser_temperature"], "0.0")


class TestCausaNonCodificata(unittest.TestCase):
    """L'invariante di progetto: si registra il fatto, mai la causa."""

    def test_lo_stesso_movimento_puo_avere_cause_diverse(self):
        """Cambio filtro con offset e autofocus producono entrambi uno
        spostamento. Il CSV li rappresenta allo stesso modo — distinguerli e'
        compito del replay, non del logger."""
        _, offset = _riga([_posa(filtro="L", pos=35400, temp=11.0),
                           _posa(filtro="R", pos=35580, temp=11.0)])
        _, autofocus = _riga([_posa(filtro="L", pos=35400, temp=11.0),
                              _posa(filtro="L", pos=35580, temp=11.0)])
        self.assertEqual(offset["focuser_position"], autofocus["focuser_position"])

    def test_nessuna_decisione_legge_il_fuoco(self):
        import inspect
        from phd2_agent import controller
        src = inspect.getsource(controller)
        for c in NUOVE:
            self.assertNotIn(c, src,
                             f"{c} e' comparso nel controller: e' telemetria, non algoritmo")


class TestGraceful(unittest.TestCase):

    def test_senza_focheggiatore_le_colonne_restano_vuote(self):
        """Chi non ha un focheggiatore collegato non deve vedere errori: il
        plugin omette i campi, l'Agente lascia le colonne vuote."""
        _, r = _riga([_posa()])
        for c in NUOVE:
            self.assertEqual(r[c], "", f"{c} doveva restare vuota")

    def test_senza_tracker_non_si_rompe_nulla(self):
        with tempfile.TemporaryDirectory() as d:
            lg = SessionLogger(csv_dir=d)
            lg.bind_controller(SimpleNamespace(
                transparency_tracker=None, diagnostic_engine=None,
                cfg=SimpleNamespace(thresholds=SimpleNamespace(rms_high=0.8, rms_low=0.35))))
            lg.log_snapshot(_snapshot(), [])
            lg.close()
            with open(lg._csv_path, encoding="utf-8") as fh:
                r = list(_csv.DictReader(fh))[-1]
        for c in NUOVE:
            self.assertEqual(r[c], "")


if __name__ == "__main__":
    unittest.main()
