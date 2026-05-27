import sys
import socket
import json

def manual_rpc(method, params=None):
    req = {"method": method, "id": 1, "jsonrpc": "2.0"}
    if params is not None:
        req["params"] = params
    
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(2.0)
    try:
        s.connect(("localhost", 4400))
        s.sendall((json.dumps(req) + "\r\n").encode("utf-8"))
        while True:
            chunk = s.recv(4096)
            if not chunk: break
            for line in chunk.decode("utf-8").split("\r\n"):
                if not line.strip(): continue
                resp = json.loads(line)
                if "id" in resp and resp["id"] == 1:
                    s.close()
                    print(f"Result for {method}: {resp}")
                    return
    except Exception as e:
        print(f"Failed {method}: {e}")

manual_rpc("get_exposure")
manual_rpc("get_exposure_durations")
