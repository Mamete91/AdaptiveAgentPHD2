"""
shadow_refs.py — §94: ANCORE DI SESSIONE, in sola osservazione.

Nato dalla notte 13-14/8 (Abell 61, RC8+CEM70). Notte serena e riuscita — 23
pose su 23, zero stelle perse — ma con un degrado lento e continuo documentato
da cinque strumenti indipendenti: RMS 0.634"->0.772", jitter +12%, N1
1.00->0.82, SNR di guida 66->48, FWHM delle light 4.35->4.75.

Il motore diagnostico ha visto SEEING nel 2.9% dei frame, e alle 03:00 — con
tutto al peggio — una volta sola. Il motivo, misurato: il RIFERIMENTO del
jitter e' cresciuto del 17.5% mentre il jitter cresceva del 12%. Il metro
saliva piu' in fretta di cio' che doveva giudicare, quindi il rapporto restava
piatto (1.27 -> 1.17 -> 1.14 -> 1.12 -> 1.22) e non superava mai la soglia.
Lo stesso e' accaduto alla soglia RMS (0.763" -> 0.875"), ed e' quello che ha
autorizzato 135 recuperi verso i valori standard MENTRE il cielo peggiorava:
relativamente a un metro che si allarga, una guida che peggiora sembra stabile.

Il cricchetto §66/§76-bis NON cura questo. Verificato col replay: a emivita 25
minuti e cadenza 3 s, dopo 4 ore il riferimento ha colmato il 99.9% del
divario. Quel cricchetto e' nato per il crollo del 4/8 (SNR 70->22 in quattro
minuti) e li' funziona; qui la malattia e' piu' lenta della medicina.

Il punto generale, che vale oltre questo caso: UN RIFERIMENTO CHE SI ADEGUA E'
CIECO A CIO' CHE E' PIU' LENTO DI LUI. Tarare l'emivita non risolve, sposta
soltanto il punto cieco. Servono due riferimenti che rispondono a due domande
diverse — esattamente la separazione del §79, un livello piu' in basso:

    riferimento adattivo (§38)  ->  "e' peggio degli ultimi minuti?"
    ancora di sessione (qui)    ->  "e' peggio di come e' stata stanotte al meglio?"

QUESTO MODULO NON DECIDE NULLA. Le sue uscite finiscono solo nel CSV, accanto
ai riferimenti veri, perche' dopo qualche notte si possa dire con i dati quale
dei due descrive meglio il degrado reale — e non per preferenza architetturale.
E' la disciplina del §47 (misura in ombra prima di promuovere un ramo).
"""
from __future__ import annotations

from typing import Optional

# Adozione del miglioramento: stessa costante del cricchetto §76-bis. A cadenza
# di guida (~3 s) servono ~20 frame perche' l'ancora si muova in modo
# apprezzabile, quindi un singolo istante fortunato non la trascina in basso.
_ALPHA = 0.05


class ShadowRefs:
    """Ancore di sessione per jitter e RMS. Scendono sul calmo, non risalgono mai.

    Asimmetria deliberata e opposta a quella del §66: li' il riferimento era una
    SNR (piu' alta = meglio) e si difendeva dai cali; qui sono jitter e RMS
    (piu' bassi = meglio) e ci si difende dalle salite. La regola pero' e' la
    stessa: il miglioramento e' sempre informazione vera e si adotta subito, il
    peggioramento non deve poter riscrivere il metro con cui lo si misura.

    Perche' non risalgono MAI, invece di risalire lentamente: il degrado da
    massa d'aria dura tutta la notte: qualunque emivita finita verrebbe colmata.
    Il prezzo e' che una notte iniziata eccezionalmente calma legge tutto il
    resto come peggiorato — ed e' proprio uno dei difetti che l'osservazione in
    ombra deve far emergere prima di promuovere il meccanismo.

    Sopravvive di proposito alle ripartenze della guida: la notte 13-14/8 ne ha
    avute UNDICI (PHD2 ferma e riparte a ogni ripresa della sequenza) e
    un'ancora azzerata a ogni ri-aggancio non misurerebbe nulla. L'atmosfera non
    si azzera perche' PHD2 si e' riagganciato.
    """

    __slots__ = ("_jitter", "_rms", "_n")

    def __init__(self) -> None:
        self._jitter: Optional[float] = None
        self._rms: Optional[float] = None
        self._n: int = 0

    # ------------------------------------------------------------------ #

    def update(self, jitter: Optional[float], rms: Optional[float]) -> None:
        """Alimenta le ancore con un frame. Valori assenti o non positivi si
        ignorano: un'ancora sporcata da uno zero non e' piu' un riferimento."""
        self._jitter = self._pull_down(self._jitter, jitter)
        self._rms = self._pull_down(self._rms, rms)
        if jitter or rms:
            self._n += 1

    @staticmethod
    def _pull_down(anchor: Optional[float], value: Optional[float]) -> Optional[float]:
        if value is None or value <= 0:
            return anchor
        if anchor is None:
            return float(value)
        if value < anchor:
            # Miglioramento: si adotta subito, come nel §66.
            return (1.0 - _ALPHA) * anchor + _ALPHA * float(value)
        # Peggioramento: l'ancora non si muove. E' tutto qui il meccanismo.
        return anchor

    # ------------------------------------------------------------------ #

    @property
    def jitter_anchor(self) -> Optional[float]:
        return self._jitter

    @property
    def rms_anchor(self) -> Optional[float]:
        return self._rms

    @property
    def frames(self) -> int:
        return self._n

    def status_block(self) -> dict:
        """Solo per /status e diagnostica. Nessun consumatore decisionale."""
        return {
            "jitter_anchor": round(self._jitter, 4) if self._jitter is not None else None,
            "rms_anchor": round(self._rms, 4) if self._rms is not None else None,
            "frames": self._n,
        }
