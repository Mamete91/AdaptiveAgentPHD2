"""
ancoraggio.py — §120: la baseline si CALCOLA dal pavimento, non si osserva soltanto.

Il problema che risolve
-----------------------
Fino alla 2.18 la baseline della sessione era un'unica misura: l'RMS che l'Agente
osservava mentre guidava. Da li' uscivano le due soglie (`1.3 x baseline` e
`0.75 x baseline`). Il difetto e' che quella grandezza e' il RISULTATO del lavoro
dell'Agente: se guida male sale, e le soglie salgono con lei — cosi' l'Agente
misura se stesso e conclude che va tutto bene. Un metro che si allunga insieme a
cio' che deve misurare.

Il Guiding Assistant offre l'unica misura che quel cerchio lo rompe: la
dispersione ad anello APERTO (`total_hpf_rms`), filtrata passa-alto a 1 s
(`hp_cutoff = 1.0` in `guiding_assistant.cpp`). Resta solo la parte che la guida
non puo' togliere — il pavimento sotto cui non si scende quella notte. Non
contiene niente di cio' che l'Agente ha fatto, perche' l'Agente in quei minuti
era fermo.

La decomposizione
-----------------
Due sorgenti d'errore indipendenti che si sommano:

    baseline^2  =  pavimento^2  +  contributo_del_rig^2

  * il PAVIMENTO e' una proprieta' della NOTTE. Cambia ogni sera, e il GA lo
    misura ogni sera (dottrina §117).
  * il CONTRIBUTO DEL RIG e' montatura + guida: una proprieta' del SETUP, che da
    una sera all'altra non cambia.

Il secondo non lo dichiara nessuno: l'Agente se lo ricava dalle notti in cui
conosce entrambi gli altri due termini, e lo tiene da parte. Cosi' non c'e'
nessuna costante in secondi d'arco da indovinare per l'utente — che e' il
requisito vero, perche' l'Agente gira su setup che vanno da 0.35"/px a 4"/px.

Perche' NON si prende il minimo
-------------------------------
La prima idea era "il rig e' il minimo delle ultime notti". E' sbagliata, e il
motivo si vede solo pensando ai setup altrui: il GA si esegue a declinazione 0 al
meridiano, cioe' a ~45 gradi di altezza dalle nostre latitudini. Se poi si
riprende allo zenit il seeing e' migliore, e l'RMS guidato puo' finire SOTTO il
pavimento misurato. Non e' un errore: e' geometria. Con la regola del minimo
basterebbe una notte cosi' per incollare la costante a un valore troppo basso e
tenere le soglie strettissime per sempre. Si usa la MEDIANA, e le notti degeneri
(guidato <= pavimento) non producono campione.
"""
from __future__ import annotations

import json
import logging
import math
import statistics
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Sotto questo rapporto guidato/pavimento la notte e' degenere: o il GA descrive
# un cielo diverso da quello in cui stai riprendendo (altezza molto diversa), o la
# misura non e' confrontabile. Non si produce campione.
RAPPORTO_MINIMO = 1.02


def contributo_rig(osservata_arcsec: float,
                   pavimento_arcsec: float) -> Optional[float]:
    """Il contributo di montatura+guida, scorporato dal pavimento della notte.

    `None` quando il conto non e' possibile: guidato al di sotto del pavimento
    (vedi il perche' nel docstring del modulo) oppure ingressi assenti.
    """
    if not osservata_arcsec or not pavimento_arcsec:
        return None
    if osservata_arcsec <= pavimento_arcsec * RAPPORTO_MINIMO:
        return None
    return math.sqrt(osservata_arcsec ** 2 - pavimento_arcsec ** 2)


def baseline_prevista(pavimento_arcsec: float, rig_arcsec: float) -> Optional[float]:
    """La baseline attesa stanotte: il pavimento di stasera con sopra il rig."""
    if not pavimento_arcsec or not rig_arcsec:
        return None
    return math.hypot(pavimento_arcsec, rig_arcsec)


