"""Avvio: python -m app [--porta 8765] [--host 127.0.0.1] [--no-browser]"""
import argparse
import socket
import threading
import time
import webbrowser

import uvicorn

from .main import crea_app


def porta_libera(host: str, porta: int) -> bool:
    with socket.socket() as s:
        return s.connect_ex((host if host != "0.0.0.0" else "127.0.0.1", porta)) != 0


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
    print(f"Comic Studio su {url}  (chiudi questa finestra o premi Ctrl+C per uscire)")
    if not a.no_browser:
        threading.Thread(target=lambda: (time.sleep(1.5), webbrowser.open(url)), daemon=True).start()
    host_consentiti = ["*"] if a.host not in ("127.0.0.1", "localhost") else None
    uvicorn.run(crea_app(host_consentiti=host_consentiti), host=a.host, port=a.porta, log_level="warning")


if __name__ == "__main__":
    main()
