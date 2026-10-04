"""
test_ga_baseline.py — §104, baseline dal Guiding Assistant di PHD2.

Copre le tre parti che possono rompersi in silenzio:

  1. il PARSING del file prodotto da `export_config_settings` (formato reale,
     campi formattati per la lettura umana, campi non inizializzati);
  2. i CRITERI di accettazione di una caratterizzazione;
  3. la GERARCHIA a tre livelli, che non deve mai lasciare l'Agente senza un
     nominale utilizzabile.

I campioni provengono dal profilo reale "CEM70 RC8": quattro esecuzioni del GA
fra aprile e agosto 2026, con SNR 18.8 / 33.6 / 44.0 / 64.9.
"""
from __future__ import annotations

import datetime as dt
import pathlib
import unittest

from phd2_agent import ga_baseline as gb


# Estratto FEDELE del file esportato da PHD2 (chiave <TAB> tipo <TAB> valore).
# Include di proposito: il campo BLT_pulse non inizializzato dell'esecuzione senza
# test di backlash, i campi formattati con unita', e un secondo profilo da ignorare.
# --------------------------------------------------------------------------- #
#  DATI REALI — non toccare a mano.                                            #
#                                                                              #
#  `_fixture_export_reale.txt` e' l'export vero del profilo CEM70 RC8, preso    #
#  dal Minix100 il 26/08/2026 chiamando `export_config_settings` su PHD2 2.6.14 #
#  e ripulito delle sole righe che non leggiamo (serie BLT_north/South e il     #
#  testo delle raccomandazioni, lunghissimi e inutili qui).                     #
#                                                                              #
#  Perche' un file e non una stringa: la fixture precedente era una copia       #
#  scritta a mano mesi fa, e nel frattempo PHD2 — che tiene solo TRE            #
#  caratterizzazioni — aveva buttato la piu' vecchia e aggiunto quella del      #
#  24/08. Ci abbiamo ragionato sopra come se fosse il presente, e ne sono usciti #
#  due errori: "aprile e giugno non hanno i campi della deriva" (falso, li       #
#  hanno tutti) e "dec_hpf_rms non esiste nell'export" (falso, c'e' sempre).     #
#  Da qui in poi i dati reali si copiano, non si trascrivono.                   #
# --------------------------------------------------------------------------- #

EXPORT_REALE = (pathlib.Path(__file__).parent / "_fixture_export_reale.txt").read_text(
    encoding="utf-8")


# --------------------------------------------------------------------------- #
#  DATI SINTETICI — casi limite che la realta' non ci ha (ancora) dato.        #
#  Tenuti separati e dichiarati: servono a provare i rifiuti, non a descrivere #
#  questo telescopio. Se un giorno una corsa reale mostrera' uno di questi     #
#  casi, si sposta di sopra.                                                   #
# --------------------------------------------------------------------------- #

def _corsa_sintetica(ts, **campi):
    TAB, NL = chr(9), chr(10)
    righe = [f"/profile/2/GA/{ts}/{k}{TAB}1{TAB}{v}" for k, v in campi.items()]
    testa = "PHD Config 1" + NL + f"/profile/2/name{TAB}1{TAB}CEM70 RC8" + NL
    return testa + NL.join(righe)


# SNR sotto la soglia: la dispersione misurata contiene il rumore di centroide.
EXPORT_SNR_BASSO = _corsa_sintetica(
    "2026-04-07 21:25:09", timestamp="2026-04-07 21:25:09", snr="18.8",
    exposure_time="1s", elapsed_time="400s", sample_count="240",
    rec_ra_minmove="1.300000", rec_dec_minmove="2.000000")

# BLT_pulse mai inizializzato: PHD2 lascia il campo con un valore assurdo.
EXPORT_BLT_SPAZZATURA = _corsa_sintetica(
    "2026-04-07 21:25:09", timestamp="2026-04-07 21:25:09", snr="33.6",
    exposure_time="1s", elapsed_time="400s", sample_count="240",
    rec_ra_minmove="0.812500", rec_dec_minmove="1.250000",
    BLT_pulse="995908700")

# criteri di QUALITA' della misura (i limiti minmove_min/max non stanno qui:
# limitano il valore applicato, non invalidano la caratterizzazione)
CRITERI = dict(snr_min=30.0, elapsed_min_s=144, campioni_min=60)


def _BL(applicato_ms, pulse=None, enabled=True):
    """Stato del backlash come lo lascia PHD2 dopo un Applica del GA:
    `SetCompValues` impone ceiling = 1.50 x valore applicato."""
    return gb.BacklashState(enabled=enabled,
                            pulse_ms=pulse if pulse is not None else applicato_ms,
                            floor_ms=20,
                            ceiling_ms=int(round(1.5 * applicato_ms)))
LIMITI = dict(minmove_min=0.15, minmove_max=1.20)


