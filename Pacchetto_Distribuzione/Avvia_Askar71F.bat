@echo off
cd /d "%~dp0"
echo.
echo  ==========================================
echo   PHD2 Adaptive Agent - Askar 71F
echo   Focale piena: 490mm
echo   Pixel scale guida: 1.58 "/px
echo   MODALITA: LIVE (dry_run=false)
echo   exposure_dynamic.enabled: true (path B attivo)
echo  ==========================================
echo.
echo  Apri il browser su: http://localhost:8080
echo.
PHD2_Agent.exe --config config_askar71f.toml
pause
