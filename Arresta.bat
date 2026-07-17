@echo off
rem ============================================================
rem  Adaptive Agent for PHD2 — ARRESTO PULITO (§58)
rem  Invia POST /shutdown: l'agente ripristina i parametri PHD2
rem  (baseline) ed esce da solo. MAI chiudere il processo a forza.
rem ============================================================
echo Arresto dell'Adaptive Agent (ripristino parametri PHD2)...
curl -s -X POST http://localhost:8080/shutdown
if errorlevel 1 (
  echo.
  echo L'agente non risponde su localhost:8080 - forse non e' in esecuzione.
)
echo.
pause
