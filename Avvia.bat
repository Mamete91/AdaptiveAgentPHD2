@echo off
cd /d "%~dp0"
echo ============================================================
echo  Adaptive Agent for PHD2 v2.2
echo  by Alessandro Curci
echo  Copyright (c) 2026 Alessandro Curci
echo  Community Telegram: https://t.me/+eewRNpvElSs5OWY8
echo ============================================================
echo.
echo Avvio agente. Profilo attivo deciso dentro PHD2.
echo Dashboard: http://localhost:8080
echo.
PHD2_Agent.exe --config config.toml
pause