class TestFormulaPHD2(unittest.TestCase):
    """`SmartDefaultMinMove` deve valere per QUALSIASI setup, non solo per l'RC8."""

    def test_valore_sul_setup_reale(self):
        # 1624 mm + pixel 4.0 um -> 0.508 arcsec/px
        self.assertAlmostEqual(gb.smart_default_minmove(0.508042), 0.45620, places=4)

    def test_monotona_decrescente_con_la_scala(self):
        scale = [0.3, 0.5, 1.0, 1.7, 2.2, 3.2]
        valori = [gb.smart_default_minmove(s) for s in scale if s != 1.0]
        self.assertEqual(valori, sorted(valori, reverse=True),
                         "campionamento piu' grossolano deve dare MinMove minore")

    def test_pavimento_a_015(self):
        self.assertGreaterEqual(gb.smart_default_minmove(50.0), 0.15)

    def test_scala_sentinella_rifiutata(self):
        # PHD2 restituisce esattamente 1.0 quando non conosce focale o pixel:
        # indistinguibile da una scala vera, quindi non utilizzabile.
        self.assertIsNone(gb.smart_default_minmove(1.0))

    def test_scala_non_valida(self):
        self.assertIsNone(gb.smart_default_minmove(0.0))
        self.assertIsNone(gb.smart_default_minmove(-1.0))


class TestParsing(unittest.TestCase):

    def setUp(self):
        self.corse = gb.parse_ga_runs(EXPORT_REALE, profile_id=2)

    def test_trova_tutte_le_esecuzioni_del_profilo(self):
        self.assertEqual(len(self.corse), 3)

    def test_ordine_cronologico(self):
        self.assertEqual([c.timestamp for c in self.corse],
                         ["2026-04-08 21:36:52", "2026-06-12 22:33:35",
                          "2026-08-24 00:28:30"])

    def test_ignora_gli_altri_profili(self):
        self.assertEqual(gb.parse_ga_runs(EXPORT_REALE, profile_id=1), [])

    def test_posa_convertita_in_ms(self):
        self.assertEqual([c.exposure_ms for c in self.corse], [1000, 1000, 2000])

    def test_campi_formattati_per_l_uomo(self):
        ultima = self.corse[-1]
        # "   1.9 s " e " 1.1 arc-min": si prende il numero nell'unita' nativa
        self.assertAlmostEqual(ultima.ra_drift_exposure_s, 1.9)
        self.assertAlmostEqual(ultima.pa_error_arcmin, 1.1)
        # "  0.32 px/sec (  0.16 arc-sec/sec )" -> il PRIMO numero, non il secondo
        self.assertAlmostEqual(ultima.ra_peak_drift_rate, 0.32)

    def test_backlash_letto_da_tutte_e_tre(self):
        self.assertEqual([c.blt_pulse_ms for c in self.corse], [198, 147, 132])

    def test_backlash_non_inizializzato_scartato(self):
        # 995908700 ms e' oltre MAX_COMP_AMOUNT: campo mai scritto da PHD2.
        # Nessuna corsa reale attuale lo mostra -> caso sintetico.
        corsa = gb.parse_ga_runs(EXPORT_BLT_SPAZZATURA, 2)[0]
        self.assertIsNone(corsa.blt_pulse_ms)

    def test_backlash_configurato(self):
        bl = gb.parse_backlash(EXPORT_REALE, 2)
        self.assertTrue(bl.enabled)
        # valori veri del profilo: PHD2 ha alzato il polso a 203 dentro la
        # forbice 20-292 fissata quando e' stato premuto Applica (292 = 1.5 x 195)
        self.assertEqual(bl.pulse_ms, 203)
        self.assertEqual(bl.floor_ms, 20)
        self.assertEqual(bl.ceiling_ms, 292)
        # 292 / 1.5 = 194.67, arrotondato a 195: e' esattamente il valore che
        # l'operatore ha applicato quel giorno. La deduzione del ceiling regge
        # sui dati veri.
        self.assertEqual(bl.applicato_ms, 195)
        self.assertIsNone(gb.parse_backlash(EXPORT_REALE, 99).pulse_ms)

    def test_export_vuoto_non_esplode(self):
        self.assertEqual(gb.parse_ga_runs("", 2), [])
        self.assertEqual(gb.parse_ga_runs("PHD Config 1\n", 2), [])


