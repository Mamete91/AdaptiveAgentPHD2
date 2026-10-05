"""
§57 S2 — RecoveryHintTracker: "il cielo sta tornando?" dalla SNR della stella guida.

§126 — LA GUIDA GIUDICA IL CIELO (decisione dell'operatore del 04/10/2026, dopo la
forense della notte 3-4/10). Questo modulo smette di essere un "suggeritore" della
camera di ripresa e diventa il SENSORE del giudice: degrado, recupero e riferimento
SNR si valutano a ogni frame, qualunque cosa dica N1. Il motivo, misurato: il 3-4/10
una posa con stelle allungate ha portato N1 a 0.457 e il monitor in UNSAFE per tre
ore, mentre la stella di guida — stesso tubo (OAG), stesso cielo — aveva SNR 66.3
contro un riferimento di 65.5. La camera di ripresa resta informativa (dashboard).
Quanto scritto sotto sulla "autorita' zero" vale per il codice di QUESTO modulo, che
resta pura misura: la decisione la prende il plugin, ora con questi segnali.

Contesto (deadlock provato, notte 12/7): durante l'attesa UNSAFE NINA non salva light
→ N1 congelato → N6 non può tornare SAFE. Ma la SNR guida (GuideStep di PHD2) continua
a fluire: è un segnale di cielo indipendente dai light. Questo tracker la integra e
stima un HINT di recupero che può solo ANTICIPARE la posa-sonda S1 (istruzione
RecoveryProbe del plugin). PALETTO 1 — autorità ZERO sulla safety: questo modulo non ha
alcun percorso verso N6/IsSafe; espone solo osservazione su /status.

La SNR guida è un proxy CONTAMINATO (seeing/fuoco/magnitudine della stella guida):
una stella luminosa sopravvive a velature sottili. Per questo l'hint non giudica mai:
la verità resta la camera di imaging (posa-sonda → N1 → drain §55 → N6).

Dinamica (§57-bis, Gate): accumulatore leaky IN SECONDI DI TEMPO REALE — sale di dt sui
frame con SNR "buona" (>= max(floor, frac×snr_ref)), scende di drain_factor×dt sugli
altri; latch active a sustained_seconds, rilascio a 0. Il criterio è così indipendente
dal frame-rate di guida (0.5–4 s per setup) e fisicamente coerente col cielo.
Gating: valutato solo se l'ultimo stato N1 noto è degradato (CLOUD/HAZE); a CLEAR è
inerte e aggiorna snr_ref (EMA della SNR di cielo limpido, il riferimento pre-nube).

Fratello di N1 (non lo importa, non lo modifica): legge lo stato via un provider
read-only iniettato da main.py.
"""
from __future__ import annotations

import json
import logging
import threading
import time
from collections import deque
from pathlib import Path
from typing import Any, Callable, Optional

from .config import RecoveryHintConfig

logger = logging.getLogger(__name__)

# EMA della SNR di riferimento in CLEAR: lenta (il riferimento è "com'era il cielo
# limpido", non l'ultimo frame).
_SNR_REF_ALPHA = 0.05

# dt massimo accreditabile per un singolo frame (s): un buco lungo tra frame (stella
# persa, dithering) non deve accreditare "tempo buono" fantasma al frame successivo.
_MAX_FRAME_DT_S = 5.0

# §76-bis — emivita del RILASCIO verso il basso del riferimento SNR, in minuti di
# tempo reale. Stessa costante e stesso principio del §66 (regola 3): il metro può
# scendere, ma molto più lentamente di quanto scenda il cielo — altrimenti insegue
# il degrado e lo rende invisibile a se stesso.
_SNR_REF_RELEASE_HALF_LIFE_MIN = 25.0

_DEGRADED = ("CLOUD", "HAZE")


