"""§104 — Baseline dal Guiding Assistant di PHD2.

Il Guiding Assistant e' l'unico strumento che misura il comportamento reale del
sistema di guida: sospende l'uscita di guida (`guiding_assistant.cpp:1668`) e
osserva il moto NON corretto della stella. Ad anello chiuso quella grandezza non
e' osservabile, perche' il loop ne rimuove una parte.

Il GA non e' raggiungibile dall'API (nessun metodo in `event_server.cpp`), ma i
suoi risultati sono salvati nel profilo (`SaveGAResults`, guiding_assistant.cpp:1030)
e `export_config_settings` scrive l'intera configurazione su file restituendone il
nome. Da li' si leggono.

Gerarchia della baseline, in ordine di preferenza:

  1. GA valido            -> rec_ra_minmove / rec_dec_minmove          MISURATO
  2. nessun GA valido     -> SmartDefaultMinMove(scala)                FORMULA PHD2
  3. scala ignota         -> DefaultMinMove delle classi PHD2 (0.20)   FALLBACK

L'aggressivita' non entra mai in questa catena: il GA non la caratterizza (le
sue dieci raccomandazioni non la toccano; l'unico valore e' la costante 80.0 per
Lowpass2 in DEC). I default PHD2 sono `DefaultAggression = 0.7` per Hysteresis
(guide_algorithm_hysteresis.cpp:44) e `1.0` per Resist Switch
(guide_algorithm_resistswitch.cpp:43), cioe' 70 e 100 in scala di configurazione.

Nessun percorso di questo modulo puo' bloccare l'avvio: in mancanza di dati si
scende di livello e si avvisa.
"""

from __future__ import annotations

import datetime as dt
import logging
import math
import re
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)

# Default delle classi PHD2 quando non esiste alcun valore salvato:
# guide_algorithm_hysteresis.cpp:42-44 e guide_algorithm_resistswitch.cpp:42-43.
PHD2_DEFAULT_MINMOVE = 0.20
PHD2_DEFAULT_AGGR = {"ra": 70.0, "dec": 100.0}

# `get_pixel_scale` restituisce ESATTAMENTE 1.0 quando PHD2 non conosce focale o
# dimensione del pixel (myframe.cpp:2838: `if (pixelSize == 0.0 || m_focalLength == 0)
# return 1.0`). Una scala vera di 1.000000 e' indistinguibile da quel sentinella,
# quindi si preferisce l'avviso al valore dedotto.
SCALA_SENTINELLA = 1.0

# Il campo BLT_pulse non e' inizializzato quando il test di backlash non e' stato
# eseguito: sul profilo reale valeva 995908700. MAX_COMP_AMOUNT di PHD2 e' 8000 ms
# (backlash_comp.cpp:42), oltre quello il dato e' spazzatura.
BACKLASH_MAX_MS = 8000


def smart_default_minmove(pixel_scale_arcsec: float) -> Optional[float]:
    """`GuideAlgorithm::SmartDefaultMinMove` (guide_algorithm.cpp:64), in pixel.

        max(0.1515 + 0.1548 / scala, 0.15)

    E' il valore che PHD2 assegna a ogni profilo creato dal wizard
    (profile_wizard.cpp:907) e quello a cui il GA stesso ripiega se i propri
    calcoli falliscono il controllo di sanita' (guiding_assistant.cpp:1263).
    Dipende dalla sola scala: focale, dimensione del pixel e binning sono gia'
    combinati da PHD2 in `get_pixel_scale`.

    Ritorna None se la scala non e' utilizzabile (<= 0 oppure il sentinella 1.0).
    """
    if pixel_scale_arcsec <= 0 or pixel_scale_arcsec == SCALA_SENTINELLA:
        return None
    return max(0.1515 + 0.1548 / pixel_scale_arcsec, 0.15)