class TestCriteriDiAccettazione(unittest.TestCase):

    def setUp(self):
        self.corse = {c.timestamp: c for c in gb.parse_ga_runs(EXPORT_REALE, 2)}

    def test_snr_basso_rifiutato(self):
        # Le tre corse reali attuali hanno SNR 33.6 / 44.0 / 64.9: nessuna sotto
        # la soglia. Caso sintetico, dichiarato.
        corsa = gb.parse_ga_runs(EXPORT_SNR_BASSO, 2)[0]
        motivi = gb.motivi_di_scarto(corsa, base_exposure_ms=1000, **CRITERI)
        self.assertTrue(any("SNR" in m for m in motivi), motivi)

    def test_posa_diversa_non_e_piu_un_motivo_di_scarto(self):
        """§118 — verificato sulla sorgente di PHD2: la posa del GA viene salvata
        e usata in UN punto, `SetCellValue(m_exposuretime_loc, ...)`, cioe' per
        mostrarla. Nessun confronto, nessun rifiuto: Applica scrive il MinMove
        misurato qualunque sia la posa in uso. La regola era nostra."""
        motivi = gb.motivi_di_scarto(self.corse["2026-06-12 22:33:35"],
                                     base_exposure_ms=2000, **CRITERI)
        self.assertEqual(motivi, [])

    def test_lo_scarto_per_posa_resta_disponibile_su_richiesta(self):
        motivi = gb.motivi_di_scarto(self.corse["2026-06-12 22:33:35"],
                                     base_exposure_ms=2000, scarta_per_posa=True,
                                     **CRITERI)
        self.assertTrue(any("2000ms" in m for m in motivi), motivi)

    def test_posa_uguale_accettata(self):
        motivi = gb.motivi_di_scarto(self.corse["2026-06-12 22:33:35"],
                                     base_exposure_ms=1000, **CRITERI)
        self.assertEqual(motivi, [])

    def test_esecuzione_valida_non_ha_motivi(self):
        motivi = gb.motivi_di_scarto(self.corse["2026-08-24 00:28:30"],
                                     base_exposure_ms=2000, **CRITERI)
        self.assertEqual(motivi, [])

    def test_i_limiti_non_invalidano_la_misura(self):
        # il tetto e' una guardia di configurazione, non un criterio di qualita':
        # non deve comparire fra i motivi di scarto
        motivi = gb.motivi_di_scarto(self.corse["2026-08-24 00:28:30"],
                                     base_exposure_ms=2000, **CRITERI)
        self.assertEqual(motivi, [])

    def test_durata_insufficiente_rifiutata(self):
        breve = gb.GARun(timestamp="2026-08-24 01:00:00", snr=60.0,
                         exposure_ms=2000, sample_count=80, elapsed_s=100,
                         rec_ra_minmove=0.6, rec_dec_minmove=0.9)
        motivi = gb.motivi_di_scarto(breve, base_exposure_ms=2000, **CRITERI)
        self.assertTrue(any("durata" in m for m in motivi), motivi)

    def test_raccomandazioni_assenti_rifiutate(self):
        vuota = gb.GARun(timestamp="2026-08-24 02:00:00", snr=60.0,
                         exposure_ms=2000, sample_count=80, elapsed_s=300)
        self.assertTrue(gb.motivi_di_scarto(vuota, base_exposure_ms=2000, **CRITERI))


class TestGerarchia(unittest.TestCase):
    """La risoluzione non deve MAI lasciare l'Agente senza un nominale."""

    def setUp(self):
        self.corse = gb.parse_ga_runs(EXPORT_REALE, 2)

    def _risolvi(self, **override):
        kwargs = dict(corse=self.corse, pixel_scale_arcsec=0.508042,
                      base_exposure_ms=2000, backlash=_BL(130),
                      **CRITERI, **LIMITI)
        kwargs.update(override)
        return gb.risolvi(**kwargs)

    def test_livello_1_usa_la_caratterizzazione_valida(self):
        b = self._risolvi()
        self.assertEqual(b.sorgente, "guide_assistant")
        self.assertAlmostEqual(b.ra_minmove, 0.6175)
        self.assertAlmostEqual(b.dec_minmove, 0.95)
        self.assertEqual(b.ga.timestamp, "2026-08-24 00:28:30")

    def test_livello_1_preferisce_la_piu_recente_valida(self):
        # la 04/07 e' esclusa per SNR 18.8; fra le restanti vince la piu' recente.
        # §118 — la posa non discrimina piu': a 1000 ms vince comunque la 24/08,
        # che e' l'ultima buona. La qualita' della misura conta, non a che posa e'
        # stata presa.
        b = self._risolvi(base_exposure_ms=1000)
        self.assertEqual(b.ga.timestamp, "2026-08-24 00:28:30")
        # misurato 1.40, limitato dal tetto 1.20 -> resta molto piu' vicino al
        # vero del ripiego alla formula (0.456), e la limitazione e' dichiarata
        self.assertAlmostEqual(b.dec_minmove, 0.95)
        # 1000 ms e' fuori dall'intervallo 1.5-3.5 misurato dalla 24/08: avviso forte
        self.assertTrue(any("fuori dall'intervallo" in a for a in b.avvisi), b.avvisi)

    def test_a_posa_diversa_la_misura_si_usa_con_una_nota(self):
        """§118 — prima questo caso finiva alla formula (0.4562). Ora la misura
        vera si usa, con la nota che e' stata presa a un'altra posa: 3 s e 2 s sono
        entrambe dentro l'intervallo 1.5-3.5 che PHD2 raccomanda per questo setup."""
        b = self._risolvi(base_exposure_ms=3000)
        self.assertEqual(b.sorgente, "guide_assistant")
        self.assertAlmostEqual(b.ra_minmove, 0.6175)
        note = [a for a in b.avvisi if "misurato a 2.0s" in a]
        self.assertEqual(len(note), 1, b.avvisi)
        self.assertIn("il valore si usa", note[0])

    def test_livello_2_senza_alcun_ga(self):
        b = self._risolvi(corse=[])
        self.assertEqual(b.sorgente, "formula_phd2")
        self.assertTrue(any("mai stato eseguito" in a for a in b.avvisi), b.avvisi)

    def test_livello_3_scala_sentinella(self):
        b = self._risolvi(corse=[], pixel_scale_arcsec=1.0)
        self.assertEqual(b.sorgente, "fallback_phd2")
        self.assertAlmostEqual(b.ra_minmove, gb.PHD2_DEFAULT_MINMOVE)
        self.assertTrue(any("scala pixel" in a for a in b.avvisi), b.avvisi)

    def test_aggressivita_sempre_ai_default_phd2(self):
        # il GA non caratterizza l'aggressivita': in NESSUN livello deve cambiare
        for kwargs in ({}, {"base_exposure_ms": 3000},
                       {"corse": [], "pixel_scale_arcsec": 1.0}):
            b = self._risolvi(**kwargs)
            self.assertEqual(b.ra_aggr, 70.0, b.sorgente)
            self.assertEqual(b.dec_aggr, 100.0, b.sorgente)

    # ---- backlash: due soli avvisi, su fatti osservabili (§105-ter) ----

    def test_nessun_avviso_in_condizioni_normali(self):
        """Valore dentro la banda: PHD2 sta lavorando, non c'e' nulla da dire."""
        b = self._risolvi(backlash=_BL(130, pulse=160))
        self.assertFalse([a for a in b.avvisi if "backlash" in a], b.avvisi)

    def test_nessun_avviso_se_compensa_piu_del_misurato(self):
        """Il GA da' un punto di partenza, non un bersaglio: superarlo non e' un
        difetto. Caso reale del 24/08/2026, PHD2 assestato a 203 contro 132 misurati."""
        b = self._risolvi(backlash=_BL(195, pulse=203))
        self.assertFalse([a for a in b.avvisi if "backlash" in a], b.avvisi)

    def test_nessun_avviso_se_compensa_meno_del_misurato(self):
        """Nemmeno al ribasso si avvisa: PHD2 scende quando serve, e' il suo mestiere."""
        b = self._risolvi(backlash=_BL(130, pulse=45))
        self.assertFalse([a for a in b.avvisi if "backlash" in a], b.avvisi)

    def test_avviso_quando_e_fermo_contro_il_tetto(self):
        """L'unico caso azionabile: l'anello chiede piu' di quanto gli sia concesso.
        Il 24/08/2026 si sarebbe acceso alle 01:19, quando PHD2 e' rimasto inchiodato
        a 195 per venti minuti."""
        b = self._risolvi(backlash=gb.BacklashState(enabled=True, pulse_ms=195,
                                                    floor_ms=20, ceiling_ms=195))
        avvisi = [a for a in b.avvisi if "backlash" in a]
        self.assertTrue(avvisi, b.avvisi)
        self.assertIn("tetto", avvisi[0])
        self.assertIn("195", avvisi[0])

    def test_avviso_se_compensazione_disattivata(self):
        b = self._risolvi(backlash=gb.BacklashState(enabled=False, pulse_ms=130,
                                                    floor_ms=20, ceiling_ms=195))
        self.assertTrue(any("DISATTIVATA" in a for a in b.avvisi), b.avvisi)

    def test_nessun_avviso_senza_dati_di_backlash(self):
        b = self._risolvi(backlash=None)
        self.assertFalse([a for a in b.avvisi if "backlash" in a], b.avvisi)

    def test_forma_consumata_dal_controller(self):
        nominale = self._risolvi().as_nominal()
        self.assertEqual(set(nominale), {"ra", "dec"})
        self.assertAlmostEqual(nominale["dec"][1], 0.95)

    def test_status_block_serializzabile(self):
        import json
        json.dumps(self._risolvi().status_block())


