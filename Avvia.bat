@echo off
cd /d "%~dp0"
echo  ==========================================
echo   PHD2 Adaptive Agent - Config unico
echo   Pixel scale: AUTO da PHD2 (fallback TOML)
echo   Soglie RMS:  AUTO da baseline misurata
echo   MODALITA: LIVE (dry_run=false)
echo  ==========================================
echo  Seleziona il PROFILO del telescopio in PHD2 prima di avviare.
echo  Apri il browser su: http://localhost:8080
echo.
PHD2_Agent.exe --config config.toml
pause
