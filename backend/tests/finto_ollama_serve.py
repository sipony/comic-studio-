"""Il programma `ollama serve` finto, per i test della gestione del processo (vedi test_ollama_processo.py).

Ascolta su OLLAMA_HOST con le stesse API del finto Ollama, scrive righe come quelle di Ollama (slog e [GIN]).
Il file «modo» accanto all'eseguibile cambia il comportamento:
  occupata   esce subito con l'errore di porta occupata
  blocca:<pid>   il processo con quel PID smette di rispondere (le richieste restano appese)
"""
from __future__ import annotations

import asyncio
import os
import sys
import time
from pathlib import Path


def riga(livello: str, msg: str):
    print(f'time={time.strftime("%Y-%m-%dT%H:%M:%S")} level={livello} source=routes.go:1 msg="{msg}"', flush=True)


def main():
    if len(sys.argv) < 2 or sys.argv[1] != "serve":
        print("ollama version is 0.40.11")
        return
    cartella = Path(sys.argv[0]).resolve().parent
    modo = (cartella / "modo").read_text().strip() if (cartella / "modo").exists() else ""
    host = os.environ.get("OLLAMA_HOST", "127.0.0.1:11434")
    if modo == "occupata":
        print(f"Error: listen tcp {host}: bind: address already in use", flush=True)
        sys.exit(1)
    import uvicorn
    from finto_ollama import FintoOllama
    f = FintoOllama()
    app = f.app

    @app.middleware("http")
    async def registro(req, chiama):
        m = (cartella / "modo").read_text().strip() if (cartella / "modo").exists() else ""
        if m == f"blocca:{os.getpid()}":
            await asyncio.sleep(3600)
        r = await chiama(req)
        print(f'[GIN] {time.strftime("%Y/%m/%d - %H:%M:%S")} | {r.status_code} | 1ms | 127.0.0.1 | '
              f'{req.method} "{req.url.path}"', flush=True)
        return r

    ip, porta = host.rsplit(":", 1)
    riga("INFO", f"Listening on {host} (version 0.40.11)")
    riga("WARN", "no compatible GPUs were discovered")
    uvicorn.run(app, host=ip, port=int(porta), log_level="error", timeout_graceful_shutdown=1)


if __name__ == "__main__":
    main()
