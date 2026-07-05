# Metodologia di validazione — LIVE sul cielo reale (regola di progetto)

**Stabilita da Alessandro, 2026-06-19.** Vale per tutte le logiche che influenzano il **motore decisionale** dell'Adaptive Agent (Guardian/Jitter, fusione NINA N1/N8 e successive).

## La regola
La validazione di una nuova logica avviene **principalmente osservando il comportamento del sistema in diretta durante l'acquisizione reale**, non tramite una fase preliminare limitata alla sola analisi dei log a posteriori. Si **abbandona** il modello "osservativo-su-log → shadow → operativo".

Motivo: con Guardian/Jitter non si dimostra più che il motore funziona "in laboratorio"; si verifica se **interpreta correttamente la realtà osservativa**. Il legame tra evento reale (arrivano velature → calano le stelle → la trasparenza degrada) e decisione del motore (attribuisce il degrado alle nubi, non al seeing) è verificabile **solo in tempo reale**; nei log quel legame si perde o si ricostruisce a fatica.

**NINA non è una nuova fonte di rischio, è un secondo "occhio".** PHD2 = come si muove la stella di guida; NINA = come stanno venendo le immagini. Informazione **indipendente che contestualizza**, non sostituisce.

## Le 5 condizioni obbligatorie (ciò che rende sicuro "operativo da subito")
Una feature che influenza il motore si rilascia **direttamente operativa** SE e SOLO SE:
1. **Visibilità in tempo reale** — ogni decisione è mostrata in diretta sulla dashboard.
2. **Tracciamento dei segnali** — si vede in live **quali segnali PHD2** (RMS/jitter/lag-1) **e quali segnali NINA** (conteggio stelle/trasparenza/SNR/fondo) hanno contribuito alla decisione (pannello evidence del motore + marcatori sul grafico di guida).
3. **Verificabilità sul campo** — l'utente può confermare a vista che la decisione corrisponde a ciò che osserva nel cielo.
4. **Reversibilità immediata** — switch OFF/GUARDIAN/JITTER + kill-switch per-feature sempre presenti.
5. **Ampiezza limitata** — le azioni restano GUARDIAN-piccole e fail-safe (nel dubbio → nessuna azione), così una decisione sbagliata è innocua e si coglie in diretta.

## Cosa resta invariato
- Ogni funzione resta **completamente tracciata e reversibile**.
- La regola "≥3-4 sessioni / più setup" resta valida, ma sono **sessioni LIVE operative** con lo sviluppatore che osserva, non una fase log-only.
- **Una sola modifica al motore per volta** (così l'attribuzione live è pulita): consolidare §43/§44 (baseline bidirezionale) in una sessione prima di attivare N8.
