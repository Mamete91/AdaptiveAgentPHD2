@echo off
REM ============================================================
REM  Build v2.5 = 32 RECOVERY (banda morta) + 33 baseline-sempre
REM  Esegui SU QUESTO PC Windows, dentro la cartella AdaptiveAgentPHD2
REM  (quella con .venv e build_dist.py).
REM  Produce: Pacchetto_Distribuzione\ + uno ZIP con NOME UNIVOCO + data.
REM ============================================================
cd /d "%~dp0"

echo.
echo === [1/4] Attivo l'ambiente virtuale (.venv) ===
call ".venv\Scripts\activate.bat"
if errorlevel 1 (
  echo [ERRORE] Non trovo .venv\Scripts\activate.bat
  echo Lancia questo file DENTRO la cartella AdaptiveAgentPHD2.
  pause
  exit /b 1
)

echo.
echo === [2/4] Verifico PyInstaller (dipendenza solo-build) ===
pip install pyinstaller==6.20.0 1>nul 2>nul

echo.
echo === [3/4] Pulizia cache build (build\ e dist\) per evitare exe stantii ===
if exist "build" rmdir /s /q "build"
if exist "dist"  rmdir /s /q "dist"
echo  cache rimossa: PyInstaller ricompila dal sorgente attuale (con 32 + 33).

echo.
echo === [3/4] Eseguo build_dist.py (qualche minuto) ===
python build_dist.py
if errorlevel 1 (
  echo [ERRORE] Build fallita. Leggi i messaggi qui sopra.
  pause
  exit /b 1
)

echo.
echo === [4/4] Copio lo ZIP con nome univoco + data/ora ===
for /f %%i in ('powershell -NoProfile -Command "Get-Date -Format yyyyMMdd_HHmm"') do set TS=%%i
set SRC=Adaptive_Agent_PHD2_v2.5.zip
set DST=Adaptive_Agent_PHD2_v2.5_RECOVERY+BASELINE_%TS%.zip
if exist "%SRC%" (
  copy /Y "%SRC%" "%DST%" 1>nul
  echo  ZIP univoco creato: %DST%
) else (
  echo [ATTENZIONE] Non trovo %SRC% - controlla l'output della build qui sopra.
)

echo.
echo ============================================================
echo  FATTO. In questa cartella ora trovi:
echo    - Pacchetto_Distribuzione\                    (cartella pronta)
echo    - %DST%
echo      ^(ZIP con nome univoco, da copiare su Minix100^)
echo.
echo  Attive di default nel config.toml del pacchetto:
echo    - 32 minmove_recovery_enabled = true   (RECOVERY banda morta)
echo    - 33 baseline_always_form     = true   (baseline sempre)
echo  Field-test in modalita' GUARDIAN (in jitter il RECOVERY non agisce).
echo  Per tornare al comportamento precedente: metti quei due a false.
echo.
echo  Su Minix100 estrai lo ZIP in una cartella NUOVA, senza sovrascrivere
echo  la v2.4 / v2.5-vecchia: tienile come fallback.
echo ============================================================
pause
