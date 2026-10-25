"""Avvio di Comic Studio su Windows, macOS e Linux.

Al primo avvio prepara tutto da solo; ai successivi controlla e aggiorna:
  1. ambiente Python dedicato (.venv) con le librerie del programma (aggiornate una volta al giorno)
  2. interfaccia compilata (frontend/dist); se manca o è vecchia la ricompila, se Node.js è installato
  3. avvia il server e apre il browser

Uso: python avvio.py [--porta 8765] [--host 0.0.0.0] [--no-browser] [--aggiorna]
"""
from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import sys
import time
import venv
from pathlib import Path

QUI = Path(__file__).resolve().parent
VENV = QUI / ".venv"
BACKEND = QUI / "backend"
FRONTEND = QUI / "frontend"
DIST = FRONTEND / "dist" / "comic-studio" / "browser"
REQ = BACKEND / "requirements.txt"
TIMBRO = VENV / ".comic-studio-librerie"
UN_GIORNO = 24 * 3600


def titolo(t: str):
    print(f"\n== {t}")


def esci(msg: str, codice: int = 1):
    print(f"\n*** {msg}\n")
    if os.name == "nt" and sys.stdin and sys.stdin.isatty():
        input("Premi INVIO per chiudere...")
    sys.exit(codice)


def python_venv() -> Path:
    return VENV / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def controlla_python():
    v = sys.version_info
    if v < (3, 10):
        esci(f"Serve Python 3.10 o più recente (trovato {v.major}.{v.minor}). Scaricalo da https://www.python.org/downloads/")


def prepara_ambiente(forza: bool):
    if not python_venv().exists():
        titolo("Creo l'ambiente Python del programma (solo la prima volta)")
        venv.EnvBuilder(with_pip=True, clear=VENV.exists()).create(VENV)
        forza = True
    impronta = hashlib.sha256(REQ.read_bytes()).hexdigest()
    try:
        vecchia, quando = TIMBRO.read_text().split()
        scaduto = time.time() - float(quando) > UN_GIORNO
    except (OSError, ValueError):
        vecchia, scaduto = "", True
    if not forza and vecchia == impronta and not scaduto:
        return
    titolo("Installo / aggiorno le librerie" if forza or vecchia != impronta else "Controllo gli aggiornamenti delle librerie")
    py = str(python_venv())
    subprocess.run([py, "-m", "pip", "install", "--disable-pip-version-check", "-q", "--upgrade", "pip"], check=False)
    r = subprocess.run([py, "-m", "pip", "install", "--disable-pip-version-check", "-q", "--upgrade", "-r", str(REQ)])
    if r.returncode != 0:
        if vecchia:   # c'era già un ambiente funzionante: si parte lo stesso
            print("   Aggiornamento delle librerie non riuscito (sei offline?): uso quelle già installate.")
            return
        esci("Installazione delle librerie non riuscita: controlla la connessione a internet e riprova.")
    TIMBRO.write_text(f"{impronta} {time.time()}")


def ultima_modifica(cartella: Path) -> float:
    m = 0.0
    for radice, cartelle, files in os.walk(cartella):
        cartelle[:] = [c for c in cartelle if c not in ("node_modules", "dist", ".angular")]
        for f in files:
            try:
                m = max(m, os.path.getmtime(os.path.join(radice, f)))
            except OSError:
                pass
    return m


def prepara_interfaccia(forza: bool):
    indice = DIST / "index.html"
    sorgenti = max(ultima_modifica(FRONTEND / "src"), (FRONTEND / "package.json").stat().st_mtime)
    aggiornata = indice.exists() and indice.stat().st_mtime >= sorgenti
    if aggiornata and not forza:
        return
    npm = shutil.which("npm")
    if not npm:
        if indice.exists():
            print("   Interfaccia non ricompilata (Node.js non installato): uso quella presente.")
            return
        esci("Manca l'interfaccia compilata e Node.js non è installato.\n"
             "    Installa Node.js LTS da https://nodejs.org (serve solo per compilarla) e rilancia,\n"
             "    oppure scarica la versione già pronta dalla pagina Actions/Releases del repository.")
    titolo("Compilo l'interfaccia (solo quando cambia: 1-2 minuti)")
    if not (FRONTEND / "node_modules").is_dir() or forza:
        r = subprocess.run([npm, "ci", "--no-audit", "--no-fund"], cwd=FRONTEND)
        if r.returncode != 0:
            esci("Installazione dei pacchetti dell'interfaccia non riuscita (npm ci).")
    r = subprocess.run([npm, "run", "build"], cwd=FRONTEND)
    if r.returncode != 0:
        esci("Compilazione dell'interfaccia non riuscita: guarda gli errori qui sopra.")


def main():
    argomenti = sys.argv[1:]
    forza = "--aggiorna" in argomenti
    argomenti = [a for a in argomenti if a != "--aggiorna"]
    print("Comic Studio — preparazione")
    controlla_python()
    prepara_ambiente(forza)
    prepara_interfaccia(forza)
    titolo("Avvio")
    try:
        r = subprocess.run([str(python_venv()), "-m", "app", *argomenti], cwd=BACKEND)
    except KeyboardInterrupt:
        r = None
    sys.exit(r.returncode if r else 0)


if __name__ == "__main__":
    main()