class TestRegressioneStoricaMinMove(unittest.TestCase):
    """Il difetto che questa modifica corregge: 0.20 fisso non e' il default PHD2."""

    def test_il_vecchio_nominale_era_molto_sotto_la_formula(self):
        formula = gb.smart_default_minmove(0.508042)
        self.assertGreater(formula / gb.PHD2_DEFAULT_MINMOVE, 2.0,
                           "a 0.51 arcsec/px la formula PHD2 vale piu' del doppio "
                           "del DefaultMinMove di classe")

    def test_su_scala_grossolana_i_due_valori_convergono(self):
        # su setup a campionamento largo il vecchio 0.20 era quasi corretto:
        # e' solo sui campionamenti fini che sbagliava di molto
        formula = gb.smart_default_minmove(3.223)
        self.assertAlmostEqual(formula, 0.20, places=2)



class TestEtaDellaCaratterizzazione(unittest.TestCase):
    """§105-quater — una misura di mesi prima non deve essere adottata in silenzio
    come se fosse di stanotte. Non la invalida (il MinMove segue il seeing TIPICO
    del sito), ma va detto."""

    ADESSO = dt.datetime(2026, 8, 24, 3, 0, 0)

    def _run(self, ts):
        return gb.GARun(timestamp=ts, snr=64.9, exposure_ms=2000, sample_count=99,
                        elapsed_s=256, rec_ra_minmove=0.6175, rec_dec_minmove=0.95)

    def _risolvi(self, ts, giorni=14, dottrina=False):
        # §117 — con la dottrina attiva il criterio non e' piu' l'eta' ma la
        # sessione: questi test presidiano la soglia in giorni, che resta il
        # criterio per chi la dottrina non la vuole.
        return gb.risolvi(corse=[self._run(ts)], pixel_scale_arcsec=0.508042,
                          base_exposure_ms=2000, eta_avviso_giorni=giorni,
                          richiedi_ga_di_sessione=dottrina,
                          adesso=self.ADESSO, **CRITERI, **LIMITI)

    def test_eta_calcolata(self):
        self.assertAlmostEqual(self._run("2026-08-14 03:00:00").eta_giorni(self.ADESSO),
                               10.0, places=3)

    def test_timestamp_illeggibile_non_esplode(self):
        self.assertIsNone(self._run("non-una-data").eta_giorni(self.ADESSO))

    def test_recente_nessun_avviso(self):
        b = self._risolvi("2026-08-24 00:28:30")
        self.assertFalse([a for a in b.avvisi if "giorni" in a], b.avvisi)

    def test_al_limite_nessun_avviso(self):
        b = self._risolvi("2026-08-11 03:00:00")   # esattamente 13 giorni
        self.assertFalse([a for a in b.avvisi if "giorni" in a], b.avvisi)

    def test_vecchia_avvisa_ma_viene_usata(self):
        b = self._risolvi("2026-04-24 22:00:00")
        self.assertEqual(b.sorgente, "guide_assistant")      # usata comunque
        self.assertAlmostEqual(b.ra_minmove, 0.6175)
        avvisi = [a for a in b.avvisi if "giorni" in a]
        self.assertTrue(avvisi, b.avvisi)
        self.assertIn("121", avvisi[0])
        self.assertIn("Assistente di guida", avvisi[0])

    def test_soglia_configurabile(self):
        b = self._risolvi("2026-08-14 03:00:00", giorni=5)    # 10 giorni, soglia 5
        self.assertTrue([a for a in b.avvisi if "giorni" in a], b.avvisi)

    def test_dettaglio_riporta_sempre_quando(self):
        for ts, atteso in (("2026-08-24 00:28:30", "di oggi"),
                           ("2026-08-22 22:00:00", "di ieri"),
                           ("2026-08-14 03:00:00", "10 giorni fa")):
            self.assertIn(atteso, self._risolvi(ts).dettaglio)