def cap_ancorato(prevista_arcsec: Optional[float], scala_arcsec: float,
                 fattore: float, minimo: float, massimo: float) -> tuple[float, bool]:
    """Il tetto su `rms_high`. Ritorna (valore, ancorato_alla_previsione).

    NB: si ancora alla baseline PREVISTA (pavimento + rig), non al pavimento nudo.
    Ancorarlo al solo pavimento sembrava naturale ed e' sbagliato: quando il rig
    domina il cielo — pavimento 0.26", rig 0.55" — `2 x pavimento` vale 0.52",
    cioe' MENO della baseline prevista di 0.61". Il tetto finirebbe sotto la
    prestazione normale e si ricreerebbe l'allarme permanente dall'altro lato.
    La previsione include entrambi i termini ed e' comunque indipendente da come
    sta andando stanotte — che e' l'unica proprieta' che serve a un backstop.

    §120 — con un pavimento misurato **il tetto assoluto in secondi d'arco sparisce**.

    Perche' andava tolto: la formula precedente era `clamp(fattore x scala, 0.70,
    1.00)`, che sembra proporzionale al setup ma non lo e'. Appena la scala supera
    0.50"/px il prodotto sfonda 1.00" e viene troncato — cioe' per QUALUNQUE setup
    normale il tetto vale 1.00" fisso. Su un cercatore che guida fisicamente a
    1.5" RMS le due soglie finivano entrambe SOTTO la baseline, e quell'utente
    avrebbe avuto l'Agente in allarme permanente, con le leve spinte tutta la
    notte per un cielo che non aveva niente che non andasse.

    L'intenzione dell'1.00" era giusta (il benchmark di "guida pulita", e impedire
    che un cercatore grossolano producesse soglie larghe dannose per l'ottica di
    ripresa). Ma e' un numero ASSOLUTO, e un numero assoluto non puo' essere giusto
    per tutti i setup.

    Lo stesso fattore, ancorato al pavimento invece che alla scala pixel, diventa
    una domanda sensata ovunque — "quanto peggio del possibile e' inaccettabile?"
    invece di "sei sotto un secondo d'arco?". E la continuita' regge: sul rig di
    riferimento (0.51"/px, pavimento 0.51") da' 1.02", cioe' l'1.00" di prima.

    Senza previsione (prima notte con GA, rig non ancora appreso, oppure GA mai
    eseguito) resta la formula di ieri: e' l'unico riparo disponibile, e toglierlo
    lascerebbe una notte con la guida rotta a diventare "normale".
    """
    if prevista_arcsec:
        return fattore * prevista_arcsec, True
    return max(minimo, min(massimo, fattore * scala_arcsec)), False


@dataclass
class StoricoRig:
    """I contributi del rig raccolti notte per notte, per setup.

    Persistente perche' e' una proprieta' del SETUP: buttarla a ogni riavvio
    vorrebbe dire ricominciare a impararla da capo ogni sera, e la prima sera non
    c'e' ancora.
    """
    percorso: Path
    massimo_campioni: int = 5
    dati: dict = field(default_factory=dict)

    def carica(self) -> "StoricoRig":
        try:
            if self.percorso.exists():
                self.dati = json.loads(self.percorso.read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            logger.warning("[ancoraggio] storico rig illeggibile (%s): riparto vuoto", e)
            self.dati = {}
        return self

    def _salva(self) -> None:
        try:
            self.percorso.write_text(json.dumps(self.dati, indent=2), encoding="utf-8")
        except OSError as e:
            logger.warning("[ancoraggio] storico rig non salvato: %s", e)

    def valore(self, setup_id: str) -> Optional[float]:
        """La mediana dei campioni di questo setup. `None` se non ce n'e' ancora."""
        campioni = self.dati.get(str(setup_id), [])
        if not campioni:
            return None
        return statistics.median(campioni)

    def aggiungi(self, setup_id: str, rig_arcsec: float) -> float:
        """Registra un campione e ritorna la mediana aggiornata."""
        chiave = str(setup_id)
        campioni = list(self.dati.get(chiave, []))
        campioni.append(round(rig_arcsec, 4))
        # Si tengono gli ULTIMI N: il rig migliora quando la taratura migliora, e
        # una coda infinita terrebbe in vita per sempre i valori delle notti mal
        # tarate di mesi fa.
        self.dati[chiave] = campioni[-self.massimo_campioni:]
        self._salva()
        return statistics.median(self.dati[chiave])

    def campioni(self, setup_id: str) -> list[float]:
        return list(self.dati.get(str(setup_id), []))
