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
    
    # Copia config.toml
    shutil.copy("config.toml", final_output / "config.toml")
    if Path("config_askar71f.toml").exists():
        shutil.copy("config_askar71f.toml", final_output / "config_askar71f.toml")
    if Path("config_rc8.toml").exists():
        shutil.copy("config_rc8.toml", final_output / "config_rc8.toml")
    if Path("config_tecnosky115.toml").exists():
        shutil.copy("config_tecnosky115.toml", final_output / "config_tecnosky115.toml")
        
    # Copia file .bat (focale piena + riduttore)
    bat_files = [
        "Avvia_Askar71F.bat",
        "Avvia_Askar71F_Ridotto.bat",
        "Avvia_RC8.bat",
        "Avvia_RC8_Ridotto.bat",
        "Avvia_Tecnosky115.bat",
        "Avvia_Tecnosky115_Ridotto.bat",
        "Sblocca_Firewall_8080.bat",
    ]
    for bat_file in bat_files:
        if Path(bat_file).exists():
            shutil.copy(bat_file, final_output / bat_file)
    
    # Copia la dashboard
    shutil.copytree("dashboard", final_output / "dashboard")
    
    # Crea una cartella per i logs offline
    (final_output / "phd2_log").mkdir(exist_ok=True)
    
    # File readme "Come avviare" specifico
    with open(final_output / "LEGGIMI_PER_AVVIARE.txt", "w", encoding="utf-8") as f:
        f.write("=== PHD2 Adaptive Guiding Agent ===\n\n")
        f.write("1. ASSICURATI DI AVER APERTO PHD2\n")
        f.write("2. IN PHD2 vai in Strumenti -> Abilita Server\n")
        f.write("3. (Opzionale) Esegui 'Diagnostica_Connessione.exe' per vedere le tre Luci Verdi di test.\n")
        f.write("4. Per avviare il tool, esegui 'PHD2_Agent.exe'.\n")
        f.write("5. Dal browser vai all'indirizzo http://localhost:8080 per vedere la dashboard live.\n\n")
        f.write("Puoi personalizzare i limiti aprendo il file config.toml con Notepad.\n")
        f.write("NOTA: Attualmente dal config.toml è impostata la modalità DRY_RUN (solo simulazione).\n")
    
    # 5. Zippa il pacchetto
    print("\n>>> Creo lo ZIP finale...")
    shutil.make_archive(str(base_dir / "PHD2_Agent_Distribuzione"), 'zip', final_output)
    
    print("\n[OK] Completato! Il file 'PHD2_Agent_Distribuzione.zip' e' pronto per essere eseguito sul pc.")

if __name__ == "__main__":
    main()
