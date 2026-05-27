"""
diagnostic.py — Strumento di diagnostica della connessione a PHD2.
Esegue un check dei tre semafori verdi richiesti.
"""
import time
import socket
import json

class Colors:
    GREEN = '\033[92m'
    RED = '\033[91m'
    YELLOW = '\033[93m'
    RESET = '\033[0m'
    BOLD = '\033[1m'

def print_step(msg):
    print(f"\n{Colors.BOLD}--- {msg} ---{Colors.RESET}")

def print_result(success, label, info=""):
    if success:
        print(f" {Colors.GREEN}🟢 LUCE VERDE{Colors.RESET} | {label} {info}")
    else:
        print(f" {Colors.RED}🔴 LUCE ROSSA{Colors.RESET} | {label} {info}")

def manual_rpc(host, port, method, params=None):
    if params is None:
        params = []
    
    req = {
        "method": method,
        "params": params,
        "id": 1,
        "jsonrpc": "2.0"
    }
    
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(3.0)
    try:
        s.connect((host, port))
        s.sendall((json.dumps(req) + "\r\n").encode("utf-8"))
        
        # Leggi finchè non otteniamo la risposta col nostro id=1
        while True:
            chunk = s.recv(4096)
            if not chunk:
                break
            lines = chunk.decode("utf-8").split("\r\n")
            for line in lines:
                if not line.strip():
                    continue
                resp = json.loads(line)
                if "id" in resp and resp["id"] == 1:
                    s.close()
                    if "error" in resp:
                        return False, resp["error"]
                    return True, resp.get("result")
    except Exception as e:
        return False, str(e)
    finally:
        s.close()

def main():
    import os
    os.system('color') # Abilita colori su cmd di Windows
    
    # Prova a prendere host e port da config.toml se esiste
    host = "localhost"
    port = 4400
    try:
        from phd2_agent.config import load_config
        cfg = load_config("config.toml")
        host = cfg.phd2.host
        port = cfg.phd2.port
    except Exception:
        pass

    print(f"{Colors.BOLD}🔭 PHD2 Adaptive Agent - Diagnostica di Connessione{Colors.RESET}")
    print(f"Tentativo di connessione a {host}:{port}...")

    # 1. TEST CONNESSIONE
    print_step("1. Verifica Connessione PHD2")
    ok, result = manual_rpc(host, port, "get_app_state")
    if ok:
        print_result(True, "Connessione a PHD2 stabilita", f"(Stato: {result})")
    else:
        print_result(False, "Connessione a PHD2 fallita", f"(Errore: {result})")
        print(f"{Colors.YELLOW}Assicurati che PHD2 sia aperto e che in Tools -> Enable Server sia spuntato!{Colors.RESET}")
        input("\nPremi Invio per uscire...")
        return

    # 2. TEST CONFIGURAZIONE
    print_step("2. Lettura Configurazione Profilo")
    ok_ra, params_ra = manual_rpc(host, port, "get_algo_param_names", ["ra"])
    ok_dec, params_dec = manual_rpc(host, port, "get_algo_param_names", ["dec"])
    
    if ok_ra and ok_dec:
        print_result(True, "Configurazione di PHD2 letta con successo")
        print(f"    - Parametri asse RA : {params_ra}")
        print(f"    - Parametri asse Dec: {params_dec}")
    else:
        print_result(False, "Impossibile leggere la configurazione", f"(Errore: {params_ra or params_dec})")

    # 3. TEST INTERAZIONE
    print_step("3. Interazione e Scrittura")
    # Proviamo a leggere il valore attuale di Aggressiveness e scriverci sopra lo stesso valore
    # Cosi testiamo la scrittura senza cambiare nulla.
    param_to_test = None
    for p in ["Aggressiveness", "aggressiveness", "Hysteresis", "hysteresis", "Aggression", "aggression"]:
        if p in params_ra:
            param_to_test = p
            break
    
    if param_to_test:
        ok_read, current_val = manual_rpc(host, port, "get_algo_param", ["ra", param_to_test])
        if ok_read:
            # Provo a scrivere lo stesso valore!
            ok_write, write_res = manual_rpc(host, port, "set_algo_param", ["ra", param_to_test, current_val])
            if ok_write and write_res == 0:
                print_result(True, f"Interazione funzionante", f"(Letto e riscritto {param_to_test}: {current_val})")
            else:
                print_result(False, "Lettura OK, ma scrittura fallita", f"(Errore: {write_res})")
        else:
            print_result(False, f"Impossibile leggere parametro '{param_to_test}'", f"(Errore: {current_val})")
    else:
         print_result(False, "Non ho trovato un parametro valido per testare la scrittura.")

    print(f"\n{Colors.BOLD}Se vedi 3 Luci Verdi 🟢, il sistema è perfettamente funzionante!{Colors.RESET}")
    input("\nPremi Invio per chiudere questa finestra...")

if __name__ == "__main__":
    main()
