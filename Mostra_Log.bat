@echo off
rem ============================================================
rem  Adaptive Agent for PHD2 — LOG LIVE (§58)
rem  Finestra di sola lettura su logs\agent.log: CHIUDERLA E'
rem  SEMPRE SICURO (l'agente continua a lavorare in background).
rem ============================================================
cd /d "%~dp0"
title Adaptive Agent - log live (chiudere e' sicuro)
powershell -NoProfile -Command "Get-Content -Path 'logs\agent.log' -Tail 50 -Wait"