class TestMessaggioSenzaCaratterizzazione(unittest.TestCase):
    """Se il GA non e' mai stato eseguito, l'avviso deve dire COSA FARE."""

    def _senza_ga(self):
        return gb.risolvi(corse=[], pixel_scale_arcsec=0.508042,
                          base_exposure_ms=2000, **CRITERI, **LIMITI)

    def test_spiega_che_i_valori_sono_stimati(self):
        avvisi = self._senza_ga().avvisi
        self.assertTrue(any("stimati" in a for a in avvisi), avvisi)

    def test_dice_dove_andare(self):
        avvisi = self._senza_ga().avvisi
        self.assertTrue(any("Assistente di guida" in a for a in avvisi), avvisi)

    def test_dice_come_farlo(self):
        avvisi = self._senza_ga().avvisi
        testo = " ".join(avvisi)
        self.assertIn("posa operativa", testo)
        self.assertIn("Applica", testo)


class TestIntervalloDiPosa(unittest.TestCase):
    """§111 — il GA non da' un valore unico di posa ma un INTERVALLO, e dentro
    quell'intervallo il punto giusto lo fissa il limite-deriva.

    Ricalcolato dai campi numerici (`ra_hpf_rms`, `ra_peak_drift_rate`,
    `rec_ra_minmove`) e non dal testo: la riga delle raccomandazioni e' testo, e
    nello stesso blocco altre righe sono tradotte.
    """

    DURATE = [1000, 1500, 2000, 2500, 3000, 3500, 4000]

    def _run(self, rms, rate, minmove, posa_ms=2000):
        return gb.GARun(timestamp="2026-08-24 00:28:30", snr=64.9,
                        exposure_ms=posa_ms, sample_count=99, elapsed_s=256,
                        rec_ra_minmove=minmove, rec_dec_minmove=0.95,
                        ra_hpf_rms_px=rms, ra_peak_drift_rate=rate)

    def test_riproduce_le_quattro_caratterizzazioni_reali(self):
        """Il controllo che conta: gli intervalli calcolati devono coincidere con
        quelli che PHD2 ha mostrato a schermo."""
        for rms, rate, atteso in ((0.43, 0.32, (1.5, 3.5)),    # 24/08
                                  (0.76, 0.48, (2.0, 4.0)),    # 12/06
                                  (0.77, 0.61, (1.5, 3.5)),    # 08/04
                                  (1.04, 0.67, (2.0, 4.0))):   # 07/04
            with self.subTest(rms=rms):
                self.assertEqual(self._run(rms, rate, 0.62).intervallo_posa_s(), atteso)

    def test_limite_deriva(self):
        # MinMove / deriva di picco = 0.6175 / 0.32
        self.assertAlmostEqual(self._run(0.43, 0.32, 0.6175).limite_deriva_s(),
                               1.9297, places=3)

    def test_posa_consigliata_e_ancorata_al_limite_non_alla_media(self):
        """Sulle quattro reali la regola ancorata da' 2.0/2.0/1.5/2.0 e non supera
        mai il limite; la media dell'intervallo lo supera sempre, fino al 58%."""
        for rms, rate, mm, atteso in ((0.43, 0.32, 0.6175, 2000),
                                      (0.76, 0.48, 0.91, 2000),
                                      (0.77, 0.61, 0.8125, 1500),
                                      (1.04, 0.67, 1.30, 2000)):
            with self.subTest(rms=rms):
                run = self._run(rms, rate, mm)
                consigliata = run.posa_consigliata_ms(self.DURATE)
                self.assertEqual(consigliata, atteso)
                media = sum(run.intervallo_posa_s()) / 2
                self.assertLess(consigliata / 1000, media,
                                "la media sarebbe piu' lunga del gradino ancorato")

    def test_senza_i_numeri_non_inventa(self):
        vuoto = gb.GARun(timestamp="2026-08-24 00:28:30", rec_ra_minmove=0.62,
                         rec_dec_minmove=0.95)
        self.assertIsNone(vuoto.intervallo_posa_s())
        self.assertIsNone(vuoto.limite_deriva_s())
        self.assertIsNone(vuoto.posa_consigliata_ms(self.DURATE))

    def test_deriva_nulla_non_divide_per_zero(self):
        self.assertIsNone(self._run(0.43, 0.0, 0.62).intervallo_posa_s())
        self.assertIsNone(self._run(0.43, 0.0, 0.62).limite_deriva_s())


