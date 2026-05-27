@echo off
cd /d "%~dp0"
echo.
echo  ==========================================
echo   PHD2 Adaptive Agent - RC8
echo   Focale ridotta: 1218mm (riduttore 0.75x)
echo   Pixel scale guida: 0.68 "/px
echo   MODALITA: LIVE (dry_run=false)
echo   exposure_dynamic.enabled: true (path B attivo)
echo  ==========================================
echo.
echo  Apri il browser su: http://localhost:8080
echo.
PHD2_Agent.exe --config config_rc8.toml --with-reducer
pause
