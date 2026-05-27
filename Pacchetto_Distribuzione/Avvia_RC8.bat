@echo off
cd /d "%~dp0"
echo.
echo  ==========================================
echo   PHD2 Adaptive Agent - RC8
echo   Focale piena: 1624mm
echo   Pixel scale guida: 0.51 "/px
echo   MODALITA: LIVE (dry_run=false)
echo   exposure_dynamic.enabled: true (path B attivo)
echo  ==========================================
echo.
echo  Apri il browser su: http://localhost:8080
echo.
PHD2_Agent.exe --config config_rc8.toml
pause
