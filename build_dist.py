"""
build_dist.py — Crea un pacchetto di distribuzione ZIP stand-alone
per l'agente e lo strumento diagnostico.
"""
import os
import shutil
import subprocess
from pathlib import Path

from phd2_agent.__about__ import (
    __project_name__, __short_name__, __version__,
    __author__, __copyright__, __contact_telegram__,
)
from version_info_template import write_version_info


def run_cmd(cmd):
    print(f"Eseguo: {' '.join(cmd)}")
    subprocess.run(cmd, check=True)

def main():
    base_dir = Path(os.getcwd())
    dist_dir = base_dir / "dist" / "PHD2_AdaptiveAgent"

    # 1. Pulisci la build folder
    if dist_dir.exists():
        shutil.rmtree(dist_dir)
    dist_dir.mkdir(parents=True, exist_ok=True)

    # 2. Genera version_info.txt da phd2_agent/__about__.py (§26: metadata
    # Windows dell'.exe — versione letta da __about__.py by Alessandro Curci).
    print("\n>>> Genero version_info.txt da __about__.py...")
    write_version_info("version_info.txt")

    # 3. Build dell'agente principale (usa il .spec che include scipy hidden imports)
    print("\n>>> Costruisco PHD2_Agent.exe (da PHD2_Agent.spec)...")
    run_cmd(["pyinstaller", "--noconfirm", "PHD2_Agent.spec"])
    
    # Rinomina la directory output di pyinstaller a "PHD2_AdaptiveAgent"
    pyinst_out = base_dir / "dist" / "PHD2_Agent"
    
    # 3. Build del diagnostico (eseguibile singolo indipendente dentro la cartella del main)
    print("\n>>> Costruisco diagnostic.exe...")
    run_cmd([
        "pyinstaller",
        "--noconfirm",
        "--onefile",
        "--name", "Diagnostica_Connessione",
        "diagnostic.py"
    ])
    
    # 4. Sposta i file nella cartella finale
    print("\n>>> Assemblo il pacchetto...")
    final_output = base_dir / "Pacchetto_Distribuzione"
    if final_output.exists():
        shutil.rmtree(final_output)
    
    # Rinomina την cartella PHD2_Agent creata al passo 2
    shutil.copytree(pyinst_out, final_output)
    
    # Sposta l'exe diagnostico dentro quella cartella
    diag_exe = base_dir / "dist" / "Diagnostica_Connessione.exe"
    if diag_exe.exists():
        shutil.copy(diag_exe, final_output / "Diagnostica_Connessione.exe")
    
    # Copia config unico
    shutil.copy("config.toml", final_output / "config.toml")

    # Copia file .bat (config unico: un solo Avvia.bat + sblocco firewall)
    bat_files = [
        "Avvia.bat",
        "Sblocca_Firewall_8080.bat",
    ]
    for bat_file in bat_files:
        if Path(bat_file).exists():
            shutil.copy(bat_file, final_output / bat_file)
    
    # Copia la dashboard
    shutil.copytree("dashboard", final_output / "dashboard")
    
    # Crea una cartella per i logs offline
    (final_output / "phd2_log").mkdir(exist_ok=True)
    
    # File readme "Come avviare" - copertina branded §26 + nota plugin NINA §27
    leggimi_text = f"""\
============================================================
 {__project_name__} v{__version__}
 by {__author__}
 Copyright (c) 2026 Alessandro Curci
 Community Telegram: {__contact_telegram__}
============================================================

L'agente e' auto-configurante: legge la pixel scale di guida
direttamente da PHD2 e deriva da solo le soglie RMS dalla
baseline misurata sul campo. Un solo config.toml, un solo Avvia.bat.

PASSI:
1. Apri PHD2 e SELEZIONA IL PROFILO del telescopio che stai usando
   (es. 'RC8', 'Askar 71F ridotto'). La focale del profilo determina
   la pixel scale che l'agente legge automaticamente.
2. In PHD2 vai in Strumenti -> Abilita Server, poi avvia la guida.
3. (Opzionale) Esegui 'Diagnostica_Connessione.exe' per il test connessione.
4. Esegui 'Avvia.bat' (unico) per avviare l'agente.
5. Apri la dashboard live (DUE MODI - scegli quello che preferisci):
   a) Browser web: http://localhost:8080 (sempre disponibile, anche da
      tablet/secondo monitor/PC remoto sulla stessa rete).
   b) Plugin NINA opzionale: se hai installato (*) il plugin "Adaptive
      Agent for PHD2 - Dashboard" dentro NINA, la dashboard appare gia'
      dentro il pannello dockable di NINA - non serve aprire il browser.
   Nella card 'Auto-calibrazione' vedrai la pixel scale rilevata e
   il progresso della baseline (es. 12/60 -> 60/60).

SEQUENZA TIPICA SE USI ANCHE IL PLUGIN NINA:
   PHD2 -> Avvia.bat -> NINA. Il pannello NINA carica la dashboard
   automaticamente. Se NINA era gia' aperto prima dell'agente, basta
   premere 'Riprova' nel pannello dopo aver lanciato Avvia.bat.

Per cambiare telescopio basta selezionare un altro profilo in PHD2:
pixel scale e soglie si adattano da sole, senza toccare alcun file.

NOVITA' v2.3 (Satisfaction gate sulla mediana baseline):
Quando la guida e' gia' al livello del cielo migliore misurato dall'Agente
(mediana della baseline auto-calibrata), l'Agente smette automaticamente di
"indurire" le leve Aggressivita' e MinMove verso la reattivita' estrema.
Risultato: meno guida nervosa in cielo buono, RMS piu' stabile. Se le
condizioni peggiorano, l'Agente riprende automaticamente ad agire come prima.
Disattivabile in config.toml con [lever_optimization] enabled = false (torna
al comportamento v2.2).

NOVITA' v2.4 (Seeing Diagnostic Engine - sperimentale, SPENTO di default):
L'Agente puo' ora distinguere la CAUSA del degrado della guida - turbolenza
atmosferica (seeing), sovra-correzione del loop, oppure deriva sistematica -
combinando jitter frame-to-frame, autocorrelazione e HFD, non solo l'RMS.
DI FABBRICA E' SPENTO: il comportamento resta IDENTICO alla v2.3. Sulla
dashboard trovi la card "Seeing Diagnostic Engine" con la diagnosi in tempo
reale (etichetta colorata + fattori). Per provarlo, imposta in config.toml
[diagnostic_engine] enabled = true (modalita' "guardian": la logica v2.3
continua a guidare, il motore ne corregge solo le mosse sbagliate ed e'
fail-safe). Le soglie sono ancora provvisorie: feedback benvenuto sul gruppo.

NOVITA' v2.5 (Recupero MinMove nella banda morta - ATTIVO di default):
Prima, una volta sceso al minimo su cielo buono, il MinMove si "congelava"
e non risaliva piu' quando il cielo peggiorava (vento), a meno di un degrado
molto forte. Ora, quando l'RMS resta sopra la mediana del cielo migliore
misurato (baseline) ma non abbastanza da scattare il caso "seeing degradato",
l'Agente RIALZA gradualmente il MinMove verso una guida piu' morbida, e si
ferma da solo quando l'RMS rientra o quando ammorbidire non aiuta piu'. Il
valore minimo di MinMove resta invariato. E' la correzione di un comportamento
storico, quindi e' ATTIVA di default in modalita' OFF e GUARDIAN (in JITTER
no). Disattivabile in config.toml con [lever_optimization]
minmove_recovery_enabled = false (torna al comportamento v2.4).

NOVITA' v2.6 (Motore di diagnosi del seeing finalmente OPERATIVO):
Il motore che distingue la causa del degrado (turbolenza/sovra-correzione/
deriva) passa da "dormiente" a operativo, e parte gia' attivo in modalita'
GUARDIAN. Quattro miglioramenti:
 - l'HFD della camera di guida (cieco al seeing) non blocca piu' la diagnosi
   SEEING, che ora si basa sui segnali dinamici reali (jitter + RMS);
 - il "riferimento di calma" del jitter si forma sempre e presto (dalla
   miglior prestazione recente), non solo nei rari attimi di cielo perfetto;
 - quel riferimento SOPRAVVIVE al dithering (un dither sposta la stella, non
   l'atmosfera): niente piu' azzeramenti continui;
 - la baseline RMS si forma anche con stelle deboli (SNR basso), non solo a
   stella brillante.
Risultato: l'Agente ora "vede" davvero il seeing e misura nella giusta unita'
(arcsec). Tutto attivo di fabbrica; nulla da configurare.

FEEDBACK / SEGNALAZIONI:
  Community Telegram: {__contact_telegram__}

NOTA: config.toml e' impostato in modalita' LIVE (dry_run=false).

============================================================
 (*) COME INSTALLARE IL PLUGIN NINA (opzionale, semplicissimo)
============================================================

Il plugin "Adaptive Agent for PHD2 - Dashboard" e' una semplice
cartella che va copiata dentro la cartella plugin di NINA. Non
servono installer, non servono permessi di amministratore.

PASSI:

1. Chiudi NINA se e' aperto.

2. Apri Esplora Risorse di Windows e nella barra in alto incolla
   questo indirizzo, poi premi Invio:

      %LOCALAPPDATA%\\NINA\\Plugins\\3.0.0

   Si aprira' la cartella plugin di NINA (il path completo e'
   C:\\Users\\<TuoNomeUtente>\\AppData\\Local\\NINA\\Plugins\\3.0.0\\).

3. Copia dentro quella cartella la cartella
   "AdaptiveAgentForPHD2.NinaPlugin" che hai ricevuto.

   Risultato finale (esempio):
      C:\\Users\\Mario\\AppData\\Local\\NINA\\Plugins\\3.0.0\\
         AdaptiveAgentForPHD2.NinaPlugin\\
            AdaptiveAgentForPHD2.NinaPlugin.dll
            (eventuali altri file)

4. Riavvia NINA. Il pannello "Adaptive Agent for PHD2" comparira'
   tra i pannelli dockable di NINA: aprilo e trascinalo dove
   preferisci nel layout.

REQUISITI:
- NINA versione 3.x (testato su 3.3).
- Microsoft Edge WebView2 Runtime installato (su Windows 11 c'e'
  gia', su Windows 10 aggiornato di solito anche; se vedi schermo
  bianco scaricalo dal sito Microsoft e riavvia NINA).

PER DISINSTALLARLO: chiudi NINA, cancella la cartella
"AdaptiveAgentForPHD2.NinaPlugin" dal path qui sopra, riavvia NINA.
Nessuna traccia residua nel sistema.

NOVITA' v1.1 (Launch Agent + badge stato):
Il plugin v1.1 aggiunge sopra la dashboard:
 - un badge "Agente online vX.Y" (verde) / "Agente offline" (grigio)
   che si aggiorna ogni 15 secondi;
 - un pulsante "Avvia Adaptive Agent" che lancia Avvia.bat con un
   click senza dover aprire Esplora Risorse.
Per usare il pulsante, vai in Options -> Plugins -> Adaptive Agent
for PHD2 - Dashboard, e nelle settings imposta una sola volta il
percorso del file Avvia.bat (es. clicca "Sfoglia..." e selezionalo).
Quando l'Agente e' gia' online il pulsante e' disabilitato (no-op),
quando e' offline e il path e' configurato e' attivo. Non serve per
usare il plugin: la dashboard funziona comunque, e' solo comodita'.

NOVITA' v1.2 (Safety Monitor virtuale opzionale):
Il plugin v1.2 espone anche un Safety Monitor virtuale che NINA puo'
usare come driver di sicurezza. Si attiva in NINA andando in Equipment
-> Safety Monitor, selezionando dalla tendina (sotto categoria N.I.N.A.)
"Adaptive Agent for PHD2 - Guide Safety" e cliccando Connect. Il driver
segnala unsafe quando la guida resta in STAR_LOST oltre 5 minuti (valore
configurabile nelle impostazioni del plugin). Le reazioni concrete
(pausa sequenza, parking, ecc.) si configurano dentro NINA in
Options -> Safety o nell'Advanced Sequencer. Per uso domestico la
configurazione consigliata e' "Pause on unsafe" + "Resume on safe".
La funzione e' opzionale: chi non la usa non e' impattato.

NOTA: il plugin e' opzionale. La dashboard via browser su
http://localhost:8080 funziona sempre, anche senza plugin.
"""
    with open(final_output / "LEGGIMI_PER_AVVIARE.txt", "w", encoding="utf-8") as f:
        f.write(leggimi_text)

    # 5. Zippa il pacchetto con nome brandizzato §26: Adaptive_Agent_PHD2_v<version>.zip
    print("\n>>> Creo lo ZIP finale...")
    zip_basename = f"Adaptive_Agent_PHD2_v{__version__}"
    shutil.make_archive(str(base_dir / zip_basename), 'zip', final_output)

    print(f"\n[OK] Completato! Il file '{zip_basename}.zip' e' pronto per essere eseguito sul pc.")

if __name__ == "__main__":
    main()