@dataclass(frozen=True)
class GARun:
    """Una esecuzione del Guiding Assistant, come salvata nel profilo."""

    timestamp: str                  # "YYYY-MM-DD HH:MM:SS", ora locale
    snr: Optional[float] = None
    exposure_ms: Optional[int] = None
    sample_count: Optional[int] = None
    elapsed_s: Optional[int] = None
    rec_ra_minmove: Optional[float] = None
    rec_dec_minmove: Optional[float] = None
    blt_pulse_ms: Optional[int] = None
    ra_drift_exposure_s: Optional[float] = None
    ra_peak_drift_rate: Optional[float] = None
    ra_hpf_rms_px: Optional[float] = None
    # §119 — PHD2 salva la dispersione passa-alto su ENTRAMBI gli assi e il totale
    # gia' composto (`SaveGAResults`, scritti sempre). Il filtro taglia tutto cio'
    # che e' piu' lento di 1 s (`hp_cutoff = 1.0`), quindi resta solo la parte che
    # la guida NON puo' togliere: e' il pavimento sotto cui non si scende.
    # Verificato sull'export reale del 26/08: presenti in tutte e tre le corse.
    dec_hpf_rms_px: Optional[float] = None
    total_hpf_rms_px: Optional[float] = None
    pa_error_arcmin: Optional[float] = None
    pa_error_soglia_arcmin: Optional[float] = None
    # §116 — timestamp della corsa piu' recente che superi i criteri di QUALITA',
    # a prescindere dalla posa a cui e' stata fatta. E' il segnale "e' successo
    # qualcosa di nuovo": non puo' dipendere dal filtro sulla posa, altrimenti un
    # GA appena concluso a posa diversa non verrebbe nemmeno notato — proprio il
    # caso in cui ha piu' da dirci (la posa in vigore e' sbagliata).
    ga_riferimento_timestamp: Optional[str] = None
    ga_di_stanotte: Optional[bool] = None
    # §119 — il pavimento misurato ad anello aperto, in pixel. Per ora si LEGGE e
    # si MOSTRA soltanto: non entra in nessuna decisione. Prima di usarlo come
    # riferimento va misurato quanto vale il rapporto con l'errore guidato su piu'
    # notti — un numero deciso a tavolino sarebbe inventato.
    pavimento_ra_px: Optional[float] = None
    pavimento_dec_px: Optional[float] = None
    pavimento_totale_px: Optional[float] = None
    pavimento_totale_arcsec: Optional[float] = None

    @property
    def completo(self) -> bool:
        return (self.rec_ra_minmove is not None
                and self.rec_dec_minmove is not None)

    def intervallo_posa_s(self) -> Optional[tuple[float, float]]:
        """L'intervallo di posa raccomandato dal GA, RICALCOLATO dai campi numerici.

        Il testo della raccomandazione ("Use exposure times in the range of 1.5s to
        3.5s") e' l'unico posto dove PHD2 lo scrive, ma e' testo — e nello stesso
        blocco altre righe sono tradotte. La formula invece la conosciamo
        (guiding_assistant.cpp:1356-1378) e i suoi ingressi sono numerici:

            drift_exp = ceil((rms_passa-alto / deriva_di_picco) / 0.5) * 0.5
            minimo    = max(1.0, min(drift_exp, 2.0))
            massimo   = min(max(drift_exp, minimo + 2.0), 4.0)

        Verificata su tutte e quattro le caratterizzazioni reali del profilo: 1.5-3.5,
        2.0-4.0, 1.5-3.5, 2.0-4.0 — identiche a quelle mostrate da PHD2.
        (I valori 2.0 e 4.0 sono `ideal_min/max` per montature senza encoder.)
        """
        if not self.ra_hpf_rms_px or not self.ra_peak_drift_rate:
            return None
        if self.ra_peak_drift_rate <= 0:
            return None
        drift_exp = math.ceil((self.ra_hpf_rms_px / self.ra_peak_drift_rate) / 0.5) * 0.5
        minimo = max(1.0, min(drift_exp, 2.0))
        massimo = min(max(drift_exp, minimo + 2.0), 4.0)
        return minimo, massimo

    def limite_deriva_s(self) -> Optional[float]:
        """Oltre questa posa la deriva supera la banda morta dentro un singolo
        fotogramma: `MinMove / deriva_di_picco` (guiding_assistant.cpp:1344).
        E' il vincolo FISICO, piu' stringente della media dell'intervallo — che
        sulle quattro caratterizzazioni reali lo supera sempre, fino al 58%."""
        if not self.rec_ra_minmove or not self.ra_peak_drift_rate:
            return None
        if self.ra_peak_drift_rate <= 0:
            return None
        return self.rec_ra_minmove / self.ra_peak_drift_rate

    def posa_consigliata_ms(self, durate_ms: list[int]) -> Optional[int]:
        """Il gradino PHD2 piu' vicino al limite-deriva, dentro l'intervallo.

        NON la media dell'intervallo: quella e' larga 2 s per costruzione
        (`minimo + 2.0`) e finisce sistematicamente sopra il vincolo fisico.
        Sulle quattro caratterizzazioni reali questa regola da' 2.0 / 2.0 / 1.5 / 2.0,
        mai sopra il limite; la media avrebbe dato 2.5 / 3.0 / 2.5 / 3.0."""
        intervallo = self.intervallo_posa_s()
        limite = self.limite_deriva_s()
        if intervallo is None or limite is None or not durate_ms:
            return None
        minimo, massimo = intervallo
        dentro = [d for d in durate_ms if minimo * 1000 <= d <= massimo * 1000]
        if not dentro:
            return None
        return min(dentro, key=lambda d: abs(d / 1000.0 - limite))

    def di_stanotte(self, adesso: Optional[dt.datetime] = None) -> Optional[bool]:
        """§117 — la caratterizzazione e' di QUESTA sessione osservativa.

        Non "di oggi": una sessione attraversa la mezzanotte, e un GA delle 21:30
        e' ancora il riferimento buono alle 4 del mattino. Il confine naturale e'
        l'ultimo MEZZOGIORNO locale — nessuno osserva a mezzogiorno, quindi il
        taglio cade sempre in mezzo a due notti e mai dentro una.
        """
        try:
            quando = dt.datetime.strptime(self.timestamp, "%Y-%m-%d %H:%M:%S")
        except (ValueError, TypeError):
            return None
        ora = adesso or dt.datetime.now()
        mezzogiorno = ora.replace(hour=12, minute=0, second=0, microsecond=0)
        if ora.hour < 12:
            mezzogiorno -= dt.timedelta(days=1)
        return quando >= mezzogiorno

    def eta_giorni(self, adesso: Optional[dt.datetime] = None) -> Optional[float]:
        """Da quanti giorni e' stata fatta questa caratterizzazione. Il timestamp e'
        `FormatISOCombined(' ')` in ORA LOCALE (guiding_assistant.cpp:1678), quindi
        va confrontato con l'ora locale."""
        try:
            quando = dt.datetime.strptime(self.timestamp, "%Y-%m-%d %H:%M:%S")
        except (ValueError, TypeError):
            return None
        delta = (adesso or dt.datetime.now()) - quando
        return delta.total_seconds() / 86400.0


