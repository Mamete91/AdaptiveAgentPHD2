@echo off
cd /d "%~dp0"
echo.
echo  ==========================================
echo   PHD2 Adaptive Agent - Tecnosky 115
echo   Focale ridotta: 640mm (riduttore 0.80x)
echo   Pixel scale guida: 1.29 "/px
echo   MODALITA: LIVE (dry_run=false)
echo   exposure_dynamic.enabled: true (path B attivo)
echo  ==========================================
echo.
echo  Apri il browser su: http://localhost:8080
echo.
PHD2_Agent.exe --config config_tecnosky115.toml --with-reducer
pause
