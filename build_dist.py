"""
build_dist.py — Crea un pacchetto di distribuzione ZIP stand-alone
per l'agente e lo strumento diagnostico.
"""
import os
import shutil
import subprocess
from pathlib import Path

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
    
    # 2. Build dell'agente principale (usa il .spec che include scipy hidden imports)
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
    
    # File readme "Come avviare" specifico (flusso a config unico)
    with open(final_output / "LEGGIMI_PER_AVVIARE.txt", "w", encoding="utf-8") as f:
        f.write("=== PHD2 Adaptive Guiding Agent - Config unico ===\n\n")
        f.write("L'agente e' auto-configurante: legge la pixel scale di guida\n")
        f.write("direttamente da PHD2 e deriva da solo le soglie RMS dalla\n")
        f.write("baseline misurata sul campo. Un solo config.toml, un solo Avvia.bat.\n\n")
        f.write("PASSI:\n")
        f.write("1. Apri PHD2 e SELEZIONA IL PROFILO del telescopio che stai usando\n")
        f.write("   (es. 'RC8', 'Askar 71F ridotto'). La focale del profilo determina\n")
        f.write("   la pixel scale che l'agente legge automaticamente.\n")
        f.write("2. In PHD2 vai in Strumenti -> Abilita Server, poi avvia la guida.\n")
        f.write("3. (Opzionale) Esegui 'Diagnostica_Connessione.exe' per il test connessione.\n")
        f.write("4. Esegui 'Avvia.bat' (unico) per avviare l'agente.\n")
        f.write("5. Apri il browser su http://localhost:8080 per la dashboard live.\n")
        f.write("   Nella card 'Auto-calibrazione' vedrai la pixel scale rilevata e\n")
        f.write("   il progresso della baseline (es. 12/60 -> 60/60).\n\n")
        f.write("Per cambiare telescopio basta selezionare un altro profilo in PHD2:\n")
        f.write("pixel scale e soglie si adattano da sole, senza toccare alcun file.\n\n")
        f.write("NOTA: config.toml e' impostato in modalita' LIVE (dry_run=false).\n")
    
    # 5. Zippa il pacchetto
    print("\n>>> Creo lo ZIP finale...")
    shutil.make_archive(str(base_dir / "PHD2_Agent_Distribuzione"), 'zip', final_output)
    
    print("\n[OK] Completato! Il file 'PHD2_Agent_Distribuzione.zip' e' pronto per essere eseguito sul pc.")

if __name__ == "__main__":
    main()