class RecoveryHintTracker:
    """Osserva la SNR guida per-frame ed espone l'hint di recupero su /status."""

    def __init__(
        self,
        config: RecoveryHintConfig,
        state_provider: Optional[Callable[[], tuple[Optional[str], Optional[float]]]] = None,
        now_fn: Callable[[], float] = time.time,
        stato_file: Optional[Path] = None,
    ) -> None:
        self.cfg = config
        # provider read-only dell'ultimo (state, index) di N1; None => gating inerte.
        self._state_provider = state_provider
        self._now = now_fn          # iniettabile nei test (clock finto)
        self._lock = threading.Lock()

        self._snr_ref: Optional[float] = None      # SNR media pre-nube (catturata in CLEAR)
        self._last_snr: Optional[float] = None
        self._last_frame_ts: Optional[float] = None
        self._accumulator_s: float = 0.0            # secondi di segnale buono accumulati (leaky)
        self._active: bool = False
        self._active_since: Optional[float] = None
        self._reason: str = "in attesa di frame"
        self._last_seen_state: Optional[str] = None  # stato N1 all'ultimo frame (pre-sonda)

        # §76 — accumulatore della polarità OPPOSTA: evidenza di DEGRADO. Vive
        # nella stessa classe perché condivide il riferimento `snr_ref` — due
        # copie dell'EMA divergerebbero, e il riferimento È il metro di entrambi.
        self._degrade_s: float = 0.0
        self._degrading: bool = False
        self._degrading_since: Optional[float] = None
        self._degrade_reason: str = "in attesa di frame"

        # Telemetria sonde (paletto 8): ultimi record, esposti su /status e dashboard.
        self._probes: deque[dict[str, Any]] = deque(maxlen=12)

        # §126 — stato del cielo VISTO DALLA GUIDA, indipendente dalla camera di
        # ripresa. Diventa DEGRADED quando l'evidenza di degrado si conferma e
        # torna CLEAR solo con l'evidenza opposta (recupero sostenuto). In mezzo il
        # riferimento non scende (vedi _ref_frozen).
        self._sky_state: str = "CLEAR"
        self._sky_state_since: Optional[float] = None
        self._ref_reset_reason: Optional[str] = None

        # §126-bis — da quando la SNR sta sotto la soglia di sereno (80%). Anche fra
        # il 50% e l'80% il metro non deve scendere: una velatura al 65% lo
        # erodeva da 65 a 46.6 in un'ora e il sereno si "confermava" con SNR 42
        # (verifica del 05/10, simulazione con le classi vere).
        self._below_recover_since: Optional[float] = None
        # §126-bis — l'ultimo giudizio prima di un cambio di stella: si reimpara il
        # riferimento SOLO se il cielo era confermato sereno. Non lo azzera
        # sospendi(): deve sopravvivere allo stop che precede la ripartenza.
        self._sereno_confermato: bool = False
        self._ref_ereditato: bool = False
        # §126-ter/quater — la stella PRECEDENTE in attesa del primo dato della
        # nuova (vedi reset_stella): riferimento, ultimo dato e suo istante, e se la
        # guida la vedeva gia' sotto le nubi (solo allora si trasporta, §126-quinquies).
        self._ref_prima_del_cambio: Optional[float] = None
        self._cambio: Optional[dict] = None
        self._ultimo_snr_ts: Optional[float] = None
        # §126-quater — da quando il riferimento e' ereditato: il tetto si conta da
        # qui, non dall'inizio del degrado della stella precedente.
        self._ereditato_dal: Optional[float] = None
        # §126-quater — posizione della stella che il riferimento descrive (per la
        # memoria su disco) e memoria letta ma non ancora confermata.
        self._posizione: Optional[tuple] = None
        self._memoria_candidata: Optional[dict] = None
        # §126-ter — orologio dei soli frame persi: on_star_lost non deve toccare
        # quello dei GuideStep. Il rigioco del 4/8 l'ha mostrato: spostandolo, con
        # nubi a chiazze il degrado arrivava ~20 s piu' tardi e l'UNSAFE delle
        # 23:13:45 non scattava prima che NINA fermasse la guida.
        self._last_lost_ts: Optional[float] = None

        # §126-bis — memoria su disco del giudizio, per un riavvio dell'Agente a
        # notte in corso: senza, il primo frame fissava il metro al cielo di quel
        # momento e un UNSAFE per nubi tornava SAFE sotto le stesse nubi.
        self._stato_file = stato_file
        self._ultimo_salvataggio: float = 0.0
        self._carica_stato()

    # ------------------------------------------------------------------ #
    #  Aggiornamento per-frame (thread del loop principale)               #
    # ------------------------------------------------------------------ #

    def update(self, snr: Optional[float]) -> None:
        """Un guide-frame: integra la SNR negli accumulatori a tempo.

        §126 — degrado, recupero e riferimento si valutano a OGNI frame. Prima il
        ramo dipendeva dallo stato N1 della camera di ripresa: in CLEAR si cercava
        solo il degrado e si imparava il riferimento, in CLOUD/HAZE solo il
        recupero. Lo stato N1 resta letto per la sola telemetria delle sonde.
        """
        if not self.cfg.enabled:
            return
        if snr is None or not (snr > 0):
            return   # frame senza SNR utile: non conta né a favore né contro

        state, _index = self._read_state()
        now = self._now()
        snr = float(snr)
        with self._lock:
            # dt reale dal frame precedente, clampato (buchi lunghi non accreditano tempo).
            dt = 0.0
            if self._last_frame_ts is not None:
                dt = min(max(now - self._last_frame_ts, 0.0), _MAX_FRAME_DT_S)
            self._last_frame_ts = now
            self._last_snr = snr
            self._ultimo_snr_ts = now
            self._last_seen_state = state

            # L'ORDINE CONTA: il frame si giudica col metro di PRIMA, poi il metro
            # si aggiorna — altrimenti il frame eroderebbe il riferimento con cui
            # sta per essere misurato (§76-bis).
            self._update_degrade(snr, dt, now)
            self._update_recover(snr, dt, now)
            self._update_sky_state(now)
            if self._snr_ref is not None and snr < self._recover_threshold():
                if self._below_recover_since is None:
                    self._below_recover_since = now
            else:
                self._below_recover_since = None
            self._update_snr_ref(snr, dt, now)
            self._sereno_confermato = (self._sky_state == "CLEAR"
                                       and self._degrade_s <= 0.0 and self._active)
            if self._sereno_confermato:
                self._ref_ereditato = False
                self._ereditato_dal = None
            self._salva_stato(now)

    def on_star_lost(self) -> None:
        """§126-bis — un frame con la stella PERSA non e' evidenza di sereno.

        Prima gli StarLost non arrivavano qui: durante una perdita `sky_ok` restava
        al valore dell'ultimo GuideStep e un latch del cielo poteva scaricarsi su
        un sereno vecchio. Qui si scarica solo l'accumulatore del sereno, con la
        stessa velocita' dei frame cattivi; degrado e riferimento non si toccano
        (contare la stella persa come degrado renderebbe la guida piu' sensibile:
        e' una scelta da fare sui dati, non qui).
        """
        if not self.cfg.enabled:
            return
        now = self._now()
        with self._lock:
            ultimo = max(t for t in (self._last_frame_ts, self._last_lost_ts) if t is not None) \
                if (self._last_frame_ts is not None or self._last_lost_ts is not None) else None
            dt = 0.0 if ultimo is None else min(max(now - ultimo, 0.0), _MAX_FRAME_DT_S)
            self._last_lost_ts = now
            self._accumulator_s = max(0.0, self._accumulator_s - self.cfg.drain_factor * dt)
            if self._accumulator_s <= 0.0 and self._active:
                self._set_active(False, now, "stella persa: nessuna evidenza di sereno")
            if self._sereno_confermato:
                self._sereno_confermato = False
                self._salva_stato(now, forza=True)

    def _recover_threshold(self) -> float:
        """Soglia di sereno.

        §126-bis — la frazione del riferimento quando il riferimento c'e'; il floor
        assoluto SOLO quando manca. Prima era max(floor, frazione): con una stella
        di guida debole (sereno sotto SNR ~31) la soglia superava l'80% e sotto 25
        il sereno non si confermava MAI — mentre il degrado su quella stella
        funzionava gia'. Un UNSAFE senza uscita (verifica del 05/10).
        """
        if self._snr_ref is None:
            return self.cfg.snr_recover_floor
        return self.cfg.snr_recover_frac * self._snr_ref

    def _update_recover(self, snr: float, dt: float, now: float) -> None:
        """Evidenza di SERENO dalla guida (chiamata sotto lock).

        Stessa dinamica del §57-bis — accumulatore leaky in secondi, sale di dt sui
        frame buoni, scende di drain_factor×dt sugli altri — ma valutata SEMPRE:
        con il §126 e' l'evidenza con cui il plugin riporta SAFE.
        """
        threshold = self._recover_threshold()
        target = max(1.0, self.cfg.sustained_seconds)
        if snr >= threshold:
            self._accumulator_s = min(target, self._accumulator_s + dt)
        else:
            self._accumulator_s = max(0.0, self._accumulator_s - self.cfg.drain_factor * dt)

        if self._accumulator_s >= target:
            self._set_active(True, now,
                             f"snr {snr:.1f} >= {threshold:.1f} sostenuta per "
                             f"{self._accumulator_s:.0f}s")
            # §126-bis — il sereno confermato chiude il degrado residuo: prima il
            # flag restava acceso fino a 90 s dopo il ritorno della SNR e il plugin
            # continuava a contare verso un UNSAFE a nube gia' passata.
            if self._degrading or self._degrade_s > 0.0:
                self._reset_degrade(now, "sereno confermato dalla guida")
        elif self._accumulator_s <= 0.0 and self._active:
            self._set_active(False, now, f"snr {snr:.1f} < {threshold:.1f} — accumulatore esaurito")
        elif not self._active:
            self._reason = (f"snr {snr:.1f} {'≥' if snr >= threshold else '<'} "
                            f"{threshold:.1f} — {self._accumulator_s:.0f}/"
                            f"{target:.0f}s (non sostenuto)")

    def _update_sky_state(self, now: float) -> None:
        """§126 — macchina a due stati del cielo visto dalla guida (sotto lock).

        Si entra in DEGRADED quando il degrado si conferma; si torna CLEAR solo con
        il recupero sostenuto e nessun degrado in corso. Fra le due soglie (50% e
        80% del riferimento) lo stato NON cambia: e' l'isteresi.
        """
        if self._degrading and self._sky_state != "DEGRADED":
            self._sky_state = "DEGRADED"
            self._sky_state_since = now
            logger.info("[cielo-guida] DEGRADATO — %s", self._degrade_reason)
            self._salva_stato(now, forza=True)
        elif self._sky_state == "DEGRADED" and self._active and not self._degrading:
            self._sky_state = "CLEAR"
            self._sky_state_since = now
            logger.info("[cielo-guida] tornato SERENO — %s", self._reason)
            self._salva_stato(now, forza=True)

    def _ref_frozen(self, now: float) -> bool:
        """§126 — il riferimento NON scende mentre la guida vede il cielo peggiore
        del sereno (chiamata sotto lock).

        Senza questo, con la guida unico giudice, una velatura lunga eroderebbe il
        metro (emivita 25 min) fino a far sembrare "sereno" il cielo velato: a SNR
        60% il ritorno a SAFE arriverebbe da solo dopo ~35 minuti. E' la stessa
        "rana bollita" del §66 per N1, e la stessa cura: congelamento, con un tetto
        (`snr_ref_freeze_max_min`, stesso principio di `ref_freeze_max_min` di N1)
        oltre il quale il degrado stabile diventa la nuova normalita'.
        """
        # §126-bis — il congelamento parte dal primo momento in cui la guida vede il
        # cielo sotto il sereno (sotto l'80%, o in DEGRADED) e il TETTO vale sempre.
        # Prima il ramo "degrado in corso" veniva prima del tetto: con SNR stabile
        # sotto il 50% (guasto della camera di guida, 3/10 22:36) il metro restava
        # fermo per sempre e l'UNSAFE non rientrava mai.
        if self._ref_ereditato and self._ereditato_dal is not None:
            # §126-quater — il riferimento di un'ALTRA stella: il tetto si conta dal
            # cambio. Contato dall'inizio del degrado della stella precedente, dopo
            # 90 minuti di nubi una ripartenza della sonda faceva reimparare subito
            # il metro sotto le stesse nubi (revisione finale, AG-3).
            return (now - self._ereditato_dal) < self.cfg.snr_ref_freeze_max_min * 60.0
        inizio: Optional[float] = None
        if self._sky_state == "DEGRADED":
            inizio = self._sky_state_since if self._sky_state_since is not None else now
        if self._below_recover_since is not None:
            inizio = (self._below_recover_since if inizio is None
                      else min(inizio, self._below_recover_since))
        if inizio is None:
            return False
        return (now - inizio) < self.cfg.snr_ref_freeze_max_min * 60.0

    def _update_snr_ref(self, snr: float, dt: float, now: float) -> None:
        """Riferimento SNR di cielo limpido — EMA con CRICCHETTO (chiamata sotto lock).

        §76-bis — difetto trovato scrivendo il replay della notte 4/8: l'EMA
        simmetrica faceva colare il riferimento INSIEME al cielo. Durante il
        crollo (70 -> 23, con N1 ancora CLEAR perché fermo all'ultima posa buona)
        il riferimento scendeva da 70 a 26 e la soglia relativa da 35 a 13: il
        degrado diventava INVISIBILE al proprio stesso metro. È la "rana bollita"
        del §66, identica, in un altro componente — lì il riferimento era il
        conteggio stelle di N1, qui è la SNR di guida.

        Cura, stessa del §66: il miglioramento si adotta subito ("le nubi non
        creano segnale"), il peggioramento NON erode il riferimento finché c'è
        evidenza di degrado in corso. Il congelamento è auto-limitato: appena
        l'evidenza rientra (cielo risalito, o era un transitorio) l'EMA riprende
        normalmente, e se il degrado è reale N1 lo riconosce e questo ramo non
        viene più eseguito.

        Il difetto colpiva ANCHE l'hint di recupero (§57), nel verso opposto: un
        riferimento eroso rende il recupero troppo facile da dichiarare, quindi
        anticipa sonde su cielo ancora cattivo. Questa correzione risana entrambe
        le polarità.
        """
        if self._snr_ref is None:
            cambio = self._cambio
            self._cambio = None
            self._ref_prima_del_cambio = None
            if cambio is None:
                self._snr_ref = snr
                return
            self._decidi_stella_nuova(cambio, snr, now)
            return
        if snr >= self._snr_ref:
            # Regola 1 (§66): il miglioramento si adotta subito — "le nubi non
            # creano segnale", quindi una SNR più alta è sempre informazione vera.
            self._snr_ref = (1 - _SNR_REF_ALPHA) * self._snr_ref + _SNR_REF_ALPHA * snr
            return
        # Regola 3 (§66): verso il basso si scende con emivita LUNGA misurata in
        # tempo reale, non a colpi di frame. Con l'EMA simmetrica il riferimento
        # perdeva il 62% in 4 minuti di crollo (70 -> 26) e la soglia crollava con
        # lui; così ne perde meno del 6% e il degrado resta misurabile. Il cielo
        # che peggiora DAVVERO e stabilmente viene comunque riconosciuto da N1
        # sull'immagine — che è il giudice giusto per un cambio di livello.
        # §126 — N1 non giudica piu': il cambio di livello stabile lo riconosce il
        # tetto al congelamento (_ref_frozen), non piu' la camera di ripresa.
        if self._ref_frozen(now):
            return
        if self._ref_ereditato:
            # §126-ter — tetto scaduto su un riferimento di un'ALTRA stella: niente
            # discesa lenta (non c'e' una deriva da proteggere), si reimpara.
            logger.info("[cielo-guida] tetto scaduto sul riferimento ereditato (%.1f): "
                        "si reimpara dalla stella attuale (%.1f)", self._snr_ref, snr)
            self._snr_ref = snr
            self._ref_ereditato = False
            self._below_recover_since = None
            return
        if dt > 0:
            keep = 0.5 ** ((dt / 60.0) / _SNR_REF_RELEASE_HALF_LIFE_MIN)
            self._snr_ref = snr + (self._snr_ref - snr) * keep

    def _decidi_stella_nuova(self, cambio: dict, snr: float, now: float) -> None:
        """§126-quater — primo dato di una stella NUOVA (chiamata sotto lock).

        La revisione finale ha mostrato che con la sonda di guida le ripartenze
        durante un UNSAFE fanno riselezionare la stella a PHD2 SOTTO LE NUBI; con le
        regole di prima il metro poteva rinascere al livello della nube (SAFE con il
        cielo coperto) o, all'opposto, una stella piu' debole restava bloccata.
        Tre casi, dal piu' informato:
          1. TRASPORTO — la guida vedeva gia' il cielo DEGRADATO, l'ultimo dato della
             stella vecchia ha al massimo `ponte_stella_max_s` ed era credibile
             (sopra il 50% del suo metro): le due misure vedono la stessa nube, quindi
             metro_nuovo = metro_vecchio x (snr_nuova / snr_vecchia). E' il caso della
             sonda di guida, che agisce solo durante l'UNSAFE.
             §126-quinquies — SOLO a cielo degradato. A cielo sereno il rapporto si
             misura su due pose singole e il rumore lo gonfia: rigioco del 17/8 alle
             02:53, ultima posa della stella vecchia al 75% del suo metro (32.6 su
             43.3, la stella oscillava attorno all'80%), metro alzato da 43.3 a 52.3,
             stella nuova ferma al 65-70% e un calo breve alle 03:22 dava UNSAFE fino
             a fine notte. Reimparando (giro 4) nessun UNSAFE.
          2. EREDITA' — la stella nuova parte sotto il 50% del metro vecchio (per
             quel metro e' una nube): si tiene il metro vecchio, con il tetto contato
             da adesso. NON basta che la guida vedesse gia' il cielo degradato: il
             rigioco del 3/10 (guasto della camera di guida, poi stella nuova) dava
             quasi tre ore di UNSAFE a cielo sereno. Scelta dichiarata: meglio qualche
             posa sotto una nube (tempo comunque perso) che una notte ferma a cielo
             sereno (tempo buono buttato).
          3. altrimenti si reimpara (19/7 02:53: stella nuova al 66%, cielo sereno;
             3/10 22:55: stella piu' debole dopo l'autofocus).
        Limite noto, dichiarato: senza un dato recente e credibile della stella
        vecchia, una stella nuova piu' luminosa sotto la stessa nube e' indistinguibile,
        con la sola SNR, da una stella piu' debole a cielo sereno: si reimpara.
        """
        vecchio = cambio["ref"]
        snr_vecchia = cambio.get("snr")
        ts_vecchia = cambio.get("ts")
        frac = self.cfg.snr_degrade_frac
        degradato = bool(cambio.get("degradato"))
        recente = ts_vecchia is not None and now - ts_vecchia <= self.cfg.ponte_stella_max_s
        credibile = snr_vecchia is not None and snr_vecchia >= frac * vecchio
        if degradato and recente and credibile:
            self._snr_ref = vecchio * snr / snr_vecchia
            self._ref_ereditato = False
            self._ereditato_dal = None
            self._ref_reset_reason = (f"{self._ref_reset_reason or 'nuova stella'} "
                                      f"(riferimento trasportato: {vecchio:.1f} x "
                                      f"{snr:.1f}/{snr_vecchia:.1f})")
            logger.info("[cielo-guida] stella nuova: riferimento TRASPORTATO %.1f -> %.1f "
                        "(rapporto %.2f misurato fra le due stelle)", vecchio,
                        self._snr_ref, snr / snr_vecchia)
            return
        if snr <= frac * vecchio:
            self._snr_ref = vecchio
            self._ref_ereditato = True
            self._ereditato_dal = now
            perche = f"{snr:.1f} <= {frac:.0%} di {vecchio:.1f}"
            self._ref_reset_reason = (f"{self._ref_reset_reason or 'nuova stella'} "
                                      f"(riferimento ereditato: {perche})")
            logger.info("[cielo-guida] stella nuova: tengo il riferimento %.1f (%s)", vecchio, perche)
            return
        logger.info("[cielo-guida] stella nuova a %.1f (riferimento precedente %.1f): "
                    "si reimpara", snr, vecchio)
        self._snr_ref = snr
        self._below_recover_since = None
        self._ref_ereditato = False
        self._ereditato_dal = None

    def _update_degrade(self, snr: float, dt: float, now: float) -> None:
        """§76 — accumulatore leaky del DEGRADO (chiamata sotto lock; dal §126 a ogni frame).

        Simmetrico all'hint ma con asimmetrie deliberate:
          • soglia più severa (50% del riferimento contro l'80% del recupero) e
            sostegno più lungo (90 s contro 60 s): un falso positivo qui mette in
            pausa la sequenza, quindi si chiede più evidenza;
          • serve un `snr_ref` credibile: senza riferimento, o con riferimento
            troppo basso, il rapporto non significa nulla → nessuna evidenza
            (fail-inert, mai "degrado per assenza di dati").

        Resta pura MISURA: non dichiara UNSAFE. Il plugin la usa per ACCUMULARE
        verso unsafe; a drenare, dal §126, e' l'evidenza opposta (_update_recover).
        """
        if not self.cfg.degrade_enabled:
            return
        if self._snr_ref is None or self._snr_ref < self.cfg.degrade_min_ref:
            self._reset_degrade(now, "riferimento SNR non ancora affidabile")
            return

        threshold = self.cfg.snr_degrade_frac * self._snr_ref
        target = max(1.0, self.cfg.degrade_sustained_seconds)
        if snr <= threshold:
            self._degrade_s = min(target, self._degrade_s + dt)
        else:
            self._degrade_s = max(0.0, self._degrade_s - dt)

        if self._degrade_s >= target and not self._degrading:
            self._degrading = True
            self._degrading_since = now
            self._degrade_reason = (f"snr {snr:.1f} <= {threshold:.1f} "
                                    f"({self.cfg.snr_degrade_frac:.0%} del riferimento "
                                    f"{self._snr_ref:.1f}) sostenuta per {self._degrade_s:.0f}s")
            logger.info("[recovery_hint] DEGRADO — %s", self._degrade_reason)
        elif self._degrade_s <= 0.0 and self._degrading:
            self._reset_degrade(now, f"snr {snr:.1f} risalita sopra {threshold:.1f}")
        elif not self._degrading:
            self._degrade_reason = (f"snr {snr:.1f} {'≤' if snr <= threshold else '>'} "
                                    f"{threshold:.1f} — {self._degrade_s:.0f}/{target:.0f}s")

    def _reset_degrade(self, now: float, reason: str) -> None:
        """Rientro dell'evidenza di degrado (chiamata sotto lock)."""
        was = self._degrading
        self._degrade_s = 0.0
        self._degrading = False
        self._degrading_since = None
        self._degrade_reason = reason
        if was:
            logger.info("[recovery_hint] degrado rientrato — %s", reason)

    def _set_active(self, value: bool, now: float, reason: str) -> None:
        if value and not self._active:
            self._active_since = now
            logger.info("[recovery_hint] ACTIVE — %s (snr_ref=%s)", reason,
                        f"{self._snr_ref:.1f}" if self._snr_ref is not None else "n/d")
        elif not value and self._active:
            logger.info("[recovery_hint] rientrato — %s", reason)
            self._active_since = None
        self._active = value
        self._reason = reason

    def sospendi(self, motivo: str) -> None:
        """§126 — la guida si ferma (stop, calibrazione, anello aperto).

        Gli accumulatori non devono restare accesi su un dato che non arriva piu'.
        Il report del 04/10 lo prova per la stella persa (24/8: UNSAFE durante una
        calibrazione, da uno stato rimasto congelato) e lo mostra nel codice per il
        flag di degrado: il plugin continuava a contarlo. Il riferimento resta: la
        stella e' la stessa finche' PHD2 non ne seleziona un'altra (reset_stella).
        """
        with self._lock:
            now = self._now()
            self._last_frame_ts = None
            self._accumulator_s = 0.0
            self._set_active(False, now, f"guida sospesa: {motivo}")
            self._reset_degrade(now, f"guida sospesa: {motivo}")

    def reset_stella(self, motivo: str) -> None:
        """§126 — PHD2 ha selezionato una stella (evento StarSelected).

        Il riferimento SNR era della stella precedente. Il 3/10 alle 22:55, dopo
        l'autofocus, PHD2 ha scelto da solo una stella con SNR 37-39 contro il
        riferimento 65.5 della precedente: con il metro vecchio sembrava una
        velatura al 60%. Si reimpara dal primo frame della stella nuova.
        §126-bis — si reimpara SOLO se il cielo era confermato sereno. Altrimenti
        il metro nuovo nascerebbe sotto le nubi: il 3/8 alle 23:34 la stella nuova
        partiva da SNR 14 e il riferimento diventava 16, poi il "sereno" si
        confermava a SNR 43 mentre l'autofocus vedeva 0-6 stelle. In quel caso si
        tiene il riferimento della stella precedente (ereditato) finche' la guida
        non conferma il sereno; il tetto al congelamento limita l'attesa se la
        stella nuova e' piu' debole di natura.
        """
        with self._lock:
            now = self._now()
            self._last_frame_ts = None
            self._accumulator_s = 0.0
            self._set_active(False, now, f"nuova stella: {motivo}")
            self._reset_degrade(now, f"nuova stella: {motivo}")
            # §126-quater — il cambio si registra SEMPRE e decide il primo dato della
            # stella nuova (_decidi_stella_nuova). Il vecchio ramo "cielo confermato
            # sereno -> si reimpara" e' stato tolto: quella conferma era una
            # fotografia dell'ultimo GuideStep, sopravviveva a pause e stelle perse,
            # e il 16/8 alle 03:01 (rigioco, autofocus partito a cielo sereno e nube
            # durante l'autofocus) faceva reimparare il metro da 60.8 a 6.1.
            if self._snr_ref is not None:
                self._cambio = {
                    "ref": self._snr_ref,
                    "snr": self._last_snr,
                    "ts": self._ultimo_snr_ts,
                    "degradato": self._sky_state == "DEGRADED" or self._degrading,
                }
                self._ref_prima_del_cambio = self._snr_ref
                logger.info("[cielo-guida] stella nuova (%s): il primo dato decide il "
                            "riferimento (era %.1f)", motivo, self._snr_ref)
            # (con _snr_ref gia' None un cambio in sospeso resta: piu' selezioni di
            # fila prima del primo dato non lo perdono, §126-ter)
            self._ref_reset_reason = motivo
            self._snr_ref = None
            self._ref_ereditato = False
            self._ereditato_dal = None
            self._salva_stato(now, forza=True)

    _CAMPI_STATO = ("snr_ref", "sky_state", "sky_state_since", "below_recover_since",
                    "sereno_confermato", "ref_ereditato")

    def _carica_stato(self) -> None:
        """§126-bis — riprende il giudizio salvato, se e' della notte in corso.

        Valido solo entro `snr_ref_freeze_max_min` dal salvataggio: oltre, il metro
        si sarebbe comunque sciolto (stesso tetto del congelamento)."""
        if self._stato_file is None:
            return
        try:
            dati = json.loads(Path(self._stato_file).read_text(encoding="utf-8"))
            eta = self._now() - float(dati["salvato"])
            if not (0.0 <= eta <= self.cfg.snr_ref_freeze_max_min * 60.0):
                return
            # §126-quater — non si applica subito: la memoria descrive UNA stella e
            # vale solo se, alla connessione, PHD2 sta guidando la stessa (vedi
            # conferma_memoria). Senza, il riferimento di un'altra stella, di un
            # altro setup o del simulatore diventava il metro corrente.
            self._memoria_candidata = dict(dati, eta=eta)
            logger.info("[cielo-guida] stato su disco di %.0f s fa: in attesa della stella "
                        "di PHD2 per confermarlo", eta)
        except FileNotFoundError:
            return
        except Exception as e:      # noqa: BLE001 — un file rovinato non deve fermare l'Agente
            logger.warning("[cielo-guida] stato su disco illeggibile (%s): si riparte da zero", e)

    def conferma_memoria(self, posizione: Optional[tuple], soglia_px: float) -> None:
        """§126-quater — chiamata alla fine del saluto di PHD2 (AppState): adotta la
        memoria solo se PHD2 sta guidando la STESSA stella (entro `soglia_px`)."""
        with self._lock:
            dati = self._memoria_candidata
            self._memoria_candidata = None
            if dati is None:
                return
            salvata = dati.get("stella")
            stessa = (posizione is not None and isinstance(salvata, (list, tuple))
                      and len(salvata) == 2
                      and ((posizione[0] - salvata[0]) ** 2 + (posizione[1] - salvata[1]) ** 2) ** 0.5
                      <= soglia_px)
            if not stessa:
                logger.info("[cielo-guida] stato su disco scartato: PHD2 non sta guidando la "
                            "stella che descrive")
                return
            self._applica_memoria(dati)

    def _applica_memoria(self, dati: dict) -> None:
        try:
            ref = dati.get("snr_ref")
            self._snr_ref = float(ref) if ref is not None else None
            self._sky_state = "DEGRADED" if dati.get("sky_state") == "DEGRADED" else "CLEAR"
            for campo in ("sky_state_since", "below_recover_since"):
                v = dati.get(campo)
                setattr(self, "_" + campo, float(v) if v is not None else None)
            self._sereno_confermato = bool(dati.get("sereno_confermato", False))
            self._ref_ereditato = bool(dati.get("ref_ereditato", False))
            v = dati.get("ereditato_dal")
            self._ereditato_dal = float(v) if v is not None else None
            if isinstance(dati.get("stella"), (list, tuple)):
                self._posizione = tuple(dati["stella"])
            logger.info("[cielo-guida] giudizio ripreso dal disco (%.0f s fa, stessa stella): "
                        "riferimento %s, cielo %s", float(dati.get("eta", 0.0)),
                        f"{self._snr_ref:.1f}" if self._snr_ref is not None else "n/d",
                        self._sky_state)
        except Exception as e:      # noqa: BLE001
            logger.warning("[cielo-guida] stato su disco non applicabile (%s): si riparte da zero", e)

    def posizione_stella(self, x: float, y: float) -> None:
        """§126-quater — la posizione della stella in uso, per legarle la memoria."""
        with self._lock:
            self._posizione = (float(x), float(y))

    def _salva_stato(self, now: float, forza: bool = False) -> None:
        """Al massimo una scrittura al minuto (chiamata sotto lock); mai un errore fatale."""
        if self._stato_file is None:
            return
        if not forza and now - self._ultimo_salvataggio < 60.0:
            return
        self._ultimo_salvataggio = now
        try:
            # §126-quater — scrittura atomica (file temporaneo + replace): un'
            # interruzione a meta' non lascia un file troncato.
            dest = Path(self._stato_file)
            tmp = dest.with_name(dest.name + ".tmp")
            tmp.write_text(json.dumps({
                "salvato": now,
                "snr_ref": self._snr_ref,
                "sky_state": self._sky_state,
                "sky_state_since": self._sky_state_since,
                "below_recover_since": self._below_recover_since,
                "sereno_confermato": self._sereno_confermato,
                "ref_ereditato": self._ref_ereditato,
                "ereditato_dal": self._ereditato_dal,
                "stella": list(self._posizione) if self._posizione else None,
            }), encoding="utf-8")
            tmp.replace(dest)
        except Exception as e:      # noqa: BLE001
            if not getattr(self, "_errore_salvataggio", False):
                self._errore_salvataggio = True
                logger.warning("[cielo-guida] salvataggio dello stato fallito (%s): il "
                               "giudizio non sopravvivera' a un riavvio", e)

    def _read_state(self) -> tuple[Optional[str], Optional[float]]:
        try:
            if self._state_provider is not None:
                return self._state_provider()
        except Exception:
            pass
        return (None, None)

    # ------------------------------------------------------------------ #
    #  Telemetria sonde (paletto 8) — thread FastAPI                      #
    # ------------------------------------------------------------------ #

    def observe_probe(self, transparency_after: Optional[dict]) -> None:
        """Chiamata (da server.py, accanto all'ingest N1) quando arriva un light mentre
        l'ultimo contesto era degradato: è la firma di una posa-sonda (o del primo light
        dopo le nubi). Registra trigger presunto ed esito — i numeri per tarare S2."""
        if not self.cfg.enabled:
            return
        with self._lock:
            if self._last_seen_state not in _DEGRADED:
                return   # light di normale imaging: non è una sonda
            after = transparency_after or {}
            record = {
                "ts": self._now(),
                # attribuzione by-construction: se l'hint era attivo, la sonda è stata
                # (o sarebbe stata) anticipata da S2; altrimenti è la cadenza S1.
                "trigger": "hint_S2" if self._active else "timeout_S1",
                "outcome_index": after.get("index"),
                "outcome_state": after.get("state"),
                "hint_active": self._active,
                "snr": self._last_snr,
                "snr_ref": self._snr_ref,
                "accumulator_s": round(self._accumulator_s, 1),
            }
            self._probes.append(record)
            logger.info(
                "[recovery_probe] sonda osservata: trigger=%s -> index=%s state=%s "
                "(hint_active=%s snr=%s ref=%s acc=%.0fs)",
                record["trigger"], record["outcome_index"], record["outcome_state"],
                self._active,
                f"{self._last_snr:.1f}" if self._last_snr is not None else "n/d",
                f"{self._snr_ref:.1f}" if self._snr_ref is not None else "n/d",
                self._accumulator_s,
            )

    # ------------------------------------------------------------------ #
    #  Lettura per /status e dashboard                                    #
    # ------------------------------------------------------------------ #

    def status_block(self) -> dict[str, Any]:
        with self._lock:
            now = self._now()
            return {
                "enabled": self.cfg.enabled,
                "active": self._active,
                "snr": round(self._last_snr, 1) if self._last_snr is not None else None,
                "snr_ref": round(self._snr_ref, 1) if self._snr_ref is not None else None,
                "accumulator_s": round(self._accumulator_s, 1),
                "sustained_target_s": self.cfg.sustained_seconds,
                "since": self._active_since,
                "reason": self._reason,
                "probes": list(self._probes),
                # §76 — evidenza di DEGRADO (polarità opposta). SOLO misura: il
                # plugin la usa per accumulare verso unsafe, mai per drenare.
                "degrading": self._degrading,
                "degrade_s": round(self._degrade_s, 1),
                "degrade_target_s": self.cfg.degrade_sustained_seconds,
                "degrade_since": self._degrading_since,
                "degrade_reason": self._degrade_reason,
                # §126 — il giudizio della guida sul cielo, per il plugin e la
                # dashboard. `sky_ok` e' l'evidenza di sereno sostenuta (stesso
                # valore di `active`, nome che dice cosa significa oggi).
                "sky_state": self._sky_state,
                "sky_state_since": self._sky_state_since,
                "sky_ok": self._active,
                "snr_ref_frozen": self._ref_frozen(now) if self._snr_ref is not None else False,
                "ref_reset_reason": self._ref_reset_reason,
                # §126-bis — riferimento tenuto dalla stella precedente perche' il
                # cambio e' avvenuto a cielo non confermato sereno.
                "ref_ereditato": self._ref_ereditato,
                "sotto_il_sereno": self._below_recover_since is not None,
            }