class TestAvvisiSullaPosa(unittest.TestCase):

    DURATE = [1000, 1500, 2000, 2500, 3000, 3500, 4000]

    def _risolvi(self, base_ms, rms=0.43, rate=0.32, mm=0.6175, posa_ga=2000):
        run = gb.GARun(timestamp="2026-08-24 00:28:30", snr=64.9,
                       exposure_ms=posa_ga, sample_count=99, elapsed_s=256,
                       rec_ra_minmove=mm, rec_dec_minmove=0.95,
                       ra_hpf_rms_px=rms, ra_peak_drift_rate=rate)
        return gb.risolvi(corse=[run], pixel_scale_arcsec=0.508042,
                          base_exposure_ms=base_ms, durate_posa_ms=self.DURATE,
                          **CRITERI, **LIMITI)

    def test_posa_coerente_nessun_avviso(self):
        """Il caso reale del 24/08: GA misurato a 2 s, raccomanda 2 s, si guida a 2 s."""
        b = self._risolvi(2000)
        # §125 — si filtrano i soli avvisi sulla POSA: l'avviso sull'eta' della
        # misura e' un'altra cosa e qui non c'entra.
        self.assertFalse([a for a in b.avvisi
                          if ("posa" in a or "guidi" in a) and "giorni fa" not in a],
                         b.avvisi)

    def test_ga_incoerente_con_se_stesso(self):
        """I GA di aprile e giugno erano misurati a 1 s ma raccomandavano 1.5 e 2 s:
        descrivono un regime diverso da quello che consigliano."""
        b = self._risolvi(1000, rms=0.77, rate=0.61, mm=0.8125, posa_ga=1000)
        self.assertTrue(any("rifai l'Assistente" in a for a in b.avvisi), b.avvisi)

    def test_sopra_il_limite_deriva_pur_dentro_l_intervallo(self):
        """L'intervallo del GA e' largo 2 s per costruzione ed e' piu' permissivo del
        vincolo fisico: ci si puo' stare dentro e superare comunque il limite-deriva.
        Qui: intervallo 1.5-3.5 s, limite 2.0 s, si guida a 3.0 s."""
        b = self._risolvi(3000, rms=0.43, rate=0.31, mm=0.62, posa_ga=3000)
        self.assertEqual(b.sorgente, "guide_assistant")
        self.assertTrue(any("limite-deriva" in a for a in b.avvisi), b.avvisi)

    def test_i_valori_finiscono_su_status(self):
        blocco = self._risolvi(2000).status_block()
        self.assertEqual(blocco["posa_min_s"], 1.5)
        self.assertEqual(blocco["posa_max_s"], 3.5)
        self.assertEqual(blocco["posa_consigliata_ms"], 2000)
        self.assertAlmostEqual(blocco["posa_limite_deriva_s"], 1.93, places=2)

if __name__ == "__main__":
    unittest.main()