@dataclass
class Baseline:
    """Valori nominali risolti + provenienza. `sorgente` e' cio' che va mostrato."""

    ra_aggr: float
    ra_minmove: float
    dec_aggr: float
    dec_minmove: float
    sorgente: str                   # "guide_assistant" | "formula_phd2" | "fallback_phd2"
    dettaglio: str
    ga: Optional[GARun] = None
    backlash: Optional["BacklashState"] = None
    posa_min_s: Optional[float] = None
    posa_max_s: Optional[float] = None
    posa_limite_deriva_s: Optional[float] = None
    posa_consigliata_ms: Optional[int] = None
    pa_error_arcmin: Optional[float] = None
    pa_error_soglia_arcmin: Optional[float] = None
    # §116 — timestamp della corsa piu' recente che superi i criteri di QUALITA',
    # a prescindere dalla posa a cui e' stata fatta. E' il segnale "e' successo
    # qualcosa di nuovo": non puo' dipendere dal filtro sulla posa, altrimenti un
    # GA appena concluso a posa diversa non verrebbe nemmeno notato — proprio il
    # caso in cui ha piu' da dirci (la posa in vigore e' sbagliata).
    ga_riferimento_timestamp: Optional[str] = None
    ga_di_stanotte: Optional[bool] = None
    # §125 — vecchia OLTRE la soglia in giorni. E' questa, non il semplice
    # "non e' di stanotte", a far scattare l'ambra e l'avviso: una misura di
    # ieri non e' un problema, una di tre mesi fa si'.
    ga_vecchia: Optional[bool] = None
    ga_eta_giorni: Optional[float] = None
    # §119 — il pavimento misurato ad anello aperto, in pixel. Per ora si LEGGE e
    # si MOSTRA soltanto: non entra in nessuna decisione. Prima di usarlo come
    # riferimento va misurato quanto vale il rapporto con l'errore guidato su piu'
    # notti — un numero deciso a tavolino sarebbe inventato.
    pavimento_ra_px: Optional[float] = None
    pavimento_dec_px: Optional[float] = None
    pavimento_totale_px: Optional[float] = None
    pavimento_totale_arcsec: Optional[float] = None
    avvisi: list[str] = field(default_factory=list)

    def as_nominal(self) -> dict[str, tuple[float, float]]:
        """Nella forma consumata dal controller: {asse: (aggr, minmove)}."""
        return {"ra": (self.ra_aggr, self.ra_minmove),
                "dec": (self.dec_aggr, self.dec_minmove)}

    def status_block(self) -> dict:
        return {
            "sorgente": self.sorgente,
            "dettaglio": self.dettaglio,
            "ra_minmove": round(self.ra_minmove, 4),
            "dec_minmove": round(self.dec_minmove, 4),
            "ra_aggr": self.ra_aggr,
            "dec_aggr": self.dec_aggr,
            "ga_timestamp": self.ga.timestamp if self.ga else None,
            "ga_snr": self.ga.snr if self.ga else None,
            "ga_exposure_ms": self.ga.exposure_ms if self.ga else None,
            "ga_backlash_ms": (raccomandazione_arrotondata(self.ga.blt_pulse_ms)
                               if self.ga else None),
            "backlash_pulse_ms": self.backlash.pulse_ms if self.backlash else None,
            "backlash_ceiling_ms": self.backlash.ceiling_ms if self.backlash else None,
            "backlash_applicato_ms": self.backlash.applicato_ms if self.backlash else None,
            "backlash_enabled": self.backlash.enabled if self.backlash else None,
            "posa_min_s": self.posa_min_s,
            "posa_max_s": self.posa_max_s,
            "posa_limite_deriva_s": (round(self.posa_limite_deriva_s, 2)
                                    if self.posa_limite_deriva_s else None),
            "posa_consigliata_ms": self.posa_consigliata_ms,
            "pa_error_arcmin": self.pa_error_arcmin,
            "pa_error_soglia_arcmin": self.pa_error_soglia_arcmin,
            "ga_riferimento_timestamp": self.ga_riferimento_timestamp,
            "ga_di_stanotte": self.ga_di_stanotte,
            "ga_vecchia": self.ga_vecchia,
            "ga_eta_giorni": (round(self.ga_eta_giorni, 1)
                              if self.ga_eta_giorni is not None else None),
            "pavimento_ra_px": self.pavimento_ra_px,
            "pavimento_dec_px": self.pavimento_dec_px,
            "pavimento_totale_px": self.pavimento_totale_px,
            "pavimento_totale_arcsec": (round(self.pavimento_totale_arcsec, 3)
                                        if self.pavimento_totale_arcsec else None),
            "avvisi": list(self.avvisi),
        }


# --------------------------------------------------------------------------- #
#  Lettura del file esportato da export_config_settings                        #
# --------------------------------------------------------------------------- #

