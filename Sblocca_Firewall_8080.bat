@echo off
title Sblocco Firewall - PHD2 Agent Dashboard
echo.
echo =====================================================
echo    Sblocco Porta Firewall (8080) per PHD2 Agent
echo =====================================================
echo.
echo NOTA BENE:
echo Per eseguire questa operazione con successo, questo script
echo DEVE essere avviato come Amministratore.
echo.
echo (Se ti viene negato l'accesso o compare "Accesso negato",
echo  chiudi tutto, fai clic destro su questo file .bat
echo  e scegli "Esegui come amministratore")
echo.
pause

echo.
echo Aggiunta regola in INGRESSO (TCP 8080) ...
netsh advfirewall firewall add rule name="PHD2 Adaptive Agent Dashboard" dir=in action=allow protocol=TCP localport=8080

echo.
echo Aggiunta regola in USCITA (TCP 8080) ...
netsh advfirewall firewall add rule name="PHD2 Adaptive Agent Dashboard" dir=out action=allow protocol=TCP localport=8080

echo.
echo =====================================================
echo Operazione completata!
echo.
echo Dal tuo tablet, smartphone o da un altro PC di rete
echo puoi ora accedere alla tua Dashboard Web.
echo Ti basta aprire il browser e scivere l'IP di NINA
echo seguito da :8080 (es: http://192.168.1.50:8080)
echo =====================================================
echo.
pause