class TestErrorePolare(unittest.TestCase):
    """§115 — il GA misura l'allineamento polare, e finora lo buttavamo via.

    Non e' un parametro di guida: e' un problema a MONTE. Una polare storta
    produce deriva costante in DEC, che non e' seeing; se l'Agente alzasse la
    zona morta per assorbirla peggiorerebbe la guida invece di aggiustarla.
    Sulle tre caratterizzazioni reali del profilo vale 0.1', 5.8' e 1.1'.
    """

    def _risolvi(self, testo, **kw):
        corse = gb.parse_ga_runs(testo, profile_id=2)
        base = dict(corse=corse, pixel_scale_arcsec=0.508, base_exposure_ms=2000,
                    minmove_min=0.15, minmove_max=1.20, snr_min=30.0,
                    elapsed_min_s=144, campioni_min=60,
                    adesso=dt.datetime(2026, 8, 25, 12, 0, 0))
        base.update(kw)
        return gb.risolvi(**base)

    def test_il_valore_misurato_arriva_alla_dashboard(self):
        b = self._risolvi(EXPORT_REALE)
        self.assertAlmostEqual(b.pa_error_arcmin, 1.1)
        self.assertAlmostEqual(b.status_block()["pa_error_arcmin"], 1.1)

    def test_sotto_la_soglia_nessun_avviso(self):
        b = self._risolvi(EXPORT_REALE, pa_error_avviso_arcmin=5.0)
        self.assertFalse([a for a in b.avvisi if "polare" in a])

    def test_sopra_la_soglia_avvisa_e_dice_dove_si_risolve(self):
        b = self._risolvi(EXPORT_REALE, pa_error_avviso_arcmin=1.0)
        polare = [a for a in b.avvisi if "polare" in a]
        self.assertEqual(len(polare), 1)
        self.assertIn("1.1 arcmin", polare[0])
        # L'avviso deve indirizzare a monte, non ai parametri di guida.
        self.assertIn("riallineando", polare[0])

    def test_la_soglia_viaggia_con_la_baseline(self):
        """La dashboard colora sopra soglia: non deve ri-dichiarare il numero."""
        b = self._risolvi(EXPORT_REALE, pa_error_avviso_arcmin=3.5)
        self.assertEqual(b.status_block()["pa_error_soglia_arcmin"], 3.5)

    def test_una_polare_storta_non_invalida_la_caratterizzazione(self):
        """Il MinMove misura il seeing, non la deriva: resta valido."""
        b = self._risolvi(EXPORT_REALE, pa_error_avviso_arcmin=0.5)
        self.assertEqual(b.sorgente, "guide_assistant")
        self.assertAlmostEqual(b.ra_minmove, 0.6175, places=3)

    def test_senza_il_campo_non_si_inventa_nulla(self):
        senza = "\n".join(r for r in EXPORT_REALE.split("\n") if "pa_error" not in r)
        b = self._risolvi(senza)
        self.assertIsNone(b.pa_error_arcmin)
        self.assertFalse([a for a in b.avvisi if "polare" in a])


class TestFreschezzaDiSessione(unittest.TestCase):
    """§117 — la dottrina: l'Assistente si esegue a ogni sessione.

    Il seeing e' una proprieta' della NOTTE, non del telescopio. La montatura e'
    la stessa da un anno; il cielo cambia da sera a sera, e la zona morta e'
    tarata sul seeing. Quindi il criterio non e' piu' "quanti giorni ha" ma
    "e' di questa sessione".

    Il confine e' l'ultimo MEZZOGIORNO locale: una sessione attraversa la
    mezzanotte, e un GA delle 21:30 deve restare "di stanotte" alle 4 del mattino.
    """

    def _run(self, ts):
        return gb.GARun(timestamp=ts, snr=64.9, exposure_ms=2000, sample_count=99,
                        elapsed_s=256, rec_ra_minmove=0.6175, rec_dec_minmove=0.95)

    def _risolvi(self, ts, adesso, dottrina=True):
        return gb.risolvi(corse=[self._run(ts)], pixel_scale_arcsec=0.508042,
                          base_exposure_ms=2000, richiedi_ga_di_sessione=dottrina,
                          adesso=adesso, **CRITERI, **LIMITI)

    # --- la regola del mezzogiorno -----------------------------------------
    def test_prima_di_mezzanotte_e_di_stanotte(self):
        r = self._run("2026-08-25 21:30:00")
        self.assertTrue(r.di_stanotte(dt.datetime(2026, 8, 25, 23, 0, 0)))

    def test_dopo_mezzanotte_il_ga_di_ieri_sera_e_ancora_di_stanotte(self):
        """Il caso che una soglia \"di oggi\" sbaglierebbe: sono le 4 del mattino
        del 26, il GA e' delle 21:30 del 25. E' la stessa sessione."""
        r = self._run("2026-08-25 21:30:00")
        self.assertTrue(r.di_stanotte(dt.datetime(2026, 8, 26, 4, 0, 0)))

    def test_la_sera_prima_non_e_di_stanotte(self):
        r = self._run("2026-08-24 21:30:00")
        self.assertFalse(r.di_stanotte(dt.datetime(2026, 8, 26, 4, 0, 0)))

    def test_il_confine_e_mezzogiorno(self):
        r = self._run("2026-08-25 11:59:00")
        self.assertFalse(r.di_stanotte(dt.datetime(2026, 8, 25, 22, 0, 0)))
        r = self._run("2026-08-25 12:00:00")
        self.assertTrue(r.di_stanotte(dt.datetime(2026, 8, 25, 22, 0, 0)))

    def test_timestamp_illeggibile_non_esplode(self):
        self.assertIsNone(self._run("non-una-data").di_stanotte())

    # --- l'avviso -----------------------------------------------------------
    def test_di_stanotte_nessun_avviso(self):
        b = self._risolvi("2026-08-25 21:30:00", dt.datetime(2026, 8, 26, 2, 0, 0))
        self.assertTrue(b.ga_di_stanotte)
        self.assertFalse([a for a in b.avvisi if "sessione" in a], b.avvisi)

    def test_di_un_altra_notte_ma_recente_non_si_dice_niente(self):
        """§125 — il §117 segnalava ogni misura che non fosse di stanotte. In campo
        era sproporzionato: una caratterizzazione di IERI faceva comparire
        etichetta ambra e spiegazione. Sotto la soglia in giorni si tace."""
        b = self._risolvi("2026-08-20 21:30:00", dt.datetime(2026, 8, 26, 2, 0, 0))
        self.assertFalse(b.ga_di_stanotte)                  # non e' di stanotte
        self.assertFalse(b.ga_vecchia)                      # ma e' recente
        self.assertEqual(b.sorgente, "guide_assistant")     # e si usa
        self.assertAlmostEqual(b.ra_minmove, 0.6175)
        self.assertFalse([a for a in b.avvisi if "giorni fa" in a], b.avvisi)

    def test_oltre_la_soglia_lo_dice(self):
        b = self._risolvi("2026-06-20 21:30:00", dt.datetime(2026, 8, 26, 2, 0, 0))
        self.assertTrue(b.ga_vecchia)
        self.assertEqual(b.sorgente, "guide_assistant")     # usata lo stesso
        avvisi = [a for a in b.avvisi if "giorni fa" in a]
        self.assertEqual(len(avvisi), 1)
        self.assertIn("conviene rifarlo", avvisi[0])

    def test_l_eta_viaggia_con_la_baseline(self):
        b = self._risolvi("2026-08-20 21:30:00", dt.datetime(2026, 8, 26, 2, 0, 0))
        self.assertAlmostEqual(b.ga_eta_giorni, 5.19, places=1)
        self.assertAlmostEqual(b.status_block()["ga_eta_giorni"], 5.2, places=1)

    def test_senza_dottrina_resta_la_sola_soglia_in_giorni(self):
        b = self._risolvi("2026-04-24 22:00:00", dt.datetime(2026, 8, 26, 2, 0, 0),
                          dottrina=False)
        self.assertEqual(len([a for a in b.avvisi if "giorni" in a]), 1, b.avvisi)

    def test_i_due_avvisi_non_si_sovrappongono(self):
        """Con una misura di mesi fa il messaggio esce da UN punto solo."""
        b = self._risolvi("2026-04-24 22:00:00", dt.datetime(2026, 8, 26, 2, 0, 0))
        detti = [a for a in b.avvisi if "giorni" in a]
        self.assertEqual(len(detti), 1, detti)

    def test_lo_stato_arriva_alla_dashboard(self):
        b = self._risolvi("2026-08-20 21:30:00", dt.datetime(2026, 8, 26, 2, 0, 0))
        s = b.status_block()
        self.assertIs(s["ga_di_stanotte"], False)
        self.assertIs(s["ga_vecchia"], False)


