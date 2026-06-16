@echo off
REM ============================================================
REM  Build del Pacchetto_Distribuzione v2.4 - one click
REM  Esegui questo file (doppio clic) SU QUESTO PC,
REM  dentro la cartella AdaptiveAgentPHD2 (dove c'e' .venv).
REM  Produce:
REM    - Pacchetto_Distribuzione\          (cartella pronta)
REM    - Adaptive_Agent_PHD2_v2.4.zip      (da copiare su Minix100)
REM ============================================================
cd /d "%~dp0"

echo.
echo === [1/3] Attivo l'ambiente virtuale (.venv) ===
call ".venv\Scripts\activate.bat"
if errorlevel 1 (
  echo [ERRORE] Non trovo .venv\Scripts\activate.bat in questa cartella.
  echo Metti/lancia questo .bat dentro la cartella AdaptiveAgentPHD2.
  pause
  exit /b 1
)

echo.
echo === [2/3] Installo PyInstaller (dipendenza solo-build, manca nel venv) ===
pip install pyinstaller==6.20.0
if errorlevel 1 (
  echo [ERRORE] Installazione PyInstaller fallita. Controlla la connessione internet.
  pause
  exit /b 1
)

echo.
echo === [3/3] Eseguo build_dist.py ===
python build_dist.py
if errorlevel 1 (
  echo [ERRORE] La build e' fallita. Leggi i messaggi qui sopra.
  pause
  exit /b 1
)

echo.
echo ============================================================
echo  FATTO. In questa cartella trovi ora:
echo    - Pacchetto_Distribuzione\        (cartella pronta all'uso)
echo    - Adaptive_Agent_PHD2_v2.4.zip    (da copiare su Minix100)
echo.
echo  Su Minix100 estrai lo ZIP in una cartella NUOVA, SENZA
echo  sovrascrivere la 2.3 (cosi la 2.3 resta come fallback).
echo ============================================================
pause
