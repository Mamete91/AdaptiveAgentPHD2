@echo off
rem ============================================================
rem  Adaptive Agent for PHD2 — avvio in BACKGROUND (§58)
rem  L'agente NON apre finestre: lavora come processo di sfondo.
rem   - Log live:   Mostra_Log.bat  (si puo' chiudere senza rischi)
rem   - Dashboard:  http://localhost:8080
rem   - Stop pulito: Arresta.bat  (ripristina i parametri PHD2)
rem  Con il plugin NINA (v1.7+) avvio e stop sono automatici.
rem ============================================================
cd /d "%~dp0"
start "" "PHD2_Agent.exe" --config config.toml
