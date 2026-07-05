# Accertamento — Path B (esposizione dinamica) deve ri-determinare la stella di guida

**Stato:** accertamento di campo confermato sul codice (Alessandro, 2026-06-13). Legato a **P1**.

## L'accertamento

Quando scatta **Path B** dell'escalation gate (leve sature → aumento esposizione, es. 1s → 2s), la stella che PHD2 aveva auto-selezionato per 1s **satura** a 2s: picco tagliato (flat-top), centroide impreciso → la guida **peggiora** proprio mentre Path B la voleva migliorare. Serve **ri-determinare la stella di guida** appropriata alla nuova esposizione (tipicamente una più debole, non satura).

## Conferma sul codice

- L'aumento esposizione (`_apply_exposure`, chiamato dal Path B dell'escalation gate) cambia l'esposizione e resetta analyzer/motore, ma **NON ri-seleziona la stella**.
- La saturazione è gestita **solo in modo reattivo**: l'AI Star Finder controlla `is_saturated` (controller.py ~L1921) e avvia un **timer 300s** (`emergency.saturation_timeout_s`); `_evaluate_saturation_timer` (~L1843) forza un re-scan `find_star()` **solo dopo 300s**. E il timer parte solo dal percorso star-finder, **non** è agganciato a Path B.
- → Dopo Path B: ~**5 minuti** di guida su stella satura prima di un eventuale re-scan. Buco reale.

## Perché è un problema P1

Path B (esposizione più lunga) è uno **strumento** per migliorare la prestazione (mediare il seeing). Se satura la stella, **peggiora** la prestazione (centroide in bias) → contraddice P1. Quindi l'azione di Path B va **validata dal suo effetto**, e l'Agente deve **adattarsi** (ri-selezionare la stella) perché l'esposizione più lunga sia davvero benefica.

## Il fix proposto

Agganciare una **ri-valutazione della stella** all'aumento esposizione di Path B:
1. Dopo che il cambio esposizione ha effetto (attendere 1-2 frame di settle), **controllare se la stella corrente satura** alla nuova esposizione (peak ADU vicino al fondo scala, oppure `is_saturated` su un'immagine fresca).
2. Se satura → **ri-selezionare** (find_star / find_best_star) una stella **non satura e ben esposta** alla nuova esposizione. **Proattivo**, senza aspettare il timer 300s.

## Cautele (oneste)

- **Condizionale, non sempre:** ri-selezionare solo se la stella satura davvero (la ri-selezione disturba: breve re-acquisizione/settle). Non re-find a ogni cambio esposizione.
- **Trade-off SNR:** una stella più debole evita la saturazione ma ha meno SNR → il finder deve scegliere la **migliore non satura** (saturazione vs SNR sufficiente).
- **Settle:** la verifica saturazione va fatta DOPO che il nuovo tempo è attivo (un paio di frame), non istantaneamente.
- **Anti-flapping:** quando Path B **torna** all'esposizione base, la stella debole ri-selezionata può tornare troppo debole → gestire il ritorno (ri-selezione o ripristino) senza oscillare su/giù.
- **Riusare il meccanismo esistente:** c'è già `find_best_star` + il check `is_saturated` + il timer; il fix è **anticipare** quel controllo al momento di Path B, non costruirlo da zero. Si può accorciare il "buco" da 300s a pochi secondi.

## Priorità

Media-alta: è una correzione che rende Path B **effettivamente utile** invece che controproducente nelle notti di seeing dove scatta. Da fare come prompt per Code.