# Righe nella forma:  <chiave><TAB><tipo><TAB><valore>
# La chiave del gruppo GA contiene uno spazio ("2026-08-24 00:28:30") ma mai '/'.
_RIGA_GA = re.compile(r"^/profile/(\d+)/GA/([^/]+)/([^/\t]+)\t\d+\t(.*)$")
_RIGA_SCOPE = re.compile(r"^/profile/(\d+)/scope/([^/\t]+)\t\d+\t(.*)$")


def _primo_numero(testo: str) -> Optional[float]:
    """Estrae il primo numero. I campi del GA sono formattati per la lettura umana
    ("  0.43 px (  0.22 arc-sec )", "   1.9 s ", " 1.1 arc-min"): il primo numero e'
    sempre quello nell'unita' nativa."""
    m = re.search(r"[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?", testo)
    if not m:
        return None
    try:
        return float(m.group(0))
    except ValueError:
        return None


def parse_ga_runs(testo: str, profile_id: int) -> list[GARun]:
    """Estrae le esecuzioni GA del profilo indicato, ordinate dalla piu' vecchia
    alla piu' recente. Il nome del gruppo e' `FormatISOCombined(' ')`
    (guiding_assistant.cpp:1678), quindi l'ordinamento lessicografico e' anche
    quello cronologico. PHD2 ne conserva al massimo tre (MAX_GA_HISTORY)."""
    grezzi: dict[str, dict[str, str]] = {}
    for riga in testo.splitlines():
        m = _RIGA_GA.match(riga)
        if not m or int(m.group(1)) != profile_id:
            continue
        grezzi.setdefault(m.group(2), {})[m.group(3)] = m.group(4)

    corse: list[GARun] = []
    for ts, campi in grezzi.items():
        # exposure_time e' "2s" / "1s"; elapsed_time e' "256s".
        posa_s = _primo_numero(campi.get("exposure_time", ""))
        blt = _primo_numero(campi.get("BLT_pulse", ""))
        if blt is not None and not (0 < blt <= BACKLASH_MAX_MS):
            blt = None          # campo non inizializzato: sul profilo reale 995908700
        corse.append(GARun(
            timestamp=campi.get("timestamp", ts).strip(),
            snr=_primo_numero(campi.get("snr", "")),
            exposure_ms=int(round(posa_s * 1000)) if posa_s else None,
            sample_count=_num_int(campi.get("sample_count", "")),
            elapsed_s=_num_int(campi.get("elapsed_time", "")),
            rec_ra_minmove=_primo_numero(campi.get("rec_ra_minmove", "")),
            rec_dec_minmove=_primo_numero(campi.get("rec_dec_minmove", "")),
            blt_pulse_ms=int(blt) if blt is not None else None,
            ra_drift_exposure_s=_primo_numero(campi.get("ra_drift_exposure", "")),
            ra_peak_drift_rate=_primo_numero(campi.get("ra_peak_drift_rate", "")),
            ra_hpf_rms_px=_primo_numero(campi.get("ra_hpf_rms", "")),
            dec_hpf_rms_px=_primo_numero(campi.get("dec_hpf_rms", "")),
            total_hpf_rms_px=_primo_numero(campi.get("total_hpf_rms", "")),
            pa_error_arcmin=_primo_numero(campi.get("pa_error", "")),
        ))
    # NB: `dec_corrected_rms` non viene letto — non e' inizializzato in PHD2
    # (sul profilo reale ha assunto 0.000000 e 1.78e+128 in esecuzioni diverse).
    corse.sort(key=lambda c: c.timestamp)
    return corse


def _num_int(testo: str) -> Optional[int]:
    v = _primo_numero(testo)
    return int(round(v)) if v is not None else None


@dataclass(frozen=True)
class BacklashState:
    """Stato della compensazione backlash in PHD2.

    `pulse` NON e' un valore statico: PHD2 lo **adatta a caldo** dentro la banda
    [floor, ceiling] (`BacklashComp::AdjustComp`). Confrontarlo direttamente con la
    raccomandazione del GA produce falsi allarmi — visto sul campo: GA 132 ms,
    PHD2 195 ms, ma 195 era semplicemente il tetto a cui PHD2 si era portato.

    Il valore davvero APPLICATO si ricava dal tetto: quando il GA preme il pulsante
    chiama `SetBacklashPulseWidth(rec, 0, 0)` e `SetCompValues` (backlash_comp.cpp:423)
    imposta `ceiling = 1.50 x rec`. Quindi `ceiling / 1.5` e' il valore applicato.
    """
    enabled: bool
    pulse_ms: Optional[int]
    floor_ms: Optional[int]
    ceiling_ms: Optional[int]

    @property
    def applicato_ms(self) -> Optional[int]:
        """Il valore IMPOSTATO (non quello adattato a caldo), dedotto dal tetto."""
        if self.ceiling_ms is None or self.ceiling_ms <= 0:
            return None
        return int(round(self.ceiling_ms / 1.5))


