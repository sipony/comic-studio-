"""Avvio: python -m app [--porta 8765] [--host 127.0.0.1] [--no-browser]"""
import argparse
import json
import socket
import threading
import time
import urllib.request
import webbrowser

import uvicorn

from .main import crea_app


def porta_libera(host: str, porta: int) -> bool:
    with socket.socket() as s:
        return s.connect_ex((host if host != "0.0.0.0" else "127.0.0.1", porta)) != 0


def e_comic_studio(porta: int) -> bool:
    """Sulla porta risponde già Comic Studio (e non un altro programma)?"""
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{porta}/api/sistema", timeout=2) as r:
            return "versione" in json.loads(r.read().decode("utf-8"))
    except Exception:  # noqa: BLE001
        return False


def servi(host: str, porta: int, apri_browser: bool):
    """Avvia il server; l'interfaccia può chiuderlo con «Esci» (POST /api/esci)."""
    url = f"http://127.0.0.1:{porta}"
    host_consentiti = ["*"] if host not in ("127.0.0.1", "localhost") else None
    api = crea_app(host_consentiti=host_consentiti)
    server = uvicorn.Server(uvicorn.Config(api, host=host, port=porta, log_level="warning"))
    api.state.spegni = lambda: setattr(server, "should_exit", True)

    def apri():
        for _ in range(100):           # appena il server risponde
            if server.started:
                webbrowser.open(url)
                return
            time.sleep(0.1)

    if apri_browser:
        threading.Thread(target=apri, daemon=True).start()
    server.run()


def main():
    ap = argparse.ArgumentParser(prog="comic-studio", description="Comic Studio")
    ap.add_argument("--host", default="127.0.0.1",
                    help="0.0.0.0 per usarlo da altri computer della rete (nessuna password: solo in reti fidate)")
    ap.add_argument("--porta", type=int, default=8765)
    ap.add_argument("--no-browser", action="store_true", help="non aprire il browser")
    a = ap.parse_args()

    url = f"http://127.0.0.1:{a.porta}"
    if not porta_libera(a.host, a.porta):
        print(f"Comic Studio sembra già avviato: apro {url}")
        if not a.no_browser:
            webbrowser.open(url)
        return

    if a.host == "0.0.0.0":
        print("ATTENZIONE: Comic Studio è raggiungibile da tutta la rete locale, senza password.")
    print(f"Comic Studio su {url}  (chiudi questa finestra, premi Ctrl+C o usa «Esci» nell'interfaccia)")
    servi(a.host, a.porta, not a.no_browser)


if __name__ == "__main__":
    main()