class TestPavimentoRMS(unittest.TestCase):
    """§119 — la dispersione a correzioni spente, letta e basta.

    PHD2 la salva su entrambi gli assi e gia' composta (`SaveGAResults`, scritti
    sempre). Il filtro passa-alto taglia tutto cio' che e' piu' lento di 1 secondo
    (`hp_cutoff = 1.0` in `guiding_assistant.cpp`), quindi resta solo la parte che
    la guida NON puo' togliere: il pavimento sotto cui non si scende.

    Per ora si legge e si mostra. Non entra in nessuna decisione: quanto valga il
    rapporto fra errore guidato e pavimento su un telescopio vero non lo sappiamo
    ancora, e una soglia decisa a tavolino sarebbe inventata.
    """

    def setUp(self):
        self.corse = {c.timestamp: c for c in gb.parse_ga_runs(EXPORT_REALE, 2)}

    def test_presente_in_tutte_e_tre_le_corse_reali(self):
        """La fixture vecchia diceva che aprile e giugno non li avevano: era una
        copia ritagliata. Sull'export vero ci sono sempre."""
        for ts, corsa in self.corse.items():
            with self.subTest(ts=ts):
                self.assertIsNotNone(corsa.ra_hpf_rms_px, ts)
                self.assertIsNotNone(corsa.dec_hpf_rms_px, ts)
                self.assertIsNotNone(corsa.total_hpf_rms_px, ts)

    def test_valori_reali(self):
        c = self.corse["2026-08-24 00:28:30"]
        self.assertAlmostEqual(c.ra_hpf_rms_px, 0.43)
        self.assertAlmostEqual(c.dec_hpf_rms_px, 0.28)
        self.assertAlmostEqual(c.total_hpf_rms_px, 0.51)

    def test_il_totale_non_e_la_somma_degli_assi(self):
        """E' la dispersione della distanza radiale, non la composizione dei due
        sigma: 0.43 e 0.28 comporrebbero 0.51 per Pitagora quasi per caso, ma su
        aprile (0.77, 0.63) darebbero 1.00 — e infatti PHD2 scrive 1.00. Il test
        fissa che il valore lo LEGGIAMO da PHD2 e non lo ricalcoliamo noi."""
        c = self.corse["2026-04-08 21:36:52"]
        self.assertAlmostEqual(c.total_hpf_rms_px, 1.00)

    def test_arriva_alla_dashboard(self):
        b = gb.risolvi(corse=list(self.corse.values()), pixel_scale_arcsec=0.508042,
                       base_exposure_ms=2000, adesso=dt.datetime(2026, 8, 26, 2, 0, 0),
                       **CRITERI, **LIMITI)
        s = b.status_block()
        self.assertAlmostEqual(s["pavimento_ra_px"], 0.43)
        self.assertAlmostEqual(s["pavimento_dec_px"], 0.28)
        self.assertAlmostEqual(s["pavimento_totale_px"], 0.51)

    def test_senza_i_campi_resta_none(self):
        corsa = gb.parse_ga_runs(EXPORT_SNR_BASSO, 2)[0]
        self.assertIsNone(corsa.total_hpf_rms_px)