def raccomandazione_arrotondata(blt_pulse_ms: Optional[int]) -> Optional[int]:
    """Il GA non applica `BLT_pulse` grezzo ma `max(floor(blt/10)*10, 10)`
    (guiding_assistant.cpp:1506-1507). E' con QUESTO che va fatto il confronto."""
    if not blt_pulse_ms or blt_pulse_ms <= 0:
        return None
    return max(int(blt_pulse_ms // 10) * 10, 10)


def parse_backlash(testo: str, profile_id: int) -> BacklashState:
    """Stato completo della compensazione: valore corrente, banda di adattamento
    e abilitazione (`backlash_comp.cpp:448` e dintorni)."""
    campi: dict[str, str] = {}
    for riga in testo.splitlines():
        m = _RIGA_SCOPE.match(riga)
        if m and int(m.group(1)) == profile_id:
            campi[m.group(2)] = m.group(3)
    abilitato = campi.get("BacklashCompEnabled", "1").strip()
    return BacklashState(
        enabled=abilitato not in ("0", "false", "False", ""),
        pulse_ms=_num_int(campi.get("DecBacklashPulse", "")),
        floor_ms=_num_int(campi.get("DecBacklashFloor", "")),
        ceiling_ms=_num_int(campi.get("DecBacklashCeiling", "")),
    )


# --------------------------------------------------------------------------- #
#  Validazione e risoluzione                                                   #
# --------------------------------------------------------------------------- #

def motivi_di_scarto(run: GARun, *, base_exposure_ms: Optional[int],
                     snr_min: float, elapsed_min_s: int,
                     campioni_min: int,
                     scarta_per_posa: bool = False) -> list[str]:
    """Perche' questa esecuzione NON e' utilizzabile come baseline. Lista vuota =
    utilizzabile. I criteri vengono dalle quattro esecuzioni reali disponibili.

    Qui stanno solo i criteri di QUALITA' della misura. I limiti di configurazione
    (minmove_min/max) non compaiono: un limite nostro non deve far buttare una
    caratterizzazione buona. Se il valore misurato eccede il tetto viene LIMITATO
    in `risolvi`, con avviso — 1.40 limitato a 1.20 resta molto piu' vicino al
    vero di un ripiego alla formula (0.456)."""
    motivi: list[str] = []
    if not run.completo:
        motivi.append("raccomandazioni MinMove assenti")
        return motivi
    if run.snr is not None and run.snr < snr_min:
        # A SNR basso la dispersione misurata contiene il rumore di centroide, che
        # il GA non sa separare dal seeing: la raccomandazione esce gonfiata.
        motivi.append(f"SNR {run.snr:.1f} sotto {snr_min:.0f}")
    if run.elapsed_s is not None and run.elapsed_s < elapsed_min_s:
        # Sotto 1.2 x MEASUREMENT_WINDOW_SIZE (guiding_assistant.cpp:1170)
        # GetMinMoveRecs non attiva lo stimatore a finestre scorrevoli.
        motivi.append(f"durata {run.elapsed_s}s sotto {elapsed_min_s}s")
    if run.sample_count is not None and run.sample_count < campioni_min:
        motivi.append(f"{run.sample_count} campioni sotto {campioni_min}")
    # §118 — lo scarto per posa diversa NON e' piu' un criterio, ed e' disattivato
    # per difetto. Verificato sulla sorgente di PHD2: la posa a cui il GA e' stato
    # eseguito viene salvata (`/GA/<ts>/exposure_time`) e poi usata in UN solo
    # punto — `m_statusgrid->SetCellValue(m_exposuretime_loc, ...)`, cioe' per
    # MOSTRARLA nella griglia dei risultati archiviati. PHD2 non ci confronta
    # niente e non rifiuta niente: premendo Applica scrive il MinMove misurato
    # qualunque sia la posa in uso.
    #
    # La regola era nostra, ed era piu' severa dello strumento che abbiamo eletto
    # a riferimento. Il fattore che la giustificava ("fra 1 s e 2 s il MinMove
    # scala di 0.679") veniva dal confronto fra due corse a 73 GIORNI di distanza,
    # con SNR 44.0 e 64.9: fra le due era cambiata la posa, ma anche il cielo. Un
    # solo confronto, con le variabili mescolate.
    #
    # La dipendenza dalla posa esiste in linea di principio — la dispersione per
    # fotogramma cala se il fotogramma e' piu' lungo — ma non e' quantificata da
    # nessuna misura che abbiamo, e PHD2 non la corregge. Resta come AVVISO
    # graduato in `_avvisi_posa`, non come motivo di scarto.
    if (scarta_per_posa and base_exposure_ms and run.exposure_ms
            and run.exposure_ms != base_exposure_ms):
        motivi.append(f"misurato a {run.exposure_ms}ms, si guida a {base_exposure_ms}ms")
    return motivi


def _avvisi_backlash(run: GARun, backlash: Optional[BacklashState],
                     tolleranza: float) -> list[str]:
    """Due soli avvisi, entrambi su FATTI osservabili.

    Non si confronta piu' il valore configurato con la raccomandazione del GA: PHD2
    quel numero lo modula in continuazione (`TrackBLCResults`), quindi il confronto
    non dice nulla di utile — e per tre volte di fila ha prodotto consigli sbagliati.
    Del resto il test del GA, per ammissione dei suoi autori, serve a "establish a
    good seed value ... not to accurately measure the hardware performance"
    (backlash_comp.cpp:788): e' un punto di partenza, non un bersaglio.

    Resta un fatto su cui si puo' agire: PHD2 non puo' uscire dalla banda
    [floor, ceiling], e il tetto vale 1.5x il valore applicato. Se il valore corrente
    e' incollato al tetto, l'anello sta chiedendo piu' di quanto gli sia concesso.
    Successo il 24/08/2026: inchiodato a 195 per venti minuti; alzato il valore di
    partenza, e' salito a 215 e si e' assestato a 203.
    """
    if backlash is None:
        return []
    raccomandato = raccomandazione_arrotondata(run.blt_pulse_ms)
    if not backlash.enabled:
        if raccomandato is None:
            return []
        return [f"backlash: il Guiding Assistant ne ha misurato {raccomandato}ms ma "
                f"in PHD2 la compensazione e' DISATTIVATA"]
    if (backlash.pulse_ms is not None and backlash.ceiling_ms is not None
            and backlash.ceiling_ms > 0 and backlash.pulse_ms >= backlash.ceiling_ms):
        return [f"backlash: PHD2 e' fermo contro il proprio tetto ({backlash.ceiling_ms}ms) "
                f"— vorrebbe compensare di piu' e non puo'. Il tetto vale 1.5x il valore "
                f"applicato: per alzarlo, alza quel valore dalle impostazioni avanzate "
                f"di PHD2 (l'Agente non puo' scriverlo)"]
    return []


def risolvi(*, corse: list[GARun], pixel_scale_arcsec: float,
            base_exposure_ms: Optional[int], minmove_min: float,
            minmove_max: float, snr_min: float, elapsed_min_s: int,
            campioni_min: int,
            eta_avviso_giorni: int = 30,
            pa_error_avviso_arcmin: float = 5.0,
            richiedi_ga_di_sessione: bool = True,
            scarta_per_posa: bool = False,
            durate_posa_ms: Optional[list[int]] = None,
            backlash: Optional[BacklashState] = None,
            backlash_tolleranza: float = 0.20,
            adesso: Optional[dt.datetime] = None) -> Baseline:
    """Applica la gerarchia a tre livelli e produce la baseline con i suoi avvisi.
    Non solleva mai: in ogni ramo esiste un valore utilizzabile."""
    avvisi: list[str] = []
    aggr_ra = PHD2_DEFAULT_AGGR["ra"]
    aggr_dec = PHD2_DEFAULT_AGGR["dec"]

    # --- livello 1: la caratterizzazione piu' recente che superi i criteri ----
    scartate: list[tuple[GARun, list[str]]] = []
    # §112 — l'intervallo di posa e' una proprieta' del SETUP, non della posa a cui
    # si guida: va estratto dalla caratterizzazione piu' recente che superi i criteri
    # di QUALITA', ignorando il confronto sulla posa. E' il caso in cui serve di piu' —
    # "il tuo MinMove non vale a questa posa, ed ecco a quale dovresti stare".
    riferimento_posa: Optional[GARun] = None
    for run in reversed(corse):
        if not motivi_di_scarto(run, base_exposure_ms=None, snr_min=snr_min,
                                elapsed_min_s=elapsed_min_s,
                                campioni_min=campioni_min):
            riferimento_posa = run
            break
    _iv = riferimento_posa.intervallo_posa_s() if riferimento_posa else None
    _posa = dict(
        posa_min_s=_iv[0] if _iv else None,
        posa_max_s=_iv[1] if _iv else None,
        posa_limite_deriva_s=(riferimento_posa.limite_deriva_s()
                              if riferimento_posa else None),
        posa_consigliata_ms=(riferimento_posa.posa_consigliata_ms(durate_posa_ms or [])
                             if riferimento_posa else None),
        # §115 — anche l'errore polare e' una proprieta' del SETUP, non della posa:
        # viaggia con lo stesso riferimento e sopravvive allo scarto per posa diversa.
        pa_error_arcmin=(riferimento_posa.pa_error_arcmin if riferimento_posa else None),
        pa_error_soglia_arcmin=pa_error_avviso_arcmin,
        ga_riferimento_timestamp=(riferimento_posa.timestamp
                                  if riferimento_posa else None),
        ga_di_stanotte=(riferimento_posa.di_stanotte(adesso)
                        if riferimento_posa else None),
        ga_eta_giorni=(riferimento_posa.eta_giorni(adesso)
                       if riferimento_posa else None),
        pavimento_ra_px=(riferimento_posa.ra_hpf_rms_px if riferimento_posa else None),
        pavimento_dec_px=(riferimento_posa.dec_hpf_rms_px if riferimento_posa else None),
        pavimento_totale_px=(riferimento_posa.total_hpf_rms_px
                             if riferimento_posa else None),
        pavimento_totale_arcsec=(
            riferimento_posa.total_hpf_rms_px * pixel_scale_arcsec
            if riferimento_posa and riferimento_posa.total_hpf_rms_px
            and pixel_scale_arcsec else None),
    )
    # §117 — la freschezza si valuta sul RIFERIMENTO, non sulla corsa adottata:
    # la domanda e' "hai eseguito l'Assistente stanotte?", e la risposta non
    # cambia se poi quella corsa non e' utilizzabile alla posa in uso.
    _fresca = _posa["ga_di_stanotte"]
    _eta_rif = _posa["ga_eta_giorni"]
    # §125 — la soglia e' l'ETA', non la sessione. Il §117 segnalava ogni misura
    # che non fosse di stanotte: in campo, una caratterizzazione di IERI faceva
    # comparire etichetta ambra e spiegazione, che e' sproporzionato. Il seeing
    # cambia da una notte all'altra, ma una misura di pochi giorni resta un
    # riferimento onesto — molto meglio della formula generica, che e' l'unica
    # alternativa. Si avvisa solo oltre `eta_avviso_giorni`.
    _vecchia = (_eta_rif is not None and _eta_rif > eta_avviso_giorni)
    _posa["ga_vecchia"] = _vecchia
    if richiedi_ga_di_sessione and _vecchia:
        avvisi.append(
            f"l'Assistente di guida e' stato eseguito {_eta_rif:.0f} giorni fa. "
            f"Si usa lo stesso — il MinMove segue il seeing TIPICO del sito, non "
            f"quello della singola notte — ma a questa distanza conviene rifarlo: "
            f"PHD2 -> Strumenti -> Assistente di guida, alla posa operativa")

    # L'avviso si emette qui, prima dei rami: una polare storta resta storta anche
    # se la caratterizzazione viene scartata per altri motivi.
    _pa = _posa["pa_error_arcmin"]
    if _pa is not None and _pa > pa_error_avviso_arcmin:
        avvisi.append(
            f"allineamento polare: il GA misura un errore di {_pa:.1f} arcmin "
            f"(soglia {pa_error_avviso_arcmin:.0f}). Produce deriva in DEC che non e' "
            f"seeing: l'Agente non la corregge e non deve inseguirla. Si risolve a "
            f"monte, riallineando la montatura")

    for run in reversed(corse):
        motivi = motivi_di_scarto(
            run, base_exposure_ms=base_exposure_ms, snr_min=snr_min,
            elapsed_min_s=elapsed_min_s, campioni_min=campioni_min,
            scarta_per_posa=scarta_per_posa)
        if motivi:
            scartate.append((run, motivi))
            continue
        for scartata, perche in scartate:
            avvisi.append(f"GA {scartata.timestamp} ignorato: {'; '.join(perche)}")
        # I limiti di configurazione LIMITANO, non invalidano: il valore ammissibile
        # piu' vicino alla misura batte sempre un ripiego alla formula.
        ra_mm = min(max(run.rec_ra_minmove, minmove_min), minmove_max)
        dec_mm = min(max(run.rec_dec_minmove, minmove_min), minmove_max)
        for nome, misurato, applicato in (("RA", run.rec_ra_minmove, ra_mm),
                                          ("DEC", run.rec_dec_minmove, dec_mm)):
            if applicato != misurato:
                avvisi.append(
                    f"MinMove {nome}: il GA misura {misurato:.3f} px, limitato a "
                    f"{applicato:.3f} da [limits.{nome.lower()}] "
                    f"minmove_min/max [{minmove_min:.2f}, {minmove_max:.2f}]")
        avvisi.extend(_avvisi_backlash(run, backlash, backlash_tolleranza))
        avvisi.extend(_avvisi_posa(run, base_exposure_ms, durate_posa_ms))
        # L'eta' non invalida la misura — il MinMove segue il seeing TIPICO del
        # sito, non quello della singola notte — ma oltre una certa distanza vale
        # la pena rimisurarlo, e senza questo avviso una caratterizzazione di
        # quattro mesi verrebbe usata in silenzio come se fosse di stanotte.
        eta = run.eta_giorni(adesso)
        # §125 — l'avviso sull'eta' esce da un punto solo. Se la dottrina e'
        # attiva l'ha gia' emesso il blocco sopra, sulla stessa soglia.
        if (not richiedi_ga_di_sessione
                and eta is not None and eta > eta_avviso_giorni):
            avvisi.append(
                f"la caratterizzazione ha {eta:.0f} giorni: viene usata lo stesso, "
                f"ma conviene rifare l'Assistente di guida (PHD2 -> Strumenti -> "
                f"Assistente di guida) alla posa operativa")
        return Baseline(
            ra_aggr=aggr_ra, ra_minmove=ra_mm,
            dec_aggr=aggr_dec, dec_minmove=dec_mm,
            sorgente="guide_assistant",
            dettaglio=_dettaglio_ga(run, eta),
            ga=run, backlash=backlash, avvisi=avvisi, **_posa)

    # --- livello 2: la formula di PHD2 ---------------------------------------
    for scartata, perche in scartate:
        avvisi.append(f"GA {scartata.timestamp} ignorato: {'; '.join(perche)}")
    if not corse:
        avvisi.append(
            "l'Assistente di guida non e' mai stato eseguito su questo profilo: "
            "i valori di partenza sono stimati dalla scala del sensore, non "
            "misurati. Per misurarli: PHD2 -> Strumenti -> Assistente di guida, "
            "alla posa operativa, almeno 4-5 minuti, poi premi Applica")
    else:
        avvisi.append(
            "nessuna caratterizzazione utilizzabile fra quelle presenti: i valori "
            "di partenza sono stimati, non misurati. Rifai l'Assistente di guida "
            "(PHD2 -> Strumenti -> Assistente di guida) alla posa operativa")

    formula = smart_default_minmove(pixel_scale_arcsec)
    if formula is not None:
        mm = min(max(formula, minmove_min), minmove_max)
        if mm != formula:
            avvisi.append(f"formula PHD2 {formula:.3f} px limitata a {mm:.3f} "
                          f"dai limiti [{minmove_min:.2f}, {minmove_max:.2f}]")
        return Baseline(
            ra_aggr=aggr_ra, ra_minmove=mm, dec_aggr=aggr_dec, dec_minmove=mm,
            sorgente="formula_phd2",
            dettaglio=(f"SmartDefaultMinMove a {pixel_scale_arcsec:.3f} arcsec/px "
                       f"= {mm:.3f} px"),
            backlash=backlash, avvisi=avvisi, **_posa)

    # --- livello 3: fallback -------------------------------------------------
    avvisi.append(
        f"scala pixel non utilizzabile ({pixel_scale_arcsec:.3f}): PHD2 restituisce "
        f"esattamente 1.0 quando non conosce focale o pixel — impossibile "
        f"distinguerla da una scala vera. Uso il default di classe PHD2")
    mm = min(max(PHD2_DEFAULT_MINMOVE, minmove_min), minmove_max)
    return Baseline(
        ra_aggr=aggr_ra, ra_minmove=mm, dec_aggr=aggr_dec, dec_minmove=mm,
        sorgente="fallback_phd2",
        dettaglio=f"DefaultMinMove delle classi PHD2 = {mm:.2f} px",
        backlash=backlash, avvisi=avvisi, **_posa)


def _dettaglio_ga(run: GARun, eta_giorni: Optional[float]) -> str:
    """Riga di dettaglio della card: cosa e' stato misurato, e quanto tempo fa."""
    parti = [f"GA {run.timestamp}"]
    if run.snr is not None:
        parti.append(f"SNR {run.snr:.1f}")
    if run.elapsed_s and run.exposure_ms:
        parti.append(f"{run.elapsed_s}s @ {run.exposure_ms}ms")
    if eta_giorni is not None:
        if eta_giorni < 1:
            parti.append("di oggi")
        elif eta_giorni < 2:
            parti.append("di ieri")
        else:
            parti.append(f"{eta_giorni:.0f} giorni fa")
    return " — ".join(parti)


def _avvisi_posa(run: GARun, base_exposure_ms: Optional[int],
                 durate_ms: Optional[list[int]]) -> list[str]:
    """§111 — la posa di guida confrontata con la caratterizzazione.

    Il GA non da' un valore unico ma un INTERVALLO, e dentro quell'intervallo il
    punto giusto lo fissa il limite-deriva (`MinMove / deriva_di_picco`). Nessuno
    finora confrontava la posa dichiarata con nessuno dei due.

    §118 — l'intervallo nasce nel codice di PHD2 da due costanti (2.0 e 4.0 s per
    montature senza encoder, larghezza fissa `min_rec_range = 2.0`) col bordo
    inferiore abbassato quando la deriva lo impone. E' un'opinione generale sulle
    buone pose di guida: NON dice niente sulla validita' del MinMove. Ma e' l'unico
    confine che PHD2 dichiara setup per setup, e lo usiamo per graduare l'avviso —
    lieve dentro, forte fuori — non per scartare.
    """
    avvisi: list[str] = []
    intervallo = run.intervallo_posa_s()
    if intervallo is None:
        return avvisi
    minimo, massimo = intervallo

    # 1. La caratterizzazione e' coerente con se stessa? Se il GA e' stato fatto a
    #    1 s ma raccomanda 1.5-3.5, quella misura descrive un regime che non e'
    #    quello che raccomanda. Successo davvero: i GA di aprile e giugno.
    consigliata = run.posa_consigliata_ms(durate_ms or [])
    if run.exposure_ms and consigliata and run.exposure_ms != consigliata:
        avvisi.append(
            f"la caratterizzazione e' stata misurata a {run.exposure_ms / 1000:.1f}s "
            f"ma raccomanda {consigliata / 1000:.1f}s: per una misura pienamente "
            f"coerente rifai l'Assistente di guida a {consigliata / 1000:.1f}s")

    if not base_exposure_ms:
        return avvisi
    base_s = base_exposure_ms / 1000.0

    # 2. Fuori dall'intervallo raccomandato.
    if base_s < minimo - 1e-9 or base_s > massimo + 1e-9:
        avvisi.append(
            f"guidi a {base_s:.1f}s, fuori dall'intervallo raccomandato dal GA "
            f"({minimo:.1f}-{massimo:.1f}s)")
        return avvisi

    # 2-bis. Posa diversa da quella della misura, ma entrambe dentro l'intervallo
    #        che PHD2 raccomanda per questo setup. Nota informativa, non allarme:
    #        PHD2 stesso applica il MinMove misurato senza guardare la posa in uso.
    if (run.exposure_ms and run.exposure_ms != base_exposure_ms
            and minimo - 1e-9 <= run.exposure_ms / 1000.0 <= massimo + 1e-9):
        avvisi.append(
            f"il MinMove e' stato misurato a {run.exposure_ms / 1000:.1f}s e stai "
            f"guidando a {base_s:.1f}s: entrambe dentro l'intervallo raccomandato "
            f"({minimo:.1f}-{massimo:.1f}s), quindi il valore si usa — con una posa "
            f"piu' lunga la zona morta ideale sarebbe un po' piu' stretta")

    # 3. Dentro l'intervallo ma oltre il vincolo fisico. L'intervallo del GA e'
    #    largo 2 s per costruzione ed e' piu' permissivo del limite-deriva: si puo'
    #    essere "dentro la raccomandazione" e comunque sopra il limite.
    limite = run.limite_deriva_s()
    if limite and base_s > limite * 1.15:
        avvisi.append(
            f"guidi a {base_s:.1f}s: dentro l'intervallo GA ({minimo:.1f}-{massimo:.1f}s) "
            f"ma sopra il limite-deriva di {limite:.1f}s — fra una correzione e "
            f"l'altra la deriva supera la banda morta")
    return avvisi
